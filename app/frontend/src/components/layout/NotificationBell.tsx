import { Anchor, Badge, Button, Loader, Popover, ScrollArea, Text } from "@mantine/core";
import { IconBell } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  listNotifications, markNotificationRead, respondToNotification, type NotificationView,
} from "../../services/notifications/api";

export const NOTIFICATIONS_CHANGED = "conta:notifications-changed";
const when = new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeStyle: "short" });
const MAX = 5;

const isOpenVote = (n: NotificationView) =>
  n.kind === "confirmation_request" && n.can_respond && (n.status === "unread" || n.status === "read");

/** Sino do cabeçalho: abre um painel por cima da página (a página completa fica em «Ver todas»). */
export default function NotificationBell({ householdId, unread, onChanged }: {
  householdId: string; unread: number | null; onChanged: () => void;
}) {
  const [opened, setOpened] = useState(false);
  const [items, setItems] = useState<NotificationView[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    void listNotifications(householdId).then(setItems).catch(() => setItems([]));
  }, [householdId]);
  useEffect(() => { if (opened) load(); }, [opened, load]);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusy(id);
    try { await fn(); } catch { /* o cliente HTTP mostra o erro (ex.: já votaste) */ }
    setBusy(null);
    load();
    onChanged();
    window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
  };

  const shown = [...(items ?? [])]
    .sort((a, b) => Number(isOpenVote(b)) - Number(isOpenVote(a)) || Number(b.status === "unread") - Number(a.status === "unread")
      || new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, MAX);

  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-end" width={400} radius={20} offset={10} withinPortal trapFocus returnFocus>
      <Popover.Target>
        <button type="button" className="conta-bell" aria-label={`Notificações: ${unread ?? 0} por responder`}
          aria-haspopup="dialog" aria-expanded={opened} onClick={() => setOpened((o) => !o)}>
          <IconBell size={20} stroke={2} aria-hidden="true" />
          {!!unread && <span className="conta-bell-count" aria-hidden="true">{unread}</span>}
        </button>
      </Popover.Target>
      <Popover.Dropdown className="conta-notif-panel" aria-label="Notificações">
        <Text fw={700} fz={18} className="conta-notif-head">Notificações</Text>
        <ScrollArea.Autosize mah="min(70dvh, 560px)" type="auto">
          {items === null && <div className="conta-notif-empty" role="status"><Loader size="sm" /> A carregar…</div>}
          {items !== null && shown.length === 0 && <Text c="dimmed" size="sm" className="conta-notif-empty">Sem notificações. Quando houver uma utilização a confirmar ou um aviso de orçamento, aparece aqui.</Text>}
          {shown.map((n) => {
            const vote = isOpenVote(n);
            const quick = n.actions.filter((a) => a.id !== "other");
            const primary = quick.find((a) => a.style === "primary");
            const rest = quick.filter((a) => a !== primary);
            return (
              <article key={n.id} className="conta-notif-item" aria-label={n.title}>
                {vote && <Badge className="conta-pending-badge" w="fit-content">Falta a tua resposta{n.voting ? ` · ${n.voting.votes} de ${n.voting.eligible} já votaram` : ""}</Badge>}
                <Text fw={700} fz={15} mt={vote ? 8 : 0}>{n.title}</Text>
                <Text fz={14} c="dimmed" lineClamp={3} mt={2}>{n.body}</Text>
                {vote && <div className="conta-notif-actions">
                  {primary && <Button fullWidth mih={44} loading={busy === n.id} onClick={() => void act(n.id, () => respondToNotification(householdId, n.id, { action_id: primary.id, target_resident_id: null }))}>{primary.label}</Button>}
                  <div className="conta-notif-actions-row">
                    {rest.map((a) => <Button key={a.id} variant="default" fullWidth mih={44} disabled={busy === n.id}
                      onClick={() => void act(n.id, () => respondToNotification(householdId, n.id, { action_id: a.id, target_resident_id: null }))}>{a.label}</Button>)}
                  </div>
                  <Anchor component={Link} to="/notificacoes" fz={13} c="inherit" onClick={() => setOpened(false)}>Mais opções (É de outra pessoa)</Anchor>
                </div>}
                {!vote && n.can_respond && (n.status === "unread" || n.status === "read") && <Anchor component={Link} to="/notificacoes" fz={14} fw={600} c="inherit" mt={10} display="inline-block" onClick={() => setOpened(false)}>Responder na página</Anchor>}
                {!vote && !n.can_respond && n.status === "unread" && <Button variant="default" mih={40} mt={10} w="fit-content" loading={busy === n.id}
                  onClick={() => void act(n.id, () => markNotificationRead(householdId, n.id))}>Marcar como lida</Button>}
                <Text fz={12} c="dimmed" mt={8}>{when.format(new Date(n.created_at))}</Text>
              </article>
            );
          })}
        </ScrollArea.Autosize>
        <div className="conta-notif-foot">
          <Anchor component={Link} to="/notificacoes" fw={600} fz={14} c="inherit" onClick={() => setOpened(false)}>Ver todas as notificações</Anchor>
        </div>
      </Popover.Dropdown>
    </Popover>
  );
}
