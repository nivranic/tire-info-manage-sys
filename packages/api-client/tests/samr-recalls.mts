/** Synthetic SDK contracts. Real source and browser acceptance are recorded separately. */
import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { SamrMonitorQuery, SamrRecallDocument, SamrRecallEvidence, SamrRecallQuery, SamrRecallResult } from "@tire/domain-types";

const search = { operation: "search", keyword: "轮胎 & 召回", page: "4" } as const;
const notice = { operation: "notice", reference: "/zhxx/jdczh/jdczh/art/2021/art_" + "a".repeat(32) + ".html?type=nFZcuWzfh2c41ylKrWj7k" } as const;
// @ts-expect-error A search requires its exact page and keyword.
const missingSearch: SamrRecallQuery = { operation: "search", keyword: "轮胎" };
// @ts-expect-error A notice query uses the source-native reference.
const wrongNotice: SamrRecallQuery = { operation: "notice", keyword: "轮胎", page: "1" };
// @ts-expect-error Notice documents require their full notice payload.
const wrongDocument: SamrRecallDocument = { operation: "notice", notices: [], notice: null };

for (const query of [search, notice]) {
  test(`SAMR ${query.operation} sends the exact online query and forwards cancellation`, async () => {
    const controller = new AbortController();
    const response = { query, source_id: "samr-cn-recalls", data_state: "consent_required", query_id: "synthetic-query", document: null } satisfies Partial<SamrRecallResult>;
    const restore = setApiTransport(async (path, init) => {
      assert.equal(path, "/v1/samr-recalls/query");
      assert.equal(init.method, "POST");
      assert.equal(init.signal, controller.signal);
      assert.deepEqual(JSON.parse(String(init.body)), { query });
      return Response.json(response);
    });
    try { assert.deepEqual(await tireApi.samrRecallQuery(query, {}, controller.signal), response); }
    finally { restore(); }
  });

  test(`SAMR ${query.operation} history encodes native values with explicit history mode`, async () => {
    const controller = new AbortController();
    const restore = setApiTransport(async (path, init) => {
      const url = new URL(path, "https://synthetic.invalid");
      assert.equal(url.pathname, "/v1/samr-recalls/history");
      assert.deepEqual(Object.fromEntries(url.searchParams), { ...query, mode: "history" });
      assert.equal(init.method, undefined);
      assert.equal(init.body, undefined);
      assert.equal(init.signal, controller.signal);
      return Response.json({ query, data_state: "local_snapshot" });
    });
    try { assert.equal((await tireApi.samrRecallHistory(query, controller.signal)).data_state, "local_snapshot"); }
    finally { restore(); }
  });
}

test("SAMR online request preserves single-use consent and an explicit fallback refusal", async () => {
  const calls: unknown[] = [];
  const restore = setApiTransport(async (_path, init) => {
    calls.push(JSON.parse(String(init.body)));
    return Response.json({ data_state: "source_unavailable" });
  });
  try {
    await tireApi.samrRecallQuery(notice, { consent_id: "synthetic-once" });
    await tireApi.samrRecallQuery(search, { fallback_policy: "never" });
    assert.deepEqual(calls, [{ query: notice, consent_id: "synthetic-once" }, { query: search, fallback_policy: "never" }]);
  } finally { restore(); }
});

test("SAMR evidence recovery preserves the stored body, hashes and access basis", async () => {
  const controller = new AbortController();
  const evidence = { id: "synthetic/id?", query: notice, body: "<script>synthetic evidence</script>",
    content_type: "text/html", data_state: "local_snapshot", raw_hash: "a".repeat(64),
    access_basis: { kind: "official_public_recall_pages", homepage: "https://www.samrdprc.org.cn/",
      redistribution_license: "unverified", ai_provider_use: "requires_separate_authorization" } } satisfies Partial<SamrRecallEvidence>;
  const restore = setApiTransport(async (path, init) => {
    assert.equal(path, "/v1/samr-recalls/evidence/synthetic%2Fid%3F?mode=history");
    assert.equal(init.signal, controller.signal);
    return Response.json(evidence);
  });
  try { assert.deepEqual(await tireApi.samrRecallEvidence(evidence.id, controller.signal), evidence); }
  finally { restore(); }
});

test("SAMR HTTP failures propagate without reading history", async () => {
  let calls = 0;
  const restore = setApiTransport(async () => { calls++; return Response.json({ detail: "source_access_changed" }, { status: 409 }); });
  try {
    await assert.rejects(tireApi.samrRecallQuery(search), error => error instanceof ApiError && error.status === 409);
    assert.equal(calls, 1);
  } finally { restore(); }
});

test("SAMR cancellation ends the current request without a fallback read", async () => {
  const controller = new AbortController();
  let calls = 0;
  const restore = setApiTransport(async (_path, init) => {
    calls++;
    return new Promise<Response>((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("Cancelled", "AbortError")), { once: true }));
  });
  try {
    const pending = tireApi.samrRecallQuery(search, {}, controller.signal);
    controller.abort();
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(calls, 1);
  } finally { restore(); }
});

test("SAMR article history forwards a fixed page range and cancellation", async () => {
  const controller = new AbortController();
  const identity = "a".repeat(32);
  const restore = setApiTransport(async (path, init) => {
    const url = new URL(path, "https://synthetic.invalid");
    assert.equal(url.pathname, `/v1/samr-recalls/notices/${identity}/history`);
    assert.deepEqual(Object.fromEntries(url.searchParams), { mode: "history", offset: "10", limit: "5", through_sequence: "23" });
    assert.equal(init.signal, controller.signal);
    assert.equal(init.body, undefined);
    return Response.json({ article_id: identity, through_sequence: 23, observations: [] });
  });
  try { assert.equal((await tireApi.samrNoticeHistory(identity, { offset: 10, limit: 5, through_sequence: 23 }, controller.signal)).through_sequence, 23); }
  finally { restore(); }
});

test("SAMR article history has bounded defaults and path-encodes its identity", async () => {
  const restore = setApiTransport(async path => {
    assert.equal(path, "/v1/samr-recalls/notices/synthetic%2Fid%3F/history?mode=history&offset=0&limit=10");
    return Response.json({ data_state: "local_snapshot", observations: [] });
  });
  try { assert.equal((await tireApi.samrNoticeHistory("synthetic/id?")).data_state, "local_snapshot"); }
  finally { restore(); }
});

test("SAMR monitor writes preserve scope, revision, idempotency and cancellation", async () => {
  const query: SamrMonitorQuery = { operation: "search", keyword: "轮胎", page_limit: 4, notice_limit: 60, text: "批次" };
  const controller = new AbortController();
  const settings = { name: "Synthetic monitor", enabled: true, interval_seconds: 3600 };
  const calls: { path: string; body: unknown }[] = [];
  const restore = setApiTransport(async (path, init) => {
    assert.equal(init.method, "POST");
    assert.equal(init.signal, controller.signal);
    assert.equal(new Headers(init.headers).get("Idempotency-Key"), "synthetic-key");
    calls.push({ path, body: JSON.parse(String(init.body)) });
    return Response.json({ id: "synthetic-rule", write_result: { revision_id: "revision", revision: 2 } });
  });
  try {
    await tireApi.createSamrRule(query, settings, "synthetic-key", controller.signal);
    await tireApi.reviseSamrRule("rule/id?", 1, { ...settings, archived: true }, "synthetic-key", controller.signal);
    assert.deepEqual(calls, [
      { path: "/v1/samr-recall-monitor-rules", body: { query, ...settings } },
      { path: "/v1/samr-recall-monitor-rules/rule%2Fid%3F/revisions", body: { expected_revision: 1, ...settings, archived: true } },
    ]);
  } finally { restore(); }
});

test("SAMR monitor readers preserve explicit history, filters and nullable running-run linkage", async () => {
  const controller = new AbortController();
  const paths: string[] = [];
  const restore = setApiTransport(async (path, init) => {
    paths.push(path);
    assert.equal(init.signal, controller.signal);
    return Response.json({ items: [{ run_id: null, attempt_id: "synthetic-attempt", lag_seconds: 0.5 }] });
  });
  try {
    await tireApi.samrRules(true, 20, controller.signal);
    await tireApi.samrRule("rule/id?", controller.signal);
    await tireApi.samrMonitorRuns("rule/id?", 10, controller.signal);
    const values = await tireApi.samrNotifications(true, 20, controller.signal);
    assert.equal(values.items[0].run_id, null);
    assert.deepEqual(paths, [
      "/v1/samr-recall-monitor-rules?archived=true&offset=20&limit=20",
      "/v1/samr-recall-monitor-rules/rule%2Fid%3F?mode=history",
      "/v1/samr-recall-monitor-rules/rule%2Fid%3F/runs?mode=history&offset=10&limit=10",
      "/v1/samr-recall-notifications?mode=history&unread=true&offset=20&limit=20",
    ]);
  } finally { restore(); }
});

test("SAMR notification read-state and generic task reader use their normal routes", async () => {
  const paths: string[] = [];
  const restore = setApiTransport(async (path, init) => {
    paths.push(path);
    if (init.method === "PUT") assert.deepEqual(JSON.parse(String(init.body)), { read: true });
    return Response.json({ id: "synthetic", read_at: null });
  });
  try {
    await tireApi.markSamrNotification("notice/id?", true);
    await tireApi.monitorTask("samr", "job/id?");
    assert.equal(paths[0], "/v1/samr-recall-notifications/notice%2Fid%3F/read");
    assert.ok(paths[1].startsWith("/v1/monitor-tasks/samr/job%2Fid%3F?"));
  } finally { restore(); }
});
