"""R-014 账户治理能力：用户列表/提权降级/口令重置/CLI 自救通道。

口令一律运行时随机生成（secrets），源码不含任何口令字面量。
"""
import os
import secrets
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from tire_api.main import create_app
from test_auth_accounts import login, register
from test_core import FixtureRegistry


@pytest.fixture
def setup_app():
    app = create_app("sqlite://", FixtureRegistry())
    with TestClient(app) as client:
        yield client, app


def test_user_listing_and_role_management(setup_app):
    """用户列表仅管理员可见；提权即时生效；唯一管理员不可自降级（防锁死）。"""
    client, app = setup_app
    register(client, username="root")
    researcher = TestClient(app)
    assert register(researcher, username="researcher").status_code == 200
    for actor in (TestClient(app), researcher):
        response = actor.get("/v1/auth/users")
        assert response.status_code == 403 and response.json()["detail"]["code"] == "admin_required"
    items = client.get("/v1/auth/users").json()["items"]
    by_name = {row["username"]: row for row in items}
    assert set(by_name) == {"root", "researcher"} and by_name["root"]["is_admin"]
    assert by_name["root"]["session_count"] == 1 and by_name["researcher"]["session_count"] == 1  # 注册即绑定
    blocked = client.post(f"/v1/auth/users/{by_name['root']['id']}/role", json={"is_admin": False})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "last_admin"
    promoted = client.post(f"/v1/auth/users/{by_name['researcher']['id']}/role", json={"is_admin": True})
    assert promoted.status_code == 200 and promoted.json()["user"]["is_admin"]
    payload = {"operator": "guard-fixture", "reason": "守卫行为验证用合成操作"}
    assert researcher.post("/v1/parser-deployments/fixture/bootstrap", json=payload).status_code != 403
    demoted = client.post(f"/v1/auth/users/{by_name['researcher']['id']}/role", json={"is_admin": False})
    assert demoted.status_code == 200 and not demoted.json()["user"]["is_admin"]
    assert researcher.post("/v1/parser-deployments/fixture/bootstrap", json=payload).status_code == 403
    assert client.post("/v1/auth/users/00000000-0000-0000-0000-000000000000/role",
                       json={"is_admin": True}).json()["detail"]["code"] == "user_not_found"


def test_admin_password_reset_unbinds_all_sessions(setup_app):
    """管理员重置任意用户口令：该用户全部会话强制登出、旧口令作废、新口令可登录。"""
    reset_password = secrets.token_urlsafe(16)
    client, app = setup_app
    register(client, username="root")
    target = TestClient(app)
    assert register(target, username="alice").status_code == 200
    other_session = TestClient(app)
    assert login(other_session, "alice").status_code == 200
    user_id = target.get("/v1/auth/me").json()["user"]["id"]
    for actor in (TestClient(app), target):  # 匿名与目标自身（非管理员）均 403
        response = actor.post(f"/v1/auth/users/{user_id}/password", json={"new_password": reset_password})
        assert response.status_code == 403
    reset = client.post(f"/v1/auth/users/{user_id}/password", json={"new_password": reset_password})
    assert reset.status_code == 200 and reset.json()["sessions_unbound"] == 2
    assert target.get("/v1/auth/me").json()["authenticated"] is False
    assert other_session.get("/v1/auth/me").json()["authenticated"] is False
    assert login(target, "alice", "wrong-old-pw").status_code == 401
    assert login(target, "alice", reset_password).status_code == 200


def test_cli_reset_password_is_the_local_recovery_path(tmp_path):
    """R-014 自救通道：唯一管理员忘口令时经 python -m tire_api.manage 重置（子进程真实执行）。"""
    cli_password = secrets.token_urlsafe(16)
    url = "sqlite:///" + str(tmp_path / "manage.db").replace("\\", "/")
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        assert register(client, username="root").status_code == 200
    result = subprocess.run([sys.executable, "-m", "tire_api.manage", "reset-password",
                             "--username", "root", "--new-password", cli_password],
                            capture_output=True, text=True, cwd=".", timeout=120,
                            env={**os.environ, "TIRE_DATABASE_URL": url})
    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout
    restarted = create_app(url, FixtureRegistry())
    with TestClient(restarted) as client:
        assert login(client, "root", cli_password).status_code == 200
