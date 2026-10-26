import type {
  CandidateAiAuthorization, CandidateAiAuthorizationRequest, CandidateAiPreparation,
  CandidateAiPrepareRequest, CandidateAiRecommendation, CandidateAiSubmitRequest,
} from "@tire/domain-types";

type ObjectValue = Record<string, unknown>;
type Send = <T>(path: string, init?: RequestInit) => Promise<T>;
const purpose = "candidate_spec_assistance@1";
const selectionKeys = ["vehicle_id", "vehicle_snapshot_id", "trim_id", "wheel_option_id", "axle"];
const weightKeys = ["dry", "wet", "quiet", "comfort", "wear", "energy", "appearance"];
const identityRequired = ["brand", "model", "manufacturer_product_code", "region", "size", "load_index", "speed_rating", "xl", "hl", "oe_mark", "acoustic_technology", "run_flat", "product_code_type"];
const identityOptional = ["gtin", "technology_features", "eprel_id"];
const fixedUncertainty = ["performance_evidence_unavailable", "installation_safety_unestablished", "official_oe_unestablished", "preference_performance_unestablished"];
const uncertaintyCodes = [...fixedUncertainty, "insufficient_spec_evidence", "no_supported_selection"];
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const integer = (value: unknown, minimum = 0) => typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
const text = (value: unknown, maximum = 4000): value is string => typeof value === "string" && value.length > 0 && value.length <= maximum && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value);
const id = (value: unknown): value is string => text(value, 200) && !/[\r\n]/.test(value);
const timestamp = (value: unknown): value is string => text(value, 80) && Number.isFinite(Date.parse(value));
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
const object = (value: unknown): value is ObjectValue => !!value && typeof value === "object" && !Array.isArray(value);
const exact = (value: unknown, keys: readonly string[]): value is ObjectValue => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 10000 && value.every(item => text(item));
const unique = (values: readonly unknown[]) => new Set(values).size === values.length;
const literal = (value: unknown, allowed: readonly string[]) => typeof value === "string" && allowed.includes(value);
const atom = (value: unknown): boolean => value === null || typeof value === "boolean" || typeof value === "string" || typeof value === "number" && Number.isFinite(value);
const valueValid = (value: unknown) => atom(value) || Array.isArray(value) && value.length <= 100 && value.every(atom);
const same = (left: unknown, right: unknown): boolean => {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left)) return Array.isArray(right) && left.length === right.length && left.every((item, index) => same(item, right[index]));
  return object(left) && object(right) && Object.keys(left).length === Object.keys(right).length && Object.keys(left).every(key => Object.hasOwn(right, key) && same(left[key], right[key]));
};
const selection = (value: unknown) => exact(value, selectionKeys) && selectionKeys.slice(0, 4).every(key => id(value[key])) && literal(value.axle, ["front", "rear"]);
const weights = (value: unknown) => value === null || exact(value, weightKeys) && weightKeys.every(key => integer(value[key]) && Number(value[key]) <= 100) && weightKeys.reduce((total, key) => total + Number(value[key]), 0) === 100;
const basisUrl = (value: unknown) => {
  if (!text(value, 2048)) return false;
  try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash; } catch { return false; }
};

export class CandidateAiContractError extends Error {
  readonly code = "candidate_ai_contract_invalid";
  constructor() { super("规格候选辅助数据与本次范围或独立合同不一致，未显示替代结果。"); this.name = "CandidateAiContractError"; }
}
function check(condition: unknown): asserts condition { if (!condition) throw new CandidateAiContractError(); }

function reason(value: unknown, variantId: unknown, scope: unknown): boolean {
  if (!exact(value, ["id", "text", "reference"]) || !id(value.id) || !text(value.text)) return false;
  const ref = value.reference;
  return exact(ref, ["variant_id", "relation_id", "relation_revision_id", "relation_revision", "selection", "field", "status", "value"])
    && ref.variant_id === variantId && id(ref.relation_id) && id(ref.relation_revision_id) && integer(ref.relation_revision, 1)
    && selection(ref.selection) && same(ref.selection, scope) && id(ref.field) && ref.status === "match" && valueValid(ref.value);
}

export function assertCandidateAiPreparation(value: unknown): asserts value is CandidateAiPreparation {
  check(exact(value, ["schema", "purpose", "preparation_id", "pack_id", "fingerprint", "selection", "preference", "candidates", "dependencies", "blockers", "provider", "consent_hash", "expires_at", "sendable"]));
  check(value.schema === "candidate-ai-preparation@1" && value.purpose === purpose && id(value.preparation_id) && id(value.pack_id)
    && hash(value.fingerprint) && selection(value.selection) && timestamp(value.expires_at) && typeof value.sendable === "boolean");
  const preference = value.preference;
  check(exact(preference, ["revision", "fingerprint", "weights"]) && integer(preference.revision) && hash(preference.fingerprint) && weights(preference.weights));
  const candidates = value.candidates;
  check(Array.isArray(candidates) && candidates.length >= 2 && candidates.length <= 20 && unique(candidates.map(item => object(item) ? item.variant_id : null)));
  const allReasons: string[] = [];
  for (const candidate of candidates) {
    check(exact(candidate, ["variant_id", "identity", "reasons", "unknown_fields"]) && id(candidate.variant_id) && object(candidate.identity));
    const identity = candidate.identity;
    check(identityRequired.every(key => Object.hasOwn(identity, key)) && Object.keys(identity).every(key => [...identityRequired, ...identityOptional].includes(key))
      && Object.values(identity).every(valueValid)
      && ["xl", "hl", "run_flat"].every(key => identity[key] === null || typeof identity[key] === "boolean")
      && Object.keys(identity).filter(key => !["xl", "hl", "run_flat", "technology_features"].includes(key)).every(key => identity[key] === null || typeof identity[key] === "string")
      && (!Object.hasOwn(identity, "technology_features") || strings(identity.technology_features)));
    check(Array.isArray(candidate.reasons) && candidate.reasons.length <= 10000 && candidate.reasons.every(item => reason(item, candidate.variant_id, value.selection)) && strings(candidate.unknown_fields));
    allReasons.push(...candidate.reasons.map(item => String((item as ObjectValue).id)));
  }
  check(unique(allReasons));
  const dependencies = value.dependencies;
  check(Array.isArray(dependencies) && dependencies.length > 0 && dependencies.length <= 10000 && unique(dependencies.map(item => object(item) ? item.id : null)));
  for (const dependency of dependencies) {
    check(exact(dependency, ["id", "source_kind", "snapshot_id", "raw_hash", "projection_hash", "fields", "authorization"])
      && id(dependency.id) && literal(dependency.source_kind, ["vehicle", "tire", "relation"]) && id(dependency.snapshot_id)
      && hash(dependency.raw_hash) && hash(dependency.projection_hash) && strings(dependency.fields) && dependency.fields.length > 0 && unique(dependency.fields));
    const auth = dependency.authorization;
    check(auth === null || exact(auth, ["state", "revision_id", "revision", "expires_at"]) && literal(auth.state, ["granted", "revoked", "expired"])
      && id(auth.revision_id) && integer(auth.revision, 1) && timestamp(auth.expires_at));
  }
  check(strings(value.blockers) && (value.consent_hash === null || hash(value.consent_hash)));
  const provider = value.provider;
  check(provider === null || exact(provider, ["provider", "model", "endpoint_host", "state", "policy_fingerprint", "body_hash", "reserved_tokens"])
    && id(provider.provider) && id(provider.model) && id(provider.endpoint_host) && provider.state === "configured" && hash(provider.policy_fingerprint) && hash(provider.body_hash) && integer(provider.reserved_tokens));
  if (value.sendable) check(provider !== null && hash(value.consent_hash) && value.blockers.length === 0 && dependencies.every(item => (item as { authorization: { state: string } | null }).authorization?.state === "granted"));
}

function assertPrepareRequest(value: unknown): asserts value is CandidateAiPrepareRequest {
  check(exact(value, ["selection", "expected_preference_revision", "expected_preference_fingerprint", "variant_ids", "question"])
    && selection(value.selection) && integer(value.expected_preference_revision) && hash(value.expected_preference_fingerprint)
    && strings(value.variant_ids) && value.variant_ids.length >= 2 && value.variant_ids.length <= 20 && value.variant_ids.every(id) && unique(value.variant_ids)
    && text(value.question, 2000) && value.question.trim().length >= 2);
}
function assertAuthorizationRequest(value: unknown): asserts value is CandidateAiAuthorizationRequest {
  check(object(value) && id(value.dependency_id) && id(value.provider) && integer(value.expected_revision) && value.acknowledged === true);
  if (value.action === "revoke") {
    check(exact(value, ["dependency_id", "provider", "expected_revision", "action", "acknowledged", "revocation_note"])
      && integer(value.expected_revision, 1) && text(value.revocation_note, 2000) && value.revocation_note.trim().length > 0);
    return;
  }
  check(exact(value, ["dependency_id", "provider", "expected_revision", "action", "rights_holder", "license_basis_url", "license_basis_note", "license_evidence_sha256", "expires_at", "acknowledged"])
    && value.action === "grant" && text(value.rights_holder, 200) && basisUrl(value.license_basis_url) && text(value.license_basis_note, 2000)
    && hash(value.license_evidence_sha256) && timestamp(value.expires_at));
}
export function assertCandidateAiRecommendation(value: unknown): asserts value is CandidateAiRecommendation {
  check(exact(value, ["schema", "id", "pack_id", "state", "usage", "reserved_tokens", "error_code", "created_at", "completed_at", "purpose", "answer", "current", "preparation", "current_status"])
    && value.schema === "candidate-ai-recommendation@1" && value.purpose === purpose && id(value.id) && id(value.pack_id)
    && literal(value.state, ["pending", "outcome_unknown", "completed", "failed"]) && integer(value.reserved_tokens)
    && (value.error_code === null || id(value.error_code)) && timestamp(value.created_at) && (value.completed_at === null || timestamp(value.completed_at)) && value.current === false);
  assertCandidateAiPreparation(value.preparation);
  check(value.pack_id === value.preparation.pack_id);
  check(exact(value.current_status, ["state", "blockers"]) && literal(value.current_status.state, ["unchanged", "stale"]) && strings(value.current_status.blockers));
  check(value.usage === null || exact(value.usage, ["input_tokens", "output_tokens", "total_tokens"]) && Object.values(value.usage).every(item => integer(item)));
  check(value.state === "completed" ? value.answer !== null : value.answer === null);
  if (value.answer === null) return;
  const answer = value.answer;
  check(exact(answer, ["decision", "selections", "not_selected_variant_ids", "uncertainty", "ranking", "performance_score", "performance_evidence", "notice"])
    && literal(answer.decision, ["choose", "abstain"]) && answer.ranking === "not_computed" && answer.performance_score === null
    && answer.performance_evidence === "not_established" && text(answer.notice) && Array.isArray(answer.selections)
    && strings(answer.not_selected_variant_ids) && Array.isArray(answer.uncertainty) && answer.uncertainty.length <= uncertaintyCodes.length
    && answer.uncertainty.every(item => exact(item, ["code", "text"]) && literal(item.code, uncertaintyCodes) && text(item.text)));
  const codes = answer.uncertainty.map(item => (item as ObjectValue).code);
  check(unique(codes) && fixedUncertainty.every(code => codes.includes(code)) && (answer.decision !== "abstain" || codes.includes("no_supported_selection")));
  const selected: string[] = [];
  for (const item of answer.selections) {
    check(exact(item, ["variant_id", "reasons"]) && id(item.variant_id) && Array.isArray(item.reasons) && item.reasons.length > 0);
    const candidate = value.preparation.candidates.find(candidate => candidate.variant_id === item.variant_id);
    check(candidate && item.reasons.every(itemReason => candidate.reasons.some(candidateReason => same(itemReason, candidateReason))));
    check(unique(item.reasons.map(itemReason => (itemReason as ObjectValue).id)));
    selected.push(item.variant_id);
  }
  const partition = [...selected, ...answer.not_selected_variant_ids];
  check(unique(partition) && partition.length === value.preparation.candidates.length && value.preparation.candidates.every(candidate => partition.includes(candidate.variant_id))
    && (answer.decision === "abstain" ? selected.length === 0 : selected.length > 0));
}

/** Shared transport only; these methods never retry or use generic analysis paths. */
export function createCandidateAiApi(send: Send) {
  return {
    prepareCandidateAI: async (payload: CandidateAiPrepareRequest, signal?: AbortSignal) => {
      assertPrepareRequest(payload);
      const result = await send<unknown>("/v1/ai/candidate-preparations", { method: "POST", body: JSON.stringify(payload), signal });
      assertCandidateAiPreparation(result);
      check(same(result.selection, payload.selection) && result.preference.revision === payload.expected_preference_revision
        && result.preference.fingerprint === payload.expected_preference_fingerprint
        && result.candidates.length === payload.variant_ids.length && result.candidates.every(item => payload.variant_ids.includes(item.variant_id)));
      return result;
    },
    authorizeCandidateAI: async (preparationId: string, payload: CandidateAiAuthorizationRequest, signal?: AbortSignal): Promise<CandidateAiAuthorization> => {
      check(id(preparationId)); assertAuthorizationRequest(payload);
      const result = await send<unknown>(`/v1/ai/candidate-preparations/${encodeURIComponent(preparationId)}/authorizations`, { method: "POST", body: JSON.stringify(payload), signal });
      check(exact(result, ["schema", "dependency_id", "provider", "purpose", "state", "revision_id", "revision", "expires_at", "rights_holder", "license_basis_url", "license_basis_note", "license_evidence_sha256", "recipient_fingerprint"])
        && result.schema === "candidate-ai-authorization@1" && result.purpose === purpose && result.dependency_id === payload.dependency_id
        && result.provider === payload.provider && (payload.action === "grant" ? result.state === "granted" || result.state === "expired" : result.state === "revoked")
        && id(result.revision_id) && integer(result.revision, 1) && result.revision === payload.expected_revision + 1 && timestamp(result.expires_at)
        && text(result.rights_holder) && basisUrl(result.license_basis_url) && text(result.license_basis_note) && hash(result.license_evidence_sha256)
        && (result.recipient_fingerprint === null ? payload.action === "revoke" : hash(result.recipient_fingerprint)));
      return result as unknown as CandidateAiAuthorization;
    },
    submitCandidateAI: async (payload: CandidateAiSubmitRequest, key: string, signal?: AbortSignal) => {
      check(exact(payload, ["preparation_id", "consent_hash", "allow_external_processing"]) && id(payload.preparation_id) && hash(payload.consent_hash) && payload.allow_external_processing === true && uuid(key));
      const result = await send<unknown>("/v1/ai/candidate-recommendations", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal });
      assertCandidateAiRecommendation(result);
      check(result.preparation.preparation_id === payload.preparation_id && result.preparation.consent_hash === payload.consent_hash);
      return result;
    },
    candidateAIRecommendation: async (recommendationId: string, signal?: AbortSignal) => {
      check(id(recommendationId));
      const result = await send<unknown>(`/v1/ai/candidate-recommendations/${encodeURIComponent(recommendationId)}?mode=history`, { signal });
      assertCandidateAiRecommendation(result); check(result.id === recommendationId); return result;
    },
    lookupCandidateAIRecommendation: async (key: string, signal?: AbortSignal) => {
      check(uuid(key));
      const result = await send<unknown>(`/v1/ai/candidate-recommendations?${new URLSearchParams({ mode: "history", key })}`, { signal });
      assertCandidateAiRecommendation(result); return result;
    },
  };
}
