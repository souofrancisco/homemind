import { Alert, Badge, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { usePolling } from "../hooks/usePolling";
import { listAppliances } from "../services/appliances/api";

const scope = { personal: "Pessoal", shared: "Partilhado", common: "Zona comum" } as const;
const category = { heating: "Aquecimento", cooling: "Arrefecimento", kitchen: "Cozinha", laundry: "Roupa", electronics: "Eletrónica", lighting: "Iluminação", other: "Outro" } as const;

export default function AppliancesContent() {
  const session = useHouseholdSession();
  const id = session.membership?.household_id;
  const list = usePolling(id, listAppliances, 60000);
  if (session.membership?.role !== "tenant") return <Text c="dimmed">O catálogo de aparelhos é visível apenas aos moradores.</Text>;
  if (list.loading) return <Group role="status"><Loader size="sm" /><Text>A carregar aparelhos…</Text></Group>;
  if (!list.data) return <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar os aparelhos" />;
  if (!list.data.length) return <Text c="dimmed">Ainda não há aparelhos registados nesta casa.</Text>;
  const room = (rid: string | null) => session.rooms.find((r) => r.id === rid)?.name;
  return (
    <Stack gap="md">
      {list.data.map((a) => (
        <Card key={a.id} withBorder radius="lg" p="lg">
          <Group justify="space-between" wrap="wrap">
            <Stack gap={2}>
              <Title order={3} size="h4">{a.name}</Title>
              <Text size="sm" c="dimmed">{category[a.category]}{a.typical_watts != null ? ` · ~${a.typical_watts} W` : ""} · {room(a.ownership.home_room_id) ?? "localização não declarada"}</Text>
            </Stack>
            <Group gap="xs">
              <Badge variant="light">{scope[a.ownership.scope]}</Badge>
              {a.status === "retired" && <Badge color="gray" variant="light">Retirado</Badge>}
            </Group>
          </Group>
        </Card>
      ))}
    </Stack>
  );
}
