import { strict as assert } from "node:assert";
import { test } from "node:test";

import { DEFAULT_ROUTE_VIEW, nativeBackRoute, parseRouteHash, serializeRouteHash } from "../components/route-hash.ts";

test("parses bare view hashes", () => {
  for (const view of ["home", "query", "vehicles", "garage", "compare", "watch", "sources"] as const) {
    assert.deepEqual(parseRouteHash("#/" + view), { view });
  }
});

test("parses compare ids with trim and four-item cap", () => {
  assert.deepEqual(parseRouteHash("#/compare?ids=a,b"), { view: "compare", compareIds: ["a", "b"] });
  assert.deepEqual(parseRouteHash("#/compare?ids=a,,b,"), { view: "compare", compareIds: ["a", "b"] });
  assert.deepEqual(parseRouteHash("#/compare?ids=1,2,3,4,5,6"), { view: "compare", compareIds: ["1", "2", "3", "4"] });
  assert.deepEqual(parseRouteHash("#/compare"), { view: "compare" });
  // ids 参数只对 compare 有意义。
  assert.deepEqual(parseRouteHash("#/watch?ids=a,b"), { view: "watch" });
});

test("parses query size prefill after url decoding", () => {
  assert.deepEqual(parseRouteHash("#/query?size=" + encodeURIComponent("245/40 R20")),
    { view: "query", size: "245/40 R20" });
  assert.deepEqual(parseRouteHash("#/query?size=%20%20"), { view: "query" });
  assert.deepEqual(parseRouteHash("#/compare?size=225"), { view: "compare" });
});

test("rejects non-route hashes", () => {
  for (const invalid of ["", "#", "#main-content", "#/unknown", "#/query/extra", "#query", "#/"]) {
    assert.equal(parseRouteHash(invalid), null, invalid);
  }
});

test("serializes and round-trips canonical states", () => {
  assert.equal(serializeRouteHash({ view: "home" }), "#/home");
  assert.equal(serializeRouteHash({ view: "query" }), "#/query");
  assert.equal(serializeRouteHash({ view: "compare", compareIds: ["a", "b"] }), "#/compare?ids=a%2Cb");
  assert.equal(serializeRouteHash({ view: "query", size: "245/40 R20" }), "#/query?size=245%2F40+R20");
  for (const hash of ["#/garage", "#/compare?ids=a,b,c", "#/query?size=" + encodeURIComponent("225/45 R18")]) {
    const state = parseRouteHash(hash)!;
    assert.deepEqual(parseRouteHash(serializeRouteHash(state)), state, hash);
  }
});

test("home is the default and native back target while query deep links remain direct", () => {
  assert.equal(DEFAULT_ROUTE_VIEW, "home");
  assert.equal(nativeBackRoute("home"), null);
  for (const view of ["query", "vehicles", "garage", "compare", "watch", "sources"] as const) assert.equal(nativeBackRoute(view), "home");
  assert.deepEqual(parseRouteHash("#/query"), { view: "query" });
  assert.deepEqual(parseRouteHash("#/home?ids=private&size=225"), { view: "home" });
  assert.equal(parseRouteHash("#"), null);
});
