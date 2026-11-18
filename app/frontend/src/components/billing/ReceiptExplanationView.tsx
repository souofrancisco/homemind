import { Accordion, Alert, Badge, Group, Stack, Text, ThemeIcon, Timeline, Title } from "@mantine/core";
import {
  IconAlertCircle, IconBolt, IconCoin, IconFlame, IconGavel, IconHistory, IconMapPin, IconSearch,
} from "@tabler/icons-react";
import type { ReceiptExplanation } from "../../services/billing/api";

// Só apresentação: todos os números e textos vêm do servidor (BILL-05); aqui não se calcula nada.
type Own = ReceiptExplanation["own"][number];
type Group_ = ReceiptExplanation["common"][number];
type Prov = Own["provenance"];

const money = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" });
const eur = (cents: number) => money.format(cents / 100);
const kwh = (wh: number) => `${(wh / 1000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} kWh`;
const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });

const kindLabel = { measured: "medido", estimated: "estimado", inferred: "inferido" } as const;
const originLabel = { real: "REAL", simulated: "SIMULADO" } as const;
const methodLabel: Record<Own["method"], string> = {
  room_rule: "Regra do quarto",
  confirmation: "Pergunta «De quem é esta conta?»",
  presence_rule: "Por quem estava em casa",
  equal_fallback: "Dividido por todos",
  manual: "Correção manual",
};
const actorLabel: Record<Own["decided_by"], string> = {
  system: "decidido pelo sistema",
  me: "decidido por ti",
  housemates: "decidido pela casa",
};
const locationLabel: Record<Own["location"], string> = {
  room: "quarto",
  common: "zona comum",
  unknown: "local desconhecido",
};
const ruleLabel: Record<ReceiptExplanation["common_area_rule"], string> = {
  equal: "dividir por igual",
  ask: "perguntar «De quem é esta conta?»",
  presence: "por presença",
};
const stageIcon = {
  measurement: IconBolt,
  identification: IconSearch,
  location: IconMapPin,
  decision: IconGavel,
  correction: IconHistory,
  allowance: IconFlame,
  share: IconCoin,
} as const;

function ProvBadge({ p }: { p: Prov }) {
  return (
    <Badge size="sm" variant="light" color={p.origin === "simulated" ? "orange" : "teal"}>
      {originLabel[p.origin]} · {kindLabel[p.kind]}
    </Badge>
  );
}

function OwnItem({ item }: { item: Own }) {
  const name = item.appliance_name ?? "Aparelho não identificado";
  return (
    <Accordion.Item value={item.consumption_event_id}>
      <Accordion.Control>
        <Group justify="space-between" wrap="nowrap" pr="sm">
          <Stack gap={0}>
            <Text fw={600}>{name}</Text>
            <Text size="xs" c="dimmed">{when.format(new Date(item.started_at))} · {kwh(item.energy_wh)}</Text>
          </Stack>
          <Text fw={600}>{eur(item.amount_cents)}</Text>
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="sm">
          <Group gap="xs">
            <ProvBadge p={item.provenance} />
            <Badge size="sm" variant="outline">{methodLabel[item.method]} · {actorLabel[item.decided_by]}</Badge>
            {item.corrections > 0 && <Badge size="sm" variant="outline" color="yellow">corrigido</Badge>}
            {item.covered_wh > 0 && <Badge size="sm" variant="light" color="teal">plafond solidário · {kwh(item.covered_wh)}</Badge>}
          </Group>
          <Timeline bulletSize={24} lineWidth={2}>
            {item.steps.map((step, i) => {
              const Icon = stageIcon[step.stage];
              return (
                <Timeline.Item key={i} bullet={<ThemeIcon size={22} radius="xl" variant="light"><Icon size={14} /></ThemeIcon>}>
                  <Text size="sm">{step.text}</Text>
                </Timeline.Item>
              );
            })}
          </Timeline>
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
}

function CommonList({ groups }: { groups: Group_[] }) {
  return (
    <Stack gap={6}>
      {groups.map((g, i) => (
        <Group key={i} justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
          <Stack gap={2}>
            <Text size="sm">{g.appliance_name ?? "Não identificado"}</Text>
            <Text size="xs" c="dimmed">
              {methodLabel[g.method]} · {locationLabel[g.location]} · {g.consumptions} {g.consumptions === 1 ? "vez" : "vezes"} · {kwh(g.energy_wh)} na casa
            </Text>
            <Group gap="xs"><ProvBadge p={g.provenance} /></Group>
          </Stack>
          <Stack gap={0} align="flex-end">
            <Text size="sm" fw={600}>{eur(g.amount_cents)}</Text>
            <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>a tua parte {kwh(g.my_energy_wh)}</Text>
          </Stack>
        </Group>
      ))}
    </Stack>
  );
}

function AllowanceSection({ a }: { a: NonNullable<ReceiptExplanation["allowance"]> }) {
  return (
    <Stack gap="xs">
      <Title order={4} size="h5">Plafond solidário de aquecimento · {eur(a.amount_cents)}</Title>
      <Text size="sm">
        O aquecimento básico de cada quarto é pago por todos. Na casa, {kwh(a.house_covered_wh)} de aquecimento foram cobertos;
        a tua parte igual é {kwh(a.my_share_wh)}.
      </Text>
      {a.limit_wh > 0 && (
        <Text size="sm">
          No teu quarto: {kwh(a.heating_wh)} de aquecimento reconhecido, {kwh(a.covered_wh)} cobertos (limite {kwh(a.limit_wh)} nesta fatura)
          {a.heating_wh > a.covered_wh ? `; os ${kwh(a.heating_wh - a.covered_wh)} acima do limite são teus.` : "."}
        </Text>
      )}
      {a.unproven_consumptions > 0 && (
        <Text size="xs" c="dimmed">
          {a.unproven_consumptions} {a.unproven_consumptions === 1 ? "consumo" : "consumos"} ({kwh(a.unproven_wh)}) no teu quarto sem aparelho identificado não contam para o plafond: sem prova de que é aquecimento, o benefício não se aplica. Registar o aquecedor no catálogo ajuda a reconhecê-lo.
        </Text>
      )}
    </Stack>
  );
}

export default function ReceiptExplanationView({ data }: { data: ReceiptExplanation }) {
  const diff = data.amount_cents - data.equal_split_cents;
  const r = data.residual;
  return (
    <Stack gap="md">
      <Alert variant="light" color={diff > 0 ? "yellow" : "teal"} title="Comparado com a divisão igual">
        Pagas {eur(data.amount_cents)}. Dividindo a fatura por igual pelos {data.residents} moradores pagarias {eur(data.equal_split_cents)}
        {diff === 0 ? ": é igual." : diff > 0 ? `: mais ${eur(diff)}, pelo consumo que é teu.` : `: menos ${eur(-diff)}.`}
      </Alert>

      {!data.evidence_available && (
        <Alert variant="light" color="gray" icon={<IconAlertCircle />}>
          Esta fatura foi fechada antes de se guardar o detalhe de cada consumo. O recibo está certo, mas só se explicam os totais.
        </Alert>
      )}

      <Stack gap="xs">
        <Title order={4} size="h5">O teu consumo · {eur(data.own.reduce((s, i) => s + i.amount_cents, 0))}</Title>
        {data.own.length ? (
          <Accordion variant="separated" radius="md">{data.own.map((item) => <OwnItem key={item.consumption_event_id} item={item} />)}</Accordion>
        ) : (
          <Text size="sm" c="dimmed">Nenhum consumo foi atribuído só a ti nesta fatura.</Text>
        )}
      </Stack>

      <Stack gap="xs">
        <Title order={4} size="h5">Zonas comuns · {eur(data.common.reduce((s, g) => s + g.amount_cents, 0))}</Title>
        <Text size="xs" c="dimmed">A tua parte igual. Regra da sala em vigor: {ruleLabel[data.common_area_rule]}. Não se mostram horas nem quem usou.</Text>
        {data.common.length ? <CommonList groups={data.common} /> : <Text size="sm" c="dimmed">Sem consumos comuns identificados.</Text>}
      </Stack>

      {data.allowance && <AllowanceSection a={data.allowance} />}

      <Stack gap="xs">
        <Title order={4} size="h5">Não atribuído · {eur(r.amount_cents)}</Title>
        <Text size="sm">
          A fatura mediu {kwh(r.bill_wh)}; as tomadas explicam {kwh(r.attributed_wh)}. Os {kwh(r.residual_wh)} restantes
          (aparelhos sem tomada medida, standby, perdas) dividem-se por igual: a tua parte é {kwh(r.my_energy_wh)}.
        </Text>
        {r.undecided_consumptions > 0 && (
          <Text size="sm">
            Inclui {r.undecided_consumptions} {r.undecided_consumptions === 1 ? "consumo" : "consumos"} ({kwh(r.undecided_wh)}) ainda sem decisão no fecho: nunca criam dívida a ninguém.
          </Text>
        )}
        <Group gap="xs"><ProvBadge p={r.provenance} /></Group>
      </Stack>

      <Group justify="space-between">
        <Text size="sm">Termo fixo (parte igual)</Text>
        <Text size="sm">{eur(data.fixed_cents)}</Text>
      </Group>
      <Text size="xs" c="dimmed">
        Preço médio da fatura {(data.price_millicents_per_kwh / 100000).toLocaleString("pt-PT", { minimumFractionDigits: 4 })} €/kWh (sem termo fixo). Todas as contas são feitas no servidor e somam o teu total ao cêntimo.
      </Text>
    </Stack>
  );
}
