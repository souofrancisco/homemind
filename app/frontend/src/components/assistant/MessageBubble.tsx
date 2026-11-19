import { Badge, Paper, Stack, Text } from "@mantine/core";
import type { AgentMessage } from "../../services/agent/api";

export default function MessageBubble({ message }: { message: AgentMessage & { interpreter?: "llm" | "rules" | null } }) {
  const mine = message.role === "user";
  return (
    <Paper
      p="12px 18px"
      radius={mine ? "20px 20px 4px 20px" : "20px 20px 20px 4px"}
      maw="min(92%, 46rem)"
      ml={mine ? "auto" : 0}
      bg={mine ? "light-dark(#16181d, #f3f4f6)" : "light-dark(#f4f4f1, #0e0f12)"}
      c={mine ? "light-dark(#ffffff, #0e0f12)" : undefined}
      shadow="none"
      aria-label={mine ? "A tua mensagem" : "Resposta do assistente"}
    >
      <Stack gap={4}>
        <Text style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{message.text}</Text>
        {!mine && message.interpreter && <Badge size="xs" variant="light" color="gray" w="fit-content">
          interpretado por {message.interpreter === "llm" ? "IA" : "regras"}
        </Badge>}
        <Text size="xs" c={mine ? "inherit" : "dimmed"} opacity={mine ? 0.75 : 1} ta={mine ? "right" : "left"}>
          {new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(new Date(message.ts))}
        </Text>
      </Stack>
    </Paper>
  );
}
