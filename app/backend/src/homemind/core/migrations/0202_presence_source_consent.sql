-- Consentimento por fonte de presença (PRIV-03 #51; dono: presence, P2). Convenção D-29: 02xx = P2.
-- Decisão D-37: opt-in SEPARADO e desligado por omissão para três fontes individuais (Wi-Fi,
-- aparelho a ligar, resposta manual). Sem linha = desligado. A porta/câmara não precisa (só conta
-- pessoas, sem identificar).
-- `presence_source_consent` é o ESTADO atual; `presence_consent_log` é o REGISTO de acrescentar
-- (quem, o quê, quando, com que versão do texto): nunca se altera nem se apaga. Não contém
-- nenhum dado de presença (só consentimentos), por isso fica depois de apagados os dados.
-- Prazo de conservação do registo: PROPOSTA a validar com o DPO (P-08/P-24).
CREATE TABLE presence_source_consent (
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  source TEXT NOT NULL CHECK (source IN ('wifi', 'appliance', 'manual')),
  enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
  text_version TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (household_id, resident_id, source)
);

CREATE TABLE presence_consent_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  household_id TEXT NOT NULL REFERENCES household(id),
  resident_id TEXT NOT NULL REFERENCES resident(id),
  subject TEXT NOT NULL CHECK (subject IN ('presence_opt_in', 'wifi', 'appliance', 'manual')),
  action TEXT NOT NULL CHECK (action IN ('granted', 'revoked')),
  text_version TEXT NOT NULL,
  reason TEXT CHECK (reason IS NULL OR reason IN ('resident', 'opt_in_revoked', 'left_household'))
);
CREATE INDEX presence_consent_log_resident ON presence_consent_log (household_id, resident_id, id);

CREATE TRIGGER presence_consent_log_no_update BEFORE UPDATE ON presence_consent_log
BEGIN SELECT RAISE(ABORT, 'presence_consent_log é só de acrescentar'); END;
CREATE TRIGGER presence_consent_log_no_delete BEFORE DELETE ON presence_consent_log
BEGIN SELECT RAISE(ABORT, 'presence_consent_log é só de acrescentar'); END;

-- Mudanças do opt-in global (feitas pelo módulo das casas, sem o importar): ficam no registo, e
-- ao REVOGAR as fontes desligam-se logo (um «ligar» rápido a seguir não as reativa em silêncio).
-- O relógio é o da base de dados (não há relógio da aplicação aqui). Os INSERT de seeds não contam.
CREATE TRIGGER membership_presence_opt_in_log AFTER UPDATE OF presence_opt_in ON membership
WHEN OLD.presence_opt_in <> NEW.presence_opt_in
BEGIN
  INSERT INTO presence_consent_log (at, household_id, resident_id, subject, action, text_version, reason)
  SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NEW.household_id, NEW.resident_id, s.source, 'revoked',
         s.text_version, 'opt_in_revoked'
  FROM presence_source_consent s
  WHERE NEW.presence_opt_in = 0 AND s.enabled = 1
    AND s.household_id = NEW.household_id AND s.resident_id = NEW.resident_id;
  UPDATE presence_source_consent
  SET enabled = 0, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE NEW.presence_opt_in = 0 AND enabled = 1
    AND household_id = NEW.household_id AND resident_id = NEW.resident_id;
  INSERT INTO presence_consent_log (at, household_id, resident_id, subject, action, text_version, reason)
  VALUES (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NEW.household_id, NEW.resident_id, 'presence_opt_in',
          CASE NEW.presence_opt_in WHEN 1 THEN 'granted' ELSE 'revoked' END, 'n/a',
          CASE NEW.presence_opt_in WHEN 1 THEN 'resident' ELSE 'opt_in_revoked' END);
END;
