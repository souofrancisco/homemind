import type { components } from "../../shared/api/schema";
import { api, request } from "../api/client";

type Schemas = components["schemas"];
export type BillView = Schemas["BillView"];
export type BillIn = Schemas["BillIn"];
export type BillPreview = Schemas["BillPreview"];
export type BillAllocation = Schemas["BillAllocation"];
export type LandlordBillView = Schemas["LandlordBillView"];
export type ReceiptExplanation = Schemas["ReceiptExplanation"];
export type TariffIn = Schemas["TariffIn"];
export type TariffStatus = Schemas["TariffStatus"];

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

// Correção de uma fatura fechada (BILL-04): nova revisão; a anterior fica `superseded`.
export const reviseBill = (householdId: string, billId: string, body: BillIn) =>
  post<BillView>(`${base(householdId)}/bills/${encodeURIComponent(billId)}/revisions`, body);
// Tarifa de referência para estimativas (ALERT-02); nunca muda faturas fechadas.
export const getTariff = (householdId: string) => api<TariffStatus>(`${base(householdId)}/tariff`);
export const setTariff = (householdId: string, body: TariffIn) =>
  request<TariffStatus>(`${base(householdId)}/tariff`, { method: "PUT", body: JSON.stringify(body) });
