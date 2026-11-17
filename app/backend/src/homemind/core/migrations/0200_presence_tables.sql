-- Presença (dono: presence, P2). Convenção D-29: 02xx = P2.
-- Nunca guarda MAC em claro: `match_key` é um HMAC com sal; ao revogar é apagado (substituído
-- por um valor sem relação com o telemóvel).
CREATE TABLE presence_device (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
  match_key TEXT NOT NULL CHECK (length(match_key) BETWEEN 16 AND 128),
  wifi_opt_in INTEGER NOT NULL DEFAULT 0 CHECK (wifi_opt_in IN (0, 1)),
  consented_at TEXT,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  CHECK (wifi_opt_in = 0 OR (consented_at IS NOT NULL AND revoked_at IS NULL)),
  CHECK (revoked_at IS NULL OR consented_at IS NOT NULL)
);
CREATE UNIQUE INDEX presence_device_key ON presence_device (household_id, match_key);
CREATE INDEX presence_device_resident ON presence_device (household_id, resident_id);

-- Pedidos «estás em casa?» emitidos pela fusão (PRES-04). Servem para só aceitar respostas a
-- pedidos que existem, do próprio morador, uma vez (idempotência).
CREATE TABLE presence_confirmation (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  reason TEXT NOT NULL CHECK (reason IN ('conflicting_cues', 'no_recent_cues')),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  answered_at TEXT
);
CREATE INDEX presence_confirmation_resident ON presence_confirmation (household_id, resident_id, created_at);

-- Último estado fundido por morador (PRES-04): `since` e deteção de mudança.
CREATE TABLE presence_state (
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  state TEXT NOT NULL CHECK (state IN ('in', 'out', 'uncertain')),
  since TEXT NOT NULL,
  confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  origin TEXT NOT NULL CHECK (origin IN ('real', 'simulated')),
  kind TEXT NOT NULL CHECK (kind IN ('measured', 'estimated', 'inferred')),
  sources_json TEXT NOT NULL,
  reason TEXT CHECK (reason IN ('conflicting_cues', 'no_recent_cues')),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (household_id, resident_id),
  CHECK ((state = 'uncertain') = (reason IS NOT NULL))
);
