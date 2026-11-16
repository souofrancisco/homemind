import { Alert, Badge, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useAuth } from "../../shared/auth/AuthProvider";
import { getHealth, type Health } from "../health/api";

export default function Dashboard() {
  const { user } = useAuth();
  const [health, setHealth] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setFailed(true));
  }, []);

  return (
    <Stack>
      <Title order={2}>Olá, {user?.profile.name ?? user?.profile.email}</Title>
      <Card withBorder>
        <Group justify="space-between">
          <Text fw={500}>Backend</Text>
          {failed ? (
            <Alert color="red" icon={<IconAlertCircle />} p="xs">
              Indisponível
            </Alert>
          ) : health ? (
            <Badge color={health.mode === "real" ? "green" : "yellow"}>
              {health.status} · {health.mode}
            </Badge>
          ) : (
            <Loader size="sm" />
          )}
        </Group>
      </Card>
      <Text c="dimmed">Sem estadias ou espaços por mostrar.</Text>
    </Stack>
  );
}
