import type { components } from "../../shared/api/schema";
import { api } from "../api/client";

export type EnergyOverview = components["schemas"]["EnergyOverview"];
export type ConsumptionSession = components["schemas"]["ConsumptionSessionView"];
export type MeterReading = components["schemas"]["MeterReadingView"];

export const getEnergyOverview = (householdId: string) =>
  api<EnergyOverview>(`/api/households/${encodeURIComponent(householdId)}/energy/overview`);
