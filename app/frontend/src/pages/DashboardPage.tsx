import { Alert, Anchor, Badge, Card, Progress, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { usePolling } from "../hooks/usePolling";
import { getMyBudget } from "../services/billing/budget";
import { listNotifications } from "../services/notifications/api";
import { getMembers, type MemberView } from "../services/households/api";
import { euro, MeterCard, SessionRow, StatCard, useEnergy, visibleMeters } from "./EnergyPage";
import { NOTIFICATIONS_CHANGED } from "../components/layout/NotificationBell";
import { NotificationCard } from "./NotificationsPage";

const ALERT_KINDS = new Set(["budget_alert", "peak_alert", "security_alert", "comfort_alert"]);

/** Dashboard do morador: só junta o que o servidor já calculou; "Sem dados" quando falta. */
export default function Dashboard() {
  const session = useHouseholdSession();
  const id = session.membership?.household_id;
  const { energy, appliances } = useEnergy();
  const budget = usePolling(id, getMyBudget, 60000);
  const notes = usePolling(id, listNotifications, 30000);
  const [members, setMembers] = useState<MemberView[]>([]);
  useEffect(() => {
    if (!id || session.membership?.role !== "tenant") return;
    let active = true;
    void getMembers(id).then((all) => active && setMembers(all.filter((m) => m.role === "tenant" && m.status === "active" && m.membership_id !== session.membership?.id))).catch(() => active && setMembers([]));
    return () => { active = false; };
  }, [id, session.membership?.id, session.membership?.role]);
  const reloadNotes = notes.reload;
  useEffect(() => {
    window.addEventListener(NOTIFICATIONS_CHANGED, reloadNotes);
    return () => window.removeEventListener(NOTIFICATIONS_CHANGED, reloadNotes);
  }, [reloadNotes]);
  const o = energy.data;
  const sessions = o?.sessions ?? [];
  const unidentified = sessions.filter((s) => s.appliance_id == null).length;
  const pending = (notes.data ?? []).filter((n) => n.kind === "confirmation_request" && n.can_respond && (n.status === "unread" || n.status === "read"));
  const alerts = (notes.data ?? []).filter((n) => ALERT_KINDS.has(n.kind)).slice(0, 3);
  const b = budget.data;
  const pendingVote = pending.find((n) => n.kind === "confirmation_request");
  const meters = o ? visibleMeters(o.meters, o.now) : [];
  const limit = b?.budget?.limit_cents ?? null;

  return (
    <Stack gap={28}>
      {(energy.offline || notes.offline) && <Alert color="yellow" title="Sem ligação — a mostrar os últimos dados recebidos" />}
      {pendingVote && id && <Stack gap="xs">
        <NotificationCard n={pendingVote} householdId={id} members={members} onChange={() => notes.reload()} />
        {pending.length > 1 && <Text size="sm" c="dimmed">+ {pending.length - 1} por responder em <Anchor component={Link} to="/notificacoes" c="inherit">Notificações</Anchor></Text>}
      </Stack>}
      <SimpleGrid cols={{ base: 2, md: 3 }} spacing={{ base: "sm", md: 20 }}>
        <StatCard label="Este mês" value={!b ? "Sem dados" : b.spent_cents == null ? "Desconhecido" : euro(b.spent_cents)}
          caption={b?.forecast ? `previsão de ${euro(b.forecast.cents)} no fim do mês` : "até agora"} />
        <StatCard className="conta-stat-wide" label={limit ? `Orçamento de ${euro(limit)}` : "Orçamento"}
          value={!b ? "Sem dados" : !limit ? "Sem orçamento" : b.pct == null ? "Desconhecido" : `${b.pct} %`} small={!limit}
          caption={!b || limit ? undefined : <Anchor component={Link} to="/contas" c="inherit">Definir em Contas</Anchor>}>
          {limit != null && b?.pct != null && <Progress color="ink" size={8} mt="sm" value={Math.min(b.pct, 100)} aria-label="Percentagem do orçamento utilizada" />}
        </StatCard>
        {energy.loading ? <StatCard label="Agora, na tomada da sala" value="…" caption="a carregar leituras" />
          : meters.length === 0 ? <StatCard label="Agora, na tomada da sala" value="Sem dados" small caption="ainda não há leituras de energia desta casa" />
            : <MeterCard m={meters[0]} now={o!.now} />}
      </SimpleGrid>
      {meters.length > 1 && <SimpleGrid cols={{ base: 2, md: 3 }} spacing={{ base: "sm", md: 20 }}>{meters.slice(1).map((m) => <MeterCard key={m.device_id} m={m} now={o!.now} />)}</SimpleGrid>}
      {meters.length > 0 && <Text size="sm" c="dimmed" mt={-12}>A tomada mede só o que está ligado a ela, não a casa toda.</Text>}
      <Card p="md" px={{ base: "md", sm: 24 }}>
        <div className="conta-list-head">
          <Title order={2} size={18}>Últimas utilizações</Title>
          {unidentified > 0 && <Badge>{unidentified} por identificar</Badge>}
        </div>
        {sessions.length === 0 ? <Text c="dimmed" py="md">Sem sessões detetadas.</Text>
          : sessions.slice(0, 3).map((s) => <SessionRow key={s.id} s={s} appliances={appliances} />)}
      </Card>
      {alerts.length > 0 && <Card p="lg">
        <Stack gap="xs">
          <Title order={2} size={18}>Alertas recentes</Title>
          {alerts.map((n) => <Text key={n.id} size="sm"><b>{n.title}</b> — {n.body}</Text>)}
        </Stack>
      </Card>}
    </Stack>
  );
}
