import { Center, Loader } from "@mantine/core";
import type { User } from "oidc-client-ts";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { login, logout, manager, onNativeRedirect } from "../../services/auth/oidc";

type Auth = { user: User | null; login: typeof login; logout: typeof logout };
const Ctx = createContext<Auth | null>(null);

export const useAuth = () => useContext(Ctx)!;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>();

  useEffect(() => {
    const ok = (u: User | null | undefined) => setUser(u && !u.expired ? u : null);
    manager.getUser().then(ok);
    manager.events.addUserLoaded(ok);
    manager.events.addUserUnloaded(() => setUser(null));
    manager.events.addSilentRenewError(() => setUser(null));
    const off = onNativeRedirect(ok);
    return () => {
      off();
      manager.events.removeUserLoaded(ok);
    };
  }, []);

  if (user === undefined) {
    return (
      <Center h="100dvh">
        <Loader />
      </Center>
    );
  }
  return <Ctx.Provider value={{ user, login, logout }}>{children}</Ctx.Provider>;
}
