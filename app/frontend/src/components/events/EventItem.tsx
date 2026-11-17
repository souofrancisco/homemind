import { Accordion, Badge, Card, Group, Stack, Text } from "@mantine/core";
import type { EventGroup } from "../../types/home";
import { categoryLabels, categoryOf, resultColor, resultLabels } from "../../utils/events";
import { formatHM } from "../../utils/format";

const levelLabels = { info: "Informação", warning: "Aviso", error: "Erro" };
const levelColors = { info: "blue", warning: "yellow", error: "red" };

export function EventItem({ group }: { group: EventGroup }) {
  const ordered = group.events;

  return <Card withBorder radius="md" p="sm">
    <Stack gap="xs">
      {ordered.map((event) => <div key={event.id}>
        <Group justify="space-between" align="center" wrap="nowrap" gap="xs">
          <Text size="sm" fw={500} style={{ minWidth: 0, overflowWrap: "anywhere" }}>{event.message}</Text>
          <Group gap="xs" wrap="nowrap"><Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>{formatHM(event.timestamp)}</Text>{event.result ? <Badge size="xs" color={resultColor(event.result)}>{resultLabels[event.result]}</Badge> : event.level !== "info" ? <Badge size="xs" color={levelColors[event.level]} variant="light">{levelLabels[event.level]}</Badge> : null}</Group>
        </Group>
        <Accordion variant="contained" radius="sm" mt="xs">
          <Accordion.Item value={event.id}>
            <Accordion.Control px="sm" py={4}><Text size="xs">Ver detalhes</Text></Accordion.Control>
            <Accordion.Panel>
              <Stack gap={6}>
                <Group gap="xs"><Badge size="xs" variant="light">{categoryLabels[categoryOf(event)]}</Badge><Text size="xs" c="dimmed">Origem: {event.source === "fake" ? "dados de demonstração" : "dados reais"}</Text></Group>
                <Text size="xs" c="dimmed">Registado em {new Date(event.timestamp).toLocaleString("pt-PT")}</Text>
                {event.id ? <Text size="xs" c="dimmed">Identificador: {event.id}</Text> : null}
                {event.correlation_id ? <Text size="xs" c="dimmed">Identificador da sequência: {event.correlation_id}</Text> : null}
                {event.details ? <pre style={{ margin: 0, overflowX: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: "var(--mantine-font-size-xs)" }}>{JSON.stringify(event.details, null, 2)}</pre> : null}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </div>)}
    </Stack>
  </Card>;
}
