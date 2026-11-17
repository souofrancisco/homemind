import { ActionIcon, AppShell, Center, Group, Loader, NavLink, Tabs, Title, useComputedColorScheme, useMantineColorScheme } from "@mantine/core";
import { IconAutomation, IconCamera, IconHome, IconMoon, IconSun, IconTimeline, IconUser } from "@tabler/icons-react";
import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Account from "../features/account/Account";
import Dashboard from "../features/dashboard/Dashboard";
import CameraPage from "../features/dashboard/CameraPage";
import EventsPage from "../features/dashboard/EventsPage";
import AutomationsPage from "../features/dashboard/AutomationsPage";
import { HomeDataProvider } from "../features/dashboard/useHomeSocket";
import { useAuth } from "../features/auth/AuthProvider";
import { completeLogin } from "../features/auth/oidc";

// Para uma nova feature: acrescentar uma linha aqui (rota + item de navegação).
const pages = [
  { path: "/", label: "Início", icon: IconHome, element: <Dashboard /> },
  { path: "/camera", label: "Câmara", icon: IconCamera, element: <CameraPage /> },
  { path: "/events", label: "Eventos", icon: IconTimeline, element: <EventsPage /> },
  { path: "/automations", label: "Automações", icon: IconAutomation, element: <AutomationsPage /> },
  { path: "/account", label: "Perfil", icon: IconUser, element: <Account /> },
];

function Protected({ children }: { children: ReactNode }) {
  const { user, login } = useAuth();
  useEffect(() => {
    if (!user) void login();
  }, [user, login]);
  return user ? (
    children
  ) : (
    <Center h="100dvh">
      <Loader />
    </Center>
  );
}

function Callback() {
  const navigate = useNavigate();
  useEffect(() => {
    completeLogin()
      .then((u) => navigate(typeof u?.state === "string" && u.state !== "/auth/callback" ? u.state : "/", { replace: true }))
      .catch(() => navigate("/", { replace: true }));
  }, [navigate]);
  return null;
}

function Shell() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");

  return (
    <HomeDataProvider>
    <AppShell header={{ height: 64 }} navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: true } }} footer={{ height: 64 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs"><Title order={3}>ObjectOS</Title><span style={{ color: "var(--mantine-color-dimmed)", fontSize: 12 }}>HOME SYSTEM</span></Group>
          <ActionIcon variant="default" aria-label="Tema" onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}>
            {scheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
          </ActionIcon>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs" visibleFrom="sm">
        {pages.map((p) => (
          <NavLink key={p.path} label={p.label} leftSection={<p.icon size={18} />} active={pathname === p.path} onClick={() => navigate(p.path)} />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Routes>
          {pages.map((p) => (
            <Route key={p.path} path={p.path} element={p.element} />
          ))}
          <Route path="/conta" element={<Navigate to="/account" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell.Main>
      <AppShell.Footer hiddenFrom="sm" pb="env(safe-area-inset-bottom)">
        <Tabs value={pathname === "/conta" ? "/account" : pathname} onChange={(v) => v && navigate(v)} variant="pills">
          <Tabs.List h={64} grow style={{ flexWrap: "nowrap", overflowX: "auto" }}>
            {pages.map((p) => (
              <Tabs.Tab key={p.path} value={p.path} leftSection={<p.icon size={18} />}>
                {p.label}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
      </AppShell.Footer>
    </AppShell>
    </HomeDataProvider>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/auth/callback" element={<Callback />} />
      <Route
        path="*"
        element={
          <Protected>
            <Shell />
          </Protected>
        }
      />
    </Routes>
  );
}
