import { Alert, Button, Card, Loader, Stack, Text, Title } from "@mantine/core";
import { IconLogout } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useAuth } from "../../shared/auth/AuthProvider";
import { getMe, type Me } from "../me/api";

export default function Account() {
  const { logout } = useAuth();
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getMe().then(setMe).catch(() => setFailed(true));
  }, []);

  return (
    <Stack>
      <Title order={2}>Conta</Title>
      {failed ? (
        <Alert color="red">Não foi possível obter o utilizador.</Alert>
      ) : me ? (
        <Card withBorder>
          <Text fw={500}>{me.name ?? me.username}</Text>
          <Text c="dimmed">{me.email}</Text>
        </Card>
      ) : (
        <Loader />
      )}
      <Button leftSection={<IconLogout size={16} />} onClick={() => logout()} variant="light" color="red">
        Terminar sessão
      </Button>
    </Stack>
  );
}
