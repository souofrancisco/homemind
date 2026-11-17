import { IconAutomation, IconCamera, IconHome, IconTimeline, IconUser } from "@tabler/icons-react";
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

const HomePage = lazy(() => import("../pages/HomePage"));
const CameraPage = lazy(() => import("../pages/CameraPage"));
const EventsPage = lazy(() => import("../pages/EventsPage"));
const AutomationsPage = lazy(() => import("../pages/AutomationsPage"));
const AutomationDetailsPage = lazy(() => import("../pages/AutomationDetailsPage"));
const SuggestionDetailsPage = lazy(() => import("../pages/SuggestionDetailsPage"));
const ProfilePage = lazy(() => import("../pages/ProfilePage"));

type Page = LazyExoticComponent<ComponentType>;

// Páginas com entrada na navegação. Nova página de topo: uma linha aqui.
export const navPages: { path: string; label: string; icon: typeof IconHome; Page: Page }[] = [
  { path: "/", label: "Início", icon: IconHome, Page: HomePage },
  { path: "/camera", label: "Câmara", icon: IconCamera, Page: CameraPage },
  { path: "/events", label: "Eventos", icon: IconTimeline, Page: EventsPage },
  { path: "/automations", label: "Automações", icon: IconAutomation, Page: AutomationsPage },
  { path: "/account", label: "Perfil", icon: IconUser, Page: ProfilePage },
];

// Páginas de detalhe, sem entrada na navegação.
export const detailPages: { path: string; Page: Page }[] = [
  { path: "/automations/suggestions/:id", Page: SuggestionDetailsPage },
  { path: "/automations/:id", Page: AutomationDetailsPage },
];

/** Item de navegação ativo para um pathname (detalhes herdam a secção de topo). */
export const activeNavPath = (pathname: string) =>
  navPages.find((page) => page.path !== "/" && pathname.startsWith(page.path))?.path ?? (pathname === "/conta" ? "/account" : pathname);
