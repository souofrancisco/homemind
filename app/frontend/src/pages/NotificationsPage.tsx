import { Alert, Badge, Button, Card, Group, Loader, Select, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import ManualControls from "../components/notifications/ManualControls";
import { getMembers, type MemberView } from "../services/households/api";
import {
  listNotifications, markNotificationRead, respondToNotification, type NotificationView,
} from "../services/notifications/api";

const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeStyle: "short" });
const statusLabel: Record<NotificationView["status"], string> = {
  unread: "Por ler", read: "Lida", actioned: "Respondida", expired: "Expirada", dismissed: "Dispensada",
};
// Aviso de regra da casa (SAFE-04): fica `expired` quando a votação fecha (aprovada, rejeitada
// ou por prazo), por isso não é «prazo de confirmação de aparelho».
const isRule = (n: NotificationView) => n.kind === "automation_proposal";
const severityColor = { info: "blue", warning: "orange", critical: "red" } as const;
const verdictLabel: Record<NonNullable<NotificationView["voting"]>["verdict"], string> = {
  pending: "Votação em curso — ainda não há decisão",
  self_claimed: "Decidido: assumido por quem o usou",
  accusation_accepted: "Decidido por votação",
  everyone: "Decidido: dividido por todos",
};
// A ação «É de outra pessoa» exige indicar a pessoa (contrato D-32): id fixado pelo backend.
const OTHER = "other";

function Card1({ n, householdId, members, onChange }: {
  n: NotificationView; householdId: string; members: MemberView[]; onChange: (v: NotificationView) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const act = async (fn: () => Promise<NotificationView>) => {
    setBusy(true);
    try { onChange(await fn()); } catch { /* o cliente HTTP mostra o erro (ex.: já votaste) */ } finally { setBusy(false); }
  };
  const respond = (actionId: string, targetId?: string) =>
    act(() => respondToNotification(householdId, n.id, { action_id: actionId, target_resident_id: targetId ?? null }));
  const canAct = n.can_respond && (n.status === "unread" || n.status === "read");
  const v = n.voting;

  return (
    <Card withBorder radius="lg" p="lg" component="article" aria-label={n.title}>
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Title order={3} size="h4">{n.title}</Title>
          <Group gap="xs">
            <Badge color={severityColor[n.severity]} variant="light">{isRule(n) && n.status === "expired" ? "Votação encerrada" : statusLabel[n.status]}</Badge>
            {n.kind === "presence_check" && <Badge color="indigo" variant="light">Presença</Badge>}
            <Badge color={n.origin === "simulated" ? "orange" : "teal"} variant="light">{n.origin === "simulated" ? "SIMULADO" : "REAL"}</Badge>
          </Group>
        </Group>
        <Text>{n.body}</Text>
        {n.kind === "presence_check" && <Text size="sm" c="dimmed">Sem câmara, a tua resposta é a forma de confirmar a presença. É uma pergunta, não uma acusação; só tu a vês.</Text>}
        {v && (
          <Alert color={v.verdict === "pending" ? "blue" : "gray"} variant="light" title={verdictLabel[v.verdict]}>
            {v.votes} de {v.eligible} votos (decide-se com {v.votes_needed}).
            {v.my_vote ? " O teu voto está registado; podes vê-lo mas não alterá-lo." : ""}
            {v.verdict !== "pending" && (v.pays_me ? " Esta utilização fica a teu cargo." : " Esta utilização não fica a teu cargo.")}
          </Alert>
        )}
        <div role="status" aria-live="polite">{n.response && !v && <Text size="sm" c="dimmed">Respondeste {when.format(new Date(n.response.responded_at))}.</Text>}</div>
        {canAct && !picking && (
          <Group gap="xs">
            {n.actions.map((a) => (
              <Button key={a.id} size="sm" aria-label={`${a.label}: ${n.title}`} loading={busy} variant={a.style === "primary" ? "filled" : "light"} color={a.style === "danger" ? "red" : undefined}
                onClick={() => (a.id === OTHER ? setPicking(true) : void respond(a.id))}>{a.label}</Button>
            ))}
            {n.status === "unread" && <Button size="sm" variant="subtle" loading={busy} onClick={() => void act(() => markNotificationRead(householdId, n.id))}>Marcar como lida</Button>}
          </Group>
        )}
        {canAct && picking && (
          <Group align="end">
            <Select label="De quem é?" placeholder="Escolhe uma pessoa" data={members.map((m) => ({ value: m.resident_id, label: m.display_name }))} value={target} onChange={setTarget} />
            <Button disabled={!target} loading={busy} onClick={() => void respond(OTHER, target ?? undefined)}>Confirmar</Button>
            <Button variant="subtle" onClick={() => setPicking(false)}>Cancelar</Button>
          </Group>
        )}
        {!canAct && n.status === "expired" && (isRule(n)
          ? <Text size="sm" c="dimmed">A votação desta regra já terminou. O resultado está em «Regras da casa».</Text>
          : <Text size="sm" c="dimmed">O prazo terminou; sem resposta, a utilização divide-se por todos.</Text>)}
        <Text size="xs" c="dimmed">{n.scope === "personal" ? "Pessoal" : "Da casa"} · {when.format(new Date(n.created_at))}{n.expires_at && n.status !== "expired" ? ` · responder até ${when.format(new Date(n.expires_at))}` : ""}</Text>
      </Stack>
    </Card>
  );
}

export default function NotificationsContent() {
  const session = useHouseholdSession();
  const householdId = session.membership?.household_id;
  const [state, setState] = useState<{ key: string; items: NotificationView[] | null; members: MemberView[] } | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!householdId) return;
    let active = true;
    Promise.all([listNotifications(householdId), session.membership?.role === "tenant" ? getMembers(householdId) : Promise.resolve([])])
      .then(([items, members]) => active && setState({ key: householdId, items, members }))
      .catch(() => active && setState({ key: householdId, items: null, members: [] }));
    return () => { active = false; };
  }, [householdId, reload, session.membership?.role]);

  if (!householdId) return null;
  const cur = state?.key === householdId ? state : null;
  if (!cur) return <Group role="status"><Loader size="sm" /><Text>A carregar notificações…</Text></Group>;
  if (!cur.items) return (
    <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar as notificações">
      <Button w="fit-content" color="red" variant="light" onClick={() => setReload((n) => n + 1)}>Tentar novamente</Button>
    </Alert>
  );
  const tenant = session.membership?.role === "tenant";
  if (!cur.items.length) return (
    <Stack gap="md">
      <Text c="dimmed">Sem notificações. Quando houver uma utilização a confirmar ou um aviso de orçamento, aparece aqui.</Text>
      {tenant && <ManualControls householdId={householdId} />}
    </Stack>
  );
  const replace = (v: NotificationView) => setState({ ...cur, items: cur.items!.map((i) => (i.id === v.id ? v : i)) });
  return (
    <Stack gap="md">
      {cur.items.map((n) => <Card1 key={n.id} n={n} householdId={householdId} members={cur.members} onChange={replace} />)}
      {tenant && <ManualControls householdId={householdId} />}
    </Stack>
  );
}
