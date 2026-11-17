-- Faturas de eletricidade (dono: billing, BILL-01). Dinheiro em cêntimos, energia em Wh.
-- Nada se apaga: uma correção é uma nova revisão e a anterior fica `superseded` (BILL-04).
CREATE TABLE billing_bill (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  total_cents INTEGER NOT NULL CHECK (total_cents > 0),
  fixed_cents INTEGER NOT NULL CHECK (fixed_cents >= 0 AND fixed_cents < total_cents),
  total_wh INTEGER NOT NULL CHECK (total_wh > 0),
  -- tarifa indicada na fatura (opcional, só para conferência)
  declared_price_millicents_per_kwh INTEGER CHECK (declared_price_millicents_per_kwh > 0),
  source TEXT NOT NULL CHECK (source IN ('manual', 'llm_extracted')),
  status TEXT NOT NULL CHECK (status IN ('draft', 'finalized', 'superseded')),
  origin TEXT NOT NULL CHECK (origin IN ('real', 'simulated')),
  kind TEXT NOT NULL CHECK (kind IN ('measured', 'estimated', 'inferred')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  supersedes_id TEXT REFERENCES billing_bill(id),
  created_at TEXT NOT NULL,
  created_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  CHECK (period_end >= period_start),
  CHECK ((revision > 1) = (supersedes_id IS NOT NULL))
);
-- uma fatura viva (não substituída) por casa e início de período
CREATE UNIQUE INDEX billing_bill_one_live ON billing_bill (household_id, period_start)
  WHERE status != 'superseded';
CREATE INDEX billing_bill_household ON billing_bill (household_id, period_start);
