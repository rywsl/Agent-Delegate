"""Operator commands: ``delegate-admin <command>``."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from . import audit
from .db import init_db, session_scope
from .models import User
from .security import hash_password


def cmd_init(_: argparse.Namespace) -> None:
    init_db()
    print("database ready")


def cmd_create_admin(args: argparse.Namespace) -> None:
    init_db()
    password = args.password or getpass.getpass("password: ")
    if len(password) < 8:
        sys.exit("password must be at least 8 characters")
    with session_scope() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == args.email.lower()))
        if user:
            user.is_admin = True
            user.password_hash = hash_password(password)
            action = "updated"
        else:
            user = User(email=args.email.lower(), display_name=args.email.split("@")[0],
                        password_hash=hash_password(password), is_admin=True)
            db.add(user)
            action = "created"
        db.flush()
        audit.record(db, "admin.cli_create_admin", actor="system", user_id=user.id)
    print(f"admin {args.email} {action}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="delegate-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create or upgrade database tables").set_defaults(fn=cmd_init)
    p = sub.add_parser("create-admin", help="create or promote an administrator")
    p.add_argument("email")
    p.add_argument("--password")
    p.set_defaults(fn=cmd_create_admin)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
