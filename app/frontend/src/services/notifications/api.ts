import type { components, paths } from "../../shared/api/schema";
import { api, request } from "../api/client";

export type NotificationView = components["schemas"]["NotificationView"];
export type VotingView = components["schemas"]["VotingView"];
export type NotificationResponseIn = components["schemas"]["NotificationRespondIn"];
export type NotificationPreferences = components["schemas"]["NotificationPreferences"];
export type NotificationPreferencesIn = paths[
  "/api/households/{household_id}/notification-preferences"
]["put"]["requestBody"]["content"]["application/json"];

const householdPath = (householdId: string) =>
  `/api/households/${encodeURIComponent(householdId)}`;

export const listNotifications = (householdId: string) =>
  api<NotificationView[]>(`${householdPath(householdId)}/notifications?limit=50`);

export const markNotificationRead = (householdId: string, notificationId: string) =>
  request<NotificationView>(`${householdPath(householdId)}/notifications/${encodeURIComponent(notificationId)}/read`, {
    method: "POST",
  });

export const respondToNotification = (
  householdId: string,
  notificationId: string,
  input: NotificationResponseIn,
) =>
  request<NotificationView>(`${householdPath(householdId)}/notifications/${encodeURIComponent(notificationId)}/respond`, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const getNotificationPreferences = (householdId: string) =>
  api<NotificationPreferences>(`${householdPath(householdId)}/notification-preferences`);

export const updateNotificationPreferences = (
  householdId: string,
  input: NotificationPreferencesIn,
) =>
  request<NotificationPreferences>(`${householdPath(householdId)}/notification-preferences`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
