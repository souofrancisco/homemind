import { Alert, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconAlertCircle, IconPower } from "@tabler/icons-react";
import HomeDetails from "../components/home/HomeDetails";
import HomeStatusCards from "../components/home/HomeStatusCards";
import PowerOffModal from "../components/home/PowerOffModal";
import { useHome } from "../hooks/useHome";

const isDecision = (message: string) => /modo .* ativ(?:ado|o)|regra aplicad|regra escolhida/i.test(message);

export default function HomePage() {
  const { state, events, online, simulated } = useHome();
  const [powerOpened, powerModal] = useDisclosure(false);
  const lastDecision = events.find((event) => event.category === "mode" || event.category === "rule" || isDecision(event.message));

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center" wrap="wrap">
        <Title order={2}>Início</Title>
        <Button color="red" leftSection={<IconPower size={18} />} onClick={powerModal.open}>Desligar tudo</Button>
      </Group>

      {!state ? <Group justify="center" py="xl"><Loader size="sm" /><Text c="dimmed">A carregar o estado da casa…</Text></Group> : null}
      {state && !online ? <Alert color="orange" icon={<IconAlertCircle />} title="Ligação perdida">A mostrar o último estado recebido.</Alert> : null}
      {state ? <HomeStatusCards state={state} lastDecision={lastDecision} /> : null}
      <HomeDetails state={state} online={online} />
      <PowerOffModal opened={powerOpened} onClose={powerModal.close} simulated={simulated} />
    </Stack>
  );
}
