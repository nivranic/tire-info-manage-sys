"""账户生命周期收尾（第59轮）：资料改名、删户、过期会话清理、驾驶偏好私有化。

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

from tire_api.db import UserSession, utc, utcnow
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


def test_profile_update_renames_account(setup_app):
    """登录用户可自改用户名/显示名；重名拒绝、匿名拒绝、非法用户名 422。"""
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
    assert alice.delete("/v1/auth/users/00000000-0000-0000-0000-000000000000").status_code == 404


def test_login_sweep_unbinds_expired_sessions(setup_app):
    """登录时顺带解绑过期会话：session_scope 聚合范围随之收敛（ADR-2026-057 补记4）。"""
    client, app = setup_app
    register(client, username="root")
    stale = TestClient(app)
    assert login(stale, "root", PASSWORD).status_code == 200
    with app.state.database.sessions() as db:
        row = db.get(UserSession, stale.cookies["tire_local_session"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    fresh = TestClient(app)
    assert login(fresh, "root", PASSWORD).status_code == 200
    with app.state.database.sessions() as db:  # 过期会话行仍在（FK 约束），但绑定被清理收敛
        assert db.get(UserSession, stale.cookies["tire_local_session"]).user_id is None
    listing = fresh.get("/v1/auth/users").json()["items"]
    assert listing[0]["session_count"] == 2  # fixture 注册会话 + fresh；不含已清理的 stale
    assert stale.get("/v1/auth/me").json()["authenticated"] is False


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
    assert cleared.status_code == 200 and cleared.json()["weights"] is None
    assert client.get("/v1/driving-preferences").json()["weights"] is None
