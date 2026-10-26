/** Synthetic handwritten public wire cases; injected transport, no HTTP/receiver. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ApiError, WebhookContractError, setApiTransport, tireApi } from "@tire/api-client";
import type { Webhook, WebhookCreate, WebhookDelivery, WebhookOperation, WebhookTargets } from "@tire/domain-types";

type Equal<A,B> = (<T>()=>T extends A?1:2) extends (<T>()=>T extends B?1:2) ? true : false;
type Assert<T extends true> = T;
type Result = Assert<Equal<Awaited<ReturnType<typeof tireApi.createWebhook>>, WebhookOperation>>;
type History = Assert<Equal<WebhookOperation["current"], false>>;
// @ts-expect-error Receiver URLs and keys are not user-controlled wire fields.
const forbiddenTarget: WebhookCreate = { url: "https://fixture.invalid", signing_key: "secret" };
// @ts-expect-error The dedicated action response cannot be replaced by a current resource.
const current: WebhookOperation["current"] = true;

const key="297dd735-0caf-4109-ae59-c93c951df0ef", hash="a".repeat(64), instant="2026-10-18T00:00:00+00:00";
const targets: WebhookTargets={schema:"webhook-targets@1",catalog_state:"ready",items:[{id:"managed",title:"Synthetic receiver",endpoint_host:"fixture.invalid",ready:true,state:"ready",policy_fingerprint:hash}],notice:"目录不证明接收端或Worker可用。"};
const subscription: Webhook={schema:"webhook@1",id:"webhook",owner_scope:"current_account",revision:1,revision_id:"revision",name:"Synthetic paused subscription",target_id:"managed",target_fingerprint:hash,endpoint_host:"fixture.invalid",channels:["tire_monitor"],enabled:false,archived:false,created_at:instant,updated_at:instant,readiness:"paused",suppressed_count:0,last_suppressed_at:null,notice:"引用外发，不含来源事实。"};
const payload: WebhookCreate={name:subscription.name,target_id:subscription.target_id,target_fingerprint:hash,channels:["tire_monitor"],enabled:false,acknowledged_external_delivery:false};
// Independently handwritten canonical UTF-8 body, not emitted by the SDK serializer.
const raw='{"channel":"tire_monitor","data_scope":"notification_reference_only","delivery_id":"delivery","domain":null,"event_id":"alert-event","notice":"通知引用，不含来源事实。","notification_id":"notification","occurred_at":"2026-10-18T00:00:00+00:00","schema":"tire-webhook-event@1"}';
const delivered: WebhookDelivery={schema:"webhook-delivery@1",id:"delivery",webhook_id:"webhook",webhook_revision:1,channel:"tire_monitor",notification_id:"notification",event_id:"alert-event",domain:null,state:"failed",attempts:1,max_attempts:5,next_attempt_at:null,created_at:instant,completed_at:instant,error_code:"request_timeout",http_status:null,body_sha256:createHash("sha256").update(raw).digest("hex"),body:JSON.parse(raw),attempt_history:[{number:1,started_at:instant,completed_at:instant,state:"unknown",error_code:"request_timeout",http_status:null}],current:false};
const operation: WebhookOperation={schema:"webhook-operation@1",id:"operation",idempotency_key:key,action:"create",created_at:instant,resource_type:"webhook",resource_id:"webhook",response:subscription,current:false,replayed:false};
let response: unknown=targets,status=200,throwing=false,checks=0;
const calls:{path:string;init:RequestInit}[]=[];
const restore=setApiTransport(async(path,init)=>{calls.push({path,init}); if(init.signal?.aborted) throw new DOMException("aborted","AbortError"); if(throwing) throw Object.assign(new Error("synthetic timeout"),{code:"request_timeout"}); return new Response(JSON.stringify(status===200?response:{detail:{code:"webhook_state_changed",message:"safe rejection"}}),{status});});
const passed=()=>{checks++;};
try {
  const controller=new AbortController();
  assert.deepEqual(await tireApi.webhookTargets(controller.signal),targets); let call=calls.at(-1)!;
  assert.equal(call.path,"/v1/webhooks/targets");assert.equal(call.init.signal,controller.signal);assert.equal(call.init.cache,"no-store");assert.equal(call.init.credentials,"include");passed();
  for(const state of ["empty","invalid"] as const){response={...targets,catalog_state:state,items:[]};await tireApi.webhookTargets();passed();}
  response={...targets,items:[{...targets.items[0],ready:false,state:"key_unavailable",policy_fingerprint:null}]}; await tireApi.webhookTargets();passed();
  response=operation;assert.deepEqual(await tireApi.createWebhook(payload,key),operation);call=calls.at(-1)!;assert.equal(call.path,"/v1/webhooks");assert.equal(call.init.method,"POST");assert.equal(new Headers(call.init.headers).get("Idempotency-Key"),key);assert.deepEqual(JSON.parse(String(call.init.body)),payload);passed();
  response={...operation,response:{...subscription,target_fingerprint:null,readiness:"key_unavailable"}};await tireApi.createWebhook({...payload,target_fingerprint:null},key);passed();
  response={schema:"webhooks@1",items:[subscription],total:1,limit:20,offset:0};await tireApi.webhooks();assert.equal(calls.at(-1)!.path,"/v1/webhooks?mode=history&limit=20&offset=0");passed();
  response=subscription;await tireApi.webhook("webhook");assert.equal(calls.at(-1)!.path,"/v1/webhooks/webhook?mode=history");passed();
  const {target_id,...settings}=payload;
  response={...operation,action:"edit",response:{...subscription,revision:2}};await tireApi.editWebhook("webhook",{...settings,expected_revision:1},key);assert.equal(calls.at(-1)!.init.method,"PUT");passed();
  for(const action of ["pause","resume","archive","restore"] as const){response={...operation,action,response:{...subscription,revision:2,enabled:action==="resume",archived:action==="archive",readiness:action==="resume"?"ready":action==="archive"?"archived":"paused"}};await tireApi.webhookState("webhook",{expected_revision:1,action,target_fingerprint:action==="resume"?hash:null,acknowledged_external_delivery:action==="resume"},key);assert.equal(calls.at(-1)!.path,"/v1/webhooks/webhook/state");passed();}
  const {schema,body,attempt_history,current:currentFlag,...summary}=delivered;
  response={schema:"webhook-deliveries@1",items:[summary],total:1,limit:20,offset:0};await tireApi.webhookDeliveries("webhook");assert.equal(calls.at(-1)!.path,"/v1/webhooks/webhook/deliveries?mode=history&limit=20&offset=0");passed();
  response=delivered;assert.deepEqual(await tireApi.webhookDelivery("webhook","delivery"),delivered);passed();
  for(const action of ["retry","cancel"] as const){response={...operation,action,resource_type:"delivery",resource_id:"delivery",response:delivered};await tireApi.webhookDeliveryAction("webhook","delivery",action,{expected_attempts:1,acknowledged:true},key);assert.equal(calls.at(-1)!.path,`/v1/webhooks/webhook/deliveries/delivery/${action}`);passed();}
  response={...operation,replayed:true};await tireApi.webhookOperation(key);assert.equal(calls.at(-1)!.path,`/v1/webhook-operations?mode=history&key=${key}`);assert.equal(calls.at(-1)!.init.method,undefined);passed();
  for(const change of [
    (v:any)=>{v.items[0].url="https://private.invalid/path";},(v:any)=>{v.items[0].ready=1;},(v:any)=>{v.items[0].state=["ready"];},
    (v:any)=>{v.items[0].policy_fingerprint=null;},(v:any)=>{v.catalog_state="empty";},(v:any)=>{v.items.push(v.items[0]);},
    (v:any)=>{v.items[0].endpoint_host="127.0.0.1";},(v:any)=>{v.items[0].endpoint_host="0x7f000001";},
  ]){response=structuredClone(targets);change(response);await assert.rejects(tireApi.webhookTargets(),WebhookContractError);passed();}
  for(const change of [
    (v:any)=>{v.owner_scope="other_account";},(v:any)=>{v.revision=true;},(v:any)=>{v.channels.push("tire_monitor");},
    (v:any)=>{v.channels=["recall_discovery"];},(v:any)=>{v.endpoint_host="https://fixture.invalid/path";},(v:any)=>{v.created_at="2026-10-18T00:00:00";},
    (v:any)=>{v.readiness=["paused"];},(v:any)=>{v.id="foreign";},(v:any)=>{v.enabled=true;v.target_fingerprint=null;},
  ]){response=structuredClone(subscription);change(response);await assert.rejects(tireApi.webhook("webhook"),WebhookContractError);passed();}
  for(const change of [
    (v:any)=>{v.body.facts={};},(v:any)=>{v.body.delivery_id="foreign";},(v:any)=>{v.body.notice="mutated";},
    (v:any)=>{v.domain="tire";v.body.domain="tire";},(v:any)=>{v.attempts=true;},(v:any)=>{v.max_attempts=0;},
    (v:any)=>{v.attempt_history[0].number=2;},(v:any)=>{v.attempt_history[0].state="received_exactly_once";},
    (v:any)=>{v.http_status=600;},(v:any)=>{v.error_code="https://private.invalid?secret";},(v:any)=>{v.current=true;},
    (v:any)=>{v.webhook_id="foreign";},(v:any)=>{v.body_sha256=hash;},
  ]){response=structuredClone(delivered);change(response);await assert.rejects(tireApi.webhookDelivery("webhook","delivery"),WebhookContractError);passed();}
  for(const change of [
    (v:any)=>{v.idempotency_key="6488ecfb-30a1-49c6-9e9c-9a5cb328ee9f";},(v:any)=>{v.resource_id="foreign";},
    (v:any)=>{v.action="retry";},(v:any)=>{v.current=true;},(v:any)=>{v.response.url="https://private.invalid";},
    (v:any)=>{v.response.revision=2;},(v:any)=>{v.response.target_id="foreign";},(v:any)=>{v.response.target_fingerprint="b".repeat(64);},
    (v:any)=>{v.response.channels=["recall_monitor"];},(v:any)=>{v.response.enabled=true;v.response.readiness="ready";},
  ]){response=structuredClone(operation);change(response);await assert.rejects(tireApi.createWebhook(payload,key),WebhookContractError);passed();}
  const before=calls.length;
  await assert.rejects(tireApi.createWebhook({...payload,actor:"other"} as any,key),WebhookContractError);passed();
  await assert.rejects(tireApi.createWebhook({...payload,channels:[]},key),WebhookContractError);passed();
  await assert.rejects(tireApi.createWebhook({...payload,enabled:true},key),WebhookContractError);passed();
  await assert.rejects(tireApi.createWebhook(payload,"not-a-uuid"),WebhookContractError);passed();
  await assert.rejects(tireApi.webhookState("webhook",{expected_revision:1,action:"resume",target_fingerprint:null,acknowledged_external_delivery:true},key),WebhookContractError);passed();
  await assert.rejects(tireApi.webhookDeliveryAction("webhook","delivery","cancel",{expected_attempts:1,acknowledged:false} as any,key),WebhookContractError);passed();
  for(const [offset,limit]of [[-1,20],[0,0],[0,101],[10001,20],[0.5,20]]){await assert.rejects(tireApi.webhooks(offset,limit),WebhookContractError);passed();}
  assert.equal(calls.length,before);
  throwing=true;const prior=calls.length;await assert.rejects(tireApi.createWebhook(payload,key),e=>e instanceof Error&&"code"in e&&e.code==="api_timeout");assert.equal(calls.length,prior+1);passed();
  throwing=false;response={...operation,replayed:true};await tireApi.webhookOperation(key);assert.equal(calls.length,prior+2);assert.equal(calls.at(-1)!.init.method,undefined);passed();
  status=404;await assert.rejects(tireApi.webhookOperation(key),e=>e instanceof ApiError&&e.status===404);assert.equal(calls.length,prior+3);passed();
  for(const code of [401,403,409,422]){status=code;const n=calls.length;await assert.rejects(tireApi.createWebhook(payload,key),e=>e instanceof ApiError&&e.status===code);assert.equal(calls.length,n+1);passed();}
  status=200;controller.abort();await assert.rejects(tireApi.webhookTargets(controller.signal),e=>e instanceof DOMException&&e.name==="AbortError");passed();
  console.log(`webhooks: ${checks} public wire/transport checks passed; injected transport only, no backend/external receiver acceptance`);
} finally {restore();}
