import { Accordion, Alert, Button, Card, Group, Loader, Modal, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useNavigate, useParams } from "react-router-dom";
import { RuleActions, RuleTrigger } from "../components/automations/AutomationPresentation";
import { useSuggestions } from "../hooks/useSuggestions";


/** Route: /automations/suggestions/:id */
export function SuggestionDetailsPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { available, find, busy, ignore, accept } = useSuggestions();
  const [confirmOpened, confirmModal] = useDisclosure(false);
  const suggestion = find(id);

  const onIgnore = () => { ignore(id); navigate("/automations", { replace: true }); };
  const onAccept = async () => {
    if (await accept(id)) { confirmModal.close(); navigate("/automations", { replace: true }); }
  };

  if (!suggestion && available) return <Stack><Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button><Alert color="gray" title="Sugestão não encontrada">Esta sugestão já não está disponível.</Alert></Stack>;
  if (!available) return <Stack><Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button><Alert color="gray" title="Sugestões indisponíveis">Ainda não há sugestões disponíveis.</Alert></Stack>;
  if (!suggestion) return <Group><Loader size="sm" /><Text c="dimmed">A carregar sugestão…</Text></Group>;

  return <Stack maw={720} mx="auto" gap="lg">
    <Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button>
    <div><Title order={2}>{suggestion.title}</Title><Text c="dimmed" mt={4}>Uma sugestão baseada nos exemplos desta demonstração.</Text></div>
    <Card withBorder radius="md"><Stack gap="sm"><Title order={4}>O que a casa reparou</Title><Text>{suggestion.explanation}</Text><Text>{suggestion.statement}</Text></Stack></Card>
    <Card withBorder radius="md"><Stack gap="sm"><Title order={4}>Quando costuma acontecer</Title><Text>{suggestion.timeWindow}</Text></Stack></Card>
    <Card withBorder radius="md"><Stack gap="md"><Title order={4}>O que sugere fazer</Title><Text fw={600}>{suggestion.proposedRule.nome}</Text><RuleTrigger object={suggestion.proposedRule.objeto} /><RuleActions rule={suggestion.proposedRule} /><div><Text fw={500}>Efeito esperado</Text><Text size="sm" c="dimmed">A luz ou tomada muda como indicado acima quando o objeto for detetado. A sugestão não aciona dispositivos agora.</Text></div></Stack></Card>
    <Accordion variant="contained"><Accordion.Item value="evidence"><Accordion.Control>Evidências da demonstração</Accordion.Control><Accordion.Panel><Stack gap="xs">{suggestion.evidence.map((evidence) => <Text size="sm" key={evidence}>{evidence}</Text>)}</Stack></Accordion.Panel></Accordion.Item></Accordion>
    <Group justify="space-between"><Button variant="default" onClick={onIgnore}>Ignorar sugestão</Button><Button onClick={confirmModal.open}>Aceitar sugestão</Button></Group>
    <Modal opened={confirmOpened} onClose={confirmModal.close} title="Guardar esta sugestão?" centered>
      <Stack><Text>A regra será guardada inativa. Não serão executadas ações nos dispositivos.</Text><Group justify="flex-end"><Button variant="default" onClick={confirmModal.close}>Cancelar</Button><Button loading={busy} onClick={() => void onAccept()}>Guardar automação</Button></Group></Stack>
    </Modal>
  </Stack>;
}

export default SuggestionDetailsPage;
