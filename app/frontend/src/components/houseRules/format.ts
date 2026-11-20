import type { AutomationView } from "../../services/automations/api";

export const originLabel = (o: AutomationView["origin"]) => (o === "simulated" ? "SIMULADO" : "REAL");

/** Gatilho em português simples; `name` resolve o id da tomada medida. */
export function describeTrigger(t: AutomationView["trigger"], name: (id: string | null | undefined) => string): string {
  if (t.kind === "presence_changed") return "Quando alguém entra ou sai de casa (a presença muda)";
  const min = Math.round((t.duration_s ?? 0) / 60);
  const span = (t.duration_s ?? 0) < 60 ? `${t.duration_s ?? 0} s` : `${min} min`;
  return `Quando ${name(t.device_id)} consumir mais de ${t.threshold_w} W durante ${span}`;
}
