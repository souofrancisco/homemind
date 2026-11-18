-- Propostas de mudança da regra da sala e os votos (dono: billing, HOUSE-04). Uma proposta só
-- vira versão (`billing_policy_version`) com a aprovação de pelo menos metade dos moradores com
-- contrato ativo. No máximo uma aberta por casa. Os votos não saem da casa por pessoa: a API só
-- devolve contagens e o voto do próprio.
CREATE TABLE billing_rule_proposal (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  effective_from TEXT NOT NULL CHECK (effective_from LIKE '____-__-01'),
  common_area_rule TEXT NOT NULL CHECK (common_area_rule IN ('equal', 'ask', 'presence')),
  ask_threshold_cents INTEGER NOT NULL CHECK (ask_threshold_cents >= 0),
  ask_timeout_hours INTEGER NOT NULL CHECK (ask_timeout_hours BETWEEN 1 AND 168),
  proposed_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  proposed_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN ('open', 'approved', 'rejected', 'withdrawn', 'superseded', 'expired')
  ),
  decided_at TEXT
);
CREATE UNIQUE INDEX billing_rule_proposal_one_open
  ON billing_rule_proposal (household_id) WHERE status = 'open';

CREATE TABLE billing_rule_vote (
  proposal_id TEXT NOT NULL REFERENCES billing_rule_proposal(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  approve INTEGER NOT NULL CHECK (approve IN (0, 1)),
  voted_at TEXT NOT NULL,
  PRIMARY KEY (proposal_id, resident_id)
);
