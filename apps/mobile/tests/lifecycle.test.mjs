import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { loadTypeScript } from "../../../packages/native-client/tests/load-typescript.mjs";

const shared = await loadTypeScript("../../../packages/native-client/src/index.ts", import.meta.url);
const mobile = await loadTypeScript("../src/native-platform.ts", import.meta.url);
const modalLifecycle = await loadTypeScript("../src/modal-lifecycle.ts", import.meta.url);
const source = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const status = { platform: "android", mode: "debug-local", api_base_url: "http://127.0.0.1:8000", session_store: "android_keystore", session_persistent: true, version: "0.1.0" };
const response = () => ({ status: 200, headers: { "content-type": "application/json" }, body_base64: Buffer.from("{}").toString("base64") });
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

// Execute the actual shell with native IPC and React scheduling replaced by controlled boundaries.
// The shared transport remains real, including its cancellation and fixed native error mapping.
async function shell() {
  let transport;
  let component;
  let checkConnection;
  const phases = [];
  const effects = [];
  const writes = [];
  const ownerEvents = [];
  let resets = 0;
  const react = {
    StrictMode() {},
    useState(initial) {
      let value = initial;
      return [value, next => {
        value = typeof next === "function" ? next(value) : next;
        if (initial === "connecting") phases.push(value);
      }];
    },
    useRef: current => ({ current }),
    useCallback: callback => { checkConnection = callback; return callback; },
    useEffect: effect => { effects.push(effect); },
    useLayoutEffect() {},
  };
  const native = {
    status: async () => status,
    resetSession: async () => { resets += 1; },
    apiRequest: async ({ request }) => {
      if (request.method === "POST") {
        const pending = deferred();
        writes.push({ request, ...pending });
        return pending.promise;
      }
      return response();
    },
    apiCancel: async () => {},
  };
  const modules = {
    react,
    "react/jsx-runtime": { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    "react-dom/client": { createRoot: () => ({ render: tree => { component = tree.props.children.type; } }) },
    "@capacitor/core": { Capacitor: { isNativePlatform: () => true, getPlatform: () => "android" }, registerPlugin: () => native },
    "@tire/api-client": { setApiTransport: value => { transport = value; }, tireApi: { health: signal => transport("/health", { signal }) } },
    "@tire/native-client": shared,
    "./native-platform": mobile,
    "./modal-lifecycle": modalLifecycle,
    "./back-navigation": { consumeMobileBack: () => false },
    "./device-ai-panel": { MobileDeviceAiEntry() {} },
    "../../web/components/workbench": { default() {} },
    "../../web/components/offline-library": { OfflineLibraryEntry() {} },
    "../../web/app/globals.css": {},
    "./styles.css": {},
  };
  runInNewContext(compiled, {
    exports: {},
    require(name) { assert.ok(Object.hasOwn(modules, name), `Unexpected import: ${name}`); return modules[name]; },
    document: { getElementById: () => ({}) },
    window: { dispatchEvent: event => { ownerEvents.push(event.type); return true; } },
    AbortController,
    Event,
  }, { filename: "apps/mobile/src/main.tsx" });
  component();
  const cleanup = effects[0]();
  // Supersede the mount check deliberately, as StrictMode and a resume event may do.
  await checkConnection();
  assert.equal(phases.at(-1), "ready");
  return { request: (...args) => transport(...args), checkConnection, writes, phases, cleanup, ownerEvents, resetCount: () => resets };
}

test("late old-session write failure cannot close the newly reset mobile connection", async () => {
  const app = await shell();
  try {
    const oldWrite = app.request("/v1/watchlists", { method: "POST" });
    const rejected = assert.rejects(oldWrite, error => error.code === "SESSION_CHANGED");
    await app.checkConnection(true);
    assert.equal(app.resetCount(), 1);
    assert.deepEqual(app.ownerEvents, ["tire-offline-owner-changed"]);
    app.writes[0].reject("SESSION_CHANGED");
    await rejected;
    assert.equal(app.phases.at(-1), "ready");
    assert.equal((await app.request("/v1/sources", {})).status, 200);
    assert.equal(app.writes.length, 1, "reset must not replay the old write");
  } finally { app.cleanup(); }
});

test("ordinary connection rechecks also ignore delayed errors from the previous connection", async () => {
  const app = await shell();
  try {
    const oldWrite = app.request("/v1/watchlists", { method: "POST" });
    const rejected = assert.rejects(oldWrite, error => error.code === "API_UNAVAILABLE");
    await app.checkConnection();
    app.writes[0].reject("API_UNAVAILABLE");
    await rejected;
    assert.equal(app.phases.at(-1), "ready");
    assert.equal((await app.request("/v1/sources", {})).status, 200);
    assert.equal(app.resetCount(), 0);
    assert.deepEqual(app.ownerEvents, []);
    assert.equal(app.writes.length, 1, "resume must not replay pending writes");
  } finally { app.cleanup(); }
});

test("a failure in the current connection still pauses the mobile workspace without retrying its write", async () => {
  const app = await shell();
  try {
    const currentWrite = app.request("/v1/watchlists", { method: "POST" });
    const rejected = assert.rejects(currentWrite, error => error.code === "SESSION_CHANGED");
    app.writes[0].reject("SESSION_CHANGED");
    await rejected;
    assert.equal(app.phases.at(-1), "failed");
    await assert.rejects(app.request("/v1/sources", {}), error => error.code === "session_unavailable");
    await app.checkConnection();
    assert.equal((await app.request("/v1/sources", {})).status, 200);
    assert.equal(app.writes.length, 1, "manual recovery must not replay the failed write");
  } finally { app.cleanup(); }
});
