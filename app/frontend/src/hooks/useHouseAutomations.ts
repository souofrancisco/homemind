import { notifications } from "@mantine/notifications";
import { useCallback, useEffect, useState } from "react";
import {
  listAutomationPlugs, listAutomations, proposeAutomation, reactivateAutomation, suspendAutomation, voteAutomation,
  type AutomationPlugView, type AutomationProposeIn, type AutomationView,
} from "../services/automations/api";

type State = { key: string; rules: AutomationView[] | null; plugs: AutomationPlugView[] };

/** Regras da casa e regras individuais (SAFE-04). Só atualiza a lista com o que o servidor devolve; um erro
 *  (incl. 409 de voto repetido ou limite de propostas) não altera nada e a lista é relida. */
export function useHouseAutomations(householdId: string | undefined) {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!householdId) return;
    let active = true;
    // As tomadas vêm do servidor (as que ele aceita numa regra); sem elas o formulário fica vazio.
    Promise.all([listAutomations(householdId), listAutomationPlugs(householdId).catch(() => [])])
      .then(([rules, plugs]) => active && setState({ key: householdId, rules, plugs }))
      .catch(() => active && setState({ key: householdId, rules: null, plugs: [] }));
    return () => { active = false; };
  }, [householdId, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  const act = useCallback(async (id: string, run: () => Promise<unknown>, done: string) => {
    setBusy(id);
    try {
      await run();
      notifications.clean();
      notifications.show({ color: "green", title: "Feito", message: done, autoClose: 4000 });
    } catch { /* o cliente já mostrou o motivo do servidor */ }
    finally { setBusy(null); reload(); }
  }, [reload]);

  const cur = householdId && state?.key === householdId ? state : null;
  return {
    loading: !cur,
    rules: cur?.rules ?? null,
    plugs: cur?.plugs ?? [],
    busy,
    reload,
    vote: (id: string, approve: boolean) =>
      act(id, () => voteAutomation(householdId!, id, approve), approve ? "Voto a favor registado." : "Voto contra registado."),
    suspend: (id: string) => act(id, () => suspendAutomation(householdId!, id), "Regra suspensa."),
    reactivate: (rule: AutomationView) =>
      act(rule.id, () => reactivateAutomation(householdId!, rule.id),
        rule.scope === "personal" ? "Regra reativada." : "Nova votação aberta para reativar a regra."),
    propose: async (body: AutomationProposeIn): Promise<boolean> => {
      setBusy("new");
      try {
        await proposeAutomation(householdId!, body);
        notifications.clean();
        notifications.show(body.scope === "personal"
          ? { color: "green", title: "Regra criada", message: "Já está ativa e só tu a vês.", autoClose: 4000 }
          : { color: "green", title: "Proposta criada", message: "Ficou registada com o teu voto a favor.", autoClose: 4000 });
        return true;
      } catch { return false; }
      finally { setBusy(null); reload(); }
    },
  };
}
