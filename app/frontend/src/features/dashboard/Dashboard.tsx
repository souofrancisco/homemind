import { Accordion, Alert, Badge, Button, Card, Group, Loader, Modal, NumberFormatter, SimpleGrid, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconBolt, IconBulb, IconHome, IconPower, IconTimeline } from "@tabler/icons-react";
import { useState } from "react";
import { getHomeService } from "./homeApi";
import { useHomeSocket } from "./useHomeSocket";
import type { EventLogItem, HomeStatus } from "./types";

const service = getHomeService();
const statusLabels: Record<HomeStatus, string> = { inativo: "Inativo", ativo: "Ativo", em_espera: "Em espera", suspenso: "Suspenso" };
const modeLabels: Record<string, string> = { leitura: "Leitura", cinema: "Cinema", cafe: "Pausa para café" };
const resultLabels: Record<NonNullable<EventLogItem["result"]>, string> = { verified: "Confirmado", failed: "Falhou", unverified: "Sem confirmação", unsupported: "Não disponível" };
const when = (value: string) => new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));

export default function Dashboard() {
  const { state, events, online, source } = useHomeSocket();
  const [powerOpened, powerModal] = useDisclosure(false);
  const [busy, setBusy] = useState(false);
  const simulated = source === "mock" || state?.backend === "fake";
  const lastDecision = events.find((event) => event.category === "mode" || event.category === "rule" || /modo .* ativ(?:ado|o)|regra aplicad|regra escolhida/i.test(event.message));

  const turnOff = async () => {
    setBusy(true);
    try {
      const result = await service.turnOff();
      notifications.show({ color: result.success ? "teal" : "orange", title: result.success ? result.backend === "fake" ? "Demonstração concluída" : "Pedido concluído" : "Resultado incompleto", message: result.message });
      if (result.success) powerModal.close();
    } catch {
      notifications.show({ color: "red", title: "Não foi possível desligar", message: "Tenta novamente mais tarde." });
    } finally { setBusy(false); }
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center" wrap="wrap">
        <Title order={2}>Início</Title>
        <Button color="red" leftSection={<IconPower size={18} />} onClick={powerModal.open}>Desligar tudo</Button>
      </Group>

      {!state ? <Group justify="center" py="xl"><Loader size="sm" /><Text c="dimmed">A carregar o estado da casa…</Text></Group> : null}
      {state && !online ? <Alert color="orange" icon={<IconAlertCircle />} title="Ligação perdida">A mostrar o último estado recebido.</Alert> : null}

      {state ? <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
        <Card withBorder radius="lg">
          <Group justify="space-between"><Text c="dimmed" size="sm">Modo</Text><IconHome size={19} /></Group>
          <Title order={3} mt="sm">{state.mode_name ?? modeLabels[state.mode ?? ""] ?? "Sem modo ativo"}</Title>
          <Badge mt="xs" color={state.state === "ativo" ? "teal" : state.state === "em_espera" ? "yellow" : "gray"}>{statusLabels[state.state]}</Badge>
        </Card>
        <Card withBorder radius="lg">
          <Group justify="space-between"><Text c="dimmed" size="sm">Presença</Text><span aria-hidden="true">◉</span></Group>
          <Title order={3} mt="sm">{state.presence === null ? "Sem dados" : state.presence ? "Presença detetada" : "Sem presença"}</Title>
        </Card>
        <Card withBorder radius="lg">
          <Group justify="space-between"><Text c="dimmed" size="sm">Luz</Text><ThemeIcon size="sm" variant="light" color="yellow"><IconBulb size={16} /></ThemeIcon></Group>
          <Title order={3} mt="sm">{state.casa?.lampada ? (state.casa.lampada.ligada ? "Ligada" : "Desligada") : "Sem dados"}</Title>
          {state.casa?.lampada?.brilho != null ? <Text size="sm" c="dimmed">{state.casa.lampada.brilho}%</Text> : null}
        </Card>
        <Card withBorder radius="lg">
          <Group justify="space-between"><Text c="dimmed" size="sm">Última decisão</Text><IconTimeline size={19} /></Group>
          {lastDecision ? <><Text fw={600} mt="sm">{lastDecision.message}</Text><Group mt="xs" gap="xs"><Text size="sm" c="dimmed">{when(lastDecision.timestamp)}</Text>{lastDecision.result ? <Badge color={resultColor(lastDecision.result)}>{resultLabels[lastDecision.result]}</Badge> : null}</Group></> : <Text c="dimmed" mt="sm">Ainda não há decisões.</Text>}
        </Card>
      </SimpleGrid> : null}

      <Accordion variant="separated" radius="lg">
        <Accordion.Item value="more">
          <Accordion.Control>Mais detalhes</Accordion.Control>
          <Accordion.Panel>
            {state ? <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
              <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Poupança estimada</Text><IconBolt size={19} /></Group><Title order={3} mt="sm"><NumberFormatter value={state.energy_saved_wh} decimalScale={1} suffix=" Wh" /></Title><Text size="sm" c="dimmed"><NumberFormatter value={state.energy_saved_eur} decimalScale={3} prefix="€" /> · estimativa desta sessão</Text></Card>
              <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Temporizador</Text><Text size="sm">{state.waiting_remaining_seconds != null ? `${state.waiting_remaining_seconds} s` : "—"}</Text></Group><Title order={3} mt="sm">{state.waiting_remaining_seconds != null ? "Até suspender" : "Sem espera ativa"}</Title></Card>
              <Card withBorder radius="lg"><Text fw={600} mb="sm">Estado da casa</Text><Group gap="xs"><Badge color={state.camera_ok ? "teal" : "gray"}>Câmara {state.camera_ok ? "disponível" : "indisponível"}</Badge><Badge color={state.mcp_ok ? "teal" : "gray"}>Ligação aos dispositivos {state.mcp_ok ? "disponível" : "indisponível"}</Badge><Badge color={online ? "teal" : "red"}>Serviço {online ? "ligado" : "indisponível"}</Badge></Group></Card>
            </SimpleGrid> : <Text c="dimmed">Os detalhes aparecem quando houver informação disponível.</Text>}
            {state?.casa?.tomada?.consumo_w != null ? <Text size="sm" mt="md">Consumo medido: {state.casa.tomada.consumo_w} W{state.casa.tomada.consumo_lido_em ? ` · leitura às ${when(state.casa.tomada.consumo_lido_em)}` : ""}</Text> : null}
            {state?.casa?.aviso ? <Alert color="orange" mt="md">{state.casa.aviso}</Alert> : null}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Modal opened={powerOpened} onClose={powerModal.close} title="Desligar tudo?" centered>
        <Stack><Alert color="orange" icon={<IconAlertCircle />}>{simulated ? "Esta ação é uma demonstração e não altera dispositivos físicos." : "O pedido será enviado à casa. Só será apresentado como concluído após confirmação."}</Alert><Text>Confirma que quer desligar os dispositivos controlados?</Text><Group justify="flex-end"><Button variant="default" onClick={powerModal.close}>Cancelar</Button><Button color="red" loading={busy} onClick={() => void turnOff()}>Confirmar</Button></Group></Stack>
      </Modal>
    </Stack>
  );
}

function resultColor(result: NonNullable<EventLogItem["result"]>) {
  if (result === "verified") return "teal";
  if (result === "failed") return "red";
  if (result === "unsupported") return "gray";
  return "yellow";
}
