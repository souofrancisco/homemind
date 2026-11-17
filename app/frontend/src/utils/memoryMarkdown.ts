import type { MemorySnapshot } from "../types/home";

export function memoryMarkdown(memory: MemorySnapshot) {
  return [
    "# ObjectOS — hábitos e privacidade",
    "",
    "> Este resumo contém apenas exemplos da sessão de demonstração. Não representa gostos confirmados nem dados guardados permanentemente.",
    "",
    `- Aprendizagem nesta sessão: ${memory.learningEnabled ? "ativa" : "inativa"}`,
    `- Eventos de exemplo: ${memory.observedEvents.length}`,
    `- Padrões de exemplo: ${memory.inferredPatterns.length}`,
    "",
    "## Padrões de exemplo",
    ...(memory.inferredPatterns.length
      ? memory.inferredPatterns.flatMap((pattern) => [
          `### ${pattern.statement}`,
          `- Frequência: ${pattern.frequency}`,
          `- Período: ${pattern.timeWindow}`,
          "- Evidências:",
          ...pattern.evidence.map((evidence) => `  - ${evidence}`),
          "",
        ])
      : ["Nenhum padrão apresentado nesta sessão.", ""]),
    "## Eventos de exemplo",
    ...(memory.observedEvents.length
      ? memory.observedEvents.map((event) => `- ${new Date(event.occurredAt).toLocaleString("pt-PT")} — ${event.text} [EXEMPLO]`)
      : ["Nenhum evento de exemplo." ]),
    "",
  ].join("\n");
}
