import type { EventCategory, HomeRule, HomeState, EventLogItem, OffResult, RuleDraft, RuleProposal } from "./types";
import type { HomeService } from "./homeApi";

export type DemoScenario = "book" | "remote" | "mug" | "absence" | "return" | "connection";

let state: HomeState = {
  mode: "leitura", state: "ativo", presence: true, camera_ok: false, mcp_ok: false,
  backend: "fake", waiting_remaining_seconds: null, energy_saved_wh: 126.4,
  energy_saved_eur: 0.038, updated_at: new Date().toISOString(),
};
let online = true;
let events: EventLogItem[] = [
  { id: "evt-1", timestamp: "2026-11-17T20:42:13Z", message: "Modo Leitura ativo", level: "info", source: "fake", category: "mode" },
  { id: "evt-2", timestamp: "2026-11-17T20:42:12Z", message: "Gesto: livro levantado", level: "info", source: "fake", category: "gesture" },
  { id: "evt-3", timestamp: "2026-11-17T20:42:11Z", message: "Livro detetado", level: "info", source: "fake", category: "object" },
  { id: "evt-4", timestamp: "2026-11-17T20:35:00Z", message: "Câmara indisponível.", level: "warning", source: "fake", category: "system" },
];
let rules: HomeRule[] = [
  { id: "leitura", objeto: "livro", nome: "Modo leitura", enabled: true, acoes: [{ dispositivo: "lâmpada", ligada: true, cor: "branco quente", brilho: 40 }] },
  { id: "cinema", objeto: "comando", nome: "Noite de cinema", enabled: true, acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 15 }, { dispositivo: "tomada", ligada: true }] },
  { id: "cafe", objeto: "caneca", nome: "Pausa para café", enabled: true, acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 70 }] },
];
const listeners = new Set<(state: HomeState) => void>();
const eventListeners = new Set<(event: EventLogItem) => void>();
const statusListeners = new Set<(online: boolean) => void>();
let eventSequence = 5;
let proposalSequence = 1;
let waitTimer: ReturnType<typeof setInterval> | undefined;
let recoveryTimer: ReturnType<typeof setTimeout> | undefined;
const publish = () => { state = { ...state, updated_at: new Date().toISOString() }; listeners.forEach((fn) => fn(state)); };
const addEvent = (message: string, level: EventLogItem["level"] = "info", category?: EventCategory) => {
  const event: EventLogItem = { id: `demo-${eventSequence++}`, timestamp: new Date().toISOString(), message, level, source: "fake", category };
  events = [event, ...events].slice(0, 50); eventListeners.forEach((fn) => fn(event));
};

function resetWaitTimer() {
  if (waitTimer) clearInterval(waitTimer);
  waitTimer = setInterval(() => {
    if (state.state !== "em_espera" || state.waiting_remaining_seconds == null) return;
    const remaining = Math.max(0, state.waiting_remaining_seconds - 5);
    state = { ...state, waiting_remaining_seconds: remaining, state: remaining === 0 ? "suspenso" : "em_espera" };
    publish();
    if (remaining === 0) addEvent("Casa suspensa após ausência", "warning", "presence");
    if (state.state === "suspenso") {
      state = { ...state, energy_saved_wh: Number((state.energy_saved_wh + 0.25).toFixed(2)), energy_saved_eur: Number((state.energy_saved_eur + 0.00004).toFixed(4)) };
      publish();
    }
  }, 5000);
}

export const mockService: HomeService = {
  mode: "mock",
  connect(onState, onEvent, onStatus) {
    listeners.add(onState); eventListeners.add(onEvent); statusListeners.add(onStatus);
    onState(state); onStatus(online);
    resetWaitTimer();
    return () => { listeners.delete(onState); eventListeners.delete(onEvent); statusListeners.delete(onStatus); };
  },
  async getEvents() { return events; },
  async getRules() { return rules; },
  async setRuleEnabled(id, enabled) {
    rules = rules.map((rule) => rule.id === id ? { ...rule, enabled } : rule);
    const rule = rules.find((item) => item.id === id);
    if (!rule) throw new Error("Regra não encontrada");
    addEvent(`Regra ${enabled ? "ativada" : "desativada"}: ${rule.nome}`); return rule;
  },
  async deleteRule(id) { const rule = rules.find((item) => item.id === id); rules = rules.filter((item) => item.id !== id); addEvent(`Regra apagada: ${rule?.nome ?? id}`, "warning"); },
  async proposeRule(text): Promise<RuleProposal> {
    const object = /livro|caneca|comando/i.exec(text)?.[0]?.toLowerCase() ?? "livro";
    const name = `Regra para ${object}`;
    return { proposal: { id: `${object}-${proposalSequence++}`, objeto: object, nome: name, acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 50 }] }, summary: `Quando detetar ${object}, ligar a lâmpada com brilho a 50%. Proposta simulada, sem chamada a serviços externos.` };
  },
  async saveRule(rule: RuleDraft) { const saved: HomeRule = { ...rule, enabled: false }; rules = [saved, ...rules]; addEvent(`Nova regra guardada como inativa: ${saved.nome}`); return saved; },
  async turnOff(): Promise<OffResult> {
    state = { ...state, mode: null, state: "inativo", waiting_remaining_seconds: null };
    publish(); addEvent("Pedido para desligar tudo.", "info", "device");
    return { success: true, state: "inativo", backend: "fake", message: "Simulação concluída; nenhum dispositivo físico foi alterado." };
  },
};

export function simulateScenario(scenario: DemoScenario) {
  const activate = (object: string) => {
    const rule = rules.find((item) => item.objeto === object && item.enabled);
    addEvent(`Objeto: ${object}`, "info", "object");
    addEvent(`Gesto: ${object} levantado`, "info", "gesture");
    if (!rule) { addEvent("Não há uma regra para este gesto.", "warning", "rule"); return; }
    state = { ...state, mode: rule.id as HomeState["mode"], state: "ativo", presence: true, waiting_remaining_seconds: null };
    publish();
    addEvent(`Regra escolhida: ${rule.nome}`, "info", "rule");
    addEvent(`Modo ${rule.nome} ativo`, "info", "mode");
    addEvent(`Ação prevista para ${rule.acoes.length} dispositivo(s)`, "info", "device");
  };

  switch (scenario) {
    case "book": activate("livro"); break;
    case "remote": activate("comando"); break;
    case "mug": activate("caneca"); break;
    case "absence":
      state = { ...state, presence: false, state: "em_espera", waiting_remaining_seconds: 10 };
      publish(); addEvent("Ausência detetada. Espera de 10 segundos.", "warning", "presence"); resetWaitTimer(); break;
    case "return":
      state = { ...state, presence: true, state: state.mode ? "ativo" : "inativo", waiting_remaining_seconds: null };
      publish(); addEvent("Presença detetada. Modo anterior mantido.", "info", "presence"); break;
    case "connection":
      online = false; statusListeners.forEach((fn) => fn(false));
      addEvent("Ligação perdida.", "error", "system");
      if (recoveryTimer) clearTimeout(recoveryTimer);
      recoveryTimer = setTimeout(() => { online = true; statusListeners.forEach((fn) => fn(true)); addEvent("Ligação restabelecida.", "info", "system"); }, 4000);
      break;
  }
}
