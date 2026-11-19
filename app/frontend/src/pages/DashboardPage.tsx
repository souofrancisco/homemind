import { Alert, Badge, Card, Group, Progress, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { usePolling } from "../hooks/usePolling";
import { getMyBudget } from "../services/billing/budget";
import { listNotifications } from "../services/notifications/api";
import { getMembers, type MemberView } from "../services/households/api";
import { MeterCard, SessionRow, useEnergy, visibleMeters } from "./EnergyPage";
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
  const o = energy.data;
  const sessions = o?.sessions ?? [];
  const unidentified = sessions.filter((s) => s.appliance_id == null).length;
  const pending = (notes.data ?? []).filter((n) => n.kind === "confirmation_request" && n.can_respond && (n.status === "unread" || n.status === "read"));
  const alerts = (notes.data ?? []).filter((n) => ALERT_KINDS.has(n.kind)).slice(0, 3);
  const b = budget.data;
  const pendingVote = pending.find((n) => n.kind === "confirmation_request");

  return (
    <Stack gap="lg">
      {(energy.offline || notes.offline) && <Alert color="yellow" title="Sem ligação — a mostrar os últimos dados recebidos" />}
      {pendingVote && id && <>
        {pending.length > 1 && <Alert color="indigo" title={`Falta a tua resposta: ${pending.length} contas por atribuir`}>Responde a uma de cada vez; as outras estão em Notificações.</Alert>}
        <NotificationCard n={pendingVote} householdId={id} members={members} onChange={() => notes.reload()} />
      </>}
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Stack gap="xs">
          {energy.loading ? <Text c="dimmed">A carregar leituras…</Text>
            : !o || o.meters.length === 0 ? <Card withBorder radius="lg" p="lg"><Text fw={700}>Sem dados</Text><Text size="sm" c="dimmed">Ainda não há leituras de energia desta casa.</Text></Card>
            : visibleMeters(o.meters, o.now).map((m) => <MeterCard key={m.device_id} m={m} now={o.now} />)}
          {!energy.loading && (o?.meters.length ?? 0) > 0 && <Text size="sm" c="dimmed">A tomada mede só o que está ligado a ela, não a casa toda.</Text>}
        </Stack>
        <Card withBorder radius="lg" p="lg">
          <Stack gap="xs">
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>O meu orçamento</Text>
            {!b ? <Text fw={700}>Sem dados</Text> : !b.budget?.limit_cents ? <Text c="dimmed">Sem orçamento definido este mês.</Text> : (
              <>
                <Text fz={28} fw={700}>{b.pct == null ? "Desconhecido" : `${b.pct} %`}</Text>
                <Progress value={Math.min(b.pct ?? 0, 100)} aria-label="Percentagem do orçamento utilizada" />
              </>
            )}
            <Text size="sm" c="dimmed">Consulta o separador Este mês em Contas.</Text>
          </Stack>
        </Card>
      </SimpleGrid>
      <Card withBorder radius="lg" p="lg">
        <Stack gap="md">
          <Group justify="space-between"><Title order={3} size="h4">Consumos recentes</Title>
            {unidentified > 0 && <Badge color="gray" variant="light">{unidentified} por identificar</Badge>}</Group>
          {sessions.length === 0 ? <Text c="dimmed">Sem sessões detetadas.</Text>
            : sessions.slice(0, 3).map((s) => <SessionRow key={s.id} s={s} appliances={appliances} />)}
        </Stack>
      </Card>
      {alerts.length > 0 && <Card withBorder radius="lg" p="lg">
        <Stack gap="xs">
          <Title order={3} size="h4">Alertas recentes</Title>
          {alerts.map((n) => <Text key={n.id} size="sm"><b>{n.title}</b> — {n.body}</Text>)}
        </Stack>
      </Card>}
    </Stack>
  );
}
