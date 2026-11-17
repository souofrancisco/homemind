-- Ações propostas pelo assistente (dono: P3, `features/agent`). Só acrescenta tabelas; sem DROP.
-- NUNCA editar depois de integrada na `main` (o checksum falha): alterações em `0311_...`.
-- Datas em UTC ISO 8601 (texto). `json` é a `ProposedAction` validada no momento da proposta;
-- o estado vigente é a coluna `status` (a fonte de verdade para as transições). `expired` pode
-- ser derivado na leitura (`expires_at`) sem escrita. Nada aqui executa uma ação: a execução
-- é de uma porta executora injetada (P1) e só depois de `status = 'confirmed'`.
CREATE TABLE agent_action (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  proposed_for_resident_id TEXT NOT NULL REFERENCES resident(id),
  -- id interno do dispositivo (nunca o id do MCP)
  target_device_id TEXT NOT NULL,
  device_name TEXT NOT NULL,
  capability TEXT NOT NULL CHECK (capability IN ('power', 'brightness', 'color_rgb')),
  status TEXT NOT NULL CHECK (status IN ('proposed', 'confirmed', 'rejected', 'expired', 'executed')),
  origin TEXT NOT NULL CHECK (origin IN ('real', 'simulated')),
  -- sem CHECK: a origem da proposta pode crescer sem migração (hoje só 'chat')
  source TEXT NOT NULL,
  proposed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  json TEXT NOT NULL,
  confirmation_json TEXT,
  execution_json TEXT,
  execution_status TEXT CHECK (execution_status IN ('confirmed', 'failed', 'uncertain', 'blocked')),
  executed_at TEXT,
  updated_at TEXT NOT NULL,
  CHECK (expires_at > proposed_at),
  CHECK ((status = 'executed') = (execution_json IS NOT NULL)),
  CHECK ((execution_json IS NULL) = (execution_status IS NULL)),
  -- uma ação só passa de `proposed` com a confirmação humana gravada
  CHECK (status IN ('proposed', 'rejected', 'expired') OR confirmation_json IS NOT NULL)
);
-- Só as transições do fluxo: proposed → confirmed | rejected, confirmed → executed. O estado
-- terminal não volta atrás e nada salta a confirmação (`expired` é derivado, nunca se grava).
CREATE TRIGGER agent_action_status_transition BEFORE UPDATE OF status ON agent_action
WHEN NOT (
  OLD.status = NEW.status
  OR (OLD.status = 'proposed' AND NEW.status IN ('confirmed', 'rejected'))
  OR (OLD.status = 'confirmed' AND NEW.status = 'executed')
)
BEGIN SELECT RAISE(ABORT, 'transição de estado inválida em agent_action'); END;
CREATE INDEX agent_action_resident ON agent_action (household_id, proposed_for_resident_id, proposed_at);
CREATE INDEX agent_action_device ON agent_action (household_id, target_device_id, executed_at);

-- Uma linha por transição, só a acrescentar (os gatilhos recusam UPDATE e DELETE).
-- `from_status` é nulo na proposta; `by_resident_id` é nulo quando é o sistema.
CREATE TABLE agent_action_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  action_id TEXT NOT NULL REFERENCES agent_action(id),
  at TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  by_resident_id TEXT REFERENCES resident(id),
  code TEXT
);
CREATE INDEX agent_action_log_action ON agent_action_log (action_id, seq);
CREATE TRIGGER agent_action_log_no_update BEFORE UPDATE ON agent_action_log
BEGIN SELECT RAISE(ABORT, 'agent_action_log é append-only'); END;
CREATE TRIGGER agent_action_log_no_delete BEFORE DELETE ON agent_action_log
BEGIN SELECT RAISE(ABORT, 'agent_action_log é append-only'); END;
