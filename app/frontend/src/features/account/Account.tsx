import { Alert, Badge, Button, Card, Divider, Group, Loader, Modal, Paper, SimpleGrid, Stack, Switch, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconDownload, IconLogout, IconShieldLock, IconTrash } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { getMe, type Me } from "../auth/api";
import { demoSuggestionDecisions, demoSuggestions } from "../dashboard/demoSuggestions";
import { useHomeSocket } from "../dashboard/useHomeSocket";
import type { MemorySnapshot } from "../dashboard/types";

function memoryMarkdown(memory: MemorySnapshot) {
  return [
    "# ObjectOS Memory", "", `- Perfil: ${memory.profileId}`, `- Atualizada em: ${memory.updatedAt}`, `- Consentimento para aprendizagem: ${memory.learningEnabled ? "ativo (sessão de demonstração)" : "inativo"}`, "",
    "## Padrões observados", ...memory.inferredPatterns.map((pattern) => `- ${pattern.statement} Frequência: ${pattern.frequency}; período: ${pattern.timeWindow}. Evidências: ${pattern.evidence.join("; ")}.`),
    "", "## Preferências confirmadas", ...(memory.confirmedPreferences.length ? memory.confirmedPreferences.map((item) => `- ${item.statement} (${item.confirmedAt})`) : ["- Nenhuma preferência confirmada." ]),
    "", "## Sugestões pendentes ou ignoradas", `- Pendentes: ${memory.pendingSuggestions.join(", ") || "nenhuma"}`, `- Ignoradas: ${memory.ignoredSuggestions.join(", ") || "nenhuma"}`,
    "", "> Exportação de demonstração. Os dados são simulados e não estão guardados no backend.", "",
  ].join("\n");
}

export default function Account() {
  const { logout } = useAuth();
  const { source } = useHomeSocket();
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState(false);
  const [learningEnabled, setLearningEnabled] = useState(true);
  const [deleteOpened, deleteModal] = useDisclosure(false);
  useEffect(() => { getMe().then(setMe).catch(() => setFailed(true)); }, []);

  const memory = useMemo<MemorySnapshot>(() => ({
    profileId: "demo-profile", updatedAt: new Date().toISOString(), learningEnabled,
    observedEvents: [
      { id: "obs-book", occurredAt: "2026-11-14T21:12:00Z", text: "Livro levantado e modo Leitura ativado", source: "fake" },
      { id: "obs-mug", occurredAt: "2026-11-15T08:33:00Z", text: "Presença seguida de deteção de caneca", source: "fake" },
      { id: "obs-remote", occurredAt: "2026-11-16T20:47:00Z", text: "Comando levantado e modo Cinema ativado", source: "fake" },
    ],
    inferredPatterns: learningEnabled ? demoSuggestions.map(({ id, statement, frequency, timeWindow, evidence }) => ({ id, statement, frequency, timeWindow, evidence, simulated: true as const })) : [],
    confirmedPreferences: [],
    pendingSuggestions: demoSuggestions.filter((item) => !demoSuggestionDecisions.has(item.id)).map((item) => item.title),
    ignoredSuggestions: demoSuggestions.filter((item) => demoSuggestionDecisions.has(item.id)).map((item) => item.title),
  }), [learningEnabled]);
  const simulated = source === "mock";
  const exportMemory = () => {
    const url = URL.createObjectURL(new Blob([memoryMarkdown(memory)], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "objectos-memory-demo.md"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
    notifications.show({ color: "teal", message: "Ficheiro Markdown exportado para este dispositivo." });
  };

  return <Stack gap="lg">
    <div><Text c="dimmed" size="sm">IDENTIDADE E PRIVACIDADE</Text><Title order={2}>Perfil</Title><Text c="dimmed">Controla a tua sessão e os dados usados na demonstração.</Text></div>
    {failed ? <Alert color="red">Não foi possível obter os dados da conta.</Alert> : me ? <Card withBorder radius="lg"><Group justify="space-between"><div><Text fw={600}>{me.name ?? me.username}</Text><Text c="dimmed">{me.email}</Text></div><IconShieldLock size={22} /></Group></Card> : <Group><Loader size="sm" /><Text size="sm" c="dimmed">A carregar perfil…</Text></Group>}

    <Card withBorder radius="lg"><Group justify="space-between" align="flex-start" wrap="wrap"><div><Title order={3}>ObjectOS Memory</Title><Text size="sm" c="dimmed" mt={4}>Padrões inferidos a partir de eventos textuais. Uma inferência não é uma preferência pessoal.</Text></div><Badge color={simulated ? "yellow" : "gray"}>{simulated ? "EXEMPLOS SIMULADOS" : "CONTRATO PENDENTE"}</Badge></Group>
      {!simulated ? <Alert color="blue" mt="md">A memória real depende de um contrato backend associado à identidade OIDC. Nenhum dado é guardado no browser.</Alert> : <>
        <Paper withBorder p="md" radius="md" mt="md"><Group justify="space-between"><div><Text fw={500}>Aprendizagem por eventos textuais</Text><Text size="sm" c="dimmed">Esta escolha vale apenas durante a sessão de demonstração.</Text></div><Switch checked={learningEnabled} onChange={(event) => setLearningEnabled(event.currentTarget.checked)} aria-label="Ativar aprendizagem por eventos textuais" /></Group></Paper>
        <SimpleGrid cols={{ base: 1, md: 3 }} mt="md">
          <Card withBorder><Text size="xs" c="dimmed">EVENTOS OBSERVADOS</Text><Title order={3} mt="xs">{memory.observedEvents.length}</Title><Text size="sm" c="dimmed">Acontecimentos textuais simulados.</Text></Card>
          <Card withBorder><Text size="xs" c="dimmed">PADRÕES INFERIDOS</Text><Title order={3} mt="xs">{memory.inferredPatterns.length}</Title><Text size="sm" c="dimmed">Propostas, não factos sobre gostos.</Text></Card>
          <Card withBorder><Text size="xs" c="dimmed">PREFERÊNCIAS CONFIRMADAS</Text><Title order={3} mt="xs">{memory.confirmedPreferences.length}</Title><Text size="sm" c="dimmed">Só após aceitação explícita.</Text></Card>
        </SimpleGrid>
        <Title order={4} mt="lg" mb="sm">Padrões observados</Title>
        {memory.inferredPatterns.length ? <Stack>{memory.inferredPatterns.map((pattern) => <Card withBorder key={pattern.id}><Group justify="space-between" align="flex-start"><Text fw={500}>{pattern.statement}</Text><Badge color="yellow">SIMULADO</Badge></Group><Text size="sm" c="dimmed" mt="xs">Frequência: {pattern.frequency} · Período: {pattern.timeWindow}</Text><Text size="xs" c="dimmed" mt="sm">Evidências textuais</Text>{pattern.evidence.map((evidence) => <Text key={evidence} size="xs">• {evidence}</Text>)}</Card>)}</Stack> : <Text c="dimmed">Aprendizagem desativada. Os exemplos não são apresentados.</Text>}
        <Divider my="lg" />
        <Title order={4} mb="sm">Dados utilizados</Title>
        <Stack gap="xs">{memory.observedEvents.map((event) => <Group key={event.id} justify="space-between" wrap="nowrap"><Text size="sm">{event.text}</Text><Badge color="yellow" size="xs">SIM</Badge></Group>)}</Stack>
        <Divider my="lg" />
        <Group gap="sm" wrap="wrap"><Button leftSection={<IconDownload size={16} />} variant="light" onClick={exportMemory} disabled={!memory.observedEvents.length && !memory.inferredPatterns.length}>Exportar memória Markdown</Button><Button leftSection={<IconTrash size={16} />} variant="light" color="red" onClick={deleteModal.open}>Solicitar eliminação dos dados</Button></Group>
        <Text size="xs" c="dimmed" mt="sm">As decisões sobre sugestões ficam apenas em memória durante esta sessão. Não é usado localStorage.</Text>
      </>}
    </Card>
    <Button leftSection={<IconLogout size={16} />} onClick={() => logout()} variant="light" color="red" w="fit-content">Terminar sessão</Button>
    <Modal opened={deleteOpened} onClose={deleteModal.close} title="Pedido de eliminação" centered><Stack><Alert color="orange">O backend ainda não tem um endpoint de memória/eliminações validado. Nenhum dado foi apagado nem foi enviado um pedido.</Alert><Text size="sm">Podes desativar a aprendizagem nesta sessão. A eliminação de dados reais terá de aguardar confirmação do backend.</Text><Button onClick={deleteModal.close} w="fit-content">Percebi</Button></Stack></Modal>
  </Stack>;
}
