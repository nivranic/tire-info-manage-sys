/** Synthetic contract cases, not live backend or device acceptance. */
import assert from "node:assert/strict";
import { apiKeyTime, ExternalApiContractError, setApiTransport, tireApi } from "@tire/api-client";
import type { ActiveApiKeys, ApiKeyHistory } from "@tire/domain-types";

const owner = "owner_safe-1", read = "2026-10-19T00:00:01.000001+00:00";
const record = { schema: "api-key@1", id: "a".repeat(32), name: "😀".repeat(80), scopes: ["sources:read"],
  created_at: "2026-10-19T00:00:00.000002+00:00", expires_at: "2026-11-19T00:00:00+00:00", revoked_at: null };
const active = { schema: "active-api-keys@1", items: [record], read_at: read };
const history = { schema: "api-key-history@1", items: [record], limit: 1, next_cursor: "opaque.signature", window_started_at: read, read_at: read };
let response: unknown = active, count = 0;
const calls: { path: string; init: RequestInit }[] = [], ok = () => count++;
const reset = setApiTransport(async (path, init) => { calls.push({ path, init }); return Response.json(response); });
try {
  const controller = new AbortController();
  const result: ActiveApiKeys = await tireApi.activeApiKeys(owner, controller.signal);
  assert.equal(result.items[0].name, record.name); assert.equal(calls.at(-1)!.path, "/v1/api-keys/active?mode=history"); ok();
  assert.equal(new Headers(calls.at(-1)!.init.headers).get("X-Tire-Expected-Account"), owner);
  assert.equal(new Headers(calls.at(-1)!.init.headers).get("Authorization"), null); assert.equal(calls.at(-1)!.init.credentials, "include");
  assert.equal(calls.at(-1)!.init.signal, controller.signal); ok();
  response = { ...active, items: [] }; assert.equal((await tireApi.activeApiKeys(owner)).items.length, 0); ok();
  // Expiry one microsecond after read remains active; ordering also keeps microseconds.
  response = { ...active, items: [{ ...record, expires_at: "2026-10-19T00:00:01.000002Z" }] };
  await tireApi.activeApiKeys(owner); ok();
  response = { ...active, items: [record, { ...record, id: "f".repeat(32), created_at: "2026-10-19T00:00:00.000001Z" }] };
  await tireApi.activeApiKeys(owner); ok();
  response = { ...active, items: [{ ...record, id: "b".repeat(32) }, record] }; await tireApi.activeApiKeys(owner); ok();
  for (const change of [
    (v: any) => { v.owner = owner; }, (v: any) => { v.items[0].token = "forbidden"; },
    (v: any) => { v.items[0].revoked_at = read; }, (v: any) => { v.items[0].expires_at = read; },
    (v: any) => { v.items.push(v.items[0]); }, (v: any) => { v.items[0].name = "😀".repeat(81); },
    (v: any) => { v.read_at = "2026-02-30T00:00:00Z"; }, (v: any) => { v.read_at = "2026-10-19T00:00:00+08:00"; },
    (v: any) => { v.items.push({ ...record, id: "f".repeat(32), created_at: "2026-10-19T00:00:00.000003Z" }); },
    (v: any) => { v.items.push({ ...record, id: "f".repeat(32) }); },
    (v: any) => { v.items = Array.from({ length: 17 }, (_, i) => ({ ...record, id: (17 - i).toString(16).padStart(32, "0") })); },
  ]) { response = structuredClone(active); change(response); await assert.rejects(tireApi.activeApiKeys(owner), ExternalApiContractError); ok(); }
  response = history;
  const page: ApiKeyHistory = await tireApi.apiKeyHistory(owner, { limit: 1, signal: controller.signal });
  assert.equal(page.next_cursor, history.next_cursor); assert.equal(calls.at(-1)!.path, "/v1/api-key-history?mode=history&limit=1"); ok();
  response = { ...history, items: [], next_cursor: null };
  await tireApi.apiKeyHistory(owner, { limit: 1, cursor: history.next_cursor });
  assert.equal(calls.at(-1)!.path, "/v1/api-key-history?mode=history&limit=1&cursor=opaque.signature"); ok();
  response = { ...history, items: [{ ...record, revoked_at: read }], next_cursor: null };
  await tireApi.apiKeyHistory(owner, { limit: 1 }); ok();
  response = { ...history, limit: 20, next_cursor: null }; await tireApi.apiKeyHistory(owner); ok();
  for (const change of [
    (v: any) => { v.total = 1; }, (v: any) => { v.schema = "api-keys@1"; }, (v: any) => { delete v.read_at; },
    (v: any) => { v.limit = 2; }, (v: any) => { v.items = []; }, (v: any) => { v.items.push(v.items[0]); },
    (v: any) => { v.read_at = "2026-10-19T00:00:01Z"; }, (v: any) => { v.next_cursor = "unsafe?"; },
    (v: any) => { v.next_cursor = "prior.signature"; }, (v: any) => { v.window_started_at = "2026-10-19T00:00:02Z"; },
  ]) { response = structuredClone(history); change(response); await assert.rejects(tireApi.apiKeyHistory(owner, { limit: 1, cursor: "prior.signature" }), ExternalApiContractError); ok(); }
  const before = calls.length;
  for (const invalid of ["", "x\n", "x ", "x/y", "中", "x".repeat(65)]) {
    await assert.rejects(tireApi.activeApiKeys(invalid), ExternalApiContractError); await assert.rejects(tireApi.apiKeyHistory(invalid), ExternalApiContractError); ok();
  }
  for (const request of [{ limit: 0 }, { limit: 101 }, { limit: 1.5 }, { cursor: "x" }, { cursor: "x.y\n" }, { cursor: "a".repeat(2048) + ".b" }, { owner }, null]) {
    await assert.rejects(tireApi.apiKeyHistory(owner, request as any), ExternalApiContractError); ok();
  }
  assert.equal(calls.length, before); ok();
  assert.equal(apiKeyTime("2026-10-19T00:00:00.000002Z") - apiKeyTime("2026-10-19T00:00:00.000001+00:00"), 1n); ok();
} finally { reset(); }
console.log(JSON.stringify({ schema: "api-key-inventory-sdk@1", passed: count, transport: "synthetic_injected_only", real_credentials: false }));
