import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const { createNativeTransport, createNativeSave, NativeError, bytesToBase64 } = await loadTypeScript("../src/index.ts", import.meta.url);
const ok = () => ({ status: 200, headers: { "content-type": "application/json" }, body_base64: bytesToBase64(new TextEncoder().encode("{}")) });

test("typed-array subviews transmit only the intended byte range", async () => {
  const original = Uint8Array.from([99, 0, 255, 128, 88]);
  const bodies = [];
  const transport = createNativeTransport(async (_command, { request }) => { bodies.push(request.body_base64); return ok(); });
  await transport("/v1/documents", { method: "POST", body: new DataView(original.buffer, 1, 3), headers: { "Content-Type": "application/pdf" } });
  assert.deepEqual(Buffer.from(bodies[0], "base64"), Buffer.from([0, 255, 128]));
});

test("UTF-8 JSON and supported Headers preserve text and idempotency", async () => {
  const headers = new Headers([["Content-Type", "application/json"], ["Idempotency-Key", "123e4567-e89b-42d3-a456-426614174000"]]);
  const transport = createNativeTransport(async (_command, { request }) => {
    assert.equal(Buffer.from(request.body_base64, "base64").toString("utf8"), '{"title":"胎迹 🚗"}');
    assert.equal(request.headers["idempotency-key"], headers.get("Idempotency-Key"));
    return ok();
  });
  await transport("/v1/reports", { method: "POST", body: '{"title":"胎迹 🚗"}', headers });
});

test("unhandled multipart or streaming uploads fail before native dispatch", async () => {
  let calls = 0;
  const transport = createNativeTransport(async () => { calls++; return ok(); });
  for (const body of [new FormData(), new ReadableStream({ start(controller) { controller.close(); } })]) {
    await assert.rejects(transport("/v1/documents", { method: "POST", body }), error => error instanceof NativeError && error.code === "invalid_request");
  }
  assert.equal(calls, 0);
});

test("response completion removes the abort hook without cancelling a later unrelated operation", async () => {
  const commands = [];
  const controller = new AbortController();
  const transport = createNativeTransport(async command => { commands.push(command); return ok(); });
  await transport("/health", { signal: controller.signal });
  controller.abort();
  assert.deepEqual(commands, ["api_request"]);
});

test("synchronous abort during invocation still rejects and cancels the same request", async () => {
  const controller = new AbortController();
  const calls = [];
  const transport = createNativeTransport(async (command, args) => {
    calls.push({ command, args });
    if (command === "api_request") controller.abort();
    return ok();
  });
  await assert.rejects(transport("/v1/reports", { method: "POST", signal: controller.signal }), { name: "AbortError" });
  assert.deepEqual(calls.map(call => call.command), ["api_request", "api_cancel"]);
  assert.equal(calls[0].args.request.id, calls[1].args.id);
});

test("malformed native responses and save results cannot masquerade as success", async () => {
  for (const value of [null, { ...ok(), status: 0 }, { ...ok(), body_base64: 123 }, { ...ok(), headers: null }]) {
    const transport = createNativeTransport(async () => value);
    await assert.rejects(transport("/health", {}), error => error instanceof NativeError && error.code === "invalid_response");
  }
  const save = createNativeSave(async () => ({ saved: "true", path: "private-path" }));
  await assert.rejects(save({ blob: new Blob(["fixture"]), filename: "fixture.pdf" }), error => error.code === "save_failed" && !error.message.includes("private-path"));
});
