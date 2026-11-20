import { Alert, Anchor, Progress, SimpleGrid, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { usePolling } from "../hooks/usePolling";
import { getMyBudget } from "../services/billing/budget";
import { listNotifications } from "../services/notifications/api";
import { getMembers, type MemberView } from "../services/households/api";
import { euro, StatCard, useEnergy } from "./EnergyPage";
import { NOTIFICATIONS_CHANGED } from "../components/layout/NotificationBell";
import { NotificationCard } from "./NotificationsPage";

/** Dashboard do morador: só junta o que o servidor já calculou; "Sem dados" quando falta. */
export default function Dashboard() {
  const session = useHouseholdSession();
  const id = session.membership?.household_id;
  const { energy } = useEnergy();
  const budget = usePolling(id, getMyBudget, 60000);
  const notes = usePolling(id, listNotifications, 30000);
  const [members, setMembers] = useState<MemberView[]>([]);
  useEffect(() => {
    if (!id || session.membership?.role !== "tenant") return;
    let active = true;
    void getMembers(id).then((all) => active && setMembers(all.filter((m) => m.role === "tenant" && m.status === "active"))).catch(() => active && setMembers([]));
    return () => { active = false; };
  }, [id, session.membership?.role]);
  const reloadNotes = notes.reload;
  useEffect(() => {
    window.addEventListener(NOTIFICATIONS_CHANGED, reloadNotes);
    return () => window.removeEventListener(NOTIFICATIONS_CHANGED, reloadNotes);
  }, [reloadNotes]);
  const pending = (notes.data ?? []).filter((n) => n.kind === "confirmation_request" && n.can_respond && (n.status === "unread" || n.status === "read"));
  const b = budget.data;
  const pendingVote = pending.find((n) => n.kind === "confirmation_request");
  const limit = b?.budget?.limit_cents ?? null;

  return (
    <Stack gap={28}>
      {(energy.offline || notes.offline) && <Alert color="yellow" title="Sem ligação — a mostrar os últimos dados recebidos" />}
      {pendingVote && id && <Stack gap="xs">
        <NotificationCard n={pendingVote} householdId={id} members={members} onChange={() => notes.reload()} />
        {pending.length > 1 && <Text size="sm" c="dimmed">+ {pending.length - 1} por responder em <Anchor component={Link} to="/notificacoes" c="inherit">Notificações</Anchor></Text>}
      </Stack>}
      <SimpleGrid cols={2} spacing={{ base: "sm", md: 20 }}>
        <StatCard label="Este mês" value={!b ? "Sem dados" : b.spent_cents == null ? "Desconhecido" : euro(b.spent_cents)}
          caption={b?.forecast ? `previsão de ${euro(b.forecast.cents)} no fim do mês` : "até agora"} />
        <StatCard label={limit ? `Orçamento de ${euro(limit)}` : "Orçamento"}
          value={!b ? "Sem dados" : !limit ? "Sem orçamento" : b.pct == null ? "Desconhecido" : `${b.pct} %`} small={!limit}
          caption={!b || limit ? undefined : <Anchor component={Link} to="/contas" c="inherit">Definir em Contas</Anchor>}>
          {limit != null && b?.pct != null && <Progress color="ink" size={8} mt="sm" value={Math.min(b.pct, 100)} aria-label="Percentagem do orçamento utilizada" />}
        </StatCard>
      </SimpleGrid>
    </Stack>
  );
}
