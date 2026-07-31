import os
import contextvars
import json
import logging
from collections import namedtuple
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool


# Named for this module, so an operator can raise or lower the verbosity
# of database-layer messages without touching anything else.
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "migrations"
)

_POOL = None

# Holds the tenant_id for the current request/session. This is a
# contextvars.ContextVar (not a plain module global) specifically because
# it must isolate correctly across concurrent asyncio requests in FastAPI -
# a global or thread-local would leak one tenant's context into another
# request handled on the same thread.
_current_tenant_id = contextvars.ContextVar("current_tenant_id", default=None)


def set_current_tenant(tenant_id):
    """
    Called once per authenticated request (API) or once after login
    (Streamlit) so that every DB connection checked out afterwards is
    pinned to this tenant at the database level via Postgres RLS -
    independent of whether the calling route/page also remembered to
    check tenant_id itself.
    """
    _current_tenant_id.set(int(tenant_id) if tenant_id is not None else None)


def clear_current_tenant():
    _current_tenant_id.set(None)


def _build_pool():

    if DATABASE_URL:
        return SimpleConnectionPool(1, 20, dsn=DATABASE_URL)

    return SimpleConnectionPool(
        1,
        20,
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "mobilityflow"),
        user=os.environ.get("PGUSER", "mobilityflow"),
        password=os.environ.get("PGPASSWORD", "mobilityflow"),
    )


def _get_pool():

    global _POOL

    if _POOL is None:
        _POOL = _build_pool()

    return _POOL


@contextmanager
def get_db_connection():
    """
    The single connection-acquisition point for the whole app. Every
    function in this module goes through this instead of opening its
    own connection, so pooling, commit/rollback, and DB configuration
    all live in exactly one place.

    Also pins the Postgres session to the current tenant (via SET LOCAL,
    scoped to just this transaction) so Row-Level Security policies on
    the tenant-scoped tables enforce isolation even if application code
    forgets to filter by tenant_id. When no tenant is set (background
    workers, migrations, bootstrap, or a superadmin/API-key client) the
    session is left unrestricted - see _TENANT_SCOPED_TABLES below.
    """

    pool = _get_pool()
    conn = pool.getconn()

    try:
        c = conn.cursor()

        tenant_id = _current_tenant_id.get()

        if tenant_id is not None:
            # GUC custom settings can't be parameterized with %s - this is
            # safe because tenant_id is coerced through int() in
            # set_current_tenant(), so only digits ever reach the string.
            c.execute(f"SET LOCAL app.current_tenant_id = '{int(tenant_id)}'")
        else:
            c.execute("SET LOCAL app.current_tenant_id = ''")

        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        pool.putconn(conn)


ALLOWED_CASE_COLUMNS = {
    "employee_name",
    "nationality",
    "canton",
    "permit",
    "business_mode",
    "employer",
    "status",
    "workflow_state",
    "risk_level",
    "ai_summary",
    "company",
    "assigned_to",
    "created_at",
    "case_history",
    "audit_log",
    # Statutory trigger dates (migration 0003). Whitelisted here so
    # update_case() can write them; without this entry an edit would be
    # silently dropped rather than rejected.
    "arrival_date",
    "contract_start_date",
    "permit_expiry_date",
}


# Positions in a row returned by load_case(), which is the only query
# these are read from.
#
# They previously described a `SELECT * FROM cases` row instead, and
# load_case() does not select *. It lists its columns explicitly and did
# not list the date columns at all, so index 16 - meant to be
# arrival_date - was tenant_id, and 17 and 18 were off the end of the
# row. case_statutory_dates() therefore returned an integer tenant id as
# the arrival date, parse_date() correctly rejected it, and every
# statutory obligation in the product reported "date not recorded".
#
# The whole deadline engine was wired to nothing, and nothing failed:
# "we have no arrival date for this case" is a legitimate answer the
# engine is designed to give, so it looked like missing data rather than
# a broken read.
#
# Named constants are not what makes this safe - they were named before
# and still wrong. test_case_row_indices.py is what makes it safe: it
# parses load_case()'s own SELECT and fails if a constant stops matching
# the column it names.
CASE_INDEX_ARRIVAL_DATE = 17
CASE_INDEX_CONTRACT_START_DATE = 18
CASE_INDEX_PERMIT_EXPIRY_DATE = 19
CASE_INDEX_CORRESPONDENCE_LANGUAGE = 20
CASE_INDEX_COMMUNE = 21


def case_statutory_dates(case_row):
    """
    Extract the trigger dates from a case row, tolerating short rows.

    Returns a mapping shaped for
    core.rules.obligations.build_obligations(trigger_dates=...). A row
    fetched before migration 0003, or by a query that selects fewer
    columns, yields None for each - which the engine reports honestly as
    "date not recorded" instead of guessing.
    """

    def at(index):
        if case_row is None or len(case_row) <= index:
            return None
        return case_row[index]

    return {
        "arrival_date": at(CASE_INDEX_ARRIVAL_DATE),
        "contract_start_date": at(CASE_INDEX_CONTRACT_START_DATE),
        "permit_expiry_date": at(CASE_INDEX_PERMIT_EXPIRY_DATE),
    }


def case_fields(case_row):
    """
    A case row as a mapping of column name to value.

    Exists so that code outside this module can read a case by name
    instead of by position. Positional access to case rows has already
    produced one silent defect here - CASE_INDEX_ARRIVAL_DATE pointed at
    tenant_id for as long as the statutory dates feature existed, and
    every deadline reported "date not recorded" while looking correct.

    The leading columns come from the CREATE TABLE and have never moved;
    the trailing ones are read through the CASE_INDEX_* constants, which
    tests/test_case_row_indices.py checks against load_case()'s own
    SELECT. Short rows yield None rather than raising, matching
    case_statutory_dates() above.
    """

    def at(index):
        if case_row is None or len(case_row) <= index:
            return None
        return case_row[index]

    return {
        "id": at(0),
        "employee_name": at(1),
        "nationality": at(2),
        "canton": at(3),
        "permit": at(4),
        "business_mode": at(5),
        "employer": at(6),
        "status": at(7),
        "workflow_state": at(8),
        "risk_level": at(9),
        "arrival_date": at(CASE_INDEX_ARRIVAL_DATE),
        "contract_start_date": at(CASE_INDEX_CONTRACT_START_DATE),
        "permit_expiry_date": at(CASE_INDEX_PERMIT_EXPIRY_DATE),
        "correspondence_language": at(CASE_INDEX_CORRESPONDENCE_LANGUAGE),
        "commune": at(CASE_INDEX_COMMUNE),
    }


def init_db():

    with get_db_connection() as conn:

        c = conn.cursor()


        c.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id SERIAL PRIMARY KEY,
            employee_name TEXT,
            nationality TEXT,
            canton TEXT,
            permit TEXT,
            business_mode TEXT,
            employer TEXT,
            status TEXT,
            workflow_state TEXT,

            risk_level INTEGER,
            ai_summary TEXT,

            company TEXT,
            assigned_to TEXT,

            created_at TEXT,

            case_history TEXT,
            audit_log TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            created_at TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            case_id INTEGER,
            title TEXT,
            status TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            case_id INTEGER,
            name TEXT,
            status TEXT,

            file_path TEXT,
            extracted_text TEXT,
            extracted_fields TEXT,
            ocr_method TEXT,
            ocr_confidence TEXT,
            uploaded_at TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT,
            password TEXT,
            role TEXT,
            company TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS case_events (
            id SERIAL PRIMARY KEY,
            case_id INTEGER,
            event_type TEXT,
            description TEXT,
            created_at TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS saved_filters (
            id SERIAL PRIMARY KEY,
            company TEXT,
            name TEXT,
            filter_json TEXT,
            created_at TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS email_templates (
            id SERIAL PRIMARY KEY,
            company TEXT,
            name TEXT,
            subject TEXT,
            body TEXT,
            created_at TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS security_audit_log (
            id SERIAL PRIMARY KEY,
            username TEXT,
            action TEXT,
            detail TEXT,
            success INTEGER,
            created_at TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS webhooks (
            id SERIAL PRIMARY KEY,
            company TEXT,
            url TEXT,
            event_type TEXT,
            secret TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            description TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            role TEXT,
            permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
            PRIMARY KEY (role, permission_id)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id SERIAL PRIMARY KEY,
            username TEXT,
            token_hash TEXT UNIQUE,
            tenant_id INTEGER,
            issued_at TEXT,
            expires_at TEXT,
            revoked INTEGER DEFAULT 0,
            user_agent TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS background_jobs (
            task_id TEXT PRIMARY KEY,
            task_name TEXT,
            tenant_id INTEGER,
            created_by TEXT,
            status TEXT DEFAULT 'PENDING',
            created_at TEXT,
            updated_at TEXT
        )
        """)

        # tenant_id comes first, before any other migration runs.
        #
        # It is the one column the rest of this function builds on:
        # migration 0003 creates indexes on cases (tenant_id, ...) and
        # _enable_row_level_security() writes the tenant_isolation policy
        # against it on every table in _RLS_TABLES. Anything below may
        # reference it, so nothing below can run before it exists.
        #
        # This used to sit five lines further down, which passed on every
        # existing database - there tenant_id predates all of these
        # migrations - and failed on every empty one with
        #
        #     psycopg2.errors.UndefinedColumn:
        #     column "tenant_id" does not exist
        #
        # i.e. it worked everywhere except a customer's first deployment.
        # scripts/verify_fresh_install.py is what catches that class of
        # ordering defect, and CI runs it on every commit.
        _migrate_add_tenant_id_columns(c)

        _migrate_documents_table(c)
        _migrate_tasks_table(c)
        _migrate_users_table(c)
        _migrate_case_statutory_dates(c)
        _migrate_case_correspondence_language(c)
        _migrate_case_commune(c)
        # Must run before _enable_row_level_security(): that function
        # applies the tenant_isolation policy to every table in
        # _RLS_TABLES, and this one is in that list.
        _migrate_tenant_value_assumptions(c)
        # Also in _RLS_TABLES, and its foreign key needs `webhooks` to
        # exist - which it does, from the CREATE TABLE block above.
        _migrate_webhook_outbox(c)
        # Its foreign key needs `refresh_tokens`, created in the block
        # above. Deliberately not in _RLS_TABLES - see the migration file.
        _migrate_session_handoff(c)
        _migrate_session_idle_timeout(c)
        _enable_row_level_security(c)
        _seed_default_rbac(c)

        c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
        ON users(username)
        """)

    with get_db_connection() as conn:
        _backfill_tenant_ids(conn)

    ensure_bootstrap_admin()


def _migrate_documents_table(c):

    new_columns = [
        ("file_path", "TEXT"),
        ("extracted_text", "TEXT"),
        ("extracted_fields", "TEXT"),
        ("ocr_method", "TEXT"),
        ("ocr_confidence", "TEXT"),
        ("uploaded_at", "TEXT"),
    ]

    for column_name, column_type in new_columns:
        c.execute(
            f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
        )


def _read_migration(filename):
    """
    Loads a checked-in .sql migration from db/migrations/.

    The SQL lives in a file rather than inline in this module so that the
    same statements a DBA reviews and can run manually with psql are the
    exact statements the application applies - there is only one copy, so
    the two can never drift apart.
    """

    path = os.path.join(MIGRATIONS_DIR, filename)

    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _migrate_tasks_table(c):

    c.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date TEXT")

    # Task idempotency: de-duplicates any pre-existing rows and creates
    # the partial UNIQUE index that add_task() uses as its ON CONFLICT
    # arbiter. Idempotent and safe to re-run - see the file header for
    # the business key and the reasoning behind it.
    #
    # psycopg2 executes a multi-statement script in a single round trip
    # and performs no %-interpolation when no parameters are passed.
    c.execute(_read_migration("0001_tasks_unique_active_title.up.sql"))


def _migrate_case_statutory_dates(c):

    # Arrival, contract start and permit expiry. These are the trigger
    # dates core/rules/obligations.py needs; without them every statutory
    # deadline is reported as "date not recorded" rather than computed.
    # DATE rather than TEXT deliberately - see the file header.
    c.execute(_read_migration("0003_case_statutory_dates.up.sql"))


def _migrate_tenant_value_assumptions(c):

    # Per-tenant manual-effort and cost baselines for the value
    # realisation report. Idempotent - see the file header for why the
    # table exists and why hourly_cost is NULLable.
    c.execute(_read_migration("0002_tenant_value_assumptions.up.sql"))

    # Customer-stated platform cost, for the value/cost ratio. Separate
    # migration rather than an edit to 0002: 0002 has already been applied
    # to a live database, and rewriting an applied migration means the
    # file no longer describes what actually ran.
    c.execute(_read_migration("0004_platform_cost.up.sql"))


def _migrate_users_table(c):

    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret TEXT")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled INTEGER DEFAULT 0")


def _migrate_case_correspondence_language(c):
    """
    Add the language a case's letters must be written in.

    Separate from the user's interface language, which lives in the
    session. See core/correspondence.py and the migration file for why
    Valais makes the distinction unavoidable rather than academic.
    """

    c.execute(_read_migration("0006_case_correspondence_language.up.sql"))


def _migrate_case_commune(c):
    """
    Add the commune a case registers in.

    Found necessary by tracing the obligation rules to their sources:
    Valais communes publish different renewal windows and administer in
    different languages, so neither can be computed from the canton
    alone. See the migration file.
    """

    c.execute(_read_migration("0007_case_commune.up.sql"))


def _migrate_webhook_outbox(c):
    """
    Create the transactional outbox that webhook delivery runs through.

    See the migration file for why the previous design - commit the case
    event, then publish to the broker on the next line - could lose a
    notification with nothing recording that it had been owed.
    """

    c.execute(_read_migration("0005_webhook_outbox.up.sql"))


def _migrate_session_handoff(c):
    """
    Create the one-time codes that move a browser session into a cookie.

    Streamlit cannot set an HttpOnly cookie; only the API can. See the
    migration file for why the session token itself must not be the thing
    that crosses the browser to get there.
    """

    c.execute(_read_migration("0008_session_handoff.up.sql"))


def _migrate_session_idle_timeout(c):
    """
    Record when a browser session was last used.

    Durable sessions meant closing the window stopped being a logout. See
    the migration file for why this is a separate column rather than a
    shorter expires_at.
    """

    c.execute(_read_migration("0009_session_idle_timeout.up.sql"))


_TENANT_SCOPED_TABLES = [
    "cases",
    "tasks",
    "documents",
    "users",
    "case_events",
    "saved_filters",
    "email_templates",
    "webhooks",
    "security_audit_log",
]


def _migrate_add_tenant_id_columns(c):

    for table_name in _TENANT_SCOPED_TABLES:
        c.execute(
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS tenant_id INTEGER"
        )


# users and security_audit_log are deliberately excluded: login has to
# look a user up by username before their tenant is known, so those two
# tables stay app-scoped rather than DB-scoped. Everything that only
# ever gets queried already knowing which case/tenant it belongs to goes
# here, so a route-level bug that forgets a tenant check still can't
# read or write another tenant's rows - the database refuses it.
_RLS_TABLES = [
    "cases",
    "tasks",
    "documents",
    "case_events",
    "saved_filters",
    "email_templates",
    "webhooks",
    "background_jobs",
    # Holds each customer's stated internal cost base, which is
    # commercially sensitive: it must never be readable across tenants.
    # Registered here rather than carrying its own policy so there is one
    # definition of tenant_isolation - see the migration file.
    "tenant_value_assumptions",
    # Rows carry the full case payload that was, or is about to be, sent
    # to a customer's endpoint. Everything true of `cases` is true here.
    "webhook_outbox",
]


def _enable_row_level_security(c):

    for table_name in _RLS_TABLES:

        c.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        # FORCE is required too - by default a table's OWNER (the role
        # our own app connects as) bypasses RLS entirely, which would
        # make the policy below pure decoration.
        c.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

        c.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")

        c.execute(f"""
        CREATE POLICY tenant_isolation ON {table_name}
        USING (
            current_setting('app.current_tenant_id', true) = ''
            OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::integer
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', true) = ''
            OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::integer
        )
        """)


_ALL_PERMISSIONS = [
    ("cases:view", "View case details"),
    ("cases:edit", "Create and edit cases"),
    ("cases:delete", "Delete cases"),
    ("documents:view", "View documents and extracted text"),
    ("documents:edit", "Upload and update documents"),
    ("tasks:view", "View follow-up tasks"),
    ("tasks:edit", "Create and update follow-up tasks"),
    ("reports:export", "Export PDF/Excel reports"),
    ("users:manage", "Create users and manage accounts"),
    ("webhooks:manage", "Create and manage webhooks"),
    ("templates:manage", "Create and manage email templates"),
    ("audit:view", "View the security audit log"),
    ("ai:use", "Use AI features (recommendations, agent, document generation)"),
    ("cases:approve", "Approve a relocation case"),
    ("cases:reject", "Reject a relocation case"),
    ("cases:close", "Close a relocation case"),
    ("cases:archive", "Archive a relocation case"),
    ("tasks:assign", "Assign or reassign a follow-up task or case"),
]

# The enterprise RBAC role matrix. ADMIN is the only role wired to every
# permission - everything else is deliberately scoped down. Adding a new
# role or changing what a role can do means editing this table, not
# scattering role-string checks through route code.
_ROLE_PERMISSIONS = {
    "ADMIN": [name for name, _ in _ALL_PERMISSIONS],
    "MANAGER": [
        "cases:view", "cases:edit", "cases:approve",
        "cases:reject", "cases:close", "cases:archive",
        "documents:view", "documents:edit",
        "tasks:view", "tasks:edit", "tasks:assign",
        "reports:export",
        "templates:manage",
        "ai:use",
    ],
    "STAFF": [
        "cases:view", "cases:edit",
        "documents:view", "documents:edit",
        "tasks:view", "tasks:edit",
        "ai:use",
    ],
    "VIEWER": [
        "cases:view",
        "documents:view",
        "tasks:view",
    ],
}


def _seed_default_rbac(c):

    for name, description in _ALL_PERMISSIONS:
        c.execute("""
        INSERT INTO permissions (name, description) VALUES (%s, %s)
        ON CONFLICT (name) DO NOTHING
        """, (name, description))

    for role, permission_names in _ROLE_PERMISSIONS.items():
        for permission_name in permission_names:
            c.execute("""
            INSERT INTO role_permissions (role, permission_id)
            SELECT %s, id FROM permissions WHERE name=%s
            ON CONFLICT DO NOTHING
            """, (role, permission_name))


def _backfill_tenant_ids(conn):

    c = conn.cursor()

    c.execute("SELECT DISTINCT company FROM cases WHERE company IS NOT NULL")
    companies = {row[0] for row in c.fetchall()}

    c.execute("SELECT DISTINCT company FROM users WHERE company IS NOT NULL")
    companies |= {row[0] for row in c.fetchall()}

    for company in companies:
        tenant_id = get_or_create_tenant(company)

        c.execute(
            "UPDATE cases SET tenant_id=%s WHERE company=%s AND tenant_id IS NULL",
            (tenant_id, company)
        )
        c.execute(
            "UPDATE users SET tenant_id=%s WHERE company=%s AND tenant_id IS NULL",
            (tenant_id, company)
        )
        c.execute(
            "UPDATE saved_filters SET tenant_id=%s WHERE company=%s AND tenant_id IS NULL",
            (tenant_id, company)
        )
        c.execute(
            "UPDATE email_templates SET tenant_id=%s WHERE company=%s AND tenant_id IS NULL",
            (tenant_id, company)
        )
        c.execute(
            "UPDATE webhooks SET tenant_id=%s WHERE company=%s AND tenant_id IS NULL",
            (tenant_id, company)
        )

    c.execute("""
    UPDATE tasks
    SET tenant_id = (SELECT tenant_id FROM cases WHERE cases.id = tasks.case_id)
    WHERE tenant_id IS NULL
    """)

    c.execute("""
    UPDATE documents
    SET tenant_id = (SELECT tenant_id FROM cases WHERE cases.id = documents.case_id)
    WHERE tenant_id IS NULL
    """)

    c.execute("""
    UPDATE case_events
    SET tenant_id = (SELECT tenant_id FROM cases WHERE cases.id = case_events.case_id)
    WHERE tenant_id IS NULL
    """)

    c.execute("""
    UPDATE security_audit_log
    SET tenant_id = (
        SELECT tenant_id FROM users WHERE users.username = security_audit_log.username
    )
    WHERE tenant_id IS NULL
    """)


def get_or_create_tenant(name):

    if not name:
        return None

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT id FROM tenants WHERE name=%s", (name,))
        row = c.fetchone()

        if row:
            return row[0]

        # ON CONFLICT DO NOTHING + RETURNING avoids relying on an
        # exception-driven "insert, catch duplicate, re-select" dance -
        # under concurrent requests two tenants can race to create the
        # same name and this stays correct either way.
        c.execute("""
        INSERT INTO tenants (name, created_at)
        VALUES (%s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'))
        ON CONFLICT (name) DO NOTHING
        RETURNING id
        """, (name,))

        row = c.fetchone()

        if row:
            return row[0]

        c.execute("SELECT id FROM tenants WHERE name=%s", (name,))
        row = c.fetchone()

        return row[0] if row else None


def get_tenant_by_id(tenant_id):

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("SELECT * FROM tenants WHERE id=%s", (tenant_id,))

        row = c.fetchone()

    return dict(row) if row else None


def list_tenants():

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("SELECT * FROM tenants ORDER BY name ASC")

        rows = c.fetchall()

    return [dict(row) for row in rows]


def get_case_tenant_id(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT tenant_id FROM cases WHERE id=%s", (case_id,))

        row = c.fetchone()

    return row[0] if row else None


def username_exists(username):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT COUNT(*) FROM users
        WHERE username=%s
        """, (username,))

        count = c.fetchone()[0]

    return count > 0


# Exported so callers (the CLI, the API) can offer the valid choices
# without importing the permission matrix itself. Derived from
# _ROLE_PERMISSIONS rather than written out again, so a role added to the
# matrix is immediately accepted everywhere and the two cannot drift.
VALID_ROLE_NAMES = sorted(_ROLE_PERMISSIONS)


class UnknownRoleError(ValueError):
    """Raised when a user is created or updated with a role that has no
    entry in the permission matrix."""


def validate_role(role):
    """
    Return the role unchanged, or raise UnknownRoleError.

    The permission matrix is the authority: a role only means something
    if _ROLE_PERMISSIONS grants it something. Anything else is a typo or
    a misunderstanding, and both must fail here rather than downstream.

    Before this existed, an unrecognised role was accepted silently and
    then coerced to a default at every permission check, so "VIEWR"
    became a working account with more rights than the VIEWER that was
    intended - with no error at any point.
    """

    if not role or not str(role).strip():
        raise UnknownRoleError(
            f"A role is required. Valid roles: {sorted(_ROLE_PERMISSIONS)}"
        )

    normalized = str(role).strip().upper()

    if normalized not in _ROLE_PERMISSIONS:
        raise UnknownRoleError(
            f"Unknown role '{role}'. Valid roles: {sorted(_ROLE_PERMISSIONS)}. "
            f"An unrecognised role would be silently downgraded to the "
            f"least-privileged role rather than doing what you intended."
        )

    return normalized


def set_user_role(username, role):
    """
    Change an existing user's role, validating it first.

    Exists so there is a supported way to correct a user whose role
    predates validate_role() - editing the users table by hand is not a
    procedure anyone should have to follow.
    """

    validated = validate_role(role)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE users SET role=%s WHERE username=%s",
            (validated, username),
        )

        updated = c.rowcount

    return updated


def create_user(username, hashed_password, role, company, must_change_password=False):

    # Validated before anything is written: a user whose role means
    # nothing is worse than no user at all, because they appear to work.
    role = validate_role(role)

    tenant_id = get_or_create_tenant(company)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT 1 FROM users WHERE username=%s", (username,))

        if c.fetchone():
            raise ValueError(
                f"Username '{username}' already exists. "
                f"Choose a different username or update the existing user."
            )

        c.execute("""
        INSERT INTO users (username, password, role, company, tenant_id, must_change_password)
        VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            username,
            hashed_password,
            role,
            company,
            tenant_id,
            1 if must_change_password else 0
        ))


def list_users():

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("""
        SELECT username, role, company, tenant_id, must_change_password
        FROM users
        ORDER BY username ASC
        """)

        rows = c.fetchall()

    return [dict(row) for row in rows]


def get_user(username):

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("""
        SELECT *
        FROM users
        WHERE username=%s
        """, (username,))

        user = c.fetchone()

    if user is None:
        return None

    return dict(user)


def ensure_bootstrap_admin():
    """
    The ONLY place in the whole codebase that creates a first admin
    account. There must never be a second competing bootstrap path
    (e.g. a standalone seed script) - that is exactly what caused two
    different admin passwords to exist before. Anything else that needs
    to create or reset a user must go through create_user() /
    update_user_password() directly (see scripts/manage_users.py).
    """

    from auth.password import hash_password

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM users")

        count = c.fetchone()[0]

    if count > 0:
        return

    username = os.environ.get("DEFAULT_ADMIN_USERNAME", "admin")
    password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin")
    company = os.environ.get("DEFAULT_ADMIN_COMPANY", "Default Company")

    create_user(
        username,
        hash_password(password),
        "ADMIN",
        company,
        must_change_password=True,
    )


def update_user_password(username, new_hashed_password):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE users
        SET password=%s, must_change_password=0
        WHERE username=%s
        """, (new_hashed_password, username))

        return c.rowcount > 0


def set_must_change_password(username, value=True):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE users
        SET must_change_password=%s
        WHERE username=%s
        """, (1 if value else 0, username))

        return c.rowcount > 0


def log_case_event(case_id, event_type, description):
    """
    Record a case event and queue the notifications it owes.

    Both happen in one transaction. That is the whole point: a committed
    event always has its outbox rows, and an event that rolls back leaves
    none behind.

    The previous version committed the event and then published to Celery
    on the next line. Between those two statements the notification could
    be lost - broker down, process killed - with nothing recording that
    it had ever been due, and the publish itself ran inside the user's
    request, where Celery's twenty-second default retry loop froze the
    page on every case creation.

    Nothing here touches the network. workers.outbox_tasks delivers.
    """

    tenant_id = get_case_tenant_id(case_id)
    company = get_case_company(case_id)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO case_events (case_id, event_type, description, created_at, tenant_id)
        VALUES (%s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), %s)
        """, (case_id, event_type, description, tenant_id))

        if company:
            _enqueue_webhook_deliveries(
                c,
                tenant_id=tenant_id,
                company=company,
                event_type=event_type,
                payload={
                    "case_id": case_id,
                    "event_type": event_type,
                    "description": description,
                },
            )


def _enqueue_webhook_deliveries(cursor, tenant_id, company, event_type, payload):
    """
    Write one outbox row per subscriber, on the caller's cursor.

    Takes a cursor rather than opening its own connection so the rows
    join the caller's transaction. Opening a second connection here would
    reintroduce exactly the gap this replaced - the event committed, the
    notifications not.

    Subscribers are resolved now rather than at delivery time, so the set
    of recipients is the set that existed when the event happened. A
    webhook registered a minute later does not retroactively receive it,
    which is both the honest reading of a subscription and the one a
    customer can reason about.

    One row per subscriber: each endpoint then succeeds, retries and
    fails independently, and a single broken integration cannot cause
    re-delivery to the others.
    """

    cursor.execute("""
    INSERT INTO webhook_outbox (tenant_id, webhook_id, company, event_type, payload)
    SELECT %s, id, %s, %s, %s::jsonb
    FROM webhooks
    WHERE company = %s
      AND is_active = 1
      AND (event_type = %s OR event_type = 'ALL')
    """, (
        tenant_id,
        company,
        event_type,
        json.dumps(payload),
        company,
        event_type,
    ))


# ---------------------------------------------------------------------
# Webhook outbox relay
# ---------------------------------------------------------------------
#
# Delivery is at-least-once, so the schedule below is about how long a
# customer's endpoint may be down before events start piling up, not
# about whether they arrive. Roughly: a minute, five, fifteen, an hour,
# six hours - then a human is needed.
#
# Growing rather than fixed because the two failure shapes are different.
# A deploy or a restart clears in seconds, and a fixed hourly retry would
# make a ten-second blip look like an hour-long outage to the customer. A
# genuinely broken endpoint, meanwhile, must not be hammered every minute
# for days.

WEBHOOK_RETRY_SCHEDULE_SECONDS = (60, 300, 900, 3600, 21600)

# The schedule holds the gaps *between* attempts, so there is one more
# attempt than there are gaps: try, wait 60s, try, wait 300s, ... try. Six
# attempts spread over roughly seven and a half hours - long enough to
# survive a working morning of downtime, short enough that a genuinely
# dead endpoint is escalated the same day.
WEBHOOK_MAX_ATTEMPTS = len(WEBHOOK_RETRY_SCHEDULE_SECONDS) + 1

# How long a claimed row stays invisible to other relay runs. Comfortably
# longer than one delivery (notifications.REQUEST_TIMEOUT_SECONDS is 5),
# so a slow endpoint is not retried while the first attempt is still in
# flight - but short enough that a relay killed mid-delivery releases its
# work in minutes rather than being lost.
WEBHOOK_CLAIM_LEASE_SECONDS = 120


def claim_due_webhook_deliveries(limit=50):
    """
    Take ownership of up to ``limit`` deliveries that are due now.

    Returns a list of (id, webhook_id, company, event_type, payload,
    attempts).

    FOR UPDATE SKIP LOCKED is what makes this safe to run in several
    workers at once: each transaction takes rows nobody else holds and
    steps over the rest instead of queueing behind them. Without it, two
    relays would either deliver the same row twice or serialise on the
    same lock.

    Claiming pushes next_attempt_at out by a lease rather than holding
    the row locked for the duration of the delivery. An HTTP call can
    take seconds; a database transaction held open across it would block
    writers on this table for as long as the customer's endpoint takes to
    answer.

    The consequence of a lease is that a relay killed after delivering
    but before recording it will deliver again when the lease expires -
    which is why the contract is at-least-once and subscribers are told
    to be idempotent.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        WITH due AS (
            SELECT id
            FROM webhook_outbox
            WHERE status = 'PENDING'
              AND next_attempt_at <= now()
            ORDER BY next_attempt_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE webhook_outbox AS o
        SET attempts = o.attempts + 1,
            next_attempt_at = now() + (%s * INTERVAL '1 second')
        FROM due
        WHERE o.id = due.id
        RETURNING o.id, o.webhook_id, o.company, o.event_type,
                  o.payload, o.attempts
        """, (limit, WEBHOOK_CLAIM_LEASE_SECONDS))

        return c.fetchall()


def mark_webhook_delivered(outbox_id, status_code=None):
    """Record a successful delivery. Terminal - never retried."""

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE webhook_outbox
        SET status = 'DELIVERED',
            delivered_at = now(),
            last_status_code = %s,
            last_error = NULL
        WHERE id = %s
          AND status = 'PENDING'
        """, (status_code, outbox_id))

        return c.rowcount > 0


def mark_webhook_delivery_failed(outbox_id, error, status_code=None):
    """
    Record a failed attempt and schedule the next one.

    Exhausting WEBHOOK_MAX_ATTEMPTS moves the row to FAILED rather than
    deleting it. A notification a customer never received is a fact worth
    keeping: it is the answer to "you never told us about that case", and
    it is what an operator lists when asked what is broken.

    The delay is chosen from the schedule by attempt number, computed in
    SQL against now() so it cannot drift with the application clock.
    """

    attempt_index = None

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "SELECT attempts FROM webhook_outbox WHERE id = %s", (outbox_id,)
        )

        row = c.fetchone()

        if row is None:
            return False

        attempt_index = row[0]

        if attempt_index >= WEBHOOK_MAX_ATTEMPTS:

            c.execute("""
            UPDATE webhook_outbox
            SET status = 'FAILED',
                last_error = %s,
                last_status_code = %s
            WHERE id = %s
            """, (error, status_code, outbox_id))

            return False

        delay = WEBHOOK_RETRY_SCHEDULE_SECONDS[
            min(attempt_index, len(WEBHOOK_RETRY_SCHEDULE_SECONDS)) - 1
        ]

        c.execute("""
        UPDATE webhook_outbox
        SET next_attempt_at = now() + (%s * INTERVAL '1 second'),
            last_error = %s,
            last_status_code = %s
        WHERE id = %s
        """, (delay, error, status_code, outbox_id))

        return True


def cancel_webhook_delivery(outbox_id, reason):
    """
    Stop trying: the subscriber is gone or switched off.

    Distinct from FAILED. FAILED means we could not deliver something the
    customer still wants; CANCELLED means they withdrew the request. An
    operator chasing broken integrations should not be shown the second.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE webhook_outbox
        SET status = 'CANCELLED',
            last_error = %s
        WHERE id = %s
          AND status = 'PENDING'
        """, (reason, outbox_id))

        return c.rowcount > 0


def get_webhook_by_id(webhook_id):
    """One subscriber, or None if it has been deleted."""

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT id, company, url, event_type, secret, is_active, created_at
        FROM webhooks
        WHERE id = %s
        """, (webhook_id,))

        return c.fetchone()


def count_webhook_outbox_by_status(tenant_id=None):
    """
    How many deliveries are pending, delivered, failed and cancelled.

    For an operations view and for support. "Are our integrations
    working?" should be answerable from data.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        if tenant_id is None:
            c.execute("""
            SELECT status, count(*) FROM webhook_outbox GROUP BY status
            """)
        else:
            c.execute("""
            SELECT status, count(*) FROM webhook_outbox
            WHERE tenant_id = %s GROUP BY status
            """, (tenant_id,))

        return dict(c.fetchall())


def get_case_events(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT id, case_id, event_type, description, created_at
        FROM case_events
        WHERE case_id=%s
        ORDER BY created_at ASC, id ASC
        """, (case_id,))

        rows = c.fetchall()

    return rows


def add_case(
    employee_name,
    nationality,
    canton,
    permit,
    business_mode,
    employer,
    company,
    risk_level,
    ai_summary,
    assigned_to="admin",
    # Keyword-only with None defaults: every existing call site passes
    # these positionally up to assigned_to, so adding them here cannot
    # shift an argument into the wrong parameter. None means "not
    # recorded", which the obligation engine reports honestly.
    *,
    arrival_date=None,
    contract_start_date=None,
    permit_expiry_date=None
):

    tenant_id = get_or_create_tenant(company)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO cases
        (
            employee_name,
            nationality,
            canton,
            permit,
            business_mode,
            employer,
            status,
            workflow_state,
            risk_level,
            ai_summary,
            company,
            assigned_to,
            created_at,
            case_history,
            audit_log,
            tenant_id,
            arrival_date,
            contract_start_date,
            permit_expiry_date
        )

        VALUES
        (
            %s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,
            to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'),
            %s,
            %s,
            %s,
            %s,%s,%s
        )
        RETURNING id
        """,
        (
            employee_name,
            nationality,
            canton,
            permit,
            business_mode,
            employer,
            "NEW",
            "DRAFT",
            risk_level,
            ai_summary,
            company,
            assigned_to,
            "Case created",
            "CREATE",
            tenant_id,
            arrival_date or None,
            contract_start_date or None,
            permit_expiry_date or None
        ))

        case_id = c.fetchone()[0]

    log_case_event(case_id, "CASE_CREATED", f"Case created for {employee_name}")

    return case_id


def get_cases_by_company(company):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT *
        FROM cases
        WHERE company=%s
        ORDER BY id DESC
        """, (company,))

        rows = c.fetchall()

    return rows


def count_cases_by_company(company):
    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM cases WHERE company=%s", (company,))

        count = c.fetchone()[0]

    return count


def get_cases_by_company_paginated(company, limit, offset):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT *
        FROM cases
        WHERE company=%s
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """, (company, limit, offset))

        rows = c.fetchall()

    return rows


def get_cases_by_tenant(tenant_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT *
        FROM cases
        WHERE tenant_id=%s
        ORDER BY id DESC
        """, (tenant_id,))

        rows = c.fetchall()

    return rows


def load_case(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT
            id,
            employee_name,
            nationality,
            canton,
            permit,
            business_mode,
            employer,
            status,
            workflow_state,
            risk_level,
            ai_summary,
            company,
            assigned_to,
            created_at,
            case_history,
            audit_log,
            tenant_id,

            -- Added by migration 0003. Absent from this list until now,
            -- which is why case_statutory_dates() read tenant_id as the
            -- arrival date and every statutory deadline in the product
            -- reported "date not recorded" - see CASE_INDEX_* above.
            arrival_date,
            contract_start_date,
            permit_expiry_date,

            -- Added by migration 0006.
            correspondence_language,

            -- Added by migration 0007.
            commune

        FROM cases
        WHERE id=%s
        """, (case_id,))

        row = c.fetchone()

    return row


def update_case(case_id, **kwargs):

    if not kwargs:
        return


    invalid_keys = set(kwargs.keys()) - ALLOWED_CASE_COLUMNS

    if invalid_keys:
        raise ValueError(
            f"Invalid column(s) for update_case: {invalid_keys}. "
            f"Allowed columns: {sorted(ALLOWED_CASE_COLUMNS)}"
        )

    fields = []
    values = []

    for key, value in kwargs.items():
        fields.append(f"{key}=%s")
        values.append(value)

    values.append(case_id)

    query = f"""
    UPDATE cases
    SET {', '.join(fields)}
    WHERE id=%s
    """
    old_risk_level = None

    if "risk_level" in kwargs:

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT risk_level FROM cases WHERE id=%s", (case_id,))
            row = c.fetchone()
            old_risk_level = row[0] if row else None

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            query,
            values
        )

    if "risk_level" in kwargs and kwargs["risk_level"] != old_risk_level:
        log_case_event(
            case_id,
            "RISK_CHANGED",
            f"Risk changed from {old_risk_level} to {kwargs['risk_level']}"
        )

    other_fields = [k for k in kwargs.keys() if k != "risk_level"]

    if other_fields:
        log_case_event(
            case_id,
            "CASE_UPDATED",
            f"Updated fields: {', '.join(sorted(other_fields))}"
        )


def delete_case(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()


        c.execute("""
        DELETE FROM tasks
        WHERE case_id=%s
        """, (case_id,))


        c.execute("""
        DELETE FROM documents
        WHERE case_id=%s
        """, (case_id,))


        c.execute("""
        DELETE FROM cases
        WHERE id=%s
        """, (case_id,))


# What add_task() returns. A namedtuple rather than a bare id because
# callers (the AI Operator, the agent tool) need to tell "I created this"
# apart from "this already existed" in order to report honestly, and
# because it stays index-addressable for any caller that only wants [0].
TaskUpsert = namedtuple("TaskUpsert", ["task_id", "created"])


# Must stay character-identical to the index expression in
# db/migrations/0001_tasks_unique_active_title.up.sql. PostgreSQL infers
# the arbiter index from this expression plus the WHERE predicate, so a
# divergence here would not silently duplicate rows - it would raise
# InvalidColumnReference at runtime, which the idempotency tests catch.
_ADD_TASK_SQL = r"""
INSERT INTO tasks (case_id, title, status, tenant_id)
VALUES (%s, %s, %s, %s)
ON CONFLICT (case_id, (lower(btrim(regexp_replace(title, '\s+', ' ', 'g')))))
WHERE status IS DISTINCT FROM 'DONE'
DO UPDATE SET case_id = tasks.case_id
RETURNING id, (xmax = 0) AS created
"""


def add_task(case_id, title):
    """
    Creates a follow-up task for a case, idempotently.

    Calling this repeatedly with the same case and the same title - which
    the AI Operator and the agent do on every run - yields exactly one
    active task. The guarantee is enforced by the partial UNIQUE index
    uq_tasks_active_case_title, not by an application-side pre-check: a
    SELECT-then-INSERT would let two concurrent operator runs both
    observe "absent" and both insert.

    The whole operation is one statement, so there is no window between
    checking and writing. The no-op DO UPDATE (rather than DO NOTHING) is
    deliberate: DO NOTHING returns no row when it conflicts, and the
    fallback SELECT could not see a row still uncommitted in a concurrent
    transaction. DO UPDATE blocks on that transaction and always RETURNs
    the surviving row, so the caller reliably gets the task id.

    Nothing about an already-existing task is modified - not its status,
    due date, assignment or title spelling. `created` distinguishes an
    insert from a reuse (xmax = 0 only on the insert path).

    Returns:
        TaskUpsert(task_id, created)
    """

    tenant_id = get_case_tenant_id(case_id)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(_ADD_TASK_SQL, (case_id, title, "PENDING", tenant_id))

        task_id, created = c.fetchone()

    return TaskUpsert(task_id=task_id, created=created)


def get_tasks(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT * FROM tasks
        WHERE case_id=%s
        """, (case_id,))

        rows = c.fetchall()

    return rows


def delete_tasks_for_case(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        DELETE FROM tasks
        WHERE case_id=%s
        """, (case_id,))


def set_task_due_date(task_id, due_date):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE tasks SET due_date=%s WHERE id=%s",
            (due_date, task_id)
        )


def update_task(task_id, status):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "SELECT case_id, title FROM tasks WHERE id=%s",
            (task_id,)
        )
        row = c.fetchone()

        c.execute("""
        UPDATE tasks
        SET status=%s
        WHERE id=%s
        """, (status, task_id))

    if row:
        task_case_id, task_title = row
        log_case_event(
            task_case_id,
            "TASK_STATUS_CHANGED",
            f"Task '{task_title}' marked {status}"
        )


def add_document(case_id, name):

    tenant_id = get_case_tenant_id(case_id)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO documents (case_id, name, status, tenant_id)
        VALUES (%s, %s, %s, %s)
        """, (case_id, name, "MISSING", tenant_id))


def get_documents(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT * FROM documents
        WHERE case_id=%s
        """, (case_id,))

        rows = c.fetchall()

    return rows


def delete_documents_for_case(case_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        DELETE FROM documents
        WHERE case_id=%s
        """, (case_id,))


def update_document(doc_id, status):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "SELECT case_id, name FROM documents WHERE id=%s",
            (doc_id,)
        )
        row = c.fetchone()

        c.execute("""
        UPDATE documents
        SET status=%s
        WHERE id=%s
        """, (status, doc_id))

    if row:
        doc_case_id, doc_name = row
        log_case_event(
            doc_case_id,
            "DOCUMENT_STATUS_CHANGED",
            f"Document '{doc_name}' marked {status}"
        )


def save_document_analysis(
    doc_id,
    file_path,
    extracted_text,
    extracted_fields_json,
    ocr_method,
    ocr_confidence
):

    from auth.encryption import encrypt_text

    encrypted_extracted_text = encrypt_text(extracted_text)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE documents
        SET
            status = 'UPLOADED',
            file_path = %s,
            extracted_text = %s,
            extracted_fields = %s,
            ocr_method = %s,
            ocr_confidence = %s,
            uploaded_at = to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')
        WHERE id=%s
        """, (
            file_path,
            encrypted_extracted_text,
            extracted_fields_json,
            ocr_method,
            ocr_confidence,
            doc_id
        ))

        # Whether the row was actually written.
        #
        # This UPDATE can match nothing and raise nothing. `documents` is
        # under FORCE ROW LEVEL SECURITY with the tenant_isolation policy:
        #
        #     current_setting('app.current_tenant_id', true) = ''
        #     OR tenant_id = NULLIF(current_setting(...), '')::integer
        #
        # A document whose tenant_id is NULL is invisible to a session
        # that has a tenant set, because NULL = 3 is neither true nor
        # false. The statement then updates zero rows and returns
        # normally, so the caller reports success and the checklist item
        # stays MISSING - which is exactly what a user reported.
        #
        # Reported rather than raised: the caller decides. Raising here
        # would turn a recoverable "nothing changed" into a page crash on
        # a screen the user was mid-task on.
        return c.rowcount > 0


def get_document_extracted_text(doc_id):

    from auth.encryption import decrypt_text

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "SELECT extracted_text FROM documents WHERE id=%s",
            (doc_id,)
        )

        row = c.fetchone()

    if not row or row[0] is None:
        return None

    return decrypt_text(row[0])


def get_document_case_id(doc_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT case_id FROM documents WHERE id=%s", (doc_id,))

        row = c.fetchone()

    return row[0] if row else None


def set_workflow_state(case_id, new_state, note=""):


    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "SELECT case_history FROM cases WHERE id=%s",
            (case_id,)
        )

        row = c.fetchone()
        existing_history = row[0] if row and row[0] else ""

        c.execute("SELECT to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')")
        timestamp = c.fetchone()[0]

        entry = f"[{timestamp}] Workflow state -> {new_state}"

        if note:
            entry += f" ({note})"

        updated_history = (
            f"{existing_history}\n{entry}"
            if existing_history
            else entry
        )

        c.execute("""
        UPDATE cases
        SET workflow_state=%s, case_history=%s
        WHERE id=%s
        """, (new_state, updated_history, case_id))

    event_description = f"Workflow state -> {new_state}"
    if note:
        event_description += f" ({note})"

    log_case_event(case_id, "WORKFLOW_STATE_CHANGED", event_description)


def save_filter(company, name, filter_dict):
    import json

    tenant_id = get_or_create_tenant(company)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO saved_filters (company, name, filter_json, created_at, tenant_id)
        VALUES (%s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), %s)
        """, (company, name, json.dumps(filter_dict), tenant_id))


def get_saved_filters(company):
    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT id, name, filter_json
        FROM saved_filters
        WHERE company=%s
        ORDER BY id DESC
        """, (company,))

        rows = c.fetchall()

    return rows


def delete_saved_filter(filter_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("DELETE FROM saved_filters WHERE id=%s", (filter_id,))


def log_security_event(username, action, detail="", success=True):

    tenant_id = None

    user = get_user(username)
    if user:
        tenant_id = user.get("tenant_id")

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO security_audit_log (username, action, detail, success, created_at, tenant_id)
        VALUES (%s, %s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), %s)
        """, (username, action, detail, 1 if success else 0, tenant_id))


def get_security_audit_log(limit=100):
    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT id, username, action, detail, success, created_at
        FROM security_audit_log
        ORDER BY id DESC
        LIMIT %s
        """, (limit,))

        rows = c.fetchall()

    return rows


def create_webhook(company, url, event_type, secret):

    tenant_id = get_or_create_tenant(company)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO webhooks (company, url, event_type, secret, is_active, created_at, tenant_id)
        VALUES (%s, %s, %s, %s, 1, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), %s)
        RETURNING id
        """, (company, url, event_type, secret, tenant_id))

        return c.fetchone()[0]


def get_webhooks_for_company(company):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT id, company, url, event_type, secret, is_active, created_at
        FROM webhooks
        WHERE company=%s
        ORDER BY id DESC
        """, (company,))

        rows = c.fetchall()

    return rows


def get_active_webhooks_for_event(company, event_type):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT id, company, url, event_type, secret, is_active, created_at
        FROM webhooks
        WHERE company=%s AND is_active=1 AND (event_type=%s OR event_type='ALL')
        """, (company, event_type))

        rows = c.fetchall()

    return rows


def delete_webhook(webhook_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("DELETE FROM webhooks WHERE id=%s", (webhook_id,))


def set_webhook_active(webhook_id, is_active):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE webhooks SET is_active=%s WHERE id=%s",
            (1 if is_active else 0, webhook_id)
        )


def get_case_company(case_id):
    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT company FROM cases WHERE id=%s", (case_id,))

        row = c.fetchone()

    return row[0] if row else None


def create_email_template(company, name, subject, body):

    tenant_id = get_or_create_tenant(company)

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO email_templates (company, name, subject, body, created_at, tenant_id)
        VALUES (%s, %s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), %s)
        """, (company, name, subject, body, tenant_id))


def get_email_templates(company):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT id, name, subject, body
        FROM email_templates
        WHERE company=%s
        ORDER BY id DESC
        """, (company,))

        rows = c.fetchall()

    return rows


def delete_email_template(template_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("DELETE FROM email_templates WHERE id=%s", (template_id,))


def get_recent_events_for_company(company, limit=20):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT
            ce.id,
            ce.case_id,
            ce.event_type,
            ce.description,
            ce.created_at,
            c.employee_name
        FROM case_events ce
        JOIN cases c ON c.id = ce.case_id
        WHERE c.company = %s
        ORDER BY ce.created_at DESC, ce.id DESC
        LIMIT %s
        """, (company, limit))

        rows = c.fetchall()

    return rows


def get_pending_tasks_for_company(company):


    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT
            t.id,
            t.case_id,
            t.title,
            t.status,
            t.due_date,
            c.employee_name
        FROM tasks t
        JOIN cases c ON c.id = t.case_id
        WHERE c.company = %s AND t.status = 'PENDING'
        ORDER BY (t.due_date IS NULL), t.due_date ASC
        """, (company,))

        rows = c.fetchall()

    return rows


def get_events_for_company(company, limit=None):
    """
    Every case event for a company, oldest first.

    Read-only, and additive: get_recent_events_for_company() is unchanged
    and still serves the dashboard's activity feed. That one is capped at
    a handful of rows and ordered newest-first for display; a value report
    has to see the whole period, so it needs its own query rather than a
    change to that one.

    Period filtering happens in core.reporting.value rather than here.
    created_at is TEXT, so a SQL range comparison would be a string
    comparison - correct for well-formed ISO values and silently wrong for
    anything else. The report layer parses each timestamp and drops the
    ones it cannot read, which is the honest behaviour for a document a
    customer is invoiced against.

    Args:
        limit: Optional cap, as a safety valve on a very large tenant.
            Applied to the most recent rows, so a capped result is still
            a contiguous window rather than an arbitrary sample.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        if limit is None:

            c.execute("""
            SELECT
                ce.id,
                ce.case_id,
                ce.event_type,
                ce.description,
                ce.created_at
            FROM case_events ce
            JOIN cases c ON c.id = ce.case_id
            WHERE c.company = %s
            ORDER BY ce.created_at ASC, ce.id ASC
            """, (company,))

        else:

            c.execute("""
            SELECT id, case_id, event_type, description, created_at
            FROM (
                SELECT
                    ce.id,
                    ce.case_id,
                    ce.event_type,
                    ce.description,
                    ce.created_at
                FROM case_events ce
                JOIN cases c ON c.id = ce.case_id
                WHERE c.company = %s
                ORDER BY ce.created_at DESC, ce.id DESC
                LIMIT %s
            ) recent
            ORDER BY created_at ASC, id ASC
            """, (company, limit))

        rows = c.fetchall()

    return rows


def count_documents_by_status_for_company(company, status):
    """
    How many documents a company currently has in one status.

    Used for the "compliance gaps detected" figure, which counts documents
    the system flagged as MISSING. A count is taken from the documents
    table rather than by parsing event descriptions: the description text
    is free-form prose that gets reworded, while a status column does not.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT COUNT(*)
        FROM documents d
        JOIN cases c ON c.id = d.case_id
        WHERE c.company = %s AND d.status = %s
        """, (company, status))

        row = c.fetchone()

    return int(row[0]) if row else 0


def count_tasks_by_status_for_company(company, status):
    """Companion to count_documents_by_status_for_company, for tasks."""

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT COUNT(*)
        FROM tasks t
        JOIN cases c ON c.id = t.case_id
        WHERE c.company = %s AND t.status = %s
        """, (company, status))

        row = c.fetchone()

    return int(row[0]) if row else 0


def get_value_assumptions_for_company(company):
    """
    A tenant's stated manual-effort and cost baselines, or None.

    None means "this customer has never told us their rates", which is
    different from "their rates are the defaults". The caller must keep
    that distinction: a value report is only defensible while the reader
    recognises the numbers as their own, so an unset baseline should
    prompt for input rather than quietly assume one.
    """

    tenant_id = get_or_create_tenant(company)

    if tenant_id is None:
        return None

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT
            minutes_per_document_review,
            minutes_per_document_request,
            minutes_per_case_status_update,
            hourly_cost,
            platform_cost_per_month,
            currency,
            updated_by,
            updated_at
        FROM tenant_value_assumptions
        WHERE tenant_id = %s
        """, (tenant_id,))

        row = c.fetchone()

    if not row:
        return None

    # NUMERIC comes back as Decimal. Converted to float at this boundary
    # so the pure report layer stays free of database types; the exact
    # decimal storage is what protects the stored value between runs.
    return {
        "minutes_per_document_review": float(row[0]),
        "minutes_per_document_request": float(row[1]),
        "minutes_per_case_status_update": float(row[2]),
        "hourly_cost": float(row[3]) if row[3] is not None else None,
        "platform_cost_per_month": float(row[4]) if row[4] is not None else None,
        "currency": row[5],
        "updated_by": row[6],
        "updated_at": row[7],
    }


def save_value_assumptions_for_company(
    company,
    minutes_per_document_review,
    minutes_per_document_request,
    minutes_per_case_status_update,
    hourly_cost=None,
    platform_cost_per_month=None,
    currency="CHF",
    updated_by=None,
):
    """
    Store a tenant's baselines, replacing any previous values.

    One row per tenant: the rates describe the organisation, not the
    person who entered them, so two colleagues reporting the same quarter
    must get identical figures. ``updated_by`` and ``updated_at`` are
    recorded because the report attributes these numbers to the customer
    and that claim has to be evidenced.

    ``hourly_cost=None`` is stored as NULL and means the customer has not
    supplied a rate; the report then reports hours only.
    """

    tenant_id = get_or_create_tenant(company)

    if tenant_id is None:
        return None

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO tenant_value_assumptions (
            tenant_id,
            minutes_per_document_review,
            minutes_per_document_request,
            minutes_per_case_status_update,
            hourly_cost,
            platform_cost_per_month,
            currency,
            updated_by,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (tenant_id) DO UPDATE SET
            minutes_per_document_review    = EXCLUDED.minutes_per_document_review,
            minutes_per_document_request   = EXCLUDED.minutes_per_document_request,
            minutes_per_case_status_update = EXCLUDED.minutes_per_case_status_update,
            hourly_cost                    = EXCLUDED.hourly_cost,
            platform_cost_per_month        = EXCLUDED.platform_cost_per_month,
            currency                       = EXCLUDED.currency,
            updated_by                     = EXCLUDED.updated_by,
            updated_at                     = now()
        """, (
            tenant_id,
            minutes_per_document_review,
            minutes_per_document_request,
            minutes_per_case_status_update,
            hourly_cost,
            platform_cost_per_month,
            currency,
            updated_by,
        ))

    return tenant_id


def record_job_enqueued(task_id, task_name, tenant_id, created_by):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO background_jobs (task_id, task_name, tenant_id, created_by, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, 'PENDING', to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'))
        """, (task_id, task_name, tenant_id, created_by))


def update_job_status(task_id, status):
    """
    Called from the Celery worker process (via a task signal), which has
    no per-request tenant context - runs in bypass mode by design so any
    job's status can be updated regardless of which tenant it belongs to.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE background_jobs
        SET status=%s, updated_at=to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')
        WHERE task_id=%s
        """, (status, task_id))


def get_job(task_id):

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("SELECT * FROM background_jobs WHERE task_id=%s", (task_id,))

        row = c.fetchone()

    return dict(row) if row else None


def list_jobs_for_tenant(tenant_id, limit=50):

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("""
        SELECT * FROM background_jobs
        WHERE tenant_id=%s
        ORDER BY created_at DESC
        LIMIT %s
        """, (tenant_id, limit))

        rows = c.fetchall()

    return [dict(row) for row in rows]


def create_refresh_token(username, token_hash, tenant_id, expires_at, user_agent=None):

    with get_db_connection() as conn:

        c = conn.cursor()

        # last_seen_at is set here, not left to the first touch.
        #
        # apps/web/session._has_gone_idle() fails closed: an absent
        # last_seen_at counts as idle. A row inserted without one is
        # therefore an already-abandoned session at the instant it is
        # created, and the symptom is precise and baffling - sign in,
        # refresh, and you are back at the login form, every time,
        # while the same session works fine if you happen to click
        # around for a minute first.
        #
        # Creating a session is using it. The value belongs in the same
        # statement as the row rather than in whatever runs next.
        c.execute("""
        INSERT INTO refresh_tokens (username, token_hash, tenant_id, issued_at, expires_at, revoked, user_agent, last_seen_at)
        VALUES (%s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), %s, 0, %s, NOW())
        RETURNING id
        """, (username, token_hash, tenant_id, expires_at, user_agent))

        return c.fetchone()[0]


def get_refresh_token(token_hash):

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("SELECT * FROM refresh_tokens WHERE token_hash=%s", (token_hash,))

        row = c.fetchone()

    return dict(row) if row else None


def revoke_refresh_token(token_hash):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("UPDATE refresh_tokens SET revoked=1 WHERE token_hash=%s", (token_hash,))


def revoke_session(session_id, username):
    """Revoke one session, only if it belongs to the given username."""

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE refresh_tokens SET revoked=1 WHERE id=%s AND username=%s",
            (session_id, username)
        )

        return c.rowcount > 0


def revoke_all_sessions_for_user(username):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("UPDATE refresh_tokens SET revoked=1 WHERE username=%s", (username,))


def list_active_sessions(username):

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("""
        SELECT id, issued_at, expires_at, user_agent
        FROM refresh_tokens
        WHERE username=%s
          AND revoked=0
          AND expires_at > to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')
        ORDER BY issued_at DESC
        """, (username,))

        rows = c.fetchall()

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------
# Browser session handoff (migration 0008)
# ---------------------------------------------------------------------
#
# Four statements, and the interesting property is in the second one. See
# db/migrations/0008_session_handoff.up.sql for why the table exists at
# all.


def create_session_handoff(code_hash, username, expires_at):
    """
    Record a one-time code that redeems into a browser session.

    ``expires_at`` is a timezone-aware datetime, seconds in the future.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        INSERT INTO session_handoff (code_hash, username, expires_at)
        VALUES (%s, %s, %s)
        RETURNING id
        """, (code_hash, username, expires_at))

        return c.fetchone()[0]


def consume_session_handoff(code_hash):
    """
    Claim a handoff code, or return None.

    Single-use is enforced by the database, not by the caller. The row is
    read and marked spent by the same UPDATE, so two requests presenting
    the same code cannot both be served it: the second one's WHERE clause
    no longer matches and it returns no row.

    Doing this as SELECT-then-UPDATE would leave a window - short, but
    reachable by anyone who can replay a request twice quickly - in which
    one code mints two sessions.

    Returns {"id": ..., "username": ...} or None. None covers unknown,
    already spent and expired without distinguishing between them; the
    caller has nothing useful to do with the difference and the browser
    has no business learning it.
    """

    with get_db_connection() as conn:

        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        c.execute("""
        UPDATE session_handoff
           SET consumed_at = now()
         WHERE code_hash = %s
           AND consumed_at IS NULL
           AND expires_at > now()
     RETURNING id, username
        """, (code_hash,))

        row = c.fetchone()

    return dict(row) if row else None


def touch_session(token_hash):
    """
    Record that a browser session is still being used.

    Written at most once a minute per session - see apps/web/session.py -
    because the caller runs on every Streamlit rerun, which is every
    click. One UPDATE per click would make an idle-timeout column the
    busiest write in the product.

    Revoked rows are excluded rather than updated and then ignored: a
    logged-out session must not be able to keep itself alive.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE refresh_tokens SET last_seen_at=now() "
            "WHERE token_hash=%s AND revoked=0",
            (token_hash,),
        )

        return c.rowcount > 0


def touch_session_for_handoff(code_hash):
    """
    The same, for a session this page load created and cannot name.

    st.context.cookies reports only what arrived with the websocket
    handshake, so the tab that just signed in does not know its own
    session token until the next full page load. Without this, someone
    who logs in and then works for an hour without refreshing is idle by
    the clock and active in fact - and is signed out the moment they do
    refresh.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE refresh_tokens
           SET last_seen_at = now()
         WHERE revoked = 0
           AND id = (
                SELECT session_id FROM session_handoff WHERE code_hash = %s
               )
        """, (code_hash,))

        return c.rowcount > 0


def link_session_handoff(handoff_id, session_id):
    """
    Record which browser session a redeemed code produced.

    This is what lets Log out revoke that session server-side in the same
    page load that created it, when st.context.cookies cannot yet see the
    cookie - see the migration file.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE session_handoff SET session_id=%s WHERE id=%s",
            (session_id, handoff_id),
        )


def revoke_session_for_handoff(code_hash):
    """
    Revoke the browser session a handoff code minted.

    Returns True if a session was revoked. False means there was nothing
    to revoke, which is the normal result when the code was never
    redeemed - not an error.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE refresh_tokens
           SET revoked = 1
         WHERE id = (
                SELECT session_id FROM session_handoff WHERE code_hash = %s
               )
        """, (code_hash,))

        return c.rowcount > 0


def purge_expired_session_handoffs(older_than_days=30):
    """
    Delete handoff rows that can no longer do anything.

    Kept well past expiry rather than deleted on redemption, because
    session_id is read for the life of the browser session it names. The
    cutoff is therefore a session lifetime with a wide margin, not the
    thirty seconds the code itself was valid for.

    Returns the number of rows removed.
    """

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        DELETE FROM session_handoff
         WHERE expires_at < now() - make_interval(days => %s)
        """, (older_than_days,))

        return c.rowcount


def set_mfa_secret(username, secret):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE users SET mfa_secret=%s WHERE username=%s",
            (secret, username)
        )


def set_mfa_enabled(username, enabled):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute(
            "UPDATE users SET mfa_enabled=%s WHERE username=%s",
            (1 if enabled else 0, username)
        )


def get_permissions_for_role(role):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT p.name
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE rp.role = %s
        """, (role,))

        rows = c.fetchall()

    return {row[0] for row in rows}


def role_has_permission(role, permission_name):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT 1
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE rp.role = %s AND p.name = %s
        """, (role, permission_name))

        return c.fetchone() is not None
