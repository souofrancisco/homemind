-- Plafond solidário de aquecimento (dono: billing, BILL-03). Só acrescenta colunas à evidência
-- do fecho (`0104`): se o consumo era aquecimento provado e quantos Wh o plafond cobriu (pagos
-- por todos). Faturas fechadas antes ficam com 0 (sem plafond aplicado, como foram fechadas).
ALTER TABLE billing_allocation_item
  ADD COLUMN heating INTEGER NOT NULL DEFAULT 0 CHECK (heating IN (0, 1));
ALTER TABLE billing_allocation_item
  ADD COLUMN covered_wh INTEGER NOT NULL DEFAULT 0 CHECK (covered_wh >= 0);

-- Plafond de cada quarto no período da fatura, tal como estava no fecho (o senhorio pode mudar
-- `room.included_wh` depois; o recibo explica-se com o valor usado).
CREATE TABLE billing_allowance (
  bill_id TEXT NOT NULL REFERENCES billing_bill(id),
  room_id TEXT NOT NULL REFERENCES room(id),
  limit_wh INTEGER NOT NULL CHECK (limit_wh >= 0),
  PRIMARY KEY (bill_id, room_id)
);
