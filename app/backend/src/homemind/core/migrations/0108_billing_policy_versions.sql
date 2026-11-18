-- Regras da casa versionadas (dono: billing, HOUSE-04). Cada linha é a política que vale a partir
-- de `effective_from` (dia 1 de um mês, no fuso da casa) até à versão seguinte. Antes da primeira
-- versão vale a política inicial de `household` (definida na criação da casa). Uma versão que já
-- começou a valer nunca muda nem se apaga: só a que ainda não começou pode ser substituída ou
-- cancelada (nada foi decidido com ela).
CREATE TABLE billing_policy_version (
  household_id TEXT NOT NULL REFERENCES household(id),
  effective_from TEXT NOT NULL CHECK (effective_from LIKE '____-__-01'),
  common_area_rule TEXT NOT NULL CHECK (common_area_rule IN ('equal', 'ask', 'presence')),
  ask_threshold_cents INTEGER NOT NULL CHECK (ask_threshold_cents >= 0),
  ask_timeout_hours INTEGER NOT NULL CHECK (ask_timeout_hours BETWEEN 1 AND 168),
  created_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (household_id, effective_from)
);
