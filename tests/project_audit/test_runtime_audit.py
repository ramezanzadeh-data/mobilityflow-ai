import os


# Database configuration has two accepted, mutually exclusive modes.
# This mirrors db.database._build_pool(), which is the single source of
# truth: it uses DATABASE_URL when that is set, and only falls back to
# the individual PG* variables otherwise. The previous version of this
# test demanded the PG* variables unconditionally, so it reported a
# perfectly healthy DATABASE_URL-configured deployment as broken.
_DATABASE_URL_VAR = "DATABASE_URL"

_PG_VARS = [
    "PGHOST",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
]

# Required in both modes: auth/jwt.py and auth/encryption.py refuse to
# import without these, so no configuration makes them optional.
_SECRET_VARS = [
    "JWT_SECRET_KEY",
    "ENCRYPTION_KEY",
]


def _missing(keys):

    return [key for key in keys if not os.getenv(key)]


def test_environment_variables():

    missing_secrets = _missing(_SECRET_VARS)

    assert not missing_secrets, (
        "Missing environment variables: "
        + str(missing_secrets)
    )

    if os.getenv(_DATABASE_URL_VAR):
        return

    missing_pg = _missing(_PG_VARS)

    # _build_pool() would still connect here, using its built-in
    # localhost/mobilityflow defaults. Those exist for local development
    # only - depending on them in a real deployment is precisely the
    # misconfiguration this audit exists to surface, so an incomplete
    # PG* set stays a failure rather than quietly passing.
    assert not missing_pg, (
        "Database is not configured. Set either "
        + _DATABASE_URL_VAR
        + ", or all of "
        + str(_PG_VARS)
        + " (see .env.example). Missing: "
        + str(missing_pg)
    )



def test_python_version():

    import sys

    print(
        "\nPython:",
        sys.version
    )

    assert sys.version_info.major==3