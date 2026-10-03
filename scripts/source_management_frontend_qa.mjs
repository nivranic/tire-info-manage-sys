// Source contract and transport tests only: no browser, HTTP, database or Parser.
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const values = await loadTypeScript("../apps/web/components/source-management-values.ts", import.meta.url);
const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const before = { state: "enabled", notes: "保留原备注", access_generation: 3 };
const after = { ...before, state: "paused", access_generation: 4 };
const source = { source_id: "michelin-us", registered_status: "ready", management: { ...before, revision: 7 }, can_fetch: true, fingerprint: "a".repeat(64) };
const intent = { action: "pause" };
const preview = { source_id: source.source_id, source, action: intent.action, revision: 7, fingerprint: "b".repeat(64), before, after };
const attempt = { sourceId: source.source_id, key: "2e94f7df-2b77-4614-b8b0-dd0eaf9df414", before, after, payload: { action: "pause", expected_revision: 7, expected_fingerprint: preview.fingerprint, operator: "本地研究员", reason: "本次核对暂停在线采集" } };
const event = { id: "event-8", source_id: source.source_id, revision: 8, action: "pause", idempotency_key: attempt.key, before, after, ...after, operator: attempt.payload.operator, reason: attempt.payload.reason };

test("preview binds the source fingerprint separately from the action fingerprint", () => {
  assert.equal(values.matchesSourceSettingPreview(preview, source, intent), true);
  assert.equal(values.matchesSourceSettingPreview({ ...preview, source: { ...source, fingerprint: "c".repeat(64) } }, source, intent), false);
  assert.equal(values.matchesSourceSettingPreview({ ...preview, revision: 8 }, source, intent), false);
  assert.equal(values.matchesSourceSettingPreview({ ...preview, action: "edit_notes", after: { ...after, notes: "" } }, source, { action: "edit_notes", notes: "" }), true);
});
test("replay validates the original event while allowing a newer current source projection", () => {
  const result = { event, replayed: true, source: { ...source, management: { ...before, revision: 12, access_generation: 6 } } };
  assert.equal(values.matchesSourceSettingAttempt(result, attempt), true);
  for (const change of [{ idempotency_key: "wrong-key" }, { source_id: "eprel" }, { action: "enable" }, { revision: 9 }, { reason: "other" }, { after: before }]) {
    assert.equal(values.matchesSourceSettingAttempt({ ...result, event: { ...event, ...change } }, attempt), false);
  }
  assert.equal(values.matchesSourceSettingAttempt({ ...result, source: { ...source, management: { ...before, revision: 6 } } }, attempt), false);
});
test("enabled intent never grants missing capability or bypasses stale directory", () => {
  assert.equal(values.canFetchSource(source, true), true);
  assert.equal(values.canFetchSource(source, false), false);
  assert.equal(values.canFetchSource(undefined, true), false);
  assert.equal(values.canFetchSource({ ...source, source_id: "eprel", registered_status: "configuration_required", can_fetch: false }, true), false);
  for (const state of ["paused", "archived"]) assert.equal(values.canFetchSource({ ...source, management: { ...source.management, state } }, true), false);
});
test("notes-only revisions retain active access generation; pause or archive invalidates it", () => {
  assert.equal(values.sourceAccessChanged(source, { ...source, management: { ...source.management, notes: "新备注", revision: 8 } }), false);
  assert.equal(values.sourceAccessChanged(source, { ...source, management: { ...after, revision: 8 } }), true);
});
test("Parser pause retains the old query/ask route; old consent checks only management state", () => {
  const parserPaused = { ...source, can_fetch: false, effective_status: "parser_paused", blockers: ["parser_deployment_paused"] };
  assert.equal(values.canFetchSource(parserPaused, true), false);
  assert.equal(values.canQuerySource(parserPaused, true), true);
  assert.equal(values.hasSourceManagementAccess(parserPaused, true), true);
  const environmentDisabled = { ...parserPaused, environment_disabled: true };
  assert.equal(values.canQuerySource(environmentDisabled, true), false);
  assert.equal(values.hasSourceManagementAccess(environmentDisabled, true), true);
  for (const state of ["paused", "archived"]) {
    const blocked = { ...parserPaused, management: { ...before, state } };
    assert.equal(values.canQuerySource(blocked, true), false);
    assert.equal(values.hasSourceManagementAccess(blocked, true), false);
  }
  assert.equal(values.hasSourceManagementAccess(parserPaused, false), false);
  assert.equal(values.canQuerySource({ ...source, registered_status: "configuration_required", can_fetch: false }, true), false);
});

test("source management SDK uses bounded paths and replays exact payload and UUID on both transports", async t => {
  for (const host of ["browser", "native"]) await t.test(host, async () => {
    const calls = [];
    const originalFetch = globalThis.fetch;
    let restore;
    const result = { event, source: { ...source, management: { ...after, revision: 8 } }, replayed: true };
    function route(path, method, body, headers) {
      calls.push({ path, method, body, headers });
      if (path.endsWith("/revisions")) return result;
      if (path.endsWith("/preview")) return preview;
      if (path.includes("/history?")) return { scope: "local_workspace", source_id: source.source_id, items: [event], total: 1, offset: 20, limit: 10 };
      if (path === "/v1/source-settings") return { scope: "local_workspace", items: [source], total: 1 };
      return source;
    }
    try {
      if (host === "browser") globalThis.fetch = async (path, init) => {
        assert.equal(init.cache, "no-store"); assert.equal(init.credentials, "include");
        return new Response(JSON.stringify(route(path.slice(4), init.method || "GET", init.body, Object.fromEntries(init.headers))), { headers: { "Content-Type": "application/json" } });
      };
      else {
        globalThis.fetch = async () => assert.fail("native used browser network");
        restore = sdk.setApiTransport(native.createNativeTransport(async (command, { request }) => {
          assert.equal(command, "api_request");
          const body = request.body_base64 ? Buffer.from(request.body_base64, "base64").toString("utf8") : undefined;
          return { status: 200, headers: { "content-type": "application/json" }, body_base64: Buffer.from(JSON.stringify(route(request.path, request.method, body, request.headers))).toString("base64") };
        }));
      }
      await sdk.tireApi.sourceSettings();
      await sdk.tireApi.sourceSetting("regional / source");
      await sdk.tireApi.sourceSettingHistory(source.source_id, 20);
      await sdk.tireApi.previewSourceSetting(source.source_id, intent);
      assert.deepEqual(await sdk.tireApi.reviseSourceSetting(source.source_id, attempt.payload, attempt.key), result);
      assert.deepEqual(await sdk.tireApi.reviseSourceSetting(source.source_id, attempt.payload, attempt.key), result);
      assert.equal(calls[1].path, "/v1/source-settings/regional%20%2F%20source");
      assert.equal(calls[2].path, "/v1/source-settings/michelin-us/history?offset=20&limit=10");
      assert.equal(calls[3].method, "POST"); assert.deepEqual(JSON.parse(calls[3].body), intent);
      assert.equal(calls[4].method, "POST"); assert.equal(calls[4].headers["idempotency-key"], attempt.key);
      assert.deepEqual(calls[4], calls[5]); assert.deepEqual(JSON.parse(calls[4].body), attempt.payload);
      assert.equal(calls.length, 6);
    } finally { restore?.(); globalThis.fetch = originalFetch; }
  });
});
