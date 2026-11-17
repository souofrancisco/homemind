import { Button, Card, Group, Pagination, Select, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconX } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { EventItem, type EventGroup } from "../components/events/EventItem";
import { useHome } from "../hooks/useHome";
import type { EventLogItem } from "../types/home";

const categories: { value: string; label: string }[] = [
  { value: "presence", label: "Presença" }, { value: "object", label: "Objeto" }, { value: "gesture", label: "Gesto" },
  { value: "mode", label: "Modo" }, { value: "rule", label: "Regra" }, { value: "device", label: "Dispositivo" },
  { value: "energy", label: "Energia" }, { value: "system", label: "Outros" },
];
const levels = [{ value: "info", label: "Informação" }, { value: "warning", label: "Aviso" }, { value: "error", label: "Erro" }];
const periods = [{ value: "24h", label: "Últimas 24 horas" }, { value: "7d", label: "Últimos 7 dias" }, { value: "all", label: "Todos os eventos carregados" }];
const pageLoadedAt = Date.now();
const eventTime = (event: EventLogItem) => Date.parse(event.timestamp);
const categoryOf = (event: EventLogItem) => event.category ?? "system";
const eventGroups = (items: EventLogItem[]): EventGroup[] => {
  const groups = new Map<string, EventLogItem[]>();
  for (const event of items) {
    const key = event.correlation_id ? `operation:${event.correlation_id}` : `event:${event.id}`;
    const group = groups.get(key);
    if (group) group.push(event);
    else groups.set(key, [event]);
  }
  return [...groups.values()].map((events) => ({
    events: [...events].sort((a, b) => eventTime(a) - eventTime(b)),
    newest: Math.max(...events.map(eventTime).filter(Number.isFinite)),
  })).sort((a, b) => b.newest - a.newest);
};

export default function EventsPage() {
  const { events, online } = useHome();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [period, setPeriod] = useState<string | null>("7d");
  const [pageSize, setPageSize] = useState("10");
  const [page, setPage] = useState(1);
  const pageLimit = Number(pageSize) || 10;

  const filtered = useMemo(() => {
    const now = pageLoadedAt;
    const cutoff = period === "24h" ? now - 86400000 : period === "7d" ? now - 7 * 86400000 : 0;
    const needle = search.trim().toLocaleLowerCase("pt-PT");
    return events.filter((event) => {
      const timestamp = eventTime(event);
      return (!needle || event.message.toLocaleLowerCase("pt-PT").includes(needle))
        && (!category || categoryOf(event) === category)
        && (!level || event.level === level)
        && Number.isFinite(timestamp) && timestamp >= cutoff;
    });
  }, [events, search, category, level, period]);

  const groups = useMemo(() => eventGroups(filtered), [filtered]);
  const pages = useMemo(() => {
    const result: EventGroup[][] = [];
    let current: EventGroup[] = [];
    let count = 0;
    for (const group of groups) {
      const size = group.events.length;
      if (current.length && count + size > pageLimit) {
        result.push(current);
        current = [];
        count = 0;
      }
      current.push(group);
      count += size;
    }
    if (current.length) result.push(current);
    return result;
  }, [groups, pageLimit]);
  const pageCount = Math.max(1, pages.length);
  const safePage = Math.min(page, pageCount);
  const currentGroups = pages[safePage - 1] ?? [];
  const currentEvents = currentGroups.flatMap((group) => group.events);
  const first = currentEvents.length ? (pages.slice(0, safePage - 1).reduce((sum, entry) => sum + entry.reduce((n, group) => n + group.events.length, 0), 0) + 1) : 0;
  const last = first ? first + currentEvents.length - 1 : 0;
  const hasFilters = Boolean(search.trim() || category || level || period !== "all");
  const updateFilter = (update: () => void) => {
    update();
    setPage(1);
  };
  const clearFilters = () => {
    setSearch("");
    setCategory(null);
    setLevel(null);
    setPeriod("all");
    setPage(1);
  };

  return <Stack gap="lg">
    <Group justify="space-between" align="flex-start" wrap="wrap">
      <Title order={2}>Eventos</Title>
    </Group>

    <Card withBorder radius="lg" p="md">
      <Stack gap="sm">
        <TextInput label="Pesquisar mensagens" placeholder="Ex.: modo leitura" value={search} onChange={(event) => updateFilter(() => setSearch(event.currentTarget.value))} />
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Select label="Categoria" placeholder="Todas" clearable data={categories} value={category} onChange={(value) => updateFilter(() => setCategory(value))} />
          <Select label="Tipo" placeholder="Todos" clearable data={levels} value={level} onChange={(value) => updateFilter(() => setLevel(value))} />
          <Select label="Período" value={period} onChange={(value) => updateFilter(() => setPeriod(value))} data={periods} />
        </SimpleGrid>
        {hasFilters ? <Group justify="flex-end"><Button variant="subtle" size="compact-sm" leftSection={<IconX size={14} />} onClick={clearFilters}>Limpar filtros</Button></Group> : null}
      </Stack>
    </Card>

    <Group justify="space-between" align="center" wrap="wrap">
      <Text size="sm" c="dimmed">{first}–{last} de {filtered.length} eventos</Text>
      <Select aria-label="Eventos por página" w={130} value={pageSize} onChange={(value) => { setPageSize(value ?? "10"); setPage(1); }} data={[{ value: "10", label: "10 por página" }, { value: "20", label: "20 por página" }, { value: "50", label: "50 por página" }]} />
    </Group>

    {currentGroups.length ? <Stack gap="md">{dateGroups(currentGroups).map(({ label, groups: dateEvents }) => <Stack key={label} gap="xs"><Text size="sm" fw={600} c="dimmed">{label}</Text>{dateEvents.map((group) => <EventItem key={group.events[0]?.correlation_id ?? group.events[0]?.id} group={group} />)}</Stack>)}</Stack>
      : <Card withBorder radius="lg"><Text ta="center" c="dimmed" py="lg">{events.length ? `Nenhum evento corresponde aos filtros${filterSummary(search, category, level, period)}.` : online ? "Ainda não há eventos disponíveis." : "Não foi possível carregar eventos. Verifica a ligação e tenta novamente mais tarde."}</Text>{hasFilters ? <Group justify="center"><Button variant="subtle" onClick={clearFilters}>Limpar filtros</Button></Group> : null}</Card>}

    {pageCount > 1 ? <Group justify="space-between" align="center"><Button variant="default" disabled={safePage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Anterior</Button><Pagination total={pageCount} value={safePage} onChange={setPage} size="sm" siblings={0} boundaries={1} /><Button variant="default" disabled={safePage >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))}>Seguinte</Button></Group> : null}
    <Text size="xs" c="dimmed">A lista mostra até 50 eventos recentes.</Text>
  </Stack>;
}

function dateGroups(groups: EventGroup[]) {
  const byDate = new Map<string, EventGroup[]>();
  for (const group of groups) {
    const timestamp = group.newest;
    const key = Number.isFinite(timestamp) ? new Intl.DateTimeFormat("pt-PT", { dateStyle: "full" }).format(timestamp) : "Data desconhecida";
    byDate.set(key, [...(byDate.get(key) ?? []), group]);
  }
  return [...byDate].map(([label, dateEvents]) => ({ label, groups: dateEvents }));
}

function filterSummary(search: string, category: string | null, level: string | null, period: string | null) {
  const active = [search.trim() ? `pesquisa “${search.trim()}”` : "", category ? categories.find((item) => item.value === category)?.label : "", level ? levels.find((item) => item.value === level)?.label : "", period && period !== "all" ? periods.find((item) => item.value === period)?.label : ""].filter(Boolean);
  return active.length ? ` (${active.join(", ")})` : "";
}
