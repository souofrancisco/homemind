import { ActionIcon, Badge, Group, Loader, Paper, Stack, Text, Tooltip } from "@mantine/core";
import { useFullscreenElement } from "@mantine/hooks";
import { IconArrowsMaximize, IconArrowsMinimize, IconBone, IconCamera, IconLock, IconMaximize, IconMinimize, IconScan } from "@tabler/icons-react";
import { useState } from "react";
import { useVideoFrame } from "../../hooks/useVideoFrame";

type Props = {
  status: { title: string; description: string; color: string };
  loading: boolean; simulated: boolean; streamEnabled: boolean;
  expanded: boolean; onExpandedChange: (value: boolean) => void;
};

function Control({ label, active, onClick, children }: { label: string; active?: boolean; onClick: () => void; children: React.ReactNode }) {
  return <Tooltip label={label} withArrow>
    <ActionIcon variant={active ? "filled" : "default"} size="lg" onClick={onClick} aria-label={label} aria-pressed={active}>{children}</ActionIcon>
  </Tooltip>;
}

export default function CameraViewer({ status, loading, simulated, streamEnabled, expanded, onExpandedChange }: Props) {
  const [annotations, setAnnotations] = useState(true);
  const [skeleton, setSkeleton] = useState(true);
  const { ref, toggle, fullscreen } = useFullscreenElement<HTMLDivElement>();
  const { url, error } = useVideoFrame(streamEnabled, { annotations, skeleton });
  const reconnecting = Boolean(url && error);
  const live = streamEnabled && Boolean(url) && !error;
  const goFullscreen = () => { void toggle().catch(() => undefined); }; // alguns browsers (iOS) não suportam

  return <Stack ref={ref} gap="xs" p={fullscreen ? "sm" : 0} bg={fullscreen ? "dark.9" : undefined} style={fullscreen ? { height: "100%" } : undefined}>
    <Paper withBorder radius="lg" bg="dark.9" p={url ? 0 : "md"} role="region" aria-label="Vídeo da câmara"
      style={{ aspectRatio: fullscreen ? undefined : "16 / 9", flex: fullscreen ? 1 : undefined, minHeight: fullscreen ? 0 : 240, maxHeight: fullscreen ? undefined : expanded ? "85vh" : "68vh", display: "grid", placeItems: "center", overflow: "hidden", position: "relative" }}>
      {url ? <>
        <img src={url} alt="Imagem em direto da câmara com deteções (processamento local, sem gravação)" style={{ width: "100%", height: "100%", objectFit: "contain", opacity: reconnecting ? 0.5 : 1 }} />
        {reconnecting ? <Badge color="yellow" variant="filled" leftSection={<Loader size={10} color="dark" />} role="status" style={{ position: "absolute", top: 8, left: 8 }}>A reconectar…</Badge> : null}
      </> : <Stack align="center" justify="center" gap="sm" ta="center" maw={520} p="md" role="status">
        {loading || (streamEnabled && !error) ? <Loader size="sm" color="gray.5" aria-label="A ligar à câmara" /> : null}
        <IconCamera size={48} stroke={1.4} color="var(--mantine-color-gray-5)" />
        <Badge color={error ? "yellow" : status.color} variant="light">{error ? "Sem imagem" : status.title}</Badge>
        <Text c="gray.3" size="sm">{error ? `${error}. Nova tentativa em curso.` : status.description}</Text>
        {simulated ? <Text c="gray.5" size="xs">Backend em simulação (FakeHome): sem imagem real; os cenários abaixo injetam eventos simulados.</Text> : null}
      </Stack>}
    </Paper>
    <Group justify="space-between" gap="xs" wrap="wrap" role="toolbar" aria-label="Controlos do vídeo">
      <Group gap="xs">
        <Control label={annotations ? "Ocultar anotações" : "Mostrar anotações"} active={annotations} onClick={() => setAnnotations((v) => !v)}><IconScan size={20} /></Control>
        <Control label={skeleton ? "Ocultar esqueleto" : "Mostrar esqueleto"} active={annotations && skeleton} onClick={() => setSkeleton((v) => !v)}><IconBone size={20} /></Control>
      </Group>
      <Group gap="xs">
        <Badge variant="light" color="teal" leftSection={<IconLock size={12} />}>Local</Badge>
        <Badge variant="dot" color={live ? "teal" : reconnecting ? "yellow" : "gray"} role="status">{live ? "Em direto" : reconnecting ? "A reconectar" : "Sem imagem"}</Badge>
      </Group>
      <Group gap="xs">
        {!fullscreen ? <Control label={expanded ? "Reduzir vídeo" : "Expandir vídeo"} active={expanded} onClick={() => onExpandedChange(!expanded)}>{expanded ? <IconMinimize size={20} /> : <IconMaximize size={20} />}</Control> : null}
        <Control label={fullscreen ? "Sair do ecrã inteiro (Esc)" : "Ecrã inteiro"} active={fullscreen} onClick={goFullscreen}>{fullscreen ? <IconArrowsMinimize size={20} /> : <IconArrowsMaximize size={20} />}</Control>
      </Group>
    </Group>
  </Stack>;
}
