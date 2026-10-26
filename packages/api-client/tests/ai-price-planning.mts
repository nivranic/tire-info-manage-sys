/** Injected transport contract only: no API, database, provider or browser. */
import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { AIPricePlanningItem, AIPricePlanningRequest, AIPricePlanningResult,
  AIPriceVersion, AIPriceVersionCreate } from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type CreateKeys = Assert<Equal<keyof AIPriceVersionCreate,
  "vendor_label" | "provider" | "model" | "currency" | "input_per_million" | "output_per_million" | "source_note" | "source_url" | "effective_from" | "effective_until">>;
type VersionKeys = Assert<Equal<keyof AIPriceVersion, keyof AIPriceVersionCreate | "id" | "recorded_at" | "actor_user_id">>;
type ItemKeys = Assert<Equal<keyof AIPricePlanningItem,
  "price_version_id" | "request_count" | "input_tokens_per_request" | "output_tokens_per_request">>;
type DecimalPrice = Assert<Equal<AIPriceVersionCreate["input_per_million"], string>>;
type DecimalAmount = Assert<Equal<AIPricePlanningResult["items"][number]["exact_total"], string>>;
// @ts-expect-error Session cookies are never public audit data.
const privateSession: keyof AIPriceVersion = "actor_session_id";
// @ts-expect-error Actor attribution is supplied by the authenticated server.
const actorOverride: keyof AIPriceVersionCreate = "actor_user_id";

const key = "971986a7-8d8c-42f8-9664-a2261d30f22a";
const payload: AIPriceVersionCreate = { vendor_label: "Synthetic manual vendor", provider: "openai_responses",
  model: "Case-Sensitive:model", currency: "USD", input_per_million: "999999999.12345678", output_per_million: "0.00000001",
  source_note: "Synthetic manual entry; not an official verified price", source_url: "https://fixture.invalid/pricing?q=synthetic",
  effective_from: "2000-01-01T00:00:00.123456Z", effective_until: "2099-01-01T00:00:00Z" };
const version: AIPriceVersion = { ...payload, id: key, recorded_at: "2026-10-22T00:00:00Z", actor_user_id: "synthetic-admin" };
const planning: AIPricePlanningRequest = { planned_for: "2050-01-01T00:00:00.000001Z", items: [{
  price_version_id: version.id, request_count: 1000000, input_tokens_per_request: 100000000, output_tokens_per_request: 0 }] };
type Call = { path: string; init: RequestInit };
async function injected<T>(response: unknown, work: (calls: Call[]) => Promise<T>, status = 200): Promise<T> {
  const calls: Call[] = [];
  const restore = setApiTransport(async (path, init) => {
    calls.push({ path, init });
    if (init.signal?.aborted) throw new DOMException("Synthetic abort", "AbortError");
    return new Response(JSON.stringify(response), { status });
  });
  try { return await work(calls); } finally { restore(); }
}
function checkCall(call: Call, method: string, path: string, signal?: AbortSignal) {
  assert.equal(call.path, path); assert.equal(call.init.method || "GET", method);
  assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store"); assert.equal(call.init.signal, signal);
}

test("version pages preserve bounded pagination and caller AbortSignal", async () => {
  const abort = new AbortController();
  const page = { items: [version], offset: 130, limit: 25, has_more: true, next_offset: 155 };
  await injected(page, async calls => {
    assert.deepEqual(await tireApi.aiPriceVersions(abort.signal, 130, 25), page);
    await tireApi.aiPriceVersions();
    checkCall(calls[0], "GET", "/v1/ai/price-versions?offset=130&limit=25", abort.signal);
    checkCall(calls[1], "GET", "/v1/ai/price-versions?offset=0&limit=10");
  });
});

test("create retains exact decimal/date strings and caller UUID across explicit retries", async () => {
  const abort = new AbortController();
  await injected(version, async calls => {
    assert.deepEqual(await tireApi.aiPriceVersionCreate(payload, key, abort.signal), version);
    await tireApi.aiPriceVersionCreate(payload, key, abort.signal);
    for (const call of calls) {
      checkCall(call, "POST", "/v1/ai/price-versions", abort.signal);
      assert.equal(new Headers(call.init.headers).get("Idempotency-Key"), key);
      assert.deepEqual(JSON.parse(String(call.init.body)), payload);
      assert.equal(JSON.parse(String(call.init.body)).input_per_million, "999999999.12345678");
    }
    assert.equal(calls.length, 2);
  });
});

test("planning preserves exact amounts and snapshots without an idempotency header or grand total", async () => {
  const result: AIPricePlanningResult = { planned_for: planning.planned_for, calculated_at: "2026-10-22T00:00:00Z",
    calculation_version: "standard-text-v1", scale: 6, rounding: "ROUND_HALF_UP", items: [{ item_index: 0,
      price_version: version, request_count: planning.items[0].request_count,
      input_tokens_per_request: planning.items[0].input_tokens_per_request, output_tokens_per_request: planning.items[0].output_tokens_per_request,
      exact_input_total: "99999999912345678", exact_output_total: "0",
      exact_total: "99999999912345678", rounded_total: "99999999912345678.000000",
      formula: "request_count * (input_tokens_per_request * input_per_million + output_tokens_per_request * output_per_million) / 1000000" }],
    exclusions: ["cached_input", "tools", "long_context", "images_audio_video", "tax", "fx", "supplier_adjustments"], notice: "Synthetic planning only" };
  const abort = new AbortController();
  await injected(result, async calls => {
    assert.deepEqual(await tireApi.aiPricePlanning(planning, abort.signal), result);
    checkCall(calls[0], "POST", "/v1/ai/price-planning", abort.signal);
    assert.equal(new Headers(calls[0].init.headers).has("Idempotency-Key"), false);
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), planning);
  });
  const tiny = { ...result, items: [{ ...result.items[0], exact_total: "0.00000000000001", rounded_total: "0.000000" }] };
  await injected(tiny, async () => {
    const value = await tireApi.aiPricePlanning(planning);
    assert.equal(value.items[0].exact_total, "0.00000000000001"); assert.equal(value.items[0].rounded_total, "0.000000");
  });
});

test("HTTP errors and cancellation propagate once without hidden retry", async () => {
  for (const [status, code] of [[401, "login_required"], [403, "admin_required"], [404, "ai_price_version_not_found"],
    [409, "ai_price_version_not_effective"], [409, "ai_price_idempotency_conflict"], [422, "ai_price_invalid_request"]] as const) {
    await injected({ detail: { code, message: "Synthetic rejection", item_index: 0 } }, async calls => {
      await assert.rejects(tireApi.aiPriceVersionCreate(payload, key), cause => cause instanceof ApiError && cause.status === status && cause.code === code);
      assert.equal(calls.length, 1);
    }, status);
  }
  const abort = new AbortController(); abort.abort();
  await injected({}, async calls => {
    await assert.rejects(tireApi.aiPricePlanning(planning, abort.signal), cause => cause instanceof Error && cause.name === "AbortError");
    assert.equal(calls.length, 1);
  });
  const restore = setApiTransport(async () => { throw new TypeError("Synthetic network loss"); });
  try { await assert.rejects(tireApi.aiPriceVersionCreate(payload, key), { message: "Synthetic network loss" }); }
  finally { restore(); }
});
