import {
  Alert, Badge, Button, Card, Divider, Group, Loader, SimpleGrid,
  Stack, Text, ThemeIcon, Title,
} from "@mantine/core";
import { IconAlertCircle, IconArrowRight, IconBuildingCommunity, IconInfoCircle, IconReceipt, IconActivity } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import type { AppRole, SectionId } from "../app/routes";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { useAuth } from "../app/providers/AuthProvider";

type Placeholder = { title: string; detail: string; dependency: string };
const placeholders: Record<"consumption" | "appliances" | "bills" | "notifications" | "assistant" | "diagnostics", Placeholder> = {
  consumption: {
    title: "O consumo ainda não está disponível",
    detail: "Este ecrã receberá apenas leituras e resumos autorizados, com origem e grau de confiança visíveis.",
    dependency: "Integração futura: energia e resumos de consumo.",
  },
  appliances: {
    title: "O catálogo de aparelhos está em preparação",
    detail: "O registo e a identificação de aparelhos serão ligados ao catálogo da casa. Aqui não existem aparelhos inventados.",
    dependency: "Integração futura: HOUSE-03 e identificação de aparelhos.",
  },
  bills: {
    title: "Ainda não existem contas ou recibos para apresentar",
    detail: "Quando a faturação estiver disponível, cada valor terá uma explicação e a origem identificada.",
    dependency: "Integração futura: APP-05/06 e faturação.",
  },
  notifications: {
    title: "O centro de notificações está em preparação",
    detail: "Os pedidos de confirmação e os alertas serão recebidos aqui. Não há notificações de exemplo a fingir que foram entregues.",
    dependency: "Integração futura: centro de notificações P3.",
  },
  assistant: {
    title: "O assistente ainda não está ligado",
    detail: "Quando estiver disponível, as respostas usarão apenas ferramentas e dados a que tens acesso. Nenhuma ação será executada sem confirmação.",
    dependency: "Integração futura: assistente P3.",
  },
  diagnostics: {
    title: "Diagnóstico técnico ainda não integrado",
    detail: "O estado da ligação MCP, da tomada e da câmara será apresentado depois da integração autorizada. Não existem comandos de controlo neste ecrã.",
    dependency: "Integração futura: ferramentas de diagnóstico do operador.",
  },
};

function NoData({ value }: { value: Placeholder }) {
  return (
    <Card withBorder radius="lg" p={{ base: "lg", sm: "xl" }}>
      <Stack align="start" gap="md">
        <ThemeIcon size={48} radius="xl" color="indigo" variant="light"><IconInfoCircle size={25} aria-hidden="true" /></ThemeIcon>
        <Badge color="gray" variant="light">Por integrar</Badge>
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
  house: "A minha casa",
  consumption: "Consumo",
  appliances: "Aparelhos",
  bills: "Contas e recibos",
  notifications: "Notificações",
  assistant: "Assistente",
  diagnostics: "Diagnóstico",
  settings: "Definições",
};

function PageHeading({ title, description }: { title: string; description: string }) {
  return <Stack gap={5}><Title order={2}>{title}</Title><Text c="dimmed" size="md">{description}</Text></Stack>;
}

function HouseContent() {
  const session = useHouseholdSession();
  const membership = session.membership;
  const role = membership?.role;
  const ownRoom = session.rooms.find((room) => room.id === membership?.room_id);
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
  return (
    <Stack gap="lg">
      <Card withBorder radius="lg" p="lg">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap="xs">
            <Text c="dimmed" size="sm">Casa selecionada</Text>
            <Title order={3}>{session.house.name}</Title>
            <Text size="sm" c="dimmed">Fuso horário: {session.house.timezone}</Text>
          </Stack>
          <Badge color={session.house.source_kind === "demo" ? "yellow" : "gray"} variant="light" size="lg">
            {session.house.source_kind === "demo" ? "Casa de demonstração" : "Registo de produção"}
          </Badge>
        </Group>
        <Text c="dimmed" size="xs" mt="md">
          A classificação da casa não demonstra que existam leituras reais. Cada medição futura terá a sua própria proveniência: REAL, ESTIMADO ou SIMULADO.
        </Text>
      </Card>
      {role === "tenant" && (
        <Card withBorder radius="lg" p="lg">
          <Text size="sm" c="dimmed">O teu quarto</Text>
          <Text fw={700} size="lg">{ownRoom?.name ?? "Informação de quarto indisponível"}</Text>
          <Text c="dimmed" size="sm">Esta associação vem do teu contrato, não de sensores de presença.</Text>
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
                  </Stack>
                </Group>
              </Card>
            ))}
          </SimpleGrid>
        ) : <Text c="dimmed">Ainda não existem divisões registadas nesta casa.</Text>}
      </section>
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
  const title = role === "landlord" ? "A gestão da casa, sem complicações" :
    role === "operator" ? "O espaço técnico da tua casa" : "A tua energia, com contas claras";
  return (
    <Stack gap="lg">
      <PageHeading title={title} description={
        role === "landlord" ? "Organiza a casa e consulta os totais mensais quando estiverem disponíveis." :
        role === "operator" ? "Acompanha a configuração técnica sem aceder a consumos pessoais." :
        "Tudo o que precisas para perceber o consumo e a tua parte da conta."
      } />
      <Card radius="lg" p={{ base: "lg", sm: "xl" }} bg="var(--mantine-primary-color-light)">
        <Group justify="space-between" align="center" wrap="wrap">
          <Stack gap="xs">
            <Text size="xs" fw={700} tt="uppercase">O teu espaço</Text>
            <Title order={3}>{session.house?.name ?? "A tua casa"}</Title>
            <Text size="sm" maw={570}>Uma única aplicação para a casa partilhada. A informação só aparece quando existe uma fonte autorizada.</Text>
          </Stack>
          <Button component={Link} to="/casa" variant="filled" rightSection={<IconArrowRight size={18} aria-hidden="true" />}>Ver a casa</Button>
        </Group>
      </Card>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        <Card withBorder radius="lg" p="lg">
          <ThemeIcon size={40} radius="xl" variant="light"><IconBuildingCommunity size={22} aria-hidden="true" /></ThemeIcon>
          <Title order={3} size="h4" mt="md">Casa</Title>
          <Text c="dimmed" size="sm" mt="xs">{session.houseStatus === "ready" ? "Estrutura da casa disponível." : "A carregar a estrutura da casa."}</Text>
          <Button component={Link} to="/casa" variant="subtle" mt="md" px={0}>Abrir casa</Button>
        </Card>
        {role !== "operator" && (
          <Card withBorder radius="lg" p="lg">
            <ThemeIcon size={40} radius="xl" variant="light"><IconActivity size={22} aria-hidden="true" /></ThemeIcon>
            <Title order={3} size="h4" mt="md">{role === "landlord" ? "Totais de consumo" : "O teu consumo"}</Title>
            <Text c="dimmed" size="sm" mt="xs">Sem medições disponíveis nesta versão. Não apresentamos valores de exemplo como reais.</Text>
            <Button component={Link} to="/consumo" variant="subtle" mt="md" px={0}>Consultar a secção</Button>
          </Card>
        )}
        {role !== "operator" && (
          <Card withBorder radius="lg" p="lg">
            <ThemeIcon size={40} radius="xl" variant="light"><IconReceipt size={22} aria-hidden="true" /></ThemeIcon>
            <Title order={3} size="h4" mt="md">Contas e recibos</Title>
            <Text c="dimmed" size="sm" mt="xs">Sem faturas integradas. Os recibos detalhados são responsabilidade do módulo de faturação.</Text>
            <Button component={Link} to="/contas" variant="subtle" mt="md" px={0}>Consultar a secção</Button>
          </Card>
        )}
        {role === "operator" && (
          <Card withBorder radius="lg" p="lg">
            <ThemeIcon size={40} radius="xl" variant="light"><IconActivity size={22} aria-hidden="true" /></ThemeIcon>
            <Title order={3} size="h4" mt="md">Diagnóstico</Title>
            <Text c="dimmed" size="sm" mt="xs">As ferramentas de diagnóstico ainda não estão integradas.</Text>
            <Button component={Link} to="/diagnostico" variant="subtle" mt="md" px={0}>Consultar a secção</Button>
          </Card>
        )}
      </SimpleGrid>
      <Alert color="indigo" variant="light" icon={<IconInfoCircle aria-hidden="true" />}>
        {role === "landlord" ? "Esta vista nunca mostra presença ou hábitos pessoais dos moradores." :
          role === "operator" ? "A vista técnica não permite consultar contas ou dados privados." :
          "A tua vista distingue informações próprias das zonas comuns. Não podes consultar dados pessoais de outros moradores."}
      </Alert>
    </Stack>
  );
}

export default function ContaCertaPage({ section }: { section: SectionId }) {
  const { logout } = useAuth();
  const session = useHouseholdSession();
  const role = session.membership?.role;
  if (!role) return null;
  if (section === "home") return <HomeContent role={role} />;
  if (section === "house") return (
    <Stack gap="xl">
      <PageHeading title="A minha casa" description="Divisões e informações da casa associada à tua conta." />
      <HouseContent />
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
          <Text c="dimmed" size="sm">O acesso é determinado pela tua associação ativa no servidor.</Text>
          <Button color="red" variant="light" onClick={() => void logout()} mt="md" w="fit-content">Terminar sessão</Button>
        </Stack>
      </Card>
      <NoData value={{ title: "Preferências ainda não disponíveis", detail: "As definições persistentes de notificações e privacidade serão integradas pelos módulos responsáveis.", dependency: "Não existem opções de exemplo que aparentem guardar alterações." }} />
    </Stack>
  );
  const placeholder = placeholders[section];
  const description = section === "consumption" && role === "landlord"
    ? "Apenas totais agregados mensais por quarto, sem horários nem perfis individuais."
    : section === "consumption" ? "O teu consumo e a parte comum, sempre com proveniência."
    : section === "appliances" && role === "operator" ? "Diagnóstico de dispositivos sem dados pessoais."
    : section === "bills" && role === "landlord" ? "Gestão de faturas e totais autorizados."
    : section === "notifications" ? "Mensagens dirigidas à tua conta, sem notificações de outros moradores."
    : "Esta área será ligada ao módulo responsável.";
  return <Stack gap="xl">
    <PageHeading title={screenLabels[section]} description={description} />
    <NoData value={placeholder} />
  </Stack>;
}
