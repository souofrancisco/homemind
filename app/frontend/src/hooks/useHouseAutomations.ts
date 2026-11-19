import { notifications } from "@mantine/notifications";
import { useCallback, useEffect, useState } from "react";
import {
  listAutomations, proposeAutomation, reactivateAutomation, suspendAutomation, voteAutomation,
  type AutomationProposeIn, type AutomationView,
} from "../services/automations/api";

type State = { key: string; rules: AutomationView[] | null };

/** Regras da casa (SAFE-04). Só atualiza a lista com o que o servidor devolve; um erro
 *  (incl. 409 de voto repetido ou limite de propostas) não altera nada e a lista é relida. */
export function useHouseAutomations(householdId: string | undefined) {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!householdId) return;
    let active = true;
    listAutomations(householdId)
      .then((rules) => active && setState({ key: householdId, rules }))
      .catch(() => active && setState({ key: householdId, rules: null }));
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
    busy,
    reload,
    vote: (id: string, approve: boolean) =>
      act(id, () => voteAutomation(householdId!, id, approve), approve ? "Voto a favor registado." : "Voto contra registado."),
    suspend: (id: string) => act(id, () => suspendAutomation(householdId!, id), "Regra suspensa."),
    reactivate: (id: string) => act(id, () => reactivateAutomation(householdId!, id), "Nova votação aberta para reativar a regra."),
    propose: async (body: AutomationProposeIn): Promise<boolean> => {
      setBusy("new");
      try {
        await proposeAutomation(householdId!, body);
        notifications.clean();
        notifications.show({ color: "green", title: "Proposta criada", message: "Ficou registada com o teu voto a favor.", autoClose: 4000 });
        return true;
      } catch { return false; }
      finally { setBusy(null); reload(); }
    },
  };
}
