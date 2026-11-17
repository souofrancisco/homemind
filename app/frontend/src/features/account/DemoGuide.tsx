import { Accordion, Alert, Badge, Group, Stack, Text } from "@mantine/core";
import { useHomeSocket } from "../dashboard/useHomeSocket";

const steps = [
  { title: "Confirmar o modo", screen: "Dashboard", description: "Mostrar se a origem apresentada pela aplicação é SIMULADA ou REAL · MCP antes de explicar qualquer resultado." },
  { title: "Detetar o livro", screen: "Dashboard · Eventos", description: "Apontar para o evento de deteção do livro e confirmar a origem indicada no registo." },
  { title: "Mostrar modo Leitura", screen: "Dashboard", description: "Explicar como o modo Leitura aparece no estado atual e que resposta da casa lhe está associada." },
  { title: "Consultar o evento", screen: "Eventos", description: "Abrir o registo correspondente para mostrar hora, origem e resultado observável." },
  { title: "Mostrar uma automação", screen: "Automações", description: "Apresentar a regra de demonstração e explicar que guardar uma regra não a ativa por si só." },
  { title: "Demonstrar ausência e suspensão", screen: "Dashboard · Eventos", description: "Mostrar a ausência detetada, o tempo de espera e o evento de suspensão, se estiverem disponíveis." },
  { title: "Mostrar o regresso", screen: "Dashboard · Eventos", description: "Apontar para a presença detetada e para o estado após o regresso." },
  { title: "Demonstrar Desligar tudo", screen: "Dashboard", description: "Explicar o controlo e mostrar o resultado apenas com a confirmação manual do apresentador." },
];

export default function DemoGuide() {
  const { source } = useHomeSocket();
  const simulated = source === "mock";

  return (
    <Accordion variant="separated">
      <Accordion.Item value="demo-guide">
        <Accordion.Control>
          <Group justify="space-between" align="center" wrap="wrap" pr="sm">
            <div><Text c="dimmed" size="xs">GUIA DE APRESENTAÇÃO</Text><Text fw={600}>Percurso da demonstração</Text></div>
            <Badge color="gray" variant="light">{simulated ? "MODO SIMULADO" : "MODO API · CONFIRMAR MCP"}</Badge>
          </Group>
        </Accordion.Control>
        <Accordion.Panel>
          <Stack gap="sm">
            <Text size="sm" c="dimmed">Lista de consulta para o apresentador; não executa ações nem muda de ecrã.</Text>
            <Alert color="blue" variant="light">
              Antes de começar, confirma a origem visível no Dashboard. Uma origem API só deve ser descrita como REAL · MCP se a ligação ao hardware estiver efetivamente confirmada.
            </Alert>
            <Accordion variant="separated">
              {steps.map((step, index) => (
                <Accordion.Item value={`step-${index + 1}`} key={step.title}>
                  <Accordion.Control>
                    <Group wrap="nowrap" gap="sm">
                      <Badge size="sm" variant="light" circle>{index + 1}</Badge>
                      <Text size="sm" fw={500}>{step.title}</Text>
                    </Group>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Stack gap={4}>
                      <Text size="sm">{step.description}</Text>
                      <Text size="xs" c="dimmed">Ecrã: {step.screen}</Text>
                    </Stack>
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          </Stack>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
