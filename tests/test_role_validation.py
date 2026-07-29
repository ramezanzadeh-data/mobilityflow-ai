"""
Tests for role validation and the fail-safe authorisation fallback.

An unrecognised role used to be accepted at creation and then silently
coerced to STAFF at every permission check. The failure mode was a typo:
an account intended as VIEWER but stored as "VIEWR" became a working
STAFF account - with cases:edit, documents:edit, tasks:edit and ai:use -
and nothing anywhere raised an error. A read-only auditor quietly gained
write access to case data.

Two independent defences, tested separately because either one alone
leaves a hole:

1. create_user() rejects a role that is not in the permission matrix, so
   the bad row is never written.
2. normalize_role() falls back to the *least*-privileged role, so rows
   that predate the validation - or arrive through some path that skips
   it - fail closed rather than open.

These tests do not touch the database: validate_role and normalize_role
are pure.
"""

import pytest

from auth.permissions import (
    FALLBACK_ROLE,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_STAFF,
    ROLE_VIEWER,
    VALID_ROLES,
    normalize_role,
)
from db.database import (
    VALID_ROLE_NAMES,
    UnknownRoleError,
    _ROLE_PERMISSIONS,
    validate_role,
)


# ------------------------------------------------- the two role lists ---

def test_the_two_role_lists_cannot_drift():
    """
    auth.permissions.VALID_ROLES decides what normalize_role() accepts;
    db.database._ROLE_PERMISSIONS decides what a role can actually do.
    If they disagree, a role is either accepted but powerless, or granted
    permissions the auth layer will not recognise. Neither is detectable
    by any behavioural test, so it is asserted directly.
    """

    assert sorted(VALID_ROLES) == sorted(_ROLE_PERMISSIONS)
    assert VALID_ROLE_NAMES == sorted(_ROLE_PERMISSIONS)


# -------------------------------------------------------- validation ---

@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF, ROLE_VIEWER])
def test_known_roles_are_accepted(role):

    assert validate_role(role) == role


@pytest.mark.parametrize(
    "role,expected",
    [("admin", ROLE_ADMIN), ("  staff  ", ROLE_STAFF), ("Viewer", ROLE_VIEWER)],
)
def test_known_roles_are_normalised_on_the_way_in(role, expected):
    """Case and stray whitespace are operator error, not a new role."""

    assert validate_role(role) == expected


@pytest.mark.parametrize(
    "role",
    ["HR_MANAGER", "VIEWR", "SUPER_ADMIN", "root", "MANAGER_2"],
)
def test_unknown_roles_are_rejected(role):
    """The primary defence: the bad row is never written."""

    with pytest.raises(UnknownRoleError) as error:
        validate_role(role)

    # The message must name the valid options - an operator who hit this
    # needs to know what to type instead.
    assert "VIEWER" in str(error.value)


@pytest.mark.parametrize("role", [None, "", "   "])
def test_a_missing_role_is_rejected_rather_than_defaulted(role):
    """
    Defaulting a blank role at creation would reintroduce the same
    silent-privilege problem from the other direction.
    """

    with pytest.raises(UnknownRoleError):
        validate_role(role)


# ---------------------------------------------------------- fallback ---

def test_the_fallback_is_the_least_privileged_role():
    """
    The property that matters, stated independently of which role is
    currently least privileged: the fallback must not grant anything the
    other roles do not all have.
    """

    assert FALLBACK_ROLE == ROLE_VIEWER

    fallback_permissions = set(_ROLE_PERMISSIONS[FALLBACK_ROLE])

    for role, permissions in _ROLE_PERMISSIONS.items():
        assert fallback_permissions <= set(permissions), (
            f"{FALLBACK_ROLE} grants something {role} does not; it is no "
            f"longer the least-privileged role and is unsafe as a fallback."
        )


@pytest.mark.parametrize("role", ["HR_MANAGER", "VIEWR", "SUPER_ADMIN", None, ""])
def test_unrecognised_roles_fail_closed(role):
    """
    The regression. These previously resolved to STAFF, which carries
    write permissions.
    """

    assert normalize_role(role) == ROLE_VIEWER


def test_the_fallback_grants_no_write_permission():
    """
    Spelled out in terms of consequence rather than role name, so this
    still fails if someone adds a write permission to VIEWER.
    """

    write_permissions = {
        "cases:edit",
        "cases:delete",
        "cases:approve",
        "documents:edit",
        "tasks:edit",
        "users:manage",
    }

    granted = set(_ROLE_PERMISSIONS[FALLBACK_ROLE])

    assert not (granted & write_permissions), (
        f"The fallback role grants write access: "
        f"{sorted(granted & write_permissions)}. An unrecognised role must "
        f"never be able to modify case data."
    )


@pytest.mark.parametrize("role", VALID_ROLES)
def test_known_roles_are_unaffected_by_the_fallback_change(role):
    """The fallback must not have altered any legitimate role."""

    assert normalize_role(role) == role
    assert normalize_role(role.lower()) == role
