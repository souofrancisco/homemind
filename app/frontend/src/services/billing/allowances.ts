import type { components } from "../../shared/api/schema";
import { api, request } from "../api/client";

// Plafond solidário por quarto (BILL-03): editar só vale a partir do mês seguinte.
export type RoomAllowanceView = components["schemas"]["RoomAllowanceView"];

const path = (householdId: string) => `/api/households/${encodeURIComponent(householdId)}/room-allowances`;
export const listRoomAllowances = (householdId: string) => api<RoomAllowanceView[]>(path(householdId));
export const setRoomAllowance = (householdId: string, roomId: string, includedWh: number) =>
  request<RoomAllowanceView>(`${path(householdId)}/${encodeURIComponent(roomId)}`, {
    method: "PUT", body: JSON.stringify({ included_wh: includedWh }),
  });
