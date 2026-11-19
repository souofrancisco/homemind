import { Badge, Paper, Stack, Text } from "@mantine/core";
import type { AgentMessage } from "../../services/agent/api";

export default function MessageBubble({ message }: { message: AgentMessage & { interpreter?: "llm" | "rules" | null } }) {
  const mine = message.role === "user";
  return (
    <Paper
      p="sm"
      radius="lg"
      maw="min(92%, 46rem)"
      ml={mine ? "auto" : 0}
      bg={mine ? "var(--mantine-primary-color-light)" : "var(--mantine-color-default)"}
      aria-label={mine ? "A tua mensagem" : "Resposta do assistente"}
    >
      <Stack gap={4}>
        <Text style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{message.text}</Text>
        {!mine && message.interpreter && <Badge size="xs" variant="light" color="gray" w="fit-content">
          interpretado por {message.interpreter === "llm" ? "IA" : "regras"}
        </Badge>}
        <Text size="xs" c="dimmed" ta={mine ? "right" : "left"}>
          {new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(new Date(message.ts))}
        </Text>
      </Stack>
    </Paper>
  );
}
