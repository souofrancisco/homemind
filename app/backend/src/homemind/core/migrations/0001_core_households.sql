-- Casas, quartos, moradores e memberships (dono: households). Datas em UTC ISO 8601 (texto);
-- `starts_on`/`ends_on` são datas (YYYY-MM-DD) do contrato.
CREATE TABLE household (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  timezone TEXT NOT NULL,
  common_area_rule TEXT NOT NULL DEFAULT 'ask' CHECK (common_area_rule IN ('equal', 'ask', 'presence')),
  ask_threshold_cents INTEGER NOT NULL DEFAULT 50 CHECK (ask_threshold_cents >= 0),
  ask_timeout_hours INTEGER NOT NULL DEFAULT 24 CHECK (ask_timeout_hours > 0),
  energy_price_millicents_per_kwh INTEGER CHECK (energy_price_millicents_per_kwh > 0),
  source_kind TEXT NOT NULL CHECK (source_kind IN ('demo', 'real')),
  created_at TEXT NOT NULL
);

CREATE TABLE room (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  kind TEXT NOT NULL CHECK (kind IN ('bedroom', 'common')),
  included_wh INTEGER CHECK (included_wh >= 0),
  UNIQUE (household_id, id),
  UNIQUE (household_id, name)
);

CREATE TABLE resident (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 80),
  auth_subject TEXT UNIQUE,  -- `sub` do Authentik; distinto do id interno
  created_at TEXT NOT NULL
);

CREATE TABLE membership (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  role TEXT NOT NULL CHECK (role IN ('landlord', 'tenant', 'operator')),
  room_id TEXT,
  starts_on TEXT NOT NULL,
  ends_on TEXT,
  status TEXT NOT NULL CHECK (status IN ('invited', 'active', 'ended')),
  presence_opt_in INTEGER NOT NULL DEFAULT 0 CHECK (presence_opt_in IN (0, 1)),
  -- o quarto tem de ser da mesma casa
  FOREIGN KEY (household_id, room_id) REFERENCES room(household_id, id),
  CHECK (ends_on IS NULL OR ends_on >= starts_on),
  CHECK (role = 'tenant' OR (room_id IS NULL AND presence_opt_in = 0)),
  CHECK (role != 'tenant' OR status = 'invited' OR room_id IS NOT NULL),
  CHECK (status != 'ended' OR ends_on IS NOT NULL)
);
-- uma membership aberta por pessoa e casa; um inquilino ativo por quarto
CREATE UNIQUE INDEX membership_one_open ON membership (household_id, resident_id)
  WHERE status IN ('invited', 'active');
CREATE UNIQUE INDEX membership_one_tenant_per_room ON membership (room_id)
  WHERE status = 'active' AND role = 'tenant';
CREATE INDEX membership_resident ON membership (resident_id, status);
