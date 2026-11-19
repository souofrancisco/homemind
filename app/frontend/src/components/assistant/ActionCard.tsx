import { Alert, Button, Card, Group, Stack, Text } from "@mantine/core";
import { useState } from "react";
import { confirmAction, rejectAction, type AgentActionView } from "../../services/agent/api";
import { useHouseholdSession } from "../../app/providers/HouseholdProvider";
import OriginBadge from "../common/OriginBadge";

export default function ActionCard({
  householdId,
  value,
  onChange,
}: {
  householdId: string;
  value: AgentActionView;
  onChange: (value: AgentActionView) => void;
}) {
  const session = useHouseholdSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const proposed = value.action.status === "proposed";

  async function decide(kind: "confirm" | "reject") {
    setBusy(true);
    setError(false);
    try {
      onChange(await (kind === "confirm"
        ? confirmAction(householdId, value.action.id)
        : rejectAction(householdId, value.action.id)));
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card withBorder radius="md" p="sm" aria-label="Ação proposta">
      <Stack gap="xs">
        <Text fw={600}>{value.action.rationale}</Text>
        <Group gap="xs"><Text size="sm" c="dimmed">{value.device_name}</Text><OriginBadge origin={value.origin} demo={session.house?.source_kind === "demo"} /></Group>
        {!proposed && <Alert color="gray" variant="light" role="status">{value.message}</Alert>}
        {error && <Alert color="red" role="alert">Não foi possível confirmar o resultado. Tenta novamente.</Alert>}
        {proposed && <Group gap="sm">
          <Button size="sm" loading={busy} onClick={() => void decide("confirm")}>Confirmar</Button>
          <Button size="sm" variant="light" color="gray" loading={busy} onClick={() => void decide("reject")}>Rejeitar</Button>
        </Group>}
      </Stack>
    </Card>
  );
}
