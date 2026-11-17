import { Badge, Code, Group, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { formatHMS } from "../../utils/format";
import type { EventLogItem, HomeState } from "../../types/home";

function eventValue(value: unknown) {
  if (value === undefined) return undefined;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function findMetric(details: Record<string, unknown> | undefined, keys: string[]) {
  if (!details) return undefined;
  const key = keys.find((candidate) => details[candidate] !== undefined && details[candidate] !== null);
  return key ? details[key] : undefined;
}

type Props = { state: HomeState | null; online: boolean; cameraAvailable: boolean; detected?: EventLogItem };

export default function CameraDiagnostics({ state, online, cameraAvailable, detected }: Props) {
  return <Paper withBorder radius="md" p="md">
    <Stack gap="sm">
      <Group justify="space-between"><Title order={4}>Diagnóstico</Title><Badge color={online ? "teal" : "red"} variant="light">Backend {online ? "ligado" : "offline"}</Badge></Group>
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <div><Text size="xs" c="dimmed">CÂMARA</Text><Text>{state ? cameraAvailable ? "Disponível" : "Indisponível" : "Sem estado"}</Text></div>
        <div><Text size="xs" c="dimmed">PROCESSAMENTO</Text><Text>{state && cameraAvailable ? "Local" : "Sem dados"}</Text></div>
        <div><Text size="xs" c="dimmed">CONFIANÇA</Text><Text>{eventValue(findMetric(detected?.details, ["confidence", "confiança", "confidence_score"])) ?? "Não fornecida"}</Text></div>
        <div><Text size="xs" c="dimmed">FPS</Text><Text>{eventValue(findMetric(detected?.details, ["fps", "FPS"])) ?? "Não fornecido"}</Text></div>
        <div><Text size="xs" c="dimmed">LATÊNCIA</Text><Text>{eventValue(findMetric(detected?.details, ["latency_ms", "latency", "latência_ms", "latência"])) ?? "Não fornecida"}</Text></div>
      </SimpleGrid>
      {detected?.details ? <div><Text size="xs" c="dimmed" mb={4}>DADOS DA DETEÇÃO</Text><Code block>{JSON.stringify(detected.details, null, 2)}</Code></div> : <Text size="sm" c="dimmed">O backend ainda não forneceu dados de deteção.</Text>}
      {state?.updated_at ? <Text size="xs" c="dimmed">Estado atualizado às {formatHMS(state.updated_at)}</Text> : null}
    </Stack>
  </Paper>;
}
