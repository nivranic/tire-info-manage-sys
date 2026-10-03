// SDK/JavaScript IPC serialization acceptance only: no real HTTP, native host or device.
// Run in the coordinator's test window: node --test scripts/identity_contract_transport_qa.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const shared = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const desktop = await loadTypeScript("../apps/desktop/src/native-platform.ts", import.meta.url);
const mobile = await loadTypeScript("../apps/mobile/src/native-platform.ts", import.meta.url);
const key = "123e4567-e89b-42d3-a456-426614174000";
const applicationId = "223e4567-e89b-42d3-a456-426614174000";
const variantId = "323e4567-e89b-42d3-a456-426614174000";
const base = "/v1/identity-contract";
const summary = { legacy_total: 1, eligible: 0, needs_review: 1, already_bound: 0, watch_risk_count: 1, rule_risk_count: 0 };
const assessment = { variant_id: variantId, state: "needs_review", reason_codes: ["unknown_namespace"],
  current_identity: null, current_key: null, identity_status: null, proof_fingerprint: "a".repeat(64),
  affected_watch_count: 1, affected_rule_count: 0 };
const preview = { scope: "local_workspace", data_state: "local_snapshot", schema: "variant-identity@2",
  contract_digest: "b".repeat(64), revision: 7, preview_fingerprint: "c".repeat(64), summary,
  items: [assessment], can_apply: true, notice: "旧身份需核对，保留原始 UUID 🚗" };
const payload = { mode: "history", schema: preview.schema, expected_revision: preview.revision,
  expected_preview_fingerprint: preview.preview_fingerprint, acknowledged: true,
  operator: "迁移验证员 🚗", reason: "保留中文、换行\n与未确认命名空间" };
const application = { id: applicationId, revision: 8, schema: preview.schema, contract_digest: preview.contract_digest,
  preview_fingerprint: preview.preview_fingerprint, fingerprint: "d".repeat(64), summary, assessments: [assessment],
  binding_ids: [], operator: payload.operator, reason: payload.reason, created_at: "2026-10-01T00:00:00Z",
  idempotent_replay: false, current_revision: 8 };
const history = { items: [application], total: 11, offset: 10, limit: 10 };
const conflict = { detail: { code: "identity_migration_revision_conflict", message: "迁移修订已改变，请重新读取预览。" } };
const bytes = value => Buffer.from(JSON.stringify(value), "utf8");

test("identity migration SDK preserves contract fields through browser and JavaScript native adapters", async t => {
  for (const host of ["browser", "shared-native", "desktop-adapter", "mobile-adapter"]) {
    await t.test(host, async () => {
      const originalFetch = globalThis.fetch;
      const calls = [];
      let restore;
      let returnConflict = false;
      const reply = request => {
        calls.push(request);
        if (request.path === `${base}/migration-preview?mode=history`) return [200, preview];
        if (request.path === `${base}/migration-applications?mode=history&offset=10&limit=10`) return [200, history];
        if (request.path === `${base}/migration-applications/${applicationId}?mode=history`) return [200, application];
        assert.equal(request.path, `${base}/migration-applications`);
        assert.equal(request.method, "POST");
        assert.equal(request.headers["content-type"], "application/json");
        assert.equal(request.headers["idempotency-key"], key);
        assert.deepEqual(JSON.parse(request.body.toString("utf8")), payload);
        assert.deepEqual(request.body, bytes(payload), "UTF-8 request bytes must survive the adapter");
        return returnConflict ? [409, conflict] : [201, application];
      };
      const invoke = async (command, { request }) => {
        assert.equal(command, "api_request");
        assert.match(request.id, /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i);
        assert.notEqual(request.id, key, "transport cancellation id must not replace the fixed migration key");
        const [status, value] = reply({ ...request,
          body: request.body_base64 === undefined ? undefined : Buffer.from(request.body_base64, "base64") });
        return { status, headers: { "content-type": "application/json" }, body_base64: bytes(value).toString("base64") };
      };
      try {
        if (host === "browser") {
          globalThis.fetch = async (path, init) => {
            assert.ok(path.startsWith("/api/"));
            assert.equal(init.credentials, "include");
            assert.equal(init.cache, "no-store");
            const [status, value] = reply({ path: path.slice(4), method: init.method || "GET",
              headers: Object.fromEntries(new Headers(init.headers)),
              body: init.body === undefined ? undefined : Buffer.from(init.body, "utf8") });
            return new Response(bytes(value), { status, headers: { "content-type": "application/json" } });
          };
        } else {
          globalThis.fetch = async () => { assert.fail("native SDK path must not fall back to browser fetch"); };
          const transport = host === "desktop-adapter" ? desktop.createNativeTransport(invoke)
            : host === "mobile-adapter" ? shared.createNativeTransport(mobile.createMobileInvoke({
              apiRequest: options => invoke("api_request", options),
            })) : shared.createNativeTransport(invoke);
          restore = sdk.setApiTransport(transport);
        }
        assert.deepEqual(await sdk.tireApi.identityMigrationPreview(), preview);
        assert.deepEqual(await sdk.tireApi.applyIdentityMigration(payload, key), application);
        assert.deepEqual(await sdk.tireApi.identityMigrationApplications(10), history);
        assert.deepEqual(await sdk.tireApi.identityMigrationApplication(applicationId), application);
        returnConflict = true;
        await assert.rejects(sdk.tireApi.applyIdentityMigration(payload, key), error =>
          error instanceof sdk.ApiError && error.status === 409
          && error.code === conflict.detail.code && error.message === conflict.detail.message);
        assert.equal(calls.length, 5, "a conflict must not trigger automatic migration retries");
        assert.equal(calls.filter(call => call.method === "POST").length, 2);
      } finally {
        restore?.();
        globalThis.fetch = originalFetch;
      }
    });
  }
});
