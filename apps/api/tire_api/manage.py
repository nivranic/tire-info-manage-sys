"""本机账户运维 CLI（R-014 自救通道）。

唯一管理员忘记密码且无其他管理员可代重置时，在本机执行：
    python -m tire_api.manage reset-password --username admin --new-password <新口令>
口令只从命令行参数或 TI_MANAGE_NEW_PASSWORD 环境变量读取，绝不内置任何凭据
字面量；执行后该用户全部会话被强制登出。属本机运维后门，服务器部署形态必须
改走带审计的在线流程（docs/DEPLOYMENT-KEY-POLICY.md）。

expire-sessions 手动收敛过期登录会话（login/register 会顺带执行同一清理）：
    python -m tire_api.manage expire-sessions
只解绑不删行——数据表以 actor_session_id 外键引用会话行且连接开启了
PRAGMA foreign_keys=ON（见 auth.sweep_expired_sessions 注释）。
"""
import argparse
import json
import os

from sqlalchemy import select

from .auth import hash_password, sweep_expired_sessions
from .db import User, UserSession
from .main import create_app


def main():
    parser = argparse.ArgumentParser(description="本机账户运维工具（仅限本机工作台）")
    sub = parser.add_subparsers(dest="action", required=True)
    reset = sub.add_parser("reset-password")
    reset.add_argument("--username", required=True)
    reset.add_argument("--new-password", default=None,
                       help="省略则读 TI_MANAGE_NEW_PASSWORD 环境变量")
    sub.add_parser("expire-sessions", help="解绑全部已过期的登录会话")
    args = parser.parse_args()

    app = create_app()
    database = app.state.database
    database.initialize()
    try:
        with database.sessions() as db:
            if args.action == "expire-sessions":
                unbound = sweep_expired_sessions(db)
                db.commit()
                print(json.dumps({"ok": True, "sessions_unbound": unbound}, ensure_ascii=False))
                return
            user = db.scalar(select(User).where(User.username == args.username))
            if user is None:
                print(json.dumps({"error": "user_not_found", "username": args.username}, ensure_ascii=False))
                raise SystemExit(1)
            new_password = args.new_password or os.environ.get("TI_MANAGE_NEW_PASSWORD")
            if not new_password or not (8 <= len(new_password) <= 200):
                print(json.dumps({"error": "invalid_password_length"}, ensure_ascii=False))
                raise SystemExit(1)
            user.password_hash = hash_password(new_password)
            sessions = db.scalars(select(UserSession).where(UserSession.user_id == user.id)).all()
            for session in sessions:
                session.user_id = None
            db.commit()
            print(json.dumps({"ok": True, "username": user.username, "sessions_unbound": len(sessions)},
                             ensure_ascii=False))
    finally:
        database.close()


if __name__ == "__main__":
    main()
