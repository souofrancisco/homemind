-- HOUSE-03: defend the temporal model even if a writer bypasses the repository.
-- Membership existence is historical: an ended membership still validates an old owner.
CREATE TRIGGER appliance_state_owner_house_guard BEFORE INSERT ON appliance_state
WHEN (NEW.owner_resident_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM membership m
    WHERE m.household_id = NEW.household_id AND m.resident_id = NEW.owner_resident_id
  )) OR NOT EXISTS (
    SELECT 1 FROM membership m
    WHERE m.household_id = NEW.household_id AND m.resident_id = NEW.changed_by_resident_id
  )
BEGIN SELECT RAISE(ABORT,'appliance_state resident outside household'); END;

CREATE TRIGGER appliance_state_no_overlap BEFORE INSERT ON appliance_state
WHEN EXISTS (
  SELECT 1 FROM appliance_state old
  WHERE old.appliance_id = NEW.appliance_id
    AND (old.valid_to IS NULL OR NEW.valid_from < old.valid_to)
    AND (NEW.valid_to IS NULL OR old.valid_from < NEW.valid_to)
)
BEGIN SELECT RAISE(ABORT,'appliance_state interval overlap'); END;

CREATE TRIGGER appliance_meter_actor_house_guard BEFORE INSERT ON appliance_meter_link
WHEN NOT EXISTS (
  SELECT 1 FROM membership m
  WHERE m.household_id = NEW.household_id AND m.resident_id = NEW.assigned_by_resident_id
)
BEGIN SELECT RAISE(ABORT,'appliance_meter_link resident outside household'); END;

CREATE TRIGGER appliance_meter_no_overlap BEFORE INSERT ON appliance_meter_link
WHEN EXISTS (
  SELECT 1 FROM appliance_meter_link old
  WHERE old.appliance_id = NEW.appliance_id
    AND (old.valid_to IS NULL OR NEW.valid_from < old.valid_to)
    AND (NEW.valid_to IS NULL OR old.valid_from < NEW.valid_to)
)
BEGIN SELECT RAISE(ABORT,'appliance_meter_link interval overlap'); END;

CREATE TRIGGER appliance_registrar_house_guard BEFORE INSERT ON appliance
WHEN NOT EXISTS (
  SELECT 1 FROM membership m
  WHERE m.household_id = NEW.household_id AND m.resident_id = NEW.registered_by_resident_id
)
BEGIN SELECT RAISE(ABORT,'appliance registrar outside household'); END;

-- Text ordering is safe only for one fixed-width UTC representation. Application timestamps
-- are normalized to microseconds; reject raw-SQL variants that would break interval ordering.
-- Normalize device timestamps written by the first HOUSE-03 revision before installing guards.
UPDATE device
SET last_seen_at = substr(last_seen_at,1,19) || '.000000+00:00'
WHERE last_seen_at IS NOT NULL AND length(last_seen_at) = 25
  AND substr(last_seen_at,-6) = '+00:00';

CREATE TRIGGER appliance_timestamp_utc_insert BEFORE INSERT ON appliance
WHEN NEW.created_at NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
BEGIN SELECT RAISE(ABORT,'appliance UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER appliance_timestamp_utc_update BEFORE UPDATE ON appliance
WHEN NEW.created_at IS NOT OLD.created_at
  OR (NEW.retired_at IS NOT NULL AND NEW.retired_at NOT GLOB
    '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00')
  OR (OLD.retired_at IS NOT NULL AND NEW.retired_at IS NOT OLD.retired_at)
  OR (OLD.status = 'retired' AND NEW.status != 'retired')
BEGIN SELECT RAISE(ABORT,'appliance lifecycle timestamp/history is immutable'); END;

CREATE TRIGGER appliance_state_timestamp_utc_insert BEFORE INSERT ON appliance_state
WHEN NEW.valid_from NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
  OR (NEW.valid_to IS NOT NULL AND NEW.valid_to NOT GLOB
    '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00')
BEGIN SELECT RAISE(ABORT,'appliance_state UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER appliance_state_timestamp_utc_update BEFORE UPDATE ON appliance_state
WHEN NEW.valid_to IS NOT NULL AND NEW.valid_to NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
BEGIN SELECT RAISE(ABORT,'appliance_state UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER appliance_meter_timestamp_utc_insert BEFORE INSERT ON appliance_meter_link
WHEN NEW.valid_from NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
  OR (NEW.valid_to IS NOT NULL AND NEW.valid_to NOT GLOB
    '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00')
BEGIN SELECT RAISE(ABORT,'appliance_meter_link UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER appliance_meter_timestamp_utc_update BEFORE UPDATE ON appliance_meter_link
WHEN NEW.valid_to IS NOT NULL AND NEW.valid_to NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
BEGIN SELECT RAISE(ABORT,'appliance_meter_link UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER appliance_signature_timestamp_utc_insert BEFORE INSERT ON appliance_signature
WHEN NEW.updated_at NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
BEGIN SELECT RAISE(ABORT,'appliance_signature UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER appliance_signature_timestamp_utc_update BEFORE UPDATE ON appliance_signature
WHEN NEW.updated_at NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
BEGIN SELECT RAISE(ABORT,'appliance_signature UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER device_timestamp_utc_insert BEFORE INSERT ON device
WHEN NEW.last_seen_at IS NOT NULL AND NEW.last_seen_at NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
BEGIN SELECT RAISE(ABORT,'device UTC timestamp must use microsecond ISO-8601'); END;

CREATE TRIGGER device_timestamp_utc_update BEFORE UPDATE ON device
WHEN NEW.last_seen_at IS NOT NULL AND NEW.last_seen_at NOT GLOB
  '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]+00:00'
BEGIN SELECT RAISE(ABORT,'device UTC timestamp must use microsecond ISO-8601'); END;
