import type { EventLogItem, HomeRule, HomeService, HomeState, OffResult, RuleProposal, ScenarioId } from "../../types/home";
import { accessToken, api, apiBase, expireSession, request } from "../api/client";
import { manager } from "../auth/oidc";

type Message = { type?: string; data?: unknown };

const scenarioEvents: Record<ScenarioId, (hora: string) => object> = {
  book: (hora) => ({ tipo: "objeto_levantado", classe: "livro", hora }),
  remote: (hora) => ({ tipo: "objeto_levantado", classe: "comando", hora }),
  mug: (hora) => ({ tipo: "objeto_levantado", classe: "caneca", hora }),
  absence: (hora) => ({ tipo: "presenca", ha_alguem: false, hora }),
  return: (hora) => ({ tipo: "presenca", ha_alguem: true, hora }),
};

export const apiService: HomeService = {
  mode: "api",
  connect(onState, onEvent, onStatus) {
    let closed = false;
    let socket: WebSocket | undefined;
    let retry = 0;
    let denied = 0;
    let timer: ReturnType<typeof setTimeout>;
    const url = new URL("/api/ws", apiBase || window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

    const schedule = (delay: number) => { if (!closed) timer = setTimeout(open, delay); };
    // Token recusado: tenta renovar uma vez em silêncio; se falhar, volta ao login (sem insistir com token morto).
    const onDenied = async () => {
      if (denied++ >= 1 || !(await manager.signinSilent().then(() => true, () => false))) return void expireSession();
      schedule(0);
    };

    function open() {
      if (closed) return;
      const ws = socket = new WebSocket(url);
      let rejected = false;
      // O token vai na 1.ª mensagem, nunca no URL.
      ws.onopen = async () => {
        const token = await accessToken();
        if (!token) { rejected = true; ws.close(); return void expireSession(); }
        ws.send(JSON.stringify({ type: "auth", token }));
      };
      ws.onmessage = (message) => {
        try {
          const envelope = JSON.parse(message.data) as Message;
          if (envelope.type === "home_state") { retry = 0; denied = 0; onStatus(true); onState(envelope.data as HomeState); }
          else if (envelope.type === "event") onEvent(envelope.data as EventLogItem);
          else if (envelope.type === "error" && (envelope.data as { code?: string })?.code === "unauthorized") rejected = true;
        } catch { /* Mensagem inválida: manter o último snapshot. */ }
      };
      ws.onerror = () => ws.close();
      ws.onclose = (close) => {
        onStatus(false);
        if (closed || ws !== socket) return;
        if (rejected || close.code === 1008) void onDenied();
        else schedule(Math.min(1000 * 2 ** retry++, 15000));
      };
    }
    open();
    return () => { closed = true; clearTimeout(timer); socket?.close(); };
  },
  getState: () => api<HomeState>("/api/state"),
  getEvents: async () => (await api<{ events: EventLogItem[] }>("/api/events?limit=50")).events,
  simulate: async (scenario) => { await request<HomeState>("/api/simulate", { method: "POST", body: JSON.stringify(scenarioEvents[scenario](new Date().toISOString())) }); },
  getRules: async () => (await api<{ rules: HomeRule[] }>("/api/rules")).rules,
  setRuleEnabled: (id, enabled) => request<HomeRule>(`/api/rules/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
  deleteRule: (id) => request<void>(`/api/rules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  proposeRule: (text) => request<RuleProposal>("/api/rules/parse", { method: "POST", body: JSON.stringify({ text }) }),
  saveRule: (rule) => request<HomeRule>("/api/rules", { method: "POST", body: JSON.stringify({ ...rule, enabled: false }) }),
  turnOff: () => request<OffResult>("/api/off", { method: "POST" }),
};
