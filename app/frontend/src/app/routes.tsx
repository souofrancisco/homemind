import {
  IconBuildingCommunity, IconDeviceDesktopAnalytics, IconHome,
  IconMessageCircle, IconReceipt,
} from "@tabler/icons-react";
import type { components } from "../shared/api/schema";

export type AppRole = components["schemas"]["MembershipRole"];
export type SectionId = "home" | "house" | "bills" | "budget" | "houseRules" | "notifications" | "assistant" | "diagnostics" | "settings";
type NavIcon = typeof IconHome;
export type NavPage = {
  path: string; label: string; section: SectionId; icon: NavIcon;
  roles: readonly AppRole[]; mobile: boolean;
};

// A filtragem é apenas de apresentação; o backend continua a aplicar o RBAC.
export const navPages: NavPage[] = [
  { path: "/", label: "Hoje", section: "home", icon: IconHome, roles: ["tenant", "landlord"], mobile: true },
  { path: "/contas", label: "Contas", section: "bills", icon: IconReceipt, roles: ["tenant", "landlord"], mobile: true },
  { path: "/casa", label: "Casa", section: "house", icon: IconBuildingCommunity, roles: ["tenant", "landlord", "operator"], mobile: true },
  { path: "/assistente", label: "Assistente", section: "assistant", icon: IconMessageCircle, roles: ["tenant"], mobile: true },
  { path: "/diagnostico", label: "Diagnóstico", section: "diagnostics", icon: IconDeviceDesktopAnalytics, roles: ["operator"], mobile: true },
];

export const visiblePages = (role: AppRole | null): NavPage[] =>
  role ? navPages.filter((page) => page.roles.includes(role)) : [];

const hiddenRoutes: Record<string, readonly AppRole[]> = {
  "/notificacoes": ["tenant", "landlord"],
  "/definicoes": ["tenant", "landlord", "operator"],
  "/regras": ["tenant"],
};

export const canSeePath = (role: AppRole | null, pathname: string): boolean => {
  if (!role) return false;
  if (visiblePages(role).some((page) => page.path === pathname)) return true;
  return hiddenRoutes[pathname]?.includes(role) ?? false;
};

export const activeNavPath = (pathname: string): string => {
  if (pathname === "/orcamento") return "/contas";
  if (pathname === "/regras") return "/casa";
  if (pathname === "/aparelhos" || pathname === "/consumo") return pathname === "/consumo" ? "/" : "/casa";
  return pathname;
};
