import type { components } from "../../shared/api/schema";
import { request } from "../api/client";

export type PresenceConsents = components["schemas"]["PresenceConsentsView"];
export type SourceConsent = components["schemas"]["PresenceSourceConsentView"];
export type ConsentSource = components["schemas"]["ConsentSource"];
export type ConsentLogEntry = components["schemas"]["PresenceConsentLogView"];
export type SourceRevocation = components["schemas"]["PresenceSourceRevocationView"];
export type PresenceExport = components["schemas"]["PresenceExport"];

const q = (householdId: string) => `?household_id=${encodeURIComponent(householdId)}`;

/** O MEU consentimento por fonte. O servidor recusa o senhorio e o operador (403). */
export const getConsents = (householdId: string) => request<PresenceConsents>(`/api/presence/consents${q(householdId)}`);
export const grantConsent = (householdId: string, source: ConsentSource, textVersion: string) =>
  request<PresenceConsents>(`/api/presence/consents/${source}${q(householdId)}`, { method: "POST", body: JSON.stringify({ text_version: textVersion }) });
export const revokeConsent = (householdId: string, source: ConsentSource) =>
  request<SourceRevocation>(`/api/presence/consents/${source}${q(householdId)}`, { method: "DELETE" });
export const exportMyPresence = (householdId: string) => request<PresenceExport>(`/api/presence/export${q(householdId)}`);

/** Opt-in global de presença (a rota é do módulo das casas). Desligar apaga todos os dados de presença do próprio. */
export const setPresenceOptIn = (householdId: string, membershipId: string, value: boolean) =>
  request(`/api/households/${encodeURIComponent(householdId)}/memberships/${encodeURIComponent(membershipId)}`, { method: "PATCH", body: JSON.stringify({ presence_opt_in: value }) });
