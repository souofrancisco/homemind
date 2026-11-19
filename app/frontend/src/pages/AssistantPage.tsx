import { Alert, Button, Card, Group, Loader, ScrollArea, Stack, Text, Textarea, Title } from "@mantine/core";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import ActionCard from "../components/assistant/ActionCard";
import MessageBubble from "../components/assistant/MessageBubble";
import { useHouseholdSession } from "../app/providers/HouseholdProvider";
import { listAgentMessages, listProposedActions, sendAgentMessage, type AgentActionView, type AgentMessage } from "../services/agent/api";

const SUGGESTIONS = ["Quanto gastei este mês?", "Como vai o meu orçamento?", "Como está o meu recibo?", "Qual foi o aparelho que mais gastou?", "Porque pago este valor?", "Tenho pedidos por responder?"];

export default function AssistantPage() {
  const householdId = useHouseholdSession().membership?.household_id;
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [actions, setActions] = useState<AgentActionView[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<"history" | "send" | null>(null);
  const [retryText, setRetryText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!householdId) return;
    setLoading(true);
    setError(null);
    try {
      const [history, pending] = await Promise.all([
        listAgentMessages(householdId),
        listProposedActions(householdId),
      ]);
      setMessages(history);
      setActions(pending);
    } catch {
      setError("history");
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [messages, sending]);

  async function submit(text: string) {
    const clean = text.trim();
    if (!householdId || !clean || sending) return;
    setDraft("");
    setSending(true);
    setError(null);
    setRetryText(clean);
    try {
      const response = await sendAgentMessage(householdId, { text: clean });
      const [history, pending] = await Promise.all([listAgentMessages(householdId), listProposedActions(householdId)]);
      let latestAssistant = -1;
      for (let index = history.length - 1; index >= 0; index -= 1) {
        if (history[index].role === "assistant") { latestAssistant = index; break; }
      }
      setMessages(history.map((message, index) => index === latestAssistant
        ? { ...message, interpreter: response.interpreter }
        : message));
      setActions(pending);
      setRetryText("");
    } catch {
      setError("send");
    } finally {
      setSending(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit(draft);
    }
  }

  function updateAction(value: AgentActionView) {
    setActions((all) => all.map((action) => action.action.id === value.action.id ? value : action));
  }

  return (
    <Stack gap={24} w="100%">
      <div className="conta-page-head">
        <Title order={1} className="conta-page-title">Assistente</Title>
        <Text c="dimmed" fz={16} mt={6}>Só responde com números calculados pela Conta Certa. Pedidos de ação pedem a tua confirmação.</Text>
      </div>
      <Card p={{ base: "md", sm: "24px 28px" }}>
        <ScrollArea h={{ base: "52vh", sm: "max(320px, calc(100dvh - 400px))" }} type="auto" offsetScrollbars>
          <Stack gap="sm" p="xs" aria-live="polite" aria-relevant="additions text">
            {loading && <Group role="status"><Loader size="sm" /><Text>A carregar a conversa…</Text></Group>}
            {error === "history" && <Alert color="red" role="alert" title="Não foi possível carregar a conversa">
              <Button size="xs" variant="light" color="red" onClick={() => void load()}>Tentar novamente</Button>
            </Alert>}
            {!loading && !error && messages.length === 0 && <Stack gap="xs" py="md">
              <Text c="dimmed" size="sm">Podes perguntar, por exemplo:</Text>
              <Group gap={10}>{SUGGESTIONS.map((suggestion) => <Button key={suggestion} variant="default" mih={44} fw={500} onClick={() => void submit(suggestion)}>{suggestion}</Button>)}</Group>
            </Stack>}
            {messages.map((message) => <MessageBubble key={message.id} message={message} />)}
            {actions.map((action) => <ActionCard key={action.action.id} householdId={householdId ?? ""} value={action} onChange={updateAction} />)}
            {sending && <Group role="status" aria-label="O assistente está a escrever"><Loader size="xs" /><Text size="sm" c="dimmed">A escrever…</Text></Group>}
            {error === "send" && <Alert color="red" role="alert" title="A mensagem não pôde ser confirmada">
              <Button size="xs" variant="light" color="red" disabled={!retryText} onClick={() => void submit(retryText)}>Repetir envio</Button>
            </Alert>}
            <div ref={endRef} />
          </Stack>
        </ScrollArea>
        <form onSubmit={onSubmit}>
          <Group align="flex-end" mt="sm" wrap="nowrap" gap={12}>
            <Textarea
              aria-label="Escreve uma mensagem ao assistente"
              placeholder="Escreve a tua pergunta…"
              value={draft}
              onChange={(event) => setDraft(event.currentTarget.value)}
              onKeyDown={onKeyDown}
              maxLength={2000}
              minRows={1}
              maxRows={5}
              autosize
              disabled={loading || sending || !householdId}
              style={{ flex: 1 }}
              styles={{ input: { borderRadius: 26, minHeight: 52, padding: "14px 22px", fontSize: 15 } }}
            />
            <Button type="submit" aria-label="Enviar mensagem" disabled={!draft.trim() || loading || sending} loading={sending} mih={52} px={24} fw={700}>
              Enviar
            </Button>
          </Group>
          <Text ta="right" size="xs" c="dimmed" mt={4}>{draft.length}/2000 · Enter envia; Shift+Enter cria uma linha</Text>
        </form>
      </Card>
    </Stack>
  );
}
