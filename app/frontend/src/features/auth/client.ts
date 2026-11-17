import { notifications } from "@mantine/notifications";
import { login, manager } from "./oidc";

// Web: mesmo origin via proxy do Vite (""). Android: URL absoluta do backend (VITE_API_URL).
const base = import.meta.env.VITE_API_URL ?? "";

export async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = {};
  new Headers(init.headers).forEach((value, key) => { headers[key] = value; });
  if (auth) {
    const u = await manager.getUser();
    if (u) headers.Authorization = `Bearer ${u.access_token}`;
  }
  const r = await fetch(base + path, { ...init, headers: { ...headers, ...(init.body ? { "Content-Type": "application/json" } : {}) } });
  if (r.status === 401 && auth) {
    await manager.removeUser();
    await login();
  }
  if (!r.ok) {
    const payload = await r.json().catch(() => null);
    const message = payload?.detail?.message ?? payload?.detail ?? payload?.error?.message ?? `Erro ${r.status}`;
    notifications.show({ color: "red", title: "Pedido falhou", message });
    throw new Error(message);
  }
  if (r.status === 204) return undefined as T;
  return r.json();
}

export const api = <T>(path: string, auth = true) => request<T>(path, {}, auth);
