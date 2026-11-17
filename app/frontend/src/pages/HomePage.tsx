import { Alert, Badge, Button, Card, Group, Loader, Modal, NumberFormatter, Paper, SimpleGrid, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconAutomation, IconBolt, IconBulb, IconCamera, IconHome, IconPower, IconTimeline } from "@tabler/icons-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHome } from "../hooks/useHome";
import { homeService } from "../services/home";
import type { HomeStatus } from "../types/home";

const statusLabels: Record<HomeStatus, string> = { inativo: "Inativo", ativo: "Ativo", em_espera: "Em espera", suspenso: "Suspenso" };
const modeLabels: Record<string, string> = { leitura: "Leitura", cinema: "Cinema", cafe: "Pausa para café" };
const when = (value: string) => new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));

export default function HomePage() {
  const { state, events, online, source } = useHome();
  const navigate = useNavigate();
  const [powerOpened, powerModal] = useDisclosure(false);
  const [busy, setBusy] = useState(false);
  const simulated = source === "mock" || state?.backend === "fake";
  const lastDecision = events.find((event) => event.category === "mode" || event.category === "rule" || /modo .* ativado|regra aplicada/i.test(event.message));

  const turnOff = async () => {
    setBusy(true);
    try {
      const result = await homeService.turnOff();
      notifications.show({ color: result.success ? "teal" : "orange", title: result.success ? "Pedido concluído" : "Resultado incompleto", message: result.message });
      if (result.success) powerModal.close();
    } catch (error) {
      notifications.show({ color: "red", title: "Não foi possível desligar", message: error instanceof Error ? error.message : "Serviço indisponível" });
    } finally { setBusy(false); }
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div><Text c="dimmed" size="sm">ESPAÇO · DEMONSTRAÇÃO</Text><Title order={2}>A casa, num relance</Title><Text c="dimmed">Estado atual e decisões recentes do ObjectOS.</Text></div>
        <Badge size="lg" color={simulated ? "yellow" : "teal"} variant="light">{simulated ? "SIMULADO" : "REAL · MCP"}</Badge>
      </Group>

      {!state ? <Group justify="center" py="xl"><Loader size="sm" /><Text c="dimmed">A carregar o estado da casa…</Text></Group> : null}
      {state && !online ? <Alert color="orange" icon={<IconAlertCircle />} title="Ligação indisponível">A mostrar o último estado recebido. A reconexão está ativa.</Alert> : null}

      {state ? <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
        <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Modo da casa</Text><IconHome size={19} /></Group><Title order={3} mt="sm">{state.mode_name ?? modeLabels[state.mode ?? ""] ?? "Sem modo ativo"}</Title><Badge mt="xs" color={state.state === "ativo" ? "teal" : state.state === "em_espera" ? "yellow" : "gray"}>{statusLabels[state.state]}</Badge></Card>
        <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Presença</Text><span aria-hidden="true">◉</span></Group><Title order={3} mt="sm">{state.presence === null ? "Sem dados" : state.presence ? "Presença detetada" : "Sem presença"}</Title><Text size="sm" c="dimmed" mt="xs">Binária e sem identificação pessoal.</Text></Card>
        <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Poupança estimada</Text><IconBolt size={19} /></Group><Title order={3} mt="sm"><NumberFormatter value={state.energy_saved_wh} decimalScale={1} suffix=" Wh" /></Title><Text size="sm" c="dimmed"><NumberFormatter value={state.energy_saved_eur} decimalScale={3} prefix="€" /> · estimativa da sessão</Text></Card>
        <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Temporizador</Text><Text size="sm">{state.waiting_remaining_seconds != null ? `${state.waiting_remaining_seconds} s` : "—"}</Text></Group><Title order={3} mt="sm">{state.waiting_remaining_seconds != null ? "Até suspender" : "Sem espera ativa"}</Title><Text size="sm" c="dimmed" mt="xs">Estado da máquina: {statusLabels[state.state]}.</Text></Card>
      </SimpleGrid> : null}

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder radius="lg">
          <Group justify="space-between" mb="md"><div><Title order={4}>Luz da casa</Title><Text size="sm" c="dimmed">Representação simples do modo ativo</Text></div><ThemeIcon size={42} radius="xl" variant="light" color={state?.mode ? "yellow" : "gray"}><IconBulb size={22} /></ThemeIcon></Group>
          <Paper withBorder radius="md" p="lg" bg={state?.mode === "cinema" ? "dark.8" : state?.mode ? "yellow.0" : undefined}>
            <Group justify="space-between" align="center"><div><Text fw={600}>Sala</Text><Text size="sm" c="dimmed">{state?.casa?.lampada ? `Luz ${state.casa.lampada.ligada ? "ligada" : "desligada"}${state.casa.lampada.brilho != null ? ` · ${state.casa.lampada.brilho}%` : ""}` : state?.mode ? `Iluminação ajustada para ${state.mode_name ?? modeLabels[state.mode] ?? state.mode}` : "Iluminação em repouso"}</Text></div><Badge color={state?.casa?.lampada?.ligada || state?.mode ? "yellow" : "gray"} variant="light">{state?.casa?.lampada?.ligada || state?.mode ? "ACESO" : "EM REPOUSO"}</Badge></Group>
          </Paper>
          {state?.casa?.tomada?.consumo_w != null ? <Text size="sm" mt="sm">Consumo medido: {state.casa.tomada.consumo_w} W{state.casa.tomada.consumo_lido_em ? ` · leitura ${when(state.casa.tomada.consumo_lido_em)}` : ""}</Text> : null}
          <Text size="xs" c="dimmed" mt="xs">A poupança apresentada é estimada{simulated ? " e simulada" : ""}; não é uma medição do contador.</Text>
          <Group mt="md" gap="xs"><Badge color={state?.camera_ok ? "teal" : "gray"} leftSection={<IconCamera size={12} />}>Câmara {state?.camera_ok ? "ligada" : "sem sinal"}</Badge><Badge color={state?.mcp_ok ? "teal" : "gray"}>MCP {state?.mcp_ok ? "ligado" : "indisponível"}</Badge><Badge color={online ? "teal" : "red"}>Backend {online ? "ligado" : "offline"}</Badge></Group>
          {state?.casa?.aviso ? <Alert color="orange" mt="sm">{state.casa.aviso}</Alert> : null}
        </Card>
        <Card withBorder radius="lg">
          <Group justify="space-between" mb="md"><div><Title order={4}>Última decisão</Title><Text size="sm" c="dimmed">O que aconteceu e porquê</Text></div><IconTimeline size={20} /></Group>
          {lastDecision ? <><Text fw={600}>{lastDecision.message}</Text><Text size="sm" c="dimmed" mt="xs">{lastDecision.details ? Object.entries(lastDecision.details).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") : `Registado às ${when(lastDecision.timestamp)}.`}</Text><Badge mt="sm" color={lastDecision.source === "fake" ? "yellow" : "teal"}>{lastDecision.source === "fake" ? "SIMULADO" : "REAL"}</Badge></> : <Text c="dimmed">Ainda não há decisões registadas.</Text>}
        </Card>
      </SimpleGrid>

      <Card withBorder radius="lg">
        <Title order={4} mb="md">Acesso rápido</Title>
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Button h="auto" py="md" variant="light" leftSection={<IconCamera size={18} />} onClick={() => navigate("/camera")}>Câmara</Button>
          <Button h="auto" py="md" variant="light" leftSection={<IconTimeline size={18} />} onClick={() => navigate("/events")}>Eventos</Button>
          <Button h="auto" py="md" variant="light" leftSection={<IconAutomation size={18} />} onClick={() => navigate("/automations")}>Automações</Button>
          <Button h="auto" py="md" variant="light" leftSection={<IconPower size={18} />} color="red" onClick={powerModal.open}>Desligar tudo</Button>
        </SimpleGrid>
      </Card>

      <Modal opened={powerOpened} onClose={powerModal.close} title="Desligar tudo?" centered>
        <Stack><Alert color="orange" icon={<IconAlertCircle />}>{simulated ? "Esta ação é simulada e não altera dispositivos físicos." : "O pedido será enviado ao backend. Só será apresentado como concluído após confirmação explícita."}</Alert><Text>Confirma que quer desligar os dispositivos controlados?</Text><Group justify="flex-end"><Button variant="default" onClick={powerModal.close}>Cancelar</Button><Button color="red" loading={busy} onClick={() => void turnOff()}>Confirmar</Button></Group></Stack>
      </Modal>
    </Stack>
  );
}
