import { Alert, Badge, Card, Group, Loader, Progress, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { usePolling } from "../hooks/usePolling";
import { listAppliances, type ApplianceView } from "../services/appliances/api";
import { getEnergyOverview, type ConsumptionSession, type MeterReading } from "../services/energy/api";

const STALE_MS = 5 * 60 * 1000;
const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "medium" });
const kind = { measured: "medido", estimated: "estimado", inferred: "inferido" } as const;
const origin = { real: "REAL", simulated: "SIMULADO" } as const;
const where = { room: "quarto", common: "zona comum", unknown: "localização desconhecida" } as const;
export const euro = (c: number) => new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" }).format(c / 100);

export function useEnergy() {
  const session = useHouseholdSession();
  const id = session.membership?.household_id;
  const energy = usePolling(id, getEnergyOverview);
  const apps = usePolling(id, listAppliances, 60000);
  return { energy, appliances: apps.data ?? [] };
}

export function MeterCard({ m, now }: { m: MeterReading; now: string }) {
  const age = new Date(now).getTime() - new Date(m.read_at).getTime();
  const stale = m.status === "stale" || age > STALE_MS;
  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap={4}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Tomada medida (não é o total da casa)</Text>
        <Text fz={32} fw={700}>{m.power_w == null ? "Sem dados" : `${Math.round(m.power_w)} W`}</Text>
        <Text size="sm" c="dimmed">Última leitura: {when.format(new Date(m.read_at))}</Text>
        <Group gap="xs">
          <Badge variant="light" color={m.provenance.origin === "simulated" ? "orange" : "teal"}>{origin[m.provenance.origin]} · {kind[m.provenance.kind]}</Badge>
          {stale && <Badge color="yellow" variant="light">Leitura antiga</Badge>}
          {m.status === "unit_unknown" && <Badge color="gray" variant="light">Unidade desconhecida</Badge>}
        </Group>
      </Stack>
    </Card>
  );
}

export function SessionRow({ s, appliances, maxPeak }: { s: ConsumptionSession; appliances: ApplianceView[]; maxPeak: number }) {
  const app = s.appliance_id ? appliances.find((a) => a.id === s.appliance_id) : undefined;
  return (
    <Stack gap={4}>
      <Group justify="space-between" wrap="wrap">
        <Text fw={600}>{s.appliance_id ? (app?.name ?? "Aparelho identificado") : "Consumo não identificado"}
          {s.confidence != null && <Text span c="dimmed" size="sm"> · confiança {Math.round(s.confidence * 100)} %</Text>}</Text>
        <Badge variant="light" color={s.status === "ongoing" ? "blue" : "gray"}>{s.status === "ongoing" ? "a decorrer" : "terminado"}</Badge>
      </Group>
      <Progress value={maxPeak > 0 ? (s.peak_w / maxPeak) * 100 : 0} aria-label={`Pico de ${Math.round(s.peak_w)} W`} />
      <Text size="xs" c="dimmed">
        {when.format(new Date(s.started_at))}{s.ended_at ? ` – ${when.format(new Date(s.ended_at))}` : ""} · pico {Math.round(s.peak_w)} W · {s.energy_wh == null ? "energia desconhecida" : `${(s.energy_wh / 1000).toFixed(2)} kWh`} · {where[s.location]} · custo {s.cost_cents == null ? "desconhecido" : euro(s.cost_cents)} · {origin[s.provenance.origin]} · {kind[s.provenance.kind]}
      </Text>
    </Stack>
  );
}

export default function EnergyContent() {
  const { energy, appliances } = useEnergy();
  if (energy.loading) return <Group role="status"><Loader size="sm" /><Text>A carregar consumo…</Text></Group>;
  const o = energy.data;
  if (!o) return <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar o consumo">Sem ligação ao servidor.</Alert>;
  const maxPeak = Math.max(0, ...o.sessions.map((s) => s.peak_w));
  return (
    <Stack gap="md">
      {energy.offline && <Alert color="yellow" title="Sem ligação — a mostrar os últimos dados recebidos" />}
      {o.meters.length === 0 ? <Text c="dimmed">Sem dados: ainda não há leituras de nenhuma tomada.</Text> : o.meters.map((m) => <MeterCard key={m.device_id} m={m} now={o.now} />)}
      <Card withBorder radius="lg" p="lg">
        <Stack gap="md">
          <Title order={3} size="h4">Sessões de consumo recentes</Title>
          {o.sessions.length === 0 ? <Text c="dimmed">Sem sessões detetadas.</Text> : o.sessions.map((s) => <SessionRow key={s.id} s={s} appliances={appliances} maxPeak={maxPeak} />)}
        </Stack>
      </Card>
    </Stack>
  );
}
