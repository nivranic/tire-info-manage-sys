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
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import User, UserSession
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


class RegisterRequest(StrictModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=80)


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=200)


def user_view(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "is_admin": user.is_admin}


def register_auth_routes(app: FastAPI) -> None:
    # 进程内登录限速：用户名 -> [连续失败数, 封锁截止时间戳]。进程重启清零可接受。
    attempts: dict[str, list] = {}
    attempts_lock = threading.Lock()

    def get_db():
        with app.state.database.sessions() as db:
            yield db

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
        from .service import QueryService
        QueryService(db, None).lock_ingestion()
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
