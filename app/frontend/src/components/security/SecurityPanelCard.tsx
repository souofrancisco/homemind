import { Alert, Badge, Button, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle } from "@tabler/icons-react";
import { useState } from "react";
import { usePolling } from "../../hooks/usePolling";
import { cancelSecurity, confirmSecurity, getSecurity, proposeSecurity, type SecurityKind, type SecurityView } from "../../services/security/api";

const dt = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });
const STATUS = { armed: ["Armado (simulado)", "red"], disarmed: ["Desarmado (simulado)", "teal"], unknown: ["Sem leitura", "gray"] } as const;
const STATUS_REAL = { armed: ["Armado (real)", "red"], disarmed: ["Desarmado (real)", "teal"], unknown: ["Sem leitura (real)", "gray"] } as const;
const AWAY = { away: "Casa aparentemente vazia", home: "Há sinais de pessoas em casa", unknown: "Presença sem sinal fiável" } as const;

/** SAFE-02: painel de segurança SIMULADO. Armar/desarmar são duas fases (proposta → confirmação) e só mudam o painel simulado. */
export default function SecurityPanelCard({ householdId }: { householdId: string }) {
  const { data, loading, offline, reload } = usePolling(householdId, getSecurity);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const act = async (run: () => Promise<SecurityView>, done?: string) => {
    setBusy(true);
    setResult(null);
    try {
      const v = await run();
      setResult(v.last_result ?? null);
      if (done) { notifications.clean(); notifications.show({ color: "green", title: "Simulado", message: done, autoClose: 5000 }); }
    } catch { /* o cliente já mostrou o motivo do servidor */ }
    finally { setBusy(false); reload(); }
  };

  if (loading) return <Group role="status"><Loader size="sm" /><Text>A consultar o painel de segurança…</Text></Group>;
  if (!data) {
    return (
      <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar o painel de segurança">
        <Button w="fit-content" color="red" variant="light" onClick={reload}>Tentar novamente</Button>
      </Alert>
    );
  }
  const v = data;
  const real = v.origin === "real";
  const [label, color] = (real ? STATUS_REAL : STATUS)[v.panel_status];
  const propose = (kind: SecurityKind) => act(() => proposeSecurity(householdId, kind));
  return (
    <Card p={{ base: "md", sm: "20px 28px" }} aria-labelledby="security-title">
      <Stack gap="sm">
        <Group justify="space-between" wrap="wrap">
          <Title id="security-title" order={2} size={18}>Alarme da casa</Title>
          <Group gap="xs">
            <Badge color={real ? "blue" : "orange"} variant="light">{real ? "REAL · só leitura" : "SIMULADO"}</Badge>
            {offline && <Badge color="gray" variant="light">Sem ligação: últimos dados</Badge>}
            <Badge color={color} variant="light">{label}</Badge>
          </Group>
        </Group>
        {!v.available ? (
          <>
            <Text size="sm" c="dimmed">Esta casa não tem painel de segurança simulado. Armamento real não está disponível.</Text>
            {real && <Text size="sm">{AWAY[v.away_status]}. {v.assessment_text}</Text>}
          </>
        ) : (
          <>
            <Text size="sm">{AWAY[v.away_status]}. {v.assessment_text}</Text>
            {v.panel_since && <Text size="xs" c="dimmed">Painel simulado desde {dt.format(new Date(v.panel_since))}.</Text>}
            {result && <Alert color="orange" title="Resultado">{result}</Alert>}
            {v.pending ? (
              <Alert color="yellow" title={v.pending.kind === "arm" ? "Confirmar: armar o painel simulado?" : "Confirmar: desarmar o painel simulado?"}>
                <Stack gap="xs">
                  <Text size="sm">Só muda o painel simulado; nada é {v.pending.kind === "arm" ? "armado" : "desarmado"} na casa real. A proposta caduca às {dt.format(new Date(v.pending.expires_at))}.</Text>
                  <Group>
                    <Button loading={busy} onClick={() => void act(() => confirmSecurity(householdId, v.pending!.id), v.pending!.kind === "arm" ? "Painel simulado armado. Nenhum alarme real foi armado." : "Painel simulado desarmado. Nenhum alarme real foi desarmado.")}>
                      Confirmar (simulado)
                    </Button>
                    <Button variant="default" loading={busy} onClick={() => void act(() => cancelSecurity(householdId, v.pending!.id))}>Cancelar</Button>
                  </Group>
                </Stack>
              </Alert>
            ) : (
              <Group>
                <Button variant="light" disabled={!v.can_arm} loading={busy} onClick={() => void propose("arm")}>Propor armar</Button>
                <Button variant="light" color="gray" disabled={!v.can_disarm} loading={busy} onClick={() => void propose("disarm")}>Propor desarmar</Button>
              </Group>
            )}
          </>
        )}
        <Text size="xs" c="dimmed">{v.notice}</Text>
      </Stack>
    </Card>
  );
}
