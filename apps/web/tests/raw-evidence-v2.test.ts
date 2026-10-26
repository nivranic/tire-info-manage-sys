import assert from "node:assert/strict";
import { test } from "node:test";
import { assertRawEvidenceDisplay, assertRawEvidenceInput, createRawEvidenceOperations, deliverBrowserRawDownload, freezeRawEvidenceDisplay,
  rawEvidenceCanonical, RawEvidenceDisplayChanged, RawEvidenceViewChanged, type BrowserDownloadEnvironment,
  type RawEvidenceOwner } from "../components/raw-evidence-v2-context.ts";

const metadata = () => ({ evidence_format: "raw-evidence-v2", body_encoding: "binary", body: null, raw_capture_id: "capture",
  raw_hash: "a".repeat(64), byte_count: 24, content_type: "application/pdf", content_path: "/v1/captures/capture/content?mode=history",
  parse_method: null, mapping_id: null, id: "capture", source_id: "source", source_url: "https://fixture.invalid/original.pdf",
  observed_at: "2026-10-20T00:00:00Z", parser_version: "parser@1", parser_identity: { bundle_id: "b".repeat(64), parser_digest: "c".repeat(64), deployment_revision: 1 },
  snapshot_id: "snapshot", vehicle_id: "vehicle", query_state: "pending", query: { vehicle_id: "vehicle", keys: ["front", "rear"] },
  parse_provenance: { method: "frozen", mapping_id: "mapping@1", source_raw_hash: "a".repeat(64) } });

test("complete metadata is copied and deeply frozen; object key order alone is irrelevant", () => {
  const original = metadata(), display = freezeRawEvidenceDisplay("capture", original);
  assert.notEqual(display.metadata, original);
  assert.ok(Object.isFrozen(display.metadata.parser_identity));
  assert.ok(Object.isFrozen(display.metadata.query.keys));
  const reordered = Object.fromEntries(Object.entries(original).reverse());
  assertRawEvidenceDisplay(display, "capture", reordered);
  original.parser_identity.deployment_revision = 9;
  assert.equal(display.metadata.parser_identity.deployment_revision, 1);
  assert.throws(() => assertRawEvidenceDisplay(display, "capture", original), RawEvidenceDisplayChanged);
});

test("every raw and display identity field rejects independently, even with the same PDF hash", () => {
  const original = metadata(), display = freezeRawEvidenceDisplay("capture", original);
  for (const key of Object.keys(original)) {
    const changed = { ...original, [key]: "different" };
    assert.throws(() => assertRawEvidenceDisplay(display, "capture", changed), RawEvidenceDisplayChanged, key);
  }
  for (const key of Object.keys(original.parser_identity)) {
    const changed = { ...original, parser_identity: { ...original.parser_identity, [key]: "different" } };
    assert.throws(() => assertRawEvidenceDisplay(display, "capture", changed), RawEvidenceDisplayChanged, `parser_identity.${key}`);
  }
  assert.throws(() => assertRawEvidenceDisplay(display, "vehicle", original), RawEvidenceDisplayChanged);
  assert.throws(() => assertRawEvidenceDisplay(display, "capture", { ...original, query: { ...original.query, keys: ["rear", "front"] } }), RawEvidenceDisplayChanged);
  assert.throws(() => assertRawEvidenceDisplay(display, "capture", { ...original, parse_provenance: { ...original.parse_provenance, mapping_id: "mapping@2" } }), RawEvidenceDisplayChanged);
  assert.notEqual(rawEvidenceCanonical({ field: null }), rawEvidenceCanonical({}));
  for (const invalid of [undefined, NaN, Infinity, { omitted: undefined }, new Date()]) assert.throws(() => rawEvidenceCanonical(invalid), RawEvidenceDisplayChanged);
});

test("Golden and evaluation capture bindings fail closed for every frozen input field", () => {
  const actual = { ...metadata(), query_id: "query", storage_kind: "object_store" };
  const input: Record<string, unknown> = { capture_id: actual.id, original_parser_version: actual.parser_version };
  for (const key of ["query_id", "source_id", "target_kind", "query", "source_url", "content_type", "raw_hash", "byte_count", "observed_at", "storage_kind"] as const) {
    // target_kind is supplied by the host's frozen input, not guessed from PDF bytes.
    input[key] = key === "target_kind" ? "vehicle" : actual[key as keyof typeof actual];
  }
  const value = { ...actual, target_kind: "vehicle" };
  assertRawEvidenceInput(value, input);
  for (const key of Object.keys(input)) {
    assert.throws(() => assertRawEvidenceInput(value, { ...input, [key]: "changed" }), RawEvidenceDisplayChanged, key);
  }
  assert.throws(() => assertRawEvidenceInput(value, {}), RawEvidenceDisplayChanged);
});

function authority() {
  const owner = new AbortController();
  let acceptedOwner = 1;
  let current: RawEvidenceOwner = { ready: true, ownerEpoch: 1, ownerSignal: owner.signal, isCurrentOwner: epoch => epoch === acceptedOwner, selection: "A", transportEpoch: 1 };
  const observers = new Set<() => void>();
  const operations = createRawEvidenceOperations(() => current, callback => { observers.add(callback); return () => { observers.delete(callback); }; });
  return { operations, owner, observers, update(value: Partial<RawEvidenceOwner>) { current = { ...current, ...value }; },
    ownerChange() { acceptedOwner++; }, transportChange() { current.transportEpoch++; for (const callback of [...observers]) callback(); } };
}

test("each owner, selection, generation, controller and transport fence is synchronous", () => {
  const changes: [string, (a: ReturnType<typeof authority>, operation: ReturnType<ReturnType<typeof authority>["operations"]["begin"]>) => void][] = [
    ["ready", a => a.update({ ready: false })], ["epoch", a => a.update({ ownerEpoch: 2 })],
    ["live owner", a => a.ownerChange()], ["ownerSignal", a => a.update({ ownerSignal: new AbortController().signal })],
    ["owner abort", a => a.owner.abort()], ["selection", a => a.update({ selection: "B" })],
    ["controller", (_a, op) => op.controller.abort()], ["transport getter", a => a.update({ transportEpoch: 2 })],
    ["transport observer", a => a.transportChange()], ["close/unmount", a => a.operations.invalidate()],
    ["repeat", a => { a.operations.begin().finish(); }],
  ];
  for (const [name, change] of changes) {
    const a = authority(), operation = a.operations.begin(); operation.fence.assertCurrent(); change(a, operation);
    assert.throws(() => operation.fence.assertCurrent(), RawEvidenceViewChanged, name); operation.finish(); a.operations.invalidate();
    assert.equal(a.observers.size, 0, name);
  }
});

test("A to B to A cannot revive an old controller", () => {
  const a = authority(), old = a.operations.begin();
  a.operations.invalidate(); a.update({ selection: "B" }); a.operations.begin();
  a.operations.invalidate(); a.update({ selection: "A" }); const fresh = a.operations.begin();
  assert.throws(old.fence.assertCurrent, RawEvidenceViewChanged); fresh.fence.assertCurrent(); fresh.finish();
});

test("owner and transport changes release pending picker work in the same stack", () => {
  for (const revoke of [(a: ReturnType<typeof authority>) => a.owner.abort(), (a: ReturnType<typeof authority>) => a.transportChange()]) {
    const a = authority(), operation = a.operations.begin(); let release = 0;
    operation.controller.signal.addEventListener("abort", () => { release++; });
    revoke(a); assert.equal(release, 1); assert.ok(operation.controller.signal.aborted); assert.equal(a.observers.size, 0);
    operation.finish(); assert.equal(release, 1);
  }
  const a = authority(); a.owner.abort(); assert.throws(() => a.operations.begin(), RawEvidenceViewChanged);
});

test("late read/content/arrayBuffer/digest/save stages cannot authorize a stale result", async () => {
  for (const stage of ["read", "content", "arrayBuffer", "digest", "save"]) {
    const a = authority(), operation = a.operations.begin(); let complete!: () => void, saved = 0;
    const pending = new Promise<void>(resolve => { complete = resolve; });
    const result = (async () => { operation.fence.assertCurrent(); await pending; operation.fence.assertCurrent(); saved++; })();
    a.operations.invalidate(); complete(); await assert.rejects(result, RawEvidenceViewChanged, stage); assert.equal(saved, 0, stage);
  }
});

function browser() {
  const calls = { created: 0, clicked: 0, removed: 0, revoked: 0, delayed: [] as (() => void)[] };
  const environment: BrowserDownloadEnvironment = {
    createObjectURL: () => { calls.created++; return "blob:owned"; }, revokeObjectURL: url => { assert.equal(url, "blob:owned"); calls.revoked++; },
    createLink: () => ({ href: "", download: "", click() { calls.clicked++; }, remove() { calls.removed++; } }),
    appendLink: () => {}, deferRevoke: callback => { calls.delayed.push(callback); },
  };
  return { calls, environment };
}
test("final browser assert failure removes the link and revokes the URL with no click", () => {
  const b = browser(); let checks = 0;
  assert.throws(() => deliverBrowserRawDownload({ blob: new Blob(["pdf"]), filename: "file.pdf", assertCurrent() { if (++checks === 2) throw new RawEvidenceViewChanged(); } }, b.environment), RawEvidenceViewChanged);
  assert.deepEqual({ ...b.calls, delayed: b.calls.delayed.length }, { created: 1, clicked: 0, removed: 1, revoked: 1, delayed: 0 });
});
test("browser creation/append failures cannot leak an owned URL", () => {
  for (const stage of ["createLink", "appendLink"] as const) {
    const b = browser(); b.environment[stage] = () => { throw new Error(stage); };
    assert.throws(() => deliverBrowserRawDownload({ blob: new Blob(), filename: "f.pdf" }, b.environment));
    assert.equal(b.calls.clicked, 0); assert.equal(b.calls.revoked, 1);
  }
});
test("browser success preserves delayed revocation; aborted signal never creates a URL", () => {
  const b = browser(); const download = { blob: new Blob(["bytes"]), filename: "file.pdf" };
  assert.deepEqual(deliverBrowserRawDownload(download, b.environment), { saved: true });
  assert.equal(b.calls.clicked, 1); assert.equal(b.calls.removed, 1); assert.equal(b.calls.revoked, 0);
  b.calls.delayed[0](); assert.equal(b.calls.revoked, 1);
  const aborted = browser(); assert.throws(() => deliverBrowserRawDownload({ ...download, signal: AbortSignal.abort() }, aborted.environment));
  assert.equal(aborted.calls.created, 0);
});
