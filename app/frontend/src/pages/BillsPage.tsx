import {
  Alert, Badge, Button, Card, Group, Loader, NumberInput, SimpleGrid, Stack, Table, Text, TextInput, Title,
} from "@mantine/core";
import { IconAlertCircle, IconChevronDown, IconChevronUp } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { LandlordContestations, TenantContest, type ContestTarget } from "../components/billing/Contestations";
import ReceiptExplanationView, { type Own } from "../components/billing/ReceiptExplanationView";
import OriginBadge from "../components/common/OriginBadge";
import TariffCard from "../components/billing/TariffCard";
import {
  createBill, finalizeBill, getBillSummary, getMyReceipt, getMyReceiptExplanation, listBills, previewBill, reviseBill,
  type BillAllocation, type BillIn, type BillPreview, type BillView, type LandlordBillView, type ReceiptExplanation,
} from "../services/billing/api";

const money = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" });
const eur = (cents: number) => money.format(cents / 100);
const kwh = (wh: number) => `${(wh / 1000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} kWh`;
const day = (iso: string) => new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));
const statusLabel: Record<BillView["status"], string> = { draft: "Rascunho", finalized: "Finalizada", superseded: "Substituída" };

function Provenance({ p }: { p: BillView["provenance"] }) {
  const session = useHouseholdSession();
  return <OriginBadge origin={p.origin} kind={p.kind} demo={session.house?.source_kind === "demo"} />;
}

const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });

function Receipt({ householdId, bill }: { householdId: string; bill: BillView }) {
  const [state, setState] = useState<{ status: "loading" | "error" | "ready"; data?: BillAllocation }>({ status: "loading" });
  const [target, setTarget] = useState<ContestTarget | null>(null);
  // BILL-06: só a revisão em vigor se contesta; uma substituída já foi corrigida.
  const canContest = bill.status === "finalized";
  const contest = (item: Own) => setTarget({
    consumptionEventId: item.consumption_event_id,
    label: `${item.appliance_name ?? "aparelho não identificado"}, ${when.format(new Date(item.started_at))}`,
  });
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
      <Text size="xs" c="dimmed">Parte fixa {eur(r.fixed_share_cents)} · parte comum {eur(r.residual_share_cents)} · só tua {eur(r.individual_cents)}.</Text>
      <Explanation householdId={householdId} billId={bill.id} onContest={canContest ? contest : undefined} />
      <TenantContest householdId={householdId} billId={bill.id} canContest={canContest} target={target} onClearTarget={() => setTarget(null)} />
    </Stack>
  );
}

/** «Porque pago isto?» (BILL-05): só se pede ao servidor quando o morador abre. */
function Explanation({ householdId, billId, onContest }: { householdId: string; billId: string; onContest?: (item: Own) => void }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<{ status: "idle" | "loading" | "error" | "ready"; data?: ReceiptExplanation }>({ status: "idle" });
  const load = () => {
    setState({ status: "loading" });
    getMyReceiptExplanation(householdId, billId)
      .then((data) => setState({ status: "ready", data }))
      .catch(() => setState({ status: "error" }));
  };
  const toggle = () => {
    if (!open && state.status === "idle") load();
    setOpen(!open);
  };
  return (
    <Stack gap="sm">
      <Button w="fit-content" variant="subtle" px={0} onClick={toggle} aria-expanded={open}
        rightSection={open ? <IconChevronUp size={16} /> : <IconChevronDown size={16} />}>
        Porque pago isto?
      </Button>
      {open && (state.status === "loading" ? <Loader size="sm" aria-label="A carregar explicação" />
        : state.status === "error" ? (
          <Alert color="red" variant="light" icon={<IconAlertCircle />} title="Não foi possível carregar a explicação">
            <Button size="xs" color="red" variant="light" onClick={load}>Tentar novamente</Button>
          </Alert>
        ) : state.data ? <ReceiptExplanationView data={state.data} onContest={onContest} /> : null)}
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

// `revise`: corrigir uma fatura fechada (nova revisão, BILL-04). Sem ele, regista uma fatura nova.
function BillForm({ householdId, origin, onCreated, revise, onCancel }: {
  householdId: string; origin: BillIn["origin"]; onCreated: () => void; revise?: BillView; onCancel?: () => void;
}) {
  const [start, setStart] = useState(revise?.period.start ?? "");
  const [end, setEnd] = useState(revise?.period.end ?? "");
  const [total, setTotal] = useState<number | string>(revise ? revise.total_cents / 100 : "");
  const [fixed, setFixed] = useState<number | string>(revise ? revise.fixed_cents / 100 : "");
  const [energy, setEnergy] = useState<number | string>(revise ? revise.total_wh / 1000 : "");
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
        <Title order={3} size="h4">{revise ? `Corrigir fatura (revisão ${revise.revision + 1})` : "Introduzir fatura"}</Title>
        {revise && <Text size="xs" c="dimmed">A correção reparte de novo e cria uma nova revisão; a atual fica guardada como «Substituída», com as suas parcelas, para auditoria.</Text>}
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
          {preview && <Button loading={busy} onClick={() => void run(async () => {
            await (revise ? reviseBill(householdId, revise.id, body()) : createBill(householdId, body()));
            reset(); onCreated();
          })}>{revise ? "Confirmar correção" : "Confirmar registo"}</Button>}
          {onCancel && <Button variant="subtle" onClick={onCancel}>Cancelar</Button>}
        </Group>
        {preview && (
          <Alert color="indigo" variant="light" title="Pré-visualização (nada foi gravado)">
            {preview.days} dias · total {eur(preview.total_cents)} · fixo {eur(preview.fixed_cents)} · energia {eur(preview.energy_cents)} · {kwh(preview.total_wh)} · preço médio {(preview.price_millicents_per_kwh / 100000).toLocaleString("pt-PT", { minimumFractionDigits: 4, maximumFractionDigits: 4 })} €/kWh
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
  const [revising, setRevising] = useState<string | null>(null);

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
  const origin: BillIn["origin"] = session.house?.source_kind === "real" ? "real" : "simulated";
  const finalize = async (bill: BillView) => {
    setBusyId(bill.id);
    try { await finalizeBill(householdId, bill.id); load(); } catch { /* erro já mostrado */ } finally { setBusyId(null); }
  };

  return (
    <Stack gap="md">
      {role === "landlord" && <LandlordContestations householdId={householdId} reload={reload} onDecided={() => load()} />}
      {role === "landlord" && <BillForm householdId={householdId} origin={origin} onCreated={() => load()} />}
      {role === "landlord" && <TariffCard householdId={householdId} />}
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
              {role === "landlord" && bill.status === "finalized" && (revising === bill.id
                ? <BillForm householdId={householdId} origin={origin} revise={bill} onCancel={() => setRevising(null)} onCreated={() => { setRevising(null); load(); }} />
                : <Button w="fit-content" variant="subtle" onClick={() => setRevising(bill.id)}>Corrigir fatura</Button>)}
              {role === "tenant" && bill.status !== "draft" && <Receipt householdId={householdId} bill={bill} />}
            </Stack>
          </Card>
        ))}
    </Stack>
  );
}
