import type { components } from "../../shared/api/schema";
import { api } from "../api/client";

export type MeContext = components["schemas"]["MeContext"];
export type Membership = components["schemas"]["MembershipSelfView"];
export type HouseholdView = components["schemas"]["HouseholdView"];
export type RoomView = components["schemas"]["RoomView"];

export const getHouseholdContext = () => api<MeContext>("/api/me/context");
export const getHousehold = (householdId: string) =>
  api<HouseholdView>(`/api/households/${encodeURIComponent(householdId)}`);
export const getRooms = (householdId: string) =>
  api<RoomView[]>(`/api/households/${encodeURIComponent(householdId)}/rooms`);
export type MemberView = components["schemas"]["MemberView"];
export const getMembers = (householdId: string) =>
  api<MemberView[]>(`/api/households/${encodeURIComponent(householdId)}/members`);
