/** Actual 8 MiB default parser and complete TS projection/closure acceptance. */
import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { CORPUS, CapacityCorpus, checkBytes, sha256 } from "./capacity-corpus.mjs";
import { canonicalDeviceAiJson, parseDeviceAiJson } from "../../src/device-ai-exact.ts";
import { projectDeviceAiPack } from "../../src/device-ai-projection.ts";
import { assertDeviceAiPrepareBody, deviceContextFingerprint, localPreviewFingerprint, selectionSha256 } from "../../src/device-ai-host.ts";

let passed = 0;
const failures: string[] = [];
async function run(id: string, test: () => unknown) {
  try { await test(); passed++; console.log(`PASS ${id}`); }
  catch (error) { failures.push(id); console.error(`FAIL ${id}`, error); }
}
function code(expected: string) { return (error: any) => error?.code === expected; }

const recipes = CORPUS.readJson("boundary-recipes.json");
const formal = CORPUS.readJson("formal-package.json");
const closure = CORPUS.readJson("closure-package.json");
const fingerprints = CORPUS.readJson("closure-fingerprints.json");
const onlyContext = process.argv.includes("--context-only");

if (!onlyContext) {
  for (const item of recipes.cases) await run(item.id, () => {
    const raw = CORPUS.expand(item);
    if (item.expected.state === "rejected") {
      assert.throws(() => parseDeviceAiJson(raw), code(item.expected.error_code));
    } else {
      const text = canonicalDeviceAiJson(parseDeviceAiJson(raw));
      assert.equal(text, item.expected.canonical_text);
      assert.equal(Buffer.from(text).toString("hex"), item.expected.canonical_utf8_hex);
      assert.equal(sha256(Buffer.from(text)), item.expected.canonical_sha256);
      // Non-BMP string entry must also count TextEncoder bytes, not UTF-16 units.
      if (item.id.startsWith("nonbmp-")) assert.equal(canonicalDeviceAiJson(parseDeviceAiJson(raw.toString("utf8"))), text);
    }
    if (item.id === "nonbmp-n-plus-1") assert.throws(() => parseDeviceAiJson(raw.toString("utf8")), code(item.expected.error_code));
  });
  for (const item of formal.cases) await run(item.id, async () => {
    const raw = CORPUS.formalBytes(formal, item);
    const request = CORPUS.readJson(formal.projection_input);
    const binding = { ...request.binding, sha256: item.input_sha256, byte_count: raw.length };
    if (item.expected.state === "rejected") {
      assert.throws(() => parseDeviceAiJson(raw), code(item.parser_expected.error_code));
      await assert.rejects(projectDeviceAiPack(raw, binding, request.selectors, request.mode, request.approved_closure), code(item.expected.error_code));
    } else {
      assert.equal(canonicalDeviceAiJson(parseDeviceAiJson(raw)), canonicalDeviceAiJson(parseDeviceAiJson(CORPUS.readBytes(formal.base_pack))));
      const result = await projectDeviceAiPack(raw, binding, request.selectors, request.mode, request.approved_closure);
      assert.equal(result.canonicalText, CORPUS.readBytes(item.expected.projection_file).toString("utf8"));
      checkBytes(Buffer.from(result.canonicalText), item.expected.projection_byte_count, item.expected.projection_sha256);
      assert.equal(result.sha256, item.expected.projection_sha256);
      assert.equal(result.memberCount, 1);
      const actual = parseDeviceAiJson(result.canonicalText) as any;
      const base = parseDeviceAiJson(CORPUS.readBytes("projections/formal-base.canonical.json")) as any;
      assert.equal(canonicalDeviceAiJson(actual.observations), canonicalDeviceAiJson(base.observations));
      assert.equal(actual.archive.sha256, item.input_sha256);
    }
  });
  for (const item of closure.cases) await run(item.id, async () => {
    const raw = CORPUS.readBytes(item.package_file ?? closure.package_file);
    const binding = item.binding ?? closure.binding;
    const promise = projectDeviceAiPack(raw, binding, item.selectors, item.mode, item.approved_closure);
    if (item.expected.state === "rejected") {
      await assert.rejects(promise, code(item.expected.error_code));
    } else {
      const result = await promise;
      assert.equal(result.canonicalText, CORPUS.readBytes(item.expected.projection_file).toString("utf8"));
      checkBytes(Buffer.from(result.canonicalText), item.expected.projection_byte_count, item.expected.projection_sha256);
      assert.equal(result.sha256, item.expected.projection_sha256);
      assert.deepEqual(result.observations.map((o: any) => o.selector), item.expected.resolved_closure);
      assert.equal(result.memberCount, item.expected.resolved_closure.length);
      for (const key of closure.unselected_member_keys) assert(!result.canonicalText.includes(key));
    }
  });
  await run("selection-permutation", async () => {
    assert.equal(await selectionSha256(fingerprints.selection_input), fingerprints.selection_expected.sha256);
    assert.equal(await selectionSha256([...fingerprints.selection_input].reverse()), fingerprints.selection_expected.sha256);
  });
  for (const item of fingerprints.preview_cases) await run(item.id, async () => {
    const input = item.input;
    const actual = await localPreviewFingerprint({ questionSha256Value: input.question_sha256,
      includeContextIds: input.include_context_ids, projectionMode: input.projection_mode,
      queryContext: input.query_context, origin: input.origin, selected: input.selected,
      resolvedClosure: input.resolved_closure, state: input.state,
      projectionSha256Value: input.projection_sha256 });
    assert.equal(actual, item.expected.sha256);
  });
  for (const count of [6, 7]) await run(`prepare-wire-cap-${count}`, () => {
    const source = closure.cases[0].selectors[0];
    const selectors = Array.from({ length: count }, (_, index) => ({ ...source, member_key: (index + 1).toString(16).padStart(64, "0") }));
    const binding = closure.binding;
    const body = { package_id: binding.package_id, expected_sha256: binding.sha256,
      expected_byte_count: binding.byte_count, expected_schema: binding.schema,
      expected_owner_scope_id: binding.owner_scope_id, selectors,
      projection_mode: "frozen_decision_closure", approved_closure: selectors,
      expected_projection_sha256: "a".repeat(64), question_sha256: "b".repeat(64),
      host_receipt_id: "11111111-2222-4333-8444-555555555555", intent_id: "66666666-7777-4888-8999-aaaaaaaaaaaa" };
    if (count === 6) assertDeviceAiPrepareBody(body as never);
    else assert.throws(() => assertDeviceAiPrepareBody(body as never), code("device_ai_host_invalid_argument"));
  });
  for (const change of ["missing", "corrupt", "manifest", "escape", "unbound", "recipe-length", "recipe-sha"]) await run(`integrity-${change}`, () => {
    const temporary = mkdtempSync(path.join(tmpdir(), "device-ai-capacity-"));
    try {
      const root = path.join(temporary, "corpus");
      cpSync(CORPUS.root, root, { recursive: true });
      if (change === "missing") unlinkSync(path.join(root, "base-pack.json"));
      if (change === "corrupt") {
        const raw = readFileSync(path.join(root, "base-pack.json")); raw[0] ^= 1;
        writeFileSync(path.join(root, "base-pack.json"), raw);
      }
      if (change === "manifest") writeFileSync(path.join(root, "manifest.json"), " ", { flag: "a" });
      if (["missing", "corrupt", "manifest"].includes(change)) assert.throws(() => new CapacityCorpus(root));
      else if (["escape", "unbound"].includes(change)) assert.throws(() => new CapacityCorpus(root).readBytes(change === "escape" ? "../base-pack.json" : "unknown.json"));
      else {
        const item = structuredClone(recipes.cases[0]);
        if (change === "recipe-length") item.input_byte_count = 1; else item.input_sha256 = "0".repeat(64);
        assert.throws(() => CORPUS.expand(item));
      }
    } finally { rmSync(temporary, { recursive: true, force: true }); }
  });
}
for (const item of fingerprints.context_cases) await run(item.id, async () => {
  assert.equal(await deviceContextFingerprint(item.input), item.expected.sha256);
});
console.log(JSON.stringify({ schema: "device-ai-capacity-ts-result@1", passed, failed: failures.length, failures,
  actual_package_bytes_limit: 8_388_608, native_full_projection_claimed: false }));
if (failures.length) process.exitCode = 1;
