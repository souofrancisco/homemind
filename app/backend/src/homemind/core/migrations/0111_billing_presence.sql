-- Regra C da sala, «por quem estava em casa» (dono: billing, BILL-07). Cópia mínima dos estados
-- que presence publica (`presence.changed`, só de quem deu `presence_opt_in`) e da ocupação
-- anónima (`presence.occupancy_changed`: visitas só como número). Só billing lê; nunca sai na
-- API nem chega ao senhorio. Guarda-se só o necessário para decidir consumos recentes e
-- apaga-se o que tem mais de `RETENTION` (40 dias) e já foi substituído por um estado novo.
CREATE TABLE billing_presence_state (
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL,
  since TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('in', 'out', 'uncertain')),
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  simulated INTEGER NOT NULL CHECK (simulated IN (0, 1)),
  PRIMARY KEY (household_id, resident_id, since)
);

CREATE TABLE billing_occupancy (
  household_id TEXT NOT NULL REFERENCES household(id),
  ts TEXT NOT NULL,
  people_inside INTEGER,
  visitors INTEGER,
  simulated INTEGER NOT NULL CHECK (simulated IN (0, 1)),
  PRIMARY KEY (household_id, ts)
);
