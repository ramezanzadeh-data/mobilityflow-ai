-- =====================================================================
-- Migration 0001 (up): enforce task idempotency at the database level.
--
-- Problem
-- -------
-- `tasks` had no uniqueness guarantee at all. Every AI Operator run and
-- every agent tool call re-inserted the same follow-up task, producing
-- rows like:
--
--     Collect Commune Registration Form
--     Collect Commune Registration Form
--     Collect Commune Registration Form
--
-- Application-side "SELECT then INSERT if absent" checks cannot fix this:
-- two concurrent operator runs both see "absent" and both insert.
--
-- Solution
-- --------
-- A partial UNIQUE index makes the duplicate physically impossible, and
-- gives INSERT ... ON CONFLICT a stable arbiter so add_task() can be a
-- single atomic, race-free statement.
--
-- Business key: (case_id, normalised title) restricted to ACTIVE tasks.
--
--   * case_id  - a task only ever belongs to one case, and case_id is
--                globally unique, so tenant_id adds nothing to the key.
--   * title    - normalised (whitespace collapsed, trimmed, lower-cased)
--                so "Collect  Passport" and "collect passport" are the
--                same business fact. The original spelling is still what
--                is stored and displayed; only the index key is folded.
--   * active   - the predicate `status IS DISTINCT FROM 'DONE'` keeps
--                completed history intact and, more importantly, still
--                allows a task to legitimately re-open later: if a
--                document is provided (task DONE) and then expires or is
--                rejected, the operator must be able to raise the task
--                again. A non-partial unique index would silently
--                suppress that and hide real outstanding work.
--                NULL status is treated as active (IS DISTINCT FROM).
--
-- This script is idempotent and safe to re-run.
--
-- Transactions: this file intentionally contains no BEGIN/COMMIT so it
-- can be executed inside the application's existing migration
-- transaction (db.database.init_db). Run standalone with:
--     psql --single-transaction -f 0001_tasks_unique_active_title.up.sql
--
-- Large tables: steps 1-2 take a brief ROW EXCLUSIVE lock and step 3
-- takes a SHARE lock on `tasks`. On a very large installation, create
-- the index ahead of time outside a transaction with
-- CREATE UNIQUE INDEX CONCURRENTLY (same name and definition as step 3)
-- and this script will then no-op on step 3.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Step 1 - preserve reminder data before collapsing duplicates.
--
-- The surviving row is the oldest (lowest id). If the survivor has no
-- due_date but a duplicate does, carry the earliest due_date over so the
-- de-duplication never silently drops an existing reminder. due_date is
-- stored as an ISO-8601 TEXT value, for which lexicographic MIN() is
-- also the chronological minimum.
-- ---------------------------------------------------------------------
WITH active_tasks AS (
    SELECT
        id,
        case_id,
        lower(btrim(regexp_replace(title, '\s+', ' ', 'g'))) AS title_key,
        due_date
    FROM tasks
    WHERE status IS DISTINCT FROM 'DONE'
),
survivors AS (
    SELECT case_id, title_key, min(id) AS keep_id
    FROM active_tasks
    GROUP BY case_id, title_key
    HAVING count(*) > 1
),
earliest_due AS (
    SELECT case_id, title_key, min(due_date) AS due_date
    FROM active_tasks
    WHERE due_date IS NOT NULL
    GROUP BY case_id, title_key
)
UPDATE tasks AS t
SET due_date = e.due_date
FROM survivors AS s
JOIN earliest_due AS e
     ON e.case_id = s.case_id
    AND e.title_key = s.title_key
WHERE t.id = s.keep_id
  AND t.due_date IS NULL;


-- ---------------------------------------------------------------------
-- Step 2 - collapse existing duplicates, keeping exactly one row per
-- (case_id, normalised title) among active tasks. The lowest id wins:
-- it is the original task, so any external reference or audit entry that
-- already points at a task id keeps resolving.
-- ---------------------------------------------------------------------
WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                case_id,
                lower(btrim(regexp_replace(title, '\s+', ' ', 'g')))
            ORDER BY id
        ) AS row_rank
    FROM tasks
    WHERE status IS DISTINCT FROM 'DONE'
)
DELETE FROM tasks
WHERE id IN (SELECT id FROM ranked WHERE row_rank > 1);


-- ---------------------------------------------------------------------
-- Step 3 - the constraint itself.
--
-- Implemented as a partial UNIQUE INDEX rather than a UNIQUE table
-- constraint because PostgreSQL table constraints support neither an
-- expression key nor a WHERE predicate. The index is a first-class
-- arbiter for INSERT ... ON CONFLICT, which is what makes add_task()
-- race-free.
-- ---------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_case_title
ON tasks (
    case_id,
    (lower(btrim(regexp_replace(title, '\s+', ' ', 'g'))))
)
WHERE status IS DISTINCT FROM 'DONE';


COMMENT ON INDEX uq_tasks_active_case_title IS
    'Idempotency guard: at most one ACTIVE task per (case_id, normalised title). '
    'Arbiter for the ON CONFLICT clause in db.database.add_task().';
