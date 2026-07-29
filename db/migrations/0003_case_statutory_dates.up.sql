-- =====================================================================
-- Migration 0003 (up): record the dates statutory deadlines depend on.
--
-- NOT YET APPLIED. db.database.init_db() does not reference this file.
-- Applying it is a deliberate decision - review the type choice below
-- before you do, because it is the one thing here that is awkward to
-- change later.
--
-- Why
-- ---
-- core/rules/obligations.py can already say *what* a case must do and
-- *how long after which event*. It cannot say *when*, because the case
-- record has no idea when the employee arrived, when their contract
-- starts, or when their current permit runs out.
--
-- Without these, every statutory deadline is "needs arrival_date"
-- instead of a date. The engine deliberately refuses to substitute
-- cases.created_at - an internal timestamp is not a legal event, and a
-- deadline computed from one would be wrong in a way nobody could see.
--
-- Type choice: DATE, not TEXT
-- ---------------------------
-- Every other date in this schema is TEXT, which is a known piece of
-- technical debt: it makes range queries string comparisons, silently
-- correct for well-formed ISO values and silently wrong for anything
-- else. These three columns are different in kind - they are arithmetic
-- inputs. "arrival + 14 days" has to be a date calculation, and a
-- customer may be shown a penalty risk based on the result.
--
-- So these are DATE. That does mean the schema now has both
-- representations, which is worse than one. The alternative - matching
-- the existing TEXT for consistency - would mean doing date arithmetic
-- on strings for the figures with the highest consequence in the
-- product. Consistency loses to correctness here, and migrating the
-- older TEXT columns to DATE is the follow-up this makes possible.
--
-- All three are NULLable
-- ----------------------
-- Every existing case predates these columns, and most will never have
-- all three. NULL means "not recorded", which the engine already
-- handles by reporting the obligation as undated rather than guessing.
-- A default would manufacture a legal date out of nothing.
--
-- Safe to re-run.
-- =====================================================================

ALTER TABLE cases ADD COLUMN IF NOT EXISTS arrival_date DATE;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS contract_start_date DATE;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS permit_expiry_date DATE;


COMMENT ON COLUMN cases.arrival_date IS
    'Day the employee physically arrives in Switzerland. Trigger for '
    'commune registration and other arrival-based obligations. NULL '
    'means not recorded - never inferred.';

COMMENT ON COLUMN cases.contract_start_date IS
    'First day of the employment contract. Trigger for authorisation '
    'obligations that must be satisfied before work begins.';

COMMENT ON COLUMN cases.permit_expiry_date IS
    'Expiry printed on the current permit. Trigger for renewal '
    'deadlines, which are computed backwards from it.';


-- Deadline queries are "which cases have something due in the next N
-- days", i.e. range scans over these columns filtered by tenant. Partial
-- indexes because a large majority of rows will have NULL here for the
-- foreseeable future, and indexing those entries would cost write
-- throughput for no read benefit.
CREATE INDEX IF NOT EXISTS idx_cases_arrival_date
    ON cases (tenant_id, arrival_date)
    WHERE arrival_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cases_permit_expiry_date
    ON cases (tenant_id, permit_expiry_date)
    WHERE permit_expiry_date IS NOT NULL;


-- A permit that expired before the employee arrived, or a contract that
-- starts years before arrival, is a data-entry error rather than a real
-- situation. Caught here because a wrong date does not look wrong - it
-- produces a plausible deadline that is simply on the wrong day, and
-- nobody notices until it passes.
--
-- Deliberately loose: it rejects the impossible, not the unusual. A
-- contract starting before arrival is normal (remote start, commuting),
-- so only a large gap is treated as a mistake.
ALTER TABLE cases DROP CONSTRAINT IF EXISTS cases_statutory_dates_plausible;

ALTER TABLE cases ADD CONSTRAINT cases_statutory_dates_plausible CHECK (
    (
        arrival_date IS NULL
        OR contract_start_date IS NULL
        OR contract_start_date >= arrival_date - INTERVAL '2 years'
    )
    AND (
        arrival_date IS NULL
        OR permit_expiry_date IS NULL
        OR permit_expiry_date >= arrival_date - INTERVAL '1 year'
    )
);
