import type { EventCategory, EventGroup, EventLogItem } from "../types/home";
import { formatDay } from "./format";

export const eventCategories: { value: EventCategory; label: string }[] = [
  { value: "presence", label: "Presença" }, { value: "object", label: "Objeto" }, { value: "gesture", label: "Gesto" },
  { value: "mode", label: "Modo" }, { value: "rule", label: "Regra" }, { value: "device", label: "Dispositivo" },
  { value: "energy", label: "Energia" }, { value: "system", label: "Outros" },
];
export const categoryLabels = Object.fromEntries(eventCategories.map(({ value, label }) => [value, label])) as Record<EventCategory, string>;
export const eventLevels = [{ value: "info", label: "Informação" }, { value: "warning", label: "Aviso" }, { value: "error", label: "Erro" }];
export const eventPeriods = [{ value: "24h", label: "Últimas 24 horas" }, { value: "7d", label: "Últimos 7 dias" }, { value: "all", label: "Todos os eventos carregados" }];
export const resultLabels: Record<NonNullable<EventLogItem["result"]>, string> = { verified: "Confirmado", failed: "Falhou", unverified: "Sem confirmação", unsupported: "Não disponível" };

export const categoryOf = (event: EventLogItem): EventCategory => event.category ?? "system";
export const eventTime = (event: EventLogItem) => Date.parse(event.timestamp);

export function resultColor(result: NonNullable<EventLogItem["result"]>) {
  if (result === "verified") return "teal";
  if (result === "failed") return "red";
  if (result === "unsupported") return "gray";
  return "yellow";
}

export function eventGroups(items: EventLogItem[]): EventGroup[] {
  const groups = new Map<string, EventLogItem[]>();
  for (const event of items) {
    const key = event.correlation_id ? `operation:${event.correlation_id}` : `event:${event.id}`;
    const group = groups.get(key);
    if (group) group.push(event);
    else groups.set(key, [event]);
  }
  return [...groups.values()].map((events) => ({
    events: [...events].sort((a, b) => eventTime(a) - eventTime(b)),
    newest: Math.max(...events.map(eventTime).filter(Number.isFinite)),
  })).sort((a, b) => b.newest - a.newest);
}

export function dateGroups(groups: EventGroup[]) {
  const byDate = new Map<string, EventGroup[]>();
  for (const group of groups) {
    const key = Number.isFinite(group.newest) ? formatDay(group.newest) : "Data desconhecida";
    byDate.set(key, [...(byDate.get(key) ?? []), group]);
  }
  return [...byDate].map(([label, groups]) => ({ label, groups }));
}

export function filterSummary(search: string, category: string | null, level: string | null, period: string | null) {
  const active = [search.trim() ? `pesquisa “${search.trim()}”` : "", category ? categoryLabels[category as EventCategory] : "", level ? eventLevels.find((item) => item.value === level)?.label : "", period && period !== "all" ? eventPeriods.find((item) => item.value === period)?.label : ""].filter(Boolean);
  return active.length ? ` (${active.join(", ")})` : "";
}
