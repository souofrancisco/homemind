-- Contestações de recibos (dono: billing, BILL-06). Uma aberta por morador e fatura; a decisão
-- (só do senhorio, com justificação) fica gravada com o antes/depois da parcela. Aceitar cria
-- uma nova revisão da fatura (`revision_bill_id`); a original nunca muda em silêncio.
CREATE TABLE billing_contestation (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  bill_id TEXT NOT NULL REFERENCES billing_bill(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  status TEXT NOT NULL CHECK (status IN ('open', 'accepted', 'rejected')),
  json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_by_resident_id TEXT REFERENCES resident(id)
);
CREATE UNIQUE INDEX billing_contestation_one_open ON billing_contestation (bill_id, resident_id)
  WHERE status = 'open';
CREATE INDEX billing_contestation_bill ON billing_contestation (bill_id);
