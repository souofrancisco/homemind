import type { components } from "../../shared/api/schema";
import { request } from "../api/client";

export type AgentMessageIn = components["schemas"]["AgentMessageIn"];
export type AgentResponse = components["schemas"]["AgentResponse"];

export const sendAgentMessage = (householdId: string, input: AgentMessageIn) =>
  request<AgentResponse>(
    `/api/households/${encodeURIComponent(householdId)}/agent/messages`,
    { method: "POST", body: JSON.stringify(input) },
  );

// Ações propostas (AGENT-03): só se executam com a confirmação de quem as recebeu.
export type AgentActionView = components["schemas"]["AgentActionView"];

const actionsPath = (householdId: string) =>
  `/api/households/${encodeURIComponent(householdId)}/agent/actions`;
export const listProposedActions = (householdId: string) =>
  request<AgentActionView[]>(`${actionsPath(householdId)}?status=proposed`);
export const confirmAction = (householdId: string, actionId: string) =>
  request<AgentActionView>(`${actionsPath(householdId)}/${encodeURIComponent(actionId)}/confirm`, { method: "POST" });
export const rejectAction = (householdId: string, actionId: string) =>
  request<AgentActionView>(`${actionsPath(householdId)}/${encodeURIComponent(actionId)}/reject`, { method: "POST" });
