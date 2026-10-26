import assert from "node:assert/strict";
import test from "node:test";
// Use native module URLs so legal SDK cycles do not deadlock the data-URL loader.
import "../../api-client/tests/device-ai/json-esm-hook.mjs";

const { createNativeTransport, createNativeSave, NativeError, bytesToBase64 } = await import("../src/index.ts");
const ok = () => ({ status: 200, headers: { "content-type": "application/json" }, body_base64: bytesToBase64(new TextEncoder().encode("{}")) });

test("inventory account hint reaches only canonical GET routes with bounded ASCII IDs", async () => {
  const calls = [];
  const transport = createNativeTransport(async (_command, { request }) => { calls.push(request); return ok(); });
  for (const route of ["/v1/api-keys/active", "/v1/api-key-history"]) {
    for (const account of ["a", "Account_01-safe", "_", "-", "a".repeat(64)]) {
      await transport(`${route}?mode=history`, { method: "GET", headers: { "X-Tire-Expected-Account": account } });
      assert.equal(calls.at(-1).headers["x-tire-expected-account"], account);
      assert.equal(calls.at(-1).path, `${route}?mode=history`);
      assert.equal(calls.at(-1).method, "GET");
    }
  }
  await transport("/v1/api-key-history?mode=history&limit=20&cursor=opaque_-0", {
    headers: new Headers([["X-TIRE-EXPECTED-ACCOUNT", "fixture-account"]]),
  });
  assert.equal(calls.length, 11);
});

test("inventory hints reject invalid IDs, duplicate headers, other routes and methods before IPC", async () => {
  let calls = 0;
  const transport = createNativeTransport(async () => { calls++; return ok(); });
  const rejected = (path, init) => assert.rejects(transport(path, init), error => error instanceof NativeError && error.code === "invalid_request");
  for (const account of ["", "a".repeat(65), "a b", " leading", "trailing ", "tab\t", "new\n", "cr\r", "a.b", "a/b", "a,b", "a%20", "é", "账户", "😀"]) {
    await rejected("/v1/api-keys/active?mode=history", { headers: { "X-Tire-Expected-Account": account } });
  }
  for (const path of ["/health", "/v1/api-keys", "/v1/api-keys/active/", "/v1/api-key-history/older", "/v1/api-key-history-extra", "/v1/api-keys/%61ctive", "/v1/%61pi-key-history", "/v1/api-keys?next=/v1/api-keys/active"]) {
    await rejected(path, { headers: { "X-Tire-Expected-Account": "account" } });
  }
  for (const method of ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]) {
    await rejected("/v1/api-key-history?mode=history", { method, headers: { "X-Tire-Expected-Account": "account" } });
  }
  await rejected("/v1/api-keys/active", { headers: [["X-Tire-Expected-Account", "one"], ["x-tire-expected-account", "one"]] });
  for (const name of ["Authorization", "Cookie", "Origin", "Host", "X-Unapproved"]) {
    await rejected("/v1/api-keys/active", { headers: { "X-Tire-Expected-Account": "account", [name]: "fixture" } });
  }
  assert.equal(calls, 0);
});

test("inventory hint preserves the existing three-header budget", async () => {
  let calls = 0;
  const transport = createNativeTransport(async () => { calls++; return ok(); });
  const headers = { "X-Tire-Expected-Account": "account", "Content-Type": "application/json", "Idempotency-Key": "123e4567-e89b-42d3-a456-426614174000" };
  await transport("/v1/api-keys/active?mode=history", { headers });
  await assert.rejects(transport("/v1/api-keys/active?mode=history", { headers: { ...headers, "X-Evidence-Metadata": "e30=" } }), error => error instanceof NativeError && error.code === "invalid_request");
  assert.equal(calls, 1);
});

test("quarantine review hint forwards exact POST path, account and JSON bytes before IPC", async () => {
  const calls = [];
  const transport = createNativeTransport(async (command, { request }) => { calls.push({ command, request }); return ok(); });
  const body = JSON.stringify({ action: "approve", expected_revision: 0, operator: "复核员", reason: "证据已核对", confirmed_loss: true, expected_binding_hash: "a".repeat(64) });
  const idempotency = "123e4567-e89b-42d3-a456-426614174000";
  for (const id of ["q", "Quarantine_01-safe", "_", "-", "q".repeat(64)]) {
    const path = `/v1/quarantines/${id}/reviews?mode=history&format=raw-evidence-v2`;
    for (const account of ["a", "Account_01-safe", "_", "-", "a".repeat(64)]) {
      const entries = [["X-Tire-Expected-Account", account], ["Content-Type", "application/json"], ["Idempotency-Key", idempotency]];
      for (const headers of [Object.fromEntries(entries), entries, new Headers(entries)]) {
        await transport(path, { method: "POST", headers, body });
        const call = calls.at(-1);
        assert.equal(call.command, "api_request");
        assert.equal(call.request.path, path);
        assert.equal(call.request.method, "POST");
        assert.deepEqual(call.request.headers, { "content-type": "application/json", "idempotency-key": idempotency, "x-tire-expected-account": account });
        assert.deepEqual(Buffer.from(call.request.body_base64, "base64"), Buffer.from(body, "utf8"));
      }
    }
  }
  assert.equal(calls.length, 75);
});

test("quarantine review hint rejects raw path and query aliases and other methods before IPC", async () => {
  let calls = 0;
  const transport = createNativeTransport(async () => { calls++; return ok(); });
  const rejected = (path, method = "POST") => assert.rejects(transport(path, { method, headers: { "X-Tire-Expected-Account": "account" } }), error => error instanceof NativeError && error.code === "invalid_request");
  for (const path of [
    "/v1/quarantines/q/reviews",
    "/v1/quarantines/q/review?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/q/reviews/?mode=history&format=raw-evidence-v2",
    "/v1/quarantines//reviews?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/q.extra/reviews?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/账户/reviews?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/q/other/reviews?mode=history&format=raw-evidence-v2",
    "/v1/%71uarantines/q/reviews?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/%71/reviews?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/q/%72eviews?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/q%2Fother/reviews?mode=history&format=raw-evidence-v2",
    "/v1/quarantines/q/reviews?format=raw-evidence-v2&mode=history",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&extra=1",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&mode=history",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&format=raw-evidence-v2",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2?",
    "/v1/quarantines/q/reviews?mode=%68istory&format=raw-evidence-v2",
    "/v1/quarantines/q/reviews?%6dode=history&format=raw-evidence-v2",
    "/v1/quarantines/q/reviews?mode=history&format=raw%2Devidence-v2",
    "/v1/quarantines/q/reviews?mode=history%26format%3Draw-evidence-v2",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2\n",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2#fragment",
    "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v1",
    `/v1/quarantines/${"q".repeat(65)}/reviews?mode=history&format=raw-evidence-v2`,
  ]) await rejected(path);
  for (const method of ["GET", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS"]) {
    await rejected("/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2", method);
  }
  assert.equal(calls, 0);
});

test("quarantine review hint rejects raw bad account values and duplicate forms before IPC", async () => {
  let calls = 0;
  const transport = createNativeTransport(async () => { calls++; return ok(); });
  const path = "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2";
  const rejected = headers => assert.rejects(transport(path, { method: "POST", headers }), error => error instanceof NativeError && error.code === "invalid_request");
  for (const account of ["", "a".repeat(65), "a b", " leading", "trailing ", "a\t", "a\n", "a\r", "a.b", "a/b", "a,b", "a%20", "é", "账户", "😀"]) {
    await rejected({ "X-Tire-Expected-Account": account });
    await rejected([["X-Tire-Expected-Account", account]]);
  }
  await rejected({ "X-Tire-Expected-Account": "account", "x-tire-expected-account": "account" });
  await rejected([["X-Tire-Expected-Account", "account"], ["x-tire-expected-account", "account"]]);
  // Headers combines duplicate entries with a comma; this form must also stay rejected.
  await rejected(new Headers([["X-Tire-Expected-Account", "account"], ["x-tire-expected-account", "account"]]));
  await rejected(new Headers([["X-Tire-Expected-Account", "account,other"]]));
  for (const name of ["Authorization", "Cookie", "Origin", "Host", "X-Unapproved"]) {
    await rejected({ "X-Tire-Expected-Account": "account", [name]: "fixture" });
  }
  await rejected({ "X-Tire-Expected-Account": "account", "Content-Type": "application/json", "Idempotency-Key": "123e4567-e89b-42d3-a456-426614174000", "X-Evidence-Metadata": "e30=" });
  assert.equal(calls, 0);
});

test("missing quarantine review hints and legacy text requests still dispatch and preserve backend status", async () => {
  const calls = [];
  const canonical = "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2";
  const transport = createNativeTransport(async (command, { request }) => {
    calls.push({ command, request });
    return { ...ok(), status: request.path === canonical ? 422 : 200 };
  });
  for (const path of [canonical, "/v1/quarantines/q/reviews", "/v1/quarantines/q/reviews?mode=history"]) {
    const response = await transport(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    assert.equal(response.status, path === canonical ? 422 : 200);
    assert.equal(calls.at(-1).request.path, path);
    assert.equal(calls.at(-1).request.headers["x-tire-expected-account"], undefined);
    assert.equal(Buffer.from(calls.at(-1).request.body_base64, "base64").toString("utf8"), "{}");
  }
  assert.equal(calls.length, 3);
  assert.ok(calls.every(call => call.command === "api_request"));
});

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
  const save = createNativeSave(async command => command === "prepare_download" ? { lease: "a".repeat(64) } : ({ saved: "true", path: "private-path" }));
  await assert.rejects(save({ blob: new Blob(["fixture"]), filename: "fixture.pdf" }), error => error.code === "save_failed" && !error.message.includes("private-path"));
});

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const flush = () => new Promise(resolve => setImmediate(resolve));
const lease = "a".repeat(64);

test("download prepares before Blob reading and saves every byte with one opaque lease", async () => {
  const calls = [], original = Uint8Array.from([0, 128, 255, 37, 80, 68, 70]);
  const blob = new Blob([original], { type: "application/pdf" });
  const read = blob.arrayBuffer.bind(blob);
  blob.arrayBuffer = async () => { assert.equal(calls[0].command, "prepare_download"); return read(); };
  const save = createNativeSave(async (command, args) => { calls.push({ command, args }); return command === "prepare_download" ? { lease } : { saved: true }; });
  assert.deepEqual(await save({ blob, filename: "evidence.pdf", assertCurrent() {} }), { saved: true });
  assert.deepEqual(calls.map(call => call.command), ["prepare_download", "save_download", "release_download"]);
  assert.equal(calls[1].args.lease, lease);
  assert.deepEqual(Buffer.from(calls[1].args.body_base64, "base64"), Buffer.from(original));
});

test("fences before/after prepare, Blob read and final IPC all reject without save", async () => {
  for (const stage of ["before", "prepare", "read", "encode"]) {
    let current = stage !== "before", reads = 0; const calls = [], stale = new Error("stale");
    const blob = { type: "application/pdf", async arrayBuffer() { reads++; if (stage === "read") current = false; return new Uint8Array([1]).buffer; } };
    if (stage === "encode") Object.defineProperty(blob, "type", { get() { current = false; return "application/pdf"; } });
    const save = createNativeSave(async command => { calls.push(command); if (stage === "prepare" && command === "prepare_download") current = false; return command === "prepare_download" ? { lease } : { saved: true }; });
    await assert.rejects(save({ blob, filename: "evidence.pdf", assertCurrent() { if (!current) throw stale; } }), error => error === stale);
    assert.equal(calls.includes("save_download"), false, stage);
    assert.equal(reads, ["before", "prepare"].includes(stage) ? 0 : 1, stage);
    assert.equal(calls.filter(command => command === "release_download").length, stage === "before" ? 0 : 1, stage);
  }
});

test("abort during prepare releases the late lease without reading or saving", async () => {
  const prepare = deferred(), calls = [], controller = new AbortController(); let reads = 0;
  const save = createNativeSave(async command => { calls.push(command); return command === "prepare_download" ? prepare.promise : { saved: true }; });
  const operation = save({ blob: { async arrayBuffer() { reads++; return new ArrayBuffer(1); } }, filename: "evidence.pdf", signal: controller.signal });
  controller.abort(); prepare.resolve({ lease });
  await assert.rejects(operation, { name: "AbortError" });
  assert.equal(reads, 0); assert.equal(calls.includes("save_download"), false);
  assert.ok(calls.includes("release_download"));
});

test("pending native picker receives release immediately on owner/selection abort", async () => {
  const picker = deferred(), calls = [], controller = new AbortController();
  const save = createNativeSave(async (command, args) => {
    calls.push({ command, args });
    if (command === "prepare_download") return { lease };
    if (command === "save_download") return picker.promise;
    if (command === "release_download") throw new Error("private-path cleanup failure");
  });
  const operation = save({ blob: new Blob(["bytes"]), filename: "evidence.pdf", signal: controller.signal });
  await flush(); assert.equal(calls.at(-1).command, "save_download");
  controller.abort();
  assert.equal(calls.at(-1).command, "release_download"); assert.equal(calls.at(-1).args.lease, lease);
  picker.resolve({ saved: true }); await assert.rejects(operation, { name: "AbortError" });
  const count = calls.length; controller.abort(); assert.equal(calls.length, count);
});

test("late native errors recheck the fence and unsupported prepare fails closed", async () => {
  const pending = deferred(), stale = new Error("stale"); let current = true;
  const save = createNativeSave(async command => command === "prepare_download" ? { lease } : command === "save_download" ? pending.promise : undefined);
  const operation = save({ blob: new Blob(["x"]), filename: "evidence.pdf", assertCurrent() { if (!current) throw stale; } });
  await flush(); current = false; pending.reject(new Error("private-path"));
  await assert.rejects(operation, error => error === stale);
  let read = false, saved = false;
  const unsupported = createNativeSave(async command => { if (command === "save_download") saved = true; return { saved: true }; });
  await assert.rejects(unsupported({ blob: { async arrayBuffer() { read = true; return new ArrayBuffer(0); } }, filename: "evidence.pdf" }), error => error.code === "DOWNLOAD_AUTHORITY_UNAVAILABLE");
  assert.equal(read, false); assert.equal(saved, false);
});
