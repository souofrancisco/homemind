import { Alert, Badge, Button, Card, ColorSwatch, Group, Loader, NumberInput, Progress, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { getMyBudget, setMyBudget, type BudgetStatus } from "../services/billing/budget";
import BudgetLampProposal from "../components/billing/BudgetLampProposal";

const money = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" });
// ALERT-06: a cor vem do servidor (`BudgetStatus.light`); a app só a mostra.
const LIGHT_COLOR = { green: "green", amber: "yellow", red: "red" } as const;
const eur = (c: number | null) => (c == null ? "Desconhecido" : money.format(c / 100));

function Figure({ label, cents, hint }: { label: string; cents: number | null; hint?: string }) {
  return <Stack gap={2}><Text size="xs" c="dimmed" tt="uppercase" fw={700}>{label}</Text><Text fw={700} size="lg">{eur(cents)}</Text>{hint && <Text size="xs" c="dimmed">{hint}</Text>}</Stack>;
}

export default function BudgetContent() {
  const session = useHouseholdSession();
  const householdId = session.membership?.household_id;
  const [state, setState] = useState<{ key: string; status: BudgetStatus | null } | null>(null);
  const [limit, setLimit] = useState<number | string>("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!householdId) return;
    let active = true;
    getMyBudget(householdId)
      .then((status) => active && setState({ key: householdId, status }))
      .catch(() => active && setState({ key: householdId, status: null }));
    return () => { active = false; };
  }, [householdId, reload]);

  if (!householdId) return null;
  const cur = state?.key === householdId ? state : null;
  if (!cur) return <Group role="status"><Loader size="sm" /><Text>A carregar orçamento…</Text></Group>;
  const s = cur.status;
  if (!s) return (
    <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar o orçamento">
      <Button w="fit-content" color="red" variant="light" onClick={() => setReload((n) => n + 1)}>Tentar novamente</Button>
    </Alert>
  );
  const save = async () => {
    setBusy(true);
    try { const next = await setMyBudget(householdId, { limit_cents: Math.round(Number(limit) * 100), thresholds: [50, 80, 100] }); setState({ key: householdId, status: next }); setLimit(""); }
    catch { /* erro já mostrado */ } finally { setBusy(false); }
  };
  const pct = s.pct;
  return (
    <Stack gap="md">
      <BudgetLampProposal householdId={householdId} refreshKey={reload + (s.pct ?? 0)} />
      <Card withBorder radius="lg" p="lg">
        <Stack gap="md">
          <Group justify="space-between"><Title order={3} size="h4">Mês {s.period}</Title>
            <Badge variant="light" color={s.final ? "green" : "gray"}>{s.final ? "Valores da fatura fechada" : "Estimativa — ainda não é definitivo"}</Badge></Group>
          {s.budget?.limit_cents != null ? (
            <>
              <Progress value={Math.min(pct ?? 0, 100)} color={s.light ? LIGHT_COLOR[s.light.light] : "gray"} aria-label="Percentagem do orçamento utilizada" />
              <Text size="sm">{pct == null ? "Sem dados de custo: a percentagem é desconhecida." : `${pct} % do orçamento de ${eur(s.budget.limit_cents)} utilizado.`}</Text>
              {s.light && (
                <Group gap="xs" wrap="nowrap">
                  <ColorSwatch color={`rgb(${s.light.rgb.join(",")})`} size={18} aria-hidden />
                  <Text size="sm" fw={600}>{s.light.label}</Text>
                </Group>
              )}
            </>
          ) : <Text c="dimmed">Ainda não definiste um orçamento para este mês.</Text>}
          {!s.final && (s.forecast ? (
            <Text size="sm">
              Previsão para o fim do mês: <b>{eur(s.forecast.cents)}</b> (entre {eur(s.forecast.low_cents)} e {eur(s.forecast.high_cents)}), com base em {s.forecast.observed_days} dias de consumo deste mês.
              {s.budget?.limit_cents != null && s.forecast.cents > s.budget.limit_cents && ` Acima do orçamento em ${eur(s.forecast.cents - s.budget.limit_cents)}.`}
            </Text>
          ) : <Text size="sm" c="dimmed">Ainda não há dados suficientes para prever o fim do mês (são precisos pelo menos 3 dias).</Text>)}
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <Figure label="Gasto" cents={s.spent_cents} />
            <Figure label="Confirmado (meu)" cents={s.confirmed_cents} />
            <Figure label="Parte comum" cents={s.shared_cents} hint="estimada" />
            <Figure label="Fixo + resíduo" cents={s.base_cents} hint={s.base_cents == null ? "sem fatura anterior" : "estimado"} />
          </SimpleGrid>
          {s.provenance && <Text size="xs" c="dimmed">{s.provenance.origin === "simulated" ? "SIMULADO" : "REAL"} · {s.provenance.kind === "measured" ? "medido" : s.provenance.kind === "estimated" ? "estimado" : "inferido"}. Os avisos chegam a 50 %, 80 % e 100 %.</Text>}
        </Stack>
      </Card>
      <Card withBorder radius="lg" p="lg">
        <Group align="end">
          <NumberInput label="Orçamento mensal (€)" decimalScale={2} min={0} value={limit} onChange={setLimit} />
          <Button disabled={limit === "" || Number(limit) <= 0} loading={busy} onClick={() => void save()}>{s.budget ? "Alterar (reinicia os avisos)" : "Definir"}</Button>
        </Group>
      </Card>
    </Stack>
  );
}
