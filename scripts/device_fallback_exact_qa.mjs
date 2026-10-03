import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, mkdirSync, copyFileSync, appendFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { loadOfflineTypeScript } from "./load_offline_typescript.mjs";
import { offlineHostBuild } from "./offline-host-build.mjs";

const exact = await loadOfflineTypeScript("../packages/api-client/src/exact-json.ts", import.meta.url);
const { ExactJsonNumber, parseExactJson, stringifyExactJson, projectExactJson,
  encodeExactDeviceFallbackWire, decodeExactDeviceFallbackWire, exactSafeInteger } = exact;
const number = value => new ExactJsonNumber(value);
const core = facts => ({ schema: "device-fallback-result@2", query_kind: "tire", complete_query_result: false,
  slot: { generation: 1, byte_count: 42 }, members: [{ payload: { facts } }] });
const roundtrip = value => decodeExactDeviceFallbackWire(JSON.parse(JSON.stringify(encodeExactDeviceFallbackWire(value)))).core;

test("exact integer/f64 tokens survive real JSON mirror encoding including integer beyond finite double", () => {
  const tokens = ["9007199254740993", "9223372036854775809", "9".repeat(400), "5e-324", "0.1", "1e20", "-0.0", "1.0"];
  const value = core(Object.fromEntries(tokens.map((token, index) => [String(index), number(token)])));
  const wire = encodeExactDeviceFallbackWire(value);
  assert.equal(wire.members[0].payload.facts["0"], 9007199254740992);
  assert.equal(wire.members[0].payload.facts["2"], null);
  const returned = roundtrip(value);
  for (const [index, token] of tokens.entries()) assert.equal(returned.members[0].payload.facts[String(index)].token, token);
  assert.equal(returned.slot.generation, 1);
  assert.ok(stringifyExactJson(returned).includes('"0":9007199254740993'));
});

test("mirrors retain all typed fields and reject number/non-number/type/keys tampering", () => {
  const value = core({ huge: number("9007199254740993"), flag: false, text: "original" });
  for (const mutate of [
    wire => wire.members[0].payload.facts.huge = 9007199254740994,
    wire => wire.members[0].payload.facts.huge = "9007199254740992",
    wire => wire.members[0].payload.facts.flag = true,
    wire => wire.members[0].payload.facts.text = "changed",
    wire => delete wire.members[0].payload.facts.text,
    wire => wire.members[0].payload.facts.extra = "unadvertised",
    wire => wire.slot.generation = 2,
    wire => wire.extra = true,
  ]) {
    const wire = encodeExactDeviceFallbackWire(value); mutate(wire);
    assert.throws(() => decodeExactDeviceFallbackWire(wire), { code: "OFFLINE_FALLBACK_INVALID" });
  }
});

test("projection null is only a huge integer transport case and cannot weaken safe metadata", () => {
  const wire = encodeExactDeviceFallbackWire(core({ value: number("9".repeat(400)) }));
  assert.equal(wire.members[0].payload.facts.value, null);
  assert.equal(roundtrip(core({ value: number("9".repeat(400)) })).members[0].payload.facts.value.integer.toString().length, 400);
  for (const token of ["9007199254740993", "9".repeat(400), "1.0", "-1"]) {
    const invalidMetadata = core({}); invalidMetadata.slot.generation = number(token);
    assert.throws(() => roundtrip(invalidMetadata), { code: "OFFLINE_FALLBACK_INVALID" });
  }
  for (const token of ["1e309", "NaN", "Infinity", "00", "+1", "1."]) assert.throws(() => number(token));
});

test("decide/consume/authorize @2 request mirror contains exact full frozen criteria", () => {
  const intent = { schema: "device-fallback-intent@2", query_kind: "tire", fallback_policy: "ask",
    query: { size: "225/45R18" }, filters: [{ field: "utqg_treadwear", op: "gte", value: number("9007199254740993") }],
    source_access_generation: 3, authority: { authority_revision: 1, runtime_session_id: "runtime" } };
  for (const request of [{ intent, decision: "allow", expected_generation: 1 }, { intent, grant_id: "grant" }, { intent, expected_generation: 1 }]) {
    const returned = roundtrip(request);
    assert.equal(returned.intent.filters[0].value.token, "9007199254740993");
    assert.equal(returned.intent.source_access_generation, 3);
    assert.deepEqual(Object.keys(returned).sort(), Object.keys(request).sort());
  }
});

test("authorize uses one outer sidechannel; ordinary facts called raw_json remain legal", () => {
  const grant = { schema: "device-fallback-grant@2", scope: "local_once", state: "allowed", generation: 1,
    intent: { schema: "device-fallback-intent@2", filters: [{ value: number("9007199254740993") }] } };
  const allowed = { schema: "device-fallback-authorization@1", state: "allowed", reason: null, grant };
  assert.equal(roundtrip(allowed).grant.intent.filters[0].value.token, "9007199254740993");
  assert.throws(() => encodeExactDeviceFallbackWire({ ...allowed, grant: { ...grant, raw_json: "recursive" } }));
  const returned = roundtrip(core({ raw_json: "ordinary material key" }));
  assert.equal(returned.members[0].payload.facts.raw_json, "ordinary material key");
});

test("duplicate keys, invalid Unicode, excessive depth, recursive transport and future/legacy schemas reject", () => {
  for (const input of ['{"x":1,"x":2}', '{"x":"\\ud800"}', '[1,]', '{"x":01}', '"\ud800"', '['.repeat(66) + '0' + ']'.repeat(66)]) assert.throws(() => parseExactJson(input));
  assert.throws(() => parseExactJson(new Uint8Array([0xc3, 0x28])));
  assert.throws(() => parseExactJson(new Uint8Array([0xef, 0xbb, 0xbf, 0x30])));
  for (const value of [{ intent: { schema: "device-fallback-intent@1" } }, { schema: "device-fallback-result@3" }, { ...core({}), raw_json: "recursive" }]) {
    assert.throws(() => encodeExactDeviceFallbackWire(value));
  }
  const wire = encodeExactDeviceFallbackWire(core({}));
  wire.raw_json = '{"schema":"device-fallback-result@2","schema":"device-fallback-result@2"}';
  assert.throws(() => decodeExactDeviceFallbackWire(wire));
});

test("raw core and native transport retain separate bounded budgets", () => {
  assert.throws(() => parseExactJson('"' + 'x'.repeat(exact.EXACT_JSON_BYTES) + '"'));
  assert.throws(() => encodeExactDeviceFallbackWire(core({ text: 'x'.repeat(exact.EXACT_JSON_BYTES) })));
  const wire = encodeExactDeviceFallbackWire(core({})); wire.extra = 'x'.repeat(exact.EXACT_NATIVE_WIRE_BYTES);
  assert.throws(() => decodeExactDeviceFallbackWire(wire));
  assert.equal(exactSafeInteger(number("9007199254740991")), Number.MAX_SAFE_INTEGER);
  assert.equal(projectExactJson(number("-0.0")), 0);
});

test("Web and both native frontend host fingerprints change when only Unicode bytes change", () => {
  const root = resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
  const output = resolve(root, ".artifacts/query-fallback49/web-consume-unicode-hash-a");
  mkdirSync(output, { recursive: true });
  const source = readFileSync(resolve(root, "scripts/offline-host-build.mjs"), "utf8");
  const names = new Set([...source.matchAll(/"((?:apps|packages|scripts)\/[^"\r\n]+)"/g)].map(match => match[1]));
  names.add("packages/domain-types/src/query-filter-unicode.json");
  for (const platform of ["web", "desktop", "mobile"]) {
    names.add(`apps/${platform}/package.json`); names.add(`apps/${platform}/${platform === "web" ? "next.config.ts" : "vite.config.ts"}`);
  }
  for (const name of names) { const target = resolve(output, name); mkdirSync(dirname(target), { recursive: true }); copyFileSync(resolve(root, name), target); }
  const before = Object.fromEntries(["web", "desktop", "mobile"].map(platform => [platform, offlineHostBuild(output, platform)]));
  for (const platform of Object.keys(before)) assert.equal(before[platform], offlineHostBuild(root, platform));
  appendFileSync(resolve(output, "packages/domain-types/src/query-filter-unicode.json"), "\n");
  for (const platform of Object.keys(before)) assert.notEqual(before[platform], offlineHostBuild(output, platform));
});
