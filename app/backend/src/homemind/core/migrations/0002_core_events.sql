-- Barramento persistente: `domain_event` é o registo imutável (a «fila»); `processed_event`
-- guarda TODOS os pares (consumidor, evento) processados, na mesma transação do efeito.
CREATE TABLE domain_event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  ts TEXT NOT NULL,
  household_id TEXT NOT NULL REFERENCES household(id),
  correlation_id TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('real', 'simulated')),
  kind TEXT NOT NULL CHECK (kind IN ('measured', 'estimated', 'inferred')),
  payload_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE INDEX domain_event_type_seq ON domain_event (type, seq);
CREATE INDEX domain_event_household_seq ON domain_event (household_id, seq);
CREATE INDEX domain_event_correlation ON domain_event (correlation_id);
CREATE TRIGGER domain_event_no_update BEFORE UPDATE ON domain_event
BEGIN SELECT RAISE(ABORT, 'domain_event é imutável'); END;
CREATE TRIGGER domain_event_no_delete BEFORE DELETE ON domain_event
BEGIN SELECT RAISE(ABORT, 'domain_event é imutável'); END;

CREATE TABLE processed_event (
  consumer TEXT NOT NULL,
  event_id TEXT NOT NULL REFERENCES domain_event(id),
  processed_at TEXT NOT NULL,
  PRIMARY KEY (consumer, event_id)
);

-- Só falhas: tentativas e tipo do erro (nunca a mensagem, pode ter dados pessoais).
-- `dead = 1`: desistiu-se; deixa de bloquear o consumidor e fica visível para diagnóstico.
CREATE TABLE event_failure (
  consumer TEXT NOT NULL,
  event_id TEXT NOT NULL REFERENCES domain_event(id),
  attempts INTEGER NOT NULL,
  last_error_type TEXT NOT NULL,
  dead INTEGER NOT NULL DEFAULT 0 CHECK (dead IN (0, 1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (consumer, event_id)
);
