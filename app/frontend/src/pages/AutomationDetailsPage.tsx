import { Alert, Button, Card, Group, Loader, Modal, Stack, Switch, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { homeService as service } from "../services/home";
import type { HomeRule } from "../types/home";
import { RuleActions, RuleTrigger } from "../components/automations/AutomationPresentation";


/** Route: /automations/:id */
export function AutomationDetailsPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [rule, setRule] = useState<HomeRule | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleteOpened, deleteModal] = useDisclosure(false);

  useEffect(() => {
    let mounted = true;
    void service.getRules().then((rules) => {
      if (mounted) setRule(rules.find((item) => item.id === id) ?? null);
    }).catch(() => { if (mounted) setFailed(true); }).finally(() => { if (mounted) setLoadedFor(id); });
    return () => { mounted = false; };
  }, [id]);

  const toggle = async (enabled: boolean) => {
    if (!rule) return;
    setBusy(true);
    try { setRule(await service.setRuleEnabled(rule.id, enabled)); }
    catch (error) { notifications.show({ color: "red", title: "Não foi possível atualizar", message: error instanceof Error ? error.message : "Tenta novamente mais tarde." }); }
    finally { setBusy(false); }
  };

  const remove = async () => {
    if (!rule) return;
    setBusy(true);
    try { await service.deleteRule(rule.id); deleteModal.close(); navigate("/automations", { replace: true }); }
    catch (error) { notifications.show({ color: "red", title: "Não foi possível apagar", message: error instanceof Error ? error.message : "Tenta novamente mais tarde." }); }
    finally { setBusy(false); }
  };

  if (loadedFor !== id) return <Group><Loader size="sm" /><Text c="dimmed">A carregar automação…</Text></Group>;
  if (failed) return <Stack><Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button><Alert color="red" title="Automação indisponível">Não foi possível carregar esta automação. Tenta novamente mais tarde.</Alert></Stack>;
  if (!rule) return <Stack><Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button><Alert color="gray" title="Automação não encontrada">Esta automação pode ter sido apagada.</Alert></Stack>;

  return <Stack maw={720} mx="auto" gap="lg">
    <Button variant="subtle" w="fit-content" px={0} onClick={() => navigate("/automations")}>Automações</Button>
    <Group justify="space-between" align="flex-start"><div><Title order={2}>{rule.nome}</Title><Text c="dimmed" mt={4}>{rule.enabled ? "Ativa" : "Inativa"}</Text></div><Switch label={rule.enabled ? "Ativa" : "Inativa"} checked={rule.enabled} disabled={busy} onChange={(event) => void toggle(event.currentTarget.checked)} /></Group>
    <Card withBorder radius="md"><Stack gap="md"><Title order={4}>Quando acontece</Title><RuleTrigger object={rule.objeto} /></Stack></Card>
    <Card withBorder radius="md"><Stack gap="md"><Title order={4}>O que a casa faz</Title><RuleActions rule={rule} /></Stack></Card>
    <Group justify="flex-end"><Button color="red" variant="subtle" onClick={deleteModal.open}>Apagar automação</Button></Group>
    <Modal opened={deleteOpened} onClose={deleteModal.close} title="Apagar automação?" centered>
      <Stack><Text>A automação “{rule.nome}” será removida.</Text><Group justify="flex-end"><Button variant="default" onClick={deleteModal.close}>Cancelar</Button><Button color="red" loading={busy} onClick={() => void remove()}>Apagar</Button></Group></Stack>
    </Modal>
  </Stack>;
}

export default AutomationDetailsPage;
