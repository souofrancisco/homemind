import { ActionIcon, AppShell, Badge, Center, Group, Loader, NavLink, SimpleGrid, Stack, Text, Title, UnstyledButton, useComputedColorScheme, useMantineColorScheme } from "@mantine/core";
import { IconMoon, IconSun } from "@tabler/icons-react";
import { Suspense, useEffect } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { activeNavPath, detailPages, navPages } from "../../app/routes";
import { useHome } from "../../hooks/useHome";

export default function Shell() {
  const { pathname } = useLocation();
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const { simulated, mock } = useHome();
  const active = activeNavPath(pathname);
  const current = navPages.find((p) => p.path === active);

  // Leitores de ecrã anunciam a mudança de página pelo título (de feat/objectos-ux).
  useEffect(() => { document.title = current ? `${current.label} · ObjectOS` : "ObjectOS"; }, [current]);

  return (
    <AppShell header={{ height: 64 }} navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: true } }} footer={{ height: 68 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs" wrap="nowrap"><Title order={1} size="h3">ObjectOS</Title><Text size="xs" fw={600} visibleFrom="xs" c="light-dark(var(--mantine-color-gray-7), var(--mantine-color-dark-1))">HOME SYSTEM</Text></Group>
          <Group gap="sm">
            {mock ? <Badge color="red" variant="light" title="VITE_OBJECTOS_SOURCE=mock: dados do browser, sem backend.">Mock do browser</Badge> : simulated ? <Badge color="yellow" variant="light" title="FakeHome do backend: as ações não alteram dispositivos físicos.">Simulado (FakeHome)</Badge> : null}
            <ActionIcon variant="default" size={44} aria-label={scheme === "dark" ? "Mudar para tema claro" : "Mudar para tema escuro"} onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}>
              {scheme === "dark" ? <IconSun size={20} /> : <IconMoon size={20} />}
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs" visibleFrom="sm" component="nav" aria-label="Navegação principal">
        {navPages.map((p) => (
          <NavLink key={p.path} component={Link} to={p.path} label={p.label} leftSection={<p.icon size={20} aria-hidden="true" />} active={active === p.path} aria-current={active === p.path ? "page" : undefined} py="sm" fw={active === p.path ? 700 : 500} />
        ))}
      </AppShell.Navbar>
      <AppShell.Main id="main">
        <Suspense fallback={<Center h="50dvh" role="status" aria-label="A carregar"><Loader /></Center>}>
          <Routes>
            {[...navPages, ...detailPages].map(({ path, Page }) => (
              <Route key={path} path={path} element={<Page />} />
            ))}
            <Route path="/conta" element={<Navigate to="/account" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AppShell.Main>
      <AppShell.Footer hiddenFrom="sm" pb="env(safe-area-inset-bottom)" component="nav" aria-label="Navegação principal">
        <SimpleGrid cols={navPages.length} spacing={0} h="100%">
          {navPages.map((p) => {
            const on = active === p.path;
            return (
              <UnstyledButton key={p.path} component={Link} to={p.path} aria-current={on ? "page" : undefined} c={on ? "var(--mantine-primary-color-filled)" : "light-dark(var(--mantine-color-gray-8), var(--mantine-color-dark-0))"} style={{ borderTop: `3px solid ${on ? "var(--mantine-primary-color-filled)" : "transparent"}`, minWidth: 0 }}>
                <Stack gap={2} align="center" justify="center" h="100%">
                  <p.icon size={22} aria-hidden="true" />
                  <Text inherit fw={on ? 700 : 500} style={{ fontSize: 11 }}>{p.label}</Text>
                </Stack>
              </UnstyledButton>
            );
          })}
        </SimpleGrid>
      </AppShell.Footer>
    </AppShell>
  );
}
