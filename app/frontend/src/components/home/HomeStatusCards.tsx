import { Badge, Card, Group, SimpleGrid, Text, ThemeIcon, Title } from "@mantine/core";
import { IconBulb, IconHome, IconTimeline } from "@tabler/icons-react";
import { resultColor, resultLabels } from "../../utils/events";
import { formatHM } from "../../utils/format";
import type { EventLogItem, HomeState, HomeStatus } from "../../types/home";

const statusLabels: Record<HomeStatus, string> = { inativo: "Inativo", ativo: "Ativo", em_espera: "Em espera", suspenso: "Suspenso" };
const modeLabels: Record<string, string> = { leitura: "Leitura", cinema: "Cinema", cafe: "Pausa para café" };

export default function HomeStatusCards({ state, lastDecision }: { state: HomeState; lastDecision?: EventLogItem }) {
  return <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
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
      <Title order={3} mt="sm">{state.casa?.lampada?.ligada == null ? "Sem dados" : state.casa.lampada.ligada ? "Ligada" : "Desligada"}</Title>
      {state.casa?.lampada?.brilho != null ? <Text size="sm" c="dimmed">{state.casa.lampada.brilho}%</Text> : null}
    </Card>
    <Card withBorder radius="lg">
      <Group justify="space-between"><Text c="dimmed" size="sm">Última decisão</Text><IconTimeline size={19} /></Group>
      {lastDecision ? <><Text fw={600} mt="sm">{lastDecision.message}</Text><Group mt="xs" gap="xs"><Text size="sm" c="dimmed">{formatHM(lastDecision.timestamp)}</Text>{lastDecision.result ? <Badge color={resultColor(lastDecision.result)}>{resultLabels[lastDecision.result]}</Badge> : null}</Group></> : <Text c="dimmed" mt="sm">Ainda não há decisões.</Text>}
    </Card>
  </SimpleGrid>;
}
