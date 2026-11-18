-- Retenção de presença (PRIV-03 #51; dono: presence, P2). Convenção D-29: 02xx = P2.
-- 1) Agregados diários que substituem os eventos brutos de presença depois de N dias. NUNCA
--    guardam horários, MAC nem identificadores de rede: só durações por estado e contagens.
-- 2) Registo de auditoria do expurgo (só contagens e motivo, nunca conteúdo de eventos).
-- 3) O trigger de PRIV-04 passa a deixar apagar também os tipos `presence.*` (só o expurgo de
--    `features/presence/retention.py` o faz). Tudo o resto continua imutável: financeiro,
--    votos, notificações, consumos.

-- Por morador e dia local da casa. `end_state` é só o estado em que o dia acabou (continuidade
-- do dia seguinte), não uma hora.
CREATE TABLE presence_daily (
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  day TEXT NOT NULL,
  seconds_in INTEGER NOT NULL CHECK (seconds_in >= 0),
  seconds_out INTEGER NOT NULL CHECK (seconds_out >= 0),
  seconds_uncertain INTEGER NOT NULL CHECK (seconds_uncertain >= 0),
  end_state TEXT NOT NULL CHECK (end_state IN ('in', 'out', 'uncertain')),
  cues_wifi INTEGER NOT NULL DEFAULT 0 CHECK (cues_wifi >= 0),
  cues_manual INTEGER NOT NULL DEFAULT 0 CHECK (cues_manual >= 0),
  cues_appliance INTEGER NOT NULL DEFAULT 0 CHECK (cues_appliance >= 0),
  confirmation_requests INTEGER NOT NULL DEFAULT 0 CHECK (confirmation_requests >= 0),
  PRIMARY KEY (household_id, resident_id, day)
);

-- Por casa e dia: passagens anónimas na porta (sem horas, sem pessoa).
CREATE TABLE presence_door_daily (
  household_id TEXT NOT NULL REFERENCES household(id),
  day TEXT NOT NULL,
  entered INTEGER NOT NULL DEFAULT 0 CHECK (entered >= 0),
  left INTEGER NOT NULL DEFAULT 0 CHECK (left >= 0),
  PRIMARY KEY (household_id, day)
);

CREATE TABLE presence_retention_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('compact', 'erase')),
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT REFERENCES resident(id),
  reason TEXT CHECK (reason IN ('opt_in_revoked', 'left_household')),
  counts_json TEXT NOT NULL
);

DROP TRIGGER domain_event_no_delete;
CREATE TRIGGER domain_event_no_delete BEFORE DELETE ON domain_event
WHEN OLD.type NOT IN ('energy.reading_recorded', 'sensor.reading_recorded',
  'presence.cue_recorded', 'presence.door_crossed', 'presence.changed',
  'presence.occupancy_changed', 'presence.confirmation_needed')
BEGIN SELECT RAISE(ABORT, 'domain_event é imutável'); END;
