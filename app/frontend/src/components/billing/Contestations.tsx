import { Alert, Badge, Button, Card, Group, Loader, Stack, Text, Textarea, Title } from "@mantine/core";
import { IconAlertCircle, IconScale } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import {
  contestBill, decideContestation, listContestations, listMyContestations,
  type Contestation, type LandlordContestationView,
} from "../../services/billing/api";

const money = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" });
const eur = (cents: number) => money.format(cents / 100);
const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeStyle: "short" });
const statusLabel = { open: "Em análise", accepted: "Aceite", rejected: "Rejeitada" } as const;
const statusColor = { open: "yellow", accepted: "green", rejected: "gray" } as const;

/** O consumo que o morador escolheu contestar na explicação do recibo (BILL-05). */
export interface ContestTarget { consumptionEventId: string; label: string }

function Outcome({ c }: { c: Pick<Contestation, "status" | "resolution" | "before_cents" | "after_cents"> }) {
  if (c.status === "open") return null;
  return (
    <Text size="sm">
      {c.resolution}
      {c.before_cents != null && c.after_cents != null && (
        <Text span c="dimmed"> · parcela {eur(c.before_cents)} → {eur(c.after_cents)}</Text>
      )}
    </Text>
  );
}

/** Inquilino: contestar o próprio recibo, em geral ou um consumo seu, e ver o estado. */
export function TenantContest({ householdId, billId, canContest, target, onClearTarget }: {
  householdId: string; billId: string; canContest: boolean; target: ContestTarget | null; onClearTarget: () => void;
}) {
  const [mine, setMine] = useState<Contestation[] | null>(null);
  const [writing, setWriting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    listMyContestations(householdId)
      .then((all) => active && setMine(all.filter((c) => c.bill_id === billId)))
      .catch(() => active && setMine([]));
    return () => { active = false; };
  }, [householdId, billId, reload]);

  const open = mine?.some((c) => c.status === "open") ?? false;
  const showForm = canContest && !open && (writing || target !== null);
  const send = async () => {
    setBusy(true);
    try {
      await contestBill(householdId, billId, { reason: reason.trim(), consumption_event_id: target?.consumptionEventId ?? null });
      setReason(""); setWriting(false); onClearTarget(); setReload((n) => n + 1);
    } catch { /* o cliente HTTP já mostra o erro */ } finally { setBusy(false); }
  };

  if (mine === null) return <Loader size="xs" aria-label="A carregar contestações" />;
  return (
    <Stack gap="xs">
      {mine.map((c) => (
        <Alert key={c.id} variant="light" color={statusColor[c.status]} icon={<IconScale />}
          title={<Group gap="xs">Contestação <Badge size="sm" variant="light" color={statusColor[c.status]}>{statusLabel[c.status]}</Badge></Group>}>
          <Text size="sm">«{c.reason}»{c.consumption_event_id ? " · sobre um consumo" : ""}</Text>
          <Outcome c={c} />
          {c.status === "accepted" && <Text size="xs" c="dimmed">A fatura foi reemitida: o recibo corrigido aparece na nova revisão.</Text>}
        </Alert>
      ))}
      {showForm ? (
        <Card withBorder radius="md" p="md">
          <Stack gap="xs">
            <Text fw={600}>{target ? `Contestar: ${target.label}` : "Contestar este recibo"}</Text>
            <Text size="xs" c="dimmed">
              {target
                ? "Se o senhorio aceitar, este consumo passa para a conta comum e a fatura é reemitida."
                : "O senhorio vê o teu quarto e o motivo, nunca os teus consumos nem horários."}
            </Text>
            <Textarea label="Motivo" autosize minRows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
            <Group>
              <Button size="xs" disabled={!reason.trim()} loading={busy} onClick={() => void send()}>Enviar ao senhorio</Button>
              <Button size="xs" variant="subtle" onClick={() => { setWriting(false); onClearTarget(); }}>Cancelar</Button>
            </Group>
          </Stack>
        </Card>
      ) : canContest && !open ? (
        <Button w="fit-content" size="xs" variant="subtle" px={0} leftSection={<IconScale size={14} />} onClick={() => setWriting(true)}>
          Não concordo com este recibo
        </Button>
      ) : null}
    </Stack>
  );
}

function Decide({ householdId, c, onDone }: { householdId: string; c: LandlordContestationView; onDone: () => void }) {
  const [resolution, setResolution] = useState("");
  const [busy, setBusy] = useState(false);
  const decide = async (status: "accepted" | "rejected") => {
    setBusy(true);
    try { await decideContestation(householdId, c.id, { status, resolution: resolution.trim() }); onDone(); }
    catch { /* o cliente HTTP já mostra o erro */ } finally { setBusy(false); }
  };
  return (
    <Stack gap="xs">
      <Textarea label="Justificação (o morador vê-a)" autosize minRows={2} maxLength={500} value={resolution} onChange={(e) => setResolution(e.currentTarget.value)} />
      <Text size="xs" c="dimmed">
        Aceitar reemite a fatura como nova revisão (a atual fica guardada)
        {c.contests_consumption ? " e passa o consumo contestado para a conta comum, por igual." : "."}
      </Text>
      <Group>
        <Button size="xs" color="green" disabled={!resolution.trim()} loading={busy} onClick={() => void decide("accepted")}>Aceitar e reemitir</Button>
        <Button size="xs" color="gray" variant="light" disabled={!resolution.trim()} loading={busy} onClick={() => void decide("rejected")}>Rejeitar</Button>
      </Group>
    </Stack>
  );
}

/** Senhorio: contestações por quarto, com motivo e decisão (nunca o consumo nem o morador). */
export function LandlordContestations({ householdId, reload, onDecided }: { householdId: string; reload: number; onDecided: () => void }) {
  const [list, setList] = useState<LandlordContestationView[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    listContestations(householdId)
      .then((l) => { if (active) { setList(l); setError(false); } })
      .catch(() => active && setError(true));
    return () => { active = false; };
  }, [householdId, reload]);

  if (error) return <Alert color="red" variant="light" icon={<IconAlertCircle />}>Não foi possível consultar as contestações.</Alert>;
  if (!list?.length) return null;
  const open = list.filter((c) => c.status === "open").length;
  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={3} size="h4">Contestações</Title>
          {open > 0 && <Badge color="yellow" variant="light">{open} por decidir</Badge>}
        </Group>
        {list.map((c) => (
          <Stack key={c.id} gap={6}>
            <Group gap="xs">
              <Text fw={600}>{c.room_name ?? "Quarto"}</Text>
              <Badge size="sm" variant="light" color={statusColor[c.status]}>{statusLabel[c.status]}</Badge>
              {c.contests_consumption && <Badge size="sm" variant="outline">sobre um consumo</Badge>}
              <Text size="xs" c="dimmed">{when.format(new Date(c.created_at))}</Text>
            </Group>
            <Text size="sm">«{c.reason}»</Text>
            {c.status === "open" ? <Decide householdId={householdId} c={c} onDone={onDecided} /> : <Outcome c={c} />}
          </Stack>
        ))}
      </Stack>
    </Card>
  );
}
