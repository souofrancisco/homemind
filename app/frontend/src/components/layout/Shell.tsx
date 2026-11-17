import { ActionIcon, AppShell, Badge, Group, Loader, NavLink, Tabs, Title, useComputedColorScheme, useMantineColorScheme } from "@mantine/core";
import { IconMoon, IconSun } from "@tabler/icons-react";
import { Suspense } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { activeNavPath, detailPages, navPages } from "../../app/routes";
import { useHome } from "../../hooks/useHome";

export default function Shell() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const { simulated } = useHome();
  const active = activeNavPath(pathname);

  return (
    <AppShell header={{ height: 64 }} navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: true } }} footer={{ height: 64 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs"><Title order={3}>ObjectOS</Title><span style={{ color: "var(--mantine-color-dimmed)", fontSize: 12 }}>HOME SYSTEM</span></Group>
          <Group gap="sm">
            {simulated ? <Badge color="yellow" variant="light" title="Dados de exemplo: as ações não alteram dispositivos reais.">Modo de demonstração</Badge> : null}
            <ActionIcon variant="default" aria-label="Tema" onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}>
              {scheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs" visibleFrom="sm">
        {navPages.map((p) => (
          <NavLink key={p.path} label={p.label} leftSection={<p.icon size={18} />} active={active === p.path} onClick={() => navigate(p.path)} />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Suspense fallback={<Loader size="sm" />}>
          <Routes>
            {[...navPages, ...detailPages].map(({ path, Page }) => (
              <Route key={path} path={path} element={<Page />} />
            ))}
            <Route path="/conta" element={<Navigate to="/account" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AppShell.Main>
      <AppShell.Footer hiddenFrom="sm" pb="env(safe-area-inset-bottom)">
        <Tabs value={active} onChange={(v) => v && navigate(v)} variant="pills">
          <Tabs.List h={64} grow style={{ flexWrap: "nowrap", overflowX: "auto" }}>
            {navPages.map((p) => (
              <Tabs.Tab key={p.path} value={p.path} leftSection={<p.icon size={18} />}>
                {p.label}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
      </AppShell.Footer>
    </AppShell>
  );
}
