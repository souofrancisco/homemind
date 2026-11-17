import { Button, Card, Group, Stack, Text } from "@mantine/core";
import type { EventGroup } from "../../types/home";
import { dateGroups } from "../../utils/events";
import { EventItem } from "./EventItem";

type Props = { groups: EventGroup[]; emptyMessage: string; onClearFilters?: () => void };

export default function EventTimeline({ groups, emptyMessage, onClearFilters }: Props) {
  if (!groups.length) {
    return <Card withBorder radius="lg"><Text ta="center" c="dimmed" py="lg">{emptyMessage}</Text>{onClearFilters ? <Group justify="center"><Button variant="subtle" onClick={onClearFilters}>Limpar filtros</Button></Group> : null}</Card>;
  }
  return <Stack gap="md">{dateGroups(groups).map(({ label, groups: dayGroups }) => <Stack key={label} gap="xs"><Text size="sm" fw={600} c="dimmed">{label}</Text>{dayGroups.map((group) => <EventItem key={group.events[0]?.correlation_id ?? group.events[0]?.id} group={group} />)}</Stack>)}</Stack>;
}
