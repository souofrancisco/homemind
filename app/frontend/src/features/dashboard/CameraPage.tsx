import { Accordion, Badge, Button, Card, Group, Loader, SegmentedControl, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle, IconCamera, IconRefresh } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { simulateScenario, type DemoScenario } from "./mockHome";
import { useHomeSocket } from "./useHomeSocket";

const scenarios: { id: DemoScenario; label: string }[] = [
  { id: "book", label: "Livro → Leitura" }, { id: "remote", label: "Comando → Cinema" }, { id: "mug", label: "Caneca → Café" },
  { id: "absence", label: "Ausência → espera" }, { id: "return", label: "Regresso" }, { id: "connection", label: "Falha → recuperação" },
];

export default function CameraPage() {
  const { state, events, source, online } = useHomeSocket();
  const [view, setView] = useState("simples");
  const [failed, setFailed] = useState(false);
  const [loadingStream, setLoadingStream] = useState(true);
  const [retry, setRetry] = useState(0);
  const simulated = source === "mock" || state?.backend === "fake";
  const streamUrl = new URL("/video", import.meta.env.VITE_API_URL ?? window.location.origin).toString();
  const recentGestureOrMode = events.find((event) => event.category === "gesture" || event.category === "mode" || /^(gesto:|modo )/i.test(event.message));
  const recentIsGesture = recentGestureOrMode?.category === "gesture" || /^gesto:/i.test(recentGestureOrMode?.message ?? "");

  useEffect(() => {
    if (!failed || simulated || !online || !state?.camera_ok) return;
    const timer = setTimeout(() => { setRetry((value) => value + 1); setFailed(false); setLoadingStream(true); }, 5000);
    return () => clearTimeout(timer);
  }, [failed, simulated, online, state?.camera_ok]);

  const cameraUnavailable = state != null && !simulated && (!online || !state.camera_ok || failed);
  const cameraStatus = simulated ? "Indisponível" : state == null ? "A carregar" : !online ? "Ligação perdida" : !state.camera_ok || failed ? "Indisponível" : "Disponível";

  return <Stack gap="lg">
    <Group justify="space-between" align="center" wrap="wrap"><Title order={2}>Câmara</Title><SegmentedControl value={view} onChange={setView} data={[{ label: "Simples", value: "simples" }, { label: "Técnica", value: "tecnica" }]} /></Group>

    <Card withBorder radius="lg">
      <Group justify="space-between" mb="md"><Title order={4}>Sala</Title><Badge color={cameraUnavailable || simulated ? "red" : state == null ? "gray" : "teal"}>{cameraStatus}</Badge></Group>
      <Card withBorder bg="dark.8" c="white" h={{ base: 230, sm: 390 }} padding="md">
        {simulated ? <Stack h="100%" align="center" justify="center" gap="xs"><IconCamera size={42} /><Text fw={600}>Demonstração</Text></Stack>
          : state == null ? <Stack h="100%" align="center" justify="center" gap="xs"><Loader size="sm" /><Text size="sm" c="gray.4">A carregar a câmara…</Text></Stack>
            : !cameraUnavailable ? <Stack h="100%" align="center" justify="center" gap="xs">{loadingStream ? <><Loader size="sm" /><Text size="sm" c="gray.4">A ligar à câmara…</Text></> : null}<img key={retry} src={streamUrl} alt="Imagem da câmara" onLoad={() => setLoadingStream(false)} onError={() => { setLoadingStream(false); setFailed(true); }} style={{ width: "100%", height: loadingStream ? 0 : "100%", objectFit: "contain" }} /></Stack>
              : <Stack h="100%" align="center" justify="center" gap="xs"><IconAlertCircle size={38} /><Text fw={600}>{online ? "Câmara indisponível." : "Ligação perdida."}</Text>{failed && online && state.camera_ok ? <Button variant="light" leftSection={<IconRefresh size={16} />} onClick={() => { setFailed(false); setLoadingStream(true); setRetry((value) => value + 1); }}>Tentar novamente</Button> : null}</Stack>}
      </Card>

      {recentGestureOrMode ? <Group justify="space-between" mt="md" gap="xs"><div><Text size="sm" c="dimmed">{recentIsGesture ? "Último gesto" : "Último modo"}</Text><Text fw={500}>{recentGestureOrMode.message}</Text></div><Text size="xs" c="dimmed">{new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(new Date(recentGestureOrMode.timestamp))}</Text></Group> : null}

      {simulated ? <Accordion variant="contained" radius="md" mt="md"><Accordion.Item value="scenarios"><Accordion.Control>Cenários de demonstração</Accordion.Control><Accordion.Panel><SimpleGrid cols={{ base: 2, sm: 3 }}>{scenarios.map((scenario) => <Button key={scenario.id} variant="light" onClick={() => simulateScenario(scenario.id)}>{scenario.label}</Button>)}</SimpleGrid></Accordion.Panel></Accordion.Item></Accordion> : null}
    </Card>

    {view === "tecnica" ? <Card withBorder radius="lg"><Title order={4} mb="md">Detalhes da câmara</Title><SimpleGrid cols={{ base: 1, sm: 2 }}><div><Text size="xs" c="dimmed">ESTADO</Text><Text>{simulated ? "Demonstração" : !online ? "Ligação perdida" : state?.camera_ok && !failed ? "Disponível" : "Indisponível"}</Text></div><div><Text size="xs" c="dimmed">ÚLTIMA ATUALIZAÇÃO</Text><Text>{state?.updated_at ? new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(state.updated_at)) : "Sem informação"}</Text></div></SimpleGrid><Text size="sm" c="dimmed" mt="md">As imagens não são guardadas nem enviadas para outros serviços.</Text></Card> : null}
  </Stack>;
}
