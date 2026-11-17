import { Accordion, Badge, Button, Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { IconBook2, IconCamera, IconCheck, IconCoffee, IconDeviceTv, IconMoon, IconUserCheck } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { homeService } from "../../services/home";
import type { ScenarioId } from "../../types/home";

const scenarios: { id: ScenarioId; label: string; description: string; consequence: string; icon: typeof IconCamera }[] = [
  { id: "book", label: "Livro", description: "Gesto de leitura", consequence: "Se houver uma regra ativa para livro, aplica-a.", icon: IconBook2 },
  { id: "remote", label: "Comando", description: "Preparar cinema", consequence: "Se houver uma regra ativa para comando, aplica-a.", icon: IconDeviceTv },
  { id: "mug", label: "Caneca", description: "Pausa para café", consequence: "Se houver uma regra ativa para caneca, aplica-a.", icon: IconCoffee },
  { id: "absence", label: "Ausência", description: "Iniciar espera", consequence: "Inicia a espera; suspende após o tempo configurado.", icon: IconMoon },
  { id: "return", label: "Regresso", description: "Presença detetada", consequence: "Cancela a espera ou restaura o estado anterior.", icon: IconUserCheck },
];

const run = (id: ScenarioId) => homeService.simulate(id).catch((error: unknown) =>
  notifications.show({ color: "red", title: "Cenário não executado", message: error instanceof Error ? error.message : "Serviço indisponível" }));

export default function DemoScenarios() {
  return <Accordion variant="separated" radius="md">
    <Accordion.Item value="scenarios">
      <Accordion.Control><Group gap="sm"><Text fw={600}>Cenários de demonstração</Text><Badge color="yellow" variant="light">{scenarios.length}</Badge></Group></Accordion.Control>
      <Accordion.Panel>
        <Stack gap="sm">
          <Text size="sm" c="dimmed">Injetam um evento simulado no motor do backend (aparece no registo como [SIMULADO]). Só com FakeHome; não alteram dispositivos físicos.</Text>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {scenarios.map(({ id, label, description, consequence, icon: Icon }) => <Paper key={id} withBorder radius="md" p="sm">
              <Group gap="xs" mb="xs"><Icon size={18} /><div><Text size="sm" fw={600}>{label}</Text><Text size="xs" c="dimmed">{description}</Text></div></Group>
              <Text size="xs" mb="sm">{consequence}</Text>
              <Button size="xs" variant="light" fullWidth leftSection={<IconCheck size={14} />} onClick={() => void run(id)}>Executar cenário</Button>
            </Paper>)}
          </SimpleGrid>
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  </Accordion>;
}
