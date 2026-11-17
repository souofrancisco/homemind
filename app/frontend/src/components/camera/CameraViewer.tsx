import { Badge, Loader, Paper, Stack, Text } from "@mantine/core";
import { IconCamera } from "@tabler/icons-react";

type Props = { status: { title: string; description: string; color: string }; loading: boolean; simulated: boolean };

export default function CameraViewer({ status, loading, simulated }: Props) {
  return <Paper withBorder radius="lg" bg="dark.9" p="md" style={{ aspectRatio: "16 / 9", minHeight: 280, maxHeight: "68vh", display: "grid", placeItems: "center", overflow: "hidden" }}>
    <Stack align="center" justify="center" gap="sm" ta="center" maw={520} p="md">
      {loading ? <Loader size="sm" color="gray.5" aria-label="A obter estado da câmara" /> : null}
      <IconCamera size={48} stroke={1.4} color="var(--mantine-color-gray-5)" />
      <Badge color={status.color} variant="light">{status.title}</Badge>
      <Text c="gray.3" size="sm">{status.description}</Text>
      {simulated ? <Text c="gray.5" size="xs">Pré-visualização sem frames · os cenários abaixo geram eventos de exemplo.</Text> : null}
    </Stack>
  </Paper>;
}
