import assert from "node:assert/strict";
import test from "node:test";
import { loadOfflineTypeScript } from "./load_offline_typescript.mjs";
const sdk = await loadOfflineTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const id = "00000000-0000-4000-8000-000000000049";
test("warehouse policy methods preserve fixed routes, exact bodies and mutation idempotency", async () => {
  const calls = [], restore = sdk.setApiTransport(async (path, init) => { calls.push({ path, body: JSON.parse(init.body || "null"), method: init.method || "GET", key: init.headers.get("Idempotency-Key") }); return new Response("{}"); });
  try {
    const preview = { mode: "ask", scope: { kind: "source", source_id: "fixture", access_generation: 0, query_kinds: ["tire"] }, expected_revision: 0 };
    const apply = { preview_id: id, expected_fingerprint: "a".repeat(64), expected_revision: 0, allow_continuous_history_fallback: true };
    await sdk.tireApi.previewQueryFallbackPolicy(preview); await sdk.tireApi.applyQueryFallbackPolicy(apply, "preview-key"); await sdk.tireApi.queryFallbackPolicies(20);
    await sdk.tireApi.pauseQueryFallbackPolicy(id, 2, "pause-key"); await sdk.tireApi.revokeQueryFallbackPolicy(id, 3, "revoke-key");
    assert.deepEqual(calls.map(call => call.path), ["/v1/query-fallback-policies:preview", "/v1/query-fallback-policies:apply", "/v1/query-fallback-policies?limit=16&offset=20", `/v1/query-fallback-policies/${id}:pause`, `/v1/query-fallback-policies/${id}:revoke`]);
    assert.deepEqual(calls.map(call => call.body), [preview, apply, null, { expected_revision: 2 }, { expected_revision: 3 }]);
    assert.deepEqual(calls.map(call => call.key), [null, "preview-key", null, "pause-key", "revoke-key"]);
  } finally { restore(); }
});
test("tire live query alone preserves exact criteria numeric tokens without changing generic JSON", async () => {
  const calls = [], restore = sdk.setApiTransport(async (path, init) => { calls.push({ path, body: init.body }); return new Response("{}"); });
  try {
    const filters = sdk.canonicalDeviceFilters(sdk.parseExactJson('[{"field":"utqg_treadwear","op":"gte","value":9007199254740993}]'));
    await sdk.tireApi.liveQuery("fixture", { query: { size: "205/55R20" }, filters, fallback_policy: "ask" });
    assert.match(calls[0].body, /"value":9007199254740993/); assert.doesNotMatch(calls[0].body, /"token"/);
    await sdk.tireApi.consent(id, "deny"); assert.equal(calls[1].body, JSON.stringify({ query_id: id, decision: "deny", scope: "once" }));
  } finally { restore(); }
});
test("custom native transports cannot publish browser denial observations", async () => {
  let captured = 0, published = 0;
  const stop = sdk.observeBrowserFallbackDenials(async () => { captured++; return async () => { published++; }; });
  const restore = sdk.setApiTransport(async () => new Response(JSON.stringify({ id, decision: "deny" }), { status: 201 }));
  try { await sdk.tireApi.consent(id, "deny"); assert.equal(captured, 0); assert.equal(published, 0); } finally { restore(); stop(); }
});
test("denial identity canonicalizes only accepted formal UUID keys", () => {
  const query = "abcdef12-abcd-4abc-8abc-abcdef123456";
  assert.equal(sdk.fallbackDenialQueryKey(query.toUpperCase()), query);
  assert.equal(sdk.fallbackDenialQueryKey("AbCdEf12-aBcD-4aBc-8aBc-aBcDeF123456"), query);
  for (const opaque of ["OpaqueQueryA", "opaquequerya", " " + query, query + " ", query.replaceAll("-", ""), "ABCDEF12-ABCD-4ABC-8ABC-ABCDEF12345Z"])
    assert.equal(sdk.fallbackDenialQueryKey(opaque), opaque);
});
test("owned Browser consent observes canonical identity while preserving original HTTP UUID text", async () => {
  const query = "abcdef12-abcd-4abc-8abc-abcdef123456", upper = query.toUpperCase(), priorFetch = globalThis.fetch;
  const captures = [], publications = [], calls = [];
  const stop = sdk.observeBrowserFallbackDenials(async (key, epoch) => { captures.push({ key, epoch }); return async () => { publications.push(key); }; });
  globalThis.fetch = async (path, init) => { calls.push({ path, body: init.body }); return new Response(JSON.stringify({ id, decision: "deny", scope: "once" }), { status: 201 }); };
  try {
    await sdk.tireApi.consent(upper, "deny"); await sdk.tireApi.consent(query, "deny");
    assert.deepEqual(captures.map(value => value.key), [query, query]); assert.deepEqual(publications, [query, query]);
    assert.ok(captures.every(value => value.epoch === sdk.apiTransportAuthorityEpoch()));
    assert.deepEqual(calls.map(call => call.path), ["/api/v1/fallback-consents", "/api/v1/fallback-consents"]);
    assert.deepEqual(calls.map(call => JSON.parse(call.body)), [{ query_id: upper, decision: "deny", scope: "once" }, { query_id: query, decision: "deny", scope: "once" }]);
  } finally { globalThis.fetch = priorFetch; stop(); }
});
