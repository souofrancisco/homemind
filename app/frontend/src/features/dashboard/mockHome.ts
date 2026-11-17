import type { HomeRule, HomeState, EventLogItem, OffResult, RuleDraft, RuleProposal } from "./types";
import type { HomeService } from "./homeApi";

let state: HomeState = {
  mode: "leitura", state: "ativo", presence: true, camera_ok: false, mcp_ok: false,
  backend: "fake", waiting_remaining_seconds: null, energy_saved_wh: 126.4,
  energy_saved_eur: 0.038, updated_at: new Date().toISOString(),
};
let events: EventLogItem[] = [
  ["Modo leitura ativado", "info"], ["Presença detetada na sala", "info"],
  ["Câmara indisponível — processamento local preservado", "warning"], ["Poupança estimada atualizada", "info"],
].map(([message, level], i) => ({ id: `evt-${i}`, timestamp: new Date(Date.now() - i * 60000).toISOString(), message: message!, level: level as EventLogItem["level"], source: "fake" }));
let rules: HomeRule[] = [
  { id: "leitura", objeto: "livro", nome: "Modo leitura", enabled: true, acoes: [{ dispositivo: "lâmpada", ligada: true, cor: "branco quente", brilho: 40 }] },
  { id: "cinema", objeto: "comando", nome: "Noite de cinema", enabled: true, acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 15 }, { dispositivo: "tomada", ligada: true }] },
  { id: "cafe", objeto: "caneca", nome: "Pausa para café", enabled: false, acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 70 }] },
];
const listeners = new Set<(state: HomeState) => void>();
const eventListeners = new Set<(event: EventLogItem) => void>();
const publish = () => { state = { ...state, updated_at: new Date().toISOString() }; listeners.forEach((fn) => fn(state)); };
const addEvent = (message: string, level: EventLogItem["level"] = "info") => {
  const event: EventLogItem = { id: crypto.randomUUID(), timestamp: new Date().toISOString(), message, level, source: "fake" };
  events = [event, ...events].slice(0, 50); eventListeners.forEach((fn) => fn(event));
};

export const mockService: HomeService = {
  mode: "mock",
  connect(onState, onEvent, onStatus) {
    listeners.add(onState); eventListeners.add(onEvent); onState(state); onStatus(true);
    const interval = setInterval(() => {
      const remaining = state.waiting_remaining_seconds;
      const suspended = remaining !== null && remaining <= 8;
      state = {
        ...state,
        energy_saved_wh: Number((state.energy_saved_wh + 0.4).toFixed(1)),
        energy_saved_eur: Number((state.energy_saved_eur + 0.0001).toFixed(4)),
        waiting_remaining_seconds: remaining === null ? null : Math.max(0, remaining - 8),
        state: suspended ? "suspenso" : state.state,
      };
      publish();
      if (suspended) addEvent("Casa suspensa após ausência", "warning");
      if (Math.random() > 0.72) addEvent("Poupança estimada atualizada");
    }, 8000);
    return () => { clearInterval(interval); listeners.delete(onState); eventListeners.delete(onEvent); };
  },
  async getEvents() { return events; },
  async getRules() { return rules; },
  async setRuleEnabled(id, enabled) { rules = rules.map((r) => r.id === id ? { ...r, enabled } : r); const rule = rules.find((r) => r.id === id)!; addEvent(`Regra ${enabled ? "ativada" : "desativada"}: ${rule.nome}`); return rule; },
  async deleteRule(id) { const rule = rules.find((r) => r.id === id); rules = rules.filter((r) => r.id !== id); addEvent(`Regra apagada: ${rule?.nome ?? id}`, "warning"); },
  async proposeRule(text): Promise<RuleProposal> {
    const object = /livro|caneca|comando/i.exec(text)?.[0]?.toLowerCase() ?? "livro";
    const name = `Regra para ${object}`;
    return { proposal: { id: `${object}-${Date.now()}`, objeto: object, nome: name, acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 50 }] }, summary: `Quando detetar ${object}, ligar a lâmpada com brilho a 50%.` };
  },
  async saveRule(rule: RuleDraft) { const saved: HomeRule = { ...rule, enabled: true }; rules = [saved, ...rules]; addEvent(`Nova regra guardada: ${saved.nome}`); return saved; },
  async turnOff(): Promise<OffResult> {
    if (Math.random() < 0.16) { addEvent("Desligar tudo: falha parcial simulada", "error"); return { success: false, state: state.state, backend: "fake", message: "Não foi possível confirmar o estado de todos os dispositivos." }; }
    state = { ...state, mode: null, state: "inativo", waiting_remaining_seconds: null };
    publish(); addEvent("Desligar tudo concluído (simulação)");
    return { success: true, state: "inativo", backend: "fake", message: "Simulação concluída; nenhum dispositivo físico foi alterado." };
  },
};

export function simulatePresence(present: boolean) {
  state = { ...state, presence: present, state: present ? (state.mode ? "ativo" : "inativo") : "em_espera", waiting_remaining_seconds: present ? null : 24 };
  publish(); addEvent(present ? "Presença detetada" : "Ausência detetada", present ? "info" : "warning");
}
export function simulateObject(object: string) {
  const rule = rules.find((r) => r.objeto === object && r.enabled);
  if (!rule) { addEvent(`Objeto detetado: ${object} (sem regra ativa)`); return; }
  state = { ...state, mode: rule.id as HomeState["mode"], state: "ativo", presence: true, waiting_remaining_seconds: null };
  publish(); addEvent(`Modo ${rule.nome} ativado por ${object}`);
}
