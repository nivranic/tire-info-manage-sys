/** SDK signal forwarding and cancellation only; no browser or backend acceptance. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { setApiTransport, tireApi } from "@tire/api-client";

await test("watch/unwatch keep legacy calls and forward each optional signal without changing wire requests", async () => {
  const calls: { path: string; init: RequestInit }[] = [];
  const restore = setApiTransport(async (path, init) => {
    calls.push({ path, init });
    return init.method === "DELETE" ? new Response(null, { status: 204 })
      : Response.json({ id: "watch-1", variant_id: JSON.parse(String(init.body)).variant_id });
  });
  try {
    await tireApi.watch("legacy-variant");
    await tireApi.unwatch("legacy-watch");
    const controller = new AbortController();
    assert.equal((await tireApi.watch("variant/id", controller.signal)).variant_id, "variant/id");
    assert.equal(await tireApi.unwatch("watch/id", controller.signal), undefined);
    assert.equal(calls.length, 4);
    assert.equal(calls[0].init.signal, undefined);
    assert.equal(calls[1].init.signal, undefined);
    assert.equal(calls[2].init.signal, controller.signal);
    assert.equal(calls[3].init.signal, controller.signal);
    assert.equal(calls[2].path, "/v1/watchlists");
    assert.equal(calls[2].init.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[2].init.body)), { variant_id: "variant/id" });
    assert.equal(calls[3].path, "/v1/watchlists/watch%2Fid");
    assert.equal(calls[3].init.method, "DELETE");
    assert.equal(calls[3].init.body, undefined);
    for (const call of calls) {
      assert.equal(call.init.credentials, "include");
      assert.equal(call.init.cache, "no-store");
    }
  } finally { restore(); }
});

for (const operation of ["watch", "unwatch"] as const) {
  await test(`${operation} exposes host cancellation and never retries the write`, async () => {
    let calls = 0;
    const controller = new AbortController();
    const failure = new DOMException("Synthetic caller cancellation", "AbortError");
    const restore = setApiTransport((_path, init) => new Promise((_resolve, reject) => {
      calls++;
      assert.equal(init.signal, controller.signal);
      init.signal!.addEventListener("abort", () => reject(failure), { once: true });
    }));
    try {
      const pending = tireApi[operation]("owned-id", controller.signal);
      const rejected = assert.rejects(pending, cause => cause === failure);
      controller.abort();
      await rejected;
      assert.equal(calls, 1);
    } finally { restore(); }
  });
}

await test("unwatch cancellation still waits for and rejects from the 204 body read", async () => {
  const controller = new AbortController();
  const response = new Response(null, { status: 204 });
  const failure = new DOMException("Synthetic 204 read cancellation", "AbortError");
  let calls = 0, reads = 0;
  let entered!: () => void;
  const reading = new Promise<void>(resolve => { entered = resolve; });
  response.arrayBuffer = () => new Promise((_resolve, reject) => {
    reads++; entered();
    controller.signal.addEventListener("abort", () => reject(failure), { once: true });
  });
  const restore = setApiTransport(async (_path, init) => {
    calls++; assert.equal(init.signal, controller.signal); return response;
  });
  try {
    const pending = tireApi.unwatch("owned-204", controller.signal);
    const rejected = assert.rejects(pending, cause => cause === failure);
    await reading; controller.abort(); await rejected;
    assert.equal(reads, 1); assert.equal(calls, 1);
  } finally { restore(); }
});
