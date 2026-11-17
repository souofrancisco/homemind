import { Alert, Badge, Button, Card, Divider, Group, Loader, Modal, NumberFormatter, SimpleGrid, Stack, Switch, Table, Text, Textarea, Title, Tooltip } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconBolt, IconCamera, IconCircleCheck, IconClock, IconHome, IconPower, IconRefresh, IconSparkles, IconTrash } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { getHomeService } from "./homeApi";
import { simulateObject, simulatePresence } from "./mockHome";
import { useHomeSocket } from "./useHomeSocket";
import type { HomeRule, RuleDraft } from "./types";

const service = getHomeService();
const modeLabel = (mode: string | null) => mode ? ({ leitura: "Leitura", cinema: "Cinema", cafe: "Pausa para café" }[mode] ?? mode) : "Sem modo ativo";
const dateLabel = (value: string) => new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));

export default function Dashboard() {
  const { user } = useAuth();
  const { state, events, online, source } = useHomeSocket();
  const isSimulated = source === "mock" || state?.backend === "fake";
  const [rules, setRules] = useState<HomeRule[]>([]);
  const [rulesFailed, setRulesFailed] = useState(false);
  const [ruleText, setRuleText] = useState("");
  const [proposal, setProposal] = useState<{ draft: RuleDraft; summary: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [powerOpened, powerModal] = useDisclosure(false);
  const [proposalOpened, proposalModal] = useDisclosure(false);
  const [cameraFailed, setCameraFailed] = useState(false);

  const refreshRules = () => service.getRules().then(setRules).catch(() => setRulesFailed(true));
  useEffect(() => { void refreshRules(); }, []);

  const setRule = async (rule: HomeRule, enabled: boolean) => {
    try { const updated = await service.setRuleEnabled(rule.id, enabled); setRules((items) => items.map((item) => item.id === rule.id ? updated : item)); }
    catch (error) { notifications.show({ color: "red", title: "Não foi possível atualizar", message: error instanceof Error ? error.message : "Erro inesperado" }); }
  };
  const deleteRule = async (rule: HomeRule) => {
    try { await service.deleteRule(rule.id); setRules((items) => items.filter((item) => item.id !== rule.id)); notifications.show({ color: "green", message: `Regra “${rule.nome}” apagada` }); }
    catch (error) { notifications.show({ color: "red", title: "Não foi possível apagar", message: error instanceof Error ? error.message : "Erro inesperado" }); }
  };
  const createProposal = async () => {
    if (!ruleText.trim()) return;
    setBusy(true);
    try { const result = await service.proposeRule(ruleText); setProposal({ draft: result.proposal, summary: result.summary }); proposalModal.open(); }
    catch (error) { notifications.show({ color: "red", title: "Não foi possível criar proposta", message: error instanceof Error ? error.message : "Serviço indisponível" }); }
    finally { setBusy(false); }
  };
  const saveProposal = async () => {
    if (!proposal) return;
    setBusy(true);
    try { const saved = await service.saveRule(proposal.draft); setRules((items) => [saved, ...items]); setProposal(null); proposalModal.close(); setRuleText(""); notifications.show({ color: "green", message: "Regra guardada" }); }
    catch (error) { notifications.show({ color: "red", title: "Regra não guardada", message: error instanceof Error ? error.message : "Erro inesperado" }); }
    finally { setBusy(false); }
  };
  const turnOff = async () => {
    setBusy(true);
    try {
      const result = await service.turnOff();
      if (result.success) notifications.show({ color: "green", title: "Desligar tudo", message: result.message });
      else notifications.show({ color: "orange", title: "Operação incompleta", message: result.message });
      powerModal.close();
    } catch (error) { notifications.show({ color: "red", title: "Operação falhou", message: error instanceof Error ? error.message : "Não foi possível desligar" }); }
    finally { setBusy(false); }
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div><Text c="dimmed" size="sm">ObjectOS · Espaço de demonstração</Text><Title order={2}>Olá, {user?.profile.name ?? user?.profile.email ?? "anfitrião"}</Title></div>
        <Group gap="xs"><Badge size="lg" color={isSimulated ? "yellow" : "green"} variant="light">{isSimulated ? "SIMULADO" : "REAL · MCP"}</Badge><Badge size="lg" color={online ? "teal" : "red"} leftSection={<span aria-hidden="true">●</span>}>{online ? "Ligado" : "Offline"}</Badge></Group>
      </Group>

      {!state && <Group justify="center" py="xl"><Loader size="sm" /><Text c="dimmed">A carregar estado da casa…</Text></Group>}
      {state && !online && <Alert color="orange" icon={<IconAlertCircle />} title="Ligação indisponível">A mostrar o último estado recebido. A reconexão é automática; controlos simulados continuam disponíveis.</Alert>}
      {state && <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
        <Card withBorder><Group justify="space-between"><Text c="dimmed" size="sm">Modo atual</Text><IconHome size={20} /></Group><Title order={3} mt="xs">{modeLabel(state.mode)}</Title><Badge mt="xs" color={state.state === "ativo" ? "teal" : "gray"}>{state.state.replace("_", " ")}</Badge></Card>
        <Card withBorder><Group justify="space-between"><Text c="dimmed" size="sm">Presença</Text><span aria-hidden="true">◉</span></Group><Title order={3} mt="xs">{state.presence ? "Alguém em casa" : "Sem presença"}</Title><Text size="sm" c="dimmed">Sem identificação ou contagem de pessoas</Text></Card>
        <Card withBorder><Group justify="space-between"><Text c="dimmed" size="sm">Poupança estimada</Text><IconBolt size={20} /></Group><Title order={3} mt="xs"><NumberFormatter value={state.energy_saved_wh} decimalScale={1} suffix=" Wh" /></Title><Text size="sm" c="dimmed"><NumberFormatter value={state.energy_saved_eur} decimalScale={3} prefix="€" /></Text></Card>
        <Card withBorder><Group justify="space-between"><Text c="dimmed" size="sm">Estado dos serviços</Text><IconRefresh size={20} /></Group><Group mt="md" gap="xs"><Badge color={state.camera_ok ? "teal" : "gray"} leftSection={<IconCamera size={12} />}>Câmara {state.camera_ok ? "ativa" : "indisponível"}</Badge><Badge color={state.mcp_ok ? "teal" : "gray"}>MCP {state.mcp_ok ? "ligado" : "indisponível"}</Badge></Group></Card>
      </SimpleGrid>}

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder padding="md">
          <Group justify="space-between" mb="sm"><div><Title order={4}>Câmara da sala</Title><Text size="sm" c="dimmed">Feed local · nunca enviado para serviços externos</Text></div><Badge color={state?.camera_ok && !cameraFailed ? "teal" : "gray"}>{state?.camera_ok && !cameraFailed ? "AO VIVO" : "SEM SINAL"}</Badge></Group>
          <Card withBorder bg="dark.8" c="white" h={{ base: 190, sm: 260 }} padding="md">
            {!isSimulated && state?.camera_ok && !cameraFailed ? <img src="/video" alt="Feed da câmara da sala" onError={() => setCameraFailed(true)} style={{ width: "100%", height: "100%", objectFit: "contain" }} /> : <Stack h="100%" align="center" justify="center" gap="xs"><IconCamera size={38} /><Text fw={600}>Pré-visualização indisponível</Text><Text size="sm" c="gray.4">{isSimulated ? "Câmara simulada — nenhum vídeo está a ser transmitido" : "A câmara não está a disponibilizar imagens"}</Text></Stack>}
          </Card>
          {source === "mock" && <Group mt="sm" gap="xs" grow><Button variant="light" onClick={() => simulatePresence(!state?.presence)}>Simular {state?.presence ? "ausência" : "presença"}</Button><Button variant="light" onClick={() => simulateObject("livro")}>Detetar livro</Button><Button variant="light" onClick={() => simulateObject("caneca")}>Detetar caneca</Button></Group>}
        </Card>

        <Card withBorder padding="md">
          <Group justify="space-between" mb="sm"><div><Title order={4}>Atividade recente</Title><Text size="sm" c="dimmed">Últimos {events.length} eventos · estimativas da sessão</Text></div><Badge variant="light">50 máx.</Badge></Group>
          <Stack gap={0} mah={310} style={{ overflowY: "auto" }}>
            {events.length ? events.slice(0, 50).map((event) => <Group key={event.id} py="sm" wrap="nowrap" align="flex-start"><IconCircleCheck size={18} color={event.level === "error" ? "var(--mantine-color-red-6)" : event.level === "warning" ? "var(--mantine-color-yellow-7)" : "var(--mantine-color-teal-6)"} /><div style={{ flex: 1 }}><Text size="sm">{event.message}</Text><Text size="xs" c="dimmed">{dateLabel(event.timestamp)}</Text></div><Badge size="xs" color={event.source === "fake" ? "yellow" : "green"}>{event.source === "fake" ? "SIM" : "REAL"}</Badge></Group>) : <Text c="dimmed" py="lg" ta="center">Ainda não há eventos.</Text>}
          </Stack>
        </Card>
      </SimpleGrid>

      <Card withBorder>
        <Group justify="space-between" mb="md" align="flex-start"><div><Title order={4}>Regras da casa</Title><Text size="sm" c="dimmed">Ative rotinas por objeto detetado.</Text></div><Badge variant="light">{rules.length} regras</Badge></Group>
        {rulesFailed ? <Alert color="orange" mb="md">Não foi possível carregar regras. A demonstração continua disponível.</Alert> : null}
        {rules.length ? <Table.ScrollContainer minWidth={480}><Table verticalSpacing="sm"><Table.Thead><Table.Tr><Table.Th>Regra</Table.Th><Table.Th>Objeto</Table.Th><Table.Th>Estado</Table.Th><Table.Th><span className="sr-only">Ações</span></Table.Th></Table.Tr></Table.Thead><Table.Tbody>{rules.map((rule) => <Table.Tr key={rule.id}><Table.Td><Text fw={500}>{rule.nome}</Text><Text size="xs" c="dimmed">{rule.acoes.map((action) => action.dispositivo).join(" · ")}</Text></Table.Td><Table.Td>{rule.objeto}</Table.Td><Table.Td><Switch aria-label={`${rule.enabled ? "Desativar" : "Ativar"} ${rule.nome}`} checked={rule.enabled} onChange={(event) => void setRule(rule, event.currentTarget.checked)} /></Table.Td><Table.Td><Tooltip label={`Apagar ${rule.nome}`}><Button aria-label={`Apagar regra ${rule.nome}`} variant="subtle" color="red" size="compact-sm" onClick={() => void deleteRule(rule)}><IconTrash size={16} /></Button></Tooltip></Table.Td></Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer> : <Text c="dimmed">Sem regras.</Text>}
        <Divider my="md" />
        <Title order={5} mb="xs">Propor uma regra</Title><Text size="sm" c="dimmed" mb="sm">Escreve em linguagem natural. A proposta só é guardada após confirmação.</Text>
        <Group align="flex-end"><Textarea aria-label="Descreva uma regra" placeholder="Quando levantar o livro, ligar a luz a 40%" value={ruleText} onChange={(event) => setRuleText(event.currentTarget.value)} minRows={2} autosize style={{ flex: 1 }} /><Button leftSection={<IconSparkles size={16} />} loading={busy} disabled={!ruleText.trim()} onClick={() => void createProposal()}>Pré-visualizar</Button></Group>
      </Card>

      <Card withBorder bg="red.0"><Group justify="space-between" align="center" wrap="wrap"><div><Title order={4}>Controlo rápido</Title><Text size="sm" c="dimmed">Pede confirmação antes de desligar dispositivos.</Text></div><Button color="red" size="md" leftSection={<IconPower size={18} />} onClick={powerModal.open}>Desligar tudo</Button></Group></Card>

      <Modal opened={powerOpened} onClose={powerModal.close} title="Desligar tudo?" centered><Stack><Alert color="orange" icon={<IconAlertCircle />}>{isSimulated ? "Esta ação é simulada e não altera dispositivos físicos." : "A operação será enviada à API e pode afetar dispositivos ligados."}</Alert><Text>Confirma que quer desligar os dispositivos controlados?</Text><Group justify="flex-end"><Button variant="default" onClick={powerModal.close}>Cancelar</Button><Button color="red" loading={busy} onClick={() => void turnOff()}>Confirmar desligar</Button></Group></Stack></Modal>
      <Modal opened={proposalOpened} onClose={proposalModal.close} title="Confirmar nova regra" centered><Stack><Alert color="blue" icon={<IconSparkles size={16} />}>{proposal?.summary}</Alert><Text size="sm"><b>Regra:</b> {proposal?.draft.nome}<br /><b>Objeto:</b> {proposal?.draft.objeto}<br /><b>Ações:</b> {proposal?.draft.acoes.map((action) => `${action.dispositivo} (${action.brilho ?? "on"})`).join(", ")}</Text><Text size="sm" c="dimmed">A regra fica apenas guardada; nenhuma ação física será executada agora.</Text><Group justify="flex-end"><Button variant="default" onClick={proposalModal.close}>Cancelar</Button><Button loading={busy} onClick={() => void saveProposal()}>Confirmar e guardar</Button></Group></Stack></Modal>
      <Text size="xs" c="dimmed" ta="right"><IconClock size={12} /> Atualizado {state ? dateLabel(state.updated_at) : "a carregar…"}{state?.waiting_remaining_seconds != null ? ` · espera ${state.waiting_remaining_seconds}s` : ""}</Text>
    </Stack>
  );
}
