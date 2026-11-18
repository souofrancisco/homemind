import { Alert, Badge, Button, Card, Group, Progress, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router-dom";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { usePolling } from "../hooks/usePolling";
import { getMyBudget } from "../services/billing/budget";
import { listNotifications } from "../services/notifications/api";
import { MeterCard, SessionRow, useEnergy } from "./EnergyPage";

const ALERT_KINDS = new Set(["budget_alert", "peak_alert", "security_alert", "comfort_alert"]);

/** Dashboard do morador: só junta o que o servidor já calculou; "Sem dados" quando falta. */
export default function Dashboard() {
  const session = useHouseholdSession();
  const id = session.membership?.household_id;
  const { energy, appliances } = useEnergy();
  const budget = usePolling(id, getMyBudget, 60000);
  const notes = usePolling(id, listNotifications, 30000);
  const o = energy.data;
  const sessions = o?.sessions ?? [];
  const unidentified = sessions.filter((s) => s.appliance_id == null).length;
  const pending = (notes.data ?? []).filter((n) => n.can_respond && (n.status === "unread" || n.status === "read"));
  const alerts = (notes.data ?? []).filter((n) => ALERT_KINDS.has(n.kind)).slice(0, 3);
  const b = budget.data;
  const maxPeak = Math.max(0, ...sessions.map((s) => s.peak_w));

  return (
    <Stack gap="lg">
      {(energy.offline || notes.offline) && <Alert color="yellow" title="Sem ligação ao servidor — a mostrar os últimos dados recebidos" />}
      <Group justify="space-between" wrap="wrap">
        <Title order={3}>{session.house?.name ?? "A tua casa"}</Title>
        <Badge variant="light" color={session.house?.source_kind === "real" ? "teal" : "orange"}>{session.house?.source_kind === "real" ? "REAL" : "SIMULADO"}</Badge>
      </Group>
      {pending.length > 0 && (
        <Alert color="indigo" title={`${pending.length} pedido(s) à espera da tua resposta`}>
          <Button component={Link} to="/notificacoes" size="xs" mt="xs">Responder</Button>
        </Alert>
      )}
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {energy.loading ? <Text c="dimmed">A carregar leituras…</Text>
          : !o || o.meters.length === 0 ? <Card withBorder radius="lg" p="lg"><Text fw={700}>Sem dados</Text><Text size="sm" c="dimmed">Ainda não há leituras de energia desta casa.</Text></Card>
          : o.meters.map((m) => <MeterCard key={m.device_id} m={m} now={o.now} />)}
        <Card withBorder radius="lg" p="lg">
          <Stack gap="xs">
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>O meu orçamento</Text>
            {!b ? <Text fw={700}>Sem dados</Text> : !b.budget?.limit_cents ? <Text c="dimmed">Sem orçamento definido este mês.</Text> : (
              <>
                <Text fz={28} fw={700}>{b.pct == null ? "Desconhecido" : `${b.pct} %`}</Text>
                <Progress value={Math.min(b.pct ?? 0, 100)} aria-label="Percentagem do orçamento utilizada" />
              </>
            )}
            <Button component={Link} to="/orcamento" variant="subtle" px={0} w="fit-content">Ver orçamento</Button>
          </Stack>
        </Card>
      </SimpleGrid>
      <Card withBorder radius="lg" p="lg">
        <Stack gap="md">
          <Group justify="space-between"><Title order={3} size="h4">Consumos recentes</Title>
            {unidentified > 0 && <Badge color="gray" variant="light">{unidentified} não identificado(s)</Badge>}</Group>
          {sessions.length === 0 ? <Text c="dimmed">Sem sessões detetadas.</Text>
            : sessions.slice(0, 3).map((s) => <SessionRow key={s.id} s={s} appliances={appliances} maxPeak={maxPeak} />)}
          <Button component={Link} to="/consumo" variant="subtle" px={0} w="fit-content">Ver tudo</Button>
        </Stack>
      </Card>
      <Card withBorder radius="lg" p="lg">
        <Stack gap="xs">
          <Title order={3} size="h4">Alertas recentes</Title>
          {alerts.length === 0 ? <Text c="dimmed">Sem alertas.</Text> : alerts.map((n) => <Text key={n.id} size="sm"><b>{n.title}</b> — {n.body}</Text>)}
          <Group gap="xs"><Button component={Link} to="/notificacoes" variant="subtle" px={0}>Notificações</Button><Button component={Link} to="/contas" variant="subtle">Faturas e recibos</Button></Group>
        </Stack>
      </Card>
    </Stack>
  );
}
