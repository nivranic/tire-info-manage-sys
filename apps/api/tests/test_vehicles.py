"""Synthetic fixtures exercise the official JSON shape; no invented business seeds."""

import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from admin_support import register_admin
from tire_api.adapters import xiaomi
from tire_api.adapters.transport import SourceAccessError
from tire_api.db import FallbackConsent, utcnow
from tire_api.main import create_app
from tire_api.vehicles import VehicleManufacturer, VehicleSnapshot, WheelFitment, register_vehicle_routes


@pytest.fixture(autouse=True)
def isolated_xiaomi_transport_state(monkeypatch):
    monkeypatch.setattr(xiaomi, "_last_fetch", -float("inf"))
    monkeypatch.setattr(xiaomi, "_busy", False)
    monkeypatch.setattr(xiaomi, "_robots", {})
    monkeypatch.setattr(xiaomi, "_robots_requests", {})


def source_document():
    """Small synthetic sample: numeric IDs preserve the public schema, values are fixtures."""
    return {"code": 0, "requestTimestamp": "fixture-1", "data": {"paramComparisonTableVOList": [{
        "carItemId": xiaomi.CURRENT_SOURCE_ID, "brandCode": "xiaomi", "version": 1,
        "pdfFileName": "新一代SU7参数配置表", "pdfConfigDownloadUrl": "",
        "carSsuDataList": [
            {"carSsuId": 1001, "pcCarVersionName": "SU7 Max"},
            {"carSsuId": 1002, "pcCarVersionName": "SU7"},
        ],
        "groups": [{"groupName": "轮毂/轮胎", "footnote": ["synthetic fixture, not a production source"],
                    "paramComparisonCols": [
                        {"carItemId": xiaomi.CURRENT_SOURCE_ID, "carSsuId": 1001,
                         "paramComparisonCells": [
                             {"paramName": "20英寸测试轮毂", "paramDesc": "前245/40 R20\\n后265/40 R20\\n测试品牌 轮胎", "paramValue": "●"},
                             {"paramName": "21英寸测试轮毂", "paramDesc": "前245/35 R21\\n后265/35 R21\\n测试品牌 轮胎\\n仅测试颜色可选", "paramValue": "○"},
                         ]},
                        {"carItemId": xiaomi.CURRENT_SOURCE_ID, "carSsuId": 1002,
                         "paramComparisonCells": [
                             {"paramName": "20英寸测试轮毂", "paramDesc": "前245/40 R20\\n后265/40 R20\\n测试品牌 轮胎", "paramValue": "●"},
                             {"paramName": "21英寸测试轮毂", "paramDesc": "前245/35 R21\\n后265/35 R21\\n测试品牌 轮胎", "paramValue": "-"},
                         ]},
                    ]}],
    }]}}


def body(document=None):
    return json.dumps(document if document is not None else source_document(), ensure_ascii=False)


def success(document=None):
    raw = body(document)
    return {"status": "ok", "url": xiaomi.API_URL, "content_type": "application/json",
            "parser_version": xiaomi.PARSER_VERSION, "body": raw, "payload": xiaomi.parse_config(raw)}


class FixtureVehicleAdapter:
    def __init__(self):
        self.result = success()
        self.calls = []

    candidates = staticmethod(xiaomi.candidates)

    async def fetch(self, vehicle_id, *, on_observation=None):
        self.calls.append(vehicle_id)
        return deepcopy(self.result)


class OfflineTireRegistry:
    @staticmethod
    def sources():
        return [{"id": "fixture"}]

    @staticmethod
    async def fetch(*_args, **_kwargs):
        return {"status": "unavailable", "reason": "test_outage"}


@pytest.fixture
def setup():
    adapter = FixtureVehicleAdapter()
    app = create_app("sqlite://", OfflineTireRegistry())
    register_vehicle_routes(app, adapter)
    with TestClient(app) as client:
        # vehicle_setup 的导入方含隔离复核流程，管理写需要管理员。
        register_admin(client)
        yield client, adapter, app.state.database


def live(client, payload=None, vehicle_id=xiaomi.CURRENT_ID):
    return client.post(f"/v1/vehicles/{vehicle_id}/live-fitments", json=payload or {"fallback_policy": "ask"})


def grant(client, query_id, decision="allow"):
    return client.post("/v1/fallback-consents", json={"query_id": query_id, "decision": decision, "scope": "once"})


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_source_parser_keeps_generation_trim_axes_and_unknown_oe_separate():
    parsed = xiaomi.parse_config(body())
    assert parsed["vehicle"]["generation"] == "新一代"
    assert parsed["vehicle"]["model_year"] is None
    assert len(parsed["trims"]) == 2 and len(parsed["fitments"]) == 4
    max_optional = next(row for row in parsed["fitments"] if row["trim_name"] == "SU7 Max" and row["availability"] == "optional")
    assert max_optional["front"]["size"] == "245/35R21"
    assert max_optional["rear"]["size"] == "265/35R21"
    assert max_optional["staggered"] is True
    assert max_optional["constraints"] == ["仅测试颜色可选"]
    assert all(row["front"]["oe_mark"] is None and row["rear"]["matched_tire_variant_id"] is None
               for row in parsed["fitments"])
    assert parsed["coverage"]["exact_tire_sku"] is False
    standard_21 = next(row for row in parsed["fitments"] if row["trim_name"] == "SU7" and row["wheel_diameter_inches"] == 21)
    assert standard_21["availability"] == "unavailable"


def test_column_reordering_uses_source_trim_id_not_position():
    document = source_document()
    document["data"]["paramComparisonTableVOList"][0]["groups"][0]["paramComparisonCols"].reverse()
    parsed = xiaomi.parse_config(body(document))
    standard_21 = next(row for row in parsed["fitments"] if row["trim_name"] == "SU7" and row["wheel_diameter_inches"] == 21)
    assert standard_21["availability"] == "unavailable"
    assert standard_21["trim_id"].endswith("1002")


def test_symmetric_axles_require_both_explicit_sizes():
    document = source_document()
    row = document["data"]["paramComparisonTableVOList"][0]["groups"][0]["paramComparisonCols"][0]["paramComparisonCells"][0]
    row["paramDesc"] = "前245/40 R20\\n后245/40 R20\\n测试品牌 轮胎"
    assert xiaomi.parse_config(body(document))["fitments"][0]["staggered"] is False
    row["paramDesc"] = "245/40 R20\\n测试品牌 轮胎"
    with pytest.raises(SourceAccessError, match="axle_mapping_ambiguous"):
        xiaomi.parse_config(body(document))


@pytest.mark.parametrize("description,expected", [
    ("前245/40R20（仅搭配选装套件可用）\\n后265/40R20\\n测试品牌 轮胎", ["前轴（仅搭配选装套件可用）"]),
    ("前轮胎245/40R20\\n后轮265/40R20（仅指定轮胎可用）\\n测试品牌 轮胎", ["后轴（仅指定轮胎可用）"]),
    ("前245/40R20 后265/40R20（仅搭配选装套件可用）\\n测试品牌 轮胎", ["前轴 后轴（仅搭配选装套件可用）"]),
])
def test_axle_attached_conditions_keep_their_scope(description, expected):
    document = source_document()
    row = document["data"]["paramComparisonTableVOList"][0]["groups"][0]["paramComparisonCols"][0]["paramComparisonCells"][0]
    row["paramDesc"] = description
    fitment = xiaomi.parse_config(body(document))["fitments"][0]
    assert fitment["constraints"] == expected
    assert fitment["source_tire_description"] == "测试品牌 轮胎"
    assert fitment["front"]["size"] == "245/40R20"
    assert fitment["rear"]["size"] == "265/40R20"


def test_axle_attached_condition_changes_append_fact_versions(setup):
    client, adapter, database = setup
    initial = live(client).json()
    assert initial["fitments"][0]["constraints"] == []
    assert initial["fact_version"] == 1
    for version, condition in [(2, "仅搭配选装套件可用"), (3, "仅搭配升级套件可用")]:
        document = source_document()
        row = document["data"]["paramComparisonTableVOList"][0]["groups"][0]["paramComparisonCols"][0]["paramComparisonCells"][0]
        row["paramDesc"] = f"前245/40R20（{condition}）\\n后265/40R20\\n测试品牌 轮胎"
        adapter.result = success(document)
        changed = live(client).json()
        assert changed["fact_version"] == version
        assert changed["fitments"][0]["constraints"] == [f"前轴（{condition}）"]
    assert count(database, VehicleSnapshot) == 3 and count(database, WheelFitment) == 12


@pytest.mark.parametrize("mutation,reason", [
    (lambda table: table.update(pdfFileName="首代SU7参数配置表"), "generation_identity_changed"),
    (lambda table: table["groups"][0]["paramComparisonCols"][0].update(carSsuId=9999), "trim_column_mismatch"),
    (lambda table: table["groups"][0]["paramComparisonCols"][0]["paramComparisonCells"][0].update(paramValue="maybe"), "availability_unknown"),
    (lambda table: table["groups"][0]["paramComparisonCols"][0]["paramComparisonCells"][0].update(paramName="19英寸测试轮毂"), "wheel_diameter_mismatch"),
])
def test_parser_rejects_ambiguous_or_changed_source_schema(mutation, reason):
    document = source_document()
    mutation(document["data"]["paramComparisonTableVOList"][0])
    with pytest.raises(SourceAccessError, match=reason):
        xiaomi.parse_config(body(document))


def test_first_generation_does_not_reuse_current_generation_data():
    result = asyncio.run(xiaomi.fetch(xiaomi.FIRST_GENERATION_ID))
    assert result == {"status": "unavailable", "reason": "vehicle_generation_not_verified"}
    with pytest.raises(SourceAccessError, match="generation_not_verified"):
        xiaomi.parse_config(body(), xiaomi.FIRST_GENERATION_ID)


def test_vehicle_catalog_is_metadata_only_and_database_starts_empty(setup):
    client, adapter, database = setup
    catalog = client.get("/v1/vehicles").json()
    assert catalog["data_state"] == "source_catalog"
    assert len(catalog["vehicles"]) == 2
    assert all("fitments" not in row for row in catalog["vehicles"])
    assert count(database, VehicleManufacturer) == count(database, VehicleSnapshot) == 0


def test_live_evidence_and_explicit_history(setup):
    client, adapter, database = setup
    response = live(client)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["data_state"] == "live" and len(result["fitments"]) == 4
    assert result["verified_at"] == result["snapshot_observed_at"]
    evidence = client.get(result["provenance"][0]["evidence_path"]).json()
    assert evidence["body"] == adapter.result["body"]
    assert evidence["content_type"] == "application/json"
    assert evidence["data_state"] == "local_snapshot"
    assert client.get(f"/v1/vehicles/{xiaomi.CURRENT_ID}/fitments").status_code == 422
    historical = client.get(f"/v1/vehicles/{xiaomi.CURRENT_ID}/fitments?mode=history").json()
    assert historical["data_state"] == "local_snapshot" and historical["fact_version"] == 1
    assert count(database, WheelFitment) == 4


def test_failed_live_query_and_denial_never_read_vehicle_snapshots(setup):
    client, adapter, database = setup
    live(client)
    adapter.result = {"status": "unavailable", "reason": "test_outage"}
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        result = live(client).json()
        assert result["data_state"] == "consent_required"
        assert result["fitments"] == result["trims"] == result["provenance"] == []
        assert result["vehicle"] is None
        denied = grant(client, result["query_id"], "deny").json()
        assert live(client, {"consent_id": denied["id"]}).status_code == 403
        assert live(client, {"fallback_policy": "never"}).json()["data_state"] == "source_unavailable"
        assert not any("vehicle_snapshots" in statement.lower() for statement in statements
                       if statement.lstrip().upper().startswith("SELECT"))
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)


def test_grant_is_single_use_preserves_time_and_does_not_requery_online(setup):
    client, adapter, database = setup
    first = live(client).json()
    adapter.result = {"status": "unavailable", "reason": "test_outage"}
    failed = live(client).json()
    consent = grant(client, failed["query_id"]).json()
    call_count = len(adapter.calls)
    result = live(client, {"consent_id": consent["id"]}).json()
    assert result["data_state"] == "local_snapshot" and result["consent_id"] == consent["id"]
    assert result["snapshot_observed_at"] == first["snapshot_observed_at"]
    assert result["provenance"] == first["provenance"] and len(adapter.calls) == call_count
    assert live(client, {"consent_id": consent["id"]}).status_code == 409


def test_tire_vehicle_session_and_generation_grants_are_isolated(setup):
    client, adapter, database = setup
    adapter.result = {"status": "unavailable", "reason": "test_outage"}
    failed_vehicle = live(client).json()
    vehicle_cid = grant(client, failed_vehicle["query_id"]).json()["id"]
    assert live(client, {"consent_id": vehicle_cid}, xiaomi.FIRST_GENERATION_ID).status_code == 403
    assert live(client, {"consent_id": vehicle_cid, "fallback_policy": "never"}).status_code == 403
    another = TestClient(client.app)
    assert live(another, {"consent_id": vehicle_cid}).status_code == 403
    tire_query = {"query": {"size": "265/40R20"}, "fallback_policy": "ask"}
    assert client.post("/v1/sources/fixture/live-query", json={**tire_query, "consent_id": vehicle_cid}).status_code == 403
    tire_failed = client.post("/v1/sources/fixture/live-query", json=tire_query).json()
    tire_cid = grant(client, tire_failed["query_id"]).json()["id"]
    assert live(client, {"consent_id": tire_cid}).status_code == 403
    assert live(client, {"consent_id": vehicle_cid}).json()["reason"] == "no_matching_vehicle_snapshot"


def test_expired_vehicle_consent_cannot_read_evidence(setup):
    client, adapter, database = setup
    adapter.result = {"status": "unavailable", "reason": "test_outage"}
    failed = live(client).json()
    cid = grant(client, failed["query_id"]).json()["id"]
    with database.sessions() as db:
        db.get(FallbackConsent, cid).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert live(client, {"consent_id": cid}).status_code == 410


def test_metadata_change_retains_fact_version_but_real_change_and_revert_append(setup):
    client, adapter, database = setup
    original = live(client).json()
    metadata = source_document()
    metadata["requestTimestamp"] = "fixture-2"
    metadata["data"]["paramComparisonTableVOList"][0]["version"] = 2
    adapter.result = success(metadata)
    same = live(client).json()
    assert same["fact_version"] == 1 and count(database, VehicleSnapshot) == 2
    assert count(database, WheelFitment) == 4
    changed = source_document()
    changed["data"]["paramComparisonTableVOList"][0]["groups"][0]["paramComparisonCols"][0]["paramComparisonCells"][0]["paramValue"] = "○"
    adapter.result = success(changed)
    assert live(client).json()["fact_version"] == 2
    adapter.result = success()
    assert live(client).json()["fact_version"] == 3
    assert count(database, WheelFitment) == 12
    with database.sessions() as db:
        snapshot = db.get(VehicleSnapshot, original["provenance"][0]["snapshot_id"])
        snapshot.body = "tamper"
        with pytest.raises(ValueError, match="只能追加"):
            db.commit()


def test_identical_response_does_not_duplicate_snapshot(setup):
    client, adapter, database = setup
    first = live(client).json()
    second = live(client).json()
    assert first["provenance"] == second["provenance"]
    assert count(database, VehicleSnapshot) == 1 and count(database, WheelFitment) == 4


def test_source_column_and_option_order_changes_do_not_revise_fitments(setup):
    client, adapter, database = setup
    live(client)
    document = source_document()
    table = document["data"]["paramComparisonTableVOList"][0]
    table["carSsuDataList"].reverse()
    columns = table["groups"][0]["paramComparisonCols"]
    columns.reverse()
    for column in columns:
        column["paramComparisonCells"].reverse()
    adapter.result = success(document)
    assert live(client).json()["fact_version"] == 1
    assert count(database, VehicleSnapshot) == 2 and count(database, WheelFitment) == 4


@pytest.mark.parametrize("blocked_host", ["www.xiaomiev.com", "website-api.xiaomiev.com"])
def test_adapter_checks_robots_on_both_origins(monkeypatch, blocked_host):
    class Client:
        def __init__(self, _hosts):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        async def get(self, url, **_kwargs):
            return SimpleNamespace(status=200, body="User-agent: *\nDisallow: /" if blocked_host in url else "")
        async def post(self, *_args, **_kwargs):
            pytest.fail("robots disallow must stop before fetching parameters")
    monkeypatch.setattr(xiaomi, "SafeHttpClient", Client)
    monkeypatch.setattr(xiaomi, "_robots", {})
    monkeypatch.setattr(xiaomi, "_last_fetch", -float("inf"))
    result = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
    assert result['status'] == 'unavailable' and result['reason'] == 'robots_disallowed'
    assert result['parser_version'] == xiaomi.PARSER_VERSION
    assert result['parser_identity']['deployment_revision'] is None


def test_adapter_post_has_fixed_url_and_no_user_input(monkeypatch):
    calls = []
    class Client:
        def __init__(self, _hosts):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        async def get(self, url, **_kwargs):
            calls.append(url)
            return SimpleNamespace(status=404, body="")
        async def post(self, url, **kwargs):
            assert url == xiaomi.API_URL and kwargs["json_body"] == [{}]
            return SimpleNamespace(url=url, body=body(), content_type="application/json")
    monkeypatch.setattr(xiaomi, "SafeHttpClient", Client)
    monkeypatch.setattr(xiaomi, "_robots", {})
    monkeypatch.setattr(xiaomi, "_last_fetch", -float("inf"))
    result = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
    assert result['status'] == 'ok', result
    assert set(calls) == {"https://www.xiaomiev.com/robots.txt", "https://website-api.xiaomiev.com/robots.txt"}


def test_crawl_delay_retries_do_not_extend_the_upstream_deadline(monkeypatch):
    clock = [0.0]
    calls = []
    policy = xiaomi.RobotsPolicy("User-agent: *\nCrawl-delay: 10", xiaomi.USER_AGENT)
    monkeypatch.setattr(xiaomi, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(xiaomi, "_robots", {hostname: (0.0, policy) for hostname in ("www.xiaomiev.com", xiaomi.HOST)})
    monkeypatch.setattr(xiaomi, "_last_fetch", 0.0)
    monkeypatch.setattr(xiaomi, "_busy", False)

    class Client:
        def __init__(self, _hosts):
            calls.append(("client", clock[0]))
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        async def get(self, *_args, **_kwargs):
            pytest.fail("fresh cached robots must not issue another request")
        async def post(self, url, **kwargs):
            calls.append(("post", clock[0]))
            assert xiaomi._last_fetch == clock[0]
            assert url == xiaomi.API_URL and kwargs["json_body"] == [{}]
            return SimpleNamespace(url=url, body=body(), content_type="application/json")

    monkeypatch.setattr(xiaomi, "SafeHttpClient", Client)
    for moment in (2.0, 4.0, 6.0, 8.0):
        clock[0] = moment
        limited = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
        assert limited['status'] == 'unavailable' and limited['reason'] == 'source_rate_limited'
        assert xiaomi._last_fetch == 0.0 and calls == []
    clock[0] = 10.0
    assert asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))["status"] == "ok"
    assert calls == [("client", 10.0), ("post", 10.0)]
    assert xiaomi._last_fetch == 10.0


@pytest.mark.parametrize("failed_host", ["www.xiaomiev.com", "website-api.xiaomiev.com"])
@pytest.mark.parametrize("failure", [SourceAccessError("upstream_http_403"), TimeoutError()])
def test_failed_robots_requests_have_a_budget_without_extending_deadline(monkeypatch, failed_host, failure):
    clock = [0.0]
    requests = []
    monkeypatch.setattr(xiaomi, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    class Client:
        def __init__(self, _hosts):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        async def get(self, url, **_kwargs):
            requests.append((url, clock[0]))
            if url == f"https://{failed_host}/robots.txt":
                raise failure
            return SimpleNamespace(status=404, body="")
        async def post(self, *_args, **_kwargs):
            pytest.fail("a failed robots check cannot reach the configuration POST")

    monkeypatch.setattr(xiaomi, "SafeHttpClient", Client)
    first = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
    assert first["reason"] in {"upstream_http_403", "vehicle_network_unavailable"}
    initial_requests = list(requests)
    for moment in (0.1, 0.5, 1.0, 1.9):
        clock[0] = moment
        limited = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
        assert limited['status'] == 'unavailable' and limited['reason'] == 'source_rate_limited'
        assert requests == initial_requests
        assert xiaomi._robots_requests[failed_host] == 0.0
        assert xiaomi._last_fetch == -float("inf")
    clock[0] = 2.0
    assert asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))["reason"] == first["reason"]
    assert requests == initial_requests + [(f"https://{failed_host}/robots.txt", 2.0)]
    assert xiaomi._robots_requests[failed_host] == 2.0
    clock[0] = 2.1
    assert asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))["reason"] == "source_rate_limited"
    assert xiaomi._robots_requests[failed_host] == 2.0
    assert xiaomi._last_fetch == -float("inf")
