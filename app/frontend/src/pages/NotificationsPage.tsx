import { Alert, Badge, Button, Card, Group, Loader, Select, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import ManualControls from "../components/notifications/ManualControls";
import OriginBadge from "../components/common/OriginBadge";
import { getMembers, type MemberView } from "../services/households/api";
import {
  listNotifications, markNotificationRead, respondToNotification, type NotificationView,
} from "../services/notifications/api";

const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeStyle: "short" });
const statusLabel: Record<NotificationView["status"], string> = {
  unread: "Por ler", read: "Lida", actioned: "Respondida", expired: "Expirada", dismissed: "Dispensada",
};
const severityColor = { info: "gray", warning: "orange", critical: "red" } as const;
const verdictLabel: Record<NonNullable<NotificationView["voting"]>["verdict"], string> = {
  pending: "Votação em curso — ainda não há decisão",
  self_claimed: "Decidido: assumido por quem o usou",
  accusation_accepted: "Decidido por votação",
  everyone: "Decidido: dividido por todos",
};
// A ação «É de outra pessoa» exige indicar a pessoa (contrato D-32): id fixado pelo backend.
const OTHER = "other";

export function NotificationCard({ n, householdId, members, onChange }: {
  n: NotificationView; householdId: string; members: MemberView[]; onChange: (v: NotificationView) => void;
}) {
  const session = useHouseholdSession();
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
  const isVote = v?.verdict === "pending" && canAct;

  return (
    <Card id={n.kind === "confirmation_request" ? `confirmation-vote-${n.id}` : undefined} p={{ base: "md", sm: 28 }} component="article" aria-label={n.title}>
      <div className="conta-vote" data-vote={isVote ? "true" : "false"}>
      <Stack gap="sm">
        {isVote && v ? <>
          <Group gap="xs"><Badge className="conta-pending-badge">Falta a tua resposta · {v.votes} de {v.eligible} já votaram</Badge>
            <OriginBadge origin={n.origin} demo={session.house?.source_kind === "demo"} /></Group>
          <Title order={3} className="conta-vote-title">{n.title}</Title>
        </> : (
          <Group justify="space-between" align="flex-start" wrap="wrap">
            <Title order={3} size={18}>{n.title}</Title>
            <Group gap="xs">
              <Badge color={severityColor[n.severity]} variant="light">{statusLabel[n.status]}</Badge>
              {n.kind === "presence_check" && <Badge color="gray" variant="light">Presença</Badge>}
              <OriginBadge origin={n.origin} demo={session.house?.source_kind === "demo"} />
            </Group>
          </Group>
        )}
        <Text fz={isVote ? 16 : undefined} c={isVote ? "dimmed" : undefined}>{n.body}</Text>
        {n.kind === "presence_check" && <Text size="sm" c="dimmed">Sem câmara, a tua resposta é a forma de confirmar a presença. É uma pergunta, não uma acusação; só tu a vês.</Text>}
        {v && !isVote && (
          <Alert className={v.verdict === "pending" ? "conta-pending" : undefined} color={v.verdict === "pending" ? "orange" : "gray"} variant="light" title={verdictLabel[v.verdict]}>
            {v.votes} de {v.eligible} votos (decide-se com {v.votes_needed}).
            {v.my_vote ? " O teu voto está registado; podes vê-lo mas não alterá-lo." : ""}
            {v.verdict !== "pending" && (v.pays_me ? " Esta utilização fica a teu cargo." : " Esta utilização não fica a teu cargo.")}
          </Alert>
        )}
        {n.kind === "confirmation_request" && canAct && <Text size="sm" c="dimmed">O voto não se pode mudar. Se te enganares, podes contestar o recibo depois de o mês fechar.</Text>}
        <div role="status" aria-live="polite">{n.response && !v && <Text size="sm" c="dimmed">Respondeste {when.format(new Date(n.response.responded_at))}.</Text>}</div>
        <Text size="xs" c="dimmed">{n.scope === "personal" ? "Pessoal" : "Da casa"} · {when.format(new Date(n.created_at))}{n.expires_at && n.status !== "expired" ? ` · responder até ${when.format(new Date(n.expires_at))}` : ""}</Text>
      </Stack>
      {canAct && <Stack gap="xs" w="100%">
        {!picking && (
          <div className="conta-vote-actions">
            {n.actions.map((a) => {
              const consequence: Record<string, string> = { mine: "Pagas tu. Decide logo.", everyone: "Dividido por todos os moradores.", other: "Escolhes quem. Para valer, metade dos moradores tem de concordar.", unknown: "Fica em aberto. Sem decisão em 24 h, divide-se por todos." };
              const emphasized = a.style === "primary";
              return <Button key={a.id} className={emphasized || a.id === OTHER ? "conta-vote-wide" : undefined} size="md" fullWidth mih={emphasized ? 52 : 48} fw={emphasized ? 700 : 600}
                title={consequence[a.id]} aria-label={consequence[a.id] ? `${a.label}. ${consequence[a.id]}` : `${a.label}: ${n.title}`} loading={busy}
                variant={emphasized ? "filled" : "default"} color={a.style === "danger" ? "red" : undefined}
                onClick={() => (a.id === OTHER ? setPicking(true) : void respond(a.id))}>{a.label}</Button>;
            })}
            {n.status === "unread" && n.kind !== "confirmation_request" && <Button size="md" mih={48} variant="default" loading={busy} onClick={() => void act(() => markNotificationRead(householdId, n.id))}>Marcar como lida</Button>}
          </div>
        )}
        {picking && (
          <Group align="end">
            <Select label="De quem é?" placeholder="Escolhe uma pessoa" data={members.map((m) => ({ value: m.resident_id, label: m.display_name }))} value={target} onChange={setTarget} />
            <Button disabled={!target} loading={busy} onClick={() => void respond(OTHER, target ?? undefined)}>Confirmar</Button>
            <Button variant="subtle" onClick={() => setPicking(false)}>Cancelar</Button>
          </Group>
        )}
      </Stack>}
      {!canAct && n.status === "expired" && <Text size="sm" c="dimmed">{n.kind === "confirmation_request"
        ? "O prazo terminou; sem resposta, a utilização divide-se por todos."
        : "O prazo terminou sem resposta; nada foi executado."}</Text>}
      </div>
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
      .then(([items, all]) => {
        // «É de outra pessoa» só pode apontar para os outros inquilinos ativos: nem o senhorio,
        // nem o operador, nem a própria pessoa (para isso há «É minha»).
        const members = all.filter(
          (m) => m.role === "tenant" && m.status === "active" && m.membership_id !== session.membership?.id,
        );
        if (active) setState({ key: householdId, items, members });
      })
      .catch(() => active && setState({ key: householdId, items: null, members: [] }));
    return () => { active = false; };
  }, [householdId, reload, session.membership?.role, session.membership?.id]);

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
      {cur.items.map((n) => <NotificationCard key={n.id} n={n} householdId={householdId} members={cur.members} onChange={replace} />)}
      {tenant && <ManualControls householdId={householdId} />}
    </Stack>
  );
}
