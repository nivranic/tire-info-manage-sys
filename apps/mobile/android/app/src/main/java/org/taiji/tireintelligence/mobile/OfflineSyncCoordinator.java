package org.taiji.tireintelligence.mobile;

import android.content.Context;
import com.getcapacitor.JSObject;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;
import org.json.JSONArray;
import org.json.JSONObject;

/** Network is outside catalog locks; every stage is journaled before its remote write. */
final class OfflineSyncCoordinator {
    interface Remote {
        String binding() throws NativeFailure;
        void check() throws NativeFailure;
        JSONObject json(String method,String path,JSONObject body,String key,String owner) throws Exception;
        byte[] download(JSONObject descriptor,String owner) throws Exception;
        default <T> T publish(java.util.concurrent.Callable<T> action) throws Exception {check();return action.call();}
    }
    private final OfflinePackStore store;
    private final Remote remote;
    private final Supplier<OfflineSyncConditions.Sample> conditions;
    OfflineSyncCoordinator(OfflinePackStore store,Remote remote,Supplier<OfflineSyncConditions.Sample> conditions) {
        this.store=store;this.remote=remote;this.conditions=conditions;
    }
    static Remote bridge(NativeHttpBridge bridge) throws NativeFailure {
        NativeHttpBridge.SessionFence fence=bridge.freezeSession();
        return new Remote() {
            public String binding() throws NativeFailure {return bridge.sessionBinding(fence);}
            public void check() throws NativeFailure {bridge.checkSession(fence);}
            public JSONObject json(String method,String path,JSONObject body,String key,String owner) throws Exception {
                Map<String,String> headers=new HashMap<>();if(body!=null)headers.put("content-type","application/json");if(key!=null)headers.put("idempotency-key",key);
                byte[] bytes=body==null?new byte[0]:OfflineJsonInteger.stringify(body).getBytes(StandardCharsets.UTF_8);
                try {
                    NativePolicy.Request request=new NativePolicy.Request(UUID.randomUUID().toString(),path,method,headers,bytes);
                    JSObject response=bridge.syncRequest(request,fence,owner);int status=response.getInteger("status",0);
                    if(status<200||status>=300)throw new NativeFailure(status==401||status==409?"OFFLINE_SYNC_OWNER_MISMATCH":"OFFLINE_SYNC_REMOTE_REJECTED");
                    byte[] raw=NativePolicy.decode(response.getString("body_base64"),NativePolicy.MAX_RESPONSE_BYTES,"OFFLINE_TOO_LARGE");
                    try{return OfflinePackageValidator.response(raw);}finally{Arrays.fill(raw,(byte)0);}
                }finally{Arrays.fill(bytes,(byte)0);}
            }
            public byte[] download(JSONObject descriptor,String owner) throws Exception {
                return bridge.downloadOffline(descriptor.getString("id"),descriptor.getString("sha256"),descriptor.getInt("byte_count"),fence,owner);
            }
            public <T> T publish(java.util.concurrent.Callable<T> action) throws Exception {return bridge.publish(fence,action);}
        };
    }
    private boolean current() {try{remote.check();return true;}catch(NativeFailure ignored){return false;}}
    private void conditions(JSONObject policy) throws Exception {
        remote.check();String reason=OfflineSyncConditions.blocked(policy.getJSONObject("conditions"),conditions.get());if(reason!=null)throw new NativeFailure(reason);
    }
    private static void base(JSONObject descriptor,JSONObject policy) throws Exception {
        JSONObject binding=policy.getJSONObject("binding");
        JSONObject request=OfflineSyncValues.json("package_id",binding.getString("package_id"),"expected_sha256",binding.getString("sha256"),
            "expected_byte_count",descriptor.getLong("byte_count"),"approved_plan_fingerprint",descriptor.getString("plan_fingerprint"));
        OfflinePackageValidator.descriptor(descriptor,request);
        OfflinePackageValidator.scope(policy.getJSONObject("scope"), OfflineSyncValues.version(descriptor,"offline-pack-descriptor@") == 2);
        if(!descriptor.getString("owner_scope_id").equals(policy.getString("owner_scope_id")))throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
    }
    private static void update(JSONObject response,JSONObject policy,JSONObject originalDescriptor) throws Exception {
        OfflinePackageValidator.keys(response,"schema","state","mode","base_pack_id","base_semantic_digest","current_semantic_digest","base_pack","plan","source_refresh_performed");
        int version=OfflineSyncValues.version(originalDescriptor,"offline-pack-descriptor@");
        OfflinePackageValidator.equal(response,"schema","offline-pack-update@"+version);OfflinePackageValidator.equal(response,"mode","history");OfflinePackageValidator.equal(response,"source_refresh_performed",false);
        OfflinePackageValidator.equal(response,"base_pack_id",policy.getJSONObject("binding").getString("package_id"));
        OfflinePackageValidator.hash(response,"base_semantic_digest");OfflinePackageValidator.hash(response,"current_semantic_digest");
        base(response.getJSONObject("base_pack"),policy);
        if(!OfflineSyncValues.equal(response.getJSONObject("base_pack"),originalDescriptor))throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
        String state=OfflinePackageValidator.text(response,"state",20);
        if(state.equals("no_change")) {
            if(!response.isNull("plan")||!response.getString("base_semantic_digest").equals(response.getString("current_semantic_digest")))throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
        } else if(state.equals("planned")) {
            if(response.getString("base_semantic_digest").equals(response.getString("current_semantic_digest")))throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
            JSONObject plan=OfflinePackageValidator.object(response,"plan");
            OfflinePackageValidator.keys(plan,"schema","id","package_id","state","created_at","expires_at","fingerprint","owner_scope_id","privacy_class","requested_scope","base_pack_id","resolved","contexts","documents","omissions","counts","measured_bytes","content_sha256","capacity","can_confirm","privacy_notice","rights_notice","diff");
            OfflinePackageValidator.equal(plan,"schema","offline-pack-plan@"+version);
            OfflinePackageValidator.scope(plan.getJSONObject("requested_scope"),version==2);
            if(!policy.getString("owner_scope_id").equals(plan.getString("owner_scope_id")) ||
                !policy.getJSONObject("binding").getString("package_id").equals(plan.getString("base_pack_id")) ||
                !OfflineSyncValues.equal(policy.getJSONObject("scope"),plan.getJSONObject("requested_scope")) ||
                !OfflineSyncValues.equal(policy.getJSONObject("capacity"),plan.getJSONObject("capacity")))throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
            if(!Boolean.TRUE.equals(plan.opt("can_confirm"))||!"ready".equals(plan.optString("state")))throw new NativeFailure("OFFLINE_SYNC_PLAN_BLOCKED");
            OfflinePackageValidator.uuid(plan,"id");OfflinePackageValidator.uuid(plan,"package_id");OfflinePackageValidator.hash(plan,"fingerprint");OfflinePackageValidator.hash(plan,"content_sha256");
            if(OfflinePackageValidator.number(plan,"measured_bytes",8*1024*1024)<1)throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
            java.time.Instant expires;
            try { expires=java.time.OffsetDateTime.parse(plan.getString("expires_at")).toInstant(); }
            catch(java.time.format.DateTimeParseException ignored){throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");}
            if(!java.time.Instant.now().isBefore(expires))throw new NativeFailure("OFFLINE_SYNC_PLAN_EXPIRED");
            JSONObject count=plan.getJSONObject("counts"),cap=policy.getJSONObject("capacity");
            for(String[] pair:new String[][]{{"garage_profiles","max_garage_profiles"},{"watch_items","max_watch_items"},{"recent_queries","max_recent_query_candidates"},{"distinct_evidence","max_distinct_evidence"},{"searchable_documents","max_searchable_documents"}})OfflinePackageValidator.number(count,pair[0],cap.getLong(pair[1]));
            JSONArray resolved=OfflinePackageValidator.array(plan,"resolved",cap.getInt("max_distinct_evidence"));
            JSONArray documents=OfflinePackageValidator.array(plan,"documents",cap.getInt("max_searchable_documents"));
            JSONArray contexts=OfflinePackageValidator.array(plan,"contexts",cap.getInt("max_garage_profiles")+cap.getInt("max_watch_items"));
            int garage=0,watch=0;
            for(int i=0;i<contexts.length();i++){
                String kind=OfflinePackageValidator.text(OfflinePackageValidator.at(contexts,i),"kind",20);
                if(kind.equals("garage"))garage++;else if(kind.equals("watchlist"))watch++;else throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
            }
            if(resolved.length()!=count.getInt("distinct_evidence")||documents.length()!=count.getInt("searchable_documents")||
                garage!=count.getInt("garage_profiles")||watch!=count.getInt("watch_items"))throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
            JSONArray omitted=plan.getJSONArray("omissions");for(int i=0;i<omitted.length();i++)if(!Boolean.FALSE.equals(omitted.getJSONObject(i).opt("blocking")))throw new NativeFailure("OFFLINE_SYNC_PLAN_BLOCKED");
        } else throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
    }
    JSONObject run(JSONObject request) throws Exception {
        JSONObject started=store.syncBegin(request,remote.binding(),conditions.get());JSONObject run=started.getJSONObject("run"),policy=started.getJSONObject("policy");
        if(!"running".equals(run.getString("state")))return run;
        String id=run.getString("run_id");boolean writePending=false;byte[] original=null;
        try {
            JSONObject originalDescriptor=started.getJSONObject("base_pack");
            base(originalDescriptor,policy);
            int version=OfflineSyncValues.version(originalDescriptor,"offline-pack-descriptor@");
            conditions(policy);store.syncStage(id,"preparing",null,null);
            JSONObject payload=OfflineSyncValues.json("mode","history","base_pack_id",policy.getJSONObject("binding").getString("package_id"),
                "expected_base_sha256",policy.getJSONObject("binding").getString("sha256"),"scope",OfflineSyncValues.copy(policy.getJSONObject("scope")),
                "supported_pack_schemas",new JSONArray().put(OfflineSyncValues.packSchema(originalDescriptor)));
            writePending=true;JSONObject prepared=remote.json("POST","/v1/offline-pack-updates:prepare",payload,null,policy.getString("owner_scope_id"));writePending=false;
            update(prepared,policy,started.getJSONObject("base_pack"));conditions(policy);
            if("no_change".equals(prepared.getString("state")))return remote.publish(()->store.syncNoChange(id,this::current,conditions));
            JSONObject plan=prepared.getJSONObject("plan");String key=UUID.randomUUID().toString();store.syncStage(id,"confirming",plan,key);
            JSONObject confirm=OfflineSyncValues.json("plan_id",plan.getString("id"),"expected_fingerprint",plan.getString("fingerprint"),"allow_device_storage",true);
            conditions(policy);writePending=true;JSONObject descriptor=remote.json("POST","/v1/offline-packs",confirm,key,policy.getString("owner_scope_id"));writePending=false;
            JSONObject install=OfflineSyncValues.json("package_id",plan.getString("package_id"),"expected_sha256",plan.getString("content_sha256"),"expected_byte_count",plan.getLong("measured_bytes"),"approved_plan_fingerprint",plan.getString("fingerprint"));
            OfflinePackageValidator.descriptor(descriptor,install);
            if(OfflineSyncValues.version(descriptor,"offline-pack-descriptor@")!=version)throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
            if(!descriptor.getString("owner_scope_id").equals(policy.getString("owner_scope_id"))||!descriptor.getString("base_pack_id").equals(policy.getJSONObject("binding").getString("package_id"))||!descriptor.getString("plan_id").equals(plan.getString("id")))throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
            conditions(policy);store.syncStage(id,"downloading",null,null);original=remote.download(descriptor,policy.getString("owner_scope_id"));conditions(policy);
            store.syncStage(id,"committing",null,null);final byte[] staged=original;return remote.publish(()->store.syncCommit(id,descriptor,staged,this::current,conditions));
        }catch(Exception error) {
            String reason=error instanceof NativeFailure?((NativeFailure)error).code:"OFFLINE_SYNC_FAILED";
            if(writePending)return store.syncFinish(id,"interrupted",reason,true);
            boolean paused=reason.equals("SESSION_CHANGED")||reason.equals("SESSION_RESET_IN_PROGRESS")||reason.equals("OFFLINE_SYNC_OWNER_MISMATCH")||reason.equals("OFFLINE_SYNC_PACKAGE_MISMATCH")||reason.equals("OFFLINE_SYNC_CANCELLED")||reason.equals("OFFLINE_STALE_GENERATION")||reason.equals("OFFLINE_NOT_FOUND")||reason.equals("OFFLINE_OWNER_LOCKED")||reason.equals("OFFLINE_SYNC_LEASE_EXPIRED");
            return store.syncFinish(id,paused?"cancelled":"failed",reason,paused);
        }finally{if(original!=null)Arrays.fill(original,(byte)0);}
    }
}
