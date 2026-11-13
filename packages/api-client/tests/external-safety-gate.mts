/** Synthetic wire contracts; never reads credentials or contacts a real server. */
import assert from "node:assert/strict";
import test from "node:test";
import { assertApiKey, assertExternalSafetyGatePage, createExternalApiClient, ExternalApiContractError } from "@tire/api-client";
import type { ExternalSafetyGateRequest } from "@tire/domain-types";

const keyId = "a".repeat(32), bearer = `ti_${keyId}.${"b".repeat(64)}`;
const BASE = "https://ec.europa.eu/safety-gate-alerts";
const request: ExternalSafetyGateRequest = { report_id: "900001", query_id: "synthetic-query", mode: "history", limit: 1 };
function canonical(v: any): any { return v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])])) : v; }
function cursor(after: number, changes: Record<string, unknown> = {}) {
  const value = { schema: "external-cursor@1", key_id: keyId, owner: "c".repeat(64), route: "safety-gate-report-alerts", limit: 1,
    filters: { report_id: request.report_id, query_id: request.query_id, mode: "history" }, expires: 1800000900,
    context: { window: "d".repeat(64), count: 3 }, after, ...changes };
  return Buffer.from(JSON.stringify(canonical(value))).toString("base64url") + "." + Buffer.alloc(32).toString("base64url");
}
function page(index = 1): any {
  return { schema: "external-safety-gate-alert-page@1", data_state: "local_snapshot", source_refresh_performed: false,
    query_id: request.query_id, report: { report_id: request.report_id, reference: "Report-2026-19", published_date: "2026-05-15" },
    observation: { source_id: "eu-safety-gate", snapshot_id: "synthetic-snapshot", raw_hash: "e".repeat(64), parser_version: "synthetic@1",
      source_url: `${BASE}/api/download/weeklyReport/detail/xml/900001?language=en&search=WEB_REPORT%7C:%7C900001,`,
      observed_at: "2026-11-13T00:00:00.000001+00:00", verified_at: "2026-11-13T00:00:00.000002+00:00" },
    items: [{ alert_id: String(900000 + index), case_number: `SR/0000${index}/26`, published_date: "2026-05-12",
      source_url: `${BASE}/screen/webReport/alertDetail/${900000 + index}`, applicability: "not_assessed", facts: { brand: "Synthetic", barcode: null } }],
    limit: 1, next_cursor: index < 3 ? cursor(index) : null };
}

test("three pages use isolated trusted transport and a fixed cursor window", async () => {
  const calls: { path: string; init: RequestInit }[] = [];
  const api = createExternalApiClient(bearer, async (path, init) => { calls.push({ path, init }); return Response.json(page(calls.length)); });
  const first = await api.safetyGateAlerts(request);
  const second = await api.safetyGateAlerts({ ...request, cursor: first.next_cursor! });
  const third = await api.safetyGateAlerts({ ...request, cursor: second.next_cursor! });
  assert.equal(third.next_cursor, null);
  assert.deepEqual([first, second, third].map(p => p.items[0].alert_id), ["900001", "900002", "900003"]);
  assert.match(calls[0].path, /^\/external\/v1\/safety-gate-reports\/900001\/alerts\?/);
  for (const { init } of calls) {
    assert.equal(init.method, "GET"); assert.equal(init.credentials, "omit"); assert.equal(init.cache, "no-store");
    assert.equal(init.redirect, "error"); assert.equal(init.referrerPolicy, "no-referrer");
    assert.equal(new Headers(init.headers).get("Authorization"), `Bearer ${bearer}`);
  }
});

test("four recognized scopes remain valid", () => {
  assert.doesNotThrow(() => assertApiKey({ schema: "api-key@1", id: keyId, name: "Synthetic",
    scopes: ["facts:read", "safety-gate:read", "sources:read", "webhooks:read"],
    created_at: "2026-11-13T00:00:00Z", expires_at: "2026-11-14T00:00:00Z", revoked_at: null }));
});

test("invalid parameters fail before transport", async () => {
  let calls = 0; const api = createExternalApiClient(bearer, async () => { calls++; return Response.json(page()); });
  for (const patch of [{ mode: "live" }, { mode: undefined }, { report_id: "../1" }, { report_id: "0" }, { query_id: "q\n" },
    { limit: 21 }, { limit: 0 }, { limit: null }, { unknown: 1 }, { cursor: "bad" },
    { cursor: cursor(1, { key_id: "f".repeat(32) }) }, { cursor: cursor(1, { limit: 2 }) },
    { cursor: cursor(1, { filters: { report_id: "900002", query_id: request.query_id, mode: "history" } }) }]) {
    await assert.rejects(api.safetyGateAlerts({ ...request, ...patch } as any), ExternalApiContractError);
  }
  let getterCalls = 0;
  await assert.rejects(api.safetyGateAlerts({ ...request, get mode() { getterCalls++; return "history" as const; } }), ExternalApiContractError);
  assert.equal(calls, 0); assert.equal(getterCalls, 0);
});

test("closed evidence and field projection reject corrupt or overbroad responses", () => {
  const changes = [
    (v: any) => { v.xml = "private"; }, (v: any) => { v.observation.owner = "private"; },
    (v: any) => { v.items[0].facts.unlicensed = "private"; }, (v: any) => { v.source_refresh_performed = true; },
    (v: any) => { v.data_state = "live"; }, (v: any) => { v.observation.raw_hash = "bad"; },
    (v: any) => { v.observation.verified_at = "2026-11-13T00:00:00Z"; },
    (v: any) => { v.report.published_date = "2026-02-30"; }, (v: any) => { v.report.reference = "Report-2026-99"; },
    (v: any) => { v.items[0].source_url += "?token=synthetic"; }, (v: any) => { v.items[0].alert_id = "0"; },
    (v: any) => { v.items[0].facts.brand = "x".repeat(60001); }, (v: any) => { v.items[0].facts.brand = "\ud800"; },
    (v: any) => { v.items[0].applicability = "safe"; }, (v: any) => { v.next_cursor = cursor(1, { owner: "raw-owner" }); },
    (v: any) => { v.next_cursor = cursor(1, { context: { window: "d".repeat(64), count: 1001 } }); },
  ];
  for (const change of changes) { const value = page(); change(value); assert.throws(() => assertExternalSafetyGatePage(value), ExternalApiContractError); }
  const duplicate = page(); duplicate.limit = 2; duplicate.next_cursor = null; duplicate.items.push(structuredClone(duplicate.items[0]));
  assert.throws(() => assertExternalSafetyGatePage(duplicate), ExternalApiContractError);
});

test("request mutation during transport cannot change response binding", async () => {
  const mutable = { ...request };
  const api = createExternalApiClient(bearer, async () => { mutable.report_id = "999999"; mutable.query_id = "other"; return Response.json(page()); });
  assert.equal((await api.safetyGateAlerts(mutable)).report.report_id, "900001");
});

test("response must match requested query and continuation window", async () => {
  for (const change of [
    (v: any) => { v.query_id = "other"; v.next_cursor = null; },
    (v: any) => { v.next_cursor = cursor(2, { expires: 1800000901 }); },
    (v: any) => { v.next_cursor = cursor(2, { context: { window: "f".repeat(64), count: 3 } }); },
    (v: any) => { v.next_cursor = cursor(1); },
    (v: any) => { v.items = []; v.next_cursor = null; },
  ]) {
    const v = page(2); change(v);
    const api = createExternalApiClient(bearer, async () => Response.json(v));
    await assert.rejects(api.safetyGateAlerts({ ...request, cursor: cursor(1) }), ExternalApiContractError);
  }
});

test("malformed UTF-8, excessive responses and redirects fail closed", async () => {
  for (const response of [new Response(new Uint8Array([255]), { headers: { "Content-Type": "application/json" } }),
    new Response(" ".repeat(2*1024*1024+1), { headers: { "Content-Type": "application/json" } })]) {
    const api = createExternalApiClient(bearer, async () => response);
    await assert.rejects(api.safetyGateAlerts(request), ExternalApiContractError);
  }
  const redirected = Response.json(page()); Object.defineProperty(redirected, "redirected", { value: true });
  await assert.rejects(createExternalApiClient(bearer, async () => redirected).safetyGateAlerts(request), ExternalApiContractError);
});

test("abort wins over uncooperative transport and stream cancellation", async () => {
  const controller = new AbortController();
  const api = createExternalApiClient(bearer, async () => new Promise<Response>(() => {}));
  const pending = api.safetyGateAlerts({ ...request, signal: controller.signal }); controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  const streamController = new AbortController();
  const stream = new ReadableStream({ pull() { return new Promise<void>(() => {}); }, cancel() { return new Promise<void>(() => {}); } });
  const streaming = createExternalApiClient(bearer, async () => new Response(stream, { headers: { "Content-Type": "application/json" } }));
  const read = streaming.safetyGateAlerts({ ...request, signal: streamController.signal });
  setTimeout(() => streamController.abort(), 0); await assert.rejects(read, { name: "AbortError" });
});
