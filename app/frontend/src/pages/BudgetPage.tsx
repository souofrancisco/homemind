import { Alert, Badge, Button, Card, ColorSwatch, Group, Loader, NumberInput, Progress, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { getMyBudget, setMyBudget, type BudgetStatus } from "../services/billing/budget";
import BudgetLampProposal from "../components/billing/BudgetLampProposal";
import OriginBadge from "../components/common/OriginBadge";

const money = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" });
const eur = (c: number | null) => (c == null ? "Desconhecido" : money.format(c / 100));
const monthName = (period: string) => {
  const name = new Intl.DateTimeFormat("pt-PT", { month: "long", year: "numeric" }).format(new Date(`${period}-01T12:00:00`));
  return name.charAt(0).toLocaleUpperCase("pt-PT") + name.slice(1);
};

function Figure({ label, cents, hint }: { label: string; cents: number | null; hint?: string }) {
  return <Stack gap={2}><Text size="sm" c="dimmed">{label}</Text><Text fw={700} fz={26} lh={1.15} className="conta-number">{eur(cents)}</Text>{hint && <Text size="xs" c="dimmed">{hint}</Text>}</Stack>;
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
  const hasBudget = s.budget?.limit_cents != null;
  // A ação vem primeiro: sem orçamento, o formulário abre a página; com orçamento, fica depois dos números.
  const budgetForm = (
    <Card p={{ base: "md", sm: "24px 28px" }}>
      <Group align="flex-end" gap={16} wrap="wrap">
        <Stack gap={4} style={{ flex: "1 1 280px" }}>
          <Title order={2} size={18}>{hasBudget ? "Mudar o orçamento" : "Quanto queres gastar por mês?"}</Title>
          {!hasBudget && <Text size="sm" c="dimmed" mb={8}>Dizemos-te quando chegares a 50 %, 80 % e 100 %. Podes mudar quando quiseres.</Text>}
          <NumberInput aria-label="Orçamento mensal (€)" placeholder="Orçamento mensal (€)" decimalScale={2} min={0} value={limit} onChange={setLimit} maw={320}
            styles={{ input: { minHeight: 48, fontSize: 16, borderRadius: 12 } }} />
        </Stack>
        <Button mih={48} px={24} fw={700} disabled={limit === "" || Number(limit) <= 0} loading={busy} onClick={() => void save()}>{hasBudget ? "Guardar" : "Definir"}</Button>
      </Group>
    </Card>
  );
  return (
    <Stack gap={24}>
      {!hasBudget && budgetForm}
      <BudgetLampProposal householdId={householdId} refreshKey={reload + (s.pct ?? 0)} />
      <Card p={{ base: "md", sm: 28 }}>
        <Stack gap="sm">
          <Group justify="space-between"><Title order={2} size={22}>{monthName(s.period)}</Title>
            <Badge variant="light" color={s.final ? "green" : "gray"}>{s.final ? "Valores da fatura fechada" : "Estimado até ao fecho do mês"}</Badge></Group>
          {s.budget?.limit_cents != null ? (
            <>
              <Progress size={8} mt={6} value={Math.min(pct ?? 0, 100)} color="ink" aria-label="Percentagem do orçamento utilizada" />
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
              Previsão para o fim do mês: <b>{eur(s.forecast.cents)}</b>, com base em {s.forecast.observed_days} dias de consumo deste mês.
            </Text>
          ) : <Text size="sm" c="dimmed">Ainda não há dados suficientes para prever o fim do mês (são precisos pelo menos 3 dias).</Text>)}
          <SimpleGrid className="conta-figures" cols={{ base: 2, sm: 4 }} spacing={24}>
            <Figure label="Até agora" cents={s.spent_cents} />
            <Figure label="O teu quarto" cents={s.confirmed_cents} />
            <Figure label="A tua parte das zonas comuns" cents={s.shared_cents} hint="estimada" />
            <Figure label="Parte fixa da fatura" cents={s.base_cents} hint={s.base_cents == null ? "ainda sem fatura" : "estimada"} />
          </SimpleGrid>
          {s.provenance && <Group><OriginBadge origin={s.provenance.origin} kind={s.provenance.kind} demo={session.house?.source_kind === "demo"} /></Group>}
        </Stack>
      </Card>
      {s.budget?.limit_cents != null && budgetForm}
    </Stack>
  );
}
