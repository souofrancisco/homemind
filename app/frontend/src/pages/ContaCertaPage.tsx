import { notifications } from "@mantine/notifications";
import {
  Alert, Badge, Button, Card, Divider, Group, Loader, SimpleGrid, Tabs,
  Stack, Text, ThemeIcon, Title,
} from "@mantine/core";
import { IconAlertCircle, IconArrowRight, IconBuildingCommunity, IconInfoCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { AppRole, SectionId } from "../app/routes";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { useAuth } from "../app/providers/AuthProvider";
import BillsContent from "./BillsPage";
import RoomAllowanceLine from "../components/billing/RoomAllowanceLine";
import { listRoomAllowances, type RoomAllowanceView } from "../services/billing/allowances";
import HouseRulesCard from "../components/billing/HouseRulesCard";
import OriginBadge from "../components/common/OriginBadge";
import Dashboard from "./DashboardPage";
import AppliancesContent from "./AppliancesPage";
import BudgetContent from "./BudgetPage";
import NotificationsContent from "./NotificationsPage";
import AssistantPage from "./AssistantPage";
import { getCameraStatus, listMcpTools, type CameraStatus, type McpTool } from "../services/diagnostics/api";
import { request } from "../services/api/client";

type Placeholder = { title: string; detail: string; dependency: string; badge?: string };
function NoData({ value }: { value: Placeholder }) {
  return (
    <Card withBorder radius="lg" p={{ base: "lg", sm: "xl" }}>
      <Stack align="start" gap="md">
        <ThemeIcon size={48} radius="xl" color="indigo" variant="light"><IconInfoCircle size={25} aria-hidden="true" /></ThemeIcon>
        <Badge color="gray" variant="light">{value.badge ?? "Por integrar"}</Badge>
        <Title order={3} size="h3">{value.title}</Title>
        <Text c="dimmed" maw={650}>{value.detail}</Text>
        <Divider w="100%" />
        <Text size="sm" c="dimmed">{value.dependency}</Text>
      </Stack>
    </Card>
  );
}

const screenLabels: Record<SectionId, string> = {
  home: "Início",
  house: "Casa",
  bills: "Contas",
  notifications: "Notificações",
  assistant: "Assistente",
  budget: "Orçamento",
  diagnostics: "Diagnóstico",
  settings: "Definições",
};

function PageHeading({ title, description }: { title: string; description?: string }) {
  return <Stack gap={5}><Title order={2}>{title}</Title>{description && <Text c="dimmed" size="md">{description}</Text>}</Stack>;
}

type LoadState<T> = { key: string; value: T | null; status: "loading" | "ready" | "error" };

function useHouseholdData<T>(
  householdId: string | undefined,
  loader: (id: string) => Promise<T>,
) {
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<LoadState<T> | null>(null);

  useEffect(() => {
    if (!householdId) return;
    let active = true;
    loader(householdId)
      .then((value) => { if (active) setResult({ key: householdId, value, status: "ready" }); })
      .catch(() => { if (active) setResult({ key: householdId, value: null, status: "error" }); });
    return () => { active = false; };
  }, [householdId, loader, retry]);

  const current = result?.key === householdId ? result : null;
  return {
    data: current?.value ?? null,
    status: householdId ? current?.status ?? "loading" : "error",
    retry: () => setRetry((value) => value + 1),
  } as const;
}

function DiagnosticCard<T>({
  title,
  data,
  status,
  retry,
  children,
}: {
  title: string;
  data: T | null;
  status: "loading" | "ready" | "error";
  retry: () => void;
  children: (data: T) => React.ReactNode;
}) {
  return <Card withBorder radius="lg" p="lg">
    <Stack gap="sm">
      <Title order={3} size="h4">{title}</Title>
      {status === "loading" ? <Group role="status"><Loader size="sm" /><Text>A consultar estado…</Text></Group> :
        status === "error" ? <><Text c="dimmed" size="sm">Estado indisponível. Não foi possível confirmar a ligação.</Text><Button w="fit-content" variant="light" onClick={retry}>Tentar novamente</Button></> :
          data ? children(data) : <Text c="dimmed">Sem informação.</Text>}
    </Stack>
  </Card>;
}

function DiagnosticsContent() {
  const session = useHouseholdSession();
  const householdId = session.membership?.household_id;
  const [starting, setStarting] = useState<"heater" | "kettle" | null>(null);
  const tools = useHouseholdData<McpTool[]>(householdId, listMcpTools);
  const camera = useHouseholdData<CameraStatus>(householdId, getCameraStatus);
  return <Stack gap="md">
    {session.house?.source_kind === "demo" && <Card withBorder radius="lg" p="lg">
      <Stack gap="sm">
        <Group justify="space-between"><Title order={4}>Simulador da demo</Title></Group>
        <Text size="sm" c="dimmed">Publica uma sessão simulada na tomada da extensão da sala.</Text>
        <Group>
          <Button loading={starting === "heater"} disabled={starting !== null} onClick={async () => {
            setStarting("heater"); try { await request("/api/demo/live/heater", { method: "POST" }); notifications.show({ color: "teal", title: "Sessão simulada iniciada", message: "O aquecedor liga-se já. O pedido «De quem é esta conta?» aparece daqui a cerca de 4 minutos." }); } catch { /* o cliente HTTP já mostrou o erro */ } finally { setStarting(null); }
          }}>Aquecedor</Button>
          <Button variant="light" loading={starting === "kettle"} disabled={starting !== null} onClick={async () => {
            setStarting("kettle"); try { await request("/api/demo/live/kettle", { method: "POST" }); notifications.show({ color: "teal", title: "Sessão simulada iniciada", message: "A chaleira comum liga-se já. É um consumo pequeno: não gera pergunta." }); } catch { /* o cliente HTTP já mostrou o erro */ } finally { setStarting(null); }
          }}>Chaleira</Button>
        </Group>
      </Stack>
    </Card>}
    <DiagnosticCard title="Ligação MCP" {...tools}>
      {(value) => <Text>{value.length} ferramentas anunciadas pela API de diagnóstico.</Text>}
    </DiagnosticCard>
    <DiagnosticCard title="Câmara da porta" {...camera}>
      {(value) => <Stack gap="xs">
        <Group><Text>{value.camera_ok ? "Fonte disponível" : "Fonte indisponível"}</Text><OriginBadge origin={value.origin} demo={session.house?.source_kind === "demo"} /></Group>
        <Text size="sm" c="dimmed">Fonte: {value.source}. A vista não carrega imagens nem frames.</Text>
      </Stack>}
    </DiagnosticCard>
    <Text size="sm" c="dimmed">Diagnóstico somente de leitura. O endpoint de preview MJPEG não é usado.</Text>
  </Stack>;
}

function HouseContent() {
  const session = useHouseholdSession();
  const membership = session.membership;
  const role = membership?.role;
  const ownRoom = session.rooms.find((room) => room.id === membership?.room_id);
  const householdId = membership?.household_id;
  // Plafond por quarto em vigor este mês e mudança agendada (BILL-03); sem resposta, o valor
  // da criação do quarto (`RoomView.included_wh`).
  const [allowances, setAllowances] = useState<Record<string, RoomAllowanceView>>({});
  useEffect(() => {
    if (!householdId || role === "operator") return;
    let active = true;
    listRoomAllowances(householdId)
      .then((list) => { if (active) setAllowances(Object.fromEntries(list.map((v) => [v.room_id, v]))); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [householdId, role]);
  if (session.houseStatus === "loading") {
    return <Group gap="sm" role="status"><Loader size="sm" /><Text>A carregar a casa…</Text></Group>;
  }
  if (session.houseStatus === "error") {
    return (
      <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar a casa">
        <Stack gap="sm"><Text size="sm">Os dados não foram carregados. Verifica a ligação à API.</Text>
          <Button w="fit-content" color="red" variant="light" onClick={session.reload}>Tentar novamente</Button>
        </Stack>
      </Alert>
    );
  }
  if (!session.house) return <NoData value={{ title: "Casa não disponível", detail: "Não existem dados de casa associados à sessão.", dependency: "Verifica a tua associação à casa." }} />;
  const allowanceWh = Math.max(0, ...session.rooms.map((room) => allowances[room.id]?.current_wh ?? room.included_wh ?? 0));
  const hasAllowance = allowanceWh > 0;
  return (
    <Stack gap="lg">
      <Card withBorder radius="lg" p="lg">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap="xs">
            <Text c="dimmed" size="sm">Casa selecionada</Text>
            <Title order={3}>{session.house.name}</Title>
            <Text size="sm" c="dimmed">Fuso horário: {session.house.timezone}</Text>
          </Stack>
          <Badge color={session.house.source_kind === "demo" ? "#a63c00" : "gray"} variant={session.house.source_kind === "demo" ? "filled" : "light"} size="lg">
            {session.house.source_kind === "demo" ? "Casa de demonstração" : "Registo de produção"}
          </Badge>
        </Group>
      </Card>
      {role === "tenant" && (
        <Card withBorder radius="lg" p="lg">
          <Text size="sm" c="dimmed">O teu quarto</Text>
          <Text fw={700} size="lg">{ownRoom?.name ?? "Informação de quarto indisponível"}</Text>
          <Text c="dimmed" size="sm">O quarto que tens no contrato.</Text>
        </Card>
      )}
      <section aria-labelledby="room-list-title">
        <Title id="room-list-title" order={3} size="h4" mb="sm">Divisões da casa</Title>
        {session.rooms.length ? (
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {session.rooms.map((room) => (
              <Card key={room.id} withBorder radius="lg" p="lg">
                <Group gap="sm" wrap="nowrap">
                  <ThemeIcon radius="xl" variant="light" color="indigo"><IconBuildingCommunity size={18} aria-hidden="true" /></ThemeIcon>
                  <Stack gap={3}>
                    <Text fw={600}>{room.name}</Text>
                    <Text size="xs" c="dimmed">{room.kind === "common" ? "Zona comum" : "Quarto"}</Text>
                    {householdId && allowances[room.id] ? (
                      <RoomAllowanceLine householdId={householdId} view={allowances[room.id]} canEdit={role === "landlord"}
                        onChange={(v) => setAllowances((all) => ({ ...all, [v.room_id]: v }))} />
                    ) : null}
                  </Stack>
                </Group>
              </Card>
            ))}
          </SimpleGrid>
        ) : <Text c="dimmed">Ainda não existem divisões registadas nesta casa.</Text>}
        {hasAllowance && <Text size="sm" c="dimmed" mt="sm">O senhorio inclui {(allowanceWh / 1000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} kWh por mês de aquecimento em cada quarto, pagos por todos.</Text>}
      </section>
      {role === "tenant" && <section aria-labelledby="appliances-title"><Title id="appliances-title" order={3} size="h4" mb="sm">Aparelhos</Title><AppliancesContent /></section>}
      {role === "operator" && <section aria-labelledby="appliances-title"><Title id="appliances-title" order={3} size="h4" mb="sm">Aparelhos</Title><NoData value={{ title: "Diagnóstico de dispositivos", detail: "O operador consulta o estado técnico autorizado na área Diagnóstico.", dependency: "Não são apresentados aparelhos pessoais." }} /></section>}
      {(role === "tenant" || role === "landlord") && (
        <HouseRulesCard householdId={session.house.id} canEdit={role === "tenant"} />
      )}
      {role === "landlord" && (
        <Alert color="blue" variant="light">
          A vista de senhorio limita-se à gestão e aos totais autorizados. Não inclui presença, horários nem aparelhos pessoais dos moradores.
        </Alert>
      )}
    </Stack>
  );
}

function HomeContent({ role }: { role: AppRole }) {
  const session = useHouseholdSession();
  const landlord = role === "landlord";
  return (
    <Stack gap="lg">
      <PageHeading title={landlord ? "Hoje" : "Diagnóstico"} description={
        landlord ? "A tua casa num relance." : "Acompanha a configuração técnica sem aceder a consumos pessoais."
      } />
      <Card radius="lg" p={{ base: "lg", sm: "xl" }} bg="var(--mantine-primary-color-light)">
        <Group justify="space-between" align="center" wrap="wrap">
          <Stack gap="xs">
            <Title order={3}>{session.house?.name ?? "A tua casa"}</Title>
            <Text size="sm" maw={570}>
              {landlord
                ? "Os totais por quarto e os alertas aparecem aqui quando houver dados e uma fatura fechada."
                : "O estado dos dispositivos e das ligações está em Diagnóstico."}
            </Text>
          </Stack>
          <Group gap="xs">
            {landlord && <Button component={Link} to="/contas" variant="filled" mih={44}>Ver contas</Button>}
            <Button component={Link} to={landlord ? "/casa" : "/diagnostico"} variant={landlord ? "default" : "filled"} mih={44}
              rightSection={<IconArrowRight size={18} aria-hidden="true" />}>{landlord ? "Ver a casa" : "Abrir diagnóstico"}</Button>
          </Group>
        </Group>
      </Card>
      <Alert color="indigo" variant="light" icon={<IconInfoCircle aria-hidden="true" />}>
        {landlord ? "Esta vista nunca mostra presença ou hábitos pessoais dos moradores." : "A vista técnica não permite consultar contas ou dados privados."}
      </Alert>
    </Stack>
  );
}

export default function ContaCertaPage({ section }: { section: SectionId }) {
  const { logout } = useAuth();
  const session = useHouseholdSession();
  const role = session.membership?.role;
  if (!role) return null;
  if (section === "home" && role === "tenant") return (
    <Stack gap="xl">
      <PageHeading title={session.residentName ? `Olá, ${session.residentName}` : "Hoje"} description="" />
      <Dashboard />
    </Stack>
  );
  if (section === "home") return <HomeContent role={role} />;
  if (section === "house") return (
    <Stack gap="xl">
      <PageHeading title="Casa" description="Divisões e informações da casa associada à tua conta." />
      <HouseContent />
    </Stack>
  );
  if (section === "bills") return (
    <Stack gap="xl"><PageHeading title="Contas" description={role === "tenant" ? "As tuas contas de cada mês, já fechadas." : "Faturas registadas e estado do processamento. Os rascunhos são visíveis apenas ao senhorio."} />
      {role === "tenant" ? <Tabs defaultValue="month" styles={{ tab: { minHeight: 44 } }}><Tabs.List><Tabs.Tab value="month">Este mês</Tabs.Tab><Tabs.Tab value="receipts">Recibos</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="month" pt="md"><BudgetContent /></Tabs.Panel><Tabs.Panel value="receipts" pt="md"><BillsContent /></Tabs.Panel></Tabs>
        : <BillsContent />}
    </Stack>
  );
  if (section === "notifications") return (
    <Stack gap="xl">
      <PageHeading title={screenLabels.notifications} description="Notificações autorizadas para a tua conta e esta casa." />
      <NotificationsContent />
    </Stack>
  );
  if (section === "assistant" && role === "tenant") return <AssistantPage />;
  if (section === "diagnostics") return (
    <Stack gap="xl">
      <PageHeading title={screenLabels.diagnostics} description="Estado técnico de leitura, disponível apenas para o papel de operador." />
      <DiagnosticsContent />
    </Stack>
  );
  if (section === "settings") return (
    <Stack gap="xl" maw={760}>
      <PageHeading title="Definições" description="A tua sessão e o contexto de acesso." />
      <Card withBorder p="lg" radius="lg">
        <Stack gap="xs">
          <Title order={3} size="h4">A tua conta</Title>
          <Text>{session.residentName ?? "Utilizador autenticado"}</Text>
          <Text c="dimmed" size="sm">
            Papel atual: {role === "tenant" ? "Morador" : role === "landlord" ? "Senhorio" : "Operador"}
          </Text>
          <Text c="dimmed" size="sm">Entraste como {role === "tenant" ? "morador" : role === "landlord" ? "senhorio" : "operador"} da {session.house?.name ?? "casa"}.</Text>
          <Button color="red" variant="light" onClick={() => void logout()} mt="md" w="fit-content">Terminar sessão</Button>
        </Stack>
      </Card>
    </Stack>
  );
}
