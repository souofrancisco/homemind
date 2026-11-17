import { Button, Group, Pagination, Select, Stack, Text, Title } from "@mantine/core";
import EventFilters from "../components/events/EventFilters";
import EventTimeline from "../components/events/EventTimeline";
import { useEvents } from "../hooks/useEvents";
import { filterSummary } from "../utils/events";

export default function EventsPage() {
  const { online, hasEvents, filtered, currentGroups, pageCount, page, setPage, range, filters, pageSize, setPageSize } = useEvents();
  const emptyMessage = hasEvents
    ? `Nenhum evento corresponde aos filtros${filterSummary(filters.search, filters.category, filters.level, filters.period)}.`
    : online ? "Ainda não há eventos disponíveis." : "Não foi possível carregar eventos. Verifica a ligação e tenta novamente mais tarde.";

  return <Stack gap="lg">
    <Title order={2}>Eventos</Title>
    <EventFilters filters={filters} />

    <Group justify="space-between" align="center" wrap="wrap">
      <Text size="sm" c="dimmed">{range.first}–{range.last} de {filtered} eventos</Text>
      <Select aria-label="Eventos por página" w={130} value={pageSize} onChange={(value) => setPageSize(value ?? "10")} data={[{ value: "10", label: "10 por página" }, { value: "20", label: "20 por página" }, { value: "50", label: "50 por página" }]} />
    </Group>

    <EventTimeline groups={currentGroups} emptyMessage={emptyMessage} onClearFilters={hasEvents && filters.hasFilters ? filters.clear : undefined} />

    {pageCount > 1 ? <Group justify="space-between" align="center"><Button variant="default" disabled={page <= 1} onClick={() => setPage(Math.max(1, page - 1))}>Anterior</Button><Pagination total={pageCount} value={page} onChange={setPage} size="sm" siblings={0} boundaries={1} /><Button variant="default" disabled={page >= pageCount} onClick={() => setPage(Math.min(pageCount, page + 1))}>Seguinte</Button></Group> : null}
    <Text size="xs" c="dimmed">A lista mostra até 50 eventos recentes.</Text>
  </Stack>;
}
