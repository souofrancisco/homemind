import { SecureStorage } from "@aparajita/capacitor-secure-storage";
import { App } from "@capacitor/app";
import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";

export const isNative = Capacitor.isNativePlatform();
const NATIVE_REDIRECT = "pt.homemind.app://auth/callback";
const NATIVE_LOGOUT = "pt.homemind.app://auth/logout";

// Android: tokens no Keystore (SecureStorage). O oidc-client-ts precisa de um Storage síncrono,
// por isso mantemos um mapa em memória, hidratado no arranque e gravado a cada alteração.
async function secureStore(): Promise<Storage> {
  const KEY = "oidc";
  const raw = (await SecureStorage.get(KEY)) as string | null;
  const map: Record<string, string> = raw ? JSON.parse(raw) : {};
  const save = () => void SecureStorage.set(KEY, JSON.stringify(map));
  return {
    get length() {
      return Object.keys(map).length;
    },
    key: (i) => Object.keys(map)[i] ?? null,
    getItem: (k) => map[k] ?? null,
    setItem: (k, v) => {
      map[k] = v;
      save();
    },
    removeItem: (k) => {
      delete map[k];
      save();
    },
    clear: () => {
      for (const k of Object.keys(map)) delete map[k];
      save();
    },
  };
}

const store = isNative ? await secureStore() : window.sessionStorage;

// `_client` é protegido; precisamos dos URLs de login/logout para abrir no navegador do sistema.
class Manager extends UserManager {
  readonly client = this._client;
}

export const manager = new Manager({
  authority: import.meta.env.VITE_OIDC_AUTHORITY ?? "http://localhost:9000/application/o/homemind/",
  client_id: "homemind",
  redirect_uri: isNative ? NATIVE_REDIRECT : `${window.location.origin}/auth/callback`,
  post_logout_redirect_uri: isNative ? NATIVE_LOGOUT : `${window.location.origin}/`,
  response_type: "code", // Authorization Code + PKCE (S256) por defeito, sem client secret
  scope: "openid profile email offline_access",
  automaticSilentRenew: true,
  userStore: new WebStorageStateStore({ store }),
  stateStore: new WebStorageStateStore({ store }),
});

export async function login(): Promise<void> {
  // state = rota pedida, para regressar a ela após o login (web).
  if (!isNative) return manager.signinRedirect({ state: window.location.pathname + window.location.search });
  // Navegador do sistema (Custom Tab), nunca WebView embebida.
  await Browser.open({ url: (await manager.client.createSigninRequest({ request_type: "si:r" })).url });
}

// Web: o signoutRedirect remove o utilizador antes de navegar para o Authentik; sem esta marca,
// a rota protegida via «sem utilizador» e abria um novo login que abortava o end-session.
let leaving = false;
export const isLeaving = () => leaving;

export async function logout(): Promise<void> {
  if (!isNative) {
    leaving = true;
    return manager.signoutRedirect().catch((e) => {
      leaving = false;
      throw e;
    });
  }
  const idToken = (await manager.getUser())?.id_token;
  const { url } = await manager.client.createSignoutRequest({ id_token_hint: idToken, request_type: "so:r" });
  // O utilizador só é removido quando o Authentik devolve a app (deep link de logout).
  await Browser.open({ url });
}

// O código só pode ser trocado uma vez (StrictMode corre os efeitos duas vezes).
let pending: Promise<User | undefined> | undefined;
export function completeLogin(url?: string): Promise<User | undefined> {
  return (pending ??= manager.signinCallback(url).finally(() => (pending = undefined)));
}

// Android: o Authentik devolve a app por deep link (esquema pt.homemind.app://).
export function onNativeRedirect(done: (u: User | undefined) => void): () => void {
  if (!isNative) return () => {};
  const sub = App.addListener("appUrlOpen", async ({ url }) => {
    if (!url.startsWith("pt.homemind.app://")) return;
    await Browser.close().catch(() => {});
    if (url.startsWith(NATIVE_REDIRECT)) done(await completeLogin(url));
    else {
      // shortcut: Browser.close() é no-op no Android e o Custom Tab ainda está a fechar; sem esta
      // pausa o Browser.open() do novo login é engolido. Trocar por evento browserFinished se falhar.
      await new Promise((r) => setTimeout(r, 1000));
      await manager.removeUser();
    }
  });
  return () => void sub.then((h) => h.remove());
}
