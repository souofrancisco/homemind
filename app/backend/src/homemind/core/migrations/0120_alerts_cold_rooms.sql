-- Noites frias por quarto (dono: billing/alerts, ALERT-06). Só o agregado da noite (soma e
-- número de leituras `ok` do sensor de clima), nunca horários nem a série de leituras.
-- `night` = data local do início da noite (22:00–08:00 no fuso da casa).
CREATE TABLE alerts_room_night (
  household_id TEXT NOT NULL REFERENCES household(id),
  room_id TEXT NOT NULL,
  night TEXT NOT NULL,
  sum_c REAL NOT NULL,
  readings INTEGER NOT NULL CHECK (readings >= 1),
  simulated INTEGER NOT NULL CHECK (simulated IN (0, 1)),
  PRIMARY KEY (household_id, room_id, night)
);

-- Último aviso de quarto frio por quarto (um por janela de noites, nunca repetido).
CREATE TABLE alerts_cold_room_notice (
  household_id TEXT NOT NULL REFERENCES household(id),
  room_id TEXT NOT NULL,
  last_night TEXT NOT NULL,
  PRIMARY KEY (household_id, room_id)
);
