// SDK and display boundary tests only; no browser, native host or real HTTP.
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const { fieldDefaultText, fieldValueText } = await loadTypeScript("../apps/web/components/field-authority-values.ts", import.meta.url);
const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const desktop = await loadTypeScript("../apps/desktop/src/native-platform.ts", import.meta.url);
const { createMobileInvoke } = await loadTypeScript("../apps/mobile/src/native-platform.ts", import.meta.url);

test("equal-rank and unavailable fields never display a supplied raw value as default", () => {
  for (const state of ["conflict_tied", "unknown", "unavailable"]) {
    const value = fieldDefaultText({ state, has_default: false, default_value: 987654321, unit: "dB" });
    assert.match(value, /暂无默认值/);
    assert.doesNotMatch(value, /987654321/);
  }
});

test("false, zero, numeric strings and measurements remain distinct display evidence", () => {
  assert.equal(fieldDefaultText({ state: "uncontested", has_default: true, default_value: false }), "否（false）");
  assert.equal(fieldDefaultText({ state: "uncontested", has_default: true, default_value: 0, unit: "dB" }), "0 dB");
  assert.notEqual(fieldValueText("300"), fieldValueText(300));
  assert.notEqual(fieldValueText(null), fieldValueText(false));
  assert.notEqual(fieldValueText({ value: 8, unit: "mm" }), fieldValueText({ value: 8, unit: "in" }));
});

const variantId = "323e4567-e89b-42d3-a456-426614174000";
const policy = { version: "field-authority@1", digest: "c".repeat(64) };
const resolution = { policy, variant_id: variantId, scope: "history", data_state: "local_snapshot", fingerprint: "d".repeat(64),
  fields: [{ field: "utqg_treadwear", label: "UTQG 磨耗指数", unit: "", category: "utqg", identity_bound: false,
    source_scope_only: false, state: "conflict_tied", has_default: false, default_value: null, default_candidate_ids: [],
    candidates: [], reasons: ["同级来源仍有不同取值，全部记录保留 🚗"] }], notice: "不改写来源与旧引用" };
const catalog = { policy, fields: [], information_categories: [], criteria: ["字段权威等级"], coverage: "已登记参数", notice: "只读规则" };
const page = { policy, data_state: "local_snapshot", scope: "history", items: [resolution], offset: 20, limit: 20, total: 21,
  filters: { field: "utqg_treadwear", source_id: "厂商 & 区域" }, notice: "保留所有来源" };

test("field authority SDK keeps read-only paths and exact frozen DTOs across JavaScript transports", async t => {
  for (const host of ["browser", "shared-native", "desktop-adapter", "mobile-adapter"]) {
    await t.test(host, async () => {
      const originalFetch = globalThis.fetch;
      const calls = [];
      let restore;
      const route = request => {
        calls.push(request);
        assert.equal(request.method, "GET");
        assert.equal(request.body, undefined);
        if (request.path === "/v1/field-policies") return catalog;
        if (request.path === `/v1/tire-variants/${variantId}/field-resolution?mode=history`) return resolution;
        assert.equal(request.path, `/v1/field-conflicts?mode=history&offset=20&limit=20&field=utqg_treadwear&source_id=${encodeURIComponent("厂商 & 区域")}`);
        return page;
      };
      const invoke = async (command, { request }) => {
        assert.equal(command, "api_request");
        const value = route({ ...request, body: request.body_base64 });
        return { status: 200, headers: { "content-type": "application/json" }, body_base64: Buffer.from(JSON.stringify(value), "utf8").toString("base64") };
      };
      try {
        if (host === "browser") {
          globalThis.fetch = async (path, init) => {
            assert.ok(path.startsWith("/api/"));
            assert.equal(init.cache, "no-store");
            assert.equal(init.credentials, "include");
            return new Response(JSON.stringify(route({ path: path.slice(4), method: init.method || "GET", body: init.body })), { headers: { "content-type": "application/json" } });
          };
        } else {
          globalThis.fetch = async () => { assert.fail("native path reached browser fetch"); };
          restore = sdk.setApiTransport(host === "desktop-adapter" ? desktop.createNativeTransport(invoke)
            : host === "mobile-adapter" ? native.createNativeTransport(createMobileInvoke({ apiRequest: options => invoke("api_request", options) }))
              : native.createNativeTransport(invoke));
        }
        assert.deepEqual(await sdk.tireApi.fieldPolicies(), catalog);
        assert.deepEqual(await sdk.tireApi.fieldConflicts({ field: "utqg_treadwear", source_id: "厂商 & 区域" }, 20), page);
        assert.deepEqual(await sdk.tireApi.fieldResolution(variantId), resolution);
        assert.equal(calls.length, 3);
      } finally { restore?.(); globalThis.fetch = originalFetch; }
    });
  }
});
