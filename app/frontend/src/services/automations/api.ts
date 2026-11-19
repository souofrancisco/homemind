import type { components } from "../../shared/api/schema";
import { request } from "../api/client";

export type AutomationView = components["schemas"]["AutomationView"];
export type AutomationPlugView = components["schemas"]["AutomationPlugView"];
export type AutomationProposeIn = components["schemas"]["AutomationProposeIn"];

const base = (householdId: string) => `/api/households/${encodeURIComponent(householdId)}/automations`;

export const listAutomations = (householdId: string) => request<AutomationView[]>(base(householdId));
export const listAutomationPlugs = (householdId: string) => request<AutomationPlugView[]>(`${base(householdId)}/plugs`);
export const proposeAutomation = (householdId: string, body: AutomationProposeIn) =>
  request<AutomationView>(base(householdId), { method: "POST", body: JSON.stringify(body) });
export const voteAutomation = (householdId: string, id: string, approve: boolean) =>
  request<AutomationView>(`${base(householdId)}/${encodeURIComponent(id)}/vote`, { method: "POST", body: JSON.stringify({ approve }) });
export const suspendAutomation = (householdId: string, id: string) =>
  request<AutomationView>(`${base(householdId)}/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ status: "disabled" }) });
export const reactivateAutomation = (householdId: string, id: string) =>
  request<AutomationView>(`${base(householdId)}/${encodeURIComponent(id)}/reactivate`, { method: "POST" });
