-- Orçamentos mensais (dono: billing/alerts, ALERT-01). `generation` sobe a cada reset explícito
-- (redefinir o orçamento): os limiares voltam a poder ser avisados, com ids de evento novos.
CREATE TABLE billing_budget (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  kind TEXT NOT NULL CHECK (kind IN ('personal', 'room_allowance')),
  resident_id TEXT REFERENCES resident(id),
  room_id TEXT,
  period TEXT NOT NULL,
  limit_cents INTEGER CHECK (limit_cents > 0),
  limit_wh INTEGER CHECK (limit_wh > 0),
  thresholds TEXT NOT NULL,
  last_threshold_notified INTEGER,
  generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
  updated_at TEXT NOT NULL,
  CHECK ((kind = 'personal') = (resident_id IS NOT NULL AND limit_cents IS NOT NULL))
);
CREATE UNIQUE INDEX billing_budget_personal ON billing_budget (household_id, resident_id, period)
  WHERE kind = 'personal';
CREATE UNIQUE INDEX billing_budget_room ON billing_budget (household_id, room_id, period)
  WHERE kind = 'room_allowance';
