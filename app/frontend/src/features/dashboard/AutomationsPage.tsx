import { Alert, Badge, Button, Card, Group, Loader, Modal, SimpleGrid, Stack, Switch, Table, Text, Textarea, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconSparkles, IconTrash } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { getHomeService } from "./homeApi";
import { demoSuggestionDecisions, demoSuggestions } from "./demoSuggestions";
import { useHomeSocket } from "./useHomeSocket";
import type { HomeRule, RuleDraft, RoutineSuggestion } from "./types";

const service = getHomeService();

export default function AutomationsPage() {
  const { source } = useHomeSocket();
  const [rules, setRules] = useState<HomeRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<{ draft: RuleDraft; summary: string } | null>(null);
  const [selectedSuggestion, setSelectedSuggestion] = useState<RoutineSuggestion | null>(null);
  const [removeTarget, setRemoveTarget] = useState<HomeRule | null>(null);
  const [busy, setBusy] = useState(false);
  const [, setDecisionVersion] = useState(0);
  const [proposalOpened, proposalModal] = useDisclosure(false);
  const [suggestionOpened, suggestionModal] = useDisclosure(false);
  const [removeOpened, removeModal] = useDisclosure(false);
  const suggestions = source === "mock" ? demoSuggestions.filter((item) => !demoSuggestionDecisions.has(item.id)) : [];

  const refresh = async () => {
    setLoading(true); setFailed(false);
    try { setRules(await service.getRules()); }
    catch { setFailed(true); }
    finally { setLoading(false); }
  };
  useEffect(() => { const timer = setTimeout(() => { void refresh(); }, 0); return () => clearTimeout(timer); }, []);

  const propose = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { const result = await service.proposeRule(text.trim()); setProposal({ draft: result.proposal, summary: result.summary }); proposalModal.open(); }
    catch (error) { notifications.show({ color: "red", title: "Proposta indisponível", message: error instanceof Error ? error.message : "O serviço de interpretação não respondeu. As regras existentes continuam disponíveis." }); }
    finally { setBusy(false); }
  };
  const save = async (draft: RuleDraft) => {
    setBusy(true);
    try { const saved = await service.saveRule(draft); setRules((items) => [saved, ...items]); setProposal(null); setSelectedSuggestion(null); proposalModal.close(); suggestionModal.close(); setText(""); if (selectedSuggestion) { demoSuggestionDecisions.add(selectedSuggestion.id); setDecisionVersion((version) => version + 1); } notifications.show({ color: "teal", message: "Regra guardada como inativa. Não foi executada nenhuma ação física." }); }
    catch (error) { notifications.show({ color: "red", title: "Regra não guardada", message: error instanceof Error ? error.message : "Serviço indisponível" }); }
    finally { setBusy(false); }
  };
  const toggle = async (rule: HomeRule, enabled: boolean) => {
    try { const updated = await service.setRuleEnabled(rule.id, enabled); setRules((items) => items.map((item) => item.id === rule.id ? updated : item)); }
    catch (error) { notifications.show({ color: "red", title: "Não foi possível atualizar", message: error instanceof Error ? error.message : "Serviço indisponível" }); }
  };
  const remove = async () => {
    if (!removeTarget) return;
    setBusy(true);
    try { await service.deleteRule(removeTarget.id); setRules((items) => items.filter((item) => item.id !== removeTarget.id)); removeModal.close(); setRemoveTarget(null); }
    catch (error) { notifications.show({ color: "red", title: "Não foi possível apagar", message: error instanceof Error ? error.message : "Serviço indisponível" }); }
    finally { setBusy(false); }
  };

  return <Stack gap="lg">
    <div><Text c="dimmed" size="sm">ROTINAS DA CASA</Text><Title order={2}>Automações</Title><Text c="dimmed">As regras guardadas só ficam ativas após confirmação.</Text></div>
    <Card withBorder radius="lg"><Group justify="space-between" mb="md"><div><Title order={4}>Regras guardadas</Title><Text size="sm" c="dimmed">Gerir as regras já guardadas.</Text></div><Badge variant="light">{rules.filter((rule) => rule.enabled).length} ativas</Badge></Group>
      {failed ? <Alert color="orange" title="Regras indisponíveis">Não foi possível carregar regras. O backend pode ainda não disponibilizar este contrato.</Alert> : loading ? <Group><Loader size="sm" /><Text size="sm" c="dimmed">A carregar regras…</Text></Group> : rules.length ? <Table.ScrollContainer minWidth={520}><Table verticalSpacing="sm"><Table.Thead><Table.Tr><Table.Th>Regra</Table.Th><Table.Th>Objeto</Table.Th><Table.Th>Ativa</Table.Th><Table.Th>Ação</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{rules.map((rule) => <Table.Tr key={rule.id}><Table.Td><Text fw={500}>{rule.nome}</Text><Text size="xs" c="dimmed">{rule.acoes.map((action) => action.dispositivo).join(" · ")}</Text></Table.Td><Table.Td>{rule.objeto}</Table.Td><Table.Td><Switch aria-label={`${rule.enabled ? "Desativar" : "Ativar"} ${rule.nome}`} checked={rule.enabled} onChange={(event) => void toggle(rule, event.currentTarget.checked)} /></Table.Td><Table.Td><Button variant="subtle" color="red" aria-label={`Apagar ${rule.nome}`} onClick={() => { setRemoveTarget(rule); removeModal.open(); }}><IconTrash size={16} /></Button></Table.Td></Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer> : <Text c="dimmed">Ainda não existem regras guardadas.</Text>}
    </Card>

    <Card withBorder radius="lg"><Title order={4}>Criar regra por linguagem natural</Title><Text size="sm" c="dimmed" mt="xs" mb="md">A frase é convertida numa proposta estruturada. Nada é guardado antes da confirmação.</Text><Group align="flex-end"><Textarea aria-label="Descreva uma regra" placeholder="Quando levantar o livro, ligar a luz a 40%" value={text} onChange={(event) => setText(event.currentTarget.value)} minRows={2} autosize style={{ flex: 1 }} /><Button leftSection={<IconSparkles size={16} />} loading={busy} disabled={!text.trim()} onClick={() => void propose()}>Pré-visualizar</Button></Group>{source === "mock" ? <Badge mt="sm" color="yellow">Interpretação simulada · sem chamada à NVIDIA</Badge> : null}</Card>

    <section><Group justify="space-between" mb="md"><div><Title order={4}>Sugestões inteligentes</Title><Text size="sm" c="dimmed">Padrões de utilização, sempre sujeitos à tua confirmação.</Text></div><Badge color={source === "mock" ? "yellow" : "gray"}>{source === "mock" ? "SIMULADAS" : "CONTRATO PENDENTE"}</Badge></Group>
      {source !== "mock" ? <Alert color="blue">As sugestões reais dependem da validação do motor de padrões e do contrato do backend. Nenhum endpoint de sugestões é chamado.</Alert> : suggestions.length ? <SimpleGrid cols={{ base: 1, lg: 2 }}>{suggestions.map((item) => <Card withBorder radius="lg" key={item.id}><Badge color="yellow" mb="sm">PADRÃO SIMULADO</Badge><Title order={5}>{item.title}</Title><Text size="sm" mt="xs">{item.explanation}</Text><Text size="sm" fw={500} mt="md">{item.statement}</Text><Text size="sm" c="dimmed">Frequência: {item.frequency} · Período: {item.timeWindow}</Text><Text size="xs" c="dimmed" mt="sm">Evidências</Text><Stack gap={2} mt={4}>{item.evidence.map((evidence) => <Text size="xs" key={evidence}>• {evidence}</Text>)}</Stack><Text size="xs" c="dimmed" mt="sm">Proposta: {item.proposedRule.nome} · objeto {item.proposedRule.objeto}</Text><Group mt="md"><Button onClick={() => { setSelectedSuggestion(item); suggestionModal.open(); }}>Aceitar e rever</Button><Button variant="default" onClick={() => { demoSuggestionDecisions.add(item.id); setDecisionVersion((version) => version + 1); }}>Ignorar</Button></Group></Card>)}</SimpleGrid> : <Text c="dimmed">Não há sugestões pendentes nesta sessão.</Text>}
    </section>

    <Modal opened={proposalOpened} onClose={proposalModal.close} title="Rever proposta" centered><Stack><Alert color="blue">{proposal?.summary}</Alert><Text><b>{proposal?.draft.nome}</b> · Objeto: {proposal?.draft.objeto}</Text><Text size="sm">Ações: {proposal?.draft.acoes.map((action) => `${action.dispositivo} (${action.brilho ?? "ligar"})`).join(" · ")}</Text><Text size="sm" c="dimmed">Guardar a regra não executa ações físicas.</Text><Group justify="flex-end"><Button variant="default" onClick={proposalModal.close}>Cancelar</Button><Button loading={busy} onClick={() => proposal && void save(proposal.draft)}>Confirmar e guardar</Button></Group></Stack></Modal>
    <Modal opened={suggestionOpened} onClose={suggestionModal.close} title="Confirmar sugestão" centered><Stack><Badge color="yellow" w="fit-content">SIMULADA</Badge><Text fw={600}>{selectedSuggestion?.title}</Text><Text>{selectedSuggestion?.statement}</Text><Text size="sm">Proposta: {selectedSuggestion?.proposedRule.nome} · {selectedSuggestion?.proposedRule.objeto}</Text><Text size="sm" c="dimmed">Aceitar guarda a regra após esta confirmação; não a ativa automaticamente nem executa dispositivos.</Text><Group justify="flex-end"><Button variant="default" onClick={suggestionModal.close}>Cancelar</Button><Button loading={busy} onClick={() => selectedSuggestion && void save(selectedSuggestion.proposedRule)}>Confirmar e guardar</Button></Group></Stack></Modal>
    <Modal opened={removeOpened} onClose={removeModal.close} title="Apagar regra?" centered><Stack><Alert color="orange" icon={<IconAlertCircle />}>A regra “{removeTarget?.nome}” será removida.</Alert><Group justify="flex-end"><Button variant="default" onClick={removeModal.close}>Cancelar</Button><Button color="red" loading={busy} onClick={() => void remove()}>Confirmar eliminação</Button></Group></Stack></Modal>
  </Stack>;
}
