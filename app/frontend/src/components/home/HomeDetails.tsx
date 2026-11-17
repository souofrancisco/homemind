import { Accordion, Alert, Badge, Card, Group, NumberFormatter, SimpleGrid, Text, Title } from "@mantine/core";
import { IconBolt } from "@tabler/icons-react";
import { formatHM } from "../../utils/format";
import type { HomeState } from "../../types/home";

export default function HomeDetails({ state, online }: { state: HomeState | null; online: boolean }) {
  return <Accordion variant="separated" radius="lg">
    <Accordion.Item value="more">
      <Accordion.Control>Mais detalhes</Accordion.Control>
      <Accordion.Panel>
        {state ? <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Poupança estimada</Text><IconBolt size={19} /></Group><Title order={3} mt="sm"><NumberFormatter value={state.energy_saved_wh} decimalScale={1} suffix=" Wh" /></Title><Text size="sm" c="dimmed"><NumberFormatter value={state.energy_saved_eur} decimalScale={3} prefix="€" /> · estimativa desta sessão</Text></Card>
          <Card withBorder radius="lg"><Group justify="space-between"><Text c="dimmed" size="sm">Temporizador</Text><Text size="sm">{state.waiting_remaining_seconds != null ? `${state.waiting_remaining_seconds} s` : "—"}</Text></Group><Title order={3} mt="sm">{state.waiting_remaining_seconds != null ? "Até suspender" : "Sem espera ativa"}</Title></Card>
          <Card withBorder radius="lg"><Text fw={600} mb="sm">Estado da casa</Text><Group gap="xs"><Badge color={state.camera_ok ? "teal" : "gray"}>Câmara {state.camera_ok ? "disponível" : "indisponível"}</Badge><Badge color={state.mcp_ok ? "teal" : "gray"}>Ligação aos dispositivos {state.mcp_ok ? "disponível" : "indisponível"}</Badge><Badge color={online ? "teal" : "red"}>Serviço {online ? "ligado" : "indisponível"}</Badge></Group></Card>
        </SimpleGrid> : <Text c="dimmed">Os detalhes aparecem quando houver informação disponível.</Text>}
        {state?.casa?.tomada?.consumo_w != null ? <Text size="sm" mt="md">Consumo medido: {state.casa.tomada.consumo_w} W{state.casa.tomada.consumo_lido_em ? ` · leitura às ${formatHM(state.casa.tomada.consumo_lido_em)}` : ""}</Text> : null}
        {state?.casa?.aviso ? <Alert color="orange" mt="md">{state.casa.aviso}</Alert> : null}
      </Accordion.Panel>
    </Accordion.Item>
  </Accordion>;
}
