import { Alert, Badge, Button, Card, Group, Loader, SegmentedControl, SimpleGrid, Stack, Text, Title } from "@mantine/core";
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
  const [retrying, setRetrying] = useState(false);
  const [retry, setRetry] = useState(0);
  const simulated = source === "mock" || state?.backend === "fake";
  const streamUrl = new URL("/video", import.meta.env.VITE_API_URL ?? window.location.origin).toString();
  const detected = events.find((event) => event.category === "object" || /objeto detetado/i.test(event.message));
  const gesture = events.find((event) => event.category === "gesture" || /gesto validado/i.test(event.message));
  const action = events.find((event) => event.category === "device" || event.category === "mode" || /modo .* ativado|ações previstas/i.test(event.message));
  useEffect(() => {
    if (!failed || simulated || !online || !state?.camera_ok) return;
    const timer = setTimeout(() => { setRetry((value) => value + 1); setFailed(false); setLoadingStream(true); setRetrying(false); }, 5000);
    return () => clearTimeout(timer);
  }, [failed, simulated, online, state?.camera_ok]);
  const reconnecting = retrying || (failed && online && Boolean(state?.camera_ok));

  return <Stack gap="lg">
    <Group justify="space-between" align="flex-start" wrap="wrap"><div><Text c="dimmed" size="sm">VISÃO COMPUTACIONAL · PROCESSAMENTO LOCAL</Text><Title order={2}>Câmara</Title><Text c="dimmed">O vídeo não é guardado nem enviado para serviços externos.</Text></div><SegmentedControl value={view} onChange={setView} data={[{ label: "Simples", value: "simples" }, { label: "Técnica", value: "tecnica" }]} /></Group>
    <Card withBorder radius="lg">
      <Group justify="space-between" mb="md"><div><Title order={4}>Sala</Title><Text size="sm" c="dimmed">Stream anotado do backend</Text></div><Badge color={simulated ? "yellow" : state?.camera_ok && !failed ? "teal" : "red"}>{simulated ? "MOCK · SEM VÍDEO" : state?.camera_ok && !failed ? "STREAM DISPONÍVEL" : "SEM SINAL"}</Badge></Group>
      <Card withBorder bg="dark.8" c="white" h={{ base: 230, sm: 390 }} padding="md">
        {simulated ? <Stack h="100%" align="center" justify="center" gap="xs"><IconCamera size={42} /><Text fw={600}>Pré-visualização simulada</Text><Text size="sm" c="gray.4" ta="center">Esta demonstração não contém vídeo. Use os cenários abaixo para gerar eventos de exemplo.</Text></Stack>
          : state?.camera_ok && online && !failed ? <Stack h="100%" align="center" justify="center" gap="xs">{loadingStream ? <><Loader size="sm" /><Text size="sm" c="gray.4">A ligar ao stream…</Text></> : null}<img key={retry} src={streamUrl} alt="Stream MJPEG anotado da câmara" onLoad={() => setLoadingStream(false)} onError={() => { setLoadingStream(false); setFailed(true); }} style={{ width: "100%", height: loadingStream ? 0 : "100%", objectFit: "contain" }} /></Stack>
          : <Stack h="100%" align="center" justify="center" gap="xs"><IconAlertCircle size={38} /><Text fw={600}>{reconnecting ? "A tentar recuperar o stream…" : failed ? "Stream sem sinal" : "A aguardar câmara"}</Text><Text size="sm" c="gray.4">{online ? "A câmara não está a disponibilizar imagens." : "Backend offline. O último estado continua visível."}</Text><Button variant="light" leftSection={<IconRefresh size={16} />} onClick={() => { setRetrying(false); setFailed(false); setLoadingStream(true); setRetry((value) => value + 1); }}>Tentar novamente</Button></Stack>}
      </Card>
      {simulated ? <><Text fw={600} mt="md" mb="xs">Cenários de demonstração · SIMULADO</Text><SimpleGrid cols={{ base: 2, sm: 3 }}>{scenarios.map((scenario) => <Button key={scenario.id} variant="light" onClick={() => simulateScenario(scenario.id)}>{scenario.label}</Button>)}</SimpleGrid></> : null}
    </Card>

    <SimpleGrid cols={{ base: 1, lg: 2 }}>
      <Card withBorder radius="lg"><Title order={4} mb="md">Última deteção</Title><Stack gap="sm"><div><Text size="xs" c="dimmed">OBJETO IDENTIFICADO</Text><Text>{detected?.message ?? "Sem deteções disponíveis"}</Text></div><div><Text size="xs" c="dimmed">CONFIANÇA</Text><Text>{typeof detected?.details?.confidence === "number" ? `${Math.round(detected.details.confidence * 100)}%` : typeof detected?.details?.confiança === "string" ? detected.details.confiança : "Não fornecida pelo backend"}</Text></div><div><Text size="xs" c="dimmed">VALIDAÇÃO DO GESTO</Text><Text>{gesture?.message ?? "Sem gesto confirmado"}</Text></div><div><Text size="xs" c="dimmed">AÇÃO RESULTANTE</Text><Text>{action?.message ?? "Sem ação registada"}</Text></div></Stack></Card>
      {view === "tecnica" ? <Card withBorder radius="lg"><Title order={4} mb="md">Diagnóstico técnico</Title><SimpleGrid cols={2}><div><Text size="xs" c="dimmed">CÂMARA</Text><Text>{state?.camera_ok ? "Disponível" : "Indisponível"}</Text></div><div><Text size="xs" c="dimmed">PROCESSAMENTO LOCAL</Text><Text>{state?.camera_ok ? "Ativo" : "Sem dados"}</Text></div><div><Text size="xs" c="dimmed">FPS</Text><Text>Não fornecido</Text></div><div><Text size="xs" c="dimmed">LATÊNCIA</Text><Text>Não fornecida</Text></div><div><Text size="xs" c="dimmed">ATUALIZAÇÃO</Text><Text>{state?.updated_at ? new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(state.updated_at)) : "Sem dados"}</Text></div><div><Text size="xs" c="dimmed">BACKEND</Text><Text>{online ? "Ligado" : "Offline"}</Text></div></SimpleGrid></Card> : <Card withBorder radius="lg"><Title order={4} mb="sm">Privacidade</Title><Alert color="teal">Sem reconhecimento facial. Não são guardados frames nem associada presença a uma identidade.</Alert></Card>}
    </SimpleGrid>
    {state == null ? <Group><Loader size="xs" /><Text size="sm" c="dimmed">A carregar estado da câmara…</Text></Group> : null}
  </Stack>;
}
