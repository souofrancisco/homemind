import { Badge, Button, Card, Group, Modal, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconPlugOff, IconThumbDown, IconThumbUp } from "@tabler/icons-react";
import type { AutomationView } from "../../services/automations/api";
import { describeTrigger, originLabel } from "./format";

type Props = {
  rule: AutomationView;
  tapName: (id: string | null | undefined) => string;
  busy: boolean;
  onVote: (approve: boolean) => void;
  onSuspend: () => void;
  onReactivate: () => void;
};

const dt = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });

export default function RuleCard({ rule, tapName, busy, onVote, onSuspend, onReactivate }: Props) {
  const pending = rule.vote_open;
  const reactivating = pending && rule.status === "disabled";
  const [confirming, { open, close }] = useDisclosure(false);
  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Title order={3} size="h4">{rule.name}</Title>
          <Group gap="xs">
            <Badge color={rule.origin === "simulated" ? "grape" : "teal"} variant="light">{originLabel(rule.origin)}</Badge>
            {rule.status === "active" && <Badge color="green" variant="light">Ativa</Badge>}
            {rule.status === "disabled" && !pending && <Badge color="gray" variant="light">Suspensa</Badge>}
            {pending && <Badge color="yellow" variant="light">{reactivating ? "Reativação em votação" : "Em votação"}</Badge>}
          </Group>
        </Group>
        <Text size="sm">{describeTrigger(rule.trigger, tapName)}.</Text>
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <IconPlugOff size={18} aria-hidden="true" style={{ flexShrink: 0, marginTop: 2 }} />
          <Text size="sm">Desliga a tomada «{rule.device_name}». Pode ser a extensão que alimenta vários aparelhos: desligá-la corta tudo o que lá está.</Text>
        </Group>
        {pending && (
          <>
            <Text size="sm" c="dimmed">
              {rule.votes_for} a favor · {rule.votes_against} contra · {rule.majority} necessários (de {rule.eligible} moradores). Votação até {dt.format(new Date(rule.vote_deadline))} (24 h); sem maioria, a proposta é rejeitada.
            </Text>
            <Group>
              <Button leftSection={<IconThumbUp size={18} />} variant={rule.my_vote === true ? "filled" : "light"} color="green" disabled={rule.my_vote != null} loading={busy} onClick={() => onVote(true)}>A favor</Button>
              <Button leftSection={<IconThumbDown size={18} />} variant={rule.my_vote === false ? "filled" : "light"} color="red" disabled={rule.my_vote != null} loading={busy} onClick={() => onVote(false)}>Contra</Button>
            </Group>
            {rule.my_vote != null && <Text size="xs" c="dimmed">O teu voto: {rule.my_vote ? "a favor" : "contra"}. Não pode ser alterado.</Text>}
          </>
        )}
        {rule.status === "active" && <Button w="fit-content" variant="light" color="red" loading={busy} onClick={open}>Suspender</Button>}
        {rule.status === "disabled" && !pending && <Button w="fit-content" variant="light" loading={busy} onClick={onReactivate}>Reativar (abre nova votação)</Button>}
      </Stack>
      <Modal opened={confirming} onClose={close} title="Suspender regra" centered>
        <Stack gap="md">
          <Text size="sm">«{rule.name}» deixa de desligar a tomada de imediato. Para voltar a ativá-la é preciso uma nova votação.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>Cancelar</Button>
            <Button color="red" onClick={() => { close(); onSuspend(); }}>Suspender</Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}
