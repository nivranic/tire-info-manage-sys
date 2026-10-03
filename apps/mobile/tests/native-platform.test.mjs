import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadTypeScript } from "../../../packages/native-client/tests/load-typescript.mjs";

const shared = await loadTypeScript("../../../packages/native-client/src/index.ts", import.meta.url);
const { createMobileInvoke, createMobilePlatform, mobileError, validateMobileStatus } = await loadTypeScript("../src/native-platform.ts", import.meta.url);
const { consumeMobileBack } = await loadTypeScript("../src/back-navigation.ts", import.meta.url);
const status = { platform: "android", mode: "debug-local", api_base_url: "http://127.0.0.1:8000", session_store: "android_keystore", session_persistent: true, version: "0.1.0" };
const response = (body = "{}", mime = "application/json") => ({ status: 200, headers: { "content-type": mime }, body_base64: Buffer.from(body).toString("base64") });

test("Capacitor adapter maps exact command names and keeps binary payloads snake_case", async () => {
  const calls = [];
  const plugin = {
    apiRequest: async args => { calls.push(["apiRequest", args]); return response(Uint8Array.from([0, 128, 255]), "application/pdf"); },
    saveDownload: async args => { calls.push(["saveDownload", args]); return { saved: false }; },
    openExternal: async args => { calls.push(["openExternal", args]); },
  };
  const invoke = createMobileInvoke(plugin);
  const transport = shared.createNativeTransport(invoke);
  const file = new File([Uint8Array.from([37, 80, 68, 70, 0, 128, 255])], "原文.pdf", { type: "application/pdf" });
  const value = await transport("/v1/documents", { method: "POST", body: file, headers: { "Content-Type": "application/pdf" } });
  assert.deepEqual(new Uint8Array(await value.arrayBuffer()), Uint8Array.from([0, 128, 255]));
  assert.equal(calls[0][0], "apiRequest");
  assert.deepEqual(Buffer.from(calls[0][1].request.body_base64, "base64"), Buffer.from(await file.arrayBuffer()));
  const platform = createMobilePlatform(invoke);
  assert.equal(platform.kind, "mobile");
  assert.deepEqual(await platform.saveDownload({ blob: file, filename: "原文.pdf" }), { saved: false });
  assert.equal(calls[1][0], "saveDownload");
  assert.equal(calls[1][1].mime, "application/pdf");
  await shared.openNativeExternal(invoke, "https://example.test/evidence");
  assert.deepEqual(calls[2], ["openExternal", { url: "https://example.test/evidence" }]);
});

test("Capacitor Error codes retain safe native errors without leaking native messages", async () => {
  const nativeFailure = Object.assign(new Error("private-file-or-cookie"), { code: "SESSION_STORE_WRITE_FAILED" });
  const transport = shared.createNativeTransport(createMobileInvoke({ apiRequest: async () => { throw nativeFailure; } }));
  await assert.rejects(transport("/health", {}), error => error instanceof shared.NativeError && error.code === "SESSION_STORE_WRITE_FAILED" && !error.message.includes("private-file"));
  assert.equal(mobileError(new Error("RELEASE_API_NOT_CONFIGURED")).code, "RELEASE_API_NOT_CONFIGURED");
  assert.equal(mobileError({ message: "session-cookie=secret", code: "UNKNOWN_SECRET" }).code, "request_failed");
});

test("mobile abort uses apiCancel with the matching id and ignores late replies", async () => {
  const controller = new AbortController();
  const calls = [];
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const transport = shared.createNativeTransport(createMobileInvoke({
    apiRequest: async args => { calls.push(["request", args]); return pending; },
    apiCancel: async args => { calls.push(["cancel", args]); },
  }));
  const request = transport("/v1/reports", { method: "POST", signal: controller.signal });
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  assert.equal(calls[0][1].request.id, calls[1][1].id);
  finish(response());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 2);
});

test("release, insecure stores and non-loopback native status remain closed", () => {
  assert.doesNotThrow(() => validateMobileStatus(status));
  for (const invalid of [
    { ...status, mode: "release-unconfigured", error: "RELEASE_API_NOT_CONFIGURED" },
    { ...status, session_store: "plaintext" }, { ...status, session_persistent: false },
    { ...status, api_base_url: "https://example.test" }, { ...status, api_base_url: "http://user:secret@127.0.0.1:8000" },
    { ...status, api_base_url: "http://127.0.0.1:8000/private" }, { ...status, platform: "web" },
  ]) assert.throws(() => validateMobileStatus(invalid), shared.NativeError);
});

test("back delegates to focused dialog cancel policy before changing workbench", () => {
  const calls = [];
  const dialog = new EventTarget();
  dialog.addEventListener("cancel", event => { assert.equal(event.cancelable, true); event.preventDefault(); calls.push("cancel"); });
  const document = { querySelectorAll: () => [dialog], activeElement: { closest: () => dialog } };
  assert.equal(consumeMobileBack(document, () => { calls.push("workbench"); return true; }), true);
  assert.deepEqual(calls, ["cancel"]);
  const plain = { querySelectorAll: () => [], activeElement: null };
  assert.equal(consumeMobileBack(plain, () => true), true);
  assert.equal(consumeMobileBack(plain, () => false), false);
});

test("mobile shell cannot directly fetch remote resources or register a service worker", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /worker-src 'none'/);
  assert.doesNotMatch(html, /manifest\.webmanifest|sw\.js/);
  const config = await readFile(new URL("../capacitor.config.ts", import.meta.url), "utf8");
  assert.match(config, /CapacitorHttp: \{ enabled: false \}/);
  assert.match(config, /CapacitorCookies: \{ enabled: false \}/);
  assert.match(config, /loggingBehavior: "none"/);
  assert.doesNotMatch(config, /allowNavigation|url\s*:/);
});
