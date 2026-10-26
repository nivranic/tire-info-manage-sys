/** Handwritten wire responses and injected transport only; no HTTP, DB, Worker or source request. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { SourcePageNotification, SourcePageNotificationDetail, SourcePageNotifications } from "@tire/domain-types";

const instant = "2026-10-25T00:00:00+00:00";
const notice: SourcePageNotification = {
  id: "notice/id?one", rule_id: "page-rule", rule_name: "Synthetic paused-by-default page rule", rule_revision: 2,
  read_at: null, delivered_at: instant,
  event: {
    id: "page-event", kind: "page_changed", source_id: "synthetic-source",
    query: { model: "Synthetic Tire", size: "265/40ZR20" }, source_url: "https://fixture.invalid/accepted-text",
    before: { snapshot_id: "before", verification_id: "verification-before", raw_hash: "a".repeat(64), observed_at: "2026-10-24T22:00:00+00:00", verified_at: "2026-10-24T23:00:00+00:00", parser_version: "synthetic@1" },
    after: { snapshot_id: "after", verification_id: "verification-after", raw_hash: "b".repeat(64), observed_at: instant, verified_at: "2026-10-25T01:00:00+00:00", parser_version: "synthetic@2" },
  },
};
const list: SourcePageNotifications = { scope: "local_workspace", data_state: "local_snapshot", items: [notice], total: 26, offset: 0, limit: 25 };
const detail: SourcePageNotificationDetail = { scope: "local_workspace", data_state: "local_snapshot", item: notice };
type Call = { path: string; init: RequestInit };

function install(value: unknown, status = 200) {
  const calls: Call[] = [];
  const restore = setApiTransport(async (path, init) => {
    calls.push({ path, init }); return Response.json(value, { status });
  });
  return { calls, restore };
}

await test("page history list preserves its independent envelope and exact paging/filter parameters", async () => {
  const transport = install(list), controller = new AbortController();
  try {
    assert.deepEqual(await tireApi.sourcePageNotifications(), list);
    assert.equal(transport.calls[0].path, "/v1/source-page-notifications?mode=history&unread=false&offset=0&limit=25");
    await tireApi.sourcePageNotifications(true, controller.signal, 25, 50);
    const call = transport.calls[1];
    assert.equal(call.path, "/v1/source-page-notifications?mode=history&unread=true&offset=25&limit=50");
    assert.equal(call.init.signal, controller.signal);
    assert.equal(call.init.method, undefined); assert.equal(call.init.body, undefined);
    assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store");
    assert.equal(transport.calls.length, 2);
  } finally { transport.restore(); }
});

await test("page detail uses history and a URL-encoded ID and retains both distinct evidence times", async () => {
  const transport = install(detail), controller = new AbortController();
  try {
    const result = await tireApi.sourcePageNotification(notice.id, controller.signal);
    assert.deepEqual(result, detail);
    assert.equal(transport.calls[0].path, "/v1/source-page-notifications/notice%2Fid%3Fone?mode=history");
    assert.equal(transport.calls[0].init.signal, controller.signal);
    assert.notEqual(result.item.event.before.observed_at, result.item.event.before.verified_at);
    assert.notEqual(result.item.event.after.observed_at, result.item.event.after.verified_at);
    assert.equal("variant_id" in result.item.event, false);
    assert.equal("identity" in result.item, false); assert.equal("changes" in result.item, false);
    assert.equal("body" in result.item.event, false);
  } finally { transport.restore(); }
});

await test("page read/unread sends only the closed read body and does not replay a write", async () => {
  for (const read of [true, false]) {
    const expected = { id: notice.id, read_at: read ? instant : null };
    const transport = install(expected), controller = new AbortController();
    try {
      assert.deepEqual(await tireApi.markSourcePageNotification(notice.id, read, controller.signal), expected);
      const call = transport.calls[0];
      assert.equal(call.path, "/v1/source-page-notifications/notice%2Fid%3Fone/read");
      assert.equal(call.init.method, "PUT"); assert.equal(call.init.signal, controller.signal);
      assert.deepEqual(JSON.parse(String(call.init.body)), { read });
      assert.equal(new Headers(call.init.headers).get("Content-Type"), "application/json");
      assert.equal(transport.calls.length, 1);
    } finally { transport.restore(); }
  }
});

await test("page history fixed errors pass through without choosing another snapshot or replaying", async () => {
  for (const [status, code] of [[503, "source_page_history_invalid"], [404, "source_page_notification_not_found"]] as const) {
    const transport = install({ detail: { code, message: "Synthetic fixed history rejection" } }, status);
    try {
      await assert.rejects(tireApi.sourcePageNotification(notice.id), cause => cause instanceof ApiError && cause.status === status && cause.code === code);
      assert.equal(transport.calls.length, 1);
    } finally { transport.restore(); }
  }
});

await test("each page SDK operation forwards caller cancellation and never retries", async () => {
  const operations = [
    (signal: AbortSignal) => tireApi.sourcePageNotifications(false, signal),
    (signal: AbortSignal) => tireApi.sourcePageNotification(notice.id, signal),
    (signal: AbortSignal) => tireApi.markSourcePageNotification(notice.id, true, signal),
  ];
  for (const operation of operations) {
    const controller = new AbortController(), failure = new DOMException("Synthetic caller cancellation", "AbortError");
    let calls = 0;
    const restore = setApiTransport((_path, init) => new Promise((_resolve, reject) => {
      calls++; assert.equal(init.signal, controller.signal);
      init.signal!.addEventListener("abort", () => reject(failure), { once: true });
    }));
    try {
      const rejected = assert.rejects(operation(controller.signal), cause => cause === failure);
      controller.abort(); await rejected; assert.equal(calls, 1);
    } finally { restore(); }
  }
});

await test("the existing SKU notification routes and payloads remain unchanged", async () => {
  const old = { items: [], total: 0 }, transport = install(old), controller = new AbortController();
  try {
    assert.deepEqual(await tireApi.notifications(false, controller.signal, 100), old);
    assert.equal(transport.calls[0].path, "/v1/notifications?unread=false&offset=100");
    await tireApi.markNotification("old/id", true, controller.signal);
    assert.equal(transport.calls[1].path, "/v1/notifications/old%2Fid/read");
    assert.equal(transport.calls[1].init.method, "PUT");
    assert.deepEqual(JSON.parse(String(transport.calls[1].init.body)), { read: true });
  } finally { transport.restore(); }
});
