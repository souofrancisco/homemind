-- Atribuição de consumos (dono: billing, BILL-02). Nada se apaga: uma nova decisão marca a
-- anterior `superseded`.

-- Última versão conhecida de cada consumo (vinda de energy.consumption_*), para a fatura.
CREATE TABLE billing_consumption (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  status TEXT NOT NULL CHECK (status IN ('ongoing', 'closed', 'discarded')),
  started_at TEXT NOT NULL,
  energy_wh INTEGER CHECK (energy_wh >= 0),
  json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX billing_consumption_period ON billing_consumption (household_id, started_at);

CREATE TABLE billing_attribution (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  consumption_event_id TEXT NOT NULL REFERENCES billing_consumption(id),
  status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
  supersedes_id TEXT REFERENCES billing_attribution(id),
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
-- nunca duas atribuições ativas para o mesmo consumo
CREATE UNIQUE INDEX billing_attribution_one_active ON billing_attribution (consumption_event_id)
  WHERE status = 'active';

-- Pedidos «De quem é esta conta?» em curso (regra B, D-32).
CREATE TABLE billing_confirmation (
  consumption_event_id TEXT PRIMARY KEY REFERENCES billing_consumption(id),
  household_id TEXT NOT NULL REFERENCES household(id),
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'resolved', 'expired')),
  created_at TEXT NOT NULL
);
CREATE INDEX billing_confirmation_pending ON billing_confirmation (status, expires_at);
