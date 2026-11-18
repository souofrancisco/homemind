import {
  IconBell, IconBolt, IconBuildingCommunity, IconDeviceDesktopAnalytics,
  IconHome, IconMessageCircle, IconPigMoney, IconGavel, IconPlug, IconReceipt, IconSettings,
} from "@tabler/icons-react";
import type { components } from "../shared/api/schema";

export type AppRole = components["schemas"]["MembershipRole"];
export type SectionId = "home" | "house" | "consumption" | "appliances" | "bills" | "budget" | "houseRules" | "notifications" | "assistant" | "settings" | "diagnostics";
type NavIcon = typeof IconHome;

export type NavPage = {
  path: string;
  label: string;
  section: SectionId;
  icon: NavIcon;
  roles: readonly AppRole[];
  mobile: boolean;
};

// O papel vem exclusivamente de /api/me/context (membership verificada pelo backend).
// Esta filtragem é apenas apresentação: os endpoints mantêm RBAC próprio.
export const navPages: NavPage[] = [
  { path: "/", label: "Início", section: "home", icon: IconHome, roles: ["tenant", "landlord", "operator"], mobile: true },
  { path: "/casa", label: "A minha casa", section: "house", icon: IconBuildingCommunity, roles: ["tenant", "landlord", "operator"], mobile: true },
  { path: "/consumo", label: "Consumo", section: "consumption", icon: IconBolt, roles: ["tenant", "landlord"], mobile: true },
  { path: "/aparelhos", label: "Aparelhos", section: "appliances", icon: IconPlug, roles: ["tenant", "operator"], mobile: false },
  { path: "/contas", label: "Contas e recibos", section: "bills", icon: IconReceipt, roles: ["tenant", "landlord"], mobile: true },
  { path: "/orcamento", label: "Orçamento", section: "budget", icon: IconPigMoney, roles: ["tenant"], mobile: false },
  { path: "/regras", label: "Regras da casa", section: "houseRules", icon: IconGavel, roles: ["tenant"], mobile: false },
  { path: "/notificacoes", label: "Notificações", section: "notifications", icon: IconBell, roles: ["tenant", "landlord"], mobile: false },
  { path: "/assistente", label: "Assistente", section: "assistant", icon: IconMessageCircle, roles: ["tenant"], mobile: false },
  { path: "/diagnostico", label: "Diagnóstico", section: "diagnostics", icon: IconDeviceDesktopAnalytics, roles: ["operator"], mobile: false },
  { path: "/definicoes", label: "Definições", section: "settings", icon: IconSettings, roles: ["tenant", "landlord", "operator"], mobile: false },
];

export const visiblePages = (role: AppRole | null): NavPage[] =>
  role ? navPages.filter((page) => page.roles.includes(role)) : [];

export const canSeePath = (role: AppRole | null, pathname: string): boolean =>
  visiblePages(role).some((page) => page.path === pathname);

export const activeNavPath = (pathname: string): string => pathname;
