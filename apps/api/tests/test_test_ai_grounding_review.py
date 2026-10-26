"""Independent R70 adversarial checks; only synthetic in-process APIs and storage.

The assertions follow the frozen plan, not the implementation's helper layout.
No test declares that a participant is a SKU, an installed tire, or verified data.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url

from tire_api import ai_analysis, ai_gateway, ai_stream_store as stream_store
from tire_api.ai_evidence import PackBuilder
from tire_api.ai_gateway import GatewayError, OpenAIConfig, analysis_contract, request_body
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.ai_stream_models import AIStreamEvent
from tire_api.ai_stream_parser import StructuredDraftProjector
from tire_api.domain import stable_json
from tire_api.main import create_app
from test_ai_stream_api import seed_accepted
from test_core import FixtureRegistry, live
from test_recalls import RecallFixture, live as recall_live, record
from test_test_events import PAYLOAD, create as create_event
from test_test_preference_routes import interpret, save_preference


GUARDS = {"external_network_attempts": 0, "child_process_attempts": 0,
          "normal_database_attempts": 0, "private_engines": 0,
          "local_socketpair_connections": 0}
EXPECTED_BOUNDARY = {
    "schema": "test-analysis-boundary@1", "policy_version": "test-grounding@1",
    "mode": "fact_selection_only", "participant_identity": "participant_only",
    "sku_link": "not_established", "verification_status": "unverified",
    "notice": "人工转录的本地测试记录，未经在线核验；参测对象尚未与精确SKU建立证据关联。本结果仅摘录所选字段，不代表车辆适配、性能推荐或跨测试排名。",
}
PRIVATE_STORAGE = Path(os.environ.get("R70_REVIEW_STORAGE_ROOT") or str(
    Path(__file__).resolve().parents[3] / ".artifacts" / ("r70-store-" + uuid4().hex)))


@pytest.fixture(autouse=True)
def private_guards(monkeypatch):
    """Fence effects before any fixture can construct an application."""
    import aiohttp
    from tire_api import db as database_module

    # Keep hard-link object paths below the Windows path-length limit while
    # retaining a fresh GUID storage root and a separate private case directory.
    storage = PRIVATE_STORAGE / uuid4().hex[:8]
    storage.mkdir(parents=True, exist_ok=False)
    for name in ("TI_AI_ENABLED", "TI_EMBEDDINGS_ENABLED", "TI_OBSERVABILITY_ENABLED"):
        monkeypatch.setenv(name, "0")
    monkeypatch.setenv("TI_OBJECT_STORE_ROOT", str(storage / "objects"))
    monkeypatch.setenv("TI_PARSER_BUNDLE_ROOT", str(storage / "bundles"))
    monkeypatch.setenv("TIRE_DATABASE_URL", "sqlite:///" + (storage / "private.sqlite").as_posix())

    def network(*_args, **_kwargs):
        GUARDS["external_network_attempts"] += 1
        raise AssertionError("R70 independent review forbids external I/O")

    # Windows implements socketpair through a temporary loopback listener.
    # Permit that internal connection only while this thread is in socketpair;
    # direct loopback connections and all non-loopback destinations stay denied.
    original_connect, original_socketpair = socket.socket.connect, socket.socketpair
    socketpair_state = threading.local()

    def connect(sock, address):
        if (getattr(socketpair_state, "active", False) and isinstance(address, tuple)
                and address[0] in {"127.0.0.1", "::1"}):
            GUARDS["local_socketpair_connections"] += 1
            return original_connect(sock, address)
        return network(sock, address)

    def local_socketpair(*args, **kwargs):
        socketpair_state.active = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            socketpair_state.active = False

    def child(*_args, **_kwargs):
        GUARDS["child_process_attempts"] += 1
        raise AssertionError("R70 independent review forbids parser/child processes")

    original_engine = database_module.create_engine

    def private_engine(url, *args, **kwargs):
        parsed = make_url(url)
        target = Path(parsed.database or "").resolve()
        if parsed.get_backend_name() != "sqlite" or not target.is_relative_to(storage.resolve()):
            GUARDS["normal_database_attempts"] += 1
            raise AssertionError("R70 review attempted a non-private database")
        GUARDS["private_engines"] += 1
        return original_engine(url, *args, **kwargs)

    monkeypatch.setattr(aiohttp, "ClientSession", network)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "socketpair", local_socketpair)
    monkeypatch.setattr(socket, "create_connection", network)
    monkeypatch.setattr(subprocess, "Popen", child)
    monkeypatch.setattr(database_module, "create_engine", private_engine)
    yield
    assert all(GUARDS[key] == 0 for key in (
        "external_network_attempts", "child_process_attempts", "normal_database_attempts"))
    if filename := os.getenv("R70_REVIEW_GUARD_REPORT"):
        Path(filename).write_text(json.dumps(GUARDS, indent=2) + "\n", encoding="utf-8")


def memory_pack(*, mixed=False, marker="both", second_event=False):
    """Use the production builder and the production TestEvent fact shape."""
    builder = PackBuilder()
    if mixed:
        builder.add(kind="manufacturer_official", label="Synthetic exact SKU A",
                    provenance={"variant_id": "synthetic-sku-a", "snapshot_id": "synthetic-snapshot"},
                    values={"产品代码": "SYNTHETIC-A"})
        builder.add(kind="oem_fitment", label="Synthetic vehicle",
                    provenance={"snapshot_id": "synthetic-vehicle"}, values={"轴位": "rear"})
    for event_index in range(2 if second_event else 1):
        provenance = {"revision": 1, "verification_status": "unverified", "verified_at": None}
        if marker != "kind_only":
            provenance["event_id"] = f"synthetic-event-{event_index}"
        values = {"测试尺寸": PAYLOAD["event"]["tested_size"]}
        for index, measurement in enumerate(PAYLOAD["event"]["measurements"], 1):
            person = next(p for p in PAYLOAD["event"]["participants"] if p["key"] == measurement["participant_key"])
            metric = next(m for m in PAYLOAD["event"]["metrics"] if m["key"] == measurement["metric_key"])
            values[f"本场成绩 {index}"] = {"参测胎": deepcopy(person), "指标与条件": deepcopy(metric), **deepcopy(measurement)}
        builder.add(kind="other_source" if marker == "event_only" else "manual_test_independent",
                    label=f"Synthetic test {event_index}", provenance=provenance, values=values, private=True)
    return SimpleNamespace(payload={"evidence": builder.evidence, "facts": builder.facts,
                                   "conflicts": [], "source_state": "snapshot"}, data_state="local_snapshot")


def fact_claim(*facts, kind="fact", text=""):
    return {"type": kind, "text": text, "fact_ids": [f["id"] for f in facts],
            "evidence_ids": list(dict.fromkeys(f["evidence_id"] for f in facts))}


def ground(pack, claims=(), uncertainty=""):
    return ai_analysis.grounded_answer(json.dumps({"claims": list(claims), "uncertainty": uncertainty}), pack)


def test_facts(pack):
    ids = {e["id"] for e in pack.payload["evidence"] if e.get("event_id") or e["kind"].startswith("manual_test_")}
    return [f for f in pack.payload["facts"] if f["evidence_id"] in ids]


test_facts.__test__ = False


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("marker", ["both", "kind_only", "event_only"])
@pytest.mark.parametrize("side", ["test", "all", "single"])
def test_review_all_test_packs_reject_inference_even_single_side(mixed, marker, side):
    pack = memory_pack(mixed=mixed, marker=marker)
    selected = test_facts(pack)[:1] if side == "test" else pack.payload["facts"][:1]
    if side == "all":
        selected = [pack.payload["facts"][0], test_facts(pack)[-1]]
    with pytest.raises(ValueError):
        ground(pack, [fact_claim(*selected, kind="inference", text="This unbridged SKU has superior performance; recommend it.")])


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("uncertainty", ["unbridged SKU recommended", " ", "\n", "来源宣称已关联SKU"])
def test_review_model_uncertainty_is_not_an_alternative_free_text_channel(mixed, uncertainty):
    with pytest.raises(ValueError):
        ground(memory_pack(mixed=mixed), uncertainty=uncertainty)


@pytest.mark.parametrize("mixed", [False, True])
def test_review_empty_fact_selection_has_fixed_server_boundary(mixed):
    result = ground(memory_pack(mixed=mixed))
    assert result["claims"] == [] and result["uncertainty"] == ""
    assert result["test_boundary"] == EXPECTED_BOUNDARY


@pytest.mark.parametrize("pair", ["sku", "vehicle", "participants", "events"])
def test_review_one_test_claim_cannot_join_other_evidence_or_participants(pair):
    pack = memory_pack(mixed=True, second_event=True)
    measurements = [f for f in test_facts(pack) if isinstance(f["value"], dict)]
    first = measurements[0]
    other = {"sku": pack.payload["facts"][0], "vehicle": pack.payload["facts"][1],
             "participants": measurements[1], "events": measurements[3]}[pair]
    with pytest.raises(ValueError):
        ground(pack, [fact_claim(first, other)])


def test_review_separate_fact_claims_keep_events_and_domains_independent():
    pack = memory_pack(mixed=True, second_event=True)
    measurements = [f for f in test_facts(pack) if isinstance(f["value"], dict)]
    selected = [pack.payload["facts"][0], measurements[0], measurements[1], measurements[3]]
    result = ground(pack, [fact_claim(f) for f in selected])
    assert [c["text"] for c in result["claims"]] == [f["text"] for f in selected]
    assert result["test_boundary"] == EXPECTED_BOUNDARY
    assert "38.00" in result["answer"] and "source_rank" in result["answer"]


def test_review_same_participant_multiple_metrics_and_event_metadata_are_legal():
    pack = memory_pack()
    metadata, wet_a, _wet_b, noise_a = test_facts(pack)
    result = ground(pack, [fact_claim(metadata, wet_a, noise_a)])
    assert result["claims"][0]["text"] == "\n".join(f["text"] for f in [metadata, wet_a, noise_a])


@pytest.mark.parametrize("failure", ["unknown_fact", "unknown_evidence", "duplicate_fact", "duplicate_evidence", "free_fact", "space_fact", "newline_fact"])
def test_review_existing_citation_and_server_rendering_gates_remain(failure):
    pack = memory_pack()
    claim = fact_claim(test_facts(pack)[1])
    if failure == "unknown_fact": claim["fact_ids"] = ["not-in-pack"]
    if failure == "unknown_evidence": claim["evidence_ids"] = ["not-in-pack"]
    if failure == "duplicate_fact": claim["fact_ids"] *= 2
    if failure == "duplicate_evidence": claim["evidence_ids"] *= 2
    if failure == "free_fact": claim["text"] = "Fabricated source fact"
    if failure == "space_fact": claim["text"] = " "
    if failure == "newline_fact": claim["text"] = "\n"
    with pytest.raises(ValueError):
        ground(pack, [claim])


def test_review_plain_sku_inference_and_uncertainty_are_unchanged():
    pack = memory_pack(mixed=True)
    pack.payload["evidence"] = pack.payload["evidence"][:2]
    pack.payload["facts"] = pack.payload["facts"][:2]
    result = ground(pack, [fact_claim(pack.payload["facts"][0], kind="inference", text="Check the selected declared code.")], "Human review remains necessary.")
    assert result["claims"][0]["type"] == "inference"
    assert result["uncertainty"] == "Human review remains necessary."
    assert "test_boundary" not in result


@pytest.mark.parametrize("failure", ["inference", "uncertainty", "cross_participants", "test_sku"])
def test_review_projector_rejects_illegal_text_before_any_draft(failure):
    pack = memory_pack(mixed=True)
    facts = test_facts(pack)
    claim = fact_claim(facts[1])
    output = {"claims": [claim], "uncertainty": ""}
    if failure == "inference": claim.update(type="inference", text="Recommend an unbridged SKU")
    if failure == "uncertainty": output = {"uncertainty": "Recommend an unbridged SKU", "claims": []}
    if failure == "cross_participants": output["claims"] = [fact_claim(facts[1], facts[2])]
    if failure == "test_sku": output["claims"] = [fact_claim(facts[1], pack.payload["facts"][0])]
    projector = StructuredDraftProjector({"payload": pack.payload, "data_state": pack.data_state})
    with pytest.raises(GatewayError, match="ai_grounding_validation_failed"):
        projector.feed(json.dumps(output))
    assert projector.claims == []


def test_review_projector_preserves_valid_fact_before_rejecting_late_uncertainty():
    pack = memory_pack()
    claim = fact_claim(test_facts(pack)[1])
    projector = StructuredDraftProjector({"payload": pack.payload, "data_state": pack.data_state})
    events = projector.feed('{"claims":[' + json.dumps(claim) + ']')
    assert [e["type"] for e in events] == ["claim_draft"]
    assert events[0]["payload"]["claim"]["text"] == test_facts(pack)[1]["text"]
    with pytest.raises(GatewayError, match="ai_grounding_validation_failed"):
        projector.feed(',"uncertainty":"Unsafe free text"}')


@pytest.mark.parametrize("provider", ["openai_responses", "openai_chat", "anthropic"])
@pytest.mark.parametrize("stream", [False, True])
def test_review_three_provider_schema_prompt_and_actual_reservation(provider, stream, monkeypatch):
    pack = memory_pack(mixed=True)
    config = OpenAIConfig(model="synthetic-review", api_key="synthetic-never-live", provider=provider,
                          response_format="json_schema", allow_private=True)
    question = "摘录所选人工测试字段"
    body, reserve = request_body(config, question, pack.payload, stream=stream)
    if provider == "openai_responses":
        system = body["input"][0]["content"]
        schema = body["text"]["format"]["schema"]
        assert body["text"]["format"]["name"] == "test_evidence_answer"
    elif provider == "openai_chat":
        system = body["messages"][0]["content"]
        schema = body["response_format"]["json_schema"]["schema"]
        assert body["response_format"]["json_schema"]["name"] == "test_evidence_answer"
    else:
        system = body["system"]
        schema = json.loads(system.rsplit("\n", 1)[-1])
    assert schema["properties"]["claims"]["items"]["properties"]["type"]["enum"] == ["fact"]
    assert schema["properties"]["claims"]["items"]["properties"]["text"]["enum"] == [""]
    assert schema["properties"]["uncertainty"]["enum"] == [""]
    assert "参测" in system and "SKU" in system
    assert body["stream"] is stream
    assert "synthetic-never-live" not in json.dumps(body)
    transmitted = stable_json({"question": question, "untrusted_evidence_pack": pack.payload})
    byte_count = len((system + transmitted).encode("utf-8"))
    assert reserve == byte_count + len(stable_json(schema).encode()) + config.max_output_tokens + 2048
    monkeypatch.setattr(ai_gateway, "MAX_REQUEST_BYTES", byte_count - 1)
    with pytest.raises(GatewayError, match="ai_evidence_too_large"):
        request_body(config, question, pack.payload, stream=stream)
    contract = analysis_contract(pack.payload)
    assert contract["prompt_version"] == "test-grounding@1"
    assert contract["test_boundary"] == EXPECTED_BOUNDARY


class SyntheticModel:
    def __init__(self):
        self.failure = None
        self.calls = 0

    def output(self, body):
        self.calls += 1
        evidence = json.loads(body["input"][1]["content"])["untrusted_evidence_pack"]
        tests = {e["id"] for e in evidence["evidence"] if e.get("event_id")}
        measurements = [f for f in evidence["facts"] if f["evidence_id"] in tests and isinstance(f["value"], dict) and "participant_key" in f["value"]]
        tire = next((f for f in evidence["facts"] if f["evidence_id"] not in tests), None)
        claim = fact_claim(measurements[0])
        output = {"claims": [claim], "uncertainty": ""}
        if self.failure == "inference": claim.update(type="inference", text="Recommend unbridged SKU")
        if self.failure == "single_sku": output["claims"] = [fact_claim(tire, kind="inference", text="The unrelated test proves this SKU wins.")]
        if self.failure == "cross_participants": output["claims"] = [fact_claim(*measurements[:2])]
        if self.failure == "uncertainty": output = {"uncertainty": "Recommend unbridged SKU", "claims": []}
        return output

    @staticmethod
    def receipt(text):
        return {"text": text, "error": None, "usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
                "provider_response_id": "synthetic_review_response"}

    async def generate(self, _config, body):
        return self.receipt(json.dumps(self.output(body)))

    async def stream(self, _config, body, on_text):
        text = json.dumps(self.output(body))
        await on_text(text)
        return self.receipt(text)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(ai_analysis, "configured_model", lambda: OpenAIConfig(
        model="synthetic-review", api_key="synthetic-never-live", allow_private=True))
    registry = FixtureRegistry()
    registry.supports_parser_deployments = False
    app = create_app(os.environ["TIRE_DATABASE_URL"], registry)
    model = SyntheticModel()
    app.state.ai_adapter = model
    with TestClient(app) as client:
        row = create_event(client)
        tire = live(client)
        assert tire.status_code == 200, tire.text
        tire = tire.json()
        references = [{"kind": "test_event", "event_id": row["id"], "event_revision": row["revision"]},
                      {"kind": "tire", "snapshot_id": tire["provenance"][0]["snapshot_id"], "variant_id": tire["variants"][0]["id"]}]
        response = client.post("/v1/ai/evidence-packs", json={"mode": "history", "references": references})
        assert response.status_code == 200, response.text
        yield client, app, model, response.json()["pack"], row, references


def submit(client, pack, channel, key):
    return client.post("/v1/ai/" + ("analyses" if channel == "sync" else "analysis-streams"),
                       headers={"Idempotency-Key": key}, json={"pack_id": pack["id"],
                       "question": "摘录所选历史字段", "allow_external_processing": True})


def terminal(client, response, channel):
    assert response.status_code in (200, 202), response.text
    if channel == "sync":
        return response.json(), None
    request_id = response.json()["analysis"]["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get(f"/v1/ai/analysis-streams/{request_id}?mode=history")
        assert result.status_code == 200, result.text
        result = result.json()
        if result["execution"]["terminal"]:
            return result["analysis"], result
        time.sleep(0.01)
    pytest.fail("Private synthetic stream failed to reach a terminal state")


@pytest.mark.parametrize("channel", ["sync", "stream"])
@pytest.mark.parametrize("failure", ["inference", "single_sku", "uncertainty", "cross_participants"])
def test_review_public_invalid_answers_fail_once_preserve_usage_and_no_illegal_draft(api, channel, failure):
    client, app, model, pack, _event, _refs = api
    model.failure = failure
    key = str(uuid4())
    run, execution = terminal(client, submit(client, pack, channel, key), channel)
    assert run["state"] == "failed" and run["answer"] is None
    assert run["error_code"] == "ai_grounding_validation_failed"
    assert model.calls == 1
    replay = submit(client, pack, channel, key)
    assert replay.status_code == 200 and model.calls == 1
    with app.state.database.sessions() as db:
        completion = db.get(AICompletion, run["id"])
        assert completion.state == "failed" and completion.answer is None
        assert completion.usage == ({"input_tokens": 50, "output_tokens": 10, "total_tokens": 60} if channel == "sync" else None)
        events = list(db.scalars(select(AIStreamEvent).where(AIStreamEvent.request_id == run["id"])))
        assert not any(e.type in {"claim_draft", "uncertainty_draft"} for e in events)
    budget = client.get("/v1/ai/status").json()["budget"]
    assert budget["accounted_tokens"] == (60 if channel == "sync" else run["reserved_tokens"])
    if execution:
        assert execution["draft_claims"] == [] and execution["draft_uncertainty"] is None


@pytest.mark.parametrize("channel", ["sync", "stream"])
def test_review_public_valid_fact_returns_boundary_once(api, channel):
    client, _app, model, pack, _event, _refs = api
    run, _execution = terminal(client, submit(client, pack, channel, str(uuid4())), channel)
    assert run["state"] == "completed" and model.calls == 1
    assert run["answer"]["test_boundary"] == EXPECTED_BOUNDARY
    assert run["answer"]["uncertainty"] == ""
    assert run["request_contract"]["prompt_version"] == "test-grounding@1"
    assert "38.00" in run["answer"]["claims"][0]["text"]


def test_review_store_also_rejects_direct_uncertainty_injection(api):
    client, app, _model, pack, _event, _refs = api
    from tire_api.main import SESSION_COOKIE
    request_id, token = seed_accepted(app.state.database, client.cookies.get(SESSION_COOKIE), pack["id"])
    assert stream_store.start_execution(app.state.database, request_id, token)
    with pytest.raises(ValueError):
        stream_store.append_event(app.state.database, request_id, token, "uncertainty_draft", {"text": "Unsafe recommendation"})
    with app.state.database.sessions() as db:
        assert not list(db.scalars(select(AIStreamEvent).where(AIStreamEvent.request_id == request_id, AIStreamEvent.type == "uncertainty_draft")))


def test_review_same_event_preference_interpretation_is_unchanged(api):
    client, _app, model, _pack, event, _refs = api
    preference = save_preference(client)
    response = interpret(client, event, preference)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["policy_version"] == "same-event-preference@1"
    assert result["ranking"] == "source_reported_only" and model.calls == 0
    assert all(p["identity_status"] == "participant_only" for p in result["source_evidence"]["participants"])
    assert result["source_evidence"]["measurements"][0]["raw_value"] == "38.00"


def test_review_recall_mixed_with_test_retains_both_contracts(api):
    client, app, _model, _pack, _event, references = api
    recall = RecallFixture()
    recall.rows = [record("SYNTHETIC A"), record("SYNTHETIC B")]
    app.state.recall_adapter = recall
    response = recall_live(client)
    assert response.status_code == 200, response.text
    assert isinstance(response.json().get("analysis_reference"), dict), response.text
    refs = [references[0], response.json()["analysis_reference"]]
    response = client.post("/v1/ai/evidence-packs", json={"mode": "history", "references": refs})
    assert response.status_code == 200, response.text
    packed = response.json()["pack"]
    pack = SimpleNamespace(payload=packed, data_state=packed["data_state"])
    tests = test_facts(pack)
    recall_facts = [f for f in packed["facts"] if f.get("scope") == "record" and f["field_code"] == "recall.remedy"]
    result = ground(pack, [fact_claim(tests[0]), fact_claim(recall_facts[0])])
    assert result["test_boundary"] == EXPECTED_BOUNDARY and result["recall_boundary"]["applicability"] == "not_assessed"
    for facts in ([tests[0], recall_facts[0]], recall_facts[:2]):
        with pytest.raises(ValueError): ground(pack, [fact_claim(*facts)])
    with pytest.raises(ValueError): ground(pack, uncertainty="Not recalled")
    body, _reserve = request_body(OpenAIConfig(model="synthetic", api_key="synthetic"), "摘录历史字段", packed)
    assert body["text"]["format"]["schema"]["properties"]["claims"]["items"]["properties"]["type"]["enum"] == ["fact"]
