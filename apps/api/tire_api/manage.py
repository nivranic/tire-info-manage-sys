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
from .service import QueryService


def main():
    parser = argparse.ArgumentParser(description="本机账户运维工具（仅限本机工作台）")
    sub = parser.add_subparsers(dest="action", required=True)
    reset = sub.add_parser("reset-password")
    reset.add_argument("--username", required=True)
    reset.add_argument("--new-password", default=None,
                       help="省略则读 TI_MANAGE_NEW_PASSWORD 环境变量")
    sub.add_parser("expire-sessions", help="解绑全部已过期的登录会话")
    migration = sub.add_parser("migrate-vehicle-binary", help="显式私库023→024演练；不代表正常库发布许可")
    migration.add_argument("--private-database", required=True, help="显式私有SQLite副本路径；不读取应用默认数据库")
    migration.add_argument("--backup-file", required=True, help="全新SQLite备份文件；对象与Parser包须单独保全核验")
    migration.add_argument("--offline-confirmed", action="store_true", required=True,
                           help="确认私库所有写入方已停止；本入口不提供在线全资产一致备份")
    args = parser.parse_args()

    if args.action == "migrate-vehicle-binary":
        from .vehicle_binary_migration import VehicleBinaryMigrationError, private_rehearsal
        try:
            result = private_rehearsal(args.private_database, args.backup_file, offline_confirmed=args.offline_confirmed)
        except VehicleBinaryMigrationError as error:
            print(json.dumps({"ok": False, "code": error.code}))
            raise SystemExit(1) from None
        except Exception:
            print(json.dumps({"ok": False, "code": "vehicle_binary_migration_failed"}))
            raise SystemExit(1) from None
        print(json.dumps({"ok": True, "scope": "private_schema_rehearsal", **result}))
        return

    from .main import create_app
    app = create_app()
    database = app.state.database
    try:
        database.initialize()
        with database.sessions() as db:
            if args.action == "expire-sessions":
                unbound = sweep_expired_sessions(db)
                db.commit()
                print(json.dumps({"ok": True, "sessions_unbound": unbound}, ensure_ascii=False))
                return
            QueryService(db, None).lock_ingestion()
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
            from .external_api import revoke_account_keys
            revoke_account_keys(db, user.id)
            db.commit()
            print(json.dumps({"ok": True, "username": user.username, "sessions_unbound": len(sessions)},
                             ensure_ascii=False))
    finally:
        database.close()


if __name__ == "__main__":
    main()
