import {
  Alert, AppShell, Box, Button, Center, Container, Group,
  Loader, Menu, SimpleGrid, Stack, Text, Title,
  UnstyledButton, useComputedColorScheme, useMantineColorScheme,
} from "@mantine/core";
import { IconLogout, IconMoon, IconSettings, IconSun } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { activeNavPath, canSeePath, visiblePages } from "../../app/routes";
import { useAuth } from "../../app/providers/AuthProvider";
import { useHouseholdSession } from "../../app/providers/HouseholdProvider";
import { listNotifications } from "../../services/notifications/api";
import ContaCertaPage from "../../pages/ContaCertaPage";
import NotificationBell from "./NotificationBell";
import "./shell.css";

export default function Shell() {
  const { pathname } = useLocation();
  const { logout } = useAuth();
  const session = useHouseholdSession();
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const role = session.membership?.role ?? null;
  const pages = visiblePages(role);
  const active = activeNavPath(pathname);
  const current = pages.find((page) => page.path === active);
  const pageTitle = current?.label ?? (pathname === "/notificacoes" ? "Notificações" : pathname === "/definicoes" ? "Definições" : "Conta Certa");
  const [unread, setUnread] = useState<number | null>(null);
  const householdId = session.membership?.household_id;

  const refreshUnread = useCallback(() => {
    if (!householdId || (role !== "tenant" && role !== "landlord")) return;
    void listNotifications(householdId).then((items) => setUnread(items.filter((item) => item.status === "unread").length)).catch(() => setUnread(null));
  }, [householdId, role]);
  useEffect(() => {
    refreshUnread();
    const timer = window.setInterval(refreshUnread, 30000);
    const onVisible = () => { if (document.visibilityState === "visible") refreshUnread(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [refreshUnread]);

  useEffect(() => { document.title = pageTitle === "Conta Certa" ? pageTitle : `${pageTitle} · Conta Certa`; }, [pageTitle]);

  const menu = pages.map((page) => (
    <Link key={page.path} to={page.path} className="conta-nav-link" aria-current={active === page.path ? "page" : undefined}>
      <page.icon size={20} stroke={2} aria-hidden="true" /><span>{page.label}</span>
    </Link>
  ));
  const displayName = session.residentName?.trim() || "Perfil";
  const initial = displayName === "Perfil" ? "P" : displayName[0].toLocaleUpperCase("pt-PT");

  return <>
    <a href="#main" className="conta-skip-link">Saltar para o conteúdo</a>
    <Box className="conta-visually-hidden" aria-live="polite" aria-atomic="true">{pageTitle}</Box>
    <AppShell layout="alt" header={{ height: 72 }} navbar={{ width: 248, breakpoint: "sm", collapsed: { mobile: true } }} padding={0}>
      <AppShell.Header withBorder={false}>
        <Group h="100%" px={{ base: "md", sm: 48 }} justify="space-between" wrap="nowrap">
          <Title order={1} size="h3" lh={1.1} hiddenFrom="sm">Conta Certa</Title>
          <Group ml="auto" gap={12} wrap="nowrap">
            {session.house?.source_kind === "demo" && <Box className="conta-demo-pill" visibleFrom="sm">Demonstração · dados simulados</Box>}
          <Group gap={12} wrap="nowrap">
            {(role === "tenant" || role === "landlord") && householdId && <NotificationBell householdId={householdId} unread={unread} onChanged={refreshUnread} />}
            <Menu position="bottom-end" withinPortal>
              <Menu.Target><UnstyledButton aria-label={`Perfil de ${displayName}`} className="conta-avatar">{initial}</UnstyledButton></Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{session.house?.name ?? "Casa não selecionada"}</Menu.Label>
                {session.memberships.length > 1 && <>
                  <Menu.Divider /><Menu.Label>Escolher casa</Menu.Label>
                  {session.memberships.map((membership, index) => <Menu.Item key={membership.id} onClick={() => session.selectMembership(membership.id)}
                    aria-current={membership.id === session.selectedMembershipId ? "true" : undefined}>
                    Casa {index + 1}
                  </Menu.Item>)}
                </>}
                <Menu.Divider />
                <Menu.Item component={Link} to="/definicoes" leftSection={<IconSettings size={16} />}>Definições</Menu.Item>
                <Menu.Item leftSection={scheme === "dark" ? <IconSun size={16} /> : <IconMoon size={16} />} onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}>
                  Tema {scheme === "dark" ? "claro" : "escuro"}
                </Menu.Item>
                <Menu.Divider /><Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={() => void logout()}>Terminar sessão</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="md" visibleFrom="sm" component="nav" aria-label="Navegação principal">
        <Stack h="100%" gap={0}><Box className="conta-side-brand"><Title order={2} size="h3">Conta Certa</Title></Box><Stack gap={6}>{menu}</Stack>
          <Box mt="auto" px={14}><Text fz={13} fw={700}>{session.house?.name ?? "Casa não selecionada"}</Text></Box>
        </Stack>
      </AppShell.Navbar>
      <AppShell.Main id="main" tabIndex={-1}>
        <Container size="xl" className="conta-main-inner">
          {session.house?.source_kind === "demo" && <Box className="conta-demo-pill" role="note" hiddenFrom="sm" mb="md">Demonstração · dados simulados</Box>}
          {session.status === "loading" ? <Center mih="55dvh" role="status" aria-label="A carregar o contexto da casa"><Stack align="center"><Loader /><Text>A carregar a tua casa…</Text></Stack></Center>
            : session.status === "error" ? <Alert color="red" title="Não foi possível carregar a tua casa"><Stack gap="sm"><Text size="sm">Verifica a ligação e tenta novamente. Não são apresentados dados guardados de outra sessão.</Text><Button variant="light" color="red" w="fit-content" onClick={session.reload}>Tentar novamente</Button></Stack></Alert>
              : !session.membership ? <Stack align="start" gap="md"><Title order={2}>Sem casa associada</Title><Text>O teu utilizador está autenticado, mas ainda não possui uma associação ativa a uma casa.</Text><Text c="dimmed" size="sm">Pede ao responsável da casa para confirmar a associação. Não é possível escolher um papel manualmente.</Text><Button variant="light" onClick={session.reload}>Atualizar</Button><Button variant="subtle" color="gray" onClick={() => void logout()}>Terminar sessão</Button></Stack>
                : <Routes>
                  {pages.map((page) => <Route key={page.path} path={page.path} element={<ContaCertaPage section={page.section} />} />)}
                  {role === "operator" && <Route path="/" element={<ContaCertaPage section="home" />} />}
                  <Route path="/notificacoes" element={canSeePath(role, pathname) ? <ContaCertaPage section="notifications" /> : <Navigate to="/" replace />} />
                  <Route path="/definicoes" element={canSeePath(role, pathname) ? <ContaCertaPage section="settings" /> : <Navigate to="/" replace />} />
                  <Route path="/consumo" element={<Navigate to="/" replace />} /><Route path="/orcamento" element={<Navigate to="/contas" replace />} />
                  <Route path="/aparelhos" element={<Navigate to="/casa" replace />} /><Route path="*" element={<Navigate to="/" replace />} />
                </Routes>}
        </Container>
      </AppShell.Main>
      <AppShell.Footer hiddenFrom="sm" component="nav" aria-label="Navegação móvel" className="conta-mobile-nav">
        <SimpleGrid cols={Math.max(1, pages.length)} spacing={0} h="100%">
          {pages.map((page) => { const selected = page.path === active; return <UnstyledButton key={page.path} component={Link} to={page.path} aria-current={selected ? "page" : undefined} ta="center" className="conta-mobile-link" style={{ minHeight: 54 }}>
            <Stack gap={3} align="center"><page.icon size={22} aria-hidden="true" /><Text size="xs" fw={selected ? 700 : 500} truncate>{page.label}</Text></Stack>
          </UnstyledButton>; })}
        </SimpleGrid>
      </AppShell.Footer>
    </AppShell>
  </>;
}
