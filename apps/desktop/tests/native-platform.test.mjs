import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript as load } from "../../../packages/native-client/tests/load-typescript.mjs";
const loadTypeScript = relative => load(relative, import.meta.url);

const { createNativeTransport, createNativePlatform, DesktopError, externalLink, openNativeExternal } = await loadTypeScript("../src/native-platform.ts");
const { setApiTransport, tireApi, ApiError } = await loadTypeScript("../../../packages/api-client/src/index.ts");
const response = (status, body, headers = { "content-type": "application/json" }) => ({ status, headers, body_base64: Buffer.from(body).toString("base64") });
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

test("PDF File preserves every byte and metadata header through the shared SDK", async () => {
  const bytes = Uint8Array.from({ length: 262147 }, (_, index) => index % 256);
  const file = new File([bytes], "原文.pdf", { type: "application/pdf" });
  const calls = [];
  const restore = setApiTransport(createNativeTransport(async (command, args) => {
    calls.push({ command, args });
    return response(201, JSON.stringify({ id: "document-1" }));
  }));
  try {
    const metadata = { title: "原始证据", source_url: "", operator: "测试", rights_basis: "测试夹具" };
    assert.deepEqual(await tireApi.uploadDocument(metadata, file), { id: "document-1" });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, "api_request");
    const { request } = calls[0].args;
    assert.equal(request.path, "/v1/documents");
    assert.equal(request.method, "POST");
    assert.equal(request.headers["content-type"], "application/pdf");
    assert.deepEqual(JSON.parse(Buffer.from(request.headers["x-evidence-metadata"], "base64").toString("utf8")), metadata);
    assert.deepEqual(Buffer.from(request.body_base64, "base64"), Buffer.from(bytes));
  } finally { restore(); }
});

test("binary response preserves Content-Type and excludes native session cookies", async () => {
  const bytes = Uint8Array.from([37, 80, 68, 70, 0, 128, 255, 13, 10]);
  const transport = createNativeTransport(async () => response(200, bytes, { "Content-Type": "application/pdf", "Set-Cookie": "fixture-session=not-for-js" }));
  const value = await transport("/v1/documents/example/content", {});
  assert.equal(value.headers.has("set-cookie"), false);
  const blob = await value.blob();
  assert.equal(blob.type, "application/pdf");
  assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), bytes);
});

test("SDK keeps browser defaults, parses native HTTP errors and preserves idempotency", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const browserFetch = async (url, init) => { calls.push({ url, init }); return new Response('{"status":"ok"}'); };
  globalThis.fetch = browserFetch;
  try {
    assert.deepEqual(await tireApi.health(), { status: "ok" });
    assert.equal(calls[0].url, "/api/health");
    assert.equal(calls[0].init.credentials, "include");
    assert.equal(calls[0].init.cache, "no-store");
    let nativeCalls = 0;
    const restore = setApiTransport(createNativeTransport(async (command, { request }) => {
      nativeCalls += 1;
      assert.equal(command, "api_request");
      assert.equal(request.headers["idempotency-key"], "stable-key");
      assert.equal(request.headers["content-type"], "application/json");
      return response(409, JSON.stringify({ detail: { message: "修订已变化", code: "revision_conflict", run_id: "run-1" } }));
    }));
    try {
      await assert.rejects(tireApi.createReport({ title: "test" }, "stable-key"), error => error instanceof ApiError && error.status === 409 && error.message === "修订已变化" && error.code === "revision_conflict" && error.runId === "run-1");
      assert.equal(nativeCalls, 1, "writes must not be retried automatically");
      assert.equal(globalThis.fetch, browserFetch, "transport injection must not replace global fetch");
      assert.equal(calls.length, 1, "native transport must not reach browser fetch");
    } finally { restore(); }
    await tireApi.health();
    assert.equal(calls.length, 2);
  } finally { globalThis.fetch = originalFetch; }
});

test("unapproved request headers and absolute paths never reach IPC", async () => {
  let calls = 0;
  const transport = createNativeTransport(async () => { calls += 1; return response(200, "{}"); });
  for (const headers of [{ Authorization: "test-fixture" }, { Cookie: "test-fixture" }, { Origin: "https://example.test" }]) {
    await assert.rejects(transport("/health", { headers }), error => error instanceof DesktopError && error.code === "invalid_request");
  }
  for (const path of ["https://example.test/health", "//example.test/health"]) await assert.rejects(transport(path, {}), DesktopError);
  assert.equal(calls, 0);
});

test("native error messages are selected from fixed codes and never echo payloads", async () => {
  for (const cause of ["SESSION_STORE_WRITE_FAILED", "credential-token=private; C:/private/path", new Error("private-file-and-cookie")]) {
    const transport = createNativeTransport(async () => { throw cause; });
    await assert.rejects(transport("/health", {}), error => error instanceof DesktopError && !/private|credential-token|C:\//.test(error.message) && (cause === "SESSION_STORE_WRITE_FAILED" ? error.code === cause : error.code === "request_failed"));
  }
});

test("pre-aborted request does not invoke or read a File", async () => {
  const controller = new AbortController(); controller.abort();
  let read = false;
  const file = new File(["fixture"], "fixture.pdf");
  file.arrayBuffer = async () => { read = true; throw new Error("must not read"); };
  const transport = createNativeTransport(async () => { throw new Error("must not invoke"); });
  await assert.rejects(transport("/v1/documents", { body: file, signal: controller.signal }), { name: "AbortError" });
  assert.equal(read, false);
});

test("abort during a pending File read rejects promptly and never dispatches later", { timeout: 1000 }, async () => {
  const controller = new AbortController();
  const reading = deferred();
  const file = new File(["fixture"], "fixture.pdf");
  file.arrayBuffer = () => reading.promise;
  const calls = [];
  const transport = createNativeTransport(async (...args) => { calls.push(args); return response(200, "{}"); });
  const pending = transport("/v1/documents", { method: "POST", body: file, signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  reading.resolve(new Uint8Array([1, 2, 3]).buffer);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, []);
});

test("abort immediately after File completion still prevents dispatch", async () => {
  const controller = new AbortController();
  const file = new File(["fixture"], "fixture.pdf");
  file.arrayBuffer = async () => { controller.abort(); return new Uint8Array([1]).buffer; };
  let calls = 0;
  const transport = createNativeTransport(async () => { calls += 1; return response(200, "{}"); });
  await assert.rejects(transport("/v1/documents", { body: file, signal: controller.signal }), { name: "AbortError" });
  assert.equal(calls, 0);
});

test("in-flight abort cancels the matching native id, ignores late results and does not retry", { timeout: 1000 }, async () => {
  const controller = new AbortController();
  const active = deferred();
  const calls = [];
  const transport = createNativeTransport(async (command, args) => {
    calls.push({ command, args });
    if (command === "api_request") return active.promise;
  });
  const pending = transport("/v1/reports", { method: "POST", signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.deepEqual(calls.map(call => call.command), ["api_request", "api_cancel"]);
  assert.equal(calls[0].args.request.id, calls[1].args.id);
  active.resolve(response(201, '{"created":true}'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 2);
});

test("late native failure and failed cancellation remain handled after abort", { timeout: 1000 }, async () => {
  const active = deferred();
  const controller = new AbortController();
  const transport = createNativeTransport(async command => {
    if (command === "api_request") return active.promise;
    throw "CANCEL_QUEUE_FULL";
  });
  const pending = transport("/health", { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  active.reject("API_REQUEST_FAILED");
  await new Promise(resolve => setImmediate(resolve));
});

test("empty 204 response is compatible with SDK JSON methods", async () => {
  const restore = setApiTransport(createNativeTransport(async () => response(204, "")));
  try { assert.equal(await tireApi.health(), undefined); }
  finally { restore(); }
});

test("save passes original binary to a native dialog; cancellation never reports success or opens HTML", async () => {
  const calls = [];
  const platform = createNativePlatform(async (command, args) => { calls.push({ command, args }); return { saved: false }; });
  const blob = new Blob(["<html>fixture</html>"], { type: "text/html" });
  assert.deepEqual(await platform.saveDownload({ blob, filename: "report.html" }), { saved: false });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, "save_download");
  assert.deepEqual(calls[0].args, { filename: "report.html", mime: "text/html", body_base64: Buffer.from(await blob.arrayBuffer()).toString("base64") });
});

test("cancelled save preparation never opens the dialog; native write errors stay sanitized", async () => {
  const controller = new AbortController();
  const blob = new Blob(["fixture"]);
  blob.arrayBuffer = async () => { controller.abort(); return new Uint8Array([1]).buffer; };
  let calls = 0;
  const platform = createNativePlatform(async () => { calls += 1; throw "private-location"; });
  await assert.rejects(platform.saveDownload({ blob, filename: "fixture.pdf", signal: controller.signal }), { name: "AbortError" });
  assert.equal(calls, 0);
  await assert.rejects(platform.saveDownload({ blob: new Blob(["fixture"]), filename: "fixture.pdf" }), error => error instanceof DesktopError && error.code === "save_failed" && !error.message.includes("private-location"));
});

test("external navigation keeps local root/hash, opens only credential-free HTTP(S), and rejects other schemes", async () => {
  assert.deepEqual(externalLink("/"), { action: "internal" });
  assert.deepEqual(externalLink("#evidence"), { action: "internal" });
  for (const href of ["javascript:alert(1)", "file:///tmp/test", "data:text/html,test", "mailto:x@example.test", "//example.test", "https://user:password@example.test", "/unknown-route"]) assert.equal(externalLink(href).action, "blocked");
  const calls = [];
  await openNativeExternal(async (...args) => { calls.push(args); }, "https://example.test/evidence");
  assert.deepEqual(calls, [["open_external", { url: "https://example.test/evidence" }]]);
  await assert.rejects(openNativeExternal(async () => { throw "private-browser-path"; }, "http://example.test"), error => error.code === "external_open_failed" && !error.message.includes("private-browser-path"));
});
