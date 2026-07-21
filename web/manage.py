"""Admin CLI: create login accounts.

    python -m web.manage create-user <username> [--name 显示名] [--admin]

Password is prompted interactively (not a CLI arg) so it never lands in shell
history or the process argument list. Use --password only for scripted/CI use.

Account creation itself (including the first-account data migration) lives in
web/accounts.py — this is now also available from the "账号管理" page in the
app for anyone with an admin account, so the CLI is mainly useful for
bootstrapping the very first account.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from web import accounts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m web.manage")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="创建登录账号")
    create.add_argument("username")
    create.add_argument("--password", default=None,
                        help="不传则交互式输入（推荐，避免密码进 shell 历史）")
    create.add_argument("--name", default=None, help="显示名，默认同用户名")
    create.add_argument("--admin", action="store_true", help="设为管理员（首个账号自动是管理员）")

    args = parser.parse_args(argv)
    if args.command == "create-user":
        password = args.password or getpass.getpass("密码：")
        try:
            user_id = accounts.create_user(args.username, password, args.name, args.admin)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"已创建账号 {args.username}（id={user_id}）")


if __name__ == "__main__":
    main(sys.argv[1:])
