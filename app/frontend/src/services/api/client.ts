import { notifications } from "@mantine/notifications";
import { login, manager } from "../auth/oidc";

// Web: mesmo origin via proxy do Vite (""). Android: URL absoluta do backend (VITE_API_URL).
const base = import.meta.env.VITE_API_URL ?? "";

/** Access token válido (renova em silêncio se expirou); null = sem sessão utilizável. */
export async function accessToken(): Promise<string | null> {
  let user = await manager.getUser();
  if (user?.expired) user = await manager.signinSilent().catch(() => null);
  return user && !user.expired ? user.access_token : null;
}

export async function expireSession(): Promise<void> {
  await manager.removeUser();
  await login();
}

export async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = {};
  new Headers(init.headers).forEach((value, key) => { headers[key] = value; });
  if (auth) {
    const token = await accessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const r = await fetch(base + path, { ...init, headers: { ...headers, ...(init.body ? { "Content-Type": "application/json" } : {}) } });
  if (r.status === 401 && auth) await expireSession();
  if (!r.ok) {
    const payload = await r.json().catch(() => null);
    const message = payload?.detail?.message ?? payload?.detail ?? payload?.error?.message ?? `Erro ${r.status}`;
    notifications.clean();
    notifications.show({ color: "red", title: "Pedido falhou", message, autoClose: 6000, withCloseButton: true });
    throw new Error(message);
  }
  if (r.status === 204) return undefined as T;
  return r.json();
}

export const apiBase = base;
export const api = <T>(path: string, auth = true) => request<T>(path, {}, auth);
