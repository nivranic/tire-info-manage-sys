// Pure client contract checks: no database, Worker, browser or network.
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const values = await loadTypeScript("../apps/web/components/recall-discovery-values.ts", import.meta.url);
const taskValues = await loadTypeScript("../apps/web/components/task-center-values.ts", import.meta.url);
const coverage = (patch = {}) => ({ status: "complete", passes_required: 2, passes_completed: 2,
  pass_fingerprints: ["synthetic-content", "synthetic-content"], page_operations: 4, pages_completed: 4,
  products_count: 11, candidates_count: 2, new_candidates_count: 1, raw_bytes: 14000, elapsed_seconds: 9,
  budget: { max_pages_per_pass: 20, max_products_per_pass: 200, required_passes: 2, max_page_operations: 40,
    max_elapsed_seconds: 300, max_raw_bytes: 67108864, lease_seconds: 600 }, baseline_advanced: true,
  is_initial_baseline: false, ...patch });
const run = (patch = {}) => ({ id: "run-one", job_id: "job-one", attempt_id: "attempt-one", state: "discovery_complete",
  reason: null, started_at: "2026-10-01T01:00:00Z", finished_at: "2026-10-01T01:00:09Z",
  previous_complete_id: "baseline-one", coverage: coverage(), ...patch });

test("name targets normalize whitespace without inventing exact brand matching or an offset", () => {
  assert.equal(values.normalizeDiscoverySearch("  GENERAL   AltiMAX\n RT43 "), "GENERAL AltiMAX RT43");
  assert.equal(values.validDiscoverySearch("  "), false);
  assert.equal(values.validDiscoverySearch("x\0y"), false);
  assert.equal(values.validDiscoverySearch("x".repeat(121)), false);
  assert.equal(values.validDiscoverySearch("品牌 型号"), true);
  assert.equal(values.discoveryCampaignValid("23T001000"), true);
  assert.equal(values.discoveryCampaignValid("javascript:alert(1)"), false);
});

test("a first page or inconsistent second pass can never be presented as complete coverage", () => {
  assert.equal(values.discoveryCoverageComplete(coverage()), true);
  for (const change of [{ status: "incomplete" }, { passes_completed: 1 },
    { pass_fingerprints: ["a", "b"] }, { pass_fingerprints: ["same"] }, { pass_fingerprints: ["", ""] }]) {
    assert.equal(values.discoveryCoverageComplete(coverage(change)), false);
    assert.match(values.discoveryNoticeHeading(run({ coverage: coverage(change) })), /不推进基线.*不产生新增候选提醒/);
  }
});

test("first complete baseline, later new candidates and no-new runs have distinct truthful labels", () => {
  const baseline = run({ coverage: coverage({ is_initial_baseline: true, new_candidates_count: 0 }), previous_complete_id: null });
  assert.equal(values.discoveryRunLabel(baseline), "已建立首次完整基线");
  assert.match(values.discoveryNoticeHeading(baseline), /不批量发送已有候选提醒/);
  assert.match(values.discoveryNoticeHeading(run()), /新增观察 1 个候选，不代表官方刚发布/);
  assert.match(values.discoveryNoticeHeading(run({ coverage: coverage({ new_candidates_count: 0 }) })), /不代表没有召回/);
  assert.match(values.discoveryRunLabel(run({ state: "source_unavailable", coverage: coverage({ status: "incomplete" }) })), /来源不可用.*不完整/);
  assert.match(values.discoveryReason("discovery_scope_budget_exceeded"), /缩小关键词/);
  assert.match(values.discoveryReason("discovery_content_changed"), /两遍/);
});

test("discovery task query, outcome and scope stay distinct from adopted campaign/tire facts", () => {
  const task = { kind: "recall_discovery", job_id: "job-one", scope: "session", query: { search: "MODEL & BRAND" }, state: "failed", rules: [] };
  const detail = { schema: "monitor-tasks@1", task, attempts: [], legacy_runs: [], cursor: "opaque" };
  assert.equal(taskValues.taskProjectionMatches(detail, "recall_discovery", "job-one"), true);
  assert.equal(taskValues.taskProjectionMatches({ ...detail, task: { ...task, scope: "local_workspace" } }, "recall_discovery", "job-one"), false);
  assert.equal(taskValues.taskQueryLabel(task), "名称关键词：MODEL & BRAND");
  assert.equal(taskValues.taskKindLabels.recall_discovery, "召回名称发现监控");
  assert.match(taskValues.taskResultLabel("discovery_complete"), /尚未核验公告/);
  assert.match(taskValues.taskResultLabel("discovery_incomplete"), /不推进基线/);
});

test("browser and native expose the same rule, coverage, notification and opaque-cursor contract", async t => {
  for (const host of ["browser", "native"]) await t.test(host, async () => {
    const originalFetch = globalThis.fetch; const calls = []; let restore;
    const writeResult = { id: "rule-one", revision: 3, write_result: { revision_id: "revision-one", revision: 1, replayed: true } };
    function respond(path, method, headers, body) {
      calls.push({ path, method, headers, body });
      return method === "POST" ? writeResult : { scope: "session", items: [], total: 0, offset: 0, limit: 20 };
    }
    try {
      if (host === "browser") globalThis.fetch = async (path, init) => new Response(JSON.stringify(respond(path.slice(4), init.method || "GET", Object.fromEntries(new Headers(init.headers)), init.body ? JSON.parse(init.body) : undefined)), { headers: { "Content-Type": "application/json" } });
      else {
        globalThis.fetch = async () => assert.fail("native used browser networking");
        restore = sdk.setApiTransport(native.createNativeTransport(async (command, { request }) => {
          assert.equal(command, "api_request");
          const body = request.body_base64 ? JSON.parse(Buffer.from(request.body_base64, "base64").toString("utf8")) : undefined;
          const result = respond(request.path, request.method, request.headers, body);
          return { status: 200, headers: { "content-type": "application/json" }, body_base64: Buffer.from(JSON.stringify(result)).toString("base64") };
        }));
      }
      const key = "0b593fb4-a372-4680-ae16-e8ae478b8b4b";
      const settings = { name: "中文名称规则", enabled: false, interval_seconds: 21600 };
      const first = await sdk.tireApi.createDiscoveryRule({ search: "MODEL & BRAND" }, settings, undefined, key);
      const repeated = await sdk.tireApi.createDiscoveryRule({ search: "MODEL & BRAND" }, settings, undefined, key);
      assert.deepEqual(first, repeated);
      assert.equal(first.revision, 3); assert.equal(first.write_result.revision, 1, "latest state must not replace original write result");
      assert.deepEqual(calls[0], calls[1], "retry preserves UUID and exact payload");
      assert.equal(calls[0].headers["idempotency-key"], key);
      assert.deepEqual(calls[0].body.query, { search: "MODEL & BRAND" });
      assert.equal(calls[0].body.enabled, false);
      await sdk.tireApi.reviseDiscoveryRule("rule / one", 3, { ...settings, enabled: true, archived: false }, undefined, key);
      assert.equal(calls[2].method, "POST"); assert.equal(calls[2].body.expected_revision, 3);
      assert.equal(calls[2].headers["idempotency-key"], key);
      assert.match(calls[2].path, /rule%20%2F%20one\/revisions$/);
      await sdk.tireApi.discoveryRules(true, 20);
      await sdk.tireApi.discoveryRule("rule / one");
      await sdk.tireApi.discoveryRuns("job / one", 20);
      await sdk.tireApi.discoveryRun("run / one", 20);
      await sdk.tireApi.discoveryNotifications(true, 20);
      await sdk.tireApi.monitorTask("recall_discovery", "job / one");
      await sdk.tireApi.monitorTaskEvents("recall_discovery", "job / one", "opaque +/=");
      const reads = calls.slice(3);
      assert.ok(reads.every(call => call.method === "GET" && call.body === undefined));
      assert.match(reads[0].path, /archived=true&offset=20&limit=20/);
      assert.match(reads[1].path, /rule%20%2F%20one\?mode=history/);
      assert.match(reads[2].path, /job_id=job\+%2F\+one&mode=history&offset=20&limit=20/);
      assert.match(reads[3].path, /run%20%2F%20one\?mode=history&page_offset=20&page_limit=20/);
      assert.match(reads[4].path, /unread_only=true&offset=20&limit=20/);
      assert.match(reads[6].path, /recall_discovery\/job%20%2F%20one\/events\?cursor=opaque\+%2B%2F%3D&limit=50/);
      assert.ok(!calls.some(call => /\/live-query|\/recalls\/search|\/stream/.test(call.path)), "opening records must not start a source query or native SSE");
      await sdk.tireApi.markDiscoveryNotification("notice / one", true);
      assert.match(calls.at(-1).path, /notice%20%2F%20one\/read$/);
      assert.equal(calls.at(-1).method, "POST"); assert.deepEqual(calls.at(-1).body, { read: true });
    } finally { restore?.(); globalThis.fetch = originalFetch; }
  });
});

test("new discovery kind streams read-only through the existing Web protocol", async () => {
  const originalFetch = globalThis.fetch;
  const cursor = "task-bound-discovery-cursor";
  try {
    globalThis.fetch = async (path, init) => {
      assert.match(path, /\/recall_discovery\/job-one\/events\/stream\?/);
      assert.equal(init.method, undefined);
      assert.equal(init.headers.get("accept"), "text/event-stream");
      return new Response(`event: stream_end\ndata: ${JSON.stringify({ cursor, server_time: "2026-10-01T01:00:00Z", reason: "window_complete" })}\n\n`, { headers: { "Content-Type": "text/event-stream" } });
    };
    const messages = [];
    assert.equal(await sdk.tireApi.streamMonitorTaskEvents("recall_discovery", "job-one", cursor, message => messages.push(message)), "window_complete");
    assert.equal(messages[0].data.cursor, cursor);
  } finally { globalThis.fetch = originalFetch; }
});
