import { Alert, Group, Paper, SegmentedControl, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useState } from "react";
import CameraDiagnostics from "../components/camera/CameraDiagnostics";
import CameraViewer from "../components/camera/CameraViewer";
import DemoScenarios from "../components/camera/DemoScenarios";
import { useCamera } from "../hooks/useCamera";
import { useHome } from "../hooks/useHome";

export default function CameraPage() {
  const { state, online, simulated, streamEnabled, detected, gesture, activeMode, mode, cameraAvailable, status } = useCamera();
  const { mock } = useHome();
  const [view, setView] = useState("simples");
  const [expanded, setExpanded] = useState(false);

  return <Stack gap="md">
    <Group justify="space-between" align="center" wrap="wrap">
      <div><Text c="dimmed" size="sm">PROCESSAMENTO LOCAL</Text><Title order={2}>Câmara</Title></div>
      <SegmentedControl value={view} onChange={setView} data={[{ label: "Simples", value: "simples" }, { label: "Técnica", value: "tecnica" }]} />
    </Group>

    <CameraViewer status={status} loading={online && !state} simulated={simulated} streamEnabled={streamEnabled} expanded={expanded} onExpandedChange={setExpanded} />

    {expanded ? null : view === "simples" ? <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
      <Paper withBorder radius="md" p="sm"><Text size="xs" c="dimmed">ÚLTIMO GESTO</Text><Text fw={500}>{gesture?.message ?? "Sem gesto registado"}</Text></Paper>
      <Paper withBorder radius="md" p="sm"><Text size="xs" c="dimmed">OBJETO RECONHECIDO</Text><Text fw={500}>{detected?.message ?? "Sem objeto registado"}</Text></Paper>
      <Paper withBorder radius="md" p="sm"><Text size="xs" c="dimmed">MODO ATIVADO</Text><Text fw={500}>{activeMode?.message ?? (mode ? `Modo ${mode}` : "Sem modo ativo")}</Text></Paper>
    </SimpleGrid> : <CameraDiagnostics state={state} online={online} cameraAvailable={cameraAvailable} detected={detected} />}

    {!expanded && simulated && !mock ? <DemoScenarios /> : null}

    {expanded ? null : <Alert icon={<IconAlertCircle size={18} />} color="teal" variant="light" title="Privacidade">
      O processamento é local. Os frames não são gravados e não é feito reconhecimento facial.
    </Alert>}
  </Stack>;
}
