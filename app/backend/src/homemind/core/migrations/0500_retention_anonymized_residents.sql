-- PRIV-04: ex-moradores já anonimizados (dono: retention). O `resident` mantém o id (os valores e
-- as parcelas continuam ligados a ele, como evidência financeira); o nome passa a «Ex-morador»,
-- a ligação à conta (`auth_subject`) apaga-se e os dados pessoais não financeiros saem.
CREATE TABLE retention_anonymized_resident (
  resident_id TEXT PRIMARY KEY REFERENCES resident(id),
  anonymized_at TEXT NOT NULL
);
