"""Operator commands: ``delegate-admin <command>``."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from . import audit, billing
from .config import get_settings
from .db import init_db, session_scope
from .models import User
from .security import hash_password


def cmd_init(_: argparse.Namespace) -> None:
    init_db()
    print("database ready")


def cmd_bootstrap(_: argparse.Namespace) -> None:
    init_db()
    billing.bootstrap()
    ok, msg = billing.health()
    print(f"new-api: {msg}")
    sys.exit(0 if ok else 1)


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


def cmd_grant(args: argparse.Namespace) -> None:
    init_db()
    s = get_settings()
    with session_scope() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == args.email.lower()))
        if user is None:
            sys.exit(f"no such user: {args.email}")
        billing.adjust(db, user, s.usd_to_quota(args.usd), kind="admin_grant", actor="cli", note=args.note or "")
        balance = billing.balance_quota(user)
    print(f"granted {args.usd:.2f} USD to {args.email}; balance {s.quota_to_usd(balance or 0):.4f} USD")


def main() -> None:
    parser = argparse.ArgumentParser(prog="delegate-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create database tables").set_defaults(fn=cmd_init)
    sub.add_parser("bootstrap", help="initialise the new-api sidecar and store its root credentials").set_defaults(
        fn=cmd_bootstrap)
    p = sub.add_parser("create-admin", help="create or promote an administrator")
    p.add_argument("email")
    p.add_argument("--password")
    p.set_defaults(fn=cmd_create_admin)
    p = sub.add_parser("grant", help="credit a user's balance")
    p.add_argument("email")
    p.add_argument("usd", type=float)
    p.add_argument("--note")
    p.set_defaults(fn=cmd_grant)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
