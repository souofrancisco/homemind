import {
  Alert, Badge, Button, Card, Group, Loader, NumberInput, SimpleGrid, Stack, Table, Text, TextInput, Title,
} from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import {
  createBill, finalizeBill, getBillSummary, getMyReceipt, listBills, previewBill,
  type BillAllocation, type BillIn, type BillPreview, type BillView, type LandlordBillView,
} from "../services/billing/api";

const money = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" });
const eur = (cents: number) => money.format(cents / 100);
const kwh = (wh: number) => `${(wh / 1000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} kWh`;
const day = (iso: string) => new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));
const kindLabel = { measured: "medido", estimated: "estimado", inferred: "inferido" } as const;
const originLabel = { real: "REAL", simulated: "SIMULADO" } as const;
const statusLabel: Record<BillView["status"], string> = { draft: "Rascunho", finalized: "Finalizada", superseded: "Substituída" };

function Provenance({ p }: { p: BillView["provenance"] }) {
  return <Badge variant="light" color={p.origin === "simulated" ? "orange" : "teal"}>{originLabel[p.origin]} · {kindLabel[p.kind]}</Badge>;
}

function Receipt({ householdId, bill }: { householdId: string; bill: BillView }) {
  const [state, setState] = useState<{ status: "loading" | "error" | "ready"; data?: BillAllocation }>({ status: "loading" });
  useEffect(() => {
    let active = true;
    getMyReceipt(householdId, bill.id)
      .then((data) => active && setState({ status: "ready", data }))
      .catch(() => active && setState({ status: "error" }));
    return () => { active = false; };
  }, [householdId, bill.id]);
  if (state.status === "loading") return <Loader size="sm" aria-label="A carregar recibo" />;
  if (!state.data) return <Text size="sm" c="dimmed">Sem recibo para ti nesta fatura.</Text>;
  const r = state.data;
  return (
    <Stack gap="xs">
      <Table withRowBorders={false} verticalSpacing={4}>
        <Table.Tbody>
          {r.breakdown.map((line, i) => (
            <Table.Tr key={i}>
              <Table.Td>{line.label}{line.energy_wh != null && <Text span c="dimmed" size="xs"> · {kwh(line.energy_wh)}</Text>}</Table.Td>
              <Table.Td>{line.provenance ? <Provenance p={line.provenance} /> : null}</Table.Td>
              <Table.Td ta="right">{eur(line.amount_cents)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group justify="space-between"><Text fw={700}>O teu total</Text><Text fw={700}>{eur(r.amount_cents)}</Text></Group>
      <Text size="xs" c="dimmed">Fixa {eur(r.fixed_share_cents)} · resíduo comum {eur(r.residual_share_cents)} · individual {eur(r.individual_cents)}. Calculado no servidor.</Text>
    </Stack>
  );
}

function Summary({ householdId, bill }: { householdId: string; bill: BillView }) {
  const [view, setView] = useState<LandlordBillView | null>(null);
  useEffect(() => {
    let active = true;
    getBillSummary(householdId, bill.id).then((v) => active && setView(v)).catch(() => undefined);
    return () => { active = false; };
  }, [householdId, bill.id]);
  if (!view) return <Loader size="sm" aria-label="A carregar totais" />;
  return (
    <Table withRowBorders={false} verticalSpacing={4}>
      <Table.Tbody>
        {view.rooms.map((room) => (
          <Table.Tr key={room.room_id}><Table.Td>{room.room_name}</Table.Td><Table.Td c="dimmed">{kwh(room.energy_wh)}</Table.Td><Table.Td ta="right">{eur(room.amount_cents)}</Table.Td></Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function BillForm({ householdId, origin, onCreated }: { householdId: string; origin: BillIn["origin"]; onCreated: () => void }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [total, setTotal] = useState<number | string>("");
  const [fixed, setFixed] = useState<number | string>("");
  const [energy, setEnergy] = useState<number | string>("");
  const [preview, setPreview] = useState<BillPreview | null>(null);
  const [busy, setBusy] = useState(false);

  const complete = start && end && total !== "" && fixed !== "" && energy !== "";
  // Conversão de unidades de entrada (€→cêntimos, kWh→Wh); a repartição é sempre do servidor.
  const body = (): BillIn => ({
    period: { start, end },
    total_cents: Math.round(Number(total) * 100),
    fixed_cents: Math.round(Number(fixed) * 100),
    total_wh: Math.round(Number(energy) * 1000),
    origin,
  });
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try { await action(); } catch { /* o cliente HTTP já mostra o erro */ } finally { setBusy(false); }
  };
  const reset = () => setPreview(null);

  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap="md">
        <Title order={3} size="h4">Introduzir fatura</Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput type="date" label="Início do período" value={start} onChange={(e) => { setStart(e.currentTarget.value); reset(); }} />
          <TextInput type="date" label="Fim do período" value={end} onChange={(e) => { setEnd(e.currentTarget.value); reset(); }} />
          <NumberInput label="Total da fatura (€)" decimalScale={2} min={0} value={total} onChange={(v) => { setTotal(v); reset(); }} />
          <NumberInput label="Termo fixo (€)" decimalScale={2} min={0} value={fixed} onChange={(v) => { setFixed(v); reset(); }} />
          <NumberInput label="Energia faturada (kWh)" decimalScale={2} min={0} value={energy} onChange={(v) => { setEnergy(v); reset(); }} />
        </SimpleGrid>
        {origin === "simulated" && <Text size="xs" c="orange">Casa de demonstração: a fatura fica marcada como SIMULADA.</Text>}
        <Group>
          <Button variant="light" disabled={!complete} loading={busy} onClick={() => void run(async () => setPreview(await previewBill(householdId, body())))}>Pré-visualizar</Button>
          {preview && <Button loading={busy} onClick={() => void run(async () => { await createBill(householdId, body()); reset(); onCreated(); })}>Confirmar registo</Button>}
        </Group>
        {preview && (
          <Alert color="indigo" variant="light" title="Pré-visualização (nada foi gravado)">
            {preview.days} dias · total {eur(preview.total_cents)} · fixo {eur(preview.fixed_cents)} · energia {eur(preview.energy_cents)} · {kwh(preview.total_wh)} · preço médio {(preview.price_millicents_per_kwh / 100000).toFixed(4)} €/kWh
          </Alert>
        )}
      </Stack>
    </Card>
  );
}

export default function BillsContent() {
  const session = useHouseholdSession();
  const householdId = session.membership?.household_id;
  const role = session.membership?.role;
  const [state, setState] = useState<{ key: string; bills: BillView[] | null; error: boolean } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [reload, setReload] = useState(0);
  const load = () => setReload((n) => n + 1);
  useEffect(() => {
    if (!householdId) return;
    let active = true;
    listBills(householdId)
      .then((bills) => active && setState({ key: householdId, bills, error: false }))
      .catch(() => active && setState({ key: householdId, bills: null, error: true }));
    return () => { active = false; };
  }, [householdId, reload]);

  if (!householdId || !role) return null;
  const current = state?.key === householdId ? state : null;
  const finalize = async (bill: BillView) => {
    setBusyId(bill.id);
    try { await finalizeBill(householdId, bill.id); load(); } catch { /* erro já mostrado */ } finally { setBusyId(null); }
  };

  return (
    <Stack gap="md">
      {role === "landlord" && <BillForm householdId={householdId} origin={session.house?.source_kind === "real" ? "real" : "simulated"} onCreated={() => load()} />}
      {!current ? <Group role="status"><Loader size="sm" /><Text>A carregar faturas…</Text></Group>
        : current.error ? (
          <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar as faturas">
            <Button w="fit-content" color="red" variant="light" onClick={() => load()}>Tentar novamente</Button>
          </Alert>
        ) : !current.bills?.length ? (
          <Text c="dimmed">{role === "tenant" ? "Ainda não há faturas finalizadas. Quando o senhorio fechar uma, o teu recibo aparece aqui." : "Ainda não foi registada nenhuma fatura."}</Text>
        ) : current.bills.map((bill) => (
          <Card key={bill.id} withBorder radius="lg" p="lg">
            <Stack gap="sm">
              <Group justify="space-between" align="flex-start" wrap="wrap">
                <Stack gap={2}>
                  <Title order={3} size="h4">{day(bill.period.start)} – {day(bill.period.end)}</Title>
                  <Group gap="xs"><Provenance p={bill.provenance} /><Badge color={bill.status === "finalized" ? "green" : "gray"} variant="light">{statusLabel[bill.status]}</Badge>{bill.revision > 1 && <Badge variant="outline">revisão {bill.revision}</Badge>}</Group>
                </Stack>
                <Title order={3} size="h3">{eur(bill.total_cents)}</Title>
              </Group>
              {role === "landlord" && bill.status === "draft" && (
                <Button w="fit-content" loading={busyId === bill.id} onClick={() => void finalize(bill)}>Finalizar e repartir</Button>
              )}
              {role === "landlord" && bill.status !== "draft" && <Summary householdId={householdId} bill={bill} />}
              {role === "tenant" && bill.status !== "draft" && <Receipt householdId={householdId} bill={bill} />}
            </Stack>
          </Card>
        ))}
    </Stack>
  );
}
