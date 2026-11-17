import {
  Accordion,
  Alert,
  Avatar,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconBook2,
  IconCoffee,
  IconDownload,
  IconLogout,
  IconMovie,
  IconShieldLock,
  IconSparkles,
} from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { getMe, type Me } from "../auth/api";
import { demoSuggestionDecisions, demoSuggestions } from "../dashboard/demoSuggestions";
import { useHomeSocket } from "../dashboard/useHomeSocket";
import type { MemorySnapshot } from "../dashboard/types";

function memoryMarkdown(memory: MemorySnapshot) {
  return [
    "# ObjectOS — hábitos e privacidade",
    "",
    "> Este resumo contém apenas exemplos da sessão de demonstração. Não representa gostos confirmados nem dados guardados permanentemente.",
    "",
    `- Aprendizagem nesta sessão: ${memory.learningEnabled ? "ativa" : "inativa"}`,
    `- Eventos de exemplo: ${memory.observedEvents.length}`,
    `- Padrões de exemplo: ${memory.inferredPatterns.length}`,
    "",
    "## Padrões de exemplo",
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
    "## Eventos de exemplo",
    ...(memory.observedEvents.length
      ? memory.observedEvents.map((event) => `- ${new Date(event.occurredAt).toLocaleString("pt-PT")} — ${event.text} [EXEMPLO]`)
      : ["Nenhum evento de exemplo." ]),
    "",
  ].join("\n");
}

function SectionTitle({ id, title, description }: { id: string; title: string; description?: string }) {
  return (
    <div>
      <Title id={id} order={3}>{title}</Title>
      {description && <Text size="sm" c="dimmed" mt={4}>{description}</Text>}
    </div>
  );
}

const patternIcons = {
  "pattern-reading-evening": IconBook2,
  "pattern-coffee-entry": IconCoffee,
  "pattern-cinema-weekend": IconMovie,
};

export default function Account() {
  const { logout } = useAuth();
  const { source } = useHomeSocket();
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState(false);
  const [learningEnabled, setLearningEnabled] = useState(true);

  useEffect(() => { getMe().then(setMe).catch(() => setFailed(true)); }, []);

  const simulated = source === "mock";
  const memory = useMemo<MemorySnapshot>(() => ({
    profileId: "demo-profile",
    updatedAt: new Date().toISOString(),
    learningEnabled,
    observedEvents: simulated ? [
      { id: "obs-book", occurredAt: "2026-11-14T21:12:00Z", text: "Livro levantado e modo Leitura ativado", source: "fake" },
      { id: "obs-mug", occurredAt: "2026-11-15T08:33:00Z", text: "Presença seguida de deteção de caneca", source: "fake" },
      { id: "obs-remote", occurredAt: "2026-11-16T20:47:00Z", text: "Comando levantado e modo Cinema ativado", source: "fake" },
    ] : [],
    inferredPatterns: simulated && learningEnabled ? demoSuggestions.map(({ id, statement, frequency, timeWindow, evidence }) => ({
      id, statement, frequency, timeWindow, evidence, simulated: true as const,
    })) : [],
    confirmedPreferences: [],
    pendingSuggestions: demoSuggestions.filter((item) => !demoSuggestionDecisions.has(item.id)).map((item) => item.title),
    ignoredSuggestions: demoSuggestions.filter((item) => demoSuggestionDecisions.has(item.id)).map((item) => item.title),
  }), [learningEnabled, simulated]);

  const exportMemory = () => {
    const url = URL.createObjectURL(new Blob([memoryMarkdown(memory)], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "objectos-habitos.md";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    notifications.show({ color: "teal", message: "Resumo Markdown exportado para este dispositivo." });
  };

  return (
    <Stack gap="xl" maw={760} mx="auto">
      <div>
        <Text c="dimmed" size="sm">A TUA CASA, AO TEU RITMO</Text>
        <Title order={2}>Perfil</Title>
      </div>

      <section aria-labelledby="account-title">
        <SectionTitle id="account-title" title="Conta" />
        <Stack gap="sm" mt="sm">
          <Card withBorder radius="lg" p="md">
            {failed ? (
              <Alert color="red" variant="light">Não foi possível carregar os dados da conta.</Alert>
            ) : me ? (
              <Group wrap="nowrap" align="flex-start">
                <Avatar radius="xl" size={48} color="teal">{(me.name ?? me.username ?? "U").slice(0, 1).toUpperCase()}</Avatar>
                <Stack gap={2} style={{ minWidth: 0 }}>
                  <Text fw={600} size="lg">{me.name ?? me.username ?? "Utilizador"}</Text>
                  {me.email && <Text size="sm" c="dimmed" style={{ overflowWrap: "anywhere" }}>{me.email}</Text>}
                </Stack>
              </Group>
            ) : (
              <Group><Loader size="sm" /><Text size="sm" c="dimmed">A carregar conta…</Text></Group>
            )}
          </Card>

          <Card withBorder radius="lg" p={0}>
            <Accordion variant="transparent">
              <Accordion.Item value="preferences">
                <Accordion.Control icon={<ThemeIcon variant="light" radius="xl"><IconShieldLock size={16} /></ThemeIcon>}>
                  <Text fw={500}>Preferências confirmadas</Text>
                </Accordion.Control>
                <Accordion.Panel>
                  {memory.confirmedPreferences.length ? (
                    <Stack gap="xs">
                      {memory.confirmedPreferences.map((item) => <Text size="sm" key={item.id}>{item.statement}</Text>)}
                    </Stack>
                  ) : (
                    <Text size="sm" c="dimmed">Ainda não confirmaste preferências.</Text>
                  )}
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
          </Card>

          <Button leftSection={<IconLogout size={17} />} onClick={() => logout()} variant="subtle" color="red" w="fit-content">
            Terminar sessão
          </Button>
        </Stack>
      </section>

      <section aria-labelledby="habits-title">
        <SectionTitle id="habits-title" title="Os teus hábitos" description="Padrões que podem ajudar a casa a acompanhar o teu ritmo." />
        <Stack gap="sm" mt="sm">
          {simulated && (
            <Alert color="gray" variant="light" icon={<IconSparkles size={18} />}>
              Exemplos desta demonstração. Não são hábitos reais nem preferências confirmadas.
            </Alert>
          )}
          {memory.inferredPatterns.length ? memory.inferredPatterns.map((pattern) => {
            const suggestion = demoSuggestions.find((item) => item.id === pattern.id);
            const HabitIcon = patternIcons[pattern.id as keyof typeof patternIcons] ?? IconSparkles;

            return (
              <Card withBorder radius="lg" p="md" key={pattern.id}>
                <Group align="flex-start" wrap="nowrap">
                  <ThemeIcon size={42} radius="xl" variant="light" color="teal"><HabitIcon size={21} /></ThemeIcon>
                  <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
                    <Text fw={600}>{suggestion?.title ?? "Padrão observado"}</Text>
                    <Text size="sm" c="dimmed">{pattern.statement}</Text>
                    <Text size="xs" c="dimmed">{pattern.frequency} · {pattern.timeWindow}</Text>
                  </Stack>
                </Group>
                <Accordion variant="transparent" mt="xs">
                  <Accordion.Item value={pattern.id}>
                    <Accordion.Control>Ver detalhes</Accordion.Control>
                    <Accordion.Panel>
                      <Stack gap="xs">
                        {suggestion?.explanation && <Text size="sm">{suggestion.explanation}</Text>}
                        <Text size="xs" fw={600}>Eventos relacionados</Text>
                        {pattern.evidence.map((evidence) => <Text size="sm" c="dimmed" key={evidence}>{evidence}</Text>)}
                        <Text size="xs" c="dimmed">Este padrão não altera as tuas preferências.</Text>
                      </Stack>
                    </Accordion.Panel>
                  </Accordion.Item>
                </Accordion>
              </Card>
            );
          }) : (
            <Card withBorder radius="lg" p="md">
              <Text size="sm" c="dimmed">Ainda não há hábitos observados nesta sessão.</Text>
            </Card>
          )}
        </Stack>
      </section>

      <section aria-labelledby="privacy-title">
        <SectionTitle id="privacy-title" title="Privacidade" description="Tu decides como os teus dados são usados." />
        <Stack gap="sm" mt="sm">
          <Card withBorder radius="lg" p="md">
            <Group justify="space-between" align="center" wrap="nowrap">
              <Stack gap={3}>
                <Text fw={500}>Aprendizagem por eventos</Text>
                <Text size="sm" c="dimmed">{simulated ? "Controla os exemplos apenas nesta sessão." : "A aprendizagem ainda não está disponível nesta conta."}</Text>
              </Stack>
              <Switch
                checked={learningEnabled}
                onChange={(event) => setLearningEnabled(event.currentTarget.checked)}
                aria-label="Apresentar exemplos de hábitos nesta sessão"
                disabled={!simulated}
              />
            </Group>
          </Card>

          <Card withBorder radius="lg" p={0}>
            <Accordion variant="transparent">
              <Accordion.Item value="data">
                <Accordion.Control>
                  <Stack gap={2}>
                    <Text fw={500}>Dados utilizados</Text>
                    <Text size="xs" c="dimmed">{simulated ? `${memory.observedEvents.length} eventos de exemplo` : "Eventos da sessão"}</Text>
                  </Stack>
                </Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="xs">
                    <Text size="sm" c="dimmed">{simulated ? "Eventos de exemplo e dados essenciais da tua conta. Estes eventos não são observações reais." : "Eventos disponíveis e dados essenciais da tua conta."}</Text>
                    {memory.observedEvents.map((event) => (
                      <Group key={event.id} gap="xs" wrap="nowrap" align="flex-start">
                        <ThemeIcon size={22} variant="light" color="gray" radius="xl"><IconShieldLock size={13} /></ThemeIcon>
                        <Text size="sm">{event.text}</Text>
                      </Group>
                    ))}
                    {!simulated && <Text size="sm" c="dimmed">Ainda não há eventos disponíveis para esta conta.</Text>}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
          </Card>

          <Button leftSection={<IconDownload size={17} />} variant="light" onClick={exportMemory} w="fit-content">
            Exportar dados em Markdown
          </Button>

          <Divider />
          <Group gap="xs" align="flex-start" wrap="nowrap">
            <ThemeIcon variant="light" color="gray" radius="xl"><IconShieldLock size={16} /></ThemeIcon>
            <Stack gap={3}>
              <Text size="sm" fw={500}>Eliminação de dados</Text>
              <Text size="sm" c="dimmed">A eliminação ainda não está disponível. Os exemplos desta sessão desaparecem ao terminar.</Text>
            </Stack>
          </Group>
        </Stack>
      </section>
    </Stack>
  );
}
