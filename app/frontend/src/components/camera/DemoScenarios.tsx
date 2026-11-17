import { Accordion, Badge, Button, Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { IconBook2, IconCamera, IconCheck, IconCoffee, IconDeviceTv, IconMoon, IconPlugConnectedX, IconUserCheck } from "@tabler/icons-react";
import { simulateScenario, type DemoScenario } from "../../mocks/home";

const scenarios: { id: DemoScenario; label: string; description: string; consequence: string; icon: typeof IconCamera }[] = [
  { id: "book", label: "Livro", description: "Gesto de leitura", consequence: "Ativa o modo Leitura.", icon: IconBook2 },
  { id: "remote", label: "Comando", description: "Preparar cinema", consequence: "Ativa a Noite de cinema.", icon: IconDeviceTv },
  { id: "mug", label: "Caneca", description: "Pausa para café", consequence: "Ativa o modo Café.", icon: IconCoffee },
  { id: "absence", label: "Ausência", description: "Iniciar espera", consequence: "Suspende a casa após a espera.", icon: IconMoon },
  { id: "return", label: "Regresso", description: "Presença detetada", consequence: "Restaura o estado anterior.", icon: IconUserCheck },
  { id: "connection", label: "Ligação", description: "Interromper e recuperar", consequence: "Mostra a perda e recuperação do backend.", icon: IconPlugConnectedX },
];

export default function DemoScenarios() {
  return <Accordion variant="separated" radius="md">
    <Accordion.Item value="scenarios">
      <Accordion.Control><Group gap="sm"><Text fw={600}>Cenários de demonstração</Text><Badge color="yellow" variant="light">{scenarios.length}</Badge></Group></Accordion.Control>
      <Accordion.Panel>
        <Stack gap="sm">
          <Text size="sm" c="dimmed">Executam a máquina de estados da demonstração e acrescentam eventos de exemplo. Não alteram dispositivos reais.</Text>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {scenarios.map(({ id, label, description, consequence, icon: Icon }) => <Paper key={id} withBorder radius="md" p="sm">
              <Group gap="xs" mb="xs"><Icon size={18} /><div><Text size="sm" fw={600}>{label}</Text><Text size="xs" c="dimmed">{description}</Text></div></Group>
              <Text size="xs" mb="sm">{consequence}</Text>
              <Button size="xs" variant="light" fullWidth leftSection={<IconCheck size={14} />} onClick={() => simulateScenario(id)}>Executar cenário</Button>
            </Paper>)}
          </SimpleGrid>
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  </Accordion>;
}
