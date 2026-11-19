import { Badge, Card, Group, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { usePolling } from "../hooks/usePolling";
import { listAppliances, type ApplianceView } from "../services/appliances/api";
import { getEnergyOverview, type ConsumptionSession, type MeterReading } from "../services/energy/api";
import OriginBadge from "../components/common/OriginBadge";

const STALE_MS = 5 * 60 * 1000;
const clock = new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "2-digit", year: "2-digit" });
const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeStyle: "short" });
const where = { room: "Quarto", common: "Zona comum", unknown: "Local desconhecido" } as const;
export const euro = (c: number) => new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" }).format(c / 100);

export function useEnergy() {
  const session = useHouseholdSession();
  const id = session.membership?.household_id;
  const energy = usePolling(id, getEnergyOverview);
  const apps = usePolling(id, listAppliances, 60000);
  return { energy, appliances: apps.data ?? [] };
}

// Um cartão por tomada com leitura atual; as antigas (por exemplo, a tomada de um cenário que já
// acabou) só aparecem se não houver nenhuma atual, e então só a mais recente.
export function visibleMeters(meters: MeterReading[], now: string): MeterReading[] {
  const age = (m: MeterReading) => new Date(now).getTime() - new Date(m.read_at).getTime();
  const fresh = meters.filter((m) => m.status !== "stale" && age(m) <= STALE_MS);
  if (fresh.length > 0) return fresh;
  return [...meters].sort((a, b) => new Date(b.read_at).getTime() - new Date(a.read_at).getTime()).slice(0, 1);
}

/** Cartão de número grande: legenda (14 px), valor (40 px, negrito) e nota (13 px). */
export function StatCard({ label, value, caption, small, className, children }: {
  label: string; value: string; caption?: ReactNode; small?: boolean; className?: string; children?: ReactNode;
}) {
  return (
    <Card className={className} p={{ base: "md", sm: 24 }} component="section" aria-label={label}>
      <Text size="sm" c="dimmed">{label}</Text>
      <Text className="conta-number" fz={small ? 26 : { base: 30, sm: 40 }} fw={700} lh={1} mt={6}>{value}</Text>
      {children}
      {caption && <Text size="xs" c="dimmed" mt={8} fz={13}>{caption}</Text>}
    </Card>
  );
}

function ago(readAt: string, now: string) {
  const s = Math.max(0, Math.round((new Date(now).getTime() - new Date(readAt).getTime()) / 1000));
  if (s < 60) return `há ${s} segundo${s === 1 ? "" : "s"}`;
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  return when.format(new Date(readAt));
}

export function MeterCard({ m, now }: { m: MeterReading; now: string }) {
  const session = useHouseholdSession();
  const age = new Date(now).getTime() - new Date(m.read_at).getTime();
  const stale = m.status === "stale" || age > STALE_MS;
  return (
    <StatCard label="Agora, na tomada da sala" value={m.power_w == null ? "Sem dados" : `${Math.round(m.power_w)} W`} small={m.power_w == null}
      caption={ago(m.read_at, now)}>
      <Group gap="xs" mt={8}>
        <OriginBadge origin={m.provenance.origin} kind={m.provenance.kind} demo={session.house?.source_kind === "demo"} />
        {stale && <Badge color="yellow" variant="light">Leitura antiga</Badge>}
        {m.status === "unit_unknown" && <Badge color="gray" variant="light">Unidade desconhecida</Badge>}
      </Group>
    </StatCard>
  );
}

export function SessionRow({ s, appliances }: { s: ConsumptionSession; appliances: ApplianceView[] }) {
  const session = useHouseholdSession();
  const app = s.appliance_id ? appliances.find((a) => a.id === s.appliance_id) : undefined;
  const start = new Date(s.started_at);
  const sameDay = start.toDateString() === new Date().toDateString();
  const duration = s.ended_at ? Math.max(0, Math.round((new Date(s.ended_at).getTime() - start.getTime()) / 60000)) : null;
  const confidence = s.confidence == null ? null : s.confidence >= 0.9 ? "quase certo" : s.confidence >= 0.7 ? "provável" : "possível";
  const energy = s.energy_wh == null ? "Energia desconhecida" : `${(s.energy_wh / 1000).toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} kWh`;
  const unidentified = s.appliance_id == null;
  return (
    <div className="conta-row-wrap">
      <div className="conta-row">
        <b className="conta-row-name">{unidentified ? "Não sei o que era" : (app?.name ?? "Aparelho identificado")}</b>
        <span className="conta-row-when">{sameDay ? "Hoje" : day.format(start)}, {clock.format(start)}{duration == null ? "" : ` · ${duration} min`}</span>
        <span className="conta-row-energy">{energy}</span>
        <span className={unidentified ? "conta-row-state conta-row-state-pending" : "conta-row-state"}>{unidentified ? `${where[s.location]} · por identificar` : where[s.location]}</span>
      </div>
      <details className="conta-row-details"><summary><Text span size="xs" c="dimmed">Ver detalhes</Text></summary><Stack gap={4} mt="xs">
        <Text size="xs" c="dimmed">Pico {Math.round(s.peak_w).toLocaleString("pt-PT")} W · custo {s.cost_cents == null ? "desconhecido" : euro(s.cost_cents)} · {s.status === "ongoing" ? "Em curso" : "Terminada"}{confidence ? ` · ${confidence}` : ""}</Text>
        <OriginBadge origin={s.provenance.origin} kind={s.provenance.kind} demo={session.house?.source_kind === "demo"} />
      </Stack></details>
    </div>
  );
}
