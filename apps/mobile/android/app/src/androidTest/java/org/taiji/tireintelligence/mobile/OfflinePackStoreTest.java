package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import android.content.Context;
import android.system.Os;
import androidx.sqlite.SQLiteConnection;
import androidx.sqlite.SQLiteStatement;
import androidx.sqlite.driver.bundled.BundledSQLiteDriver;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Ignore;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Real bundled SQLite/FTS5 + Android Keystore; only dedicated offlineQa profiles. */
@RunWith(AndroidJUnit4.class)
public final class OfflinePackStoreTest {
    private Context context;
    private byte[] raw;
    private JSONObject descriptor;
    private final List<String> namespaces = new ArrayList<>();
    private final List<OfflinePackStore> stores = new ArrayList<>();

    @Before public void fixture() throws Exception {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue("Dedicated QA app is required", context.getPackageName().endsWith(".offlineqa"));
        raw = asset("offline-producer-v2/valid-envelope.json");
        descriptor = new JSONObject(new String(asset("offline-producer-v2/valid-descriptor.json"), StandardCharsets.UTF_8));
        assertEquals("Actual backend producer fixture", "0076612dde0739fa4f3f1ea22514d102e4d6bc5204f823dbc0ae3e56821fb014", OfflineCipher.sha256(raw));
    }

    private byte[] asset(String name) throws Exception {
        try (InputStream input = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(name)) { return readBytes(input); }
    }

    private static byte[] readBytes(InputStream input) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[65536]; int count;
        while ((count = input.read(buffer)) != -1) bytes.write(buffer, 0, count);
        return bytes.toByteArray();
    }

    private String namespace() { String namespace = "qa-" + UUID.randomUUID(); namespaces.add(namespace); return namespace; }
    private OfflinePackStore store(String namespace) throws Exception { OfflinePackStore store = new OfflinePackStore(context, namespace); stores.add(store); return store; }
    private OfflinePackStore store() throws Exception { return store(namespace()); }
    private static JSONObject json(Object... pairs) throws Exception {
        JSONObject value = new JSONObject();
        for (int i=0;i<pairs.length;i+=2) value.put((String)pairs[i], pairs[i+1]);
        return value;
    }

    private JSONObject installRequest(String slot, long generation) throws Exception {
        return json("package_id",descriptor.getString("id"),"expected_sha256",descriptor.getString("sha256"),
            "expected_byte_count",raw.length,"approved_plan_fingerprint",descriptor.getString("plan_fingerprint"),
            "slot_id",slot,"expected_generation",generation,"allow_device_storage",true);
    }

    private static JSONObject search(String slot, long generation, String query) throws Exception {
        return json("slot_id",slot,"expected_generation",generation,"query",query,"limit",50,"offset",0);
    }

    private static JSONObject slotRequest(String slot, long generation) throws Exception {
        return json("slot_id",slot,"expected_generation",generation);
    }

    private File directory(String namespace) throws Exception {
        assertTrue(namespace.startsWith("qa-") && context.getPackageName().endsWith(".offlineqa"));
        String profile = OfflineCipher.sha256((context.getPackageName()+":offline-profile@1:"+namespace).getBytes(StandardCharsets.UTF_8));
        File target = new File(context.getNoBackupFilesDir(),"offline-v1/"+profile);
        assertTrue(target.getCanonicalPath().startsWith(context.getNoBackupFilesDir().getCanonicalPath()+File.separator));
        return target;
    }

    private interface Checked { void run() throws Exception; }
    private static void fails(String expected, Checked operation) throws Exception {
        try { operation.run(); fail("Expected "+expected); }
        catch(NativeFailure failure) { assertEquals(expected, failure.code); }
    }

    /** User approval 2026-10-03: retain synthetic QA data and Keystore aliases as evidence instead of deleting them. */
    @After public void cleanup() throws Exception {
        for(OfflinePackStore store:stores) store.close();
        if(context!=null) for(String namespace:namespaces) {
            File[] sealed=new File(directory(namespace),"blobs").listFiles();
            if(sealed!=null&&sealed.length>0) assertTrue(new OfflineCipher(context,namespace).hasKey());
        }
    }

    @Test public void realProducerFourDomainsRestartCjkFtsAndEncryptedDisk() throws Exception {
        String namespace=namespace(), slot=UUID.randomUUID().toString(); OfflinePackStore store=store(namespace);
        assertTrue(store.status().getBoolean("available")); assertEquals(0,store.list().getJSONArray("items").length());
        JSONObject installed=store.install(installRequest(slot,0),descriptor,raw);
        assertEquals(1,installed.getLong("generation")); assertEquals(raw.length,store.status().getLong("total_bytes"));
        JSONObject found=store.search(search(slot,1,"")); assertEquals(9,found.getInt("total"));
        assertTrue(store.search(search(slot,1,"车库")).getInt("total")>=1);
        JSONObject chinese=store.search(search(slot,1,"车库")).getJSONArray("items").getJSONObject(0);
        JSONObject detail=store.read(json("slot_id",slot,"expected_generation",1,"document_id",chinese.getString("id")));
        assertEquals("garage",detail.getJSONObject("context").getString("kind"));
        JSONArray docs=found.getJSONArray("items"); JSONObject sourceDoc=null;
        for(int i=0;i<docs.length();i++) if("tire".equals(docs.getJSONObject(i).getString("kind"))) sourceDoc=docs.getJSONObject(i);
        assertNotNull(sourceDoc);
        JSONObject source=store.read(json("slot_id",slot,"expected_generation",1,"document_id",sourceDoc.getString("id")));
        assertEquals(sourceDoc.getString("observed_at"),source.getJSONObject("member").getJSONObject("source").getString("observed_at"));
        assertNotEquals(installed.getString("installed_at"),sourceDoc.getString("observed_at"));
        assertEquals(0,store.search(search(slot,1,"\" OR 1=1; DROP TABLE docs; --")).getInt("total"));
        assertEquals(9,store.search(search(slot,1,"")).getInt("total"));
        store.close(); OfflinePackStore restarted=store(namespace);
        assertEquals(descriptor.getString("sha256"),restarted.list().getJSONArray("items").getJSONObject(0).getString("sha256"));
        assertTrue(restarted.search(search(slot,1,"Brand A")).getInt("total")>=1);
        for(File file:allFiles(directory(namespace))) {
            try(InputStream input=new FileInputStream(file)) {
                String disk=new String(readBytes(input),StandardCharsets.ISO_8859_1);
                assertFalse(file.getName(),disk.contains("Fixture Tire"));
                assertFalse(file.getName(),disk.contains("Synthetic wet braking"));
                assertFalse(file.getName(),disk.contains("offline-pack@1"));
                assertFalse(file.getName(),disk.contains(descriptor.getString("owner_scope_id")));
            }
        }
    }

    private static List<File> allFiles(File root) {
        List<File> result=new ArrayList<>(); File[] children=root.listFiles();
        if(children!=null) for(File child:children) { if(child.isDirectory()) result.addAll(allFiles(child)); else result.add(child); }
        return result;
    }

    @Test public void deletionTombstoneAndStaleCasNeverResetGeneration() throws Exception {
        OfflinePackStore store=store(); String slot=UUID.randomUUID().toString();
        store.install(installRequest(slot,0),descriptor,raw);
        fails("OFFLINE_STALE_GENERATION",()->store.install(installRequest(slot,0),descriptor,raw));
        assertEquals(2,store.install(installRequest(slot,1),descriptor,raw).getLong("generation"));
        fails("OFFLINE_STALE_GENERATION",()->store.search(search(slot,1,"")));
        assertEquals(3,store.remove(slotRequest(slot,2)).getLong("generation"));
        assertEquals(0,store.list().getJSONArray("items").length());
        fails("OFFLINE_STALE_GENERATION",()->store.install(installRequest(slot,0),descriptor,raw));
        fails("OFFLINE_STALE_GENERATION",()->store.remove(slotRequest(slot,2)));
        assertEquals(4,store.install(installRequest(slot,3),descriptor,raw).getLong("generation"));
    }

    @Test public void resetLocksPrivateCopyAndExplicitUnlockKeepsExportOwner() throws Exception {
        OfflinePackStore store=store(); String slot=UUID.randomUUID().toString();
        JSONObject installed=store.install(installRequest(slot,0),descriptor,raw);
        assertEquals(2,store.resetOwnerEpoch());
        JSONObject locked=store.list().getJSONArray("items").getJSONObject(0);
        assertTrue(locked.getBoolean("locked")); assertTrue(locked.getBoolean("previous_owner"));
        fails("OFFLINE_OWNER_LOCKED",()->store.search(search(slot,1,"")));
        fails("OFFLINE_OWNER_LOCKED",()->store.install(installRequest(slot,1),descriptor,raw));
        fails("OFFLINE_PACKAGE_INVALID",()->store.unlockPreviousOwner(json("slot_id",slot,"expected_generation",1,"allow_previous_owner",false)));
        JSONObject unlocked=store.unlockPreviousOwner(json("slot_id",slot,"expected_generation",1,"allow_previous_owner",true));
        assertFalse(unlocked.getBoolean("locked")); assertTrue(unlocked.getBoolean("previous_owner"));
        assertEquals(installed.getString("owner_scope_id"),unlocked.getString("owner_scope_id"));
        assertEquals(9,store.search(search(slot,1,"")).getInt("total"));
        store.resetOwnerEpoch(); fails("OFFLINE_OWNER_LOCKED",()->store.search(search(slot,1,"")));
        assertTrue(store.remove(slotRequest(slot,1)).getBoolean("removed"));
    }

    @Ignore("Destroys a QA Keystore alias mid-test; retained-evidence policy per user approval 2026-10-03.")
    @Test public void tamperedBodyAndMissingKeyFailClosedAndCanDeleteCiphertext() throws Exception {
        String namespace=namespace(),slot=UUID.randomUUID().toString(); OfflinePackStore store=store(namespace);
        store.install(installRequest(slot,0),descriptor,raw);
        File[] bodies=new File(directory(namespace),"blobs").listFiles(); assertNotNull(bodies); assertEquals(1,bodies.length);
        byte[] sealed; try(InputStream input=new FileInputStream(bodies[0])) { sealed=readBytes(input); }
        sealed[sealed.length-1]^=1;
        try(FileOutputStream output=new FileOutputStream(bodies[0])) { output.write(sealed); output.getFD().sync(); }
        fails("OFFLINE_CORRUPT",()->store.search(search(slot,1,"")));
        new OfflineCipher(context,namespace).deleteQaKey();
        fails("OFFLINE_KEY_MISSING",()->store.search(search(slot,1,"")));
        fails("OFFLINE_KEY_MISSING",()->store.install(installRequest(UUID.randomUUID().toString(),0),descriptor,raw));
        assertTrue(store.remove(slotRequest(slot,1)).getBoolean("removed"));
        assertEquals(0,new File(directory(namespace),"blobs").listFiles().length);
    }

    @Test public void installCommitCancellationPreservesPreviousGenerationAndOneCipher() throws Exception {
        String namespace=namespace(),slot=UUID.randomUUID().toString(); OfflinePackStore store=store(namespace);
        store.install(installRequest(slot,0),descriptor,raw);
        AtomicInteger checks=new AtomicInteger();
        fails("OFFLINE_OPERATION_CANCELLED",()->store.install(installRequest(slot,1),descriptor,raw,()->checks.incrementAndGet()<5));
        assertEquals(5,checks.get());
        assertEquals(1,store.list().getJSONArray("items").getJSONObject(0).getLong("generation"));
        assertEquals(9,store.search(search(slot,1,"")).getInt("total"));
        assertEquals(1,new File(directory(namespace),"blobs").listFiles().length);
    }

    @Test public void twoStoreInstancesCompeteWithOneCasWinnerAndNoExtraCipher() throws Exception {
        String namespace=namespace(),slot=UUID.randomUUID().toString(); OfflinePackStore first=store(namespace),second=store(namespace);
        first.install(installRequest(slot,0),descriptor,raw); CountDownLatch ready=new CountDownLatch(2),go=new CountDownLatch(1);
        ExecutorService pool=Executors.newFixedThreadPool(2);
        try {
            List<Future<String>> futures=new ArrayList<>();
            for(OfflinePackStore store:Arrays.asList(first,second)) futures.add(pool.submit(()-> {
                ready.countDown();go.await();
                try { store.install(installRequest(slot,1),descriptor,raw);return "installed"; }
                catch(NativeFailure failure) { return failure.code; }
            }));
            ready.await();go.countDown(); List<String> results=Arrays.asList(futures.get(0).get(),futures.get(1).get());
            assertTrue(results.contains("installed"));assertTrue(results.contains("OFFLINE_STALE_GENERATION"));
            assertEquals(2,first.list().getJSONArray("items").getJSONObject(0).getLong("generation"));
            assertEquals(1,new File(directory(namespace),"blobs").listFiles().length);
        } finally { pool.shutdownNow(); }
    }

    @Test public void boundedQuerySlotLimitAndStartupOwnedOrphanCleanup() throws Exception {
        String namespace=namespace(),slot=UUID.randomUUID().toString();OfflinePackStore store=store(namespace);
        store.install(installRequest(slot,0),descriptor,raw);
        fails("OFFLINE_PACKAGE_INVALID",()->store.search(search(slot,1,"x".repeat(501))));
        JSONObject over=search(slot,1,"");over.put("limit",51);fails("OFFLINE_PACKAGE_INVALID",()->store.search(over));
        for(int i=1;i<16;i++) store.install(installRequest(UUID.randomUUID().toString(),0),descriptor,raw);
        fails("OFFLINE_STORE_LIMIT",()->store.install(installRequest(UUID.randomUUID().toString(),0),descriptor,raw));
        File orphan=new File(new File(directory(namespace),"blobs"),UUID.randomUUID()+".sealed");
        try(FileOutputStream output=new FileOutputStream(orphan)) { output.write(new byte[]{1,2,3}); }
        store.close();OfflinePackStore reopened=store(namespace);
        assertFalse(orphan.exists());assertEquals(16,reopened.list().getJSONArray("items").length());
    }

    @Test public void catalogTriggerAbortRollsBackPointerAndCleansStaging() throws Exception {
        String namespace=namespace(),slot=UUID.randomUUID().toString();OfflinePackStore store=store(namespace);
        store.install(installRequest(slot,0),descriptor,raw);
        File catalog=new File(directory(namespace),"catalog.sqlite");
        try(SQLiteConnection sql=new BundledSQLiteDriver().open(catalog.getAbsolutePath());
            SQLiteStatement trigger=sql.prepare("CREATE TRIGGER synthetic_abort BEFORE UPDATE ON slots BEGIN SELECT RAISE(ABORT,'synthetic'); END")) { trigger.step(); }
        fails("OFFLINE_STORE_UNAVAILABLE",()->store.install(installRequest(slot,1),descriptor,raw));
        assertEquals(1,store.list().getJSONArray("items").getJSONObject(0).getLong("generation"));
        assertEquals(9,store.search(search(slot,1,"")).getInt("total"));
        assertEquals(1,new File(directory(namespace),"blobs").listFiles().length);
    }

    @Test public void lostCatalogOwnerRowAndTamperedEpochNeverUnlockOldPrivateData() throws Exception {
        String namespace=namespace(),slot=UUID.randomUUID().toString();OfflinePackStore store=store(namespace);
        store.install(installRequest(slot,0),descriptor,raw);store.resetOwnerEpoch();
        File catalog=new File(directory(namespace),"catalog.sqlite");
        try(SQLiteConnection sql=new BundledSQLiteDriver().open(catalog.getAbsolutePath());
            SQLiteStatement tamper=sql.prepare("UPDATE owner_state SET epoch=1 WHERE id=1")) { tamper.step(); }
        fails("OFFLINE_CORRUPT",()->store.search(search(slot,1,"")));
        store.close(); OfflinePackStore reloaded=store(namespace);
        fails("OFFLINE_CORRUPT",()->reloaded.search(search(slot,1,"")));
        reloaded.close();
        try(SQLiteConnection sql=new BundledSQLiteDriver().open(catalog.getAbsolutePath());
            SQLiteStatement missing=sql.prepare("DELETE FROM owner_state")) { missing.step(); }
        fails("OFFLINE_CORRUPT",()->store(namespace));
        assertTrue(catalog.delete());
        fails("OFFLINE_CORRUPT",()->store(namespace));
    }

    @Test public void existingKeyWithLostEmptyCatalogCannotSilentlyRestartOwnerOrTombstones() throws Exception {
        String namespace=namespace(),slot=UUID.randomUUID().toString(); OfflinePackStore store=store(namespace);
        store.install(installRequest(slot,0),descriptor,raw);store.remove(slotRequest(slot,1));store.close();
        assertEquals(0,new File(directory(namespace),"blobs").listFiles().length);
        assertTrue(new File(directory(namespace),"catalog.sqlite").delete());
        fails("OFFLINE_CORRUPT",()->store(namespace));
    }

    @Test public void fourRealEightMibOriginalBytePackagesFitButFifthAndOversizedReplacementDoNot() throws Exception {
        OfflinePackStore store=store();
        byte[] padded=Arrays.copyOf(raw,8*1024*1024);
        Arrays.fill(padded,raw.length,padded.length,(byte)' ');
        JSONObject paddedDescriptor=new JSONObject(descriptor.toString());
        paddedDescriptor.put("sha256",OfflineCipher.sha256(padded));paddedDescriptor.put("byte_count",padded.length);
        List<String> slots=new ArrayList<>();
        for(int i=0;i<4;i++) {
            String slot=UUID.randomUUID().toString();slots.add(slot);
            JSONObject request=installRequest(slot,0).put("expected_sha256",paddedDescriptor.getString("sha256"))
                .put("expected_byte_count",padded.length);
            store.install(request,paddedDescriptor,padded);
        }
        assertEquals(32L*1024*1024,store.status().getLong("total_bytes"));
        String fifth=UUID.randomUUID().toString();
        fails("OFFLINE_STORE_LIMIT",()->store.install(installRequest(fifth,0),descriptor,raw));
        // Replacement capacity subtracts the old committed original size.
        JSONObject smaller=store.install(installRequest(slots.get(0),1),descriptor,raw);
        assertEquals(2,smaller.getLong("generation"));
        assertEquals(24L*1024*1024+raw.length,store.status().getLong("total_bytes"));
        JSONObject tooLarge=installRequest(fifth,0).put("expected_sha256",paddedDescriptor.getString("sha256"))
            .put("expected_byte_count",padded.length);
        fails("OFFLINE_STORE_LIMIT",()->store.install(tooLarge,paddedDescriptor,padded));
        store.install(installRequest(fifth,0),descriptor,raw);
        assertEquals(24L*1024*1024+raw.length*2L,store.status().getLong("total_bytes"));
        assertEquals(9,store.search(search(slots.get(0),2,"")).getInt("total"));
    }

    private static JSONObject fallbackIntent(String model, String size) throws Exception {
        return json("schema", "device-fallback-intent@1", "attempt_id", UUID.randomUUID().toString(),
            "query_fingerprint", "a".repeat(64), "source_id", "fixture", "source_access_generation", 0,
            "query", json("model", model, "size", size == null ? JSONObject.NULL : size), "filters", new JSONArray(),
            "failure", json("scope", "source_response", "reason", "upstream_network_error", "query_id", UUID.randomUUID().toString()));
    }
    private JSONObject fallbackRequest(OfflinePackStore store, String slot, JSONObject intent, String decision) throws Exception {
        JSONObject status = store.status();
        return json("intent", intent, "slot_id", slot, "expected_generation", 1,
            "expected_sha256", descriptor.getString("sha256"), "expected_profile_id", status.getString("profile_id"),
            "expected_owner_epoch", status.getLong("owner_epoch"), "decision", decision);
    }
    private static JSONObject consume(JSONObject receipt) throws Exception {
        return json("grant_id", receipt.getString("id"), "intent", receipt.getJSONObject("intent"));
    }
    @Test public void fallbackNeedsOwnDecisionThenReturnsExactHistoricalMemberAndSingleReceipt() throws Exception {
        OfflinePackStore store=store(); String slot=UUID.randomUUID().toString();
        store.install(installRequest(slot,0),descriptor,raw);
        fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(json("grant_id",UUID.randomUUID().toString(),"intent",fallbackIntent("Fixture Tire","265/40ZR20"))));
        JSONObject request=fallbackRequest(store,slot,fallbackIntent("Fixture Tire","265/40ZR20"),"allow");
        JSONObject receipt=store.decideFallback(request), result=store.consumeFallback(consume(receipt));
        assertEquals("local_once",result.getString("fallback_consent"));assertFalse(result.getBoolean("complete_query_result"));
        assertEquals(1,result.getJSONArray("members").length());assertEquals("consumed",result.getJSONObject("grant").getString("state"));
        assertEquals(descriptor.getString("sha256"),result.getJSONObject("slot").getString("sha256"));
        JSONArray originals=new JSONObject(new String(raw,StandardCharsets.UTF_8)).getJSONArray("members");JSONObject original=null;
        for(int index=0;index<originals.length();index++){JSONObject member=originals.getJSONObject(index);if(member.getJSONObject("reference").getString("kind").equals("tire"))original=member;}
        assertNotNull(original);assertEquals(original.toString(),result.getJSONArray("members").getJSONObject(0).toString());
        fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(receipt)));
        fails("OFFLINE_FALLBACK_USED",()->store.decideFallback(request));
    }
    @Test public void fallbackDenyCannotBeConsumedOrReallowedForSameAttempt() throws Exception {
        OfflinePackStore store=store();String slot=UUID.randomUUID().toString();store.install(installRequest(slot,0),descriptor,raw);
        JSONObject request=fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"deny"),receipt=store.decideFallback(request);
        assertEquals("denied",receipt.getString("state"));assertFalse(receipt.has("members"));
        fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(receipt)));
        request.put("decision","allow");fails("OFFLINE_FALLBACK_USED",()->store.decideFallback(request));
    }
    @Test public void fallbackRejectsAllAdvancedFiltersAndUnprovenFailureReasons() throws Exception {
        OfflinePackStore store=store();String slot=UUID.randomUUID().toString();store.install(installRequest(slot,0),descriptor,raw);
        JSONObject intent=fallbackIntent("Fixture Tire",null),request=fallbackRequest(store,slot,intent,"allow");
        intent.put("filters",new JSONArray().put(json("field","xl","op","eq","value",true)));
        fails("OFFLINE_FALLBACK_UNSUPPORTED",()->store.decideFallback(request));intent.put("filters",new JSONArray());
        for(String reason: new String[]{"unsupported_model","source_paused","source_fetch_failed","HTTP_403","API_REQUEST_FAILED"}) {
            intent.getJSONObject("failure").put("reason",reason);
            fails("OFFLINE_FALLBACK_INVALID",()->store.decideFallback(request));
        }
    }
    @Test public void fallbackMismatchBurnsGrantEvenWithUnchangedFrontendFingerprint() throws Exception {
        OfflinePackStore store=store();String slot=UUID.randomUUID().toString();store.install(installRequest(slot,0),descriptor,raw);
        JSONObject receipt=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        JSONObject changed=consume(receipt);changed.getJSONObject("intent").getJSONObject("query").put("model","Different Tire");
        fails("OFFLINE_FALLBACK_MISMATCH",()->store.consumeFallback(changed));
        fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(receipt)));
    }
    @Test public void fallbackExactMatchingDoesNotFoldZrOrInventCurrentOnlineAbsence() throws Exception {
        OfflinePackStore store=store();String slot=UUID.randomUUID().toString();store.install(installRequest(slot,0),descriptor,raw);
        for(JSONObject intent:new JSONObject[]{fallbackIntent("Fixture Tire","265/40R20"),fallbackIntent("Fixture",null),fallbackIntent("Fixture Tire",null).put("source_id","different")}) {
            JSONObject receipt=store.decideFallback(fallbackRequest(store,slot,intent,"allow"));
            JSONObject result=store.consumeFallback(consume(receipt));assertEquals(0,result.getJSONArray("members").length());
            assertFalse(result.getBoolean("complete_query_result"));
        }
    }
    private static final class FallbackClock implements OfflineFallbackGrant.Clock {
        long wall=1700000000000L,mono=1000000L;
        public long wall(){return wall;}public long monotonic(){return mono;}
    }
    @Test public void fallbackExpiresAtFiveMinutesAndWallClockRollbackCannotExtendIt() throws Exception {
        String ns=namespace();FallbackClock clock=new FallbackClock();OfflinePackStore store=new OfflinePackStore(context,ns,clock);stores.add(store);
        String slot=UUID.randomUUID().toString();store.install(installRequest(slot,0),descriptor,raw);
        JSONObject receipt=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        clock.mono+=300000;fails("OFFLINE_FALLBACK_EXPIRED",()->store.consumeFallback(consume(receipt)));
        JSONObject second=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        clock.wall--;fails("OFFLINE_FALLBACK_EXPIRED",()->store.consumeFallback(consume(second)));
    }
    @Test public void fallbackKeepsDecisionMonotonicClockAcrossSlowAuditAndInvalidatesDocument() throws Exception {
        FallbackClock clock=new FallbackClock();OfflineFallbackGrant grants=new OfflineFallbackGrant(clock);
        JSONObject intent=fallbackIntent("Fixture Tire",null),request=json("decision","allow","slot_id",UUID.randomUUID().toString(),"expected_generation",1,"expected_sha256","b".repeat(64));
        OfflineFallbackGrant.Pending prepared=grants.receipt(intent,request,"qa-profile",1);
        clock.mono+=120000;clock.wall+=10000;grants.register(prepared);
        clock.mono+=190000;clock.wall+=190000;
        fails("OFFLINE_FALLBACK_EXPIRED",()->grants.take(prepared.receipt.getString("id"),intent));
        OfflinePackStore store=store();String slot=UUID.randomUUID().toString();store.install(installRequest(slot,0),descriptor,raw);
        JSONObject request2=fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"),receipt=store.decideFallback(request2);
        store.invalidateFallbackGrants();fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(receipt)));
        fails("OFFLINE_FALLBACK_USED",()->store.decideFallback(request2));
    }
    @Test public void fallbackOwnerResetUnlockDeleteAndRestartCannotReviveGrant() throws Exception {
        String ns=namespace(),slot=UUID.randomUUID().toString();OfflinePackStore store=store(ns);store.install(installRequest(slot,0),descriptor,raw);
        JSONObject grant=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        store.resetOwnerEpoch();fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(grant)));
        store.unlockPreviousOwner(json("slot_id",slot,"expected_generation",1,"allow_previous_owner",true));
        fails("OFFLINE_OWNER_LOCKED",()->store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow")));
        // Separate fresh profile keeps restart and delete checks independent of old-owner rejection.
        String nextNs=namespace(),nextSlot=UUID.randomUUID().toString();OfflinePackStore current=store(nextNs);current.install(installRequest(nextSlot,0),descriptor,raw);
        JSONObject old=current.decideFallback(fallbackRequest(current,nextSlot,fallbackIntent("Fixture Tire",null),"allow"));current.close();
        OfflinePackStore reloaded=store(nextNs);fails("OFFLINE_FALLBACK_USED",()->reloaded.consumeFallback(consume(old)));
        JSONObject next=reloaded.decideFallback(fallbackRequest(reloaded,nextSlot,fallbackIntent("Fixture Tire",null),"allow"));
        reloaded.remove(slotRequest(nextSlot,1));fails("OFFLINE_STALE_GENERATION",()->reloaded.consumeFallback(consume(next)));
        fails("OFFLINE_FALLBACK_USED",()->reloaded.consumeFallback(consume(next)));
    }
    @Test public void fallbackDecisionNeverReadsCorruptBodyAndFailedConsumptionIsNotReplayed() throws Exception {
        String ns=namespace(),slot=UUID.randomUUID().toString();OfflinePackStore store=store(ns);store.install(installRequest(slot,0),descriptor,raw);
        File blob=new File(directory(ns),"blobs").listFiles()[0];byte[] bytes;
        try(FileInputStream input=new FileInputStream(blob)){bytes=readBytes(input);}bytes[bytes.length-1]^=1;
        try(FileOutputStream output=new FileOutputStream(blob)){output.write(bytes);}
        JSONObject receipt=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        fails("OFFLINE_CORRUPT",()->store.consumeFallback(consume(receipt)));
        fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(receipt)));
    }
    @Test public void fallbackConcurrentConsumerAndRevocationStaySingleUse() throws Exception {
        OfflinePackStore store=store();String slot=UUID.randomUUID().toString();store.install(installRequest(slot,0),descriptor,raw);
        JSONObject receipt=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        ExecutorService executor=Executors.newFixedThreadPool(2);List<Future<String>> runs=new ArrayList<>();
        try {
            for(int index=0;index<2;index++)runs.add(executor.submit(()->{try{store.consumeFallback(consume(receipt));return "success";}catch(NativeFailure error){return error.code;}}));
            List<String> results=Arrays.asList(runs.get(0).get(),runs.get(1).get());assertTrue(results.contains("success"));assertTrue(results.contains("OFFLINE_FALLBACK_USED"));
        }finally{executor.shutdownNow();}
        JSONObject next=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        assertTrue(store.revokeFallback(json("grant_id",next.getString("id"))).getBoolean("revoked"));
        fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(next)));
    }
    @Test public void fallbackEncryptedAuditIsBoundedAndFailedAuditPreventsBodyRelease() throws Exception {
        String ns=namespace(),slot=UUID.randomUUID().toString();OfflinePackStore store=store(ns);store.install(installRequest(slot,0),descriptor,raw);
        for(int index=0;index<70;index++)store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"deny"));
        File catalog=new File(directory(ns),"catalog.sqlite");
        try(SQLiteConnection sql=new BundledSQLiteDriver().open(catalog.getAbsolutePath());SQLiteStatement rows=sql.prepare("SELECT id,value FROM fallback_audit")) {
            int count=0;OfflineCipher cipher=new OfflineCipher(context,ns);
            while(rows.step()){String id=rows.getText(0);byte[] sealed=rows.getBlob(1);assertFalse(new String(sealed,StandardCharsets.UTF_8).contains("Fixture Tire"));
                JSONObject record=new JSONObject(new String(cipher.open(sealed,"fallback-audit@1:"+id),StandardCharsets.UTF_8));assertEquals(id,record.getString("id"));count++;}
            assertEquals(64,count);
        }
        JSONObject receipt=store.decideFallback(fallbackRequest(store,slot,fallbackIntent("Fixture Tire",null),"allow"));
        try(SQLiteConnection sql=new BundledSQLiteDriver().open(catalog.getAbsolutePath());SQLiteStatement trigger=sql.prepare("CREATE TRIGGER reject_fixture_audit BEFORE UPDATE ON fallback_audit BEGIN SELECT RAISE(ABORT,'fixture'); END")){trigger.step();}
        fails("OFFLINE_STORE_UNAVAILABLE",()->store.consumeFallback(consume(receipt)));
        fails("OFFLINE_FALLBACK_USED",()->store.consumeFallback(consume(receipt)));
    }

    @Test public void canonicalAppAliasIsAllowedButProfileChildSymlinkIsRejected() throws Exception {
        String firstNamespace=namespace(),secondNamespace=namespace();
        OfflinePackStore first=store(firstNamespace),second=store(secondNamespace);
        assertTrue(first.status().getBoolean("available"));
        first.close();second.close();
        File child=new File(directory(firstNamespace),"blobs");
        File target=new File(directory(secondNamespace),"blobs");
        assertTrue(child.delete());
        Os.symlink(target.getCanonicalPath(),child.getAbsolutePath());
        try { fails("OFFLINE_INVALID_PROFILE",()->store(firstNamespace)); }
        finally { assertTrue(child.delete());assertTrue(child.mkdir()); }
    }
}
