/** Public SDK completion boundary only: real Responses, injected transport, no HTTP or browser claim. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { setImmediate } from "node:timers/promises";
import { setApiTransport, tireApi } from "@tire/api-client";

function controlled204(readFailure?: Error) {
  const response = new Response(null, { status: 204 });
  const readEmptyBody = response.arrayBuffer.bind(response);
  let release!: () => void;
  const boundary = new Promise<void>(resolve => { release = resolve; });
  let reads = 0;
  // A 204 Response cannot contain a ReadableStream; control its real instance's read boundary instead.
  response.arrayBuffer = async () => {
    reads++;
    await boundary;
    if (readFailure) throw readFailure;
    return readEmptyBody();
  };
  return { response, release, readCount: () => reads };
}

function installResponse(response: Response) {
  const calls: { path: string; init: RequestInit }[] = [];
  const restore = setApiTransport(async (path, init) => { calls.push({ path, init }); return response; });
  return { calls, restore };
}

await test("unwatch stays pending until the 204 body read completes, then returns undefined", { timeout: 5000 }, async () => {
  const body = controlled204(), transport = installResponse(body.response);
  const pending = tireApi.unwatch("watch/id?one");
  let settled = false;
  void pending.then(() => { settled = true; }, () => { settled = true; });
  try {
    await setImmediate();
    assert.equal(body.readCount(), 1, "204 completion must enter the Response read boundary");
    assert.equal(settled, false, "HTTP 204 must not settle the SDK promise before its read boundary finishes");
    assert.equal(transport.calls.length, 1);
    assert.equal(transport.calls[0].path, "/v1/watchlists/watch%2Fid%3Fone");
    assert.equal(transport.calls[0].init.method, "DELETE");
    assert.equal(transport.calls[0].init.credentials, "include");
    assert.equal(transport.calls[0].init.cache, "no-store");
    assert.equal(transport.calls[0].init.body, undefined);
    body.release();
    assert.equal(await pending, undefined);
    assert.equal(body.readCount(), 1);
    assert.equal(transport.calls.length, 1, "body completion must not replay the DELETE");
  } finally {
    body.release();
    await pending.catch(() => undefined);
    transport.restore();
  }
});

for (const failure of [new TypeError("Synthetic empty-body read failure"), new DOMException("Synthetic canceled body read", "AbortError")]) {
  await test(`unwatch rejects with the original ${failure.name} from the 204 read without retry`, { timeout: 5000 }, async () => {
    const body = controlled204(failure), transport = installResponse(body.response);
    const pending = tireApi.unwatch("failed-read");
    let fulfilled = false;
    void pending.then(() => { fulfilled = true; }, () => {});
    try {
      await setImmediate();
      assert.equal(body.readCount(), 1);
      assert.equal(fulfilled, false);
      body.release();
      await assert.rejects(pending, cause => cause === failure, "read rejection must retain its identity instead of resolving undefined or remapping");
      await setImmediate();
      assert.equal(fulfilled, false);
      assert.equal(body.readCount(), 1);
      assert.equal(transport.calls.length, 1, "a failed body read must not resend the DELETE");
    } finally {
      body.release();
      await pending.catch(() => undefined);
      transport.restore();
    }
  });
}

await test("unwatch accepts an unmodified real empty 204 Response and keeps its undefined result", { timeout: 5000 }, async () => {
  const transport = installResponse(new Response(null, { status: 204 }));
  try {
    assert.equal(await tireApi.unwatch("empty-response"), undefined);
    assert.equal(transport.calls.length, 1);
    assert.equal(transport.calls[0].init.method, "DELETE");
  } finally { transport.restore(); }
});
