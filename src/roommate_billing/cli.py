"""运维 CLI：创建用户/账本。"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .db.models import User
from .db.session import SessionLocal
from .security.passwords import hash_password
from .services import households


def create_user(email: str, name: str) -> None:
    password = getpass.getpass("密码（12–128 字符）: ")
    confirm = getpass.getpass("再次输入密码: ")
    if password != confirm:
        raise SystemExit("两次密码不一致")
    with SessionLocal() as session:
        existing = session.scalar(select(User).where(User.email == email.strip().lower()))
        if existing is not None:
            raise SystemExit("邮箱已存在")
        user = User(
            email=email.strip().lower(),
            display_name=name.strip(),
            password_hash=hash_password(password),
        )
        session.add(user)
        session.commit()
        print(f"created user {user.email} ({user.id})")


def create_household(email: str, name: str) -> None:
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise SystemExit("用户不存在")
        household = households.create_household(session, name=name, actor_user_id=user.id)
        session.commit()
        print(f"created household {household.name} ({household.id})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="roommate-billing")
    sub = parser.add_subparsers(dest="command", required=True)

    user_parser = sub.add_parser("create-user", help="创建用户")
    user_parser.add_argument("--email", required=True)
    user_parser.add_argument("--name", required=True)

    household_parser = sub.add_parser("create-household", help="创建账本")
    household_parser.add_argument("--email", required=True, help="owner 邮箱")
    household_parser.add_argument("--name", required=True)

    args = parser.parse_args(argv)
    if args.command == "create-user":
        create_user(args.email, args.name)
    elif args.command == "create-household":
        create_household(args.email, args.name)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
