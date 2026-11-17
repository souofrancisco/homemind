-- Parcelas por morador de uma fatura fechada (dono: billing, BILL-04). Imutáveis depois do
-- fecho: uma correção cria uma nova revisão da fatura com parcelas novas; as antigas ficam.
CREATE TABLE billing_allocation (
  id TEXT PRIMARY KEY,
  bill_id TEXT NOT NULL REFERENCES billing_bill(id),
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  room_id TEXT,
  amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
  attributed_wh INTEGER NOT NULL CHECK (attributed_wh >= 0),
  status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'contested', 'resolved')),
  json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (bill_id, resident_id)
);
CREATE INDEX billing_allocation_resident ON billing_allocation (resident_id, bill_id);
