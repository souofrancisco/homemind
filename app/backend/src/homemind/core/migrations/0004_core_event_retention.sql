-- PRIV-04: retenção diferenciada. `domain_event` continua imutável (nunca UPDATE) e só a
-- TELEMETRIA EM BRUTO pode ser apagada, pelo expurgo de retenção (`features/retention`).
-- Tudo o resto (faturação, consumos, votos, decisões, notificações, presença) continua
-- impossível de apagar aqui: a evidência financeira nunca se perde por engano. Presença tem a
-- sua própria política (PRIV-03 #51); alargar esta lista exige nova migração e acordo da equipa.
DROP TRIGGER domain_event_no_delete;
CREATE TRIGGER domain_event_no_delete BEFORE DELETE ON domain_event
WHEN OLD.type NOT IN ('energy.reading_recorded', 'sensor.reading_recorded')
BEGIN SELECT RAISE(ABORT, 'domain_event é imutável'); END;
