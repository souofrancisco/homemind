import { notifications } from "@mantine/notifications";
import { login, manager } from "../auth/oidc";

// Web: mesmo origin via proxy do Vite (""). Android: URL absoluta do backend (VITE_API_URL).
const base = import.meta.env.VITE_API_URL ?? "";

export async function api<T>(path: string, auth = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (auth) {
    const u = await manager.getUser();
    if (u) headers.Authorization = `Bearer ${u.access_token}`;
  }
  const r = await fetch(base + path, { headers });
  if (r.status === 401 && auth) {
    await manager.removeUser();
    await login();
  }
  if (!r.ok) {
    const message = (await r.json().catch(() => null))?.error?.message ?? `Erro ${r.status}`;
    notifications.show({ color: "red", title: "Pedido falhou", message });
    throw new Error(message);
  }
  return r.json();
}
