-- Regras individuais (SAFE-04, D-39, dono: P3, `features/automations`). Só acrescenta colunas.
-- `scope = 'house'` (predefinição: as regras já existentes continuam regras da casa, sem nova
-- votação) ou `'personal'`: regra privada do dono (`owner_resident_id` = quem a criou), criada
-- `active` na hora, sem votação. Uma individual nunca tem ronda aberta: guarda `vote_round = 1`,
-- `vote_open = 0`, `vote_deadline = proposed_at` e `eligible_json = [dono]` só para cumprir os
-- NOT NULL de `0320`; a coerência (individual ⇒ dono, sem votação) é do serviço e do contrato.
ALTER TABLE automation_rule ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'
  CHECK (scope IN ('house', 'personal'));
ALTER TABLE automation_rule ADD COLUMN owner_resident_id TEXT REFERENCES resident(id);
CREATE INDEX automation_rule_owner ON automation_rule (owner_resident_id)
  WHERE owner_resident_id IS NOT NULL;
