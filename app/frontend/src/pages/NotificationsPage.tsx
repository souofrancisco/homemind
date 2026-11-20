import { Alert, Badge, Button, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
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
// Aviso de regra da casa (SAFE-04): fica `expired` quando a votação fecha (aprovada, rejeitada
// ou por prazo), por isso não é «prazo de confirmação de aparelho».
const isRule = (n: NotificationView) => n.kind === "automation_proposal";
const severityColor = { info: "gray", warning: "orange", critical: "red" } as const;
const verdictLabel: Record<NonNullable<NotificationView["voting"]>["verdict"], string> = {
  pending: "Votação em curso — ainda não há decisão",
  self_claimed: "Decidido: assumido por quem o usou",
  accusation_accepted: "Decidido por votação",
  everyone: "Decidido: dividido por todos",
};
// «Escolher responsável(eis)» exige indicar as pessoas (contrato D-32): id fixado pelo backend.
const OTHER = "other";

/** Escolha do grupo que paga: uma ou mais pessoas, incluindo quem vota (D-32). Só a própria
 *  pessoa equivale a «É minha»; com mais alguém é preciso que metade da casa escolha o mesmo. */
function ResponsiblePicker({ members, selfId, busy, onConfirm, onCancel }: {
  members: MemberView[]; selfId: string | undefined; busy: boolean;
  onConfirm: (ids: string[]) => void; onCancel: () => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const people = [...members].sort((a, b) => Number(b.resident_id === selfId) - Number(a.resident_id === selfId));
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const onlyMe = picked.length === 1 && picked[0] === selfId;
  const needed = Math.max(1, Math.ceil(members.length / 2));
  const names = people.filter((m) => picked.includes(m.resident_id)).map((m) => (m.resident_id === selfId ? "tu" : m.display_name));
  const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} e ${names[names.length - 1]}` : names[0];
  return (
    <Stack gap="sm" className="conta-picker">
      <Group justify="space-between" align="center" wrap="wrap">
        <Title order={4} size={18}>Escolher responsável(eis)</Title>
        <Button variant="subtle" color="ink" mih={44} onClick={() => setPicked(people.map((m) => m.resident_id))}>Toda a casa</Button>
      </Group>
      <Text size="sm" c="dimmed" mt={-8}>Escolhe uma ou mais pessoas.</Text>
      <Group gap="xs">
        {people.map((m) => {
          const on = picked.includes(m.resident_id);
          return <Button key={m.resident_id} size="md" mih={48} radius="xl" variant={on ? "filled" : "default"} aria-pressed={on}
            onClick={() => toggle(m.resident_id)}>{m.resident_id === selfId ? `Eu (${m.display_name})` : m.display_name}</Button>;
        })}
      </Group>
      <div className="conta-picker-summary" role="status" aria-live="polite">
        <Text fw={700}>{!picked.length ? "Ainda não escolheste ninguém" : onlyMe ? "Fica a teu cargo" : "Precisa de quórum"}</Text>
        <Text size="sm" c="dimmed">{!picked.length ? "Escolhe pelo menos uma pessoa para votar."
          : onlyMe ? "Só tu estás escolhido: decide logo, como «É minha»."
            : `A conta fica com ${list} quando pelo menos metade da casa (${needed} de ${members.length}) escolher exatamente as mesmas pessoas. Sem quórum em 24 h, divide-se por todos.`}</Text>
      </div>
      <Group justify="flex-end" gap="xs">
        <Button variant="default" mih={48} onClick={onCancel}>Cancelar</Button>
        <Button mih={48} disabled={!picked.length} loading={busy} onClick={() => onConfirm(picked)}>Confirmar voto</Button>
      </Group>
    </Stack>
  );
}

export function NotificationCard({ n, householdId, members, onChange }: {
  n: NotificationView; householdId: string; members: MemberView[]; onChange: (v: NotificationView) => void;
}) {
  const session = useHouseholdSession();
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const selfId = members.find((m) => m.membership_id === session.membership?.id)?.resident_id;
  const act = async (fn: () => Promise<NotificationView>) => {
    setBusy(true);
    try { onChange(await fn()); } catch { /* o cliente HTTP mostra o erro (ex.: já votaste) */ } finally { setBusy(false); }
  };
  const respond = (actionId: string, targets: string[] = []) =>
    act(() => respondToNotification(householdId, n.id, { action_id: actionId, target_resident_ids: targets }));
  // Só a própria pessoa escolhida é «É minha» (o contrato recusa `other` só com quem vota).
  const respondGroup = (ids: string[]) => (ids.length === 1 && ids[0] === selfId ? respond("mine") : respond(OTHER, ids));
  const canAct = n.can_respond && (n.status === "unread" || n.status === "read");
  const v = n.voting;
  const isVote = v?.verdict === "pending" && canAct;
  // Grupo decidido por votação (D-32): o que chegou ao quórum.
  const groupSize = v?.verdict === "accusation_accepted"
    ? v.accusations.find((a) => a.votes >= v.votes_needed)?.target_resident_ids.length ?? 1 : 1;

  return (
    <Card id={n.kind === "confirmation_request" ? `confirmation-vote-${n.id}` : undefined} p={{ base: "md", sm: 28 }} component="article" aria-label={n.title}>
      <div className="conta-vote" data-vote={isVote ? "true" : "false"} data-picking={picking ? "true" : "false"}>
      <Stack gap="sm">
        {isVote && v ? <>
          <Group gap="xs"><Badge className="conta-pending-badge">Falta a tua resposta · {v.votes} de {v.eligible} já votaram</Badge>
            <OriginBadge origin={n.origin} demo={session.house?.source_kind === "demo"} /></Group>
          <Title order={3} className="conta-vote-title">{n.title}</Title>
        </> : (
          <Group justify="space-between" align="flex-start" wrap="wrap">
            <Title order={3} size={18}>{n.title}</Title>
            <Group gap="xs">
              <Badge color={severityColor[n.severity]} variant="light">{isRule(n) && n.status === "expired" ? "Votação encerrada" : statusLabel[n.status]}</Badge>
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
            {v.verdict !== "pending" && (!v.pays_me ? " Esta utilização não fica a teu cargo."
              : groupSize > 1 ? ` Esta utilização divide-se por igual entre ti e mais ${groupSize - 1} ${groupSize === 2 ? "pessoa" : "pessoas"}.`
                : " Esta utilização fica a teu cargo.")}
          </Alert>
        )}
        <div role="status" aria-live="polite">{n.response && !v && <Text size="sm" c="dimmed">Respondeste {when.format(new Date(n.response.responded_at))}.</Text>}</div>
        <Text size="xs" c="dimmed">{n.scope === "personal" ? "Pessoal" : "Da casa"} · {when.format(new Date(n.created_at))}{n.expires_at && n.status !== "expired" ? ` · responder até ${when.format(new Date(n.expires_at))}` : ""}</Text>
      </Stack>
      {canAct && <Stack gap="xs" w="100%">
        {!picking && (
          <div className="conta-vote-actions">
            {n.actions.map((a) => {
              const consequence: Record<string, string> = { mine: "Pagas tu. Decide logo.", everyone: "Dividido por todos os moradores.", other: "Escolhes uma ou mais pessoas. Para valer, metade dos moradores tem de escolher exatamente as mesmas.", unknown: "Fica em aberto. Sem decisão em 24 h, divide-se por todos." };
              const emphasized = a.style === "primary";
              return <Button key={a.id} className={emphasized || n.kind === "confirmation_request" ? "conta-vote-wide" : undefined} size="md" fullWidth mih={emphasized ? 52 : 48} fw={emphasized ? 700 : 600}
                title={consequence[a.id]} aria-label={consequence[a.id] ? `${a.label}. ${consequence[a.id]}` : `${a.label}: ${n.title}`} loading={busy}
                variant={emphasized ? "filled" : "default"} color={a.style === "danger" ? "red" : undefined}
                onClick={() => (a.id === OTHER ? setPicking(true) : void respond(a.id))}>{a.label}</Button>;
            })}
            {n.status === "unread" && n.kind !== "confirmation_request" && <Button size="md" mih={48} variant="default" loading={busy} onClick={() => void act(() => markNotificationRead(householdId, n.id))}>Marcar como lida</Button>}
          </div>
        )}
        {picking && <ResponsiblePicker members={members} selfId={selfId} busy={busy}
          onConfirm={(ids) => void respondGroup(ids)} onCancel={() => setPicking(false)} />}
      </Stack>}
      {!canAct && n.status === "expired" && <Text size="sm" c="dimmed">{isRule(n)
        ? "A votação desta regra já terminou. O resultado está em «Regras da casa»."
        : n.kind === "confirmation_request"
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
        // «Escolher responsável(eis)» só aponta para inquilinos ativos (incluindo a própria
        // pessoa, num grupo): nunca o senhorio nem o operador.
        const members = all.filter((m) => m.role === "tenant" && m.status === "active");
        if (active) setState({ key: householdId, items, members });
      })
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
      {cur.items.map((n) => <NotificationCard key={n.id} n={n} householdId={householdId} members={cur.members} onChange={replace} />)}
      {tenant && <ManualControls householdId={householdId} />}
    </Stack>
  );
}
