import type { components } from "../../shared/api/schema";
import { api, request } from "../api/client";

type Schemas = components["schemas"];
export type BillView = Schemas["BillView"];
export type BillIn = Schemas["BillIn"];
export type BillPreview = Schemas["BillPreview"];
export type BillAllocation = Schemas["BillAllocation"];
export type LandlordBillView = Schemas["LandlordBillView"];
export type ReceiptExplanation = Schemas["ReceiptExplanation"];

const base = (householdId: string) => `/api/households/${encodeURIComponent(householdId)}`;
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const listBills = (householdId: string) => api<BillView[]>(`${base(householdId)}/bills`);
export const previewBill = (householdId: string, body: BillIn) => post<BillPreview>(`${base(householdId)}/bills/preview`, body);
export const createBill = (householdId: string, body: BillIn) => post<BillView>(`${base(householdId)}/bills`, body);
export const finalizeBill = (householdId: string, billId: string) => post<BillView>(`${base(householdId)}/bills/${billId}/finalize`);
export const getMyReceipt = (householdId: string, billId: string) => api<BillAllocation>(`${base(householdId)}/bills/${billId}/receipt`);
export const getBillSummary = (householdId: string, billId: string) => api<LandlordBillView>(`${base(householdId)}/bills/${billId}/summary`);
export const getMyReceiptExplanation = (householdId: string, billId: string) =>
  api<ReceiptExplanation>(`${base(householdId)}/bills/${billId}/receipt/explanation`);

// BILL-06: contestar (inquilino) e decidir (senhorio).
export type Contestation = Schemas["Contestation"];
export type ContestationIn = Schemas["ContestationIn"];
export type ContestationDecisionIn = Schemas["ContestationDecisionIn"];
export type LandlordContestationView = Schemas["LandlordContestationView"];
export const contestBill = (householdId: string, billId: string, body: ContestationIn) =>
  post<Contestation>(`${base(householdId)}/bills/${billId}/contestations`, body);
export const listMyContestations = (householdId: string) => api<Contestation[]>(`${base(householdId)}/contestations/mine`);
export const listContestations = (householdId: string) => api<LandlordContestationView[]>(`${base(householdId)}/contestations`);
export const decideContestation = (householdId: string, contestationId: string, body: ContestationDecisionIn) =>
  post<LandlordContestationView>(`${base(householdId)}/contestations/${contestationId}/decision`, body);

// Plafond solidário por quarto (BILL-03): editar só vale a partir do mês seguinte.
export type RoomAllowanceView = Schemas["RoomAllowanceView"];
export const listRoomAllowances = (householdId: string) =>
  api<RoomAllowanceView[]>(`${base(householdId)}/room-allowances`);
export const setRoomAllowance = (householdId: string, roomId: string, includedWh: number) =>
  request<RoomAllowanceView>(`${base(householdId)}/room-allowances/${encodeURIComponent(roomId)}`, {
    method: "PUT", body: JSON.stringify({ included_wh: includedWh }),
  });
