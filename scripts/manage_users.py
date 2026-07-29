"""
Single, authoritative CLI for creating and managing users.

This replaces the old db/seed.py. There must only ever be ONE place
that can create or reset a user's password, otherwise you end up with
the exact bug this replaced: two different scripts silently creating
"admin" with two different passwords depending on which one ran last.

Usage:
    python -m scripts.manage_users create-admin --username admin --password admin --company "Default Company"
    python -m scripts.manage_users create-user --username jsmith --password s3cret --role STAFF --company "Acme AG"
    python -m scripts.manage_users reset-password --username admin --password new-password
    python -m scripts.manage_users list-users
"""

import argparse
import getpass
import sys

# Must run before db.database and auth.* are imported: those modules read
# configuration at import time. Without it this CLI would create or reset
# accounts on whichever server answered on localhost:5432 rather than the
# configured one - see bootstrap/environment.py.
from bootstrap import load_environment

load_environment()

from db.database import (  # noqa: E402  (deliberate - see above)
    init_db,
    create_user,
    update_user_password,
    username_exists,
    get_user,
    list_tenants,
    list_users,
    set_user_role,
    UnknownRoleError,
    VALID_ROLE_NAMES,
)
from auth.password import hash_password  # noqa: E402  (deliberate - see above)


def _prompt_password_if_missing(password):
    if password:
        return password
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(1)
    return first


def cmd_create_user(args, role):
    if username_exists(args.username):
        print(f"User '{args.username}' already exists. Use reset-password instead.", file=sys.stderr)
        sys.exit(1)

    password = _prompt_password_if_missing(args.password)

    create_user(
        args.username,
        hash_password(password),
        role,
        args.company,
        must_change_password=not args.no_force_change,
    )

    print(f"Created user '{args.username}' (role={role}, company='{args.company}').")

    if not args.no_force_change:
        print("This user must change their password on first login.")


def cmd_reset_password(args):
    if not username_exists(args.username):
        print(f"User '{args.username}' does not exist.", file=sys.stderr)
        sys.exit(1)

    password = _prompt_password_if_missing(args.password)

    update_user_password(args.username, hash_password(password))

    print(f"Password for '{args.username}' has been reset.")


def cmd_set_role(args):

    if not username_exists(args.username):
        print(f"User '{args.username}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        updated = set_user_role(args.username, args.role)
    except UnknownRoleError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

    if not updated:
        print(f"No user updated for '{args.username}'.", file=sys.stderr)
        sys.exit(1)

    print(f"Role for '{args.username}' set to {args.role}.")


def cmd_list_users(args):
    rows = list_users()

    if not rows:
        print("No users found.")
        return

    unknown_roles = []

    for row in rows:
        if row["role"] not in VALID_ROLE_NAMES:
            unknown_roles.append((row["username"], row["role"]))

        flag = " [must change password]" if row["must_change_password"] else ""
        marker = "" if row["role"] in VALID_ROLE_NAMES else "  <-- UNKNOWN ROLE"
        print(f"- {row['username']} | role={row['role']} | company={row['company']} | tenant_id={row['tenant_id']}{flag}{marker}")

    if unknown_roles:
        print(file=sys.stderr)
        print(
            "WARNING: these accounts have a role that is not in the "
            "permission matrix, so they are treated as the "
            "least-privileged role regardless of what the name suggests:",
            file=sys.stderr,
        )
        for username, role in unknown_roles:
            print(f"  {username}: {role}", file=sys.stderr)
        print(
            f"Fix with: python -m scripts.manage_users set-role "
            f"--username <name> --role <{'|'.join(VALID_ROLE_NAMES)}>",
            file=sys.stderr,
        )


def main():
    init_db()

    parser = argparse.ArgumentParser(description="Manage MobilityFlow AI users.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_admin = subparsers.add_parser("create-admin", help="Create a new ADMIN user.")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--password", default=None, help="Omit to be prompted securely.")
    p_admin.add_argument("--company", required=True)
    p_admin.add_argument("--no-force-change", action="store_true",
                          help="Skip forcing a password change on first login.")

    p_user = subparsers.add_parser("create-user", help="Create a new user with any role.")
    p_user.add_argument("--username", required=True)
    p_user.add_argument("--password", default=None, help="Omit to be prompted securely.")
    p_user.add_argument(
        "--role",
        required=True,
        choices=VALID_ROLE_NAMES,
        help="Role from the permission matrix. Rejected if unknown - an "
             "unrecognised role would be silently downgraded rather than "
             "doing what you intended.",
    )
    p_user.add_argument("--company", required=True)
    p_user.add_argument("--no-force-change", action="store_true",
                         help="Skip forcing a password change on first login.")

    p_reset = subparsers.add_parser("reset-password", help="Reset an existing user's password.")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument("--password", default=None, help="Omit to be prompted securely.")

    p_role = subparsers.add_parser(
        "set-role",
        help="Change an existing user's role (validated).",
    )
    p_role.add_argument("--username", required=True)
    p_role.add_argument("--role", required=True, choices=VALID_ROLE_NAMES)

    subparsers.add_parser("list-users", help="List all users.")

    args = parser.parse_args()

    if args.command == "create-admin":
        cmd_create_user(args, role="ADMIN")
    elif args.command == "create-user":
        cmd_create_user(args, role=args.role)
    elif args.command == "reset-password":
        cmd_reset_password(args)
    elif args.command == "set-role":
        cmd_set_role(args)
    elif args.command == "list-users":
        cmd_list_users(args)


if __name__ == "__main__":
    main()
