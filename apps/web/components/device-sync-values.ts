import type { DeviceSyncCapabilities, DeviceSyncConditions, DeviceSyncPolicy, DeviceSyncPreviewRequest, OfflineCapacity,
  AnyOfflineEnvelope as OfflineEnvelope, AnyOfflinePackDescriptor as OfflinePackDescriptor, OfflinePackUpdate, OfflinePackUpdateV2, OfflineSlot } from "@tire/domain-types";
import { parseExactJson } from "@tire/api-client";
import { MAX_OFFLINE_BYTES, OfflineError, offlineSha256, parseOfflineJson } from "./offline-crypto";
import { validateOfflineDescriptor } from "./offline-values";

export const DEVICE_SYNC_CAPACITY: OfflineCapacity = { version: "offline-policy@1", max_package_bytes: MAX_OFFLINE_BYTES,
  max_distinct_evidence: 200, max_garage_profiles: 50, max_watch_items: 100, max_recent_query_candidates: 20,
  max_searchable_documents: 4000, plan_ttl_seconds: 600, raw_policy: "exclude" };
export const DEVICE_SYNC_NOTICE = "独立持续许可仅重新打包已有历史，不查询官网、不调用 AI，也不重新核验来源。全部车库、全部关注和最近 N 次正式查询是动态范围，未来新增或移除项会改变包；固定 ID 使用该对象届时的历史版本；显式证据固定已保存的核验回执。容量超限会停止更新，保留旧包。许可持续到暂停或撤销。Web 仅在页面运行时尽力调度，页面关闭后不执行；Wi-Fi、电源与充电条件在 Web 不支持。";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const digest = /^[0-9a-f]{64}$/;
export const validSyncUUID = (value: unknown): value is string => typeof value === "string" && uuid.test(value);
export const validSyncDigest = (value: unknown): value is string => typeof value === "string" && digest.test(value);
const fail = (code = "OFFLINE_SYNC_INVALID"): never => { throw new OfflineError(code); };
export function stableSyncJson(value: unknown): string {
  const order = (a: string, b: string) => {
    const x = Array.from(a), y = Array.from(b);
    for (let i = 0; i < Math.min(x.length, y.length); i++) { const difference = x[i].codePointAt(0)! - y[i].codePointAt(0)!; if (difference) return difference; }
    return x.length - y.length;
  };
  const sorted = (value: unknown): unknown => Array.isArray(value) ? value.map(sorted) : value && typeof value === "object"
    ? Object.fromEntries(Object.keys(value).sort(order).map(key => [key, sorted((value as Record<string, unknown>)[key])])) : value;
  return JSON.stringify(sorted(value));
}
export async function deviceSyncSemanticDigest(envelope: OfflineEnvelope): Promise<string> {
  const content = { ...envelope } as Partial<OfflineEnvelope>;
  for (const key of ["package_id", "created_at", "plan_fingerprint", "base_pack_id"] as const) delete content[key];
  return offlineSha256(new TextEncoder().encode(stableSyncJson({ namespace: "offline-semantic@1", envelope: content })));
}
/** Preserve producer numeric tokens (including 1.0); never re-encode package numbers. */
export async function deviceSyncSemanticDigestFromBytes(bytes: Uint8Array): Promise<string> {
  parseExactJson(bytes);
  const input = new TextDecoder("utf-8", { fatal: true }).decode(bytes); let position = 0;
  type Node = { kind: "scalar"; raw: string } | { kind: "object"; entries: [string, Node][] } | { kind: "array"; values: Node[] };
  const skip = () => { while (/[\t\n\r ]/.test(input[position] || "x")) position++; };
  const readString = () => {
    const start = position++; let escaped = false;
    while (position < input.length) { const char = input[position++]; if (!escaped && char === '"') return JSON.parse(input.slice(start, position)) as string; escaped = !escaped && char === "\\"; }
    return fail("OFFLINE_SYNC_RESPONSE_INVALID");
  };
  const parse = (): Node => {
    skip(); const char = input[position];
    if (char === "{") {
      position++; skip(); const entries: [string, Node][] = [];
      if (input[position] === "}") { position++; return { kind: "object", entries }; }
      while (position < input.length) { skip(); const key = readString(); skip(); position++; const node = parse(); entries.push([key, node]); skip(); if (input[position++] === "}") break; }
      return { kind: "object", entries };
    }
    if (char === "[") {
      position++; skip(); const values: Node[] = [];
      if (input[position] === "]") { position++; return { kind: "array", values }; }
      while (position < input.length) { values.push(parse()); skip(); if (input[position++] === "]") break; }
      return { kind: "array", values };
    }
    if (char === '"') return { kind: "scalar", raw: JSON.stringify(readString()) };
    const match = /^(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/.exec(input.slice(position));
    if (!match) return fail("OFFLINE_SYNC_RESPONSE_INVALID"); position += match[0].length; return { kind: "scalar", raw: match[0] };
  };
  const order = (a: string, b: string) => { const x = Array.from(a), y = Array.from(b); for (let i = 0; i < Math.min(x.length, y.length); i++) { const d = x[i].codePointAt(0)! - y[i].codePointAt(0)!; if (d) return d; } return x.length - y.length; };
  const canonical = (node: Node): string => node.kind === "scalar" ? node.raw : node.kind === "array" ? `[${node.values.map(canonical).join(",")}]`
    : `{${node.entries.sort(([a], [b]) => order(a, b)).map(([key, value]) => `${JSON.stringify(key)}:${canonical(value)}`).join(",")}}`;
  const root = parse(); skip(); if (position !== input.length || root.kind !== "object") fail("OFFLINE_SYNC_RESPONSE_INVALID");
  if (root.kind !== "object") return fail("OFFLINE_SYNC_RESPONSE_INVALID");
  root.entries = root.entries.filter(([key]) => !["package_id", "created_at", "plan_fingerprint", "base_pack_id"].includes(key));
  return offlineSha256(new TextEncoder().encode(`{"envelope":${canonical(root)},"namespace":"offline-semantic@1"}`));
}
export function deriveDeviceSyncScope(envelope: OfflineEnvelope) {
  const scope: import("@tire/domain-types").OfflineScopeV2 = structuredClone(envelope.scope);
  // Members retain distinct resolved receipt keys even when the original selector
  // omitted verification_id or selected the same snapshot more than once.
  const members = envelope.members.filter(member => member.member_reasons.some(reason => reason.selector === "explicit")), keys = new Set<string>();
  scope.references = [];
  for (const original of envelope.scope.references) for (const member of members) {
    const ref = member.reference;
    if (keys.has(member.key) || ref.kind !== original.kind || Object.entries(original).some(([key, value]) => (ref as unknown as Record<string, unknown>)[key] !== value)) continue;
    keys.add(member.key); scope.references.push(structuredClone(ref));
  }
  if (keys.size !== members.length) fail("OFFLINE_SYNC_INVALID");
  return scope;
}
export function validateSyncConditions(conditions: DeviceSyncConditions): void {
  if (!conditions || Object.keys(conditions).sort().join(",") !== "network,power" || !["any", "wifi"].includes(conditions.network)
    || !["any", "external_power", "battery_charging"].includes(conditions.power)) fail();
}
export function validateSyncPreviewRequest(request: DeviceSyncPreviewRequest, capabilities: DeviceSyncCapabilities): void {
  if (!request || Object.keys(request).sort().join(",") !== "conditions,expected_generation,expected_owner_epoch,expected_profile_id,interval_seconds,slot_id"
    || !validSyncUUID(request.slot_id) || !validSyncUUID(request.expected_profile_id) || !Number.isSafeInteger(request.expected_generation) || request.expected_generation < 1
    || !Number.isSafeInteger(request.expected_owner_epoch) || request.expected_owner_epoch < 1 || !Number.isSafeInteger(request.interval_seconds)
    || request.interval_seconds < capabilities.min_interval_seconds || request.interval_seconds > capabilities.max_interval_seconds) fail();
  validateSyncConditions(request.conditions);
  if (capabilities.scheduler === "unsupported" || request.conditions.network === "wifi" && !capabilities.wifi
    || request.conditions.power !== "any" && !capabilities[request.conditions.power]) fail("OFFLINE_SYNC_UNSUPPORTED");
}
export interface DeviceSyncObservations { network_available: boolean | null; wifi: boolean | null; external_power: boolean | null; battery_charging: boolean | null }
export function syncConditionsSatisfied(conditions: DeviceSyncConditions, capabilities: DeviceSyncCapabilities, observations: DeviceSyncObservations): boolean {
  validateSyncConditions(conditions);
  return capabilities.scheduler !== "unsupported" && observations.network_available === true
    && (conditions.network === "any" || capabilities.wifi && observations.wifi === true)
    && (conditions.power === "any" || capabilities[conditions.power] && observations[conditions.power] === true);
}
export function sameSyncValue(a: unknown, b: unknown) { return stableSyncJson(a) === stableSyncJson(b); }
export function validateSyncUpdate(value: unknown, policy: DeviceSyncPolicy, slot: OfflineSlot, descriptor: OfflinePackDescriptor): OfflinePackUpdate | OfflinePackUpdateV2 {
  const response = value as OfflinePackUpdate | OfflinePackUpdateV2;
  if (!response || Object.keys(response).sort().join(",") !== "base_pack,base_pack_id,base_semantic_digest,current_semantic_digest,mode,plan,schema,source_refresh_performed,state"
    || response.schema !== (descriptor.schema === "offline-pack-descriptor@2" ? "offline-pack-update@2" : "offline-pack-update@1") || !["no_change", "planned"].includes(response.state) || response.mode !== "history"
    || response.source_refresh_performed !== false || response.base_pack_id !== slot.package_id
    || !validSyncDigest(response.base_semantic_digest) || !validSyncDigest(response.current_semantic_digest)) fail("OFFLINE_SYNC_RESPONSE_INVALID");
  const base = validateOfflineDescriptor(response.base_pack);
  if (!sameSyncValue(base, descriptor) || base.id !== policy.binding.package_id || base.sha256 !== policy.binding.sha256
    || base.byte_count !== slot.byte_count || base.owner_scope_id !== policy.owner_scope_id) fail("OFFLINE_SYNC_RESPONSE_INVALID");
  if (response.state === "no_change") {
    if (response.plan !== null || response.base_semantic_digest !== response.current_semantic_digest) fail("OFFLINE_SYNC_RESPONSE_INVALID");
    return response;
  }
  const plan = response.plan;
  if (!plan) throw new OfflineError("OFFLINE_SYNC_RESPONSE_INVALID");
  if (plan.schema !== (descriptor.schema === "offline-pack-descriptor@2" ? "offline-pack-plan@2" : "offline-pack-plan@1") || !validSyncUUID(plan.id) || !validSyncUUID(plan.package_id)
    || !validSyncDigest(plan.fingerprint) || !validSyncDigest(plan.content_sha256) || plan.owner_scope_id !== policy.owner_scope_id
    || plan.base_pack_id !== slot.package_id || !sameSyncValue(plan.requested_scope, policy.scope)
    || !sameSyncValue(plan.capacity, policy.capacity) || plan.state !== "ready" || plan.can_confirm !== true
    || !Number.isSafeInteger(plan.measured_bytes) || plan.measured_bytes < 1 || plan.measured_bytes > policy.capacity.max_package_bytes
    || !Number.isFinite(Date.parse(plan.expires_at)) || Date.parse(plan.expires_at) <= Date.now()
    || response.base_semantic_digest === response.current_semantic_digest || !Array.isArray(plan.resolved) || !Array.isArray(plan.contexts)
    || !Array.isArray(plan.documents) || !Array.isArray(plan.omissions) || plan.omissions.some(value => value.blocking)) fail("OFFLINE_SYNC_RESPONSE_INVALID");
  const ceilings: [keyof typeof plan.counts, keyof OfflineCapacity][] = [["garage_profiles", "max_garage_profiles"], ["watch_items", "max_watch_items"],
    ["recent_queries", "max_recent_query_candidates"], ["distinct_evidence", "max_distinct_evidence"], ["searchable_documents", "max_searchable_documents"]];
  for (const [count, ceiling] of ceilings) if (!Number.isSafeInteger(plan.counts?.[count]) || plan.counts[count] < 0 || plan.counts[count] > Number(policy.capacity[ceiling])) fail("OFFLINE_SYNC_CAPACITY");
  if (plan.resolved.length !== plan.counts.distinct_evidence || plan.contexts.filter(value => value.kind === "garage").length !== plan.counts.garage_profiles
    || plan.contexts.filter(value => value.kind === "watchlist").length !== plan.counts.watch_items || plan.documents.length !== plan.counts.searchable_documents) fail("OFFLINE_SYNC_RESPONSE_INVALID");
  return response;
}
