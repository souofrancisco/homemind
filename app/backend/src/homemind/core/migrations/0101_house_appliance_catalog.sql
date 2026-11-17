-- HOUSE-03. Internal UUIDs only; external MCP reference never belongs in API/event payloads.
-- All timestamps are UTC ISO-8601 with explicit offset. Intervals are [valid_from, valid_to).
CREATE TABLE device (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  room_id TEXT,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  kind TEXT NOT NULL CHECK (kind IN ('plug','bulb','camera','sensor')),
  role TEXT NOT NULL DEFAULT 'none'
    CHECK (role IN ('main_meter','room_meter','actuator','none')),
  source TEXT NOT NULL CHECK (source IN ('mcp','fake','replay')),
  external_ref TEXT,
  power_unit TEXT NOT NULL DEFAULT 'unknown'
    CHECK (power_unit IN ('W','dW','mW','unknown')),
  last_seen_at TEXT,
  online INTEGER NOT NULL DEFAULT 0 CHECK (online IN (0,1)),
  UNIQUE (household_id, id),
  FOREIGN KEY (household_id,room_id) REFERENCES room(household_id,id),
  CHECK (role NOT IN ('main_meter','room_meter') OR kind = 'plug'),
  CHECK (role != 'room_meter' OR room_id IS NOT NULL),
  CHECK (role != 'actuator' OR kind IN ('plug','bulb')),
  CHECK (source != 'mcp' OR external_ref IS NOT NULL)
);
CREATE UNIQUE INDEX device_external_identity
  ON device (household_id,source,external_ref) WHERE external_ref IS NOT NULL;

CREATE TABLE appliance (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  category TEXT NOT NULL
    CHECK (category IN ('heating','cooling','kitchen','laundry','electronics','lighting','other')),
  typical_watts REAL CHECK (typical_watts IS NULL OR (typical_watts > 0 AND typical_watts <= 100000)),
  registered_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired')),
  created_at TEXT NOT NULL,
  retired_at TEXT,
  UNIQUE (household_id,id),
  CHECK ((status = 'active' AND retired_at IS NULL)
    OR (status = 'retired' AND retired_at IS NOT NULL))
);
-- Reject accidental duplicate active registrations by the same resident.
CREATE UNIQUE INDEX appliance_active_duplicate
  ON appliance (household_id,registered_by_resident_id,category,lower(name))
  WHERE status = 'active';

-- State changes never overwrite who owned an appliance or its usual room at a previous time.
CREATE TABLE appliance_state (
  id TEXT PRIMARY KEY,
  appliance_id TEXT NOT NULL,
  household_id TEXT NOT NULL,
  scope TEXT NOT NULL CHECK (scope IN ('personal','shared','common')),
  owner_resident_id TEXT REFERENCES resident(id),
  home_room_id TEXT,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  changed_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  FOREIGN KEY (household_id,appliance_id) REFERENCES appliance(household_id,id),
  FOREIGN KEY (household_id,home_room_id) REFERENCES room(household_id,id),
  CHECK ((scope = 'common' AND owner_resident_id IS NULL)
    OR (scope IN ('personal','shared') AND owner_resident_id IS NOT NULL)),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX appliance_one_current_state ON appliance_state(appliance_id)
  WHERE valid_to IS NULL;
CREATE INDEX appliance_state_period ON appliance_state(appliance_id,valid_from,valid_to);

-- Several appliances can be associated with one meter; an appliance has at most one
-- habitual meter at a time. A link is NOT evidence that the meter uniquely measured it.
CREATE TABLE appliance_meter_link (
  id TEXT PRIMARY KEY,
  appliance_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  household_id TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  assigned_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  FOREIGN KEY (household_id,appliance_id) REFERENCES appliance(household_id,id),
  FOREIGN KEY (household_id,device_id) REFERENCES device(household_id,id),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX appliance_one_current_meter ON appliance_meter_link(appliance_id)
  WHERE valid_to IS NULL;
CREATE INDEX appliance_link_at_time ON appliance_meter_link(appliance_id,valid_from,valid_to);
CREATE INDEX appliance_meter_active ON appliance_meter_link(device_id) WHERE valid_to IS NULL;

-- P1 owns signature learning and matching. HOUSE-03 supplies only durable storage
-- referencing the catalogue; neither ownership nor billing is inferred from this table.
CREATE TABLE appliance_signature (
  id TEXT PRIMARY KEY,
  appliance_id TEXT NOT NULL REFERENCES appliance(id),
  watts_mean REAL NOT NULL CHECK (watts_mean > 0 AND watts_mean <= 100000),
  watts_tolerance REAL NOT NULL CHECK (watts_tolerance >= 0 AND watts_tolerance < watts_mean),
  duration_typical_s INTEGER CHECK (duration_typical_s > 0),
  pattern TEXT NOT NULL CHECK (pattern IN ('continuous','cyclic','short','decaying')),
  typical_hours_json TEXT,
  samples INTEGER NOT NULL DEFAULT 0 CHECK (samples >= 0),
  origin TEXT NOT NULL CHECK (origin IN ('registered','learned','simulated')),
  updated_at TEXT NOT NULL
);
CREATE INDEX appliance_signature_appliance ON appliance_signature(appliance_id);

-- A closed history interval can never be changed/reopened; active intervals can only close.
CREATE TRIGGER appliance_state_history_guard BEFORE UPDATE ON appliance_state
WHEN OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL
  OR NEW.id != OLD.id OR NEW.appliance_id != OLD.appliance_id
  OR NEW.household_id != OLD.household_id OR NEW.scope != OLD.scope
  OR NEW.owner_resident_id IS NOT OLD.owner_resident_id
  OR NEW.home_room_id IS NOT OLD.home_room_id
  OR NEW.valid_from != OLD.valid_from
  OR NEW.changed_by_resident_id != OLD.changed_by_resident_id
BEGIN SELECT RAISE(ABORT,'appliance_state history immutable'); END;
CREATE TRIGGER appliance_meter_history_guard BEFORE UPDATE ON appliance_meter_link
WHEN OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL
  OR NEW.id != OLD.id OR NEW.appliance_id != OLD.appliance_id
  OR NEW.household_id != OLD.household_id OR NEW.device_id != OLD.device_id
  OR NEW.valid_from != OLD.valid_from
  OR NEW.assigned_by_resident_id != OLD.assigned_by_resident_id
BEGIN SELECT RAISE(ABORT,'appliance_meter_link history immutable'); END;
CREATE TRIGGER appliance_state_no_delete BEFORE DELETE ON appliance_state
BEGIN SELECT RAISE(ABORT,'appliance_state history immutable'); END;
CREATE TRIGGER appliance_meter_no_delete BEFORE DELETE ON appliance_meter_link
BEGIN SELECT RAISE(ABORT,'appliance_meter_link history immutable'); END;
