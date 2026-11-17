import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import { homeService } from "../services/home";
import type { HomeRule, RuleDraft } from "../types/home";

const message = (error: unknown) => error instanceof Error ? error.message : "Tenta novamente mais tarde.";
const fail = (title: string, error: unknown) => notifications.show({ color: "red", title, message: message(error) });

/** Regras guardadas: carregamento, ativar/desativar e apagar. */
export function useRules() {
  const [rules, setRules] = useState<HomeRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let mounted = true;
    void homeService.getRules().then((items) => { if (mounted) setRules(items); }).catch(() => { if (mounted) setFailed(true); }).finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const toggle = async (rule: HomeRule, enabled: boolean) => {
    setBusy(true);
    try {
      const updated = await homeService.setRuleEnabled(rule.id, enabled);
      setRules((items) => items.map((item) => item.id === rule.id ? updated : item));
    } catch (error) { fail("Não foi possível atualizar", error); }
    finally { setBusy(false); }
  };

  /** Resolve `true` se a regra foi apagada. */
  const remove = async (rule: HomeRule) => {
    setBusy(true);
    try {
      await homeService.deleteRule(rule.id);
      setRules((items) => items.filter((item) => item.id !== rule.id));
      return true;
    } catch (error) { fail("Não foi possível apagar", error); return false; }
    finally { setBusy(false); }
  };

  return { rules, loading, failed, busy, toggle, remove };
}

/** Criação de uma regra: proposta a partir de texto e gravação (sempre inativa). */
export function useNewRule() {
  const [proposal, setProposal] = useState<{ draft: RuleDraft; summary?: string } | null>(null);
  const [proposalError, setProposalError] = useState("");
  const [busy, setBusy] = useState(false);

  const propose = async (text: string) => {
    setBusy(true);
    setProposalError("");
    try {
      const result = await homeService.proposeRule(text.trim());
      setProposal({ draft: result.proposal, summary: result.summary });
    } catch {
      setProposal(null);
      setProposalError("Não foi possível criar a proposta. Podes escolher um exemplo para começar.");
    } finally { setBusy(false); }
  };

  /** Resolve a regra guardada, ou `null` se falhou. */
  const save = async (draft: RuleDraft) => {
    setBusy(true);
    try {
      const saved = await homeService.saveRule(draft);
      notifications.show({ color: "teal", message: "Automação guardada e inativa. Nenhum dispositivo foi acionado." });
      return saved;
    } catch (error) { fail("Não foi possível guardar", error); return null; }
    finally { setBusy(false); }
  };

  /** Começar a partir de um rascunho já pronto (exemplo). */
  const startFrom = (draft: RuleDraft) => { setProposal({ draft }); setProposalError(""); };
  const discard = () => setProposal(null);

  return { proposal, proposalError, busy, propose, save, startFrom, discard };
}
