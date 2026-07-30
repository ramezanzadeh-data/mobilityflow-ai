-- =====================================================================
-- Migration 0007 (up): the commune a case belongs to.
--
-- Applied by db.database._migrate_case_commune() during init_db().
--
-- Why the canton is not enough
-- ----------------------------
-- Two things this product computes turn out to depend on the commune,
-- not the canton, and both were found by tracing the rules to their
-- sources rather than by anyone asking for the field.
--
-- 1. Permit renewal windows. Three Valais communes publish three
--    different answers: general guidance says a renewal may be filed at
--    the earliest 3 months before expiry, Sierre says at the earliest 2
--    months, Grimisuat states applications are filed 14 days before
--    expiry. The single -90 day offset the engine used is therefore
--    wrong for at least two of them, and no canton-level number can be
--    right.
--
-- 2. Correspondence language. Valais is officially bilingual and the
--    boundary runs through the middle of the canton: Martigny and Sion
--    administer in French, Brig and Visp in German. core/correspondence.py
--    currently falls back to a canton default and says on screen that it
--    is guessing, because there was nothing better to use.
--
-- Deliberately free text, not a foreign key
-- -----------------------------------------
-- There is no verified commune registry in this repository, and
-- inventing one would repeat a mistake this codebase has already made
-- once: a lookup table that looks researched and is not. A constrained
-- column would force exactly that.
--
-- So the column stores what the user typed, and
-- data/canton_valais_communes.json holds only the communes whose
-- practice has actually been traced to a published source - three, at
-- the time of writing. Everything else resolves to "not known for this
-- commune", which is a true statement the product can act on.
--
-- NULL means not recorded. Every existing case predates this column and
-- must keep working: the deadline engine already reports "date not
-- recorded" honestly rather than guessing, and an unknown commune is the
-- same kind of gap.
--
-- Safe to re-run.
-- =====================================================================

ALTER TABLE cases
    ADD COLUMN IF NOT EXISTS commune TEXT;


-- Deadline queries filter by canton and commune together: "which cases
-- in Sierre have a renewal window opening". Partial, because the column
-- is NULL on every case that predates this migration.
CREATE INDEX IF NOT EXISTS idx_cases_commune
    ON cases (tenant_id, canton, commune)
    WHERE commune IS NOT NULL;


COMMENT ON COLUMN cases.commune IS
    'The Valais commune this case registers in. Drives the renewal '
    'window and the correspondence language, both of which differ '
    'between communes within the same canton. Free text: no verified '
    'commune registry exists yet, and a constrained list would have to '
    'be invented. NULL means not recorded.';
