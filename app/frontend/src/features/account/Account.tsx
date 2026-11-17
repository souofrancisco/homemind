import {
  Accordion,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Switch,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDownload, IconLogout, IconShieldLock } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { getMe, type Me } from "../auth/api";
import { demoSuggestionDecisions, demoSuggestions } from "../dashboard/demoSuggestions";
import { useHomeSocket } from "../dashboard/useHomeSocket";
import type { MemorySnapshot } from "../dashboard/types";
import DemoGuide from "./DemoGuide";

function memoryMarkdown(memory: MemorySnapshot) {
  return [
    "# ObjectOS Memory — exemplos de demonstração",
    "",
    "> Este ficheiro contém apenas dados simulados desta sessão. Não representa memória guardada permanentemente.",
    "",
    `- Aprendizagem nesta sessão: ${memory.learningEnabled ? "ativa" : "desativada"}`,
    `- Exemplos de eventos: ${memory.observedEvents.length}`,
    `- Padrões inferidos: ${memory.inferredPatterns.length}`,
    `- Preferências confirmadas: ${memory.confirmedPreferences.length}`,
    "",
    "## Padrões inferidos (simulados)",
    ...(memory.inferredPatterns.length
      ? memory.inferredPatterns.flatMap((pattern) => [
          `### ${pattern.statement}`,
          `- Frequência: ${pattern.frequency}`,
          `- Período: ${pattern.timeWindow}`,
          "- Evidências:",
          ...pattern.evidence.map((evidence) => `  - ${evidence}`),
          "",
        ])
      : ["Nenhum padrão apresentado nesta sessão.", ""]),
    "## Preferências confirmadas",
    ...(memory.confirmedPreferences.length
      ? memory.confirmedPreferences.map((item) => `- ${item.statement} (confirmada em ${item.confirmedAt})`)
      : ["Nenhuma preferência confirmada." ]),
    "",
    "## Eventos de exemplo",
    ...(memory.observedEvents.length
      ? memory.observedEvents.map((event) => `- ${new Date(event.occurredAt).toLocaleString("pt-PT")} — ${event.text} [SIMULADO]`)
      : ["Nenhum evento de exemplo." ]),
    "",
    "## Sugestões nesta sessão",
    `- Pendentes: ${memory.pendingSuggestions.join(", ") || "nenhuma"}`,
    `- Ignoradas: ${memory.ignoredSuggestions.join(", ") || "nenhuma"}`,
    "",
  ].join("\n");
}

function PatternCards({ memory }: { memory: MemorySnapshot }) {
  if (!memory.inferredPatterns.length) {
    return <Text size="sm" c="dimmed">A aprendizagem está desativada nesta sessão. Não há padrões a apresentar.</Text>;
  }

  return (
    <Stack gap="sm">
      {memory.inferredPatterns.map((pattern) => (
        <Card withBorder radius="md" key={pattern.id}>
          <Group justify="space-between" align="flex-start" wrap="wrap">
            <Text fw={600} size="sm">{pattern.statement}</Text>
            <Badge color="yellow" variant="light" size="sm">SIMULADO</Badge>
          </Group>
          <Text size="sm" mt="xs">{pattern.frequency}</Text>
          <Text size="xs" c="dimmed">Período: {pattern.timeWindow}</Text>
          <Accordion variant="contained" radius="sm" mt="sm">
            <Accordion.Item value={pattern.id}>
              <Accordion.Control>Ver evidências</Accordion.Control>
              <Accordion.Panel>
                <Stack gap={4}>
                  {pattern.evidence.map((evidence) => <Text size="xs" key={evidence}>{evidence}</Text>)}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        </Card>
      ))}
    </Stack>
  );
}

export default function Account() {
  const { logout } = useAuth();
  const { source } = useHomeSocket();
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState(false);
  const [learningEnabled, setLearningEnabled] = useState(true);

  useEffect(() => { getMe().then(setMe).catch(() => setFailed(true)); }, []);

  const memory = useMemo<MemorySnapshot>(() => ({
    profileId: "demo-profile",
    updatedAt: new Date().toISOString(),
    learningEnabled,
    observedEvents: [
      { id: "obs-book", occurredAt: "2026-11-14T21:12:00Z", text: "Livro levantado e modo Leitura ativado", source: "fake" },
      { id: "obs-mug", occurredAt: "2026-11-15T08:33:00Z", text: "Presença seguida de deteção de caneca", source: "fake" },
      { id: "obs-remote", occurredAt: "2026-11-16T20:47:00Z", text: "Comando levantado e modo Cinema ativado", source: "fake" },
    ],
    inferredPatterns: learningEnabled ? demoSuggestions.map(({ id, statement, frequency, timeWindow, evidence }) => ({
      id, statement, frequency, timeWindow, evidence, simulated: true as const,
    })) : [],
    confirmedPreferences: [],
    pendingSuggestions: demoSuggestions.filter((item) => !demoSuggestionDecisions.has(item.id)).map((item) => item.title),
    ignoredSuggestions: demoSuggestions.filter((item) => demoSuggestionDecisions.has(item.id)).map((item) => item.title),
  }), [learningEnabled]);
  const simulated = source === "mock";

  const exportMemory = () => {
    const url = URL.createObjectURL(new Blob([memoryMarkdown(memory)], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "objectos-memory-exemplo.md";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    notifications.show({ color: "teal", message: "Exemplos exportados em Markdown para este dispositivo." });
  };

  return (
    <Stack gap="lg">
      <div>
        <Text c="dimmed" size="sm">IDENTIDADE E PRIVACIDADE</Text>
        <Title order={2}>Perfil</Title>
        <Text c="dimmed">Conta, preferências e dados usados nesta sessão.</Text>
      </div>

      <Tabs defaultValue="account" keepMounted={false}>
        <Tabs.List grow>
          <Tabs.Tab value="account">Conta</Tabs.Tab>
          <Tabs.Tab value="preferences">Preferências</Tabs.Tab>
          <Tabs.Tab value="memory">Memória</Tabs.Tab>
          <Tabs.Tab value="privacy">Privacidade</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="account" pt="md">
          <Stack gap="md">
            {failed ? <Alert color="red">Não foi possível obter os dados da conta. A sessão continua ativa.</Alert> : me ? (
              <Card withBorder radius="lg">
                <Group justify="space-between" wrap="nowrap">
                  <div>
                    <Text fw={600}>{me.name ?? me.username}</Text>
                    <Text c="dimmed" size="sm">{me.email}</Text>
                  </div>
                  <IconShieldLock size={22} aria-label="Identidade autenticada" />
                </Group>
              </Card>
            ) : <Group><Loader size="sm" /><Text size="sm" c="dimmed">A carregar conta…</Text></Group>}
            <Button leftSection={<IconLogout size={16} />} onClick={() => logout()} variant="light" color="red" w="fit-content">
              Terminar sessão
            </Button>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="preferences" pt="md">
          <Card withBorder radius="lg">
            <Stack gap="sm">
              <Group justify="space-between" align="flex-start">
                <div><Title order={4}>Preferências confirmadas</Title><Text size="sm" c="dimmed">Só aparecem aqui escolhas confirmadas explicitamente.</Text></div>
                <Badge color="gray" variant="light">{memory.confirmedPreferences.length}</Badge>
              </Group>
              {memory.confirmedPreferences.length ? memory.confirmedPreferences.map((item) => (
                <Text size="sm" key={item.id}>{item.statement} · Confirmada em {item.confirmedAt}</Text>
              )) : <Text size="sm" c="dimmed">Ainda não há preferências confirmadas associadas a esta demonstração.</Text>}
              <Text size="xs" c="dimmed">Os padrões inferidos são sugestões e não alteram as tuas preferências.</Text>
            </Stack>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="memory" pt="md">
          <Stack gap="md">
            <Card withBorder radius="lg">
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start" wrap="wrap">
                  <div><Title order={3}>ObjectOS Memory</Title><Text size="sm" c="dimmed" mt={4}>Exemplos de padrões inferidos a partir de eventos textuais.</Text></div>
                  <Badge color={simulated ? "yellow" : "gray"} variant="light">{simulated ? "EXEMPLOS SIMULADOS" : "MEMÓRIA REAL INDISPONÍVEL"}</Badge>
                </Group>
                {!simulated && <Alert color="blue">A memória real ainda não está ligada a um contrato backend. Os cartões abaixo continuam a usar apenas exemplos simulados.</Alert>}
                <Alert color="gray" variant="light">Uma inferência não é uma preferência confirmada. Os exemplos existem apenas durante esta sessão e não representam armazenamento permanente.</Alert>
                <Switch
                  checked={learningEnabled}
                  onChange={(event) => setLearningEnabled(event.currentTarget.checked)}
                  label="Apresentar padrões inferidos (exemplos)"
                  description="Só controla estes exemplos nesta sessão; não elimina dados já existentes noutros sistemas."
                />
              </Stack>
            </Card>

            <Card withBorder radius="lg">
              <Group justify="space-between" mb="sm">
                <Title order={4}>Padrões observados</Title>
                <Badge color="yellow" variant="light">{memory.inferredPatterns.length}</Badge>
              </Group>
              <PatternCards memory={memory} />
            </Card>

            <Accordion variant="separated">
              <Accordion.Item value="observed-events">
                <Accordion.Control>Eventos textuais de exemplo ({memory.observedEvents.length})</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="xs">
                    {memory.observedEvents.map((event) => (
                      <Group key={event.id} justify="space-between" align="flex-start" wrap="wrap">
                        <Text size="sm">{event.text}</Text>
                        <Badge color="yellow" size="xs">SIMULADO</Badge>
                      </Group>
                    ))}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>

            <Button leftSection={<IconDownload size={16} />} variant="light" onClick={exportMemory}>
              Exportar exemplos em Markdown
            </Button>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="privacy" pt="md">
          <Stack gap="md">
            <Alert color="blue" title="Vídeo e câmara">
              O vídeo é processado localmente para deteção e não é armazenado nem enviado para serviços externos.
            </Alert>
            <Card withBorder radius="lg">
              <Stack gap="sm">
                <Title order={4}>Dados usados nesta demonstração</Title>
                <Text size="sm">• Eventos textuais de deteção de objetos, gestos, presença e modos.</Text>
                <Text size="sm">• Nome de apresentação e email fornecidos pela identidade OIDC para mostrar a conta.</Text>
                <Text size="sm" c="dimmed">Não são apresentados tokens nem credenciais.</Text>
              </Stack>
            </Card>
            <Card withBorder radius="lg">
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start">
                  <div><Title order={4}>Aprendizagem simulada</Title><Text size="sm" c="dimmed">{learningEnabled ? "Exemplos visíveis nesta sessão" : "Exemplos ocultos nesta sessão"}</Text></div>
                  <Badge color={learningEnabled ? "teal" : "gray"} variant="light">{learningEnabled ? "ATIVA" : "INATIVA"}</Badge>
                </Group>
                <Text size="sm">Ocultar os exemplos interrompe apenas a sua apresentação nesta sessão. Isto não equivale a eliminar dados.</Text>
                <Text size="sm">A eliminação de memória real não está disponível: o backend ainda não fornece um pedido ou confirmação de eliminação.</Text>
              </Stack>
            </Card>
          </Stack>
        </Tabs.Panel>
      </Tabs>

      <DemoGuide />
    </Stack>
  );
}
