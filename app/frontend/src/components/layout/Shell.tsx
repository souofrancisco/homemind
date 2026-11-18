import {
  ActionIcon, Alert, AppShell, Badge, Box, Burger, Button, Center, Container,
  Group, Loader, NavLink, Select, SimpleGrid, Stack, Text, Title, UnstyledButton,
  useComputedColorScheme, useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconAlertCircle, IconDots, IconMoon, IconSun } from "@tabler/icons-react";
import { useEffect } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { activeNavPath, visiblePages, type AppRole } from "../../app/routes";
import { useAuth } from "../../app/providers/AuthProvider";
import { useHouseholdSession } from "../../app/providers/HouseholdProvider";
import ContaCertaPage from "../../pages/ContaCertaPage";
import "./shell.css";

const roleNames: Record<AppRole, string> = {
  tenant: "Morador",
  landlord: "Senhorio",
  operator: "Operador",
};

export default function Shell() {
  const { pathname } = useLocation();
  const { logout } = useAuth();
  const session = useHouseholdSession();
  const [opened, { toggle, close }] = useDisclosure(false);
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const role = session.membership?.role ?? null;
  const pages = visiblePages(role);
  const active = activeNavPath(pathname);
  const current = pages.find((page) => page.path === active);
  const primaryMobile = pages.filter((page) => page.mobile);
  const moreMobile = pages.filter((page) => !page.mobile);
  const activeInMore = moreMobile.some((page) => page.path === active);
  const hasMore = moreMobile.length > 0;

  useEffect(() => {
    document.title = current ? `${current.label} · Conta Certa` : "Conta Certa";
  }, [current]);

  const menu = pages.map((page) => (
    <NavLink
      key={page.path}
      component={Link}
      to={page.path}
      onClick={close}
      label={page.label}
      leftSection={<page.icon size={20} aria-hidden="true" />}
      active={active === page.path}
      aria-current={active === page.path ? "page" : undefined}
      fw={active === page.path ? 700 : 500}
      py="sm"
    />
  ));

  return (
    <>
      <a href="#main" className="conta-skip-link">Saltar para o conteúdo</a>
      <Box className="conta-visually-hidden" aria-live="polite" aria-atomic="true">
        {current?.label ?? "Conta Certa"}
      </Box>
      <AppShell
        header={{ height: 76 }}
        navbar={{ width: 258, breakpoint: "sm", collapsed: { mobile: !opened } }}
        footer={{ height: 76 }}
        padding={{ base: "md", md: "xl" }}
      >
        <AppShell.Header>
          <Group h="100%" px={{ base: "md", sm: "xl" }} justify="space-between" wrap="nowrap">
            <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
              <Burger hiddenFrom="sm" opened={opened} onClick={toggle} aria-label={opened ? "Fechar menu" : "Abrir menu"} size="sm" />
              <Box style={{ minWidth: 0 }}>
                <Title order={1} size="h3" lh={1.1}>Conta Certa</Title>
                <Text c="dimmed" size="xs" visibleFrom="sm">A energia da casa, com contas claras.</Text>
              </Box>
            </Group>
            <Group gap="xs" wrap="nowrap">
              {role && <Badge size="sm" variant="light" visibleFrom="sm">{roleNames[role]}</Badge>}
              {role && session.memberships.length <= 1 && <Badge size="xs" variant="light" hiddenFrom="sm">{roleNames[role]}</Badge>}
              {session.memberships.length > 1 && (
                <Select
                  size="sm"
                  aria-label="Selecionar casa e papel"
                  value={session.selectedMembershipId}
                  onChange={(value) => { if (value) session.selectMembership(value); close(); }}
                  data={session.memberships.map((m, index) => ({
                    value: m.id,
                    label: `Casa ${index + 1} · ${roleNames[m.role]}`,
                  }))}
                  w={{ base: 104, sm: 195 }}
                  allowDeselect={false}
                />
              )}
              <ActionIcon
                size={44}
                variant="default"
                aria-label={scheme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"}
                onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}
              >
                {scheme === "dark" ? <IconSun size={20} /> : <IconMoon size={20} />}
              </ActionIcon>
            </Group>
          </Group>
        </AppShell.Header>

        <AppShell.Navbar p="md" component="nav" aria-label="Navegação principal">
          <Stack h="100%" gap="sm">
            <Text size="xs" fw={700} c="dimmed" tt="uppercase" px="sm">Explorar</Text>
            <Stack gap={3}>{menu}</Stack>
            <Box mt="auto" px="sm">
              <Text c="dimmed" size="xs">
                {session.house?.name ?? "Casa não selecionada"}
              </Text>
              <Text c="dimmed" size="xs">Os dados pessoais são limitados pelo teu papel.</Text>
            </Box>
          </Stack>
        </AppShell.Navbar>

        <AppShell.Main id="main" tabIndex={-1}>
          <Container size="xl" px={0} pb={{ base: "xl", sm: "md" }}>
            {session.status === "loading" ? (
              <Center mih="55dvh" role="status" aria-label="A carregar o contexto da casa">
                <Stack align="center"><Loader /><Text>A carregar a tua casa…</Text></Stack>
              </Center>
            ) : session.status === "error" ? (
              <Alert icon={<IconAlertCircle />} color="red" title="Não foi possível carregar a tua casa">
                <Stack gap="sm">
                  <Text size="sm">Verifica a ligação e tenta novamente. Não são apresentados dados guardados de outra sessão.</Text>
                  <Button variant="light" color="red" w="fit-content" onClick={session.reload}>Tentar novamente</Button>
                </Stack>
              </Alert>
            ) : !session.membership ? (
              <Stack align="start" gap="md">
                <Title order={2}>Sem casa associada</Title>
                <Text>O teu utilizador está autenticado, mas ainda não possui uma associação ativa a uma casa.</Text>
                <Text c="dimmed" size="sm">Pede ao responsável da casa para confirmar a associação. Não é possível escolher um papel manualmente.</Text>
                <Button variant="light" onClick={session.reload}>Atualizar</Button>
                <Button variant="subtle" color="gray" onClick={() => void logout()}>Terminar sessão</Button>
              </Stack>
            ) : (
              <Routes>
                {pages.map((page) => (
                  <Route key={page.path} path={page.path} element={<ContaCertaPage section={page.section} />} />
                ))}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            )}
          </Container>
        </AppShell.Main>

        <AppShell.Footer hiddenFrom="sm" pb="env(safe-area-inset-bottom)" component="nav" aria-label="Navegação móvel">
          <SimpleGrid cols={Math.max(1, primaryMobile.length + (hasMore ? 1 : 0))} spacing={0} h="100%">
            {primaryMobile.map((page) => {
              const selected = page.path === active;
              return (
                <UnstyledButton
                  key={page.path}
                  component={Link}
                  to={page.path}
                  onClick={close}
                  aria-current={selected ? "page" : undefined}
                  ta="center"
                  c={selected ? "var(--mantine-primary-color-filled)" : "dimmed"}
                  style={{ borderTop: selected ? "3px solid var(--mantine-primary-color-filled)" : "3px solid transparent" }}
                >
                  <Stack gap={3} align="center">
                    <page.icon size={22} aria-hidden="true" />
                    <Text size="xs" fw={selected ? 700 : 500} truncate>{page.label === "Contas e recibos" ? "Contas" : page.label === "A minha casa" ? "Casa" : page.label}</Text>
                  </Stack>
                </UnstyledButton>
              );
            })}
            {hasMore && (
              <UnstyledButton
                onClick={toggle}
                aria-label={opened ? "Fechar mais páginas" : "Abrir mais páginas"}
                aria-expanded={opened}
                ta="center"
                c={activeInMore ? "var(--mantine-primary-color-filled)" : "dimmed"}
              >
                <Stack gap={3} align="center"><IconDots size={22} aria-hidden="true" /><Text size="xs" fw={activeInMore ? 700 : 500}>Mais</Text></Stack>
              </UnstyledButton>
            )}
          </SimpleGrid>
        </AppShell.Footer>
      </AppShell>
    </>
  );
}
