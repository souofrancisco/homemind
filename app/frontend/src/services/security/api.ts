import type { components } from "../../shared/api/schema";
import { api, request } from "../api/client";

export type SecurityView = components["schemas"]["SecurityView"];
export type SecurityKind = components["schemas"]["SecurityActionKind"];

const base = (householdId: string) => `/api/households/${encodeURIComponent(householdId)}/security`;

/** Painel de segurança SIMULADO. O servidor recusa o senhorio e o operador (403). */
export const getSecurity = (householdId: string) => api<SecurityView>(base(householdId));
export const proposeSecurity = (householdId: string, kind: SecurityKind) =>
  request<SecurityView>(`${base(householdId)}/proposals`, { method: "POST", body: JSON.stringify({ kind }) });
export const confirmSecurity = (householdId: string, id: string) =>
  request<SecurityView>(`${base(householdId)}/proposals/${encodeURIComponent(id)}/confirm`, { method: "POST" });
export const cancelSecurity = (householdId: string, id: string) =>
  request<SecurityView>(`${base(householdId)}/proposals/${encodeURIComponent(id)}/cancel`, { method: "POST" });
