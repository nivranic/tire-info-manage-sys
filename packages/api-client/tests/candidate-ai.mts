/** Independent C wire and injected transport checks; no server or Provider. */
import assert from "node:assert/strict";
import { ApiError, CandidateAiContractError, setApiTransport, tireApi } from "@tire/api-client";
import type { CandidateAiAuthorizationRequest, CandidateAiPrepareRequest, CandidateAiPreparation, CandidateAiRecommendation, CandidateAiSubmitRequest } from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type Prepared = Assert<Equal<Awaited<ReturnType<typeof tireApi.prepareCandidateAI>>, CandidateAiPreparation>>;
type History = Assert<Equal<Awaited<ReturnType<typeof tireApi.candidateAIRecommendation>>, CandidateAiRecommendation>>;
type NoScore = Assert<Equal<NonNullable<CandidateAiRecommendation["answer"]>["performance_score"], null>>;
type NoRanking = Assert<Equal<NonNullable<CandidateAiRecommendation["answer"]>["ranking"], "not_computed">>;
type Historical = Assert<Equal<CandidateAiRecommendation["current"], false>>;
// @ts-expect-error A personal checkbox cannot grant material use or add an actor.
const actorOverride: CandidateAiPrepareRequest = { actor: "other", provider_use: true };
// @ts-expect-error Submission requires a bound affirmative consent, not a false/optional toggle.
const denied: CandidateAiSubmitRequest = { preparation_id: "p", consent_hash: "x", allow_external_processing: false };
// @ts-expect-error This C slice cannot turn model choice into a performance score.
const score: NonNullable<CandidateAiRecommendation["answer"]>["performance_score"] = 0;

const hash = "a".repeat(64), otherHash = "b".repeat(64), key = "4bb51843-2fdd-4490-9f41-c1084ded0cc4";
const selection = { vehicle_id: "vehicle", vehicle_snapshot_id: "vehicle-snapshot", trim_id: "trim", wheel_option_id: "wheel", axle: "front" as const };
const payload: CandidateAiPrepareRequest = { selection, expected_preference_revision: 2, expected_preference_fingerprint: hash, variant_ids: ["sku-a", "sku-b"], question: "仅核对规格候选与未知项。" };
const prepared: CandidateAiPreparation = {
  schema: "candidate-ai-preparation@1", purpose: "candidate_spec_assistance@1", preparation_id: "preparation", pack_id: "pack", fingerprint: hash,
  selection, preference: { revision: 2, fingerprint: hash, weights: { dry: 20, wet: 30, quiet: 15, comfort: 10, wear: 10, energy: 10, appearance: 5 } },
  candidates: payload.variant_ids.map(variant_id => ({ variant_id,
    identity: { brand: "Synthetic", model: "Synthetic", manufacturer_product_code: variant_id, product_code_type: "MSPN", region: "CN", size: "245/40R20", load_index: "101", speed_rating: "Y", xl: true, hl: false, oe_mark: null, acoustic_technology: null, run_flat: null },
    reasons: [{ id: "reason-" + variant_id, text: "来源尺寸检查一致，不证明安装安全或性能。", reference: { variant_id, relation_id: "relation-" + variant_id, relation_revision_id: "revision-" + variant_id, relation_revision: 2, selection, field: "size", status: "match", value: "245/40R20" } }], unknown_fields: ["run_flat"],
  })),
  dependencies: [{ id: "dependency", source_kind: "tire", snapshot_id: "tire-snapshot", raw_hash: hash, projection_hash: otherHash, fields: ["identity.brand", "identity.size"], authorization: { state: "granted", revision_id: "grant", revision: 1, expires_at: "2099-01-01T00:00:00+00:00" } }],
  blockers: [], provider: { provider: "openai_responses", model: "synthetic-controlled", endpoint_host: "fixture.invalid", state: "configured", policy_fingerprint: hash, body_hash: otherHash, reserved_tokens: 1200 },
  consent_hash: otherHash, expires_at: "2098-01-01T00:00:00+00:00", sendable: true,
};
const authorization: CandidateAiAuthorizationRequest = {
  dependency_id: "dependency", provider: "openai_responses", expected_revision: 1, action: "grant", rights_holder: "Synthetic fixture author",
  license_basis_url: "https://fixture.invalid/license", license_basis_note: "Synthetic self-owned fixture, controlled engineering only.",
  license_evidence_sha256: hash, expires_at: "2099-01-01T00:00:00+00:00", acknowledged: true,
};
const recommendation: CandidateAiRecommendation = {
  schema: "candidate-ai-recommendation@1", id: "recommendation", pack_id: "pack", state: "completed", usage: { input_tokens: 50, output_tokens: 10, total_tokens: 60 },
  reserved_tokens: 1200, error_code: null, created_at: "2026-10-18T00:00:00+00:00", completed_at: "2026-10-18T00:01:00+00:00", purpose: "candidate_spec_assistance@1",
  answer: { decision: "choose", selections: [{ variant_id: "sku-a", reasons: prepared.candidates[0].reasons }], not_selected_variant_ids: ["sku-b"], uncertainty: [
    { code: "performance_evidence_unavailable", text: "七维精确SKU性能证据未建立。" },
    { code: "installation_safety_unestablished", text: "安装安全结论未建立。" },
    { code: "official_oe_unestablished", text: "官方原配结论未建立。" },
    { code: "preference_performance_unestablished", text: "偏好与精确SKU性能关联未建立。" },
  ], ranking: "not_computed", performance_score: null, performance_evidence: "not_established", notice: "规格选择不表明优于未选项，也不改变适配资格。" },
  current: false, preparation: prepared, current_status: { state: "unchanged", blockers: [] },
};
const submit: CandidateAiSubmitRequest = { preparation_id: prepared.preparation_id, consent_hash: otherHash, allow_external_processing: true };
const calls: { path: string; init: RequestInit }[] = [];
let response: unknown = prepared, status = 200, throwing = false;
const restore = setApiTransport(async (path, init) => {
  calls.push({ path, init });
  if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
  if (throwing) throw Object.assign(new Error("synthetic timeout"), { code: "request_timeout" });
  return new Response(JSON.stringify(status === 200 ? response : { detail: { code: "candidate_ai_binding_changed", message: "Synthetic rejection" } }), { status });
});
let checks = 0;
const passed = () => { checks++; };
try {
  const controller = new AbortController();
  assert.deepEqual(await tireApi.prepareCandidateAI(payload, controller.signal), prepared);
  let call = calls.at(-1)!;
  assert.equal(call.path, "/v1/ai/candidate-preparations"); assert.equal(call.init.method, "POST"); assert.equal(call.init.signal, controller.signal);
  assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store"); assert.deepEqual(JSON.parse(String(call.init.body)), payload); passed();
  const noConfiguration = structuredClone(prepared);
  noConfiguration.provider = null; noConfiguration.consent_hash = null; noConfiguration.sendable = false; noConfiguration.blockers = ["ai_configuration_required", "candidate_ai_authorization_required"];
  noConfiguration.dependencies[0].authorization = null; response = noConfiguration;
  assert.deepEqual(await tireApi.prepareCandidateAI(payload), noConfiguration); passed();
  response = { schema: "candidate-ai-authorization@1", purpose: prepared.purpose, dependency_id: authorization.dependency_id, provider: authorization.provider, state: "granted", revision_id: "next-grant", revision: 2,
    rights_holder: authorization.rights_holder, license_basis_url: authorization.license_basis_url, license_basis_note: authorization.license_basis_note, license_evidence_sha256: authorization.license_evidence_sha256, expires_at: authorization.expires_at, recipient_fingerprint: hash };
  await tireApi.authorizeCandidateAI("preparation/a?b#c", authorization);
  assert.equal(calls.at(-1)!.path, "/v1/ai/candidate-preparations/preparation%2Fa%3Fb%23c/authorizations"); passed();
  const revoke: CandidateAiAuthorizationRequest = { dependency_id: authorization.dependency_id, provider: authorization.provider, expected_revision: 1, action: "revoke", acknowledged: true, revocation_note: "Withdraw this synthetic fixture permission." };
  const authorizationResponse = structuredClone(response) as Record<string, unknown>;
  response = { ...authorizationResponse, state: "revoked" };
  await tireApi.authorizeCandidateAI("preparation", revoke);
  assert.deepEqual(JSON.parse(String(calls.at(-1)!.init.body)), revoke); passed();
  response = { ...authorizationResponse, recipient_fingerprint: null };
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", authorization), CandidateAiContractError); passed();
  response = recommendation;
  assert.deepEqual(await tireApi.submitCandidateAI(submit, key), recommendation);
  call = calls.at(-1)!; assert.equal(new Headers(call.init.headers).get("Idempotency-Key"), key); assert.deepEqual(JSON.parse(String(call.init.body)), submit); passed();
  await tireApi.candidateAIRecommendation("recommendation"); assert.equal(calls.at(-1)!.path, "/v1/ai/candidate-recommendations/recommendation?mode=history"); assert.equal(calls.at(-1)!.init.method, undefined); passed();
  await tireApi.lookupCandidateAIRecommendation(key); assert.equal(calls.at(-1)!.path, `/v1/ai/candidate-recommendations?mode=history&key=${key}`); assert.equal(calls.at(-1)!.init.method, undefined); passed();
  const abstained = structuredClone(recommendation);
  abstained.answer!.decision = "abstain"; abstained.answer!.selections = []; abstained.answer!.not_selected_variant_ids = ["sku-a", "sku-b"];
  abstained.answer!.uncertainty.push({ code: "no_supported_selection", text: "本次没有可支持的规格选择。" }); response = abstained;
  assert.deepEqual(await tireApi.submitCandidateAI(submit, key), abstained); passed();
  for (const change of [
    (p: any) => { p.sendable = 1; }, (p: any) => { p.candidates[0].identity.xl = 1; },
    (p: any) => { p.candidates[0].identity.facts = {}; }, (p: any) => { p.candidates[0].reasons[0].reference.status = "unknown"; },
    (p: any) => { p.candidates[0].reasons[0].reference.variant_id = "sku-b"; }, (p: any) => { p.dependencies[0].authorization.revision = true; },
    (p: any) => { p.candidates[1].variant_id = "foreign"; }, (p: any) => { p.candidates[1].variant_id = "sku-a"; },
    (p: any) => { p.dependencies[0].source_kind = "test_event"; }, (p: any) => { p.provider.body_hash = "not a hash"; },
    (p: any) => { delete p.provider.endpoint_host; }, (p: any) => { p.provider.endpoint_host = false; },
    (p: any) => { p.selection.axle = "rear"; }, (p: any) => { p.consent_hash = null; },
    (p: any) => { p.dependencies[0].source_kind = ["tire"]; }, (p: any) => { p.dependencies[0].authorization.state = ["granted"]; },
  ]) {
    response = structuredClone(prepared); change(response);
    await assert.rejects(tireApi.prepareCandidateAI(payload), CandidateAiContractError); passed();
  }
  for (const change of [
    (r: any) => { r.current = true; }, (r: any) => { r.answer.performance_score = 0; },
    (r: any) => { r.answer.ranking = "weighted"; }, (r: any) => { r.answer.free_text = "unsupported fact"; },
    (r: any) => { r.answer.selections[0].variant_id = "foreign"; },
    (r: any) => { r.answer.selections[0].reasons = r.preparation.candidates[1].reasons; },
    (r: any) => { r.answer.not_selected_variant_ids = ["sku-a", "sku-b"]; },
    (r: any) => { r.answer.decision = "abstain"; }, (r: any) => { r.state = "pending"; },
    (r: any) => { r.usage.total_tokens = true; }, (r: any) => { r.preparation.consent_hash = hash; },
    (r: any) => { r.answer.decision = ["choose"]; },
    (r: any) => { r.answer.uncertainty[0].code = "unknown"; },
    (r: any) => { r.answer.uncertainty.push(r.answer.uncertainty[0]); },
    (r: any) => { r.answer.uncertainty.pop(); },
    (r: any) => { r.answer.decision = "abstain"; r.answer.selections = []; r.answer.not_selected_variant_ids = ["sku-a", "sku-b"]; },
  ]) {
    response = structuredClone(recommendation); change(response);
    await assert.rejects(tireApi.submitCandidateAI(submit, key), CandidateAiContractError); passed();
  }
  const beforeInvalid = calls.length;
  await assert.rejects(tireApi.prepareCandidateAI({ ...payload, actor: "foreign" } as any), CandidateAiContractError); passed();
  await assert.rejects(tireApi.prepareCandidateAI({ ...payload, selection: { ...selection, axle: ["front"] } } as any), CandidateAiContractError); passed();
  await assert.rejects(tireApi.submitCandidateAI({ ...submit, allow_external_processing: false } as any, key), CandidateAiContractError); passed();
  await assert.rejects(tireApi.submitCandidateAI(submit, "not-a-uuid"), CandidateAiContractError); passed();
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", { ...authorization, acknowledged: false } as any), CandidateAiContractError); passed();
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", { ...authorization, license_basis_url: "https://name:secret@fixture.invalid/license?identity=value" }), CandidateAiContractError); passed();
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", { ...authorization, license_basis_url: "http://fixture.invalid/license" }), CandidateAiContractError); passed();
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", { ...authorization, action: "revoke", revocation_note: "Do not renew." } as any), CandidateAiContractError); passed();
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", { ...revoke, action: "grant" } as any), CandidateAiContractError); passed();
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", { ...revoke, expected_revision: 0 }), CandidateAiContractError); passed();
  await assert.rejects(tireApi.authorizeCandidateAI("preparation", { ...revoke, revocation_note: "   " }), CandidateAiContractError); passed();
  assert.equal(calls.length, beforeInvalid);
  response = recommendation;
  throwing = true; const beforeTimeout = calls.length;
  await assert.rejects(tireApi.submitCandidateAI(submit, key), error => error instanceof Error && "code" in error && error.code === "api_timeout");
  assert.equal(calls.length, beforeTimeout + 1); passed();
  throwing = false; await tireApi.lookupCandidateAIRecommendation(key); assert.equal(calls.length, beforeTimeout + 2); assert.equal(calls.at(-1)!.init.method, undefined); passed();
  for (const errorStatus of [401, 403, 409, 422]) {
    status = errorStatus; const before = calls.length;
    await assert.rejects(tireApi.submitCandidateAI(submit, key), error => error instanceof ApiError && error.status === errorStatus && error.code === "candidate_ai_binding_changed");
    assert.equal(calls.length, before + 1); passed();
  }
  status = 200; controller.abort();
  await assert.rejects(tireApi.prepareCandidateAI(payload, controller.signal), error => error instanceof DOMException && error.name === "AbortError"); passed();
  console.log(`candidate-ai: ${checks} wire/transport checks passed; injected transport only, no backend/Provider acceptance`);
} finally { restore(); }
