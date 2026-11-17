import { Accordion, Alert, Button, Card, Group, Stack, Text, Textarea, Title } from "@mantine/core";
import { IconArrowLeft, IconSparkles } from "@tabler/icons-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { RuleActions, RuleTrigger } from "../components/automations/AutomationPresentation";
import { useNewRule } from "../hooks/useRules";
import type { RuleDraft } from "../types/home";

const presets: { title: string; description: string; draft: RuleDraft }[] = [
  { title: "Luz suave para ler", description: "Quando levantar o livro, ajustar a luz.", draft: { id: "preset-reading", nome: "Luz suave para ler", objeto: "livro", acoes: [{ dispositivo: "lampada", ligada: true, cor: "branco_quente", brilho: 40 }] } },
  { title: "Ligar a tomada", description: "Quando levantar o comando, ligar a tomada.", draft: { id: "preset-plug", nome: "Ligar a tomada", objeto: "comando", acoes: [{ dispositivo: "tomada", ligada: true }] } },
];

/** Route: /automations/new */
export default function NewAutomationPage() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const { proposal, proposalError, busy, propose, save, startFrom, discard } = useNewRule();

  const onSave = async () => {
    const saved = proposal && await save(proposal.draft);
    if (saved) navigate(`/automations/${encodeURIComponent(saved.id)}`);
  };

  return <Stack maw={720} mx="auto" gap="lg">
    <Button variant="subtle" leftSection={<IconArrowLeft size={16} />} w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button>
    <div><Title order={2}>Nova automação</Title><Text c="dimmed" mt={4}>Descreve o que gostarias que a casa fizesse.</Text></div>

    {!proposal ? <Stack gap="md">
      <Textarea label="O que queres que aconteça?" placeholder="Quando levantar o livro, deixar a luz mais suave" value={text} onChange={(event) => setText(event.currentTarget.value)} minRows={3} autosize maxRows={6} />
      <Button leftSection={<IconSparkles size={16} />} loading={busy} disabled={!text.trim()} onClick={() => void propose(text)}>Ver proposta</Button>
      {proposalError ? <Alert color="orange" title="Proposta indisponível">{proposalError}</Alert> : null}
      <Accordion variant="separated">
        <Accordion.Item value="examples"><Accordion.Control>Ver exemplos</Accordion.Control><Accordion.Panel><Stack gap="sm">
          {presets.map((preset) => <Card key={preset.title} withBorder padding="sm" radius="md"><Group justify="space-between"><div><Text fw={500}>{preset.title}</Text><Text size="sm" c="dimmed">{preset.description}</Text></div><Button variant="light" onClick={() => startFrom(preset.draft)}>Usar exemplo</Button></Group></Card>)}
        </Stack></Accordion.Panel></Accordion.Item>
      </Accordion>
    </Stack> : <Stack>
      <Text size="sm" c="dimmed">Proposta</Text>
      <Card withBorder radius="md"><Stack gap="md">
        {proposal.summary ? <Text>{proposal.summary}</Text> : null}
        <div><Text fw={600}>{proposal.draft.nome}</Text><Text size="sm" c="dimmed">Quando acontece</Text><RuleTrigger object={proposal.draft.objeto} /></div>
        <div><Text fw={600} mb="xs">O que a casa faz</Text><RuleActions rule={proposal.draft} /></div>
        <Text size="sm" c="dimmed">A automação fica inativa até a ativares. Guardar não aciona dispositivos.</Text>
      </Stack></Card>
      <Group justify="space-between"><Button variant="default" disabled={busy} onClick={() => discard()}>Alterar descrição</Button><Button loading={busy} onClick={() => void onSave()}>Guardar automação</Button></Group>
    </Stack>}
  </Stack>;
}
