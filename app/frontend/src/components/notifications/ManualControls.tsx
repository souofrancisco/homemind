import { Alert, Badge, Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { IconBulb, IconPlug } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import {
  confirmAction, listProposedActions, rejectAction, sendAgentMessage, type AgentActionView,
} from "../../services/agent/api";

// APP-04: controlos manuais sem câmara. Nada é executado aqui: «Pedir» cria uma PROPOSTA no
// backend (mesma rota do assistente) e só a confirmação humana a executa, com a política MCP-04
// (flag + grant + releitura). A UI só mostra sucesso quando o servidor diz `confirmed` (releitura).
const REQUESTS = [
  { label: "Lâmpada", text: "desliga a lâmpada", icon: IconBulb },
  { label: "Tomada", text: "desliga a tomada", icon: IconPlug },
] as const;

type Outcome = { tone: "teal" | "yellow" | "orange" | "gray"; title: string; message: string };

// Incerto nunca é apresentado como sucesso nem repetido (política MCP-04).
export function outcomeOf(view: AgentActionView): Outcome {
  if (view.action.status === "rejected") return { tone: "gray", title: "Não executado", message: view.message };
  switch (view.execution?.status) {
    case "confirmed": return { tone: "teal", title: "Confirmado por releitura", message: view.message };
    case "uncertain": return { tone: "orange", title: "Resultado incerto", message: view.message };
    case "blocked": return { tone: "yellow", title: "Bloqueado, nada foi executado", message: view.message };
    case "failed": return { tone: "yellow", title: "Falhou, nada foi aplicado", message: view.message };
    default: return { tone: "gray", title: "Sem resultado", message: view.message };
  }
}

export default function ManualControls({ householdId }: { householdId: string }) {
  const [pending, setPending] = useState<AgentActionView[]>([]);
  const [results, setResults] = useState<Array<{ id: string; device: string; origin: AgentActionView["origin"]; outcome: Outcome }>>([]);
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => listProposedActions(householdId)
    .then((all) => setPending(all.filter((a) => a.action.command.capability === "power")))
    .catch(() => undefined), [householdId]);
  useEffect(() => { void refresh(); }, [refresh]);

  const request = async (text: string, key: string) => {
    setBusy(key); setInfo("");
    try {
      const reply = await sendAgentMessage(householdId, { text });
      setInfo(reply.text);
      await refresh();
    } catch { /* o cliente HTTP já mostrou o erro */ } finally { setBusy(null); }
  };

  const decide = async (view: AgentActionView, verb: typeof confirmAction) => {
    setBusy(view.action.id);
    try {
      const done = await verb(householdId, view.action.id);
      setResults((r) => [{ id: done.action.id, device: done.device_name, origin: done.origin, outcome: outcomeOf(done) }, ...r]);
      setInfo("");
      await refresh();
    } catch { /* idem */ } finally { setBusy(null); }
  };

  return (
    <Card withBorder radius="lg" p="lg" component="section" aria-labelledby="manual-controls-title">
      <Stack gap="sm">
        <Title id="manual-controls-title" order={3} size="h4">Controlos manuais</Title>
        <Text size="sm" c="dimmed">
          Pede ao servidor para desligar um dispositivo autorizado. Nada muda até confirmares, e só aparece
          «confirmado» depois de o servidor reler o estado. Um resultado incerto fica incerto e não se repete.
        </Text>
        <Group gap="xs" role="group" aria-label="Pedir para desligar um dispositivo">
          {REQUESTS.map(({ label, text, icon: Icon }) => (
            <Button key={label} variant="light" leftSection={<Icon size={18} aria-hidden="true" />}
              loading={busy === label} disabled={busy !== null && busy !== label}
              aria-label={`Pedir para desligar: ${label}`} onClick={() => void request(text, label)}>
              Desligar {label.toLowerCase()}
            </Button>
          ))}
        </Group>
        <div role="status" aria-live="polite">
          {info && <Text size="sm">{info}</Text>}
        </div>
        {pending.map((v) => (
          <Alert key={v.action.id} variant="light" color="yellow" title={`Confirmar: desligar «${v.device_name}»?`}>
            <Stack gap="xs">
              <Group gap="xs">
                <Badge color={v.origin === "simulated" ? "orange" : "teal"} variant="light">{v.origin === "simulated" ? "SIMULADO" : "REAL"}</Badge>
                <Text size="sm">{v.action.rationale}</Text>
              </Group>
              {v.origin === "simulated" && <Text size="xs" c="dimmed">Nenhum aparelho real muda.</Text>}
              <Group gap="xs">
                <Button size="sm" loading={busy === v.action.id} aria-label={`Confirmar desligar ${v.device_name}`} onClick={() => void decide(v, confirmAction)}>Confirmar</Button>
                <Button size="sm" variant="subtle" disabled={busy === v.action.id} aria-label={`Rejeitar desligar ${v.device_name}`} onClick={() => void decide(v, rejectAction)}>Agora não</Button>
              </Group>
            </Stack>
          </Alert>
        ))}
        <div role="status" aria-live="assertive">
          {results.map((r) => (
            <Alert key={r.id} mb="xs" variant="light" color={r.outcome.tone} title={`${r.device}: ${r.outcome.title}`} withCloseButton
              closeButtonLabel="Fechar aviso" onClose={() => setResults((all) => all.filter((x) => x.id !== r.id))}>
              {r.outcome.message}
              <Text size="xs" c="dimmed" mt={4}>{r.origin === "simulated" ? "SIMULADO" : "REAL"}</Text>
            </Alert>
          ))}
        </div>
      </Stack>
    </Card>
  );
}
