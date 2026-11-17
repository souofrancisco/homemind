import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { demoSuggestionDecisions, demoSuggestions } from "../mocks/suggestions";
import { homeService } from "../services/home";
import { useHome } from "./useHome";

/** Sugestões: só existem em demonstração; decisões vivem apenas durante a sessão. */
export function useSuggestions() {
  const { source } = useHome();
  const [, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const available = source === "mock";
  const suggestions = available ? demoSuggestions.filter((item) => !demoSuggestionDecisions.has(item.id)) : [];

  const ignore = (id: string) => { demoSuggestionDecisions.add(id); setVersion((version) => version + 1); };

  /** Guarda a regra proposta (inativa). Resolve `true` se guardou. */
  const accept = async (id: string) => {
    const suggestion = demoSuggestions.find((item) => item.id === id);
    if (!suggestion) return false;
    setBusy(true);
    try {
      await homeService.saveRule(suggestion.proposedRule);
      ignore(id);
      notifications.show({ color: "teal", message: "Sugestão guardada como inativa. Nenhum dispositivo foi acionado." });
      return true;
    } catch (error) {
      notifications.show({ color: "red", title: "Não foi possível guardar", message: error instanceof Error ? error.message : "Tenta novamente mais tarde." });
      return false;
    } finally { setBusy(false); }
  };

  return { available, suggestions, find: (id: string) => available ? demoSuggestions.find((item) => item.id === id) : undefined, busy, ignore, accept };
}
