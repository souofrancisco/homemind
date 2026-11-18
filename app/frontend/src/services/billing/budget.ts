import type { components } from "../../shared/api/schema";
import { api, request } from "../api/client";

export type BudgetStatus = components["schemas"]["BudgetStatus"];
export type BudgetIn = components["schemas"]["BudgetIn"];

const path = (householdId: string) => `/api/households/${encodeURIComponent(householdId)}/budgets/me`;
export const getMyBudget = (householdId: string) => api<BudgetStatus>(path(householdId));
export const setMyBudget = (householdId: string, body: BudgetIn) =>
  request<BudgetStatus>(path(householdId), { method: "PUT", body: JSON.stringify(body) });
