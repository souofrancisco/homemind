import type { components } from "../../shared/api/schema";
import { api } from "../api/client";

export type ApplianceView = components["schemas"]["ApplianceView"];

export const listAppliances = (householdId: string) =>
  api<ApplianceView[]>(`/api/households/${encodeURIComponent(householdId)}/appliances`);
