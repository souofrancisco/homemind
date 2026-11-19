import {
  ActionIcon, Alert, AppShell, Badge, Box, Button, Center, Container, Group,
  Indicator, Loader, Menu, NavLink, SimpleGrid, Stack, Text, Title,
  UnstyledButton, useComputedColorScheme, useMantineColorScheme,
} from "@mantine/core";
import { IconBell, IconChevronDown, IconLogout, IconMoon, IconSettings, IconSun } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { activeNavPath, canSeePath, visiblePages, type AppRole } from "../../app/routes";
import { useAuth } from "../../app/providers/AuthProvider";
import { useHouseholdSession } from "../../app/providers/HouseholdProvider";
import { listNotifications } from "../../services/notifications/api";
import ContaCertaPage from "../../pages/ContaCertaPage";
import "./shell.css";

const roleNames: Record<AppRole, string> = { tenant: "Morador", landlord: "Senhorio", operator: "Operador" };

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
    <NavLink key={page.path} component={Link} to={page.path} label={page.label}
      leftSection={<page.icon size={20} aria-hidden="true" />} active={active === page.path}
      aria-current={active === page.path ? "page" : undefined} fw={active === page.path ? 700 : 500} py="sm" />
  ));
  const displayName = session.residentName?.trim() || "Perfil";
  const initial = displayName === "Perfil" ? "P" : displayName[0].toLocaleUpperCase("pt-PT");

  return <>
    <a href="#main" className="conta-skip-link" style={{ background: "#364fc7", color: "#fff" }}>Saltar para o conteúdo</a>
    <Box className="conta-visually-hidden" aria-live="polite" aria-atomic="true">{pageTitle}</Box>
    <AppShell header={{ height: 76 }} navbar={{ width: 258, breakpoint: "sm", collapsed: { mobile: true } }} footer={{ height: 76 }} padding={{ base: "md", md: "xl" }}>
      <AppShell.Header>
        <Group h="100%" px={{ base: "md", sm: "xl" }} justify="space-between" wrap="nowrap">
          <Box style={{ minWidth: 0 }}><Title order={1} size="h3" lh={1.1}>Conta Certa</Title><Text c="dimmed" size="xs" visibleFrom="sm">A energia da casa, com contas claras.</Text></Box>
          <Group gap="xs" wrap="nowrap">
            {(role === "tenant" || role === "landlord") && <ActionIcon component={Link} to="/notificacoes" size={44} variant="default"
              aria-label={`Notificações: ${unread ?? 0} por responder`}>
              <Indicator label={unread ?? 0} size={18} disabled={!unread} color="red.9"><IconBell size={21} aria-hidden="true" /></Indicator>
            </ActionIcon>}
            <Menu position="bottom-end" withinPortal>
              <Menu.Target><UnstyledButton aria-label={`Perfil de ${displayName}`} className="conta-profile-button">
                <Group gap="xs" wrap="nowrap"><Badge circle size="lg" variant="filled" color="indigo.8">{initial}</Badge><Text size="sm" fw={600} maw={{ base: 72, sm: 145 }} truncate>{displayName}</Text><IconChevronDown size={16} aria-hidden="true" /></Group>
              </UnstyledButton></Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{session.house?.name ?? "Casa não selecionada"}{role ? ` · ${roleNames[role]}` : ""}</Menu.Label>
                {session.memberships.length > 1 && <>
                  <Menu.Divider /><Menu.Label>Casa e papel</Menu.Label>
                  {session.memberships.map((membership, index) => <Menu.Item key={membership.id} onClick={() => session.selectMembership(membership.id)}
                    aria-current={membership.id === session.selectedMembershipId ? "true" : undefined}>
                    Casa {index + 1} · {roleNames[membership.role]}
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
      </AppShell.Header>
      <AppShell.Navbar p="md" visibleFrom="sm" component="nav" aria-label="Navegação principal">
        <Stack h="100%" gap="sm"><Text size="xs" fw={700} c="dimmed" tt="uppercase" px="sm">Navegação</Text><Stack gap={3}>{menu}</Stack>
          <Box mt="auto" px="sm"><Text c="dimmed" size="sm">{session.house?.name ?? "Casa não selecionada"}</Text>{role && <Text c="dimmed" size="xs">{roleNames[role]}</Text>}</Box>
        </Stack>
      </AppShell.Navbar>
      <AppShell.Main id="main" tabIndex={-1}>
        <Container size="xl" px={0} pb={{ base: "xl", sm: "md" }}>
          {session.house?.source_kind === "demo" && <Box className="conta-demo-banner" role="note">Casa de demonstração · todos os dados são SIMULADOS</Box>}
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
      <AppShell.Footer hiddenFrom="sm" pb="env(safe-area-inset-bottom)" component="nav" aria-label="Navegação móvel">
        <SimpleGrid cols={Math.max(1, pages.length)} spacing={0} h="100%">
          {pages.map((page) => { const selected = page.path === active; return <UnstyledButton key={page.path} component={Link} to={page.path} aria-current={selected ? "page" : undefined} ta="center" c={selected ? "var(--mantine-primary-color-filled)" : "dimmed"} style={{ minHeight: 44, borderTop: selected ? "3px solid var(--mantine-primary-color-filled)" : "3px solid transparent" }}>
            <Stack gap={3} align="center"><page.icon size={22} aria-hidden="true" /><Text size="xs" fw={selected ? 700 : 500} truncate>{page.label}</Text></Stack>
          </UnstyledButton>; })}
        </SimpleGrid>
      </AppShell.Footer>
    </AppShell>
  </>;
}
