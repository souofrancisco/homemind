-- HOUSE-02: token SHA-256 only, never a raw bearer secret.
CREATE TABLE membership_invitation (
  id TEXT PRIMARY KEY,
  membership_id TEXT NOT NULL UNIQUE REFERENCES membership(id),
  token_sha256 TEXT NOT NULL UNIQUE CHECK (length(token_sha256) = 64),
  target_email TEXT NOT NULL,
  created_by_membership_id TEXT NOT NULL REFERENCES membership(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  redeemed_at TEXT,
  redeemed_by_resident_id TEXT REFERENCES resident(id),
  revoked_at TEXT,
  CHECK (redeemed_at IS NULL OR revoked_at IS NULL),
  CHECK (redeemed_at IS NULL OR redeemed_by_resident_id IS NOT NULL)
);
CREATE INDEX membership_invitation_expiry ON membership_invitation(expires_at)
  WHERE redeemed_at IS NULL AND revoked_at IS NULL;
