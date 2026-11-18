-- ENERGY-01: frequency counts and explicit resident corrections, transaction scoped.
CREATE TABLE energy_signature_stats (
  signature_id TEXT NOT NULL REFERENCES appliance_signature(id),
  pattern TEXT NOT NULL CHECK (pattern IN ('continuous','cyclic','short','decaying')),
  count INTEGER NOT NULL CHECK (count >= 0),
  PRIMARY KEY(signature_id, pattern)
);
CREATE TABLE energy_signature_lock (
  signature_id TEXT PRIMARY KEY REFERENCES appliance_signature(id),
  pattern TEXT NOT NULL CHECK (pattern IN ('continuous','cyclic','short','decaying')),
  locked_at TEXT NOT NULL
);
