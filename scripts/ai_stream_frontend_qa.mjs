// Pure client contracts: no database, browser, provider or external requests.
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const values = await loadTypeScript("../apps/web/components/ai-stream-values.ts", import.meta.url);
const id = "request-one", now = "2026-10-01T09:00:00Z";
const claim = (patch = {}) => ({ type: "fact", text: "来源记录的完整字段", fact_ids: ["F1"], evidence_ids: ["E1"], ...patch });
const analysis = (patch = {}) => ({ id, pack_id: "pack-one", question: "解释所选证据", provider: "openai", model: "synthetic-only",
  state: "pending", created_at: now, completed_at: null, reserved_tokens: 1000, usage: null, error_code: null,
  answer: null, request_contract: { delivery_mode: "stream" }, ...patch });
const execution = (state = "running", patch = {}) => ({ state, terminal: ["completed", "failed", "outcome_unknown"].includes(state),
  deadline_at: "2026-10-01T09:01:30Z", last_event_at: now, projection_only: false, ...patch });
const detail = (patch = {}) => ({ schema: "ai-streams@1", scope: "session", analysis: analysis(), execution: execution(),
  draft_claims: [{ index: 0, claim: claim() }], draft_uncertainty: null, cursor: "opaque-2", server_time: now, ...patch });
const event = (sequence = 3, patch = {}) => ({ id: "event-" + sequence, request_id: id, sequence, cursor: "opaque-" + sequence,
  type: "claim_draft", payload: { index: 0, claim: claim() }, created_at: now, ...patch });
const frame = value => `event: ai_event\nid: ${value.cursor}\ndata: ${JSON.stringify(value)}\n\n`;
const end = cursor => `event: stream_end\ndata: ${JSON.stringify({ cursor, server_time: now, reason: "window_complete" })}\n\n`;
const response = text => new Response(text, { headers: { "Content-Type": "text/event-stream; charset=utf-8" } });

test("active and committed detail projections enforce request, scope and draft/final boundaries", () => {
  assert.equal(sdk.isAIStreamDetail(detail(), id), true);
  for (const changed of [detail({ scope: "workspace" }), detail({ schema: "unknown" }),
    detail({ analysis: analysis({ id: "other" }) }), detail({ execution: execution("completed") }),
    detail({ analysis: analysis({ answer: { claims: [claim()] } }) }),
    detail({ draft_claims: [{ index: 0, claim: claim() }, { index: 0, claim: claim() }] })]) {
    assert.equal(sdk.isAIStreamDetail(changed, id), false);
  }
  const completed = detail({ analysis: analysis({ state: "completed", answer: { claims: [claim()], uncertainty: "", notice: "人工复核" } }),
    execution: execution("completed"), draft_claims: [] });
  assert.equal(sdk.isAIStreamDetail(completed, id), true);
  assert.equal(sdk.isAIStreamDetail({ ...completed, draft_uncertainty: "stale draft" }), false);
});

test("fact reconstruction may exceed model text limits while inference and reference bounds remain enforced", () => {
  assert.equal(sdk.isAIClaim(claim({ text: "证据".repeat(2000) })), true);
  assert.equal(sdk.isAIClaim(claim({ type: "inference", text: "💡".repeat(2000) })), true);
  assert.equal(sdk.isAIClaim(claim({ type: "inference", text: "x".repeat(2001) })), false);
  assert.equal(sdk.isAIClaim(claim({ fact_ids: Array(25).fill("F1") })), false);
  assert.equal(sdk.isAIClaim(claim({ evidence_ids: Array(7).fill("E1") })), false);
  assert.equal(sdk.isAIClaim(claim({ text: "x".repeat(65536) })), false);
});

test("uncertainty-only drafts and completed empty-claim answers remain meaningful content", async () => {
  const item = event(3, { type: "uncertainty_draft", payload: { text: "证据不足，无法给出判断。" } });
  const received = [];
  await sdk.consumeAIStream(response(frame(item) + end(item.cursor)), id, message => received.push(message));
  assert.equal(received[0].data.payload.text, item.payload.text);
  const value = detail({ draft_claims: [], draft_uncertainty: item.payload.text });
  assert.deepEqual(values.visibleAIDrafts(value), { claims: [], uncertainty: item.payload.text });
  const completed = analysis({ state: "completed", answer: { claims: [], uncertainty: item.payload.text, notice: "需人工核对" } });
  assert.equal(values.canExportAIAnalysis(completed), true);
});

test("SSE preserves split UTF-8, CRLF and opaque cursors without exposing JSON fragments", async () => {
  const bytes = new TextEncoder().encode((frame(event()) + end("opaque-3")).replaceAll("\n", "\r\n"));
  const body = new ReadableStream({ start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close(); } });
  const received = [];
  const result = await sdk.consumeAIStream(new Response(body, { headers: { "Content-Type": "text/event-stream" } }), id, message => received.push(message));
  assert.equal(result, "window_complete"); assert.equal(received.length, 2);
  assert.equal(received[0].data.payload.claim.text, claim().text);
});

test("complete draft arrives while the stream is still open", async () => {
  let control, seen;
  const observed = new Promise(resolve => { seen = resolve; });
  const body = new ReadableStream({ start(controller) { control = controller; controller.enqueue(new TextEncoder().encode(frame(event()))); } });
  const consuming = sdk.consumeAIStream(new Response(body, { headers: { "Content-Type": "text/event-stream" } }), id, message => { if (message.type === "ai_event") seen(message); });
  const message = await observed;
  assert.equal(message.data.payload.claim.text, claim().text);
  control.enqueue(new TextEncoder().encode(end("opaque-3"))); control.close();
  assert.equal(await consuming, "window_complete");
});

test("coalesced transport chunks may contain many individually bounded draft events", async () => {
  const events = Array.from({ length: 70 }, (_, index) => event(index + 1, { payload: { index: 0, claim: claim({ text: "x".repeat(2500) }) } }));
  const text = events.map(frame).join("") + end(events.at(-1).cursor);
  assert.ok(new TextEncoder().encode(text).length > 131072);
  let received = 0;
  await sdk.consumeAIStream(response(text), id, message => { if (message.type === "ai_event") received++; });
  assert.equal(received, 70);
});

test("unknown events, partial JSON, foreign requests and cursor disagreement are rejected before callbacks", async () => {
  const invalid = [frame(event(3, { request_id: "other-request" })), frame(event()).replace("id: opaque-3", "id: different"),
    frame(event()).replace("event: ai_event", "event: output_text.delta"),
    'event: ai_event\nid: opaque-3\ndata: {"payload":\n\n',
    frame(event(3, { payload: { index: 0, claim: { type: "fact", text: "partial" } } }))];
  for (const text of invalid) {
    let callbacks = 0;
    await assert.rejects(sdk.consumeAIStream(response(text), id, () => { callbacks++; }));
    assert.equal(callbacks, 0);
  }
});

test("unexpected EOF is not a completed stream window even after a terminal hint", async () => {
  const completed = event(3, { type: "completed", payload: { state: "completed", error_code: null } });
  await assert.rejects(sdk.consumeAIStream(response(frame(completed)), id, () => {}), /连接中断/);
  const reset = `event: reset\ndata: ${JSON.stringify({ code: "ai_stream_cursor_reset_required", server_time: now })}\n\n`;
  assert.equal(await sdk.consumeAIStream(response(reset), id, () => {}), "reset");
});

test("abort stops the reader and prevents later frames from reaching the UI", async () => {
  const controller = new AbortController(); let cancelled = false, received = 0;
  const body = new ReadableStream({ start(stream) { stream.enqueue(new TextEncoder().encode(frame(event()) + frame(event(4)))); }, cancel() { cancelled = true; } });
  await assert.rejects(sdk.consumeAIStream(new Response(body, { headers: { "Content-Type": "text/event-stream" } }), id,
    () => { received++; controller.abort(); }, controller.signal), { name: "AbortError" });
  assert.equal(received, 1); assert.equal(cancelled, true);
});

test("event positions deduplicate replay and reject foreign, conflicting or skipped sequence", () => {
  const first = values.advanceAIEvent(id, { cursor: "opaque-2", sequence: 0, eventId: null }, event());
  assert.deepEqual(values.advanceAIEvent(id, first, event()), first);
  assert.deepEqual(values.advanceAIEvent(id, first, event(2)), first);
  assert.throws(() => values.advanceAIEvent(id, first, event(4, { request_id: "other" })), /另一条请求/);
  assert.throws(() => values.advanceAIEvent(id, first, event(3, { id: "different" })), /冲突/);
  assert.throws(() => values.advanceAIEvent(id, first, event(5)), /不连续/);
});

test("terminal or invalidated projections hide all drafts and only committed answers can be exported", () => {
  assert.equal(values.visibleAIDrafts(detail()).claims.length, 1);
  assert.deepEqual(values.visibleAIDrafts(detail(), true), { claims: [], uncertainty: null });
  for (const state of ["failed", "outcome_unknown", "completed"]) {
    assert.deepEqual(values.visibleAIDrafts(detail({ execution: execution(state), draft_uncertainty: "stale" })), { claims: [], uncertainty: null });
    if (state !== "completed") assert.equal(values.canExportAIAnalysis(analysis({ state, answer: { claims: [claim()] } })), false);
  }
  assert.equal(values.canExportAIAnalysis(analysis({ answer: { claims: [claim()] } })), false);
});

test("tab recovery retains only identifiers and refuses malformed persisted values", () => {
  const pointer = { key: "10f4a320-4bb7-42a3-bd56-15565bbf980d", requestId: id, cursor: "opaque +/=", question: "private question", consent: true, pack: { secret: "evidence" } };
  assert.deepEqual(values.parseAIRecovery(JSON.stringify(pointer)), { key: pointer.key, requestId: id, cursor: pointer.cursor });
  for (const raw of [null, "not json", JSON.stringify({ key: "invalid" }), JSON.stringify({ ...pointer, cursor: "a\nb" }), JSON.stringify({ ...pointer, requestId: "other/route" })]) {
    assert.equal(values.parseAIRecovery(raw), null);
  }
});

test("stream failures have readable Chinese explanations without raw codes or no-charge promises", () => {
  for (const code of ["ai_stream_interrupted", "ai_stream_protocol_error", "ai_stream_owner_expired", "ai_stream_start_failed", "ai_stream_shutdown", "ai_stream_invalid", "ai_stream_too_large", "ai_stream_cursor_reset_required", "ai_stream_mode_conflict", "ai_stream_future_failure"]) {
    const text = values.aiStreamErrorMessage(code);
    assert.match(text, /[\u4e00-\u9fff]/);
    assert.ok(!text.includes(code));
    assert.doesNotMatch(text, /不会计费|不收费|免费|已取消供应商/);
  }
  assert.match(values.aiStreamErrorMessage("ai_stream_interrupted"), /结果与用量尚未确认.*不会自动重新调用模型/);
  assert.match(values.aiStreamErrorMessage("ai_stream_protocol_error"), /最终正文不一致.*完整性校验/);
});

test("browser and native acceptance/recovery use one UUID and read-only bounded progress routes", async t => {
  for (const host of ["browser", "native"]) await t.test(host, async () => {
    const originalFetch = globalThis.fetch, calls = []; let restore;
    const reply = (path, method, headers, body) => {
      calls.push({ path, method, headers, body });
      if (path.includes("/events?")) return { schema: "ai-streams@1", scope: "session", request_id: id, items: [], next_cursor: "opaque +/=", latest_cursor: "opaque +/=", has_more: false, execution: execution(), server_time: now };
      return method === "POST" ? { ...detail(), replayed: calls.filter(call => call.method === "POST").length > 1 } : detail();
    };
    try {
      if (host === "browser") globalThis.fetch = async (path, init) => new Response(JSON.stringify(reply(path.slice(4), init.method || "GET", Object.fromEntries(init.headers), init.body ? JSON.parse(init.body) : undefined)), { headers: { "Content-Type": "application/json" } });
      else {
        globalThis.fetch = async () => assert.fail("native used browser networking");
        restore = sdk.setApiTransport(native.createNativeTransport(async (command, { request }) => {
          assert.equal(command, "api_request");
          const body = request.body_base64 ? JSON.parse(Buffer.from(request.body_base64, "base64").toString("utf8")) : undefined;
          return { status: 200, headers: { "content-type": "application/json" }, body_base64: Buffer.from(JSON.stringify(reply(request.path, request.method, request.headers, body))).toString("base64") };
        }));
      }
      const key = "10f4a320-4bb7-42a3-bd56-15565bbf980d", payload = { pack_id: "pack-one", question: "解释所选证据", allow_external_processing: true };
      assert.equal((await sdk.tireApi.startAIStream(payload, key)).replayed, false);
      assert.equal((await sdk.tireApi.startAIStream(payload, key)).replayed, true);
      assert.deepEqual(calls[0], calls[1]); assert.equal(calls[0].headers["idempotency-key"], key);
      await sdk.tireApi.lookupAIStream(key); await sdk.tireApi.aiStream(id); await sdk.tireApi.aiStreamEvents(id, "opaque +/=");
      assert.ok(calls.slice(2).every(call => call.method === "GET" && call.body === undefined));
      assert.match(calls[2].path, /lookup\?mode=history&idempotency_key=/);
      assert.equal(calls[3].path, "/v1/ai/analysis-streams/request-one?mode=history");
      assert.match(calls[4].path, /cursor=opaque\+%2B%2F%3D&limit=50/);
      assert.ok(!calls.some(call => call.path.includes("/events/stream")));
    } finally { restore?.(); globalThis.fetch = originalFetch; }
  });
});

test("Web SSE is a separate GET and HTTP cursor reset remains distinguishable", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (path, init) => {
      assert.equal(init.method, undefined); assert.equal(init.headers.get("Accept"), "text/event-stream");
      assert.match(path, /request-one\/events\/stream\?cursor=opaque-2/);
      return response(end("opaque-2"));
    };
    assert.equal(await sdk.tireApi.streamAIEvents(id, "opaque-2", () => {}), "window_complete");
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: { code: "ai_stream_cursor_reset_required", message: "reset" } }), { status: 409 });
    await assert.rejects(sdk.tireApi.streamAIEvents(id, "opaque-2", () => {}), error => error instanceof sdk.ApiError && error.code === "ai_stream_cursor_reset_required");
  } finally { globalThis.fetch = originalFetch; }
});

test("legacy synchronous SDK remains available and stream acceptance requires explicit replay metadata", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (path, init) => {
      if (path.endsWith("/analyses")) { assert.equal(init.method, "POST"); return new Response(JSON.stringify(analysis())); }
      return new Response(JSON.stringify(detail()));
    };
    assert.equal((await sdk.tireApi.analyzeAI({ pack_id: "pack-one", question: "legacy", allow_external_processing: true }, "legacy-key")).id, id);
    await assert.rejects(sdk.tireApi.startAIStream({ pack_id: "pack-one", question: "new", allow_external_processing: true }, "new-key"), /核对信息/);
  } finally { globalThis.fetch = originalFetch; }
});
