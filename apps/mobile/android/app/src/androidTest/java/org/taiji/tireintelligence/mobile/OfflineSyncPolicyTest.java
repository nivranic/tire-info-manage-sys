package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.sqlite.SQLiteConnection;
import androidx.sqlite.SQLiteStatement;
import androidx.sqlite.driver.bundled.BundledSQLiteDriver;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkInfo;
import androidx.work.WorkManager;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Actual Keystore/catalog/index with frozen producer data; remote responses are synthetic. */
@RunWith(AndroidJUnit4.class)
public final class OfflineSyncPolicyTest {
    private Context context;private OfflinePackStore store;private String namespace,slot;
    private JSONObject descriptor,candidate,planned,noChange;private byte[] original,updated;
    private final String binding="b".repeat(64);
    private interface Checked{void run()throws Exception;}
    private static void fails(String code,Checked action)throws Exception{try{action.run();fail("Expected "+code);}catch(NativeFailure failure){assertEquals(code,failure.code);}}
    private byte[] asset(String name)throws Exception{
        try(InputStream input=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("device-sync48/"+name)){
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[16384];int count;while((count=input.read(buffer))!=-1)bytes.write(buffer,0,count);return bytes.toByteArray();
        }
    }
    private JSONObject object(String name)throws Exception{return OfflinePackageValidator.response(asset(name));}
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();assertTrue(context.getPackageName().endsWith(".offlineqa"));
        namespace="qa-r48-"+UUID.randomUUID();slot=UUID.randomUUID().toString();store=new OfflinePackStore(context,namespace);
        original=asset("base-pack.json");updated=asset("candidate-pack.json");descriptor=object("base-descriptor.json");candidate=object("candidate-descriptor.json");planned=object("planned-update.json");noChange=object("no-change.json");
        store.install(install(0),descriptor,original);assertEquals(descriptor.getString("sha256"),OfflineCipher.sha256(original));assertEquals(candidate.getString("sha256"),OfflineCipher.sha256(updated));
    }
    private JSONObject install(long generation)throws Exception{return OfflineSyncValues.json("package_id",descriptor.getString("id"),"expected_sha256",descriptor.getString("sha256"),"expected_byte_count",original.length,"approved_plan_fingerprint",descriptor.getString("plan_fingerprint"),"slot_id",slot,"expected_generation",generation,"allow_device_storage",true);}
    private JSONObject preview(JSONObject conditions)throws Exception{JSONObject status=store.status();return store.syncPreview(OfflineSyncValues.json("slot_id",slot,"expected_generation",store.list().getJSONArray("items").getJSONObject(0).getLong("generation"),"expected_profile_id",status.getString("profile_id"),"expected_owner_epoch",status.getLong("owner_epoch"),"interval_seconds",900,"conditions",conditions),binding);}
    private JSONObject authorize(JSONObject conditions)throws Exception{JSONObject preview=preview(conditions);return store.syncApply(OfflineSyncValues.json("preview_id",preview.getString("preview_id"),"expected_fingerprint",preview.getString("fingerprint"),"expected_policy_revision",preview.getLong("expected_policy_revision"),"allow_continuous_history_updates",true),binding);}
    private JSONObject any()throws Exception{return OfflineSyncValues.json("network","any","power","any");}
    private JSONObject request(JSONObject policy,String trigger)throws Exception{return OfflineSyncValues.json("policy_id",policy.getString("policy_id"),"expected_policy_revision",policy.getLong("policy_revision"),"trigger",trigger);}
    private JSONObject change(JSONObject policy)throws Exception{return OfflineSyncValues.json("policy_id",policy.getString("policy_id"),"expected_policy_revision",policy.getLong("policy_revision"));}
    private static OfflineSyncConditions.Sample permitted(){return new OfflineSyncConditions.Sample(true,true,true);}
    private final class Remote implements OfflineSyncCoordinator.Remote{
        int prepares,confirms,downloads;boolean changed,uncertain,uncertainConfirm;String confirmationKey;Checked onDownload;
        public String binding(){return binding;}public void check(){}
        public JSONObject json(String method,String path,JSONObject body,String key,String owner)throws Exception{
            assertEquals(descriptor.getString("owner_scope_id"),owner);
            if(path.equals("/v1/offline-pack-updates:prepare")){
                prepares++;assertEquals("history",body.getString("mode"));assertEquals(descriptor.getString("sha256"),body.getString("expected_base_sha256"));
                if(uncertain)throw new NativeFailure("API_TIMEOUT");
                JSONObject result=OfflineSyncValues.copy(changed?planned:noChange);
                if(changed)result.getJSONObject("plan").put("expires_at",java.time.OffsetDateTime.now(java.time.ZoneOffset.UTC).plusSeconds(600)
                    .format(java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSSSSSxxx")));return result;
            }
            assertEquals("/v1/offline-packs",path);assertNotNull(key);NativePolicy.requestId(key);confirms++;confirmationKey=key;
            JSONObject status=store.syncStatus(false);JSONObject run=status.getJSONArray("runs").getJSONObject(status.getJSONArray("runs").length()-1);
            assertEquals("confirming",run.getString("stage"));assertEquals(body.getString("plan_id"),run.getString("plan_id"));if(uncertainConfirm)throw new NativeFailure("API_TIMEOUT");return OfflineSyncValues.copy(candidate);
        }
        public byte[] download(JSONObject current,String owner)throws Exception{downloads++;if(onDownload!=null)onDownload.run();return Arrays.copyOf(updated,updated.length);}
    }
    private JSONObject run(JSONObject policy,Remote remote)throws Exception{return new OfflineSyncCoordinator(store,remote,OfflineSyncPolicyTest::permitted).run(request(policy,"manual"));}
    private long generation()throws Exception{return store.list().getJSONArray("items").getJSONObject(0).getLong("generation");}
    private File directory()throws Exception{return new File(context.getNoBackupFilesDir(),"offline-v1/"+OfflineCipher.sha256((context.getPackageName()+":offline-profile@1:"+namespace).getBytes(StandardCharsets.UTF_8)));}
    private void sql(String statement)throws Exception{try(SQLiteConnection connection=new BundledSQLiteDriver().open(new File(directory(),"catalog.sqlite").getAbsolutePath());SQLiteStatement operation=connection.prepare(statement)){while(operation.step()){} }}
    /** User approval 2026-10-03: retain synthetic QA data and Keystore aliases as evidence instead of deleting them. */
    @After public void cleanup()throws Exception{if(store!=null)store.close();if(namespace!=null){assertTrue(namespace.startsWith("qa-r48-")&&context.getPackageName().endsWith(".offlineqa"));assertTrue(new OfflineCipher(context,namespace).hasKey());}}

    @Test public void installDoesNotGrantContinuousAndPreviewIsOneShot()throws Exception{
        assertEquals(0,store.syncStatus(false).getJSONArray("policies").length());JSONObject preview=preview(any());
        JSONObject applied=OfflineSyncValues.json("preview_id",preview.getString("preview_id"),"expected_fingerprint",preview.getString("fingerprint"),"expected_policy_revision",0,"allow_continuous_history_updates",true);
        JSONObject policy=store.syncApply(applied,binding);assertEquals(1,policy.getLong("policy_revision"));fails("OFFLINE_SYNC_PREVIEW_EXPIRED",()->store.syncApply(applied,binding));
        assertTrue(OfflineSyncValues.equal(planned.getJSONObject("plan").getJSONObject("requested_scope"),policy.getJSONObject("scope")));
        JSONObject next=preview(any());JSONObject denied=OfflineSyncValues.json("preview_id",next.getString("preview_id"),"expected_fingerprint",next.getString("fingerprint"),"expected_policy_revision",1,"allow_continuous_history_updates",false);
        fails("OFFLINE_PACKAGE_INVALID",()->store.syncApply(denied,binding));assertEquals(1,store.syncStatus(false).getJSONArray("policies").getJSONObject(0).getLong("policy_revision"));
    }
    @Test public void noChangeHasNoConfirmDownloadOrGenerationGrowthAndHistoryIsBounded()throws Exception{
        JSONObject policy=authorize(any());Remote remote=new Remote();assertEquals("no_change",run(policy,remote).getString("state"));assertEquals(1,generation());assertEquals(0,remote.confirms);assertEquals(0,remote.downloads);
        for(int i=0;i<65;i++)assertEquals("no_change",run(policy,remote).getString("state"));JSONObject status=store.syncStatus(false);assertEquals(64,status.getJSONArray("runs").length());assertEquals(1,status.getJSONArray("policies").getJSONObject(0).getLong("policy_revision"));
    }
    private void noChangeConditionAtCommit(OfflineSyncConditions.Sample changed,String expected)throws Exception{
        JSONObject policy=authorize(OfflineSyncValues.json("network","wifi","power","external_power"));
        JSONObject started=store.syncBegin(request(policy,"manual"),binding,permitted());String id=started.getJSONObject("run").getString("run_id");
        java.util.concurrent.atomic.AtomicInteger samples=new java.util.concurrent.atomic.AtomicInteger();
        fails(expected,()->store.syncNoChange(id,()->true,()->samples.incrementAndGet()==1?permitted():changed));
        assertEquals(2,samples.get());assertEquals(1,generation());
        JSONObject status=store.syncStatus(false),saved=status.getJSONArray("policies").getJSONObject(0),run=status.getJSONArray("runs").getJSONObject(0);
        assertEquals(policy.getString("next_due_at"),saved.getString("next_due_at"));assertEquals(1,saved.getJSONObject("binding").getLong("binding_revision"));
        assertEquals("running",run.getString("state"));assertTrue(run.isNull("after_generation"));
        store.syncFinish(id,"failed",expected,false);
    }
    @Test public void noChangeUnknownConditionAfterEncryptedSaveRollsBack()throws Exception{
        noChangeConditionAtCommit(new OfflineSyncConditions.Sample(null,true,true),"OFFLINE_SYNC_CONDITION_UNKNOWN");
    }
    @Test public void noChangeUnmetConditionAfterEncryptedSaveRollsBack()throws Exception{
        noChangeConditionAtCommit(new OfflineSyncConditions.Sample(false,true,true),"OFFLINE_SYNC_CONDITION_UNMET");
    }
    @Test public void changedProducerBytesAtomicallyAdvanceBindingAndSlot()throws Exception{
        JSONObject policy=authorize(any());Remote remote=new Remote();remote.changed=true;JSONObject result=run(policy,remote);assertEquals("succeeded",result.getString("state"));assertEquals(2,generation());
        JSONObject current=store.syncStatus(false).getJSONArray("policies").getJSONObject(0);assertEquals(1,current.getLong("policy_revision"));assertEquals(2,current.getJSONObject("binding").getLong("binding_revision"));assertEquals(candidate.getString("sha256"),current.getJSONObject("binding").getString("sha256"));assertEquals(1,remote.confirms);assertEquals(1,remote.downloads);
        assertEquals(11,store.search(OfflineSyncValues.json("slot_id",slot,"expected_generation",2,"query","","limit",50,"offset",0)).getInt("total"));
    }
    @Test public void revokeDuringDownloadCannotPublish()throws Exception{
        JSONObject policy=authorize(any());Remote remote=new Remote();remote.changed=true;remote.onDownload=()->store.syncChange(change(policy),true);
        assertEquals("cancelled",run(policy,remote).getString("state"));assertEquals(1,generation());assertEquals("revoked",store.syncStatus(false).getJSONArray("policies").getJSONObject(0).getString("state"));
    }
    @Test public void manualReplacementAndResetInvalidateOldRunAndOldOwnerUnlockIsNotConsent()throws Exception{
        JSONObject policy=authorize(any());Remote remote=new Remote();remote.changed=true;remote.onDownload=()->store.install(install(1),descriptor,original);run(policy,remote);assertEquals(2,generation());assertEquals("paused",store.syncStatus(false).getJSONArray("policies").getJSONObject(0).getString("state"));
        store.resetOwnerEpoch();store.unlockPreviousOwner(OfflineSyncValues.json("slot_id",slot,"expected_generation",2,"allow_previous_owner",true));fails("OFFLINE_OWNER_LOCKED",()->preview(any()));
    }
    @Test public void unknownPreparePausesAndNeverAutomaticallyReplays()throws Exception{
        JSONObject policy=authorize(any());Remote remote=new Remote();remote.uncertain=true;assertEquals("interrupted",run(policy,remote).getString("state"));assertEquals(1,generation());JSONObject paused=store.syncStatus(false).getJSONArray("policies").getJSONObject(0);assertEquals("paused",paused.getString("state"));fails("OFFLINE_SYNC_DISABLED",()->run(paused,remote));assertEquals(1,remote.prepares);
    }
    @Test public void unknownConfirmKeepsExactDurableKeyAndRequiresNewConsent()throws Exception{
        JSONObject policy=authorize(any());Remote remote=new Remote();remote.changed=true;remote.uncertainConfirm=true;
        assertEquals("interrupted",run(policy,remote).getString("state"));assertEquals(1,generation());assertEquals(1,remote.confirms);assertEquals(0,remote.downloads);
        changeSidecar(namespace,state->{try{JSONObject entry=state.getJSONArray("runs").getJSONObject(0);assertEquals(remote.confirmationKey,entry.getString("confirmation_key"));assertEquals(planned.getJSONObject("plan").getString("fingerprint"),entry.getString("plan_fingerprint"));}catch(Exception error){throw new AssertionError(error);}});
        JSONObject paused=store.syncStatus(false).getJSONArray("policies").getJSONObject(0);assertEquals("paused",paused.getString("state"));fails("OFFLINE_SYNC_DISABLED",()->run(paused,remote));assertEquals(1,remote.confirms);
    }
    @Test public void onlyOneRunLeaseAndBlockedAuthorityIsDurableWithoutBootstrap()throws Exception{
        JSONObject policy=authorize(any());JSONObject started=store.syncBegin(request(policy,"manual"),binding,permitted());
        fails("OFFLINE_SYNC_BUSY",()->store.syncBegin(request(policy,"manual"),binding,permitted()));store.syncFinish(started.getJSONObject("run").getString("run_id"),"cancelled","OFFLINE_SYNC_CANCELLED",false);
        JSONObject blocked=store.syncBlocked(request(policy,"os_job"),"SESSION_COOKIE_MISSING");assertEquals("blocked",blocked.getString("state"));assertEquals("SESSION_COOKIE_MISSING",blocked.getString("reason"));assertEquals("paused",store.syncStatus(false).getJSONArray("policies").getJSONObject(0).getString("state"));assertEquals(1,generation());
    }
    @Test public void andUnknownDefersWithoutNetworkAndConditionsRecheckedAfterDownload()throws Exception{
        JSONObject policy=authorize(OfflineSyncValues.json("network","wifi","power","battery_charging"));Remote remote=new Remote();
        JSONObject deferred=new OfflineSyncCoordinator(store,remote,()->new OfflineSyncConditions.Sample(null,true,true)).run(request(policy,"manual"));assertEquals("deferred",deferred.getString("state"));assertEquals(0,remote.prepares);
        java.util.concurrent.atomic.AtomicBoolean charging=new java.util.concurrent.atomic.AtomicBoolean(true);remote.changed=true;remote.onDownload=()->charging.set(false);
        JSONObject result=new OfflineSyncCoordinator(store,remote,()->new OfflineSyncConditions.Sample(true,true,charging.get())).run(request(policy,"manual"));assertEquals("failed",result.getString("state"));assertEquals(1,generation());
    }
    @Test public void corruptedSidecarIsRetainedSyncClosedAndOwnerResetStillWorks()throws Exception{
        authorize(any());sql("UPDATE sync_state SET value=x'010203' WHERE id=1");fails("OFFLINE_SYNC_STATE_INVALID",()->store.syncStatus(false));assertEquals(1,generation());long epoch=store.resetOwnerEpoch();assertEquals(2,epoch);
        try(SQLiteConnection connection=new BundledSQLiteDriver().open(new File(directory(),"catalog.sqlite").getAbsolutePath());SQLiteStatement row=connection.prepare("SELECT value FROM sync_state WHERE id=1")){assertTrue(row.step());assertArrayEquals(new byte[]{1,2,3},row.getBlob(0));}
    }
    @Test public void releaseChecksAllSlotsIncludingOldOwnerAndMetadataUnknownHasNullSha()throws Exception{
        String second=UUID.randomUUID().toString();JSONObject secondRequest=install(0);secondRequest.put("slot_id",second);store.install(secondRequest,descriptor,original);store.resetOwnerEpoch();
        JSONObject status=store.syncStatus(true);assertEquals(2,status.getJSONArray("release_checks").length());for(int i=0;i<2;i++)assertEquals("passed",status.getJSONArray("release_checks").getJSONObject(i).getString("state"));
        sql("UPDATE slots SET metadata=x'010203' WHERE slot_id='"+slot+"'");status=store.syncStatus(true);JSONArray checks=status.getJSONArray("release_checks");JSONObject failed=null;for(int i=0;i<checks.length();i++)if(slot.equals(checks.getJSONObject(i).getString("slot_id")))failed=checks.getJSONObject(i);assertNotNull(failed);assertEquals("failed",failed.getString("state"));assertTrue(failed.isNull("sha256"));assertEquals(2,checks.length());store.remove(OfflineSyncValues.json("slot_id",slot,"expected_generation",1));
    }
    private void changeSidecar(String selectedNamespace,java.util.function.Consumer<JSONObject> change)throws Exception{
        assertTrue(context.getPackageName().endsWith(".offlineqa"));String profile=OfflineCipher.sha256((context.getPackageName()+":offline-profile@1:"+selectedNamespace).getBytes(StandardCharsets.UTF_8));
        File catalog=new File(context.getNoBackupFilesDir(),"offline-v1/"+profile+"/catalog.sqlite");OfflineCipher cipher=new OfflineCipher(context,selectedNamespace);
        try(SQLiteConnection connection=new BundledSQLiteDriver().open(catalog.getAbsolutePath())){
            JSONObject state;try(SQLiteStatement row=connection.prepare("SELECT value FROM sync_state WHERE id=1")){assertTrue(row.step());state=OfflinePackageValidator.parse(cipher.open(row.getBlob(0),"device-sync-state@1"));}
            change.accept(state);byte[] bytes=cipher.seal(state.toString().getBytes(StandardCharsets.UTF_8),"device-sync-state@1");try(SQLiteStatement update=connection.prepare("UPDATE sync_state SET value=? WHERE id=1")){update.bindBlob(1,bytes);while(update.step()){} }
        }
    }
    @Test public void foreignProcessJournalIsInterruptedAndCannotResume()throws Exception{
        JSONObject policy=authorize(any());JSONObject started=store.syncBegin(request(policy,"manual"),binding,permitted());assertEquals("running",started.getJSONObject("run").getString("state"));
        changeSidecar(namespace,state->{try{state.getJSONArray("runs").getJSONObject(0).put("process_id",UUID.randomUUID().toString());}catch(Exception error){throw new AssertionError(error);}});
        store.close();store=new OfflinePackStore(context,namespace);JSONObject status=store.syncStatus(false);assertEquals("interrupted",status.getJSONArray("runs").getJSONObject(0).getString("state"));assertEquals("paused",status.getJSONArray("policies").getJSONObject(0).getString("state"));assertEquals(1,generation());
    }
    @Test public void leaseCrossedDuringStagingRollsBackSlotBindingAndRunPublication()throws Exception{
        JSONObject policy=authorize(any());JSONObject started=store.syncBegin(request(policy,"manual"),binding,permitted());String id=started.getJSONObject("run").getString("run_id");
        JSONObject plan=planned.getJSONObject("plan");store.syncStage(id,"confirming",plan,UUID.randomUUID().toString());store.syncStage(id,"committing",null,null);
        changeSidecar(namespace,state->{try{JSONObject entry=state.getJSONArray("runs").getJSONObject(0);entry.put("expires_at",java.time.Instant.now().plusSeconds(2).toString());entry.put("monotonic_deadline",android.os.SystemClock.elapsedRealtime()+2000);}catch(Exception error){throw new AssertionError(error);}});
        java.util.concurrent.atomic.AtomicInteger samples=new java.util.concurrent.atomic.AtomicInteger();
        fails("OFFLINE_SYNC_LEASE_EXPIRED",()->store.syncCommit(id,candidate,Arrays.copyOf(updated,updated.length),()->true,()->{
            if(samples.incrementAndGet()==1)try{Thread.sleep(2500);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new AssertionError(error);}return permitted();
        }));
        assertEquals(1,generation());JSONObject status=store.syncStatus(false);assertEquals("paused",status.getJSONArray("policies").getJSONObject(0).getString("state"));assertEquals("interrupted",status.getJSONArray("runs").getJSONObject(0).getString("state"));assertEquals(descriptor.getString("sha256"),status.getJSONArray("policies").getJSONObject(0).getJSONObject("binding").getString("sha256"));
    }
    @Test public void noChangeCannotCommitAfterLeaseDeadline()throws Exception{
        JSONObject policy=authorize(any());JSONObject started=store.syncBegin(request(policy,"manual"),binding,permitted());String id=started.getJSONObject("run").getString("run_id");
        changeSidecar(namespace,state->{try{JSONObject entry=state.getJSONArray("runs").getJSONObject(0);entry.put("expires_at",java.time.Instant.now().plusSeconds(2).toString());entry.put("monotonic_deadline",android.os.SystemClock.elapsedRealtime()+2000);}catch(Exception error){throw new AssertionError(error);}});
        java.util.concurrent.atomic.AtomicInteger checks=new java.util.concurrent.atomic.AtomicInteger();
        fails("OFFLINE_SYNC_LEASE_EXPIRED",()->store.syncNoChange(id,()->{if(checks.incrementAndGet()==3)try{Thread.sleep(2500);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new AssertionError(error);}return true;},()->permitted()));
        assertEquals(1,generation());assertEquals("interrupted",store.syncStatus(false).getJSONArray("runs").getJSONObject(0).getString("state"));
    }
    @Test public void actualWorkManagerRunsHistoryCheckWithoutActivityOrBootstrap()throws Exception{
        OfflineRuntime runtime=OfflineRuntime.get(context);OfflinePackStore shared=runtime.store();String ownedSlot=UUID.randomUUID().toString();JSONObject installed=install(0);installed.put("slot_id",ownedSlot);shared.install(installed,descriptor,original);
        runtime.http().session.persist(UUID.randomUUID().toString());NativeHttpBridge.SessionFence fence=runtime.http().freezeSession();String sessionBinding=runtime.http().sessionBinding(fence);
        JSONObject status=shared.status();JSONObject preview=shared.syncPreview(OfflineSyncValues.json("slot_id",ownedSlot,"expected_generation",1,"expected_profile_id",status.getString("profile_id"),"expected_owner_epoch",status.getLong("owner_epoch"),"interval_seconds",900,"conditions",any()),sessionBinding);
        JSONObject policy=shared.syncApply(OfflineSyncValues.json("preview_id",preview.getString("preview_id"),"expected_fingerprint",preview.getString("fingerprint"),"expected_policy_revision",0,"allow_continuous_history_updates",true),sessionBinding);
        String otherSlot=UUID.randomUUID().toString();JSONObject otherInstalled=install(0);otherInstalled.put("slot_id",otherSlot);shared.install(otherInstalled,descriptor,original);
        JSONObject otherPreview=shared.syncPreview(OfflineSyncValues.json("slot_id",otherSlot,"expected_generation",1,"expected_profile_id",status.getString("profile_id"),"expected_owner_epoch",status.getLong("owner_epoch"),"interval_seconds",900,"conditions",any()),sessionBinding);
        JSONObject otherPolicy=shared.syncApply(OfflineSyncValues.json("preview_id",otherPreview.getString("preview_id"),"expected_fingerprint",otherPreview.getString("fingerprint"),"expected_policy_revision",0,"allow_continuous_history_updates",true),sessionBinding);
        changeSidecar(BuildConfig.SESSION_NAMESPACE,state->{try{for(int i=0;i<state.getJSONArray("policies").length();i++){JSONObject p=state.getJSONArray("policies").getJSONObject(i).getJSONObject("policy");if(p.getString("policy_id").equals(policy.getString("policy_id"))||p.getString("policy_id").equals(otherPolicy.getString("policy_id")))p.put("next_due_at",java.time.Instant.now().minusSeconds(1).toString());}}catch(Exception error){throw new AssertionError(error);}});
        try(okhttp3.mockwebserver.MockWebServer server=new okhttp3.mockwebserver.MockWebServer()){
            server.start(java.net.InetAddress.getByName("127.0.0.1"),BuildConfig.API_PORT);
            server.enqueue(new okhttp3.mockwebserver.MockResponse().setBody(noChange.toString()).addHeader("Content-Type","application/json").addHeader("X-Tire-Offline-Owner-Scope",descriptor.getString("owner_scope_id")));
            server.enqueue(new okhttp3.mockwebserver.MockResponse().setBody(noChange.toString()).addHeader("Content-Type","application/json").addHeader("X-Tire-Offline-Owner-Scope",descriptor.getString("owner_scope_id")));
            OneTimeWorkRequest job=new OneTimeWorkRequest.Builder(OfflineSyncWorker.class).build();WorkManager manager=WorkManager.getInstance(context);manager.enqueue(job).getResult().get(5,TimeUnit.SECONDS);
            WorkInfo info=null;long deadline=android.os.SystemClock.elapsedRealtime()+30000;
            while(android.os.SystemClock.elapsedRealtime()<deadline){info=manager.getWorkInfoById(job.getId()).get(2,TimeUnit.SECONDS);if(info!=null&&info.getState().isFinished())break;Thread.sleep(100);}
            assertNotNull(info);assertEquals(WorkInfo.State.SUCCEEDED,info.getState());assertEquals(2,server.getRequestCount());
            okhttp3.mockwebserver.RecordedRequest sent=server.takeRequest(2,TimeUnit.SECONDS);assertEquals("/v1/offline-pack-updates:prepare",sent.getPath());assertEquals("1",sent.getHeader("X-Tire-Offline-Sync"));
            JSONObject after=shared.syncStatus(false);JSONObject run=after.getJSONArray("runs").getJSONObject(after.getJSONArray("runs").length()-1);assertEquals("os_job",run.getString("trigger"));assertEquals("no_change",run.getString("state"));
            assertEquals("no_change",after.getJSONArray("runs").getJSONObject(after.getJSONArray("runs").length()-2).getString("state"));
            shared.syncChange(change(policy),true);shared.syncChange(change(otherPolicy),true);runtime.reconcile();runtime.http().reset();shared.remove(OfflineSyncValues.json("slot_id",ownedSlot,"expected_generation",1));shared.remove(OfflineSyncValues.json("slot_id",otherSlot,"expected_generation",1));
        }
    }
}
