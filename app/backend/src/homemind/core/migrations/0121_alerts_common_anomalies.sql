-- Gasto anormal nas zonas comuns (dono: billing/alerts, ALERT-03). Só o agregado do dia por
-- tomada de zona comum (energia integrada das leituras `ok` e segundos cobertos), nunca a série.
-- `day` = data local (fuso da casa) do início de cada intervalo entre duas leituras.
CREATE TABLE alerts_device_day (
  household_id TEXT NOT NULL REFERENCES household(id),
  device_id TEXT NOT NULL,
  day TEXT NOT NULL,
  energy_wh REAL NOT NULL CHECK (energy_wh >= 0),
  covered_s INTEGER NOT NULL CHECK (covered_s >= 0),
  PRIMARY KEY (household_id, device_id, day)
);

-- Última leitura `ok` por tomada (para integrar a seguinte) e último dia avisado.
CREATE TABLE alerts_anomaly_state (
  household_id TEXT NOT NULL REFERENCES household(id),
  device_id TEXT NOT NULL,
  last_ok_at TEXT NOT NULL,
  last_power_w REAL NOT NULL,
  alerted_day TEXT,
  PRIMARY KEY (household_id, device_id)
);
