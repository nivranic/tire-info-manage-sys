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
    # 已登录会话注册新账户被拒（防静默改绑）；登出后才可再注册。
    assert register(other, username="admin").json()["detail"]["code"] == "already_authenticated"
    assert other.post("/v1/auth/logout").status_code == 200
    duplicate = register(other, username="admin")
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "username_taken"


def test_register_while_authenticated_preserves_identity(setup):
    client, _ = setup
    assert register(client, username="alice").status_code == 200
    response = register(client, username="mallory")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "already_authenticated"
    state = me(client)
    assert state["authenticated"] and state["user"]["username"] == "alice"  # 原身份不丢


def test_logout_then_login_other_user_on_same_session(setup):
    client, app = setup
    register(client, username="alice")
    register(TestClient(app), username="bob")
    assert client.post("/v1/auth/logout").status_code == 200
    assert login(client, "bob").status_code == 200
    assert me(client)["user"]["username"] == "bob"


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
    still = login(fresh, "alice", "wrong-password")  # 封锁期内不因换密码绕过
    assert still.status_code == 429


def test_rate_limit_counter_resets_after_successful_login(setup):
    """显式锚定"成功登录清零"：4 败→成功→再 4 败不得触发 429（若清零逻辑缺失，
    第二轮第 1 次失败即累计到 5 而封锁——旧测试无法区分这两种实现）。"""
    client, app = setup
    register(client, username="alice")
    fresh = TestClient(app)
    for _ in range(4):
        assert login(fresh, "alice", "wrong-password").status_code == 401
    assert login(fresh, "alice").status_code == 200
    fresh.post("/v1/auth/logout")
    for _ in range(4):
        assert login(fresh, "alice", "wrong-password").status_code == 401
    assert login(fresh, "alice").status_code == 200  # 未被封锁
    assert login(fresh, "alice", "wrong-password").status_code == 401


def test_unknown_username_failures_do_not_consume_known_counter(setup):
    client, app = setup
    register(client, username="alice")
    fresh = TestClient(app)
    for _ in range(4):  # 打在未知用户名上，计数按用户名隔离（同样防枚举）
        assert login(fresh, "ghost-user", "whatever-pw").status_code == 401
    assert login(fresh, "alice").status_code == 200


def test_verify_password_rejects_tampered_hashes():
    from tire_api.auth import hash_password, verify_password
    stored = hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored) and not verify_password("wrong", stored)
    scheme, n, r, p, salt, digest = stored.split("$")
    absurd = f"scrypt${1 << 24}${r}${p}${salt}${digest}"  # 被篡改的超大参数
    assert not verify_password(PASSWORD, absurd)
    assert not verify_password(PASSWORD, f"bcrypt${n}${r}${p}${salt}${digest}")
    assert not verify_password(PASSWORD, "garbage-without-dollars")
    assert not verify_password(PASSWORD, "")


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


@pytest.mark.parametrize("path,body,keyed", [
    ("/v1/tire-variants/some-variant/identity-revisions",
     {"mode": "history", "target_id": "some-target", "action": "merge", "expected_revision": 0,
      "expected_fingerprint": "0" * 64, "operator": "guard-fixture", "reason": "守卫行为验证用合成操作",
      "acknowledged": True, "evidence": [{"snapshot_id": "s", "locator": "loc"}]}, True),
    ("/v1/tire-variants/some-variant/fact-revisions",
     {"source_id": "fixture", "base_fact_id": "f", "expected_revision": 0, "field": "utqg_treadwear",
      "action": "manual_override", "value": 400, "operator": "guard-fixture",
      "reason": "守卫行为验证用合成操作", "evidence": [{"snapshot_id": "s", "locator": "loc"}]}, False),
    ("/v1/golden/cases/nonexistent/reviews",
     {"case_revision": 1, "case_fingerprint": "0" * 64, "action": "approve", "acknowledged": True,
      "operator": "guard-fixture", "reason": "守卫行为验证用合成操作",
      "expected_revision": 1, "expected_fingerprint": "0" * 64}, True),
    ("/v1/reparse/runs/nonexistent/reviews",
     {"mode": "history", "expected_revision": 0, "status": "reviewed",
      "operator": "guard-fixture", "reason": "守卫行为验证用合成操作"}, False),
])
def test_governance_write_guards_reject_non_admin(setup, path, body, keyed):
    """圆桌 R1 裁决补齐的四类治理写守卫：匿名/研究员在业务校验前即 403。"""
    client, app = setup
    register(client)
    researcher = TestClient(app)
    assert register(researcher, username="researcher").status_code == 200
    for actor in (TestClient(app), researcher):
        headers = {"Idempotency-Key": "0f0e8d64-9d1a-4b7a-8f2c-3e4d5a6b7c8d"} if keyed else {}
        response = actor.post(path, json=body, headers=headers)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "admin_required", path


def test_watchlist_dedup_across_sessions_of_same_user(setup):
    """跨会话关注去重（圆桌 R2-3）：同用户另一会话重复关注不产生重复行。"""
    client, app = setup
    register(client, username="alice")
    variant_id = live(client).json()["variants"][0]["id"]
    first = client.post("/v1/watchlists", json={"variant_id": variant_id}).json()
    second = TestClient(app)
    assert login(second, "alice").status_code == 200
    replay = second.post("/v1/watchlists", json={"variant_id": variant_id})
    assert replay.status_code == 201 and replay.json()["id"] == first["id"]
    items = second.get("/v1/watchlists").json()["items"]
    assert [item["variant_id"] for item in items] == [variant_id]


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
