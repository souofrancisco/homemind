import { Alert, Badge, Button, Card, Group, Loader, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { usePolling } from "../../hooks/usePolling";
import { getOccupancy } from "../../services/presence/api";

const count = (n: number | null | undefined, unknown: string) => (n == null ? unknown : String(n));

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>{label}</Text>
      <Text fw={700} size="xl">{value}</Text>
      {hint && <Text size="xs" c="dimmed">{hint}</Text>}
    </Stack>
  );
}

/** PRES-05: quantas pessoas estão em casa e quantas são visitas. Só números: sem nomes, horários nem imagens. */
export default function OccupancyCard({ householdId }: { householdId: string }) {
  const { data, loading, offline, reload } = usePolling(householdId, getOccupancy);
  if (loading) return <Group role="status"><Loader size="sm" /><Text>A consultar ocupação…</Text></Group>;
  if (!data) {
    return (
      <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar a ocupação">
        <Button w="fit-content" color="red" variant="light" onClick={reload}>Tentar novamente</Button>
      </Alert>
    );
  }
  const uncertain = data.state === "uncertain";
  return (
    <Card withBorder radius="lg" p="lg" aria-labelledby="occupancy-title">
      <Stack gap="md">
        <Group justify="space-between" wrap="wrap">
          <Title id="occupancy-title" order={3} size="h4">Quem está em casa</Title>
          <Group gap="xs">
            {data.provenance.origin === "simulated" && <Badge color="yellow" variant="light">SIMULADO</Badge>}
            {offline && <Badge color="gray" variant="light">Sem ligação: últimos dados</Badge>}
            <Badge color={uncertain ? "gray" : "teal"} variant="light">{uncertain ? "Incerto" : "Em casa"}</Badge>
          </Group>
        </Group>
        <SimpleGrid cols={{ base: 1, xs: 3 }}>
          <Figure label="Pessoas dentro" value={count(data.people_inside, "Desconhecido")} />
          <Figure label="Moradores em casa" value={String(data.residents_home)} hint="Com telemóvel registado e consentimento" />
          <Figure label="Visitas" value={count(data.visitors, "Desconhecido")} />
        </SimpleGrid>
        <Text size="sm" c="dimmed">
          {uncertain
            ? "A contagem na porta não é fiável neste momento (câmara parada, evento perdido ou números que não batem). Em dúvida, não se assume nada."
            : "Contagem anónima na soleira da porta. As visitas são só um número: não geram contas nem pistas de ninguém."}
        </Text>
      </Stack>
    </Card>
  );
}
