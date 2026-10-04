"""Local multi-user accounts: stdlib scrypt passwords, first user becomes admin.

Design constraints (see docs/DEPLOYMENT-KEY-POLICY.md and the risk register):
- Zero new dependencies: hashlib.scrypt (N=2^14, r=8, p=1) + hmac.compare_digest.
- Sessions stay cookie-based (httponly, samesite=strict); login binds user_id on
  the current session, logout unbinds it. No tokens are introduced.
- Read scoping upgrades session-filtered listings to "all sessions of the bound
  user" (session_scope below); anonymous behavior is unchanged.
- Threat model: workstation role separation on a loopback-bound service. This is
  NOT protection against local malware; do not deploy on a server as-is.
"""
import hashlib
import hmac
import re
import secrets
import threading
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import User, UserSession, utcnow
from .domain import StrictModel

SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 14, 8, 1
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{3,32}")
LOGIN_FAIL_LIMIT = 5
LOGIN_BLOCK_SECONDS = 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(32)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$" + "$".join([str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), salt.hex(), digest.hex()])


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        # 防御被篡改的存储串把校验变成无界计算（正常值由本模块写入，远低于上界）。
        if not (1 <= n <= 1 << 20 and 1 <= r <= 16 and 1 <= p <= 8):
            return False
        expected = bytes.fromhex(digest_hex)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=n, r=r, p=p, dklen=len(expected))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def session_scope(db: Session, session_id: str) -> list[str]:
    """Data-visibility range for a session: all sessions of the bound user, or itself when anonymous."""
    user_id = db.scalar(select(UserSession.user_id).where(UserSession.id == session_id))
    if not user_id:
        return [session_id]
    return list(db.scalars(select(UserSession.id).where(UserSession.user_id == user_id)))


def current_user(db: Session, session_id: str) -> User | None:
    user_id = db.scalar(select(UserSession.user_id).where(UserSession.id == session_id))
    return db.get(User, user_id) if user_id else None


def require_admin(request: Request, db: Session) -> None:
    user = current_user(db, request.state.session_id)
    if not user or not user.is_admin:
        raise HTTPException(403, {"code": "admin_required", "message": "此管理操作需要管理员账户登录。"})


def make_admin_guard(get_db):
    """FastAPI 依赖形式的 require_admin 工厂。

    各路由模块的 get_db 都是在 register_*_routes 闭包里定义的，共享依赖必须
    由各模块用自己的 get_db 组装。依赖形式使守卫先于 body/查询参数校验执行
    （未登录的畸形请求得到 403 而非 422），这是圆桌裁决明确的语义变化。
    """
    def admin_guard(request: Request, db: Session = Depends(get_db)) -> None:
        require_admin(request, db)
    return admin_guard


def sweep_expired_sessions(db: Session) -> int:
    """解绑已过期的登录会话，收敛 session_scope 的聚合范围。

    只做 UPDATE 不删行：数据表（关注/报告/AI 历史等）以 actor_session_id
    外键引用会话行，且连接已开启 PRAGMA foreign_keys=ON，删除会被约束阻断。
    过期会话行本身极小，允许留存在本机 SQLite 中。
    """
    result = db.execute(update(UserSession).where(
        UserSession.user_id.is_not(None), UserSession.expires_at <= utcnow()).values(user_id=None))
    return int(result.rowcount or 0)


class RegisterRequest(StrictModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=80)


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=200)


class RoleUpdateRequest(StrictModel):
    is_admin: bool


class PasswordResetRequest(StrictModel):
    new_password: str = Field(min_length=8, max_length=200)


class ProfileUpdateRequest(StrictModel):
    username: str | None = Field(default=None, min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str | None = Field(default=None, max_length=80)


def user_view(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "is_admin": user.is_admin}


def register_auth_routes(app: FastAPI) -> None:
    # 进程内登录限速：用户名 -> [连续失败数, 封锁截止时间戳]。进程重启清零可接受。
    attempts: dict[str, list] = {}
    attempts_lock = threading.Lock()
    from .service import QueryService  # 函数级导入避免模块环（service 不反向依赖 auth）

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    def bind_session(db: Session, request: Request, user: User) -> None:
        session = db.get(UserSession, request.state.session_id)
        if session is None:
            raise HTTPException(401, {"code": "session_required", "message": "会话尚未建立，请重试。"})
        session.user_id = user.id
        db.commit()

    @app.post("/v1/auth/register")
    def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        if current_user(db, request.state.session_id) is not None:
            raise HTTPException(409, {"code": "already_authenticated",
                                      "message": "当前会话已登录，请先登出再注册新账户。"})
        # ingestion 锁串行化"首用户判定+写入"，防止并发注册产生双管理员。
        QueryService(db, None).lock_ingestion()
        sweep_expired_sessions(db)
        if db.scalar(select(User.id).where(User.username == payload.username)):
            raise HTTPException(409, {"code": "username_taken", "message": "此用户名已被注册。"})
        first = db.scalar(select(User.id).limit(1)) is None
        user = User(username=payload.username, display_name=payload.display_name.strip() or payload.username,
                    password_hash=hash_password(payload.password), is_admin=first)
        db.add(user)
        db.commit()
        bind_session(db, request, user)
        return {"user": user_view(user), "authenticated": True}

    @app.post("/v1/auth/login")
    def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        with attempts_lock:
            record = attempts.setdefault(payload.username, [0, 0.0])
            if record[1] > time.monotonic():
                raise HTTPException(429, {"code": "auth_too_many_attempts",
                                          "message": "连续失败次数过多，请稍后再试。"})
        user = db.scalar(select(User).where(User.username == payload.username))
        if not user or not verify_password(payload.password, user.password_hash):
            with attempts_lock:
                record = attempts.setdefault(payload.username, [0, 0.0])
                record[0] += 1
                if record[0] >= LOGIN_FAIL_LIMIT:
                    record[1] = time.monotonic() + LOGIN_BLOCK_SECONDS
            raise HTTPException(401, {"code": "bad_credentials", "message": "用户名或密码不正确。"})
        with attempts_lock:
            record = attempts.setdefault(payload.username, [0, 0.0])
            record[0], record[1] = 0, 0.0
        sweep_expired_sessions(db)
        bind_session(db, request, user)
        return {"user": user_view(user), "authenticated": True}

    @app.post("/v1/auth/logout")
    def logout(request: Request, db: Session = Depends(get_db)) -> dict:
        session = db.get(UserSession, request.state.session_id)
        if session is not None and session.user_id is not None:
            session.user_id = None
            db.commit()
        return {"authenticated": False, "user": None}

    @app.get("/v1/auth/me")
    def me(request: Request, db: Session = Depends(get_db)) -> dict:
        user = current_user(db, request.state.session_id)
        return {"authenticated": user is not None, "user": user_view(user) if user else None}

    @app.post("/v1/auth/profile")
    def update_profile(payload: ProfileUpdateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        user = current_user(db, request.state.session_id)
        if user is None:
            raise HTTPException(403, {"code": "not_authenticated", "message": "修改资料需要先登录。"})
        if payload.username is not None and payload.username != user.username:
            # ingestion 锁串行化"查重+写入"（与 register 同标准）；IntegrityError 兜底极端并发竞态。
            QueryService(db, None).lock_ingestion()
            if db.scalar(select(User.id).where(User.username == payload.username)):
                raise HTTPException(409, {"code": "username_taken", "message": "此用户名已被注册。"})
            user.username = payload.username
        if payload.display_name is not None:
            user.display_name = payload.display_name.strip() or user.username
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, {"code": "username_taken", "message": "此用户名已被注册。"})
        return {"user": user_view(user)}

    @app.get("/v1/auth/users", dependencies=[Depends(admin_guard)])
    def users(db: Session = Depends(get_db)) -> dict:
        rows = db.scalars(select(User).order_by(User.created_at, User.id)).all()
        # 只统计未过期绑定（sweep 仅由 login/register/CLI 触发，存在滞后窗口），读数即时准确。
        counts = dict(db.execute(select(UserSession.user_id, func.count()).where(
            UserSession.user_id.is_not(None), UserSession.expires_at > utcnow()).group_by(
            UserSession.user_id)).all())
        return {"items": [{**user_view(row), "session_count": counts.get(row.id, 0)} for row in rows]}

    @app.post("/v1/auth/users/{user_id}/role", dependencies=[Depends(admin_guard)])
    def set_role(user_id: str, payload: RoleUpdateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, {"code": "user_not_found", "message": "用户不存在。"})
        if (not payload.is_admin and target.is_admin
                and db.scalar(select(func.count()).select_from(User).where(User.is_admin)) == 1):
            raise HTTPException(409, {"code": "last_admin",
                                      "message": "不能取消唯一管理员的角色；请先提升另一位管理员。"})
        target.is_admin = payload.is_admin
        QueryService(db, None).audit(request.state.session_id, "user_role_changed",
                                     target_user_id=target.id, target_username=target.username,
                                     is_admin=target.is_admin)
        db.commit()
        return {"user": user_view(target)}

    @app.post("/v1/auth/users/{user_id}/password", dependencies=[Depends(admin_guard)])
    def reset_password(user_id: str, payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, {"code": "user_not_found", "message": "用户不存在。"})
        target.password_hash = hash_password(payload.new_password)
        # 强制该用户全部会话重新登录（新密码生效即旧凭据作废）。
        sessions = db.scalars(select(UserSession).where(UserSession.user_id == target.id)).all()
        for session in sessions:
            session.user_id = None
        QueryService(db, None).audit(request.state.session_id, "user_password_reset",
                                     target_user_id=target.id, target_username=target.username,
                                     sessions_unbound=len(sessions))
        db.commit()
        return {"id": target.id, "sessions_unbound": len(sessions)}

    @app.delete("/v1/auth/users/{user_id}", dependencies=[Depends(admin_guard)])
    def delete_user(user_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, {"code": "user_not_found", "message": "用户不存在。"})
        if target.is_admin and db.scalar(select(func.count()).select_from(User).where(User.is_admin)) == 1:
            raise HTTPException(409, {"code": "last_admin",
                                      "message": "不能删除唯一管理员；请先提升另一位管理员。"})
        # 数据行（关注/报告/AI 历史等）以会话为归属锚点，不随删户级联删除：解绑后其
        # 会话退化为匿名，数据仅对该会话自身可见；若有人在该会话上重新登录另一账
        # 户，数据会并入新账户的作用域（会话聚合语义的自然延伸——共享浏览器场景
        # 下被删用户的私有数据会暴露给下一登录者，见 ADR-2026-057 补记 8）。
        sessions = db.scalars(select(UserSession).where(UserSession.user_id == target.id)).all()
        for session in sessions:
            session.user_id = None
        username = target.username
        QueryService(db, None).audit(request.state.session_id, "user_deleted",
                                     target_user_id=target.id, target_username=username,
                                     sessions_unbound=len(sessions))
        db.delete(target)
        db.commit()
        return {"ok": True, "username": username, "sessions_unbound": len(sessions)}
