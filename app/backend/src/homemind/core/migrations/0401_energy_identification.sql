-- ENERGY-04: aprendizagem por confirmação. Tabelas da energia (P1); nunca tocam em leituras,
-- consumos ou eventos. Tempos em UTC ISO-8601 com fuso.

-- Grupos de consumos desconhecidos parecidos (potência e duração), por casa.
CREATE TABLE energy_identification_group (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  status TEXT NOT NULL CHECK (status IN ('open','asked','resolved')),
  snoozed_until TEXT,  -- «Ignorar» ou pergunta caducada: não perguntar antes disto
  appliance_id TEXT REFERENCES appliance(id),
  created_at TEXT NOT NULL,
  CHECK ((status = 'resolved') = (appliance_id IS NOT NULL))
);
CREATE INDEX energy_identification_group_house ON energy_identification_group(household_id);

-- Uma linha por sessão fechada desconhecida que entrou num grupo (cópia derivada do evento).
CREATE TABLE energy_identification_session (
  consumption_id TEXT PRIMARY KEY,
  source_event_id TEXT NOT NULL UNIQUE,  -- `energy.consumption_closed`
  group_id TEXT NOT NULL REFERENCES energy_identification_group(id),
  household_id TEXT NOT NULL REFERENCES household(id),
  device_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  power_w REAL NOT NULL CHECK (power_w > 0),
  duration_s REAL NOT NULL CHECK (duration_s > 0),
  pattern TEXT NOT NULL CHECK (pattern IN ('continuous','cyclic','short','decaying')),
  hour_local INTEGER NOT NULL CHECK (hour_local BETWEEN 0 AND 23)
);
CREATE INDEX energy_identification_session_group
  ON energy_identification_session(group_id, started_at);

-- Pedidos «O que é este aparelho?»: um pendente por grupo; a primeira resposta válida fecha.
CREATE TABLE energy_identification_request (
  id TEXT PRIMARY KEY,
  group_id TEXT NOT NULL REFERENCES energy_identification_group(id),
  household_id TEXT NOT NULL REFERENCES household(id),
  status TEXT NOT NULL CHECK (status IN ('pending','answered','expired','revoked')),
  choice TEXT CHECK (choice IN ('mine','household','ignore')),
  appliance_id TEXT REFERENCES appliance(id),
  power_w REAL NOT NULL CHECK (power_w > 0),
  hour_local INTEGER NOT NULL CHECK (hour_local BETWEEN 0 AND 23),
  occurrences INTEGER NOT NULL CHECK (occurrences >= 1),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  answered_at TEXT,
  revoked_at TEXT,
  CHECK ((status IN ('answered','revoked')) = (choice IS NOT NULL)),
  CHECK (status != 'revoked' OR (appliance_id IS NOT NULL AND revoked_at IS NOT NULL)),
  CHECK ((choice IN ('mine','household')) = (appliance_id IS NOT NULL))
);
CREATE UNIQUE INDEX energy_identification_one_pending
  ON energy_identification_request(group_id) WHERE status = 'pending';

-- Histórico de amostras por evento: a assinatura recalcula-se SEMPRE a partir das não revogadas.
-- Desfazer = preencher `revoked_at` (uma vez); nunca se apaga nem se muda o resto.
CREATE TABLE energy_signature_sample (
  id TEXT PRIMARY KEY,
  signature_id TEXT NOT NULL,  -- stable_id("energy.signature", appliance_id); sem FK: sobrevive à assinatura
  appliance_id TEXT NOT NULL REFERENCES appliance(id),
  source_event_id TEXT NOT NULL,  -- `energy.consumption_closed` que deu a amostra
  power_w REAL NOT NULL CHECK (power_w > 0),
  duration_s REAL NOT NULL CHECK (duration_s > 0),
  pattern TEXT NOT NULL CHECK (pattern IN ('continuous','cyclic','short','decaying')),
  hour_local INTEGER NOT NULL CHECK (hour_local BETWEEN 0 AND 23),
  origin_kind TEXT NOT NULL CHECK (origin_kind IN ('confirmation','learning')),
  identification_id TEXT REFERENCES energy_identification_request(id),
  created_at TEXT NOT NULL,
  revoked_at TEXT,
  CHECK ((origin_kind = 'confirmation') = (identification_id IS NOT NULL)),
  UNIQUE (signature_id, source_event_id)
);
CREATE INDEX energy_signature_sample_signature ON energy_signature_sample(signature_id);
CREATE INDEX energy_signature_sample_identification
  ON energy_signature_sample(identification_id) WHERE identification_id IS NOT NULL;
CREATE TRIGGER energy_signature_sample_append_only BEFORE UPDATE ON energy_signature_sample
WHEN OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
  OR NEW.id != OLD.id OR NEW.signature_id != OLD.signature_id
  OR NEW.appliance_id != OLD.appliance_id OR NEW.source_event_id != OLD.source_event_id
  OR NEW.power_w != OLD.power_w OR NEW.duration_s != OLD.duration_s
  OR NEW.pattern != OLD.pattern OR NEW.hour_local != OLD.hour_local
  OR NEW.origin_kind != OLD.origin_kind
  OR NEW.identification_id IS NOT OLD.identification_id
  OR NEW.created_at != OLD.created_at
BEGIN SELECT RAISE(ABORT,'energy_signature_sample: só se revoga, uma vez'); END;
CREATE TRIGGER energy_signature_sample_no_delete BEFORE DELETE ON energy_signature_sample
BEGIN SELECT RAISE(ABORT,'energy_signature_sample: histórico imutável'); END;

-- Assinaturas aprendidas antes desta migração não têm amostras por evento: o agregado de então
-- fica como base fixa (não revogável) e soma-se às amostras novas no recálculo.
CREATE TABLE energy_signature_baseline (
  signature_id TEXT PRIMARY KEY,
  samples INTEGER NOT NULL CHECK (samples > 0),
  watts_mean REAL NOT NULL CHECK (watts_mean > 0),
  duration_typical_s INTEGER,
  typical_hours_json TEXT,
  pattern_counts_json TEXT NOT NULL
);
INSERT INTO energy_signature_baseline
  (signature_id, samples, watts_mean, duration_typical_s, typical_hours_json, pattern_counts_json)
SELECT s.id, s.samples, s.watts_mean, s.duration_typical_s, s.typical_hours_json,
  CASE WHEN EXISTS (SELECT 1 FROM energy_signature_stats st WHERE st.signature_id = s.id)
    THEN (SELECT json_group_object(st.pattern, st.count) FROM energy_signature_stats st
          WHERE st.signature_id = s.id)
    ELSE json_object(s.pattern, s.samples) END
FROM appliance_signature s WHERE s.origin = 'learned' AND s.samples > 0;
