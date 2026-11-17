import { Button, Card, Group, Select, SimpleGrid, Stack, TextInput } from "@mantine/core";
import { IconX } from "@tabler/icons-react";
import type { useEvents } from "../../hooks/useEvents";
import { eventCategories, eventLevels, eventPeriods } from "../../utils/events";

export default function EventFilters({ filters }: { filters: ReturnType<typeof useEvents>["filters"] }) {
  return <Card withBorder radius="lg" p="md">
    <Stack gap="sm">
      <TextInput label="Pesquisar mensagens" placeholder="Ex.: modo leitura" value={filters.search} onChange={(event) => filters.setSearch(event.currentTarget.value)} />
      <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
        <Select label="Categoria" placeholder="Todas" clearable data={eventCategories} value={filters.category} onChange={filters.setCategory} />
        <Select label="Tipo" placeholder="Todos" clearable data={eventLevels} value={filters.level} onChange={filters.setLevel} />
        <Select label="Período" value={filters.period} onChange={filters.setPeriod} data={eventPeriods} />
      </SimpleGrid>
      {filters.hasFilters ? <Group justify="flex-end"><Button variant="subtle" size="compact-sm" leftSection={<IconX size={14} />} onClick={filters.clear}>Limpar filtros</Button></Group> : null}
    </Stack>
  </Card>;
}
