// Read-only SDK/protocol checks. No browser, database, Worker or external HTTP.
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const values = await loadTypeScript("../apps/web/components/task-center-values.ts", import.meta.url);
const now = "2026-10-01T00:00:00Z";
const event = (sequence = 1, patch = {}) => ({ id: `event-${sequence}`, sequence, cursor: `opaque-v1-tire-job-${sequence}`, attempt_id: sequence < 4 ? "attempt-one" : "attempt-two", phase: "running", state: "running", result_state: null, reason: null, query_id: null, run_id: null, created_at: now, ...patch });
const frame = (type, data, id) => `${id ? `id: ${id}\r\n` : ""}event: ${type}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`;
const end = cursor => frame("stream_end", { cursor, server_time: now, reason: "window_complete" });
function response(text, chunkSize = 7) {
  const bytes = new TextEncoder().encode(text);
  let position = 0;
  return new Response(new ReadableStream({ pull(controller) { if (position >= bytes.length) controller.close(); else { controller.enqueue(bytes.slice(position, position + chunkSize)); position += chunkSize; } } }), { headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
}

test("SSE preserves UTF-8 split across bytes, CRLF, event cursor and explicit window completion", async () => {
  const value = event(1, { reason: "合成阶段，未声称已联网 🛞" });
  const messages = [];
  const result = await sdk.consumeMonitorTaskStream(response(": comment\r\n\r\n" + frame("task_event", value, value.cursor) + frame("heartbeat", { cursor: value.cursor, server_time: now }) + end(value.cursor), 1), message => messages.push(message));
  assert.equal(result, "window_complete");
  assert.deepEqual(messages.map(message => message.type), ["task_event", "heartbeat", "stream_end"]);
  assert.deepEqual(messages[0].data, value);
  assert.equal(messages[0].data.state, "running", "stream window must not complete a running task");
});
test("SSE delivers a durable event while the stream remains open", async () => {
  let channel, observed = false;
  const first = event();
  const pending = sdk.consumeMonitorTaskStream(new Response(new ReadableStream({ start(controller) { channel = controller; controller.enqueue(new TextEncoder().encode(frame("task_event", first, first.cursor))); } }), { headers: { "Content-Type": "text/event-stream" } }), message => { if (message.type === "task_event") observed = true; });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(observed, true, "must not buffer the whole 25-second stream");
  channel.enqueue(new TextEncoder().encode(end(first.cursor))); channel.close();
  assert.equal(await pending, "window_complete");
});
test("one network chunk can contain more than 128KiB of individually bounded task frames", async () => {
  const events = Array.from({ length: 500 }, (_, index) => event(index + 1, { reason: "synthetic ".repeat(35) }));
  const text = events.map(value => frame("task_event", value, value.cursor)).join("") + end(events.at(-1).cursor);
  const bytes = new TextEncoder().encode(text);
  assert.ok(bytes.length > 131072);
  const seen = [];
  assert.equal(await sdk.consumeMonitorTaskStream(response(text, bytes.length), message => { if (message.type === "task_event") seen.push(message.data.sequence); }), "window_complete");
  assert.deepEqual(seen, events.map(value => value.sequence));
  await assert.rejects(sdk.consumeMonitorTaskStream(response("data: " + "x".repeat(132000), 132006), () => {}), /缓冲区超过限制/);
});
test("reset is explicit and unexpected EOF never claims a completed task", async () => {
  const messages = [];
  assert.equal(await sdk.consumeMonitorTaskStream(response(frame("reset", { code: "task_cursor_reset_required", server_time: now })), item => messages.push(item)), "reset");
  assert.equal(messages.length, 1);
  await assert.rejects(sdk.consumeMonitorTaskStream(response(frame("task_event", event(), event().cursor)), () => {}), /最新状态未知/);
  await assert.rejects(sdk.consumeMonitorTaskStream(response("event: task_event\ndata: {\"id\":\"incomplete\"}"), () => {}), /最新状态未知/);
});
test("malformed, oversized and mismatched cursor frames are rejected before callbacks", async () => {
  for (const text of [frame("task_event", event(), "different-cursor"), frame("task_event", event(2, { phase: "parser_90_percent" }), event(2).cursor), frame("task_event", event(2, { sequence: Number.MAX_SAFE_INTEGER + 1 }), event(2).cursor), "data: " + "x".repeat(66000) + "\n\n"]) {
    let calls = 0;
    await assert.rejects(sdk.consumeMonitorTaskStream(response(text, 1024), () => calls++));
    assert.equal(calls, 0);
  }
  await assert.rejects(sdk.consumeMonitorTaskStream(new Response("{}", { headers: { "Content-Type": "application/json" } }), () => {}));
});
test("abort cancels the streaming reader without emitting later messages", async () => {
  const controller = new AbortController(); let canceled = 0, calls = 0;
  const stream = new ReadableStream({ cancel() { canceled++; } });
  const pending = sdk.consumeMonitorTaskStream(new Response(stream, { headers: { "Content-Type": "text/event-stream" } }), () => calls++, controller.signal);
  controller.abort();
  await assert.rejects(pending, error => error.name === "AbortError");
  assert.equal(canceled, 1); assert.equal(calls, 0);
});
test("task events deduplicate by UUID across reconnect and maintain per-job order across attempts", () => {
  const events = [event(3), event(4), event(5, { phase: "finished", state: "blocked", result_state: "source_unavailable", reason: "source_paused", run_id: "run-two" })];
  const merged = values.mergeTaskEvents([event(1), event(2), events[0]], events);
  assert.deepEqual(merged.map(value => value.sequence), [1, 2, 3, 4, 5]);
  assert.equal(merged[3].attempt_id, "attempt-two");
  assert.equal(merged[4].state, "blocked");
  assert.throws(() => values.mergeTaskEvents(merged, [event(3, { state: "succeeded" })]), /同一任务事件/);
  assert.throws(() => values.mergeTaskEvents(merged, [event(3, { id: "different" })]), /顺序冲突/);
  assert.equal(values.mergeTaskEvents([], Array.from({ length: 230 }, (_, index) => event(index + 1))).length, 200);
});
test("task scope and result_unknown come from the projection, never guessed from a lease", () => {
  const task = { kind: "tire", job_id: "job-one", scope: "local_workspace", state: "result_unknown", phase: "running", terminal: false, lease_until: "2000-01-01T00:00:00Z", rules: [] };
  const detail = { schema: "monitor-tasks@1", task, attempts: [], legacy_runs: [], cursor: "opaque" };
  assert.equal(values.taskProjectionMatches(detail, "tire", "job-one"), true);
  assert.equal(values.taskProjectionMatches({ ...detail, task: { ...task, scope: "session" } }, "tire", "job-one"), false);
  assert.equal(values.taskProjectionMatches(detail, "recall", "job-one"), false);
  assert.equal(values.taskStateLabels[task.state], "结果待确认");
  assert.equal(values.taskScopeLabel("session"), "当前会话");
});
test("SDK uses encoded read-only task routes, separate history pages and native REST cursor", async t => {
  for (const host of ["browser", "native"]) await t.test(host, async () => {
    const calls = []; const originalFetch = globalThis.fetch; let restore;
    function route(path, method, body) { calls.push({ path, method, body }); assert.equal(method, "GET"); assert.equal(body, undefined); return { fixture: true }; }
    try {
      if (host === "browser") globalThis.fetch = async (path, init) => new Response(JSON.stringify(route(path.slice(4), init.method || "GET", init.body)), { headers: { "Content-Type": "application/json" } });
      else {
        globalThis.fetch = async () => assert.fail("native polled through browser fetch");
        restore = sdk.setApiTransport(native.createNativeTransport(async (command, { request }) => {
          assert.equal(command, "api_request");
          const value = route(request.path, request.method, request.body_base64);
          return { status: 200, headers: { "content-type": "application/json" }, body_base64: Buffer.from(JSON.stringify(value)).toString("base64") };
        }));
      }
      await sdk.tireApi.monitorTasks({ kind: "recall", source_id: "source & region", state: "blocked", rule_id: "rule / one" }, 20);
      await sdk.tireApi.monitorTask("tire", "job / one", { attemptOffset: 40, legacyOffset: 20 });
      await sdk.tireApi.monitorTaskEvents("tire", "job / one", "opaque +/= cursor");
      assert.match(calls[0].path, /kind=recall/); assert.match(calls[0].path, /source_id=source\+%26\+region/);
      assert.match(calls[1].path, /job%20%2F%20one\?attempt_offset=40&attempt_limit=20&legacy_offset=20&legacy_limit=20/);
      assert.match(calls[2].path, /cursor=opaque\+%2B%2F%3D\+cursor&limit=50/);
      assert.equal(calls.some(call => call.path.includes("/stream")), false);
    } finally { restore?.(); globalThis.fetch = originalFetch; }
  });
});
test("Web stream GET uses the same cursor and exposes HTTP reset code without changing a task", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (path, init) => {
      assert.match(path, /\/api\/v1\/monitor-tasks\/tire\/job-one\/events\/stream\?cursor=opaque/);
      assert.equal(init.method, undefined); assert.equal(init.headers.get("accept"), "text/event-stream");
      return new Response(JSON.stringify({ detail: { code: "task_cursor_reset_required", message: "重新读取" } }), { status: 409 });
    };
    await assert.rejects(sdk.tireApi.streamMonitorTaskEvents("tire", "job-one", "opaque", () => {}), error => error instanceof sdk.ApiError && values.isTaskCursorReset(error));
  } finally { globalThis.fetch = originalFetch; }
});
