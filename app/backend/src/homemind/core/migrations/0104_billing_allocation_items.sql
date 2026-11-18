-- Evidência de cada fatura fechada (dono: billing, BILL-05). Fotografia, no momento do fecho,
-- de cada consumo do período que entrou nas contas (ou ficou no resíduo por falta de decisão):
-- o consumo e a decisão TAL COMO ESTAVAM, para explicar o recibo mesmo que mudem depois.
-- Imutável: uma correção da fatura é uma nova revisão (novo bill_id) com a sua evidência.
CREATE TABLE billing_allocation_item (
  bill_id TEXT NOT NULL REFERENCES billing_bill(id),
  consumption_event_id TEXT NOT NULL REFERENCES billing_consumption(id),
  household_id TEXT NOT NULL REFERENCES household(id),
  -- 1: entrou com atribuição ativa; 0: sem decisão no fecho → resíduo, dividido por igual
  attributed INTEGER NOT NULL CHECK (attributed IN (0, 1)),
  target_resident_id TEXT REFERENCES resident(id),  -- NULL: conta comum (ou sem decisão)
  energy_wh INTEGER NOT NULL CHECK (energy_wh > 0),
  superseded_count INTEGER NOT NULL DEFAULT 0 CHECK (superseded_count >= 0),
  consumption_json TEXT NOT NULL,
  attribution_json TEXT,
  PRIMARY KEY (bill_id, consumption_event_id),
  CHECK ((attributed = 1) = (attribution_json IS NOT NULL)),
  CHECK (attributed = 1 OR target_resident_id IS NULL)
);
