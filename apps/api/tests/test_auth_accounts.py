"""Multi-user accounts: scrypt logins, first-user admin, user-scoped reads, admin guards,
and session-user binding surviving a schema-upgraded restart. Synthetic fixtures only."""

import pytest
from fastapi.testclient import TestClient

from tire_api.main import create_app
from test_core import FixtureRegistry, live

PASSWORD = "correct horse battery"


@pytest.fixture
def setup():
    app = create_app("sqlite://", FixtureRegistry())
    with TestClient(app) as client:
        yield client, app


def me(client):
    return client.get("/v1/auth/me").json()


def register(client, username="admin", password=PASSWORD, display_name="管理员"):
    return client.post("/v1/auth/register",
                       json={"username": username, "password": password, "display_name": display_name})


def login(client, username, password=PASSWORD):
    return client.post("/v1/auth/login", json={"username": username, "password": password})


def test_me_anonymous_then_bound_after_register(setup):
    client, _ = setup
    assert me(client) == {"authenticated": False, "user": None}
    response = register(client)
    assert response.status_code == 200, response.text
    assert response.json()["user"]["is_admin"] is True
    state = me(client)
    assert state["authenticated"] and state["user"]["username"] == "admin" and state["user"]["is_admin"]


def test_second_user_not_admin_and_duplicate_username_rejected(setup):
    client, app = setup
    assert register(client).status_code == 200
    other = TestClient(app)
    second = register(other, username="researcher", display_name="研究员")
    assert second.status_code == 200 and second.json()["user"]["is_admin"] is False
    duplicate = register(other, username="admin")
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "username_taken"


@pytest.mark.parametrize("payload", [
    {"username": "ab", "password": "longenough1"},
    {"username": "has space", "password": "longenough1"},
    {"username": "bad|name", "password": "longenough1"},
    {"username": "validuser", "password": "short"},
])
def test_register_validation(setup, payload):
    client, _ = setup
    assert client.post("/v1/auth/register", json=payload).status_code == 422


def test_login_logout_and_rate_limit(setup):
    client, app = setup
    register(client, username="alice")
    fresh = TestClient(app)
    bad = login(fresh, "alice", "wrong-password")
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "bad_credentials"
    unknown = login(fresh, "nobody", "whatever-pw")
    assert unknown.status_code == 401  # 同一文案，不区分用户名是否存在
    assert login(fresh, "alice").status_code == 200 and me(fresh)["authenticated"]
    assert fresh.post("/v1/auth/logout").status_code == 200
    assert me(fresh)["authenticated"] is False
    for _ in range(5):
        login(fresh, "alice", "wrong-password")
    blocked = login(fresh, "alice")
    assert blocked.status_code == 429 and blocked.json()["detail"]["code"] == "auth_too_many_attempts"


def test_user_scoped_watchlists_across_sessions(setup):
    client, app = setup
    register(client, username="alice")
    variant_id = live(client).json()["variants"][0]["id"]
    added = client.post("/v1/watchlists", json={"variant_id": variant_id})
    assert added.status_code == 201, added.text
    second = TestClient(app)
    assert second.get("/v1/watchlists").json()["items"] == []  # 未登录互不可见
    assert login(second, "alice").status_code == 200
    items = second.get("/v1/watchlists").json()["items"]
    assert [item["variant_id"] for item in items] == [variant_id]  # 同用户跨会话可见
    assert second.delete(f"/v1/watchlists/{items[0]['id']}").status_code == 204  # 跨会话可删除


def test_admin_guard_blocks_management_writes(setup):
    client, app = setup
    register(client)  # 首个注册用户 = 管理员
    researcher = TestClient(app)
    assert register(researcher, username="researcher").status_code == 200
    anonymous = TestClient(app)
    payload = {"operator": "guard-fixture", "reason": "守卫行为验证用合成操作"}
    for actor in (anonymous, researcher):
        response = actor.post("/v1/parser-deployments/fixture/bootstrap", json=payload)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "admin_required"
    allowed = client.post("/v1/parser-deployments/fixture/bootstrap", json=payload)
    assert allowed.status_code != 403  # 管理员通过守卫，后续按业务规则返回


def test_session_user_binding_survives_restart(tmp_path):
    url = "sqlite:///" + str(tmp_path / "auth-restart.db").replace("\\", "/")
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        assert register(client, username="alice").status_code == 200
        cookies = dict(client.cookies)
    upgraded = create_app(url, FixtureRegistry())
    with TestClient(upgraded, cookies=cookies) as client:
        state = me(client)
        assert state["authenticated"] and state["user"]["username"] == "alice"
