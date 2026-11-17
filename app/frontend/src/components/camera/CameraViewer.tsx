import { Badge, Loader, Paper, Stack, Text } from "@mantine/core";
import { IconCamera } from "@tabler/icons-react";
import { useVideoFrame } from "../../hooks/useVideoFrame";

type Props = { status: { title: string; description: string; color: string }; loading: boolean; simulated: boolean; streamEnabled: boolean };

export default function CameraViewer({ status, loading, simulated, streamEnabled }: Props) {
  const { url, error } = useVideoFrame(streamEnabled);
  return <Paper withBorder radius="lg" bg="dark.9" p={url ? 0 : "md"} style={{ aspectRatio: "16 / 9", minHeight: 280, maxHeight: "68vh", display: "grid", placeItems: "center", overflow: "hidden" }}>
    {url ? <img src={url} alt="Imagem em direto da câmara (processamento local, sem gravação)" style={{ width: "100%", height: "100%", objectFit: "contain" }} /> : <Stack align="center" justify="center" gap="sm" ta="center" maw={520} p="md">
      {loading ? <Loader size="sm" color="gray.5" aria-label="A obter estado da câmara" /> : null}
      <IconCamera size={48} stroke={1.4} color="var(--mantine-color-gray-5)" />
      <Badge color={error ? "yellow" : status.color} variant="light">{error ? "Sem imagem" : status.title}</Badge>
      <Text c="gray.3" size="sm">{error ? `${error}. Nova tentativa em curso.` : status.description}</Text>
      {simulated ? <Text c="gray.5" size="xs">Backend em simulação (FakeHome): sem imagem real; os cenários abaixo injetam eventos simulados.</Text> : null}
    </Stack>}
  </Paper>;
}
