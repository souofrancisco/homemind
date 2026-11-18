import type { components } from "../../shared/api/schema";
import { api, request } from "../api/client";

export type HouseRulesView = components["schemas"]["HouseRulesView"];
export type HouseRulesIn = components["schemas"]["HouseRulesIn"];

const path = (householdId: string) => `/api/households/${encodeURIComponent(householdId)}/rules`;
export const getHouseRules = (householdId: string) => api<HouseRulesView>(path(householdId));
export const scheduleHouseRules = (householdId: string, body: HouseRulesIn) =>
  request<HouseRulesView>(`${path(householdId)}/next`, { method: "PUT", body: JSON.stringify(body) });
export const cancelHouseRules = (householdId: string) =>
  request<HouseRulesView>(`${path(householdId)}/next`, { method: "DELETE" });
