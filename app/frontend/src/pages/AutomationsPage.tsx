import { Alert, Badge, Button, Card, Group, Loader, SimpleGrid, Stack, Switch, Text, Title } from "@mantine/core";
import { IconArrowRight, IconPlus } from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";
import { useRules } from "../hooks/useRules";
import { useSuggestions } from "../hooks/useSuggestions";

export default function AutomationsPage() {
  const navigate = useNavigate();
  const { rules, loading, failed, toggle } = useRules();
  const { available, suggestions, ignore } = useSuggestions();

  return <Stack gap="xl">
    <Group justify="space-between" align="flex-start">
      <div><Title order={2}>Automações</Title><Text c="dimmed" mt={4}>A casa adapta-se às tuas rotinas.</Text></div>
      <Button leftSection={<IconPlus size={16} />} onClick={() => navigate("/automations/new")}>Nova automação</Button>
    </Group>

    <section>
      <Title order={4} mb="sm">As tuas automações</Title>
      {failed ? <Alert color="red" title="Não foi possível carregar as automações">Tenta novamente mais tarde.</Alert> : loading ? <Group><Loader size="sm" /><Text size="sm" c="dimmed">A carregar…</Text></Group> : rules.length ? <Stack gap="sm">
        {rules.map((rule) => <Card key={rule.id} withBorder radius="md" padding="md">
          <Group justify="space-between" wrap="nowrap" align="center">
            <div style={{ minWidth: 0 }}>
              <Text fw={600}>{rule.nome}</Text>
              <Text size="sm" c="dimmed">Quando levantar {rule.objeto === "livro" ? "o livro" : rule.objeto === "comando" ? "o comando" : rule.objeto === "caneca" ? "a caneca" : rule.objeto}</Text>
            </div>
            <Group gap="sm" wrap="nowrap">
              <Badge color={rule.enabled ? "teal" : "gray"} variant="light">{rule.enabled ? "Ativa" : "Inativa"}</Badge>
              <Switch aria-label={`${rule.enabled ? "Desativar" : "Ativar"} ${rule.nome}`} checked={rule.enabled} onChange={(event) => void toggle(rule, event.currentTarget.checked)} />
              <Button variant="subtle" rightSection={<IconArrowRight size={15} />} onClick={() => navigate(`/automations/${encodeURIComponent(rule.id)}`)}>Ver detalhes</Button>
            </Group>
          </Group>
        </Card>)}
      </Stack> : <Card withBorder radius="md"><Text c="dimmed">Ainda não criaste automações.</Text><Button mt="sm" variant="light" onClick={() => navigate("/automations/new")}>Criar a primeira</Button></Card>}
    </section>

    <section>
      <Group justify="space-between" mb="sm" align="baseline"><Title order={4}>Sugestões</Title><Text size="sm" c="dimmed">Ideias para as tuas rotinas</Text></Group>
      {!available ? <Text size="sm" c="dimmed">Ainda não há sugestões disponíveis.</Text> : suggestions.length ? <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {suggestions.map((suggestion) => <Card key={suggestion.id} withBorder radius="md" padding="md">
          <Text fw={600}>{suggestion.title}</Text>
          <Text size="sm" c="dimmed" mt={4}>{suggestion.statement}</Text>
          <Group mt="md" justify="space-between">
            <Button variant="subtle" px={0} onClick={() => navigate(`/automations/suggestions/${encodeURIComponent(suggestion.id)}`)}>Ver sugestão</Button>
            <Button variant="subtle" color="gray" onClick={() => ignore(suggestion.id)}>Ignorar</Button>
          </Group>
        </Card>)}
      </SimpleGrid> : <Text size="sm" c="dimmed">Não há sugestões pendentes nesta sessão.</Text>}
    </section>
  </Stack>;
}
