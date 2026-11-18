import type { components } from "../../shared/api/schema";
import { api, request } from "../api/client";

export type HouseRulesView = components["schemas"]["HouseRulesView"];
export type HouseRulesIn = components["schemas"]["HouseRulesIn"];

const path = (householdId: string) => `/api/households/${encodeURIComponent(householdId)}/rules`;
export const getHouseRules = (householdId: string) => api<HouseRulesView>(path(householdId));
// HOUSE-04: propor (conta como «sim»), votar e retirar; só a maioria agenda a mudança.
export const proposeHouseRules = (householdId: string, body: HouseRulesIn) =>
  request<HouseRulesView>(`${path(householdId)}/next`, { method: "PUT", body: JSON.stringify(body) });
export const voteHouseRules = (householdId: string, approve: boolean) =>
  request<HouseRulesView>(`${path(householdId)}/next/vote`, { method: "POST", body: JSON.stringify({ approve }) });
export const withdrawHouseRules = (householdId: string) =>
  request<HouseRulesView>(`${path(householdId)}/next`, { method: "DELETE" });
