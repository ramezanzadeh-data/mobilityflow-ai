# Changelog

## [Unreleased] — Make host-side configuration deterministic (P0, Correctness)

### Summary

Running the test suite on a developer machine produced results that depended
on which PostgreSQL server happened to answer, and which entry point was used.
Four independent defects were stacked on top of each other, each masking the
next. All four are fixed, and the suite is green (144/144) from a bare
`python -m pytest`.

The application's runtime behaviour under Docker Compose is unchanged. Every
fix targets the path where a process runs **directly on the host**, which was
the only unconfigured path.

---

## What changed

### 1. `bootstrap/environment.py`, `bootstrap/__init__.py` — NEW

**The root cause.** Only `conftest.py` loaded `.env`. Nothing else did.

So `python -m pytest` reached the containerised database, while
`python -m scripts.migrate` loaded no configuration at all, fell through to
`db.database._build_pool()`'s `localhost:5432` defaults, and migrated a
*different server* — printing `Database migration completed.` the whole time.
The migration was real; it just landed somewhere nobody was looking.

`.env` is now loaded in exactly one place, called by every entry point:

| Entry point | |
|---|---|
| `conftest.py` | pytest |
| `scripts/migrate.py` | **was silently migrating the wrong database** |
| `scripts/manage_users.py` | could have created accounts in the wrong database |
| `scripts/diagnose_*.py` | |
| `apps/web/app.py`, `apps/api/main.py`, `workers/celery_app.py` | direct (non-Compose) runs |

Precedence is **real environment > `.env` > per-module defaults**.
`override=False` guarantees the first step, so a variable exported by CI or
injected by Compose always wins over the file. That is what makes the call
safe to make unconditionally — inside a container it is a no-op.

The call sites deliberately sit **above** the other imports, marked
`# noqa: E402`. `db/database.py`, `auth/jwt.py` and `auth/encryption.py` all
read configuration at *import* time, so a load placed after them is too late.
This is the only place in the codebase where import order carries meaning, and
it is commented as such in each file.

Domain and library modules must not call `load_environment()`. Loading
configuration is a composition-root concern; a module that mutates the process
environment on import is untestable and order-dependent.

**The package is named `bootstrap`, not `config`, deliberately.**
`apps/web/config/` already exists, and Streamlit puts the running script's own
directory (`apps/web/`) at the front of `sys.path`. A top-level `config`
package is therefore shadowed by `apps.web.config` inside the Streamlit
process, and `from config import load_environment` raises `ImportError` at
runtime — while passing the entire test suite, because pytest puts the
repository root first. Do not rename this package to `config`.

### 2. `docker-compose.yml` — Postgres published on `127.0.0.1:5433`

A natively installed `postgresql-x64-18` Windows service already owned 5432.
Windows permits two processes to bind `0.0.0.0:5432` at once and resolves
incoming connections by bind order, so the collision never failed loudly — it
silently routed the app to the wrong server, and could flip after any
unrelated restart. That is what made the symptom look intermittent across days.

A dedicated port removes the ambiguity without touching a machine-wide service
that other projects may depend on.

Bound to `127.0.0.1` rather than `0.0.0.0`: nothing off-machine has any reason
to reach the database directly, and the previous binding exposed it to the
whole LAN.

**Containers are unaffected** — they reach Postgres over the Compose network at
`postgres:5432`, which is independent of the published host port.

### 3. `.env` / `.env.example` — host-side values, and a rotated password

`.env` held container-network values that were meaningless on the host and had
no effect inside containers either, because `docker-compose.yml` sets them
itself:

| Variable | Was | Now |
|---|---|---|
| `PGHOST` | `postgres` (Compose service name) | `localhost` |
| `PGPORT` | *(unset)* | `5433` |
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | *(commented out)* |

`OLLAMA_HOST` is deliberately left unset. `docker-compose.yml` already defaults
it to `${OLLAMA_HOST:-http://host.docker.internal:11434}`, so containers get
the Docker-only hostname and host processes fall back to
`core.ai.ollama_client.DEFAULT_OLLAMA_HOST` (`http://localhost:11434`). One
unset variable is correct in both contexts; setting it makes one of them wrong.

**Password rotation.** `PGPASSWORD` was the placeholder `change_me`, which had
never been applied: the `pgdata` volume is `external: true` and pre-populated,
and Postgres only honours `POSTGRES_PASSWORD` when initialising an *empty* data
directory. The live password was the weak default `mobilityflow`. It has been
rotated to a 32-character random value via `ALTER USER`, and `.env` now matches
reality.

> **Note for future maintainers:** while the external `pgdata` volume persists,
> `POSTGRES_PASSWORD` in `docker-compose.yml` has no effect on the running
> server. Changing the database password requires an explicit
> `ALTER USER mobilityflow WITH PASSWORD '…'` *plus* the `.env` update. Editing
> `.env` alone will silently lock every client out.

### 4. `.dockerignore` — NEW (secret leak)

`Dockerfile` uses `COPY . .` and there was no `.dockerignore`, so `.env` — with
`JWT_SECRET_KEY`, `ENCRYPTION_KEY` and the database password — was baked into
every image layer. Layer contents are readable by anyone who can pull the
image and cannot be removed by deleting the file in a later layer.

Also excluded: `*.sql` dumps, `.git`, build artefacts, and test caches. Stale
`.pyc` files compiled against a different interpreter are a genuine source of
"works locally, fails in the container" bugs.

### 5. `tests/` — four non-test scripts relocated to `scripts/`

`test_context_builder.py`, `test_ollama.py`, `test_agent.py` and
`test_action_agent.py` contained no `test_*` functions. They were ad-hoc
scripts that opened a database connection and called a live LLM **at module
import time**. pytest collects by filename, so it imported and ran them during
collection — meaning an unreachable backend aborted collection of the entire
144-test suite.

They are now `scripts/diagnose_context_builder.py`, `scripts/diagnose_ollama.py`
and `scripts/diagnose_agent.py` (the last merges the two agent scripts behind a
`--role` flag; the only difference between them was whether an authenticated
caller was supplied). The diagnostic value is kept; test collection is now
hermetic. No test was lost — the collected count is unchanged at 144.

### 6. `requirements.txt`

Added `python-dotenv>=1.0` under Dev/Test.

---

## Verification

```
python -m pytest -v
# 144 passed
```

`tests/project_audit/test_runtime_audit.py::test_environment_variables` and the
seven `tests/test_task_idempotency.py` cases now exercise the configured
database rather than whatever answered first.

---

## [Unreleased] — Fix duplicate Task creation (P0, Data Integrity)

### Summary

The same missing document could produce an unbounded number of identical
follow-up tasks — one more on every AI Operator run and every agent tool call:

```
Collect Commune Registration Form
Collect Commune Registration Form
Collect Commune Registration Form
```

Task creation is now **idempotent, enforced by PostgreSQL**. Creating the same
task for the same case any number of times, from any code path, concurrently or
sequentially, results in exactly one active task.

Nothing else changed: no UI, no translations, no AI prompts, no workflow, no
permissions, no Docker, no authentication, and no API request/response contract.

---

## What changed

### 1. `db/migrations/0001_tasks_unique_active_title.up.sql` — NEW

Three steps, idempotent and safe to re-run:

| Step | Action |
|---|---|
| 1 | Carry the earliest non-`NULL` `due_date` from duplicate rows onto the survivor, so de-duplication never silently drops a reminder. |
| 2 | Delete duplicate **active** rows, keeping the lowest `id` per business key. |
| 3 | Create the partial `UNIQUE` index `uq_tasks_active_case_title`. |

**The business key: `(case_id, normalised title)`, restricted to active tasks.**

```sql
CREATE UNIQUE INDEX uq_tasks_active_case_title
ON tasks (case_id, (lower(btrim(regexp_replace(title, '\s+', ' ', 'g')))))
WHERE status IS DISTINCT FROM 'DONE';
```

Why each part:

- **`case_id`** — a task belongs to exactly one case, and `case_id` is globally
  unique, so `tenant_id` would add nothing. Tenant isolation is already handled
  by the existing RLS policy.
- **normalised `title`** — whitespace collapsed, trimmed, lower-cased, so
  `"Collect  Passport"` and `"collect passport"` are recognised as the same
  business fact. Only the *index key* is folded; the stored title keeps its
  original spelling, so nothing in the UI changes.
- **`WHERE status IS DISTINCT FROM 'DONE'`** — this is the important one. A
  non-partial unique index would permanently block re-raising a task after it
  was completed. That is wrong for this domain: if a document is supplied
  (task `DONE`) and later expires or is rejected, the operator **must** be able
  to raise the task again. The partial predicate keeps completed history intact
  while still guaranteeing at most one *active* task per business key.
  `NULL` status counts as active (`IS DISTINCT FROM` rather than `<>`).

Implemented as a partial unique **index** rather than a table `UNIQUE`
constraint because PostgreSQL table constraints support neither an expression
key nor a `WHERE` predicate. The index is still a first-class `ON CONFLICT`
arbiter, which is what makes step 3 below race-free.

### 2. `db/database.py` — MODIFIED

**`add_task()` is now a single atomic, race-free UPSERT:**

```sql
INSERT INTO tasks (case_id, title, status, tenant_id)
VALUES (%s, %s, %s, %s)
ON CONFLICT (case_id, (lower(btrim(regexp_replace(title, '\s+', ' ', 'g')))))
WHERE status IS DISTINCT FROM 'DONE'
DO UPDATE SET case_id = tasks.case_id
RETURNING id, (xmax = 0) AS created
```

- **No Python-side pre-check.** A `SELECT`-then-`INSERT` cannot fix this defect:
  two concurrent operator runs both observe "absent" and both insert. Integrity
  is enforced by the database.
- **`DO UPDATE` rather than `DO NOTHING`, deliberately.** `DO NOTHING` returns no
  row on conflict, and a fallback `SELECT` could not see a row still uncommitted
  in a concurrent transaction. The no-op `DO UPDATE` blocks on that transaction
  and always `RETURN`s the surviving row, so the caller reliably gets a task id.
- **Existing tasks are never mutated** — status, due date, assignment and title
  spelling are all left exactly as they were.
- **Return value (additive):** `TaskUpsert(task_id, created)`, a `namedtuple`.
  `add_task()` previously returned `None` and no caller consumed its result, so
  this breaks nothing; `created` (via `xmax = 0`) lets callers distinguish a real
  insert from a reuse.

**`_migrate_tasks_table()`** now applies the migration file, so `init_db()` and
`scripts/migrate.py` pick it up through the project's existing migration
mechanism. It executes the checked-in `.sql` file (via the new `_read_migration()`
helper) rather than an inlined copy, so the statements a DBA reviews and can run
manually with `psql` are byte-for-byte the statements the application applies —
the two can never drift.

### 3. `core/ai/operator.py` — MODIFIED (requirement 4)

The AI Operator reuses an existing task instead of creating another one. Only
genuinely new tasks are reported in `result["tasks_created"]`, which makes the
`AI_OPERATOR_RUN` audit entry (`"N task(s) auto-created"`) truthful for the first
time.

Reminder behaviour is unchanged: every task the run touched — newly created *or*
reused — still gets its `due_date` refreshed, exactly as before. The due dates
are now applied via the ids returned by `add_task()` instead of by re-scanning
every task on the case and string-matching titles.

`get_tasks` was dropped from the import list because that re-scan is gone and it
became an unused import (dead-import lint failure otherwise). No behaviour change.

### 4. `core/ai/tools.py` — MODIFIED (requirement 5)

`create_task_for_case()` reports reuse honestly:

> `Task already exists for case 42: 'Collect Passport' (task #17). No duplicate was created.`

Only the tool's **return string** changed — not the tool schema, not the system
prompt, not `TOOLS_LIST`. This matters behaviourally: telling the model a task was
"created" when it was not invites a retry, which is one of the ways duplicates
were generated in the first place.

### 5. `apps/api/routes/tasks.py` — MODIFIED

> Flagged per instructions: this file is not strictly required to change, but
> leaving it would have left a latent correctness bug that the fix makes
> reachable.

`POST /tasks` used to locate the row it had just written by re-querying and
taking the **last title match**. Now that a title can legitimately be carried by
both a completed and an active task, that lookup can return the `DONE` task —
wrong id and wrong status in the `201` body. It now resolves the row by the id
`add_task()` returns, which is also one fewer race.

**The API contract is unchanged:** same path, same request model, same
`TaskItem` response model, same `201` status code. A repeated `POST` of an
identical task returns `201` with the existing task rather than creating a
duplicate.

### 6. `tests/test_task_idempotency.py` — NEW

Seven regression tests against a real PostgreSQL instance (a mocked database
would prove nothing, since the guarantee under test *is* a database guarantee):

- repeated `add_task()` creates exactly one task;
- casing/whitespace variants collapse to one task;
- genuinely different titles still create separate tasks;
- a `DONE` task can be legitimately raised again;
- reuse does not mutate the existing task (requirement 6);
- **8 concurrent threads in overlapping transactions produce exactly one row**;
- the unique index exists and is partial (fails loudly if the migration is ever
  dropped, rather than letting duplicates quietly return).

---

## Separate change (not part of the P0 fix)

### `tests/project_audit/test_runtime_audit.py` — MODIFIED

`test_environment_variables()` asserted that `PGHOST`, `PGDATABASE`, `PGUSER` and
`PGPASSWORD` were all set. That contradicts `db.database._build_pool()`, which
accepts **either** `DATABASE_URL` **or** the individual `PG*` variables — so the
audit failed on a correctly configured `DATABASE_URL` deployment.

The test now mirrors the real contract: secrets are required in both modes, and
the `PG*` set is only demanded when `DATABASE_URL` is absent. An *incomplete*
`PG*` set is still a failure — `_build_pool()` would fall back to its
`localhost`/`mobilityflow` development defaults, and depending on those in a real
deployment is precisely the misconfiguration this audit exists to catch.

Verified across all five combinations: `DATABASE_URL` only (pass), full `PG*`
only (pass), neither (fail), partial `PG*` (fail), both (pass).

This is unrelated to the duplicate-task defect and is listed separately so it can
be reviewed, or reverted, on its own.

---

## Migration strategy

The project has no Alembic; `init_db()` in `db/database.py` is the migration
mechanism. This change follows that existing pattern rather than introducing a
migration framework as a side effect of a P0 fix.

**To deploy:**

```bash
python -m scripts.migrate          # or any normal app start, which calls init_db()
```

**Or apply manually, reviewed by a DBA:**

```bash
psql "$DATABASE_URL" --single-transaction \
     -f db/migrations/0001_tasks_unique_active_title.up.sql
```

Notes:

- **Existing databases with duplicates succeed.** Steps 1–2 clean the data before
  step 3 adds the constraint. Verified against a live PostgreSQL 16 instance
  seeded with exact duplicates, whitespace/case variants, a `DONE` row, a `NULL`
  status row and a second tenant's case.
- **Re-running is a no-op** (`UPDATE 0`, `DELETE 0`, index already exists).
- **The `.sql` file contains no `BEGIN`/`COMMIT`** so it can run inside the
  application's existing migration transaction. Use `--single-transaction` when
  running it standalone.
- **Locking:** steps 1–2 take `ROW EXCLUSIVE`, step 3 takes `SHARE` on `tasks`.
  For a very large installation, pre-create the index outside a transaction with
  `CREATE UNIQUE INDEX CONCURRENTLY` using the same name and definition; step 3
  then no-ops via `IF NOT EXISTS`.
- **Rows deleted in step 2 carry no unique information** — identical `case_id`,
  `title`, `status` and `tenant_id`, with any `due_date` preserved onto the
  survivor by step 1. The lowest `id` survives, so any audit entry or external
  reference already pointing at a task id keeps resolving.

---

## Rollback notes

```bash
psql "$DATABASE_URL" --single-transaction \
     -f db/migrations/0001_tasks_unique_active_title.down.sql
```

- **The schema change is fully reversible.** Dropping the index restores the
  previous unconstrained behaviour.
- **Roll back the application code together with the migration.** `add_task()`'s
  `ON CONFLICT` clause needs this index as its arbiter; without the index the
  statement raises `InvalidColumnReference`. Do not deploy the down migration
  against the new code.
- **The step-2 data deletion is not reversible.** Nothing of business value is
  lost (see above), but if the environment requires byte-for-byte restorability,
  snapshot first:
  ```sql
  CREATE TABLE tasks_backup_0001 AS SELECT * FROM tasks;
  ```

---

## Known interaction (deliberately not changed — requires a product decision)

If a case ends up with a `DONE` task **and** an active task sharing the same
normalised title (a legitimate state under the partial index), then re-opening
the completed one — un-ticking its checkbox in the case detail view, which calls
`update_task(id, 'PENDING')` — would violate the unique index.

This was left alone on purpose: requirement 6 explicitly forbids changing task
status behaviour, and the fix is a product decision rather than a mechanical one.
Recommended follow-up, as a separate change:

- have `update_task()` merge into the existing active task instead of raising, or
- hide the re-open control while an active twin exists.

## Verification performed

- PostgreSQL 16.2, real instance.
- Migration applied to a database pre-seeded with duplicates: 3 duplicates
  collapsed to 1, earliest `due_date` preserved, `DONE` row retained, other
  tenant's case untouched; re-run was a clean no-op.
- `init_db()` run twice against a fresh database — succeeds and is idempotent.
- Up → down → up cycle verified.
- AI Operator run three times over the same case with two missing documents:
  2 tasks after run 1, 0 new tasks on runs 2 and 3, 2 rows total, reminders
  still refreshed.
- Agent tool, `core.tasks.service.create_task` and the API route all verified to
  converge on the same single task id.
- 8-thread concurrency test: one insert, seven reuses, one row, zero errors.
- Full existing test suite: **144 passed** (with `DATABASE_URL` configured) (excluding `tests/test_ollama.py`,
  which needs a live Ollama server).
