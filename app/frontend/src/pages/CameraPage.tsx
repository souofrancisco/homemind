import { Accordion, Alert, Badge, Button, Code, Group, Loader, Paper, SegmentedControl, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle, IconCamera, IconCheck, IconCoffee, IconDeviceTv, IconMoon, IconPlugConnectedX, IconBook2, IconUserCheck } from "@tabler/icons-react";
import { useState } from "react";
import { useHome } from "../hooks/useHome";
import { simulateScenario, type DemoScenario } from "../mocks/home";

const scenarios: { id: DemoScenario; label: string; description: string; consequence: string; icon: typeof IconCamera }[] = [
  { id: "book", label: "Livro", description: "Gesto de leitura", consequence: "Ativa o modo Leitura.", icon: IconBook2 },
  { id: "remote", label: "Comando", description: "Preparar cinema", consequence: "Ativa a Noite de cinema.", icon: IconDeviceTv },
  { id: "mug", label: "Caneca", description: "Pausa para café", consequence: "Ativa o modo Café.", icon: IconCoffee },
  { id: "absence", label: "Ausência", description: "Iniciar espera", consequence: "Suspende a casa após a espera.", icon: IconMoon },
  { id: "return", label: "Regresso", description: "Presença detetada", consequence: "Restaura o estado anterior.", icon: IconUserCheck },
  { id: "connection", label: "Ligação", description: "Interromper e recuperar", consequence: "Mostra a perda e recuperação do backend.", icon: IconPlugConnectedX },
];

function eventValue(value: unknown) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function findMetric(details: Record<string, unknown> | undefined, keys: string[]) {
  if (!details) return undefined;
  const key = keys.find((candidate) => details[candidate] !== undefined && details[candidate] !== null);
  return key ? details[key] : undefined;
}

export default function CameraPage() {
  const { state, events, source, online } = useHome();
  const [view, setView] = useState("simples");
  const simulated = source === "mock" || state?.backend === "fake";
  const detected = events.find((event) => event.category === "object" || /objeto detetado/i.test(event.message));
  const gesture = events.find((event) => event.category === "gesture" || /gesto validado/i.test(event.message));
  const activeMode = events.find((event) => event.category === "mode" || /modo .* ativado|ações previstas/i.test(event.message));
  const mode = state?.mode_name ?? state?.mode ?? null;
  const cameraAvailable = Boolean(state?.camera_ok);
  const simpleStatus = !online
    ? { title: "Backend offline", description: "A ligação ao serviço foi interrompida. O vídeo não está a ser atualizado.", color: "red" }
    : !state
      ? { title: "A obter estado da câmara", description: "A ligação está ativa; à espera do primeiro estado.", color: "blue" }
      : !cameraAvailable
        ? { title: "Câmara indisponível", description: "O backend está ligado, mas não comunica uma câmara disponível.", color: "yellow" }
        : { title: "Câmara disponível · stream por configurar", description: "A origem MJPEG ainda não foi confirmada. Nenhuma rota de vídeo foi solicitada.", color: "teal" };

  return <Stack gap="md">
    <Group justify="space-between" align="center" wrap="wrap">
      <div><Text c="dimmed" size="sm">PROCESSAMENTO LOCAL</Text><Title order={2}>Câmara</Title></div>
      <Group gap="sm">
        <Badge color={simulated ? "yellow" : "teal"} variant="light">{simulated ? "SIMULAÇÃO" : "ORIGEM REAL"}</Badge>
        <SegmentedControl value={view} onChange={setView} data={[{ label: "Simples", value: "simples" }, { label: "Técnica", value: "tecnica" }]} />
      </Group>
    </Group>

    <Paper withBorder radius="lg" bg="dark.9" p="md" style={{ aspectRatio: "16 / 9", minHeight: 280, maxHeight: "68vh", display: "grid", placeItems: "center", overflow: "hidden" }}>
      <Stack align="center" justify="center" gap="sm" ta="center" maw={520} p="md">
        {online && !state ? <Loader size="sm" color="gray.5" aria-label="A obter estado da câmara" /> : null}
        <IconCamera size={48} stroke={1.4} color="var(--mantine-color-gray-5)" />
        <Badge color={simpleStatus.color} variant="light">{simpleStatus.title}</Badge>
        <Text c="gray.3" size="sm">{simpleStatus.description}</Text>
        {simulated ? <Text c="gray.5" size="xs">Pré-visualização sem frames · os cenários abaixo geram eventos de exemplo.</Text> : null}
      </Stack>
    </Paper>

    {view === "simples" ? <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
      <Paper withBorder radius="md" p="sm"><Text size="xs" c="dimmed">ÚLTIMO GESTO</Text><Text fw={500}>{gesture?.message ?? "Sem gesto registado"}</Text></Paper>
      <Paper withBorder radius="md" p="sm"><Text size="xs" c="dimmed">OBJETO RECONHECIDO</Text><Text fw={500}>{detected?.message ?? "Sem objeto registado"}</Text></Paper>
      <Paper withBorder radius="md" p="sm"><Text size="xs" c="dimmed">MODO ATIVADO</Text><Text fw={500}>{activeMode?.message ?? (mode ? `Modo ${mode}` : "Sem modo ativo")}</Text></Paper>
    </SimpleGrid> : <Paper withBorder radius="md" p="md">
      <Stack gap="sm">
        <Group justify="space-between"><Title order={4}>Diagnóstico</Title><Badge color={online ? "teal" : "red"} variant="light">Backend {online ? "ligado" : "offline"}</Badge></Group>
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <div><Text size="xs" c="dimmed">CÂMARA</Text><Text>{state ? cameraAvailable ? "Disponível" : "Indisponível" : "Sem estado"}</Text></div>
          <div><Text size="xs" c="dimmed">PROCESSAMENTO</Text><Text>{state && cameraAvailable ? "Local" : "Sem dados"}</Text></div>
          <div><Text size="xs" c="dimmed">CONFIANÇA</Text><Text>{eventValue(findMetric(detected?.details, ["confidence", "confiança", "confidence_score"])) ?? "Não fornecida"}</Text></div>
          <div><Text size="xs" c="dimmed">FPS</Text><Text>{eventValue(findMetric(detected?.details, ["fps", "FPS"])) ?? "Não fornecido"}</Text></div>
          <div><Text size="xs" c="dimmed">LATÊNCIA</Text><Text>{eventValue(findMetric(detected?.details, ["latency_ms", "latency", "latência_ms", "latência"])) ?? "Não fornecida"}</Text></div>
        </SimpleGrid>
        {detected?.details ? <div><Text size="xs" c="dimmed" mb={4}>DADOS DA DETEÇÃO</Text><Code block>{JSON.stringify(detected.details, null, 2)}</Code></div> : <Text size="sm" c="dimmed">O backend ainda não forneceu dados de deteção.</Text>}
        {state?.updated_at ? <Text size="xs" c="dimmed">Estado atualizado às {new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(state.updated_at))}</Text> : null}
      </Stack>
    </Paper>}

    {simulated ? <Accordion variant="separated" radius="md">
      <Accordion.Item value="scenarios">
        <Accordion.Control><Group gap="sm"><Text fw={600}>Cenários de demonstração</Text><Badge color="yellow" variant="light">6 · simulados</Badge></Group></Accordion.Control>
        <Accordion.Panel>
          <Stack gap="sm">
            <Text size="sm" c="dimmed">Executam a máquina de estados da demonstração e acrescentam eventos simulados. Não alteram dispositivos reais.</Text>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
              {scenarios.map(({ id, label, description, consequence, icon: Icon }) => <Paper key={id} withBorder radius="md" p="sm">
                <Group justify="space-between" align="flex-start" mb="xs"><Group gap="xs"><Icon size={18} /><div><Text size="sm" fw={600}>{label}</Text><Text size="xs" c="dimmed">{description}</Text></div></Group><Badge size="xs" color="yellow" variant="light">SIM</Badge></Group>
                <Text size="xs" mb="sm">{consequence}</Text>
                <Button size="xs" variant="light" fullWidth leftSection={<IconCheck size={14} />} onClick={() => simulateScenario(id)}>Executar cenário</Button>
              </Paper>)}
            </SimpleGrid>
          </Stack>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion> : null}

    <Alert icon={<IconAlertCircle size={18} />} color="teal" variant="light" title="Privacidade">
      O processamento é local. Os frames não são gravados e não é feito reconhecimento facial.
    </Alert>
  </Stack>;
}
