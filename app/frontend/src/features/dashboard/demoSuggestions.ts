import type { RoutineSuggestion } from "./types";

export const demoSuggestions: RoutineSuggestion[] = [
  {
    id: "pattern-reading-evening", title: "Uma leitura tranquila à noite", explanation: "O modo Leitura apareceu várias vezes em eventos de demonstração no mesmo período horário.",
    statement: "O modo Leitura costuma ser ativado entre as 21h e as 22h.", frequency: "4 de 5 dias", timeWindow: "21:00–22:00",
    evidence: ["Livro levantado · 21:12 · SIMULADO", "Gesto validado · 21:12 · SIMULADO", "Modo Leitura ativado · 21:13 · SIMULADO"], simulated: true,
    proposedRule: { id: "suggested-reading-time", objeto: "livro", nome: "Leitura à noite", acoes: [{ dispositivo: "lâmpada", ligada: true, cor: "branco quente", brilho: 40 }] },
  },
  {
    id: "pattern-coffee-entry", title: "Café após a chegada", explanation: "Nos eventos de exemplo, a deteção de presença foi seguida pela caneca em menos de dois minutos.",
    statement: "Após a entrada na divisão, o modo Café é ativado com frequência.", frequency: "4 ocorrências observadas", timeWindow: "Manhã · após entrada",
    evidence: ["Presença detetada · 08:32 · SIMULADO", "Caneca levantada · 08:33 · SIMULADO", "Modo Café ativado · 08:33 · SIMULADO"], simulated: true,
    proposedRule: { id: "suggested-coffee-arrival", objeto: "caneca", nome: "Café após chegada", acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 70 }] },
  },
  {
    id: "pattern-cinema-weekend", title: "Cinema ao fim de semana", explanation: "O modo Cinema surge repetidamente em exemplos de eventos de fim de semana.",
    statement: "O modo Cinema é frequentemente utilizado ao fim de semana.", frequency: "3 fins de semana", timeWindow: "Sexta a domingo · noite",
    evidence: ["Comando levantado · sábado 20:47 · SIMULADO", "Gesto validado · sábado 20:47 · SIMULADO", "Modo Cinema ativado · sábado 20:48 · SIMULADO"], simulated: true,
    proposedRule: { id: "suggested-cinema-weekend", objeto: "comando", nome: "Cinema ao fim de semana", acoes: [{ dispositivo: "lâmpada", ligada: true, brilho: 15 }] },
  },
];

// Decisões válidas apenas durante a sessão de demonstração; não são memória persistente.
export const demoSuggestionDecisions = new Set<string>();
