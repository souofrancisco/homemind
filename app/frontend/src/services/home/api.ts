import type { EventLogItem, HomeRule, HomeService, HomeState, OffResult, RuleProposal } from "../../types/home";
import { api, request } from "../api/client";

export const apiService: HomeService = {
  mode: "api",
  connect(onState, onEvent, onStatus) {
    let closed = false;
    let socket: WebSocket | undefined;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout>;
    const open = () => {
      if (closed) return;
      const base = import.meta.env.VITE_API_URL ?? window.location.origin;
      const url = new URL("/ws", base);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(url);
      socket.onopen = () => { retry = 0; onStatus(true); };
      socket.onmessage = (message) => {
        try {
          const envelope = JSON.parse(message.data) as { type?: string; data?: unknown };
          if (envelope.type === "home_state") onState(envelope.data as HomeState);
          if (envelope.type === "event") onEvent(envelope.data as EventLogItem);
        } catch { /* Mensagem inválida: manter o último snapshot. */ }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        onStatus(false);
        if (!closed) timer = setTimeout(open, Math.min(1000 * 2 ** retry++, 15000));
      };
    };
    open();
    return () => { closed = true; clearTimeout(timer); socket?.close(); };
  },
  getEvents: async () => (await api<{ events: EventLogItem[] }>("/events?limit=50")).events,
  getRules: async () => (await api<{ rules: HomeRule[] }>("/rules")).rules,
  setRuleEnabled: (id, enabled) => request<HomeRule>(`/rules/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
  deleteRule: (id) => request<void>(`/rules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  proposeRule: (text) => request<RuleProposal>("/rules/parse", { method: "POST", body: JSON.stringify({ text }) }),
  saveRule: (rule) => request<HomeRule>("/rules", { method: "POST", body: JSON.stringify({ ...rule, enabled: false }) }),
  turnOff: () => request<OffResult>("/off", { method: "POST", body: JSON.stringify({}) }),
};
