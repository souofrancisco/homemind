-- Regras da casa votadas (SAFE-04, dono: P3, `features/automations`). Só acrescenta tabelas.
-- NUNCA editar depois de integrada na `main` (o checksum falha): alterações em `0321_...`.
-- Datas em UTC ISO 8601 (texto). `json` é a `AutomationRule` validada à proposta; as colunas
-- `status`, `approved_by_resident_id`, `vote_*` e `rev` são a fonte de verdade das transições.
-- Nada aqui executa uma regra: o motor (onda 3) só olha para `status = 'active'`.
CREATE TABLE automation_rule (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft', 'proposed', 'active', 'disabled')),
  origin TEXT NOT NULL CHECK (origin IN ('real', 'simulated')),
  created_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  approved_by_resident_id TEXT REFERENCES resident(id),
  -- nome(s) da(s) tomada(s) à altura da proposta (as ações, com ids internos, estão em `json`)
  device_name TEXT NOT NULL,
  proposed_at TEXT NOT NULL,
  -- ronda de votação em curso (ou a última): 1 na proposta, +1 a cada reativação
  vote_round INTEGER NOT NULL CHECK (vote_round >= 1),
  vote_open INTEGER NOT NULL CHECK (vote_open IN (0, 1)),
  vote_deadline TEXT NOT NULL,
  -- ids dos inquilinos elegíveis à abertura da ronda (maioria determinística)
  eligible_json TEXT NOT NULL,
  last_verdict TEXT CHECK (last_verdict IN ('approved', 'rejected')),
  -- versão para o compare-and-set e para ids de eventos estáveis
  rev INTEGER NOT NULL DEFAULT 1,
  json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (status != 'active' OR approved_by_resident_id IS NOT NULL),
  -- só se vota numa regra proposta ou numa suspensa que se quer reativar
  CHECK (vote_open = 0 OR status IN ('proposed', 'disabled'))
);
-- Só as transições do contrato (`AUTOMATION_TRANSITIONS`).
CREATE TRIGGER automation_rule_status_transition BEFORE UPDATE OF status ON automation_rule
WHEN NOT (
  OLD.status = NEW.status
  OR (OLD.status = 'draft' AND NEW.status = 'proposed')
  OR (OLD.status = 'proposed' AND NEW.status IN ('active', 'draft'))
  OR (OLD.status = 'active' AND NEW.status = 'disabled')
  OR (OLD.status = 'disabled' AND NEW.status = 'active')
)
BEGIN SELECT RAISE(ABORT, 'transição de estado inválida em automation_rule'); END;
CREATE INDEX automation_rule_household ON automation_rule (household_id, proposed_at);

-- Um voto por morador na ronda em curso (a reativação abre uma ronda limpa e apaga estes votos;
-- o histórico fica em `automation_log`).
CREATE TABLE automation_vote (
  rule_id TEXT NOT NULL REFERENCES automation_rule(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  approve INTEGER NOT NULL CHECK (approve IN (0, 1)),
  at TEXT NOT NULL,
  PRIMARY KEY (rule_id, resident_id)
);

-- Uma linha por acontecimento, só a acrescentar (os gatilhos recusam UPDATE e DELETE).
-- `by_resident_id` é nulo quando é o sistema (prazo); `code` explica o desfecho.
CREATE TABLE automation_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id TEXT NOT NULL REFERENCES automation_rule(id),
  at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('proposed', 'voted', 'decided', 'suspended', 'reactivation_opened')),
  from_status TEXT,
  to_status TEXT,
  by_resident_id TEXT REFERENCES resident(id),
  approve INTEGER CHECK (approve IN (0, 1)),
  code TEXT
);
CREATE INDEX automation_log_rule ON automation_log (rule_id, seq);
CREATE TRIGGER automation_log_no_update BEFORE UPDATE ON automation_log
BEGIN SELECT RAISE(ABORT, 'automation_log é append-only'); END;
CREATE TRIGGER automation_log_no_delete BEFORE DELETE ON automation_log
BEGIN SELECT RAISE(ABORT, 'automation_log é append-only'); END;
