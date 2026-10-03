import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../apps/web/pwa/worker.js", import.meta.url), "utf8");
const origin = "https://tire.example";
const assets = ["/", "/_next/static/a.js", "/icons/icon-192.png", "/manifest.webmanifest"];
function harness({ offline = false, failInstall = false } = {}) {
  const events = new Map(), buckets = new Map(), calls = [], deleted = [];
  let skips = 0, claims = 0;
  const cache = name => {
    if (!buckets.has(name)) buckets.set(name, new Map());
    const entries = buckets.get(name);
    return {
      addAll: async requests => {
        for (const request of requests) {
          calls.push(request);
          if (failInstall) throw new Error("injected install failure");
          entries.set(new URL(request.url).pathname, new Response("<html><head></head><body>static shell: " + new URL(request.url).pathname + "</body></html>"));
        }
      },
      match: async path => entries.get(path)?.clone(),
    };
  };
  const self = { location: { origin }, clients: { claim: async () => { claims++; } },
    skipWaiting: async () => { skips++; }, addEventListener: (name, callback) => events.set(name, callback) };
  const context = vm.createContext({ self, URL, Set, Response, Promise,
    Request: class extends Request { constructor(url, init) { super(new URL(url, origin), init); } },
    caches: { open: async name => cache(name), keys: async () => [...buckets.keys()], delete: async name => { deleted.push(name); return buckets.delete(name); } },
    fetch: async request => { calls.push(request); if (offline) throw new Error("offline"); return new Response("network-only"); },
  });
  vm.runInContext(source.replace("__TIRE_PWA_CONFIG__", JSON.stringify({ version: "current", assets })), context);
  async function dispatch(name, properties = {}) {
    let wait, response;
    events.get(name)({ ...properties, waitUntil: task => { wait = task; }, respondWith: task => { response = task; } });
    await wait;
    return response ? await response : undefined;
  }
  const request = (path, overrides = {}) => ({ url: new URL(path, origin).href, method: "GET", mode: "cors", headers: new Headers(), ...overrides });
  return { dispatch, request, buckets, calls, deleted, counters: () => ({ skips, claims }) };
}

test("install caches only build allowlist, without session credentials", async () => {
  const h = harness(); await h.dispatch("install");
  assert.deepEqual(h.calls.map(request => new URL(request.url).pathname), assets);
  assert(h.calls.every(request => request.credentials === "omit" && request.cache === "reload"));
  assert.equal(h.counters().skips, 0);
});

test("API, evidence, session and mutations are never intercepted even offline", async () => {
  const h = harness({ offline: true }); await h.dispatch("install");
  for (const path of ["/api/health", "/api/v1/sources", "/api/v1/evidence/test", "/api/v1/vehicles", "/api/v1/notifications", "/auth", "/?consent_id=test"]) {
    assert.equal(await h.dispatch("fetch", { request: h.request(path, { mode: "navigate" }) }), undefined);
  }
  assert.equal(await h.dispatch("fetch", { request: h.request("/", { method: "POST", mode: "navigate" }) }), undefined);
});

test("RSC, query strings, cross-origin and ordinary root fetch bypass cache", async () => {
  const h = harness();
  for (const request of [h.request("/"), h.request("/?_rsc=abc"), h.request("/_next/static/a.js?v=1"),
    h.request("/", { mode: "navigate", headers: new Headers({ RSC: "1" }) }),
    h.request("/", { mode: "navigate", headers: new Headers({ "Next-Router-State-Tree": "state" }) }),
    h.request("https://external.example/_next/static/a.js")]) {
    assert.equal(await h.dispatch("fetch", { request }), undefined);
  }
});

test("offline navigation serves only the fixed static shell", async () => {
  const h = harness({ offline: true }); await h.dispatch("install");
  const response = await h.dispatch("fetch", { request: h.request("/", { mode: "navigate" }) });
  assert.equal(await response.text(), '<html><head><meta name="tire-offline-shell" content="true"></head><body>static shell: /</body></html>');
  assert.deepEqual([...h.buckets.get("tire-shell-current").keys()], assets);
});

test("online navigation is network-first and never overwrites the offline shell", async () => {
  const h = harness(); await h.dispatch("install");
  assert.equal(await (await h.dispatch("fetch", { request: h.request("/", { mode: "navigate" }) })).text(), "network-only");
  assert.equal(await h.buckets.get("tire-shell-current").get("/").text(), "<html><head></head><body>static shell: /</body></html>");
});

test("activation cleans only this application's previous shell caches", async () => {
  const h = harness(); h.buckets.set("tire-shell-old", new Map()); h.buckets.set("unrelated-cache", new Map());
  await h.dispatch("install"); await h.dispatch("activate");
  assert.deepEqual(h.deleted, ["tire-shell-old"]); assert.equal(h.counters().claims, 1);
  assert(h.buckets.has("tire-shell-current") && h.buckets.has("unrelated-cache"));
});

test("waiting update activates only on explicit activation message", async () => {
  const h = harness(); await h.dispatch("install");
  await h.dispatch("message", { data: { type: "unrelated" } }); assert.equal(h.counters().skips, 0);
  await h.dispatch("message", { data: { type: "ACTIVATE_UPDATE" } }); assert.equal(h.counters().skips, 1);
});

test("failed install cleans its incomplete cache and leaves old cache", async () => {
  const h = harness({ failInstall: true }); h.buckets.set("tire-shell-old", new Map());
  await assert.rejects(h.dispatch("install"), /injected/);
  assert(!h.buckets.has("tire-shell-current") && h.buckets.has("tire-shell-old"));
});
