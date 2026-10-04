"""账户生命周期收尾（第59轮）与第60轮圆桌修复锚点：资料改名、删户、过期会话
清理与滑动续期、驾驶偏好私有化、会话数据过户语义、lifecycle/fitment 守卫。

口令一律运行时随机或复用 test_auth_accounts.PASSWORD（本身即运行时随机），
源码不含任何口令字面量。
"""
import secrets
import subprocess
import os
import sys
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tire_api.db import DrivingPreferenceRevision, UserSession, utc, utcnow
from tire_api.main import create_app
from test_auth_accounts import PASSWORD, login, register
from test_core import FixtureRegistry
from test_research import WEIGHTS


@pytest.fixture
def setup_app():
    app = create_app("sqlite://", FixtureRegistry())
    with TestClient(app) as client:
        yield client, app


def test_admin_guard_dependency_runs_before_body_validation(setup_app):
    """Depends 化守卫时序（圆桌裁决的独立验证轮）：守卫先于 body 校验。

    匿名/非管理员发畸形 body 一律 403 admin_required（旧实现为 422）；
    管理员发畸形 body 才到达 body 校验得到 422。
    """
    client, app = setup_app
    anonymous = TestClient(app)
    response = anonymous.post("/v1/tire-variants/some-variant/fact-revisions", json={"unexpected": True})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "admin_required"
    register(client, username="root")
    researcher = TestClient(app)
    assert register(researcher, username="researcher").status_code == 200
    blocked = researcher.post("/v1/tire-variants/some-variant/fact-revisions", json={"unexpected": True})
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "admin_required"
    assert client.post("/v1/tire-variants/some-variant/fact-revisions",
                       json={"unexpected": True}).status_code == 422


def test_lifecycle_and_fitment_write_endpoints_require_admin(setup_app):
    """第60轮守卫补齐（R1）：lifecycle-events 与 fitment revisions 为全局生效写端点，
    匿名 403（守卫先于 body 校验）；fitment preview 无全局写副作用，保持开放（422=到达校验）。"""
    client, app = setup_app
    anonymous = TestClient(app)
    r1 = anonymous.post("/v1/tire-variants/x/lifecycle-events", json={})
    assert r1.status_code == 403 and r1.json()["detail"]["code"] == "admin_required"
    r2 = anonymous.post("/v1/fitment-relations/revisions", json={})
    assert r2.status_code == 403 and r2.json()["detail"]["code"] == "admin_required"
    assert anonymous.post("/v1/fitment-relations/preview", json={}).status_code == 422


def test_profile_update_renames_account(setup_app):
    """登录用户可自改用户名/显示名；重名拒绝、匿名拒绝、非法用户名 422；
    display_name 置空回退当前用户名（R3）。"""
    client, app = setup_app
    register(client, username="root")
    stranger = TestClient(app)
    assert stranger.post("/v1/auth/profile", json={"username": "nope"}).status_code == 403
    assert stranger.post("/v1/auth/profile", json={"username": "x!"}).status_code == 422  # profile 为内联守卫：body 校验先于登录检查
    assert client.post("/v1/auth/profile", json={"username": "x!"}).status_code == 422
    renamed = client.post("/v1/auth/profile", json={"username": "renamed-root", "display_name": "根用户"})
    assert renamed.status_code == 200
    assert renamed.json()["user"]["username"] == "renamed-root"
    assert client.get("/v1/auth/me").json()["user"]["display_name"] == "根用户"
    assert login(TestClient(app), "root", PASSWORD).status_code == 401
    fresh = TestClient(app)
    assert login(fresh, "renamed-root", PASSWORD).status_code == 200
    register(TestClient(app), username="alice")
    assert fresh.post("/v1/auth/profile", json={"username": "alice"}).status_code == 409
    blank = fresh.post("/v1/auth/profile", json={"display_name": "  "})
    assert blank.status_code == 200 and blank.json()["user"]["display_name"] == "renamed-root"


def test_delete_user_unbinds_sessions_and_guards_last_admin(setup_app):
    """删户=解绑全部会话+删除账户行；唯一管理员不可删；数据行不级联（以会话为锚点）。"""
    client, app = setup_app
    register(client, username="root")
    alice = TestClient(app)
    assert register(alice, username="alice").status_code == 200
    root_id = client.get("/v1/auth/me").json()["user"]["id"]
    alice_id = alice.get("/v1/auth/me").json()["user"]["id"]
    for actor in (TestClient(app), alice):  # 匿名与非管理员均 403
        assert actor.delete(f"/v1/auth/users/{alice_id}").status_code == 403
    blocked = client.delete(f"/v1/auth/users/{root_id}")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "last_admin"
    assert client.post(f"/v1/auth/users/{alice_id}/role", json={"is_admin": True}).status_code == 200
    done = client.delete(f"/v1/auth/users/{root_id}")
    assert done.status_code == 200 and done.json() == {"ok": True, "username": "root", "sessions_unbound": 1}
    assert client.get("/v1/auth/me").json()["authenticated"] is False  # 根会话已解绑
    assert {row["username"] for row in alice.get("/v1/auth/users").json()["items"]} == {"alice"}
    assert login(TestClient(app), "root", PASSWORD).status_code == 401
    missing = alice.delete("/v1/auth/users/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "user_not_found"


def test_reset_password_for_missing_user_is_404(setup_app):
    """R3：口令重置对不存在用户 404 user_not_found。"""
    client, _ = setup_app
    register(client, username="root")
    response = client.post("/v1/auth/users/00000000-0000-0000-0000-000000000000/password",
                           json={"new_password": secrets.token_urlsafe(12)})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "user_not_found"


def test_delete_user_keeps_session_anchored_data_rows(setup_app):
    """R3-1：删户数据不级联——DB 行留存、会话行留存且解绑、旧 cookie 匿名可见自身、
    其他账户作用域不可见。"""
    client, app = setup_app
    register(client, username="root")
    assert client.put("/v1/driving-preferences", json={"expected_revision": 0, "weights": WEIGHTS}).status_code == 200
    root_session = client.cookies["tire_local_session"]
    alice = TestClient(app)
    register(alice, username="alice")
    alice_id = alice.get("/v1/auth/me").json()["user"]["id"]
    root_id = client.get("/v1/auth/me").json()["user"]["id"]
    assert client.post(f"/v1/auth/users/{alice_id}/role", json={"is_admin": True}).status_code == 200
    assert client.delete(f"/v1/auth/users/{root_id}").status_code == 200
    with app.state.database.sessions() as db:
        row = db.scalar(select(DrivingPreferenceRevision).where(
            DrivingPreferenceRevision.actor_session_id == root_session))
        assert row is not None and row.weights == WEIGHTS  # 数据行留存，未级联删除
        assert db.get(UserSession, root_session).user_id is None  # 会话行留存且已解绑
    assert client.get("/v1/driving-preferences").json()["weights"] == WEIGHTS  # 旧 cookie 匿名可见自身
    assert alice.get("/v1/driving-preferences").json()["weights"] is None  # 其他账户不可见


def test_deleted_users_data_joins_next_login_on_same_session(setup_app):
    """R2-2 如实锚定：会话聚合的自然延伸——删户后该会话再登录另一账户，
    其上锚定的旧数据并入新账户作用域（共享浏览器场景的已知隐私后果，ADR-057 补记8）。"""
    client, app = setup_app
    register(client, username="root")
    assert client.put("/v1/driving-preferences", json={"expected_revision": 0, "weights": WEIGHTS}).status_code == 200
    alice = TestClient(app)
    register(alice, username="alice")
    alice_id = alice.get("/v1/auth/me").json()["user"]["id"]
    root_id = client.get("/v1/auth/me").json()["user"]["id"]
    assert client.post(f"/v1/auth/users/{alice_id}/role", json={"is_admin": True}).status_code == 200
    assert client.delete(f"/v1/auth/users/{root_id}").status_code == 200
    assert client.get("/v1/auth/me").json()["authenticated"] is False
    assert client.get("/v1/driving-preferences").json()["weights"] == WEIGHTS  # 匿名期间仅自身可见
    assert login(client, "alice", PASSWORD).status_code == 200  # 同一会话登录他人
    assert client.get("/v1/driving-preferences").json()["weights"] == WEIGHTS  # 旧数据并入 alice 作用域
    assert alice.get("/v1/driving-preferences").json()["weights"] == WEIGHTS  # 且 alice 的其他会话同样可见


def test_login_sweep_unbinds_expired_sessions(setup_app):
    """登录时顺带解绑过期会话：session_scope 聚合范围随之收敛（ADR-2026-057 补记4）；
    未过期会话不受误伤（R3-4 边界）。"""
    client, app = setup_app
    register(client, username="root")
    stale = TestClient(app)
    assert login(stale, "root", PASSWORD).status_code == 200
    alive = TestClient(app)
    assert login(alive, "root", PASSWORD).status_code == 200
    with app.state.database.sessions() as db:
        row = db.get(UserSession, stale.cookies["tire_local_session"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    fresh = TestClient(app)
    assert login(fresh, "root", PASSWORD).status_code == 200
    with app.state.database.sessions() as db:  # 过期会话行仍在（FK 约束），但绑定被清理收敛
        assert db.get(UserSession, stale.cookies["tire_local_session"]).user_id is None
        assert db.get(UserSession, alive.cookies["tire_local_session"]).user_id is not None  # 未过期不动
    listing = fresh.get("/v1/auth/users").json()["items"]
    assert listing[0]["session_count"] == 3  # fixture 注册 + alive + fresh；不含已清理的 stale
    assert stale.get("/v1/auth/me").json()["authenticated"] is False


def test_active_sessions_slide_instead_of_expiring(setup_app):
    """R2-1（第60轮圆桌）：滑动续期——剩余 TTL 过半则续满、未过半不动；
    活跃用户的会话锚定数据不再因固定 TTL 静默失踪。"""
    client, app = setup_app
    register(client, username="root")
    sid = client.cookies["tire_local_session"]

    def set_expiry(delta):
        with app.state.database.sessions() as db:
            db.get(UserSession, sid).expires_at = utcnow() + delta
            db.commit()

    set_expiry(timedelta(days=3))  # 剩 3 天 < TTL/2 → 触发续期
    assert client.get("/v1/auth/me").status_code == 200
    with app.state.database.sessions() as db:
        assert utc(db.get(UserSession, sid).expires_at) - utcnow() > timedelta(days=13)

    set_expiry(timedelta(days=10))  # 剩 10 天 > TTL/2 → 不动（无写放大）
    assert client.get("/v1/auth/me").status_code == 200
    with app.state.database.sessions() as db:
        assert utc(db.get(UserSession, sid).expires_at) - utcnow() < timedelta(days=10)


def test_cli_expire_sessions_reports_zero_when_clean(tmp_path):
    """expire-sessions 子命令可独立执行（真实子进程），空库返回 0。"""
    url = "sqlite:///" + str(tmp_path / "expire.db").replace("\\", "/")
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        assert register(client, username="root").status_code == 200
    result = subprocess.run([sys.executable, "-m", "tire_api.manage", "expire-sessions"],
                            capture_output=True, text=True, cwd=".", timeout=120,
                            env={**os.environ, "TIRE_DATABASE_URL": url})
    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout and '"sessions_unbound": 0' in result.stdout


def test_cli_expire_sessions_unbinds_stale_bindings(tmp_path):
    """R3-2：CLI 非空正路径——过期绑定被解绑并如实上报计数。"""
    url = "sqlite:///" + str(tmp_path / "expire-stale.db").replace("\\", "/")
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        assert register(client, username="root").status_code == 200
        stale = TestClient(app)
        assert login(stale, "root", PASSWORD).status_code == 200
        with app.state.database.sessions() as db:
            db.get(UserSession, stale.cookies["tire_local_session"]).expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
    result = subprocess.run([sys.executable, "-m", "tire_api.manage", "expire-sessions"],
                            capture_output=True, text=True, cwd=".", timeout=120,
                            env={**os.environ, "TIRE_DATABASE_URL": url})
    assert result.returncode == 0, result.stderr
    assert '"sessions_unbound": 1' in result.stdout
    with TestClient(create_app(url, FixtureRegistry())) as check:
        assert login(check, "root", PASSWORD).status_code == 200
        assert check.get("/v1/auth/users").json()["items"][0]["session_count"] == 2  # 注册会话 + check 登录；stale 已被 CLI 清理


def test_driving_preferences_are_private_per_actor(setup_app):
    """偏好按行为主体隔离：匿名会话互不可见；同一账户多会话共享（session_scope 聚合）。"""
    client, app = setup_app
    other = TestClient(app)
    saved = client.put("/v1/driving-preferences", json={"expected_revision": 0, "weights": WEIGHTS}).json()
    assert saved["scope"] == "actor" and saved["revision"] == 1
    stranger_view = other.get("/v1/driving-preferences").json()
    assert stranger_view["revision"] == 0 and stranger_view["weights"] is None  # B 看不到 A 的偏好
    own = other.put("/v1/driving-preferences", json={"expected_revision": 0, "weights": {**WEIGHTS, "dry": 25, "wet": 20}})
    assert own.status_code == 200  # 互不阻塞：各自从 0 起算
    assert client.get("/v1/driving-preferences").json()["weights"] == WEIGHTS  # A 的偏好未被 B 改写
    # 登录后聚合：同账户的第二个会话能看到偏好并接续修订
    register(client, username="root")
    second = TestClient(app)
    assert login(second, "root", PASSWORD).status_code == 200
    shared = second.get("/v1/driving-preferences").json()
    assert shared["weights"] == WEIGHTS
    cleared = second.post("/v1/driving-preferences/clear", json={"expected_revision": shared["revision"]})
    assert cleared.status_code == 200
    cleared_state = cleared.json()
    assert cleared_state["weights"] is None and cleared_state["scope"] == "actor"
    assert cleared_state["revision"] == 3  # 全局计数 1(client)+2(other)+3(clear)，各主体链条编号跳档
    assert client.get("/v1/driving-preferences").json()["weights"] is None
