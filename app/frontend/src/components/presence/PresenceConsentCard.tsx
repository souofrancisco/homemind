import { Alert, Badge, Button, Card, Divider, Group, Loader, Modal, Stack, Switch, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import {
  exportMyPresence, getConsents, grantConsent, revokeConsent, setPresenceOptIn,
  type ConsentLogEntry, type PresenceConsents, type SourceConsent,
} from "../../services/presence/api";

const dt = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });
const SUBJECT: Record<ConsentLogEntry["subject"], string> = {
  presence_opt_in: "Partilha da presença", wifi: "Wi-Fi do telemóvel", appliance: "Aparelho pessoal a ligar", manual: "Respostas a «Estás em casa?»",
};
const REASON: Record<string, string> = { resident: "por ti", opt_in_revoked: "ao desligar a partilha da presença", left_household: "ao saíres da casa" };

type Pending = { kind: "grant"; source: SourceConsent } | { kind: "revoke"; source: SourceConsent } | { kind: "global"; value: boolean };

/** PRIV-03 #51: consentimento por fonte de presença. Tudo desligado por omissão; cada fonte liga-se e desliga-se à parte. Só do próprio. */
export default function PresenceConsentCard({ householdId, membershipId }: { householdId: string; membershipId: string }) {
  const [result, setResult] = useState<{ key: string; data: PresenceConsents | null } | null>(null);
  const [tick, setTick] = useState(0);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getConsents(householdId)
      .then((v) => { if (active) setResult({ key: householdId, data: v }); })
      .catch(() => { if (active) setResult({ key: householdId, data: null }); });
    return () => { active = false; };
  }, [householdId, tick]);
  const current = result?.key === householdId ? result : null;
  const data = current?.data ?? null;
  const status = current === null ? "loading" : data ? "ready" : "error";
  const load = () => { setResult(null); setTick((n) => n + 1); };
  const setData = (v: PresenceConsents) => setResult({ key: householdId, data: v });

  const confirm = async () => {
    if (!pending || !data) return;
    setBusy(true);
    try {
      if (pending.kind === "grant") {
        setData(await grantConsent(householdId, pending.source.source, data.text_version));
        notifications.show({ color: "green", title: "Fonte ligada", message: `${pending.source.title}: podes desligar quando quiseres.`, autoClose: 5000 });
      } else if (pending.kind === "revoke") {
        const r = await revokeConsent(householdId, pending.source.source);
        notifications.show({ color: "green", title: "Fonte desligada", message: `${pending.source.title}: ${r.erased_cues} pistas apagadas. As outras fontes mantêm-se.`, autoClose: 6000 });
        load();
      } else {
        await setPresenceOptIn(householdId, membershipId, pending.value);
        notifications.show({ color: "green", title: pending.value ? "Partilha ligada" : "Partilha desligada", message: pending.value ? "Escolhe agora que fontes queres ligar." : "Os teus dados de presença vão ser apagados.", autoClose: 6000 });
        load();
      }
      setPending(null);
    } catch { /* o cliente já mostrou o motivo do servidor; mantém-se o diálogo para tentar de novo */ }
    finally { setBusy(false); }
  };

  const download = async () => {
    try {
      const body = await exportMyPresence(householdId);
      const url = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url; a.download = "os-meus-dados-de-presenca.json"; a.click();
      URL.revokeObjectURL(url);
    } catch { /* o cliente já mostrou o erro */ }
  };

  if (status === "loading") return <Group role="status"><Loader size="sm" /><Text>A carregar as tuas opções de privacidade…</Text></Group>;
  if (status === "error" || !data) {
    return (
      <Alert color="red" icon={<IconAlertCircle />} title="Não foi possível consultar as tuas opções de privacidade">
        <Button w="fit-content" color="red" variant="light" onClick={load}>Tentar novamente</Button>
      </Alert>
    );
  }
  const on = data.presence_opt_in;
  const globalValue = pending?.kind === "global" ? pending.value : false;
  const dialogTitle = !pending ? "" : pending.kind === "global" ? (globalValue ? "Partilhar a minha presença" : "Desligar a partilha da presença")
    : pending.kind === "grant" ? `Ligar: ${pending.source.title}` : `Desligar: ${pending.source.title}`;
  return (
    <Card p={{ base: "md", sm: 28 }} maw={640} aria-labelledby="presence-consent-title">
      <Stack gap={16}>
        <Title id="presence-consent-title" order={2} size={20}>Presença e privacidade</Title>
        <Text size="sm" c="dimmed">Tudo começa desligado. Só tu vês as tuas pistas e o teu estado; os colegas e o senhorio não. Escolhes fonte a fonte e podes desligar quando quiseres. A câmara da porta só conta pessoas, não identifica ninguém e não tem opção individual.</Text>
        <Switch checked={on} onChange={(e) => setPending({ kind: "global", value: e.currentTarget.checked })} label="Partilhar a minha presença (em casa / fora)" description="Sem isto nenhuma fonte recolhe nada. Ao desligar, apagam-se todos os teus dados de presença." size="md" />
        <Divider />
        {data.sources.map((s) => (
          <Stack key={s.source} gap={6}>
            <Group justify="space-between" wrap="wrap">
              <Title order={3} size={16}>{s.title}</Title>
              <Group gap="xs">
                <Badge color={s.enabled ? "teal" : "gray"} variant="light">{s.enabled ? "Ligada" : "Desligada"}</Badge>
                {s.enabled
                  ? <Button variant="default" mih={44} onClick={() => setPending({ kind: "revoke", source: s })}>Desligar</Button>
                  : <Button mih={44} disabled={!on} onClick={() => setPending({ kind: "grant", source: s })}>Ligar</Button>}
              </Group>
            </Group>
            <Text size="sm"><b>O que se recolhe.</b> {s.collects}</Text>
            <Text size="sm"><b>Quem vê.</b> {s.who_sees}</Text>
            <Text size="sm"><b>Como revogar.</b> {s.how_to_revoke}</Text>
            {!on && !s.enabled && <Text size="xs" c="dimmed">Liga primeiro a partilha da presença.</Text>}
          </Stack>
        ))}
        <Divider />
        <Stack gap={6}>
          <Title order={3} size={16}>O meu registo</Title>
          {data.history.length === 0 ? <Text size="sm" c="dimmed">Ainda não há registo: não ligaste nada.</Text> : (
            <Stack gap={2} component="ul" m={0} pl="md">
              {[...data.history].reverse().map((h, i) => (
                <Text component="li" size="sm" key={`${h.at}-${i}`}>
                  {dt.format(new Date(h.at))} · {SUBJECT[h.subject]} {h.action === "granted" ? "ligada" : "desligada"}{h.reason ? ` (${REASON[h.reason] ?? h.reason})` : ""}{h.text_version !== "n/a" ? ` · texto ${h.text_version}` : ""}
                </Text>
              ))}
            </Stack>
          )}
        </Stack>
        <Group>
          <Button variant="default" mih={44} onClick={() => void download()}>Descarregar os meus dados</Button>
        </Group>
        <Text size="xs" c="dimmed">Prazos de conservação (proposta, ainda por validar) e base legal estão por decidir; esta página não é um parecer jurídico.</Text>
      </Stack>
      <Modal opened={pending !== null} onClose={() => !busy && setPending(null)} title={dialogTitle} centered>
        {pending && (
          <Stack gap="md">
            {pending.kind === "grant" && <><Text size="sm">{pending.source.collects}</Text><Text size="sm">{pending.source.who_sees}</Text><Text size="sm">{pending.source.how_to_revoke}</Text></>}
            {pending.kind === "revoke" && <Text size="sm">Os dados desta fonte são apagados já. As outras fontes e o teu estado (recalculado com o que sobra) mantêm-se. Não toca em contas nem em dados dos teus colegas.</Text>}
            {pending.kind === "global" && <Text size="sm">{globalValue ? "Isto só permite escolher fontes; não liga nenhuma. Cada fonte tem o seu próprio consentimento." : "Todas as fontes são desligadas e os teus dados de presença (pistas, estado, telemóveis) são apagados. Não toca em contas nem em dados dos teus colegas."}</Text>}
            <Group justify="flex-end">
              <Button variant="default" mih={44} onClick={() => setPending(null)} disabled={busy}>Cancelar</Button>
              <Button mih={44} loading={busy} onClick={() => void confirm()}>{pending.kind === "grant" ? "Aceito e ligo" : pending.kind === "revoke" ? "Desligar e apagar" : globalValue ? "Partilhar" : "Desligar e apagar"}</Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Card>
  );
}
