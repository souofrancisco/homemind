import { Accordion, Alert, Button, Card, Group, Loader, Modal, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { demoSuggestionDecisions, demoSuggestions } from "./demoSuggestions";
import { getHomeService } from "./homeApi";
import { RuleActions, RuleTrigger } from "./AutomationPresentation";
import { useHomeSocket } from "./useHomeSocket";

const service = getHomeService();

/** Route: /automations/suggestions/:id */
export function SuggestionDetailsPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { source } = useHomeSocket();
  const [busy, setBusy] = useState(false);
  const [confirmOpened, confirmModal] = useDisclosure(false);
  const suggestion = source === "mock" ? demoSuggestions.find((item) => item.id === id) : undefined;

  const ignore = () => {
    demoSuggestionDecisions.add(id);
    navigate("/automations", { replace: true });
  };

  const accept = async () => {
    if (!suggestion) return;
    setBusy(true);
    try {
      await service.saveRule(suggestion.proposedRule);
      demoSuggestionDecisions.add(suggestion.id);
      confirmModal.close();
      notifications.show({ color: "teal", message: "Sugestão guardada como inativa. Nenhum dispositivo foi acionado." });
      navigate("/automations", { replace: true });
    } catch (error) {
      notifications.show({ color: "red", title: "Não foi possível guardar", message: error instanceof Error ? error.message : "Tenta novamente mais tarde." });
    } finally {
      setBusy(false);
    }
  };

  if (!suggestion && source === "mock") return <Stack><Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button><Alert color="gray" title="Sugestão não encontrada">Esta sugestão já não está disponível.</Alert></Stack>;
  if (source !== "mock") return <Stack><Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button><Alert color="gray" title="Sugestões indisponíveis">Ainda não há sugestões disponíveis.</Alert></Stack>;
  if (!suggestion) return <Group><Loader size="sm" /><Text c="dimmed">A carregar sugestão…</Text></Group>;

  return <Stack maw={720} mx="auto" gap="lg">
    <Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button>
    <div><Title order={2}>{suggestion.title}</Title><Text c="dimmed" mt={4}>Uma sugestão baseada nos exemplos desta demonstração.</Text></div>
    <Card withBorder radius="md"><Stack gap="sm"><Title order={4}>O que a casa reparou</Title><Text>{suggestion.explanation}</Text><Text>{suggestion.statement}</Text></Stack></Card>
    <Card withBorder radius="md"><Stack gap="sm"><Title order={4}>Quando costuma acontecer</Title><Text>{suggestion.timeWindow}</Text></Stack></Card>
    <Card withBorder radius="md"><Stack gap="md"><Title order={4}>O que sugere fazer</Title><Text fw={600}>{suggestion.proposedRule.nome}</Text><RuleTrigger object={suggestion.proposedRule.objeto} /><RuleActions rule={suggestion.proposedRule} /><div><Text fw={500}>Efeito esperado</Text><Text size="sm" c="dimmed">A luz ou tomada muda como indicado acima quando o objeto for detetado. A sugestão não aciona dispositivos agora.</Text></div></Stack></Card>
    <Accordion variant="contained"><Accordion.Item value="evidence"><Accordion.Control>Evidências da demonstração</Accordion.Control><Accordion.Panel><Stack gap="xs">{suggestion.evidence.map((evidence) => <Text size="sm" key={evidence}>{evidence}</Text>)}</Stack></Accordion.Panel></Accordion.Item></Accordion>
    <Group justify="space-between"><Button variant="default" onClick={ignore}>Ignorar sugestão</Button><Button onClick={confirmModal.open}>Aceitar sugestão</Button></Group>
    <Modal opened={confirmOpened} onClose={confirmModal.close} title="Guardar esta sugestão?" centered>
      <Stack><Text>A regra será guardada inativa. Não serão executadas ações nos dispositivos.</Text><Group justify="flex-end"><Button variant="default" onClick={confirmModal.close}>Cancelar</Button><Button loading={busy} onClick={() => void accept()}>Guardar automação</Button></Group></Stack>
    </Modal>
  </Stack>;
}

export default SuggestionDetailsPage;
