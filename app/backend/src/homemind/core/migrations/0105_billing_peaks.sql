-- Picos em zonas comuns (ALERT-03). Estado por tomada, para o detetor sobreviver a reinícios
-- sem repetir avisos: o episódio acima do limite e o último incidente avisado.
CREATE TABLE billing_peak_state (
  device_id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  last_ok_at TEXT,          -- última leitura utilizável (deteta lacunas)
  above_since TEXT,         -- início do episódio contínuo acima do limite
  alerted_last_above TEXT,  -- última leitura acima do limite do incidente já avisado
  updated_at TEXT NOT NULL
);
