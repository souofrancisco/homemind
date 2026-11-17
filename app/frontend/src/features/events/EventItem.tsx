import { Accordion, Badge, Card, Group, Stack, Text } from "@mantine/core";
import type { EventCategory, EventLogItem } from "../dashboard/types";

export interface EventGroup {
  events: EventLogItem[];
  newest: number;
}

const categoryLabels: Record<EventCategory, string> = {
  presence: "Presença", object: "Objeto detetado", gesture: "Gesto confirmado", mode: "Modo ativado",
  rule: "Regra executada", device: "Dispositivo", energy: "Energia", system: "Sistema / sem categoria",
};
const levelLabels = { info: "Informação", warning: "Aviso", error: "Erro" };
const levelColors = { info: "blue", warning: "yellow", error: "red" };
const resultLabels = { verified: "Confirmado", failed: "Falhou", unverified: "Sem confirmação", unsupported: "Não suportado" };
const categoryOf = (event: EventLogItem) => event.category ?? "system";
const timeLabel = (timestamp: string) => new Intl.DateTimeFormat("pt-PT", { timeStyle: "short" }).format(new Date(timestamp));
const durationLabel = (milliseconds: number) => milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(1)} s`;

export function EventItem({ group }: { group: EventGroup }) {
  const correlated = Boolean(group.events[0]?.correlation_id);
  const ordered = group.events;
  const timestamps = ordered.map((event) => Date.parse(event.timestamp));
  const validTimestamps = timestamps.length > 1 && timestamps.every(Number.isFinite);
  const duration = validTimestamps ? Math.max(...timestamps) - Math.min(...timestamps) : null;
  const groupResult = ordered.length > 1 && ordered.every((event) => event.result && event.result === ordered[0]?.result) ? ordered[0]?.result : null;

  return <Card withBorder radius="md" p="sm">
    <Stack gap="xs">
      {correlated ? <Group justify="space-between" wrap="wrap" gap="xs">
        <Text size="sm" fw={600}>Sequência de operação</Text>
        <Group gap="xs"><Badge variant="light">{ordered.length} eventos</Badge>{duration !== null ? <Badge variant="light" color="gray">{durationLabel(duration)}</Badge> : null}{groupResult ? <Badge color={resultColor(groupResult)}>{resultLabels[groupResult]}</Badge> : null}</Group>
      </Group> : null}
      {ordered.map((event, index) => <div key={event.id}>
        {correlated ? <Group gap="xs" mb={6}><Badge size="xs" variant="outline">{index + 1}</Badge><Text size="xs" c="dimmed">{categoryLabels[categoryOf(event)]}</Text></Group> : null}
        <Group justify="space-between" align="center" wrap="nowrap" gap="xs">
          <Text size="sm" fw={500} style={{ minWidth: 0, overflowWrap: "anywhere" }}>{event.message}</Text>
          <Group gap="xs" wrap="nowrap"><Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>{timeLabel(event.timestamp)}</Text><Badge size="xs" color={levelColors[event.level]} variant="light">{event.result ? resultLabels[event.result] : levelLabels[event.level]}</Badge></Group>
        </Group>
        <Accordion variant="contained" radius="sm" mt="xs">
          <Accordion.Item value={event.id}>
            <Accordion.Control px="sm" py={4}><Text size="xs">Detalhes técnicos</Text></Accordion.Control>
            <Accordion.Panel>
              <Stack gap={6}>
                <Group gap="xs"><Badge size="xs" variant="light">{categoryLabels[categoryOf(event)]}</Badge><Badge size="xs" color={event.source === "fake" ? "yellow" : "teal"}>{event.source === "fake" ? "SIMULADO" : "REAL"}</Badge>{event.result ? <Badge size="xs" color={resultColor(event.result)}>{resultLabels[event.result]}</Badge> : null}</Group>
                <Text size="xs" c="dimmed">ID: {event.id} · {new Date(event.timestamp).toLocaleString("pt-PT")}</Text>
                {event.correlation_id ? <Text size="xs" c="dimmed">Correlação: {event.correlation_id}</Text> : null}
                {event.details ? <pre style={{ margin: 0, overflowX: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: "var(--mantine-font-size-xs)" }}>{JSON.stringify(event.details, null, 2)}</pre> : <Text size="xs" c="dimmed">Sem dados técnicos adicionais.</Text>}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </div>)}
    </Stack>
  </Card>;
}

function resultColor(result: NonNullable<EventLogItem["result"]>) {
  if (result === "verified") return "teal";
  if (result === "failed") return "red";
  if (result === "unsupported") return "gray";
  return "yellow";
}
