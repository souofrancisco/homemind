-- Plafond solidário editado depois de criado o quarto (dono: billing, BILL-03). Cada linha vale a
-- partir de `effective_from` (dia 1 de um mês, fuso da casa); antes da primeira vale
-- `room.included_wh` (definido na criação). Só a mudança que ainda não começou pode ser
-- substituída: um mês já começado e as faturas fechadas nunca mudam. `included_wh = 0`: sem plafond.
CREATE TABLE billing_room_allowance (
  household_id TEXT NOT NULL REFERENCES household(id),
  room_id TEXT NOT NULL REFERENCES room(id),
  effective_from TEXT NOT NULL CHECK (effective_from LIKE '____-__-01'),
  included_wh INTEGER NOT NULL CHECK (included_wh >= 0),
  created_by_resident_id TEXT NOT NULL REFERENCES resident(id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (room_id, effective_from)
);
