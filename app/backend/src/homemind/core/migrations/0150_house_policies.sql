-- HOUSE-04. Versioned household policy, current decision and immutable audit history.
-- All writes go through Database.run / BEGIN IMMEDIATE. No financial allocations live here.
CREATE TABLE household_policy_version (
  household_id TEXT NOT NULL REFERENCES household(id),
  version INTEGER NOT NULL CHECK (version >= 1),
  valid_from TEXT NOT NULL,
  valid_until TEXT,
  common_area_rule TEXT NOT NULL CHECK (common_area_rule IN ('equal','ask','presence')),
  ask_threshold_cents INTEGER NOT NULL CHECK (ask_threshold_cents >= 0),
  ask_timeout_hours INTEGER NOT NULL CHECK (ask_timeout_hours BETWEEN 1 AND 168),
  fallback_rule TEXT NOT NULL DEFAULT 'equal' CHECK (fallback_rule = 'equal'),
  PRIMARY KEY (household_id, version),
  UNIQUE (household_id, valid_from),
  CHECK (valid_until IS NULL OR valid_until > valid_from)
);
CREATE UNIQUE INDEX house_policy_one_current
  ON household_policy_version(household_id) WHERE valid_until IS NULL;

CREATE TABLE household_policy_decision (
  household_id TEXT NOT NULL REFERENCES household(id),
  consumption_event_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision >= 1),
  status TEXT NOT NULL CHECK (status IN ('automatic','confirmed','pending','fallback')),
  policy_version INTEGER NOT NULL,
  decision_json TEXT NOT NULL CHECK (json_valid(decision_json)),
  PRIMARY KEY (household_id, consumption_event_id),
  FOREIGN KEY (household_id, policy_version)
    REFERENCES household_policy_version(household_id, version)
);
CREATE INDEX household_policy_pending ON household_policy_decision(household_id, status);

CREATE TABLE household_policy_audit (
  household_id TEXT NOT NULL,
  consumption_event_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision >= 1),
  source_event_id TEXT NOT NULL UNIQUE,
  decided_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('automatic','confirmed','pending','fallback')),
  reason TEXT NOT NULL,
  decision_json TEXT NOT NULL CHECK (json_valid(decision_json)),
  PRIMARY KEY (household_id, consumption_event_id, revision),
  FOREIGN KEY (household_id, consumption_event_id)
    REFERENCES household_policy_decision(household_id, consumption_event_id)
);
CREATE TRIGGER house_policy_audit_no_update BEFORE UPDATE ON household_policy_audit
BEGIN SELECT RAISE(ABORT, 'household_policy_audit imutável'); END;
CREATE TRIGGER house_policy_audit_no_delete BEFORE DELETE ON household_policy_audit
BEGIN SELECT RAISE(ABORT, 'household_policy_audit imutável'); END;
