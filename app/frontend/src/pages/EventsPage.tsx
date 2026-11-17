import { Badge, Card, Code, Group, Select, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useMemo, useState } from "react";
import { useHome } from "../hooks/useHome";
import type { EventCategory, EventLogItem } from "../types/home";

const categories: { value: string; label: string }[] = [
  { value: "presence", label: "Presença" }, { value: "object", label: "Objeto detetado" }, { value: "gesture", label: "Gesto confirmado" },
  { value: "mode", label: "Modo ativado" }, { value: "rule", label: "Regra executada" }, { value: "device", label: "Dispositivo atualizado" },
  { value: "energy", label: "Energia" }, { value: "system", label: "Sistema / erro" },
];
const categoryLabels: Record<EventCategory, string> = Object.fromEntries(categories.map(({ value, label }) => [value, label])) as Record<EventCategory, string>;
const levels = [{ value: "info", label: "Informação" }, { value: "warning", label: "Aviso" }, { value: "error", label: "Erro" }];
const pageLoadedAt = Date.now();
const dateLabel = (value: string) => new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value));

function OperationCard({ events }: { events: EventLogItem[] }) {
  const ordered = [...events].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
  const timestamps = ordered.map((event) => Date.parse(event.timestamp));
  const valid = timestamps.every(Number.isFinite);
  const duration = valid && timestamps.length > 1 ? Math.max(...timestamps) - Math.min(...timestamps) : null;
  const label = (ms: number) => ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  return <Card withBorder radius="lg">
    <Group justify="space-between" mb="sm"><div><Text fw={600}>Sequência de operação</Text><Text size="xs" c="dimmed">Correlação {events[0]?.correlation_id}</Text></div>{duration != null ? <Badge variant="light">Duração {label(duration)}</Badge> : null}</Group>
    <Stack gap="sm">{ordered.map((event) => <Group key={event.id} align="flex-start" wrap="nowrap"><Badge size="xs" variant="light">{categoryLabels[event.category ?? "system"]}</Badge><div style={{ flex: 1 }}><Text size="sm">{event.message}</Text><Text size="xs" c="dimmed">{dateLabel(event.timestamp)}</Text>{event.details ? <Code block mt={6}>{JSON.stringify(event.details, null, 2)}</Code> : null}</div><Badge size="xs" color={event.source === "fake" ? "yellow" : "teal"}>{event.source === "fake" ? "SIM" : "REAL"}</Badge></Group>)}</Stack>
  </Card>;
}

export default function EventsPage() {
  const { events, source } = useHome();
  const [category, setCategory] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [period, setPeriod] = useState<string | null>("7d");
  const filtered = useMemo(() => {
    const cutoff = period === "24h" ? pageLoadedAt - 86400000 : period === "7d" ? pageLoadedAt - 7 * 86400000 : 0;
    return events.filter((event) => (!category || (event.category ?? "system") === category)
      && (!level || event.level === level)
      && Number.isFinite(Date.parse(event.timestamp)) && Date.parse(event.timestamp) >= cutoff);
  }, [events, category, level, period]);
  const groups = useMemo(() => {
    const grouped = new Map<string, EventLogItem[]>();
    for (const event of filtered) {
      const key = event.correlation_id ? `operation:${event.correlation_id}` : `event:${event.id}`;
      grouped.set(key, [...(grouped.get(key) ?? []), event]);
    }
    return [...grouped.values()];
  }, [filtered]);
  const simulated = source === "mock";

  return <Stack gap="lg">
    <Group justify="space-between" align="flex-start" wrap="wrap"><div><Text c="dimmed" size="sm">REGISTO EXPLICÁVEL</Text><Title order={2}>Eventos</Title><Text c="dimmed">Cada decisão mostra a origem e a evidência disponível.</Text></div><Badge size="lg" color={simulated ? "yellow" : "teal"}>{simulated ? "DADOS SIMULADOS" : "ORIGEM API"}</Badge></Group>
    <SimpleGrid cols={{ base: 1, sm: 3 }}><Select label="Categoria" placeholder="Todas" clearable data={categories} value={category} onChange={setCategory} /><Select label="Período" value={period} onChange={setPeriod} data={[{ value: "24h", label: "Últimas 24 horas" }, { value: "7d", label: "Últimos 7 dias" }, { value: "all", label: "Todo o histórico" }]} /><Select label="Gravidade" placeholder="Todas" clearable data={levels} value={level} onChange={setLevel} /></SimpleGrid>
    {events.some((event) => !event.category) ? <Text size="xs" c="dimmed">Os eventos atuais não incluem categoria estruturada; surgem como Sistema. O filtro por categoria depende da validação do contrato.</Text> : null}
    <Text size="sm" c="dimmed">{filtered.length} eventos · até 50 carregados</Text>
    {groups.length ? groups.map((group) => group[0]?.correlation_id ? <OperationCard key={group[0].correlation_id} events={group} /> : <Card key={group[0]?.id} withBorder radius="lg"><Group align="flex-start" wrap="nowrap"><Badge color={group[0]?.level === "error" ? "red" : group[0]?.level === "warning" ? "yellow" : "teal"}>{categoryLabels[group[0]?.category ?? "system"]}</Badge><div style={{ flex: 1 }}><Text>{group[0]?.message}</Text><Text size="xs" c="dimmed">{group[0] ? dateLabel(group[0].timestamp) : ""}</Text>{group[0]?.details ? <Code block mt="xs">{JSON.stringify(group[0].details, null, 2)}</Code> : null}</div><Badge color={group[0]?.source === "fake" ? "yellow" : "teal"}>{group[0]?.source === "fake" ? "SIMULADO" : "REAL"}</Badge></Group></Card>) : <Card withBorder radius="lg"><Text ta="center" c="dimmed" py="lg">Não há eventos para estes filtros.</Text></Card>}
  </Stack>;
}
