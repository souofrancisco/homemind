import { Alert, Badge, Button, Card, Group, Loader, NumberInput, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle, IconCalendarEvent, IconUsersGroup } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { getHouseRules, proposeHouseRules, voteHouseRules, withdrawHouseRules, type HouseRulesIn, type HouseRulesView } from "../../services/billing/rules";

// Regras da casa (HOUSE-04): o servidor decide quando valem e conta os votos; aqui só se mostra,
// se propõe e se vota. Uma mudança só fica agendada com a maioria dos moradores.
type Policy = HouseRulesView["current"]["policy"];

const ruleLabel: Record<Policy["common_area_rule"], string> = {
  equal: "Por igual",
  ask: "Perguntar «De quem é esta conta?»",
  presence: "Por presença",
};
const day = new Intl.DateTimeFormat("pt-PT", { dateStyle: "long" });
const fmtDay = (iso: string) => day.format(new Date(`${iso}T12:00:00`));
const eur = (cents: number) => (cents / 100).toLocaleString("pt-PT", { style: "currency", currency: "EUR" });

function PolicyText({ p }: { p: Policy }) {
  return (
    <Text size="sm">
      {ruleLabel[p.common_area_rule]}
      {p.common_area_rule === "ask" && ` · só acima de ${eur(p.ask_threshold_cents)} · sem resposta em ${p.ask_timeout_hours} h → por igual`}
      {p.common_area_rule === "presence" && " · só de quem estava sozinho em casa, sem visitas; na dúvida, por igual"}
    </Text>
  );
}

export default function HouseRulesCard({ householdId, canEdit }: { householdId: string; canEdit: boolean }) {
  const [data, setData] = useState<HouseRulesView | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<HouseRulesIn | null>(null);

  useEffect(() => {
    let active = true;
    getHouseRules(householdId)
      .then((v) => { if (active) { setData(v); setError(false); } })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [householdId]);

  if (error) return <Alert color="red" icon={<IconAlertCircle />}>Não foi possível consultar as regras da casa.</Alert>;
  if (!data) return <Group gap="sm" role="status"><Loader size="sm" /><Text>A carregar as regras…</Text></Group>;

  const run = (work: Promise<HouseRulesView>) => {
    setBusy(true);
    work.then((v) => { setData(v); setDraft(null); }).catch(() => undefined).finally(() => setBusy(false));
  };
  const proposal = data.proposal;
  const start = () => {
    const p = (proposal ?? data.upcoming ?? data.current).policy;
    setDraft({ ...p });
  };

  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap="sm">
        <Title order={3} size="h4">Regras da casa · zonas comuns</Title>
        <Text size="xs" c="dimmed">O quarto é sempre de quem lá mora. Esta regra decide o que se faz ao consumo da sala e da cozinha.</Text>
        <Stack gap={2}>
          <Text size="xs" c="dimmed">Em vigor{data.current.effective_from ? ` desde ${fmtDay(data.current.effective_from)}` : ""}</Text>
          <PolicyText p={data.current.policy} />
        </Stack>
        {data.upcoming?.effective_from && (
          <Alert variant="light" color="gray" icon={<IconCalendarEvent />} title={`Muda a ${fmtDay(data.upcoming.effective_from)}`}>
            <Stack gap="xs">
              <PolicyText p={data.upcoming.policy} />
              <Text size="xs" c="dimmed">Aprovada pela maioria dos moradores. Para a desfazer, propõe outra regra.</Text>
            </Stack>
          </Alert>
        )}
        {proposal && (
          <Alert variant="light" color="yellow" icon={<IconUsersGroup />} title={`Proposta para ${fmtDay(proposal.effective_from)} · ${proposal.approvals} de ${proposal.needed} aprovações necessárias`}>
            <Stack gap="xs">
              <PolicyText p={proposal.policy} />
              <Text size="xs" c="dimmed">
                {proposal.eligible} moradores · {proposal.approvals} a favor · {proposal.rejections} contra. Sem maioria até {fmtDay(proposal.effective_from)}, nada muda.
              </Text>
              {canEdit && (
                <Group gap="xs">
                  {proposal.my_vote !== true && <Button className="conta-keep-color" size="xs" color="green" loading={busy} onClick={() => run(voteHouseRules(householdId, true))}>Aprovar</Button>}
                  {proposal.my_vote !== false && !proposal.proposed_by_me && <Button size="xs" variant="light" color="red" loading={busy} onClick={() => run(voteHouseRules(householdId, false))}>Rejeitar</Button>}
                  {proposal.proposed_by_me && <Button size="xs" variant="subtle" color="red" loading={busy} onClick={() => run(withdrawHouseRules(householdId))}>Retirar proposta</Button>}
                  {proposal.my_vote != null && <Badge variant="outline">{proposal.my_vote ? "Aprovaste" : "Rejeitaste"}</Badge>}
                </Group>
              )}
            </Stack>
          </Alert>
        )}
        {canEdit && !draft && (
          <Button variant="light" w="fit-content" onClick={start}>{proposal ? "Fazer outra proposta" : `Propor mudança para ${fmtDay(data.next_change_from)}`}</Button>
        )}
        {canEdit && draft && (
          <Stack gap="sm">
            <SegmentedControl
              fullWidth
              value={draft.common_area_rule}
              onChange={(v) => setDraft({ ...draft, common_area_rule: v as HouseRulesIn["common_area_rule"] })}
              data={[
                { value: "ask", label: "Perguntar" },
                { value: "equal", label: "Por igual" },
                { value: "presence", label: "Por presença" },
              ]}
            />
            {draft.common_area_rule === "ask" && (
              <Group grow align="flex-start">
                <NumberInput label="Perguntar acima de (€)" decimalScale={2} min={0} step={0.1} value={draft.ask_threshold_cents / 100}
                  onChange={(v) => setDraft({ ...draft, ask_threshold_cents: Math.round(Number(v || 0) * 100) })} />
                <NumberInput label="Prazo para responder (h)" min={1} max={168} value={draft.ask_timeout_hours}
                  onChange={(v) => setDraft({ ...draft, ask_timeout_hours: Math.min(168, Math.max(1, Math.round(Number(v || 1)))) })} />
              </Group>
            )}
            <Text size="xs" c="dimmed">Vale a partir de {fmtDay(data.next_change_from)}. O mês em curso e as faturas fechadas não mudam. Só muda se pelo menos metade dos moradores aprovar (a tua proposta conta como «sim»); toda a casa é avisada.</Text>
            <Group gap="xs">
              <Button loading={busy} onClick={() => run(proposeHouseRules(householdId, draft))}>Propor à casa</Button>
              <Button variant="subtle" onClick={() => setDraft(null)}>Cancelar</Button>
            </Group>
          </Stack>
        )}
        {data.history.length > 1 && (
          <Group gap="xs">
            <Text size="xs" c="dimmed">Histórico:</Text>
            {data.history.slice(1).map((v) => (
              <Badge key={v.effective_from ?? "inicial"} variant="outline" size="sm">
                {v.effective_from ? fmtDay(v.effective_from) : "inicial"} · {ruleLabel[v.policy.common_area_rule]}
              </Badge>
            ))}
          </Group>
        )}
      </Stack>
    </Card>
  );
}
