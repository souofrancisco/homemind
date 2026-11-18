-- PRES-06: último estado agregado da casa (só o estado e o instante, nunca por pessoa). Serve para
-- publicar `presence.occupancy_changed` só quando muda e para manter o zero fiável para lá das 24 h.
CREATE TABLE presence_house_state (
  household_id TEXT PRIMARY KEY REFERENCES household(id),
  state TEXT NOT NULL CHECK (state IN ('occupied', 'likely_empty', 'uncertain')),
  since TEXT NOT NULL
);
