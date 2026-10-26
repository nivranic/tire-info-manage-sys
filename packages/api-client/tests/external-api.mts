/** Handwritten synthetic wire assertions; no real credentials, HTTP or database. */
import assert from "node:assert/strict";
import { createExternalApiClient, ExternalApiContractError, ExternalApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { ApiKeyCreate, ApiKeyOperation } from "@tire/domain-types";

const keyId = "a".repeat(32), bearer = `ti_${keyId}.${"b".repeat(64)}`, uuid = "4ce1c696-162e-4703-926f-86c852218dcc";
const record = { schema: "api-key@1", id: keyId, name: "合成 SDK", scopes: ["sources:read"], created_at: "2026-10-18T00:00:00+00:00", expires_at: "2026-11-17T00:00:00+00:00", revoked_at: null };
const operation = { schema: "api-key-operation@1", idempotency_key: uuid, action: "create", key: record, token: bearer, replayed: false };
const payload: ApiKeyCreate = { name: record.name, scopes: ["sources:read"], expires_in_days: 30, acknowledged: true };
let response: unknown = operation, count = 0;
const calls: { path: string; init: RequestInit }[] = [];
const ok = () => count++;
const reset = setApiTransport(async (path, init) => { calls.push({ path, init }); return Response.json(response); });
try {
  const result: ApiKeyOperation = await tireApi.createApiKey(payload, uuid); assert.equal(result.token, bearer); assert.equal(calls.at(-1)!.path, "/v1/api-keys"); ok();
  assert.equal(new Headers(calls.at(-1)!.init.headers).get("Idempotency-Key"), uuid); assert.equal(new Headers(calls.at(-1)!.init.headers).get("Authorization"), null); ok();
  response = { schema: "api-keys@1", items: [record] }; assert.equal((await tireApi.apiKeys()).items.length, 1); ok();
  response = { ...operation, token: null, replayed: true }; assert.equal((await tireApi.apiKeyOperation(uuid)).token, null); assert.equal(calls.at(-1)!.init.method, undefined); ok();
  assert.equal((await tireApi.createApiKey(payload, uuid)).replayed, true); ok();
  const scopeCases: ApiKeyCreate["scopes"][] = [["facts:read"], ["facts:read", "sources:read", "webhooks:read"], ["sources:read", "webhooks:read"]];
  for (const scopes of scopeCases) {
    const scopedRecord = { ...record, scopes }, scopedPayload: ApiKeyCreate = { ...payload, scopes };
    response = { ...operation, key: scopedRecord };
    const created = await tireApi.createApiKey(scopedPayload, uuid);
    assert.deepEqual(created.key.scopes, scopes); assert.equal(created.token, bearer);
    assert.deepEqual(JSON.parse(calls.at(-1)!.init.body as string).scopes, scopes); ok();
    response = { schema: "api-keys@1", items: [scopedRecord] };
    assert.deepEqual((await tireApi.apiKeys()).items[0].scopes, scopes); ok();
    response = { ...operation, key: scopedRecord, token: null, replayed: true };
    const recovered = await tireApi.apiKeyOperation(uuid);
    assert.deepEqual(recovered.key.scopes, scopes); assert.equal(recovered.token, null); assert.equal(recovered.replayed, true); ok();
    const replayed = await tireApi.createApiKey(scopedPayload, uuid);
    assert.deepEqual(replayed.key.scopes, scopes); assert.equal(replayed.token, null); assert.equal(replayed.replayed, true); ok();
  }
  response = { ...operation, key: { ...record, name: "😀".repeat(80) } }; assert.equal((await tireApi.createApiKey({ ...payload, name: "😀".repeat(80) }, uuid)).key.name, "😀".repeat(80)); ok();
  response = { ...operation, action: "revoke", token: null, key: { ...record, revoked_at: "2026-10-18T01:00:00Z" } }; assert.equal((await tireApi.revokeApiKey(keyId, uuid)).action, "revoke"); ok();
  for (const change of [
    (v: any) => { v.key.owner_user_id = "foreign"; }, (v: any) => { v.key.secret_hash = "hidden"; },
    (v: any) => { v.key.scopes = ["sources:read", "sources:read"]; }, (v: any) => { v.key.scopes = ["admin:write"]; },
    (v: any) => { v.key.id = "foreign"; }, (v: any) => { v.key.expires_at = v.key.created_at; },
    (v: any) => { v.replayed = true; }, (v: any) => { v.token = null; }, (v: any) => { v.action = "revoke"; },
    (v: any) => { v.token = bearer + "\n"; }, (v: any) => { v.idempotency_key = "00000000-0000-0000-0000-000000000000"; },
  ]) { response = structuredClone(operation); change(response); await assert.rejects(tireApi.createApiKey(payload, uuid), ExternalApiContractError); ok(); }
  const before = calls.length;
  await assert.rejects(tireApi.createApiKey({ ...payload, acknowledged: false } as any, uuid), ExternalApiContractError); ok();
  await assert.rejects(tireApi.revokeApiKey("../other", uuid), ExternalApiContractError); ok();
  await assert.rejects(tireApi.createApiKey({ ...payload, expires_in_days: 91 }, uuid), ExternalApiContractError); ok();
  for (const scopes of [["facts:read", "unknown:read"], ["facts:read", "facts:read"], ["sources:read", "facts:read", "webhooks:read"], ["facts:read", "sources:read", "webhooks:read", "webhooks:read"]]) {
    const beforeScopeRequest = calls.length;
    await assert.rejects(tireApi.createApiKey({ ...payload, scopes } as any, uuid), ExternalApiContractError);
    assert.equal(calls.length, beforeScopeRequest); ok();
  }
  assert.equal(calls.length, before); ok();
} finally { reset(); }

let page: unknown = { schema: "external-sources@1", items: [{ id: "fixture", name: "合成来源", source_class: "manufacturer_official", region: "CN", parser_version: "fixture@1", status: "ready" }], next_cursor: null, limit: 20, data_state: "local_snapshot" };
let mode = "ok";
const reads: { path: string; init: RequestInit }[] = [];
const api = createExternalApiClient(bearer, async (path, init) => {
  reads.push({ path, init });
  if (mode === "network") throw new Error(`sensitive ${bearer}`);
  if (mode === "401") return Response.json({ detail: { message: bearer } }, { status: 401 });
  if (mode === "redirect") return new Response(null, { status: 302, headers: { location: "https://foreign.invalid" } });
  if (mode === "oversize") return new Response("x".repeat(1024 * 1024 + 1), { headers: { "content-type": "application/json" } });
  return Response.json(page);
});
await api.sources(); ok();
assert.equal(reads.at(-1)!.path, "/external/v1/sources?limit=20"); assert.equal(reads.at(-1)!.init.credentials, "omit"); assert.equal(reads.at(-1)!.init.redirect, "error"); assert.equal(reads.at(-1)!.init.cache, "no-store"); ok();
assert.deepEqual(reads.at(-1)!.init.headers, { Authorization: `Bearer ${bearer}`, Accept: "application/json" }); ok();
page = { schema: "external-sources@1", items: [{ id: "x".repeat(80), name: null, source_class: null, region: null, parser_version: null, status: null }], next_cursor: null, limit: 20, data_state: "local_snapshot" };
assert.equal((await api.sources()).items[0].id.length, 80); ok();
page = { schema: "external-sources@1", items: [{ id: "fixture", name: "😀".repeat(500), source_class: null, region: null, parser_version: null, status: null }], next_cursor: null, limit: 20, data_state: "local_snapshot" };
assert.equal((await api.sources()).items[0].name, "😀".repeat(500)); ok();
for (const change of [
  (v: any) => { v.items[0].url = "https://source.invalid"; }, (v: any) => { v.data_state = "live"; },
  (v: any) => { v.next_cursor = "incomplete"; }, (v: any) => { v.limit = 21; }, (v: any) => { v.items.push(v.items[0]); },
  (v: any) => { v.items[0].source_class = 42; }, (v: any) => { v.secret = bearer; },
]) { page = { schema: "external-sources@1", items: [{ id: "fixture", name: null, source_class: null, region: null, parser_version: null, status: null }], next_cursor: null, limit: 20, data_state: "local_snapshot" }; change(page); await assert.rejects(api.sources(), ExternalApiContractError); ok(); }
const before = reads.length;
await assert.rejects(api.sources({ limit: 101 }), ExternalApiContractError); ok();
await assert.rejects(api.sources({ cursor: "?secret=bad" }), ExternalApiContractError); ok();
await assert.rejects(api.deliveries({ webhook_id: "../foreign" }), ExternalApiContractError); ok();
assert.equal(reads.length, before); ok();
for (mode of ["401", "network", "redirect"]) { await assert.rejects(api.sources(), (e: unknown) => e instanceof ExternalApiError && !e.message.includes(bearer)); ok(); }
mode = "oversize"; await assert.rejects(api.sources(), ExternalApiContractError); ok();
assert.throws(() => createExternalApiClient(bearer + "\r\nX-Evil: 1", async () => Response.json({})), ExternalApiContractError); ok();
console.log(JSON.stringify({ schema: "external-api-sdk-tests@1", passed: count, transport: "synthetic_injected_only", real_credentials: false }));
