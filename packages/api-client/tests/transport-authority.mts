import assert from "node:assert/strict";
import { test } from "node:test";
import { apiTransportAuthorityEpoch, observeApiTransportAuthority, setApiTransport, type ApiTransport } from "@tire/api-client";
import { createRawEvidenceOperations } from "../../../apps/web/components/raw-evidence-v2-context.ts";

test("set and effective restore notify observers synchronously after advancing authority", () => {
  const start = apiTransportAuthorityEpoch(), epochs: number[] = [];
  const stopBad = observeApiTransportAuthority(() => { throw new Error("an observer cannot alter transport installation"); });
  const stop = observeApiTransportAuthority(epoch => { assert.equal(epoch, apiTransportAuthorityEpoch()); epochs.push(epoch); });
  const a: ApiTransport = async () => new Response("a"), b: ApiTransport = async () => new Response("b");
  try {
    const restoreA = setApiTransport(a); assert.deepEqual(epochs, [start + 1]);
    const restoreB = setApiTransport(b); assert.deepEqual(epochs, [start + 1, start + 2]);
    restoreA(); assert.equal(epochs.length, 2, "an ineffective restore preserves existing semantics");
    restoreB(); assert.equal(epochs.at(-1), start + 3);
    restoreA(); assert.equal(epochs.at(-1), start + 4);
  } finally { stop(); stopBad(); }
});

test("pending picker operation aborts/releases in the transport set and restore stack", () => {
  const owner = new AbortController();
  const operations = createRawEvidenceOperations(() => ({ ready: true, ownerEpoch: 1, ownerSignal: owner.signal,
    isCurrentOwner: epoch => epoch === 1, selection: "capture", transportEpoch: apiTransportAuthorityEpoch() }),
  callback => observeApiTransportAuthority(callback));
  const pending = operations.begin(); let releases = 0;
  pending.controller.signal.addEventListener("abort", () => { releases++; });
  const restore = setApiTransport(async () => new Response("test"));
  try {
    assert.equal(releases, 1); assert.ok(pending.controller.signal.aborted);
    const other = operations.begin(); other.controller.signal.addEventListener("abort", () => { releases++; });
    restore(); assert.equal(releases, 2); assert.ok(other.controller.signal.aborted);
  } finally { restore(); operations.invalidate(); }
});
