import type { components } from "../../shared/api/schema";
import { api } from "../api/client";

export type HouseOccupancy = components["schemas"]["HouseOccupancy"];

/** Ocupação agregada da casa (só números). O servidor recusa o senhorio e o operador (403). */
export const getOccupancy = (householdId: string) =>
  api<HouseOccupancy>(`/api/presence/occupancy?household_id=${encodeURIComponent(householdId)}`);
