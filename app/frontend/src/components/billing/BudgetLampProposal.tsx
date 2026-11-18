import { Alert, Button, ColorSwatch, Group, Stack, Text } from "@mantine/core";
import { IconBulb } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { confirmAction, listProposedActions, rejectAction, type AgentActionView } from "../../services/agent/api";

// ALERT-06: a proposta de mostrar a cor do orçamento na lâmpada. A app só pede a confirmação; o
// servidor executa uma vez e diz o que aconteceu (sucesso só com releitura, SIMULADO etiquetado).
export default function BudgetLampProposal({ householdId, refreshKey }: { householdId: string; refreshKey: number }) {
  const [proposal, setProposal] = useState<AgentActionView | null>(null);
  const [result, setResult] = useState<AgentActionView | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    listProposedActions(householdId)
      .then((all) => { if (active) setProposal(all.find((a) => a.action.command.capability === "color_rgb") ?? null); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [householdId, refreshKey]);

  const decide = (verb: typeof confirmAction) => {
    if (!proposal) return;
    setBusy(true);
    verb(householdId, proposal.action.id)
      .then((view) => { setResult(view); setProposal(null); })
      .catch(() => undefined)
      .finally(() => setBusy(false));
  };

  if (result) {
    const ok = result.execution?.status === "confirmed";
    return (
      <Alert variant="light" color={ok ? "teal" : result.action.status === "rejected" ? "gray" : "yellow"} icon={<IconBulb />} withCloseButton onClose={() => setResult(null)}>
        {result.action.status === "rejected" ? "A lâmpada fica como está." : result.message}
      </Alert>
    );
  }
  if (!proposal) return null;
  const rgb = proposal.action.command.color_rgb;
  return (
    <Alert variant="light" color="yellow" icon={<IconBulb />} title="Mostrar na lâmpada?">
      <Stack gap="sm">
        <Group gap="xs" wrap="nowrap" align="flex-start">
          {rgb && <ColorSwatch color={`rgb(${rgb.r},${rgb.g},${rgb.b})`} size={18} aria-hidden />}
          <Text size="sm">{proposal.action.rationale}</Text>
        </Group>
        <Text size="xs" c="dimmed">
          {proposal.origin === "simulated" ? "SIMULADO: nenhuma lâmpada real muda. " : ""}Nada muda sem a tua confirmação.
        </Text>
        <Group gap="xs">
          <Button size="xs" loading={busy} onClick={() => decide(confirmAction)}>Mudar a cor</Button>
          <Button size="xs" variant="subtle" disabled={busy} onClick={() => decide(rejectAction)}>Agora não</Button>
        </Group>
      </Stack>
    </Alert>
  );
}
