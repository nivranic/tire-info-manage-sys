package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.InputStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Arrays;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Original producer49 baseline, explicitly synthetic candidate/HTTP; own Keystore profiles retained. */
@RunWith(AndroidJUnit4.class)
public final class OfflineSyncV2Test {
    private static byte[] asset(String name) throws Exception {
        try (InputStream input=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("offline-producer49/"+name)) { return input.readAllBytes(); }
    }
    private static final String SESSION="b".repeat(64);
    private interface Checked { void run() throws Exception; }
    private static void rejected(Checked action) throws Exception {
        try { action.run(); fail("Invalid version/scope accepted"); }
        catch (NativeFailure expected) { assertTrue(expected.code.startsWith("OFFLINE_")); }
    }
    private static OfflineSyncConditions.Sample permitted() { return new OfflineSyncConditions.Sample(true,true,true); }

    private static final class Fixture implements AutoCloseable {
        final OfflinePackStore store; final byte[] original; final JSONObject base,material; final String slot;
        Fixture(String name) throws Exception {
            Context context=InstrumentationRegistry.getInstrumentation().getTargetContext(); assertTrue(context.getPackageName().endsWith(".offlineqa"));
            store=new OfflinePackStore(context,"qa-r49-sync-v2-"+UUID.randomUUID());slot=UUID.randomUUID().toString();
            original=asset(name+"-pack.json");base=OfflinePackageValidator.response(asset(name+"-descriptor.json"));
            material=OfflinePackageValidator.envelope(original,base);
            store.install(OfflineSyncValues.json("package_id",base.getString("id"),"expected_sha256",base.getString("sha256"),
                "expected_byte_count",original.length,"approved_plan_fingerprint",base.getString("plan_fingerprint"),"slot_id",slot,"expected_generation",0,"allow_device_storage",true),base,original);
            assertEquals(base.getString("sha256"),OfflineCipher.sha256(original));
        }
        JSONObject policy() throws Exception {
            JSONObject status=store.status();
            JSONObject preview=store.syncPreview(OfflineSyncValues.json("slot_id",slot,"expected_generation",1,"expected_profile_id",status.getString("profile_id"),
                "expected_owner_epoch",status.getLong("owner_epoch"),"interval_seconds",900,"conditions",OfflineSyncValues.json("network","any","power","any")),SESSION);
            return store.syncApply(OfflineSyncValues.json("preview_id",preview.getString("preview_id"),"expected_fingerprint",preview.getString("fingerprint"),
                "expected_policy_revision",preview.getLong("expected_policy_revision"),"allow_continuous_history_updates",true),SESSION);
        }
        JSONObject request(JSONObject policy) throws Exception { return OfflineSyncValues.json("policy_id",policy.getString("policy_id"),"expected_policy_revision",policy.getLong("policy_revision"),"trigger","manual"); }
        JSONObject run(JSONObject policy, Remote remote) throws Exception { return new OfflineSyncCoordinator(store,remote,OfflineSyncV2Test::permitted).run(request(policy)); }
        long generation() throws Exception { return store.list().getJSONArray("items").getJSONObject(0).getLong("generation"); }
        void unchanged() throws Exception { assertEquals(1,generation());assertEquals(base.getString("sha256"),store.list().getJSONArray("items").getJSONObject(0).getString("sha256")); }
        public void close() { store.close(); } // Keep this isolated profile/key; do not touch shared credentials.
    }

    private static final class Remote implements OfflineSyncCoordinator.Remote {
        final Fixture f; final JSONObject policy; final int version;
        JSONObject candidate,plan; byte[] updated; int prepares,confirms,downloads;
        boolean changed; String responseSchema,planSchema,descriptorSchema; Checked afterDownload;
        Remote(Fixture f, JSONObject policy) throws Exception {
            this.f=f;this.policy=policy;version=OfflineSyncValues.version(f.base,"offline-pack-descriptor@");
            JSONObject next=OfflineSyncValues.copy(f.material); String id=UUID.randomUUID().toString(),planId=UUID.randomUUID().toString(),fingerprint="d".repeat(64);
            next.put("package_id",id).put("base_pack_id",f.base.getString("id")).put("plan_fingerprint",fingerprint);
            next.put("scope",OfflineSyncValues.copy(policy.getJSONObject("scope")));
            // Synthetic document update changes bytes; original producer baseline remains unmodified.
            JSONObject document=next.getJSONArray("documents").getJSONObject(0);document.put("text",document.getString("text")+"\nSynthetic sync QA update");
            updated=OfflineJsonInteger.stringify(next).getBytes(StandardCharsets.UTF_8);
            candidate=OfflineSyncValues.copy(f.base).put("id",id).put("plan_id",planId).put("plan_fingerprint",fingerprint).put("base_pack_id",f.base.getString("id"))
                .put("sha256",OfflineCipher.sha256(updated)).put("byte_count",updated.length).put("download_path","/v1/offline-packs/"+id+"/download?mode=history");
            JSONArray resolved=new JSONArray();for(int at=0;at<next.getJSONArray("members").length();at++){
                JSONObject member=next.getJSONArray("members").getJSONObject(at),metadata=new JSONObject();
                for(String key:new String[]{"key","reference","member_reasons","privacy_class","raw_included"})metadata.put(key,member.get(key));resolved.put(metadata);
            }
            plan=OfflineSyncValues.json("schema","offline-pack-plan@"+version,"id",planId,"package_id",id,"state","ready","created_at",Instant.now().toString(),
                "expires_at",Instant.now().plusSeconds(600).toString(),"fingerprint",fingerprint,"owner_scope_id",f.base.getString("owner_scope_id"),"privacy_class",next.getString("privacy_class"),
                "requested_scope",OfflineSyncValues.copy(policy.getJSONObject("scope")),"base_pack_id",f.base.getString("id"),"resolved",resolved,"contexts",next.getJSONArray("contexts"),
                "documents",next.getJSONArray("documents"),"omissions",next.getJSONArray("omissions"),"counts",f.base.getJSONObject("counts"),"measured_bytes",updated.length,
                "content_sha256",candidate.getString("sha256"),"capacity",OfflineSyncValues.capacity(),"can_confirm",true,"privacy_notice","Synthetic QA only","rights_notice","Original byte baseline; synthetic update",
                "diff",OfflineSyncValues.json("added",new JSONArray(),"removed",new JSONArray(),"changed",new JSONArray()));
        }
        JSONObject response() throws Exception {
            JSONObject current=changed?OfflineSyncValues.copy(plan):null;if(current!=null&&planSchema!=null)current.put("schema",planSchema);
            return OfflineSyncValues.json("schema",responseSchema==null?"offline-pack-update@"+version:responseSchema,"state",changed?"planned":"no_change","mode","history",
                "base_pack_id",f.base.getString("id"),"base_semantic_digest","a".repeat(64),"current_semantic_digest",(changed?"b":"a").repeat(64),
                "base_pack",OfflineSyncValues.copy(f.base),"plan",current,"source_refresh_performed",false);
        }
        public String binding() { return SESSION; }
        public void check() { }
        public JSONObject json(String method,String path,JSONObject body,String key,String owner) throws Exception {
            assertEquals("POST",method);assertEquals(f.base.getString("owner_scope_id"),owner);
            if(path.equals("/v1/offline-pack-updates:prepare")){
                prepares++;assertNull(key);assertEquals("history",body.getString("mode"));assertEquals(f.base.getString("sha256"),body.getString("expected_base_sha256"));
                assertEquals(f.base.getString("id"),body.getString("base_pack_id"));assertTrue(OfflineSyncValues.equal(policy.getJSONObject("scope"),body.getJSONObject("scope")));
                JSONArray supported=body.getJSONArray("supported_pack_schemas");assertEquals(1,supported.length());assertEquals("offline-pack@"+version,supported.getString(0));return response();
            }
            assertEquals("/v1/offline-packs",path);confirms++;assertNotNull(key);NativePolicy.requestId(key);
            JSONObject receipt=OfflineSyncValues.copy(candidate);if(descriptorSchema!=null)receipt.put("schema",descriptorSchema);return receipt;
        }
        public byte[] download(JSONObject descriptor,String owner) throws Exception { downloads++;if(afterDownload!=null)afterDownload.run();return Arrays.copyOf(updated,updated.length); }
    }

    @Test public void originalV2ScopeKeepsAllFrozenQueryDomainsIncludingEmptySearchReceipt() throws Exception {
        for(String name:new String[]{"nonempty","empty"})try(Fixture f=new Fixture(name)){
            JSONObject scope=OfflineSyncValues.scope(f.material);OfflinePackageValidator.scope(scope,true);
            boolean search=false;for(int at=0;at<scope.getJSONArray("references").length();at++){
                JSONObject reference=scope.getJSONArray("references").getJSONObject(at);if(reference.getString("kind").equals("recall_search")){search=true;assertTrue(reference.has("verification_id"));}
            }assertTrue(search);rejected(()->OfflinePackageValidator.scope(scope,false));
            JSONObject policy=f.policy();assertTrue(OfflineSyncValues.equal(scope,policy.getJSONObject("scope")));
            assertEquals(1,f.store.syncStatus(false).getJSONArray("policies").length());
        }
    }

    @Test public void bothOriginalVersionsNegotiateOnlyTheirBaseSchemaAndNoChangeDownloadsNothing() throws Exception {
        for(String name:new String[]{"nonempty","legacy"})try(Fixture f=new Fixture(name)){
            JSONObject policy=f.policy();Remote remote=new Remote(f,policy);assertEquals("no_change",f.run(policy,remote).getString("state"));
            assertEquals(1,remote.prepares);assertEquals(0,remote.confirms);assertEquals(0,remote.downloads);f.unchanged();
            assertEquals(1,f.store.syncStatus(false).getJSONArray("policies").getJSONObject(0).getJSONObject("binding").getLong("binding_revision"));
        }
    }

    @Test public void bothVersionsRetainFormatOnSyntheticAtomicCandidateAndSaveNewFallbackBinding() throws Exception {
        for(String name:new String[]{"nonempty","legacy"})try(Fixture f=new Fixture(name)){
            JSONObject policy=f.policy();Remote remote=new Remote(f,policy);remote.changed=true;
            assertEquals("succeeded",f.run(policy,remote).getString("state"));assertEquals(2,f.generation());assertEquals(1,remote.confirms);assertEquals(1,remote.downloads);
            JSONObject current=f.store.syncStatus(false).getJSONArray("policies").getJSONObject(0);
            assertEquals(1,current.getLong("policy_revision"));assertEquals(2,current.getJSONObject("binding").getLong("binding_revision"));
            assertEquals(remote.candidate.getString("sha256"),current.getJSONObject("binding").getString("sha256"));
            JSONObject fallback=f.store.fallbackStatus().getJSONArray("package_bindings").getJSONObject(0);
            assertEquals(2,fallback.getLong("generation"));assertEquals(remote.candidate.getString("sha256"),fallback.getString("sha256"));
        }
    }

    @Test public void updateAndPlanCannotUpgradeDowngradeOrUseFutureVersionBeforeConfirmation() throws Exception {
        for(String name:new String[]{"nonempty","legacy"})for(boolean mutatePlan:new boolean[]{false,true})try(Fixture f=new Fixture(name)){
            JSONObject policy=f.policy();Remote remote=new Remote(f,policy);remote.changed=true;int other=remote.version==1?2:1;
            if(mutatePlan)remote.planSchema="offline-pack-plan@"+other;else remote.responseSchema="offline-pack-update@"+other;
            assertNotEquals("succeeded",f.run(policy,remote).getString("state"));assertEquals(0,remote.confirms);assertEquals(0,remote.downloads);f.unchanged();
        }
        try(Fixture f=new Fixture("nonempty")){JSONObject policy=f.policy();Remote remote=new Remote(f,policy);remote.changed=true;remote.planSchema="offline-pack-plan@3";
            assertNotEquals("succeeded",f.run(policy,remote).getString("state"));assertEquals(0,remote.confirms);f.unchanged();}
    }

    @Test public void confirmedDescriptorCannotChangeBaseVersionBeforeDownload() throws Exception {
        for(String name:new String[]{"nonempty","legacy"})try(Fixture f=new Fixture(name)){
            JSONObject policy=f.policy();Remote remote=new Remote(f,policy);remote.changed=true;remote.descriptorSchema="offline-pack-descriptor@"+(remote.version==1?2:1);
            assertEquals("OFFLINE_SYNC_PACKAGE_MISMATCH",f.run(policy,remote).getString("reason"));assertEquals(1,remote.confirms);assertEquals(0,remote.downloads);f.unchanged();
        }
    }

    private static void gate(JSONObject response,JSONObject policy,JSONObject base) throws Exception {
        Method method=OfflineSyncCoordinator.class.getDeclaredMethod("update",JSONObject.class,JSONObject.class,JSONObject.class);method.setAccessible(true);
        try { method.invoke(null,response,policy,base); }
        catch(InvocationTargetException failure){if(failure.getCause() instanceof Exception)throw (Exception)failure.getCause();throw failure;}
    }
    @Test public void closedV2PlanRejectsExtraMissingScopeOwnerAndHashBeforeConfirmation() throws Exception {
        try(Fixture f=new Fixture("nonempty")){
            JSONObject policy=f.policy();Remote remote=new Remote(f,policy);remote.changed=true;gate(remote.response(),policy,f.base);
            JSONObject extra=remote.response();extra.getJSONObject("plan").put("permission_claim",true);rejected(()->gate(extra,policy,f.base));
            JSONObject missing=remote.response();missing.getJSONObject("plan").remove("documents");rejected(()->gate(missing,policy,f.base));
            JSONObject owner=remote.response();owner.getJSONObject("plan").put("owner_scope_id","f".repeat(64));rejected(()->gate(owner,policy,f.base));
            JSONObject hash=remote.response();hash.getJSONObject("plan").put("content_sha256","not-a-hash");rejected(()->gate(hash,policy,f.base));
            JSONObject scope=remote.response();scope.getJSONObject("plan").getJSONObject("requested_scope").getJSONArray("references").getJSONObject(0).put("kind","future");rejected(()->gate(scope,policy,f.base));
        }
    }

    @Test public void futureBaseAndLegacySearchScopeFailClosed() throws Exception {
        JSONObject descriptor=OfflinePackageValidator.response(asset("nonempty-descriptor.json"));descriptor.put("schema","offline-pack-descriptor@3");rejected(()->OfflineSyncValues.packSchema(descriptor));
        JSONObject material=OfflinePackageValidator.envelope(asset("nonempty-pack.json"),OfflinePackageValidator.response(asset("nonempty-descriptor.json")));
        material.put("schema","offline-pack@1");rejected(()->OfflineSyncValues.scope(material));
        material.put("schema","offline-pack@3");rejected(()->OfflineSyncValues.scope(material));
    }

    @Test public void v2ScopeNeverBorrowsDifferentFrozenSearchVerificationOrUnresolvedSelector() throws Exception {
        JSONObject material=OfflinePackageValidator.envelope(asset("nonempty-pack.json"),OfflinePackageValidator.response(asset("nonempty-descriptor.json")));
        JSONObject scope=material.getJSONObject("scope");JSONArray references=scope.getJSONArray("references");
        for(int at=0;at<references.length();at++)if(references.getJSONObject(at).getString("kind").equals("recall_search"))references.getJSONObject(at).put("verification_id",UUID.randomUUID().toString());
        try { OfflineSyncValues.scope(material);fail("Unresolved exact search receipt accepted"); }
        catch(NativeFailure expected){assertEquals("OFFLINE_SYNC_SCOPE_UNRESOLVED",expected.code);}
    }
}
