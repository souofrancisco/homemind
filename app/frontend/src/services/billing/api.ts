import type { components } from "../../shared/api/schema";
import { api } from "../api/client";

export type BillView = components["schemas"]["BillView"];

export const listBills = (householdId: string) =>
  api<BillView[]>(`/api/households/${encodeURIComponent(householdId)}/bills`);
