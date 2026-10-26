/** Independent synthetic page/cursor wire vectors. No network, credential or database. */
import assert from "node:assert/strict";
import { assertExternalTireFactPage, createExternalApiClient, ExternalApiContractError, ExternalApiError } from "@tire/api-client";
import type { ExternalTireFactPage, ExternalTireFactPageRequest, ExternalTireFactProjection, ExternalTireFactIdentityValues } from "@tire/domain-types";

const MAX_BYTES = 1_327_104, bearer = `ti_${"a".repeat(32)}.${"b".repeat(64)}`;
const request: ExternalTireFactPageRequest = { source_id: "synthetic-page-source", query_id: "synthetic-page-query", verification_id: "synthetic-page-verification", limit: 2 };
const values: ExternalTireFactIdentityValues = { brand: "合成品牌", model: "Synthetic Page Tire", region: "US", manufacturer_product_code: "SYN-PAGE-001",
  product_code_type: "MSPN", size: "265/40ZR20", load_index: "104", speed_rating: "Y", xl: true, hl: false,
  run_flat: false, oe_mark: "", acoustic_technology: "", gtin: "12345670", technology_features: ["Ａ", "😀"], eprel_id: "1" };
function item(id = "variant-001"): ExternalTireFactProjection {
  return { schema: "external-tire-fact-projection@1", data_state: "local_snapshot", source_refresh_performed: false,
    observation: { source_id: request.source_id, snapshot_id: "synthetic-page-snapshot", raw_hash: "c".repeat(64), parser_version: "synthetic-page@1" },
    identity: { variant_id: id, contract_version: "variant-identity@2", status: "complete", values: structuredClone(values) as any },
    facts: { utqg_treadwear: 0, utqg_traction: "AA", utqg_temperature: "A", eu_fuel_class: "G", eu_wet_grip: "A", eu_external_noise_db: 0,
      eu_noise_class: "B", weight_kg: null, tread_depth: { value: 0, unit: "mm" } }, conflicted_fields: [] };
}
function payload(change: Record<string, unknown> = {}) {
  return { schema: "external-tire-facts-cursor@1", key_id: "a".repeat(32), owner: "d".repeat(64), route: "/external/v1/tire-facts",
    source_id: request.source_id, query_id: request.query_id, verification_id: request.verification_id, limit: 2,
    issued: 1_700_000_000, expires: 1_700_000_900, window: "e".repeat(64), context: "f".repeat(64), after: "variant-002", ...change };
}
const base64 = (text: string) => btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
function rawCursor(raw: string, signature = base64("\0".repeat(32))) { return base64(raw) + "." + signature; }
function cursor(change: Record<string, unknown> = {}) {
  const p = payload(change); return rawCursor(JSON.stringify(Object.fromEntries(Object.keys(p).sort().map(key => [key, (p as any)[key]]))));
}
function page(ids = ["variant-001", "variant-002"], next: string | null = cursor(), limit = 2): ExternalTireFactPage {
  return { schema: "external-tire-fact-page@1", items: ids.map(id => item(id)), next_cursor: next, limit, data_state: "local_snapshot", source_refresh_performed: false };
}
const completed: string[] = [];
function done(id: string) { assert.ok(!completed.includes(id)); completed.push(id); }
function valid(id: string, value: unknown) { assert.doesNotThrow(() => assertExternalTireFactPage(value)); done(id); }
function invalid(id: string, value: unknown) { assert.throws(() => assertExternalTireFactPage(value), ExternalApiContractError); done(id); }
function changed(id: string, change: (v: any) => void) { const v = page(); change(v); invalid(id, v); }
async function timely<T>(pending: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([pending, new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(new Error("page_result_did_not_settle")), 1000); })]); }
  finally { if (timer !== undefined) clearTimeout(timer); }
}
valid("page-full-next", page()); valid("page-full-final", page(undefined, null)); valid("page-partial-final", page(["variant-003"], null));
valid("page-limit-1", page(["variant-001"], cursor({ limit: 1, after: "variant-001" }), 1));
valid("page-limit-20", page(Array.from({ length: 20 }, (_, i) => `variant-${String(i).padStart(3, "0")}`), null, 20));
const reordered: any = page(); const o = reordered.items[1].observation;
reordered.items[1].observation = { parser_version: o.parser_version, raw_hash: o.raw_hash, snapshot_id: o.snapshot_id, source_id: o.source_id };
valid("observation-member-order", reordered);
const scoped: any = page(); scoped.items[0].identity.status = "source_scoped";
for (const key of ["manufacturer_product_code", "product_code_type", "load_index", "speed_rating", "xl", "hl", "run_flat", "oe_mark", "acoustic_technology", "gtin", "technology_features", "eprel_id"]) scoped.items[0].identity.values[key] = null;
valid("source-scoped-nulls", scoped);
for (const [name, change] of Object.entries({
  "schema": (v: any) => { v.schema = "external-sources@1"; }, "owner": (v: any) => { v.owner = "private"; },
  "missing": (v: any) => { delete v.data_state; }, "empty": (v: any) => { v.items = []; }, "items-null": (v: any) => { v.items = null; },
  "item-null": (v: any) => { v.items[0] = null; }, "refresh": (v: any) => { v.source_refresh_performed = true; },
  "state": (v: any) => { v.data_state = "live"; }, "limit-0": (v: any) => { v.limit = 0; }, "limit-21": (v: any) => { v.limit = 21; },
  "limit-string": (v: any) => { v.limit = "2"; }, "limit-fraction": (v: any) => { v.limit = 1.5; }, "limit-bool": (v: any) => { v.limit = true; },
  "over-limit": (v: any) => { v.items.push(item("variant-003")); }, "partial-next": (v: any) => { v.items.pop(); },
  "duplicate": (v: any) => { v.items[1].identity.variant_id = v.items[0].identity.variant_id; }, "order": (v: any) => { v.items.reverse(); },
  "snapshot": (v: any) => { v.items[1].observation.snapshot_id = "different"; }, "source": (v: any) => { v.items[1].observation.source_id = "different"; },
  "hash": (v: any) => { v.items[1].observation.raw_hash = "d".repeat(64); }, "parser": (v: any) => { v.items[1].observation.parser_version = "different@1"; },
  "cursor-after": (v: any) => { v.next_cursor = cursor({ after: "variant-001" }); }, "cursor-limit": (v: any) => { v.next_cursor = cursor({ limit: 1 }); },
  "cursor-source": (v: any) => { v.next_cursor = cursor({ source_id: "different" }); },
})) changed("page-invalid-" + name, change);

// The unchanged R113 single-item matrix is run separately as a full regression.
// Here its semantic families are independently embedded in a page item.
const badItems: Record<string, (v: any) => void> = {
  "schema": v => { v.schema = "external-tire-fact-projection@2"; }, "refresh": v => { v.source_refresh_performed = true; },
  "extra": v => { v.owner = "private"; }, "evidence": v => { v.observation.verification_id = "private"; },
  "raw-hash": v => { v.observation.raw_hash = "C".repeat(64); }, "parser-trim": v => { v.observation.parser_version = " bad "; },
  "identity-schema": v => { v.identity.contract_version = "variant-identity@1"; }, "identity-state": v => { v.identity.status = "unknown"; },
  "identity-missing": v => { delete v.identity.values.gtin; }, "identity-extra": v => { v.identity.values.owner = "private"; },
  "bool": v => { v.identity.values.hl = 0; }, "required-null": v => { v.identity.values.hl = null; },
  "size": v => { v.identity.values.size = "099/40ZR20"; }, "size-ratio": v => { v.identity.values.size = "265/96R20"; },
  "load": v => { v.identity.values.load_index = "1"; }, "speed": v => { v.identity.values.speed_rating = "Z"; },
  "gtin": v => { v.identity.values.gtin = "12345671"; }, "eprel": v => { v.identity.values.eprel_id = "01"; },
  "feature-order": v => { v.identity.values.technology_features = ["😀", "Ａ"]; }, "feature-dupe": v => { v.identity.values.technology_features = ["a", "a"]; },
  "fact-key": v => { v.facts.noise_db = 70; }, "fact-bool": v => { v.facts.utqg_treadwear = true; },
  "treadwear": v => { v.facts.utqg_treadwear = 5001; }, "integer": v => { v.facts.eu_external_noise_db = 0.1; },
  "noise": v => { v.facts.eu_external_noise_db = 201; }, "enum": v => { v.facts.eu_noise_class = "D"; },
  "weight-negative": v => { v.facts.weight_kg = -1; }, "weight-zero": v => { v.facts.weight_kg = 0; },
  "weight-max": v => { v.facts.weight_kg = 200.001; }, "precision": v => { v.facts.weight_kg = 1e-7; },
  "binary-precision": v => { v.facts.weight_kg = 1.2300000000000002; }, "depth-precision": v => { v.facts.tread_depth = { value: 1e-5, unit: "in" }; },
  "unit": v => { v.facts.tread_depth = { value: 1, unit: "cm" }; }, "depth-extra": v => { v.facts.tread_depth = { value: 1, unit: "mm", private: true }; },
  "empty": v => { v.facts = {}; }, "conflict-value": v => { v.conflicted_fields = ["weight_kg"]; },
  "conflict-unknown": v => { v.conflicted_fields = ["private"]; }, "conflict-order": v => { v.facts = {}; v.conflicted_fields = ["weight_kg", "eu_noise_class"]; },
};
for (const [name, change] of Object.entries(badItems)) changed("item-invalid-" + name, v => change(v.items[0]));
for (const [i, forbidden] of ["\0", "\u0085", "\u00a0", "\u200b", "\ue000", "\u0378", "\u2028", "\ud800", "\udfff"].entries()) changed("unicode-" + i, v => { v.items[0].identity.values.brand = "a" + forbidden + "b"; });
for (const [i, special] of [NaN, Infinity, -Infinity, undefined, 1n, () => 1].entries()) changed("non-json-" + i, v => { v.items[0].facts.weight_kg = special; });
for (const ending of ["\n", "\r\n"]) for (const key of ["source_id", "snapshot_id", "raw_hash"]) changed("id-ending-" + JSON.stringify(ending) + key, v => { v.items[0].observation[key] += ending; });
let getterCalled = false; const accessor: any = page(); Object.defineProperty(accessor, "private", { enumerable: true, get() { getterCalled = true; return bearer; } });
invalid("accessor", accessor); assert.equal(getterCalled, false); done("accessor-not-invoked");
const hidden: any = page(); Object.defineProperty(hidden, "private", { value: bearer }); invalid("hidden-property", hidden);
const cyclic: any = page(); cyclic.private = cyclic; invalid("cycle", cyclic);
const sparse: any = page(); delete sparse.items[0]; invalid("sparse", sparse);
const prototype: any = page(); Object.setPrototypeOf(prototype, { private: true }); invalid("prototype", prototype);
changed("depth-budget", v => { v.private = { a: { b: { c: { d: { e: { f: {} } } } } } }; });
changed("node-budget", v => { v.private = Array(5473).fill(null); });
changed("byte-budget", v => { v.private = "x".repeat(MAX_BYTES); });

const badCursors: Record<string, Record<string, unknown>> = {
  schema: { schema: "external-cursor@1" }, key: { key_id: "A".repeat(32) }, owner: { owner: "d".repeat(63) }, route: { route: "/external/v1/sources" },
  query: { query_id: "q\n" }, verification: { verification_id: "" }, source: { source_id: "a".repeat(81) }, after: { after: "variant-002\n" },
  "limit-zero": { limit: 0 }, "limit-high": { limit: 21 }, "limit-bool": { limit: true }, "limit-null": { limit: null },
  "issued-fraction": { issued: 1.5 }, "issued-negative": { issued: -1 }, "issued-unsafe": { issued: Number.MAX_SAFE_INTEGER + 1 },
  "expires-equal": { expires: 1_700_000_000 }, "expires-long": { expires: 1_700_000_901 }, "expires-null": { expires: null },
  "window": { window: {} }, "context": { context: "F".repeat(64) }, extra: { private: bearer },
};
for (const [name, change] of Object.entries(badCursors)) changed("cursor-invalid-" + name, v => { v.next_cursor = cursor(change); });
const canonical = JSON.stringify(Object.fromEntries(Object.entries(payload()).sort(([a], [b]) => a < b ? -1 : 1)));
for (const [i, value] of [cursor() + "\n", cursor() + "=", "a".repeat(2049), rawCursor(canonical + " "), rawCursor(JSON.stringify(payload())),
  rawCursor(canonical.replace('{', '{"schema":"external-tire-facts-cursor@1",')), rawCursor("{}"), rawCursor(canonical, base64("\0".repeat(31))),
  rawCursor(canonical).slice(0, -1) + "B"].entries()) changed("cursor-encoding-" + i, v => { v.next_cursor = value; });

const calls: { path: string; init: RequestInit }[] = [];
let reply: () => Response | Promise<Response> = () => Response.json(page());
const api = createExternalApiClient(bearer, async (path, init) => { calls.push({ path, init }); return reply(); });
const first = await api.tireFacts(request); assert.equal(first.items[0].facts.utqg_treadwear, 0); assert.equal(first.items[0].facts.weight_kg, null); assert.equal(first.items[0].identity.values.hl, false); done("transport-valid");
assert.equal(calls.at(-1)!.path, "/external/v1/tire-facts?source_id=synthetic-page-source&query_id=synthetic-page-query&verification_id=synthetic-page-verification&limit=2"); done("transport-url");
const init = calls.at(-1)!.init; assert.equal(init.method, "GET"); assert.deepEqual(init.headers, { Authorization: `Bearer ${bearer}`, Accept: "application/json" });
assert.equal(init.credentials, "omit"); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error"); assert.equal(init.referrerPolicy, "no-referrer"); assert.equal(init.body, undefined); done("transport-options");
reply = () => Response.json(page(["variant-001"], null, 20)); const defaults = { ...request }; delete defaults.limit;
assert.equal((await api.tireFacts(defaults)).limit, 20); assert.ok(calls.at(-1)!.path.endsWith("&limit=20")); done("request-default-limit");
const before = cursor({ after: "variant-001" });
reply = () => Response.json(page(["variant-002", "variant-003"], cursor({ after: "variant-003" })));
assert.equal((await api.tireFacts({ ...request, cursor: before })).items[0].identity.variant_id, "variant-002"); assert.equal(new URL("http://synthetic" + calls.at(-1)!.path).searchParams.get("cursor"), before); done("request-next-page");
for (const [name, change] of Object.entries({
  missing: (v: any) => { delete v.query_id; }, extra: (v: any) => { v.owner = "private"; }, variant: (v: any) => { v.variant_id = "single"; },
  source: (v: any) => { v.source_id = "a".repeat(81); }, query: (v: any) => { v.query_id = "../foreign"; }, verify: (v: any) => { v.verification_id += "\n"; },
  limit: (v: any) => { v.limit = 21; }, "limit-null": (v: any) => { v.limit = null; }, signal: (v: any) => { v.signal = {}; },
  cursor: (v: any) => { v.cursor = "x"; }, "cursor-key": (v: any) => { v.cursor = cursor({ key_id: "c".repeat(32) }); },
  "cursor-source": (v: any) => { v.cursor = cursor({ source_id: "foreign" }); }, "cursor-query": (v: any) => { v.cursor = cursor({ query_id: "foreign" }); },
  "cursor-verification": (v: any) => { v.cursor = cursor({ verification_id: "foreign" }); }, "cursor-limit": (v: any) => { v.cursor = cursor({ limit: 1 }); },
})) {
  const v: any = { ...request }; change(v); const count = calls.length;
  await assert.rejects(api.tireFacts(v), ExternalApiContractError); assert.equal(calls.length, count); done("request-invalid-" + name);
}
let requestGetter = false; const getterRequest: any = { ...request }; Object.defineProperty(getterRequest, "source_id", { enumerable: true, get() { requestGetter = true; return "private"; } });
await assert.rejects(api.tireFacts(getterRequest), ExternalApiContractError); assert.equal(requestGetter, false); done("request-accessor");
for (const original of [true, false]) {
  let release!: (response: Response) => void; const mutable = { ...request, signal: new AbortController().signal };
  const savedSignal = mutable.signal; let observed: RequestInit | undefined;
  const delayed = createExternalApiClient(bearer, async (_path, options) => { observed = options; return new Promise<Response>(resolve => { release = resolve; }); });
  const pending = delayed.tireFacts(mutable); mutable.source_id = "later"; mutable.query_id = "later"; mutable.verification_id = "later"; mutable.limit = 1; mutable.signal = new AbortController().signal;
  const response = page(); if (!original) response.items.forEach(value => { value.observation.source_id = mutable.source_id; }); release(Response.json(response));
  if (original) assert.equal((await pending).limit, 2); else await assert.rejects(pending, ExternalApiContractError);
  assert.equal(observed!.signal, savedSignal); done("request-snapshot-" + original);
}
for (const [name, change] of Object.entries({
  source: (v: any) => { v.items.forEach((i: any) => { i.observation.source_id = "foreign"; }); v.next_cursor = null; },
  limit: (v: any) => { v.limit = 3; v.next_cursor = null; }, key: (v: any) => { v.next_cursor = cursor({ key_id: "c".repeat(32) }); },
  query: (v: any) => { v.next_cursor = cursor({ query_id: "foreign" }); }, verification: (v: any) => { v.next_cursor = cursor({ verification_id: "foreign" }); },
})) { reply = () => { const v = page(); change(v); return Response.json(v); }; await assert.rejects(api.tireFacts(request), ExternalApiContractError); done("response-binding-" + name); }
for (const field of ["owner", "issued", "expires", "window", "context"] as const) {
  reply = () => Response.json(page(["variant-002", "variant-003"], cursor({ after: "variant-003", [field]: field === "issued" ? 1_700_000_001 : field === "expires" ? 1_700_000_899 : "b".repeat(64) })));
  await assert.rejects(api.tireFacts({ ...request, cursor: before }), ExternalApiContractError); done("continuation-binding-" + field);
}
reply = () => Response.json(page()); await assert.rejects(api.tireFacts({ ...request, cursor: before }), ExternalApiContractError); done("continuation-after");
for (const status of [401, 403, 404, 409, 422, 429, 503]) {
  reply = () => Response.json({ detail: bearer }, { status }); await assert.rejects(api.tireFacts(request), (e: unknown) => e instanceof ExternalApiError
    && e.status === status && e.code === "external_request_rejected" && !e.message.includes(bearer)); done("http-error-" + status);
}
reply = () => { throw new Error(bearer); }; await assert.rejects(api.tireFacts(request), (e: unknown) => e instanceof ExternalApiError && e.status === 0 && !e.message.includes(bearer)); done("transport-error");
const preAborted = new AbortController(); preAborted.abort(); const count = calls.length;
await assert.rejects(api.tireFacts({ ...request, signal: preAborted.signal }), (e: unknown) => e instanceof DOMException && e.name === "AbortError"); assert.equal(calls.length, count); done("abort-before-transport");
const pendingController = new AbortController(), never = createExternalApiClient(bearer, async () => new Promise<Response>(() => {}));
const pending = never.tireFacts({ ...request, signal: pendingController.signal }); pendingController.abort();
await assert.rejects(pending, (e: unknown) => e instanceof DOMException && e.name === "AbortError"); done("abort-pending-transport");
let bodyCancelled = 0, bodyStarted!: () => void; const started = new Promise<void>(resolve => { bodyStarted = resolve; }); let abortBody!: ReadableStream<Uint8Array>;
reply = () => { abortBody = new ReadableStream({ pull() { bodyStarted(); }, cancel() { bodyCancelled++; } }, { highWaterMark: 0 }); return new Response(abortBody, { headers: { "content-type": "application/json" } }); };
const streamController = new AbortController(), bodyPending = api.tireFacts({ ...request, signal: streamController.signal }); await started; streamController.abort();
await assert.rejects(bodyPending, (e: unknown) => e instanceof DOMException && e.name === "AbortError"); assert.equal(bodyCancelled, 1); assert.equal(abortBody.locked, false); done("abort-pending-body");
reply = () => { const v = Response.json(page()); Object.defineProperty(v, "redirected", { value: true }); return v; };
await assert.rejects(api.tireFacts(request), ExternalApiContractError); done("redirect");
for (const [name, response] of Object.entries({
  media: () => new Response("{}", { headers: { "content-type": "text/plain" } }), json: () => new Response("{", { headers: { "content-type": "application/json" } }),
  utf8: () => new Response(new Uint8Array([0xff]), { headers: { "content-type": "application/json" } }),
  stream: () => new Response(new ReadableStream({ start(controller) { controller.error(new Error(bearer)); } }), { headers: { "content-type": "application/json" } }),
})) { reply = response; await assert.rejects(api.tireFacts(request), (e: unknown) => e instanceof ExternalApiContractError && !e.message.includes(bearer)); done("wire-invalid-" + name); }
const raw = JSON.stringify(page()), rawBytes = new TextEncoder().encode(raw).byteLength;
for (const size of [MAX_BYTES - 1, MAX_BYTES, MAX_BYTES + 1]) {
  reply = () => new Response(raw + " ".repeat(size - rawBytes), { headers: { "content-type": "application/json" } });
  if (size <= MAX_BYTES) assert.equal((await api.tireFacts(request)).schema, "external-tire-fact-page@1"); else await assert.rejects(api.tireFacts(request), ExternalApiContractError);
  done("wire-bytes-" + size);
}
let cancelled = 0, oversizeBody!: ReadableStream<Uint8Array>;
reply = () => { oversizeBody = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(MAX_BYTES + 1)); }, cancel() { cancelled++; } }); return new Response(oversizeBody, { headers: { "content-type": "application/json" } }); };
await assert.rejects(api.tireFacts(request), ExternalApiContractError); assert.equal(cancelled, 1); assert.equal(oversizeBody.locked, false); done("wire-cancel-release");

// Cancellation is initiated, but an injected stream's cancel promise cannot hold the SDK result open.
const neverCancel = () => new Promise<void>(() => {});
let hangingHttpCancelled = 0, hangingHttpBody!: ReadableStream<Uint8Array>;
reply = () => { hangingHttpBody = new ReadableStream({ cancel() { hangingHttpCancelled++; return neverCancel(); } }); return new Response(hangingHttpBody, { status: 409, headers: { "content-type": "application/json" } }); };
await assert.rejects(timely(api.tireFacts(request)), (e: unknown) => e instanceof ExternalApiError && e.status === 409);
assert.equal(hangingHttpCancelled, 1); assert.equal(hangingHttpBody.locked, false); done("never-cancel-http-error");
let hangingOversizeCancelled = 0, hangingOversizeBody!: ReadableStream<Uint8Array>;
reply = () => { hangingOversizeBody = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(MAX_BYTES + 1)); }, cancel() { hangingOversizeCancelled++; return neverCancel(); } }); return new Response(hangingOversizeBody, { headers: { "content-type": "application/json" } }); };
await assert.rejects(timely(api.tireFacts(request)), ExternalApiContractError);
assert.equal(hangingOversizeCancelled, 1); assert.equal(hangingOversizeBody.locked, false); done("never-cancel-oversize");
let hangingAbortCancelled = 0, hangingAbortStarted!: () => void, hangingAbortBody!: ReadableStream<Uint8Array>;
const hangingStarted = new Promise<void>(resolve => { hangingAbortStarted = resolve; });
reply = () => { hangingAbortBody = new ReadableStream({ pull() { hangingAbortStarted(); }, cancel() { hangingAbortCancelled++; return neverCancel(); } }, { highWaterMark: 0 }); return new Response(hangingAbortBody, { headers: { "content-type": "application/json" } }); };
const hangingController = new AbortController(), hangingPending = api.tireFacts({ ...request, signal: hangingController.signal });
await hangingStarted; hangingController.abort();
await assert.rejects(timely(hangingPending), (e: unknown) => e instanceof DOMException && e.name === "AbortError");
assert.equal(hangingAbortCancelled, 1); assert.equal(hangingAbortBody.locked, false); done("never-cancel-abort");
let unhandled = 0; const onUnhandled = () => { unhandled++; }; process.on("unhandledRejection", onUnhandled);
try {
  let lateResolve!: (response: Response) => void, lateCancelled = 0;
  const lateClient = createExternalApiClient(bearer, async () => new Promise<Response>(resolve => { lateResolve = resolve; }));
  const lateController = new AbortController(), latePending = lateClient.tireFacts({ ...request, signal: lateController.signal });
  lateController.abort(); await assert.rejects(timely(latePending), (e: unknown) => e instanceof DOMException && e.name === "AbortError");
  const lateBody = new ReadableStream<Uint8Array>({ cancel() { lateCancelled++; return neverCancel(); } });
  lateResolve(new Response(lateBody, { headers: { "content-type": "application/json" } }));
  await new Promise<void>(resolve => setImmediate(resolve));
  assert.equal(lateCancelled, 1); assert.equal(lateBody.locked, false); assert.equal(unhandled, 0); done("abort-late-response-cleanup");
  let rejectCancelled = 0, rejectBody!: ReadableStream<Uint8Array>;
  reply = () => { rejectBody = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(MAX_BYTES + 1)); }, cancel() { rejectCancelled++; return Promise.reject(new Error(bearer)); } }); return new Response(rejectBody, { headers: { "content-type": "application/json" } }); };
  await assert.rejects(timely(api.tireFacts(request)), ExternalApiContractError); await new Promise<void>(resolve => setImmediate(resolve));
  assert.equal(rejectCancelled, 1); assert.equal(rejectBody.locked, false); assert.equal(unhandled, 0); done("cleanup-rejection-consumed");
} finally { process.removeListener("unhandledRejection", onUnhandled); }
const encoded = new TextEncoder().encode(raw), emoji = new TextEncoder().encode("😀");
const split = encoded.findIndex((value, index) => value === emoji[0] && encoded[index + 1] === emoji[1]) + 1; assert.ok(split > 0);
reply = () => new Response(new ReadableStream({ start(controller) { controller.enqueue(encoded.slice(0, split)); controller.enqueue(encoded.slice(split)); controller.close(); } }), { headers: { "content-type": "application/json" } });
assert.equal((await api.tireFacts(request)).items[0].identity.values.technology_features?.at(-1), "😀"); done("wire-split-utf8");
assert.equal(completed.length, 189);
console.log(JSON.stringify({ schema: "external-tire-fact-page-sdk-synthetic@1", checks: completed.length, status: "passed", real_http: false, database: false }));
