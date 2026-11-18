-- Histórico da conversa com o assistente (dono: P3, `features/agent`). Só acrescenta tabelas; sem DROP.
-- NUNCA editar depois de integrada na `main` (o checksum falha): alterações em `0312_...`.
-- Datas em UTC ISO 8601 (texto). Dados pessoais: cada linha é de UM residente e só ele a lê;
-- a retenção é curta (cortada por número e por idade em `features/agent/history.py`, P-25).
-- O histórico serve só a app: nunca é enviado a um LLM (P-06).
CREATE TABLE agent_message (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX agent_message_resident ON agent_message (household_id, resident_id, created_at);
