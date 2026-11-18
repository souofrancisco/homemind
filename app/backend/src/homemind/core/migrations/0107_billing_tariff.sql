-- Tarifário de referência da casa (dono: billing, ALERT-02). Só para ESTIMAR custos antes da
-- fatura (orçamento, previsão); o fecho reparte sempre o total real. Sem linha: preço simples
-- de referência da casa ou da última fatura fechada.
CREATE TABLE billing_tariff (
  household_id TEXT PRIMARY KEY REFERENCES household(id),
  kind TEXT NOT NULL CHECK (kind IN ('simple', 'bi_hourly')),
  price_millicents_per_kwh INTEGER NOT NULL CHECK (price_millicents_per_kwh > 0),
  offpeak_price_millicents_per_kwh INTEGER
    CHECK (offpeak_price_millicents_per_kwh IS NULL OR offpeak_price_millicents_per_kwh > 0),
  updated_at TEXT NOT NULL,
  CHECK ((kind = 'bi_hourly') = (offpeak_price_millicents_per_kwh IS NOT NULL))
);
