/** Independent synthetic wire vectors. No real credential, HTTP server or database. */
import assert from "node:assert/strict";
import { assertExternalTireFactResult, createExternalApiClient, ExternalApiContractError, ExternalApiError } from "@tire/api-client";
import type { ExternalTireFactRequest, ExternalTireFactResult, ExternalTireFactIdentityValues } from "@tire/domain-types";

const MAX_BYTES = 65_792, bearer = `ti_${"a".repeat(32)}.${"b".repeat(64)}`;
const request: ExternalTireFactRequest = { source_id: "synthetic-reader-source", query_id: "synthetic-query", verification_id: "synthetic-verification", variant_id: "synthetic-variant" };
const values: ExternalTireFactIdentityValues = { brand: "合成品牌", model: "Synthetic Tire", region: "US", manufacturer_product_code: "SYN-001",
  product_code_type: "MSPN", size: "265/40ZR20", load_index: "104", speed_rating: "Y", xl: true, hl: false,
  run_flat: false, oe_mark: "", acoustic_technology: "", gtin: "12345670", technology_features: ["Ａ", "😀"], eprel_id: "1" };
function result(): ExternalTireFactResult {
  return { status: "projected", reason: "projected", item: { schema: "external-tire-fact-projection@1", data_state: "local_snapshot", source_refresh_performed: false,
    observation: { source_id: request.source_id, snapshot_id: "synthetic-snapshot", raw_hash: "c".repeat(64), parser_version: "synthetic@1" },
    identity: { variant_id: request.variant_id, contract_version: "variant-identity@2", status: "complete", values: structuredClone(values) as any },
    facts: { utqg_treadwear: 0, utqg_traction: "AA", utqg_temperature: "A", eu_fuel_class: "G", eu_wet_grip: "A", eu_external_noise_db: 0,
      eu_noise_class: "B", weight_kg: null, tread_depth: { value: 0, unit: "mm" } }, conflicted_fields: [] } };
}
let checked = 0;
function valid(v: unknown) { assert.doesNotThrow(() => assertExternalTireFactResult(v)); checked++; }
function invalid(v: unknown) { assert.throws(() => assertExternalTireFactResult(v), ExternalApiContractError); checked++; }
function changed(change: (v: any) => void) { const v = result(); change(v); invalid(v); }
valid(result());
for (const speed of ["(Y)", "ZR"]) { const v: any = result(); v.item.identity.values.speed_rating = speed; valid(v); }
const scoped: any = result(); scoped.item.identity.status = "source_scoped";
for (const key of ["manufacturer_product_code", "product_code_type", "load_index", "speed_rating", "xl", "hl", "run_flat", "oe_mark", "acoustic_technology", "gtin", "technology_features", "eprel_id"]) scoped.item.identity.values[key] = null;
valid(scoped);
for (const unit of ["mm", "1/32 in", "in"]) { const v: any = result(); v.item.facts.tread_depth = { value: unit === "in" ? 0.0001 : 0.001, unit }; v.item.facts.weight_kg = 0.001; valid(v); }
const conflict: any = result(); conflict.item.facts = {}; conflict.item.conflicted_fields = ["eu_fuel_class", "weight_kg"]; valid(conflict);
const nullFact: any = result(); nullFact.item.facts = { weight_kg: null }; valid(nullFact);
const noFeatures: any = result(); noFeatures.item.identity.values.technology_features = []; valid(noFeatures);
const maxValues: any = result(); maxValues.item.facts = { utqg_treadwear: 5000, eu_external_noise_db: 200, weight_kg: 199.999, tread_depth: { value: 4, unit: "in" } }; valid(maxValues);

for (const change of [
  (v: any) => { v.owner = "private"; }, (v: any) => { v.status = "not_applicable"; }, (v: any) => { v.reason = "reader_policy_invalid"; },
  (v: any) => { v.item = null; }, (v: any) => { v.item.schema = "external-tire-fact-projection@2"; },
  (v: any) => { v.item.data_state = "live"; }, (v: any) => { v.item.source_refresh_performed = true; },
  (v: any) => { v.item.observation.verification_id = "private"; }, (v: any) => { v.item.observation.raw_hash = "C".repeat(64); },
  (v: any) => { v.item.observation.parser_version = " bad "; }, (v: any) => { v.item.observation.source_id = "a".repeat(81); },
  (v: any) => { v.item.identity.contract_version = "variant-identity@1"; }, (v: any) => { v.item.identity.status = "unknown"; },
  (v: any) => { delete v.item.identity.values.gtin; }, (v: any) => { v.item.identity.values.owner = "private"; },
  (v: any) => { v.item.identity.values.xl = 1; }, (v: any) => { v.item.identity.values.hl = null; },
  (v: any) => { v.item.identity.values.size = "099/40ZR20"; }, (v: any) => { v.item.identity.values.size = "265/96R20"; },
  (v: any) => { v.item.identity.values.size = "265/40R30.5"; }, (v: any) => { v.item.identity.values.size = "265/40R20.0"; },
  (v: any) => { v.item.identity.values.load_index = "1"; }, (v: any) => { v.item.identity.values.speed_rating = "Z"; },
  (v: any) => { v.item.identity.values.gtin = "12345671"; }, (v: any) => { v.item.identity.values.eprel_id = "01"; },
  (v: any) => { v.item.identity.values.technology_features = ["😀", "Ａ"]; },
  (v: any) => { v.item.identity.values.technology_features = ["feature", "feature"]; },
  (v: any) => { v.item.identity.values.technology_features = Array.from({ length: 33 }, (_, i) => `f${i}`); },
  (v: any) => { v.item.facts.noise_db = 70; }, (v: any) => { v.item.facts.utqg_treadwear = true; },
  (v: any) => { v.item.facts.utqg_treadwear = 5001; }, (v: any) => { v.item.facts.utqg_treadwear = 0.1; },
  (v: any) => { v.item.facts.eu_external_noise_db = 201; }, (v: any) => { v.item.facts.eu_noise_class = "D"; },
  (v: any) => { v.item.facts.weight_kg = 0; }, (v: any) => { v.item.facts.weight_kg = 200.001; },
  (v: any) => { v.item.facts.weight_kg = 1e-7; }, (v: any) => { v.item.facts.weight_kg = 1.2300000000000002; },
  (v: any) => { v.item.facts.tread_depth = { value: 1e-5, unit: "in" }; },
  (v: any) => { v.item.facts.tread_depth = { value: 1, unit: "cm" }; },
  (v: any) => { v.item.facts.tread_depth = { value: 129, unit: "1/32 in" }; },
  (v: any) => { v.item.facts.tread_depth = { value: 1, unit: "mm", after: "private" }; },
  (v: any) => { v.item.facts = {}; }, (v: any) => { v.item.conflicted_fields = ["weight_kg"]; },
  (v: any) => { v.item.conflicted_fields = ["unknown"]; }, (v: any) => { v.item.facts = {}; v.item.conflicted_fields = ["weight_kg", "weight_kg"]; },
  (v: any) => { v.item.facts = {}; v.item.conflicted_fields = ["weight_kg", "eu_noise_class"]; },
]) changed(change);
for (const forbidden of ["\0", "\u0085", "\u00a0", "\u200b", "\ue000", "\u0378", "\u2028", "\ud800", "\udfff"]) changed(v => { v.item.identity.values.brand = "a" + forbidden + "b"; });
for (const ending of ["\n", "\r\n"]) {
  for (const key of ["source_id", "snapshot_id", "raw_hash"]) changed(v => { v.item.observation[key] += ending; });
  changed(v => { v.item.identity.variant_id += ending; });
  for (const key of ["size", "load_index", "gtin", "eprel_id"]) changed(v => { v.item.identity.values[key] += ending; });
}
for (const special of [NaN, Infinity, -Infinity, undefined, 1n, () => 1]) changed(v => { v.item.facts.weight_kg = special; });
const cyclic: any = result(); cyclic.item.facts.cycle = cyclic; invalid(cyclic);
let getterCalled = false; const accessor: any = result(); Object.defineProperty(accessor.item, "owner", { enumerable: true, get() { getterCalled = true; return "private"; } }); invalid(accessor); assert.equal(getterCalled, false); checked++;
const hidden: any = result(); Object.defineProperty(hidden.item, "owner", { value: "private" }); invalid(hidden);
const deep: any = result(); deep.extra = { a: { b: { c: { d: { e: {} } } } } }; invalid(deep);
const many: any = result(); many.item.identity.values.technology_features = Array(273).fill("feature"); invalid(many);

const calls: { path: string; init: RequestInit }[] = [];
let reply: () => Response | Promise<Response> = () => Response.json(result());
const api = createExternalApiClient(bearer, async (path, init) => { calls.push({ path, init }); return reply(); });
const first = await api.tireFact(request); assert.equal(first.item.facts.utqg_treadwear, 0); assert.equal(first.item.facts.weight_kg, null); assert.equal(first.item.identity.values.hl, false); checked++;
assert.equal(calls.at(-1)!.path, "/external/v1/tire-facts/synthetic-variant?source_id=synthetic-reader-source&query_id=synthetic-query&verification_id=synthetic-verification"); checked++;
const init = calls.at(-1)!.init;
assert.equal(init.method, "GET"); assert.deepEqual(init.headers, { Authorization: `Bearer ${bearer}`, Accept: "application/json" });
assert.equal(init.credentials, "omit"); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error"); assert.equal(init.referrerPolicy, "no-referrer"); assert.equal(init.body, undefined); checked++;
for (const returnOriginal of [true, false]) {
  let release!: (response: Response) => void;
  const mutable = { ...request };
  const deferred = createExternalApiClient(bearer, async () => new Promise<Response>(resolve => { release = resolve; }));
  const pending = deferred.tireFact(mutable);
  mutable.source_id = "later-source"; mutable.variant_id = "later-variant";
  const response = result();
  if (!returnOriginal) { response.item.observation.source_id = mutable.source_id; response.item.identity.variant_id = mutable.variant_id; }
  release(Response.json(response));
  if (returnOriginal) assert.equal((await pending).item.identity.variant_id, request.variant_id);
  else await assert.rejects(pending, ExternalApiContractError);
  checked++;
}
for (const change of [
  (v: any) => { delete v.source_id; }, (v: any) => { v.owner = "private"; }, (v: any) => { v.variant_id = "../foreign"; },
  (v: any) => { v.source_id = "a".repeat(81); }, (v: any) => { v.query_id = ""; }, (v: any) => { v.verification_id = "a".repeat(65); },
  (v: any) => { v.signal = {}; }, (v: any) => { v.cursor = "forbidden"; },
]) {
  const v: any = { ...request }; change(v); const count = calls.length;
  await assert.rejects(api.tireFact(v), ExternalApiContractError); assert.equal(calls.length, count); checked++;
}
for (const ending of ["\n", "\r\n"]) for (const key of ["source_id", "query_id", "verification_id", "variant_id"]) {
  const v: any = { ...request }; v[key] += ending; const count = calls.length;
  await assert.rejects(api.tireFact(v), ExternalApiContractError); assert.equal(calls.length, count); checked++;
}
for (const mismatch of ["source", "variant"]) {
  reply = () => { const v = result(); if (mismatch === "source") v.item.observation.source_id = "foreign"; else v.item.identity.variant_id = "foreign"; return Response.json(v); };
  await assert.rejects(api.tireFact(request), ExternalApiContractError); checked++;
}
for (const status of [401, 403, 404, 409, 429, 503]) {
  reply = () => Response.json({ detail: bearer }, { status });
  await assert.rejects(api.tireFact(request), (error: unknown) => error instanceof ExternalApiError && error.status === status
    && error.code === "external_request_rejected" && !error.message.includes(bearer)); checked++;
}
reply = () => { throw new Error(bearer); };
await assert.rejects(api.tireFact(request), (error: unknown) => error instanceof ExternalApiError && error.status === 0 && !error.message.includes(bearer)); checked++;
const aborted = new AbortController(); aborted.abort();
await assert.rejects(api.tireFact({ ...request, signal: aborted.signal }), (error: unknown) => error instanceof DOMException && error.name === "AbortError"); checked++;
reply = () => { const v = Response.json(result()); Object.defineProperty(v, "redirected", { value: true }); return v; };
await assert.rejects(api.tireFact(request), ExternalApiContractError); checked++;
for (const response of [() => new Response("{}", { headers: { "content-type": "text/plain" } }),
  () => new Response("{", { headers: { "content-type": "application/json" } }),
  () => new Response(new Uint8Array([0xff]), { headers: { "content-type": "application/json" } }),
  () => new Response(new ReadableStream({ start(controller) { controller.error(new Error(bearer)); } }), { headers: { "content-type": "application/json" } })]) {
  reply = response; await assert.rejects(api.tireFact(request), (error: unknown) => error instanceof ExternalApiContractError && !error.message.includes(bearer)); checked++;
}
const raw = JSON.stringify(result()), rawBytes = new TextEncoder().encode(raw).length;
for (const size of [MAX_BYTES - 1, MAX_BYTES, MAX_BYTES + 1]) {
  reply = () => new Response(raw + " ".repeat(size - rawBytes), { headers: { "content-type": "application/json" } });
  if (size <= MAX_BYTES) assert.equal((await api.tireFact(request)).status, "projected");
  else await assert.rejects(api.tireFact(request), ExternalApiContractError);
  checked++;
}
let cancelled = 0; let oversizeBody: ReadableStream<Uint8Array>;
reply = () => { oversizeBody = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(MAX_BYTES + 1)); }, cancel() { cancelled++; } }); return new Response(oversizeBody, { headers: { "content-type": "application/json" } }); };
await assert.rejects(api.tireFact(request), ExternalApiContractError); assert.equal(cancelled, 1); assert.equal(oversizeBody!.locked, false); checked++;
const encoded = new TextEncoder().encode(raw), emoji = new TextEncoder().encode("😀");
const splitAt = encoded.findIndex((value, index) => value === emoji[0] && encoded[index + 1] === emoji[1]) + 1;
assert.ok(splitAt > 0);
reply = () => new Response(new ReadableStream({ start(controller) { controller.enqueue(encoded.slice(0, splitAt)); controller.enqueue(encoded.slice(splitAt)); controller.close(); } }), { headers: { "content-type": "application/json" } });
assert.equal((await api.tireFact(request)).item.identity.values.technology_features?.at(-1), "😀"); checked++;
console.log(JSON.stringify({ schema: "external-tire-facts-sdk-synthetic@1", checks: checked, status: "passed", real_http: false, database: false }));
