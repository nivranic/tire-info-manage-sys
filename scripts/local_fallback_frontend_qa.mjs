import assert from "node:assert/strict";
import test from "node:test";
import { loadOfflineTypeScript } from "./load_offline_typescript.mjs";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";
const values = await loadOfflineTypeScript("../apps/web/components/local-fallback-values.ts", import.meta.url);
const { LocalFallbackController } = await loadOfflineTypeScript("../apps/web/components/local-fallback-controller.ts", import.meta.url);
const sdk = await loadOfflineTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const mobile = await loadTypeScript("../apps/mobile/src/native-platform.ts", import.meta.url);
const query = { model: "Pilot Sport EV", size: "245/40 ZR20" };
const intent = await values.createFallbackIntent(query, [], "fixture-source", 3, { scope: "api_transport", reason: "api_network_unavailable", query_id: null }, crypto.randomUUID());
const request = { intent, slot_id: crypto.randomUUID(), expected_generation: 1, expected_sha256: "a".repeat(64), expected_profile_id: "profile", expected_owner_epoch: 0, decision: "allow" };
const receiptTime = Date.now();
const receipt = (state) => ({ schema: "device-fallback-grant@1", id: crypto.randomUUID(), scope: "local_once", state, intent, profile_id: "profile", owner_epoch: 0, slot_id: request.slot_id, generation: 1, package_sha256: request.expected_sha256, decided_at: new Date(receiptTime).toISOString(), expires_at: new Date(receiptTime+300000).toISOString(), consumed_at: state === "consumed" ? new Date().toISOString() : null });

test("strict intent fields, enum whitelist, empty filters and zero epoch", async () => {
  values.validateFallbackDecision(request);
  for (const mutate of [x=>x.intent.filters.push({field:"xl"}),x=>x.intent.query.extra=true,x=>x.intent.failure.reason="source_fetch_failed",x=>x.intent.failure.query_id=crypto.randomUUID(),x=>x.intent.query.model="",x=>x.expected_owner_epoch=-1,x=>x.expected_generation=0,x=>x.unknown=true]) {
    const changed=structuredClone(request); mutate(changed); assert.throws(()=>values.validateFallbackDecision(changed),{code:"OFFLINE_FALLBACK_INVALID"});
  }
  assert.equal(await values.createFallbackIntent(query, [{field:"xl"}], "fixture-source", 3, intent.failure, crypto.randomUUID()), null);
  assert.equal(await values.createFallbackIntent({size:"225/45 R18"}, [], "fixture-source", 3, intent.failure, crypto.randomUUID()), null);
});
test("offline network failure cannot authorize malformed or oversized ordinary tyre input", async () => {
  const failure=values.fallbackFailure(new sdk.ApiTransportError("api_network_unavailable"),"fixture-source");
  for(const size of ["invalid","099/40R20","456/40R20","265/19R20","265/96R20","265/40R09","265/40R31","265/40R20.2","265/40R30.5","265/40                R20"]) {
    assert.equal(await values.createFallbackIntent({model:"Fixture Tire",size},[],"fixture-source",3,failure,crypto.randomUUID()),null,size);
  }
  assert.equal(await values.createFallbackIntent({model:"m".repeat(121)},[],"fixture-source",3,failure,crypto.randomUUID()),null);
  const accepted=await values.createFallbackIntent({model:"Fixture Tire",size:"265/40 ZR20"},[],"fixture-source",3,failure,crypto.randomUUID());
  assert.equal(accepted.query.size,"265/40 ZR20");
});
test("full structured intent equality and R/ZR/source exact membership", () => {
  const member={reference:{kind:"tire"},source:{source_id:"fixture-source"},payload:{variant:{...query},field_resolution:{other_source:true}}};
  assert.equal(values.fallbackMemberMatches(member,intent),true);
  assert.equal(values.fallbackMemberMatches({...member,payload:{variant:{...query,size:"245/40 R20"}}},intent),false);
  assert.equal(values.fallbackMemberMatches({...member,source:{source_id:"other"}},intent),false);
  const copy=structuredClone(intent);copy.query.model="Other";copy.query_fingerprint=intent.query_fingerprint;
  assert.notEqual(values.fallbackIntentKey(copy),values.fallbackIntentKey(intent));
  assert.equal(member.payload.field_resolution.other_source,true);
});
test("formal failure gate excludes permission/parser/cancellation/live and generic objects", () => {
  assert.equal(values.fallbackFailure(new Error("network failed"),"fixture-source"),null);
  assert.equal(values.fallbackFailure({code:"api_network_unavailable"},"fixture-source"),null);
  for(const data_state of ["live","live_verified_304","local_snapshot"]) assert.equal(values.fallbackFailure({source_id:"fixture-source",query_id:crypto.randomUUID(),data_state,reason:"upstream_timeout"},"fixture-source"),null);
  for(const reason of ["source_fetch_failed","source_paused","source_access_changed","parser_timeout"]) assert.equal(values.fallbackFailure({source_id:"fixture-source",query_id:crypto.randomUUID(),data_state:"source_unavailable",reason},"fixture-source"),null);
  assert.equal(values.fallbackFailure({source_id:"fixture-source",query_id:crypto.randomUUID(),data_state:"source_unavailable",reason:"upstream_timeout"},"fixture-source").scope,"source_response");
});
test("actual fetch rejection permits caller-observed failure; HTTP500/403 and bad JSON do not", async () => {
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async()=>{throw new TypeError("fetch failed")};
    await assert.rejects(sdk.tireApi.health(),error=>values.fallbackFailure(error,"fixture-source")?.reason === "api_network_unavailable");
    for(const status of [500,403]) {globalThis.fetch=async()=>new Response("proxy failure",{status});await assert.rejects(sdk.tireApi.health(),error=>error.status===status && values.fallbackFailure(error,"fixture-source")===null);}
    globalThis.fetch=async()=>new Response("not JSON",{status:200}); await assert.rejects(sdk.tireApi.health(),error=>values.fallbackFailure(error,"fixture-source")===null);
    globalThis.fetch=async()=>({ok:true,status:200,json:async()=>{throw new TypeError("body read failed")}});await assert.rejects(sdk.tireApi.health(),error=>error instanceof TypeError && values.fallbackFailure(error,"fixture-source")===null);
  } finally {globalThis.fetch=original;}
});
test("controlled timeout and caller cancellation remain distinct", async () => {
  const fetch=globalThis.fetch, timer=globalThis.setTimeout;
  try {
    globalThis.setTimeout=(callback,_ms)=>timer(callback,0);
    globalThis.fetch=async(_url,init)=>new Promise((_resolve,reject)=>{if(init.signal.aborted)reject(new DOMException("cancel","AbortError"));else init.signal.addEventListener("abort",()=>reject(new DOMException("timeout","AbortError")));});
    await assert.rejects(sdk.tireApi.health(),{code:"api_timeout"});
    const controller=new AbortController(); controller.abort();
    await assert.rejects(sdk.tireApi.health(controller.signal),error=>error.name==="AbortError" && values.fallbackFailure(error,"fixture-source")===null);
  } finally {globalThis.fetch=fetch;globalThis.setTimeout=timer;}
});
test("native precise transport codes only; generic request failures excluded", async () => {
  for(const [code,expected] of [["API_UNAVAILABLE","api_network_unavailable"],["api_unavailable","api_network_unavailable"],["API_TIMEOUT","api_timeout"],["request_timeout","api_timeout"],["API_REQUEST_FAILED",null],["request_failed",null]]) {
    const restore=sdk.setApiTransport(async()=>{throw {code}});
    try {await assert.rejects(sdk.tireApi.health(),error=>expected ? values.fallbackFailure(error,"fixture-source")?.reason===expected : values.fallbackFailure(error,"fixture-source")===null);}finally{restore();}
  }
});
test("controller metadata and denial never consume/search/read; invalidation discards late grant", async () => {
  const calls=[];let resolve;
  const storage={list:async()=>{calls.push("list");return {items:[]}},decideFallback:async()=>{calls.push("decide");return receipt("denied")},consumeFallback:async()=>assert.fail("must not consume"),revokeFallback:async()=>calls.push("revoke"),search:async()=>assert.fail(),read:async()=>assert.fail()};
  const controller=new LocalFallbackController(storage);await controller.metadata();await controller.answer({...request,decision:"deny"});assert.deepEqual(calls,["list","decide"]);
  storage.decideFallback=()=>new Promise(done=>{resolve=done}); const pending=controller.answer(request);controller.invalidate();resolve(receipt("allowed"));assert.equal(await pending,null);assert.equal(calls.at(-1),"revoke");
});
test("controller rejects double click and ignores late consumed results after query edit", async () => {
  let done;const storage={decideFallback:async()=>receipt("allowed"),consumeFallback:()=>new Promise(resolve=>done=resolve),revokeFallback:async()=>({revoked:true})};
  const controller=new LocalFallbackController(storage), pending=controller.answer(request);await Promise.resolve();
  await assert.rejects(controller.answer(request),{code:"OFFLINE_FALLBACK_USED"});controller.invalidate();done({});assert.equal(await pending,null);
});
test("native and Android use exact three fallback commands and request envelope",async()=>{
  const calls=[],storage=native.createNativeOfflineStorage(async(command,args)=>{calls.push({command,args});return {};});
  await storage.decideFallback(request);await storage.consumeFallback({grant_id:request.slot_id,intent});await storage.revokeFallback({grant_id:request.slot_id});
  assert.deepEqual(calls.map(x=>x.command),["offline_fallback_decide","offline_fallback_consume","offline_fallback_revoke"]);assert.deepEqual(calls[0].args,{request});
  const androidCalls=[],plugin=Object.fromEntries(["offlineFallbackDecide","offlineFallbackConsume","offlineFallbackRevoke"].map(name=>[name,async args=>{androidCalls.push({name,args});return {}}]));
  const android=native.createNativeOfflineStorage(mobile.createMobileInvoke(plugin));await android.decideFallback(request);await android.consumeFallback({grant_id:request.slot_id,intent});await android.revokeFallback({grant_id:request.slot_id});
  assert.deepEqual(androidCalls.map(x=>x.name),["offlineFallbackDecide","offlineFallbackConsume","offlineFallbackRevoke"]);
});
