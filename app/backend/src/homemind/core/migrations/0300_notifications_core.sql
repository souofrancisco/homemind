-- Notificações (dono: P3, `features/notifications`). Só acrescenta tabelas; sem DROP.
-- NUNCA editar depois de integrada na `main` (o checksum falha): alterações em `0301_...`.
-- Datas em UTC ISO 8601 (texto). `json` é a `Notification` validada (fonte de verdade); as
-- colunas escalares existem para filtrar, deduplicar e impor a coerência por SQL.
CREATE TABLE notification (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES household(id),
  scope TEXT NOT NULL CHECK (scope IN ('personal', 'household')),
  recipient_resident_id TEXT REFERENCES resident(id),
  -- sem CHECK: o conjunto de tipos cresce no contrato sem migração
  kind TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('unread', 'read', 'actioned', 'expired', 'dismissed')),
  ref_type TEXT,
  ref_id TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('real', 'simulated')),
  json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK ((scope = 'personal') = (recipient_resident_id IS NOT NULL))
);
CREATE INDEX notification_household_created ON notification (household_id, created_at);
-- Um pedido de confirmação aberto de cada vez por (casa, tipo, referência, destinatário).
CREATE UNIQUE INDEX notification_open_dedupe ON notification (
  household_id, kind, COALESCE(ref_type, ''), COALESCE(ref_id, ''),
  COALESCE(recipient_resident_id, '')
) WHERE status IN ('unread', 'read') AND kind = 'confirmation_request';

-- Recibo de leitura por residente (o estado `read` partilhado só vale nas pessoais).
CREATE TABLE notification_read (
  notification_id TEXT NOT NULL REFERENCES notification(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  read_at TEXT NOT NULL,
  PRIMARY KEY (notification_id, resident_id)
);

-- Por (residente, casa): o silêncio noturno é a hora local de CADA casa.
CREATE TABLE notification_preferences (
  resident_id TEXT NOT NULL REFERENCES resident(id),
  household_id TEXT NOT NULL REFERENCES household(id),
  json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (resident_id, household_id)
);
