import { Badge, Button, Card, Group, NumberInput, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { getTariff, setTariff, type TariffIn, type TariffStatus } from "../../services/billing/api";

// Tarifário de referência (ALERT-02): só muda ESTIMATIVAS (orçamento, previsão); a fatura reparte
// sempre o total real. 1 cêntimo = 1000 milicêntimos; aqui escreve-se em €/kWh.
const sourceLabel: Record<NonNullable<TariffStatus["source"]>, string> = {
  configured: "definida por ti",
  reference: "preço de referência da casa",
  last_bill: "preço médio da última fatura",
};
const perKwh = (m: number) => `${(m / 100000).toLocaleString("pt-PT", { minimumFractionDigits: 4 })} €/kWh`;
const toMilli = (v: number | string) => Math.round(Number(v) * 100000);

export default function TariffCard({ householdId }: { householdId: string }) {
  const [status, setStatus] = useState<TariffStatus | null>(null);
  const [kind, setKind] = useState<TariffIn["kind"]>("simple");
  const [price, setPrice] = useState<number | string>("");
  const [offpeak, setOffpeak] = useState<number | string>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getTariff(householdId).then((s) => { if (active) setStatus(s); }).catch(() => undefined);
    return () => { active = false; };
  }, [householdId]);

  const valid = Number(price) > 0 && (kind === "simple" || Number(offpeak) > 0);
  const save = () => {
    setBusy(true);
    const body: TariffIn = { kind, price_millicents_per_kwh: toMilli(price), offpeak_price_millicents_per_kwh: kind === "bi_hourly" ? toMilli(offpeak) : null };
    setTariff(householdId, body).then((s) => { setStatus(s); setPrice(""); setOffpeak(""); }).catch(() => undefined).finally(() => setBusy(false));
  };
  const t = status?.tariff;

  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={3} size="h4">Tarifário de referência</Title>
          {status?.source && <Badge variant="light">{sourceLabel[status.source]}</Badge>}
        </Group>
        <Text size="sm">
          {!t ? "Sem preço: os custos estimados ficam desconhecidos até haver tarifário ou uma fatura fechada."
            : t.kind === "simple" ? `Simples: ${perKwh(t.price_millicents_per_kwh)}`
            : `Bi-horário: ${perKwh(t.price_millicents_per_kwh)} fora do vazio · ${perKwh(t.offpeak_price_millicents_per_kwh ?? 0)} no vazio`}
        </Text>
        <Text size="xs" c="dimmed">Serve só para estimar o orçamento e a previsão dos moradores. A repartição usa sempre o total real da fatura. Bi-horário simplificado: vazio das 22h às 08h e ao fim de semana.</Text>
        <SegmentedControl value={kind} onChange={(v) => setKind(v as TariffIn["kind"])} data={[{ value: "simple", label: "Simples" }, { value: "bi_hourly", label: "Bi-horário" }]} />
        <Group grow align="flex-start">
          <NumberInput label={kind === "simple" ? "Preço (€/kWh)" : "Fora do vazio (€/kWh)"} decimalScale={4} min={0} step={0.01} value={price} onChange={setPrice} />
          {kind === "bi_hourly" && <NumberInput label="Vazio (€/kWh)" decimalScale={4} min={0} step={0.01} value={offpeak} onChange={setOffpeak} />}
        </Group>
        <Button w="fit-content" disabled={!valid} loading={busy} onClick={save}>Guardar tarifário</Button>
      </Stack>
    </Card>
  );
}
