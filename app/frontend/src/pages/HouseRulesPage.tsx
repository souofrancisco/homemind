import { Alert, Badge, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle, IconLock } from "@tabler/icons-react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { useHouseAutomations } from "../hooks/useHouseAutomations";
import ProposeRuleForm, { type PlugOption } from "../components/houseRules/ProposeRuleForm";
import RuleCard from "../components/houseRules/RuleCard";

export default function HouseRulesContent() {
  const session = useHouseholdSession();
  const householdId = session.membership?.household_id;
  const isTenant = session.membership?.role === "tenant";
  const auto = useHouseAutomations(isTenant ? householdId : undefined);

  if (!isTenant) return <Alert icon={<IconLock />} color="gray" title="Só para moradores">As regras da casa são votadas e geridas apenas pelos moradores.</Alert>;
  if (auto.loading) return <Group role="status"><Loader size="sm" /><Text>A carregar regras…</Text></Group>;
  if (!auto.rules) return (
    <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar as regras da casa">
      <Button w="fit-content" color="red" variant="light" onClick={auto.reload}>Tentar novamente</Button>
    </Alert>
  );

  // As tomadas do formulário são as que o servidor aceita (GET .../automations/plugs).
  const names = new Map<string, string>();
  auto.rules.forEach((r) => r.actions.forEach((a) => names.set(a.target_device_id, r.device_name)));
  const plugs: PlugOption[] = auto.plugs.map((p) => ({
    value: p.id,
    label: `${p.name}${p.simulated && !/simulad/i.test(p.name) ? " (SIMULADO)" : ""}`,
  }));
  const tapName = (id: string | null | undefined) => (id ? plugs.find((p) => p.value === id)?.label.replace(/ \(SIMULAD[OA]\)/, "") ?? names.get(id) ?? "uma tomada" : "uma tomada");
  const simulated = auto.rules.some((r) => r.origin === "simulated") || auto.plugs.some((p) => p.simulated);

  const pending = auto.rules.filter((r) => r.vote_open);
  const active = auto.rules.filter((r) => r.status === "active" && !r.vote_open);
  const suspended = auto.rules.filter((r) => r.status === "disabled" && !r.vote_open);
  const card = (r: (typeof auto.rules)[number]) => (
    <RuleCard key={r.id} rule={r} tapName={tapName} busy={auto.busy === r.id}
      onVote={(a) => void auto.vote(r.id, a)} onSuspend={() => void auto.suspend(r.id)} onReactivate={() => void auto.reactivate(r.id)} />
  );
  const section = (title: string, rules: typeof pending, empty: string) => (
    <Stack gap="sm">
      <Group gap="xs"><Title order={2} size="h3">{title}</Title><Badge variant="light" color="gray">{rules.length}</Badge></Group>
      {rules.length ? rules.map(card) : <Text c="dimmed" size="sm">{empty}</Text>}
    </Stack>
  );
  return (
    <Stack gap="xl" maw={760}>
      {section("Propostas em votação", pending, "Não há propostas à espera de voto.")}
      {section("Regras ativas", active, "Ainda não há regras ativas.")}
      {suspended.length > 0 && section("Regras suspensas", suspended, "")}
      <ProposeRuleForm plugs={plugs} busy={auto.busy === "new"} simulated={simulated} onSubmit={auto.propose} />
    </Stack>
  );
}
