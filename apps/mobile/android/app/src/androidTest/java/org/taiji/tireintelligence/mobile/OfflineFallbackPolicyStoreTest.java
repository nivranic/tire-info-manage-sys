package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.sqlite.SQLiteConnection;
import androidx.sqlite.SQLiteStatement;
import androidx.sqlite.driver.bundled.BundledSQLiteDriver;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Real Android Keystore and bundled SQLite policy metadata, with fixed loopback HTTP fixtures.
 * Every harness owns a fresh random QA profile. Profiles and keys are deliberately retained.
 * These tests cover policy storage and legacy negative gates, not @2 grant consumption or
 * a claim that continuous fallback is available in the native host.
 */
@RunWith(AndroidJUnit4.class)
public final class OfflineFallbackPolicyStoreTest {
    private interface Checked { void run() throws Exception; }
    private static void fails(String code, Checked action) throws Exception {
        try { action.run(); fail("Expected " + code); }
        catch (NativeFailure failure) { assertEquals(code, failure.code); }
    }
    private static JSONObject json(Object... values) throws Exception {
        JSONObject result = new JSONObject();
        for (int at = 0; at < values.length; at += 2)
            result.put((String) values[at], values[at + 1] == null ? JSONObject.NULL : values[at + 1]);
        return result;
    }
    private static JSONObject copy(JSONObject value) throws Exception {
        return (JSONObject) OfflineTireCriteria.parse(OfflineJsonInteger.stringify(value), 2 * 1024 * 1024, 250000);
    }
    private static byte[] asset(String path) throws Exception {
        try (InputStream stream = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(path)) {
            return stream.readAllBytes();
        }
    }
    private static final class Sample {
        final byte[] bytes;
        final JSONObject descriptor, material;
        Sample(String prefix) throws Exception {
            bytes = asset("offline-producer49/" + prefix + "-pack.json");
            descriptor = OfflinePackageValidator.response(asset("offline-producer49/" + prefix + "-descriptor.json"));
            assertEquals("Original producer bytes", descriptor.getString("sha256"), OfflineCipher.sha256(bytes));
            assertEquals(descriptor.getLong("byte_count"), bytes.length);
            material = OfflinePackageValidator.envelope(bytes, descriptor);
        }
    }
    private static final class Clock implements OfflineFallbackGrant.Clock {
        long wall = System.currentTimeMillis(), mono = android.os.SystemClock.elapsedRealtime();
        public long wall() { return wall; }
        public long monotonic() { return mono; }
        void advance(long millis) { wall += millis; mono += millis; }
    }
    private static final class MemorySession implements SessionState.Store {
        String cookie;
        public String load() { return cookie; }
        public void save(String value) { cookie = value; }
        public void delete() { cookie = null; }
    }
    private static JSONObject queryScope(String source) throws Exception {
        return json("kind", "query", "query_kind", "tire", "sources", new JSONArray().put(json("source_id", source, "access_generation", 0)));
    }
    private static JSONObject sourceScope() throws Exception {
        return json("kind", "source", "source_id", "fixture", "access_generation", 0, "query_kinds", new JSONArray().put("tire"));
    }
    private static JSONObject sessionScope() throws Exception {
        return json("kind", "session", "sources", new JSONArray().put(json("source_id", "fixture", "access_generation", 0,
            "query_kinds", new JSONArray().put("tire"))));
    }
    private static JSONObject source(JSONObject authority, String id) throws Exception {
        JSONArray sources = authority.getJSONArray("sources");
        for (int at = 0; at < sources.length(); at++)
            if (id.equals(sources.getJSONObject(at).getString("source_id"))) return sources.getJSONObject(at);
        throw new AssertionError("Missing explicit synthetic source " + id);
    }
    private static final class Harness implements AutoCloseable {
        final Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        final String namespace = "qa-r49-policy-" + UUID.randomUUID();
        final Clock clock = new Clock();
        final MockWebServer server = new MockWebServer();
        final NativeHttpBridge http;
        OfflinePackStore store;
        JSONObject installed;
        Sample sample;
        Harness() throws Exception {
            assertTrue("Only the dedicated QA application may run these tests", context.getPackageName().endsWith(".offlineqa"));
            store = new OfflinePackStore(context, namespace, clock);
            server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
            server.enqueue(new MockResponse().setBody("{}").addHeader("Set-Cookie",
                "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict"));
            http = new NativeHttpBridge("http://127.0.0.1:" + server.getPort(), new MemorySession());
        }
        void install(String prefix) throws Exception {
            sample = new Sample(prefix);
            installed = store.install(json("package_id", sample.descriptor.getString("id"),
                "expected_sha256", sample.descriptor.getString("sha256"), "expected_byte_count", sample.bytes.length,
                "approved_plan_fingerprint", sample.descriptor.getString("plan_fingerprint"),
                "slot_id", UUID.randomUUID().toString(), "expected_generation", 0, "allow_device_storage", true),
                sample.descriptor, sample.bytes);
        }
        JSONObject refresh() throws Exception { return refresh(true); }
        JSONObject refresh(boolean fixtureCanFetch) throws Exception {
            JSONObject settings = OfflinePackageValidator.response(asset("source-authority49/source-settings.json"));
            JSONObject directory = OfflinePackageValidator.response(asset("source-authority49/sources.json"));
            JSONArray items = settings.getJSONArray("items"); JSONObject tire = null, vehicle = null;
            for (int at = 0; at < items.length(); at++) {
                JSONObject row = items.getJSONObject(at);
                if (tire == null && row.getString("target_kind").equals("tire") && row.getBoolean("can_fetch")) tire = copy(row);
                if (row.getString("source_id").equals("xiaomi-cn-vehicles")) vehicle = copy(row);
            }
            assertNotNull(tire); assertNotNull(vehicle);
            tire.put("source_id", "fixture").put("name", "Explicit synthetic tire policy fixture")
                .put("source_class", "test_fixture").put("supported_models", new JSONArray().put("Fixture Tire"))
                .put("can_fetch", fixtureCanFetch).put("effective_status", fixtureCanFetch ? "ready" : "paused");
            tire.getJSONObject("management").put("access_generation", 0);
            vehicle.put("source_id", "synthetic-oem").put("name", "Explicit synthetic OEM policy fixture")
                .put("source_class", "test_fixture");
            vehicle.getJSONObject("management").put("access_generation", 0);
            items.put(tire).put(vehicle); settings.put("total", items.length());
            directory.getJSONArray("sources").put(json("id", "fixture", "name", tire.getString("name"),
                "status", "ready", "target_kind", "tire", "region", tire.getString("region"),
                "supported_models", new JSONArray().put("Fixture Tire"), "source_setting", copy(tire)));
            String owner = new Sample("nonempty").descriptor.getString("owner_scope_id");
            server.enqueue(new MockResponse().setBody(settings.toString()).addHeader("Content-Type", "application/json")
                .addHeader("X-Tire-Offline-Owner-Scope", owner));
            server.enqueue(new MockResponse().setBody(directory.toString()).addHeader("Content-Type", "application/json"));
            return OfflineFallbackAuthorityCoordinator.refresh(store, http, () -> true);
        }
        JSONObject binding() throws Exception { return store.fallbackStatus().getJSONArray("package_bindings").getJSONObject(0); }
        JSONObject request(String mode, JSONObject scope, JSONObject binding, JSONObject existing) throws Exception {
            JSONObject status = store.fallbackStatus(), authority = status.getJSONObject("authority");
            return json("mode", mode, "scope", copy(scope), "binding", binding == null ? null : copy(binding),
                "allow_same_scope_sync_binding_advance", false, "expected_profile_id", status.getString("profile_id"),
                "expected_owner_epoch", status.getLong("owner_epoch"), "authority", json("runtime_session_id", authority.getString("runtime_session_id"),
                    "authority_revision", authority.getLong("authority_revision")),
                "policy_id", existing == null ? null : existing.getString("policy_id"),
                "expected_policy_revision", existing == null ? 0 : existing.getLong("policy_revision"), "expires_in_seconds", 3600);
        }
        JSONObject preview(String mode, JSONObject scope, JSONObject binding, JSONObject existing) throws Exception {
            return store.fallbackPolicyPreview(request(mode, scope, binding, existing));
        }
        JSONObject apply(JSONObject preview) throws Exception { return store.fallbackPolicyApply(applyRequest(preview)); }
        JSONObject save(String mode, JSONObject scope, JSONObject binding, JSONObject existing) throws Exception {
            return apply(preview(mode, scope, binding, existing));
        }
        JSONObject saveAsk() throws Exception { return save("ask", queryScope("fixture"), null, null); }
        JSONObject change(JSONObject policy, boolean revoke) throws Exception {
            return store.fallbackPolicyChange(json("policy_id", policy.getString("policy_id"),
                "expected_policy_revision", policy.getLong("policy_revision")), revoke);
        }
        JSONArray policies() throws Exception { return store.fallbackStatus().getJSONArray("policies"); }
        void reopen() throws Exception { store.close(); store = new OfflinePackStore(context, namespace, clock); }
        File directory() throws Exception {
            java.lang.reflect.Field field = OfflinePackStore.class.getDeclaredField("directory"); field.setAccessible(true);
            File directory = (File) field.get(store);
            assertEquals(directory.getCanonicalFile(), directory.getAbsoluteFile());
            assertTrue(directory.getPath().startsWith(context.getNoBackupFilesDir().getCanonicalPath() + File.separator));
            return directory;
        }
        SQLiteConnection sql() throws Exception { return new BundledSQLiteDriver().open(new File(directory(), "catalog.sqlite").getAbsolutePath()); }
        void corruptOnlyOwnBody() throws Exception {
            File[] files = new File(directory(), "blobs").listFiles(); assertNotNull(files); assertEquals(1, files.length);
            byte[] sealed = Files.readAllBytes(files[0].toPath()); sealed[sealed.length - 1] ^= 1; Files.write(files[0].toPath(), sealed);
        }
        byte[] sealedJournal() throws Exception {
            try (SQLiteConnection sql = sql(); SQLiteStatement row = sql.prepare("SELECT value FROM fallback_state WHERE id=1")) {
                assertTrue(row.step()); return row.getBlob(0);
            }
        }
        JSONObject journal() throws Exception {
            String profile = store.fallbackStatus().getString("profile_id");
            byte[] clear = new OfflineCipher(context, namespace).open(sealedJournal(), "device-fallback-journal@1:" + profile);
            try { return (JSONObject) OfflineTireCriteria.parse(new String(clear, StandardCharsets.UTF_8), 2 * 1024 * 1024, 250000); }
            finally { Arrays.fill(clear, (byte) 0); }
        }
        JSONObject legacyRequest(long generation) throws Exception {
            JSONObject status = store.fallbackStatus();
            JSONObject intent = json("schema", "device-fallback-intent@1", "attempt_id", UUID.randomUUID().toString(),
                "query_fingerprint", "c".repeat(64), "source_id", "fixture", "source_access_generation", generation,
                "query", json("model", "Fixture Tire", "size", null), "filters", new JSONArray(),
                "failure", json("scope", "api_transport", "reason", "api_timeout", "query_id", null));
            return json("intent", intent, "decision", "allow", "slot_id", installed.getString("slot_id"),
                "expected_generation", installed.getLong("generation"), "expected_sha256", installed.getString("sha256"),
                "expected_profile_id", status.getString("profile_id"), "expected_owner_epoch", status.getLong("owner_epoch"));
        }
        public void close() throws Exception { try { store.close(); } finally { try { http.close(); } finally { server.close(); } } }
    }
    private static JSONObject applyRequest(JSONObject preview) throws Exception {
        return json("preview_id", preview.getString("preview_id"), "expected_fingerprint", preview.getString("fingerprint"),
            "expected_policy_revision", preview.getLong("expected_policy_revision"), "allow_continuous_history_fallback", true);
    }
    private static JSONObject policy(JSONArray policies, String id) throws Exception {
        for (int at = 0; at < policies.length(); at++) if (id.equals(policies.getJSONObject(at).getString("policy_id"))) return policies.getJSONObject(at);
        return null;
    }
    private static JSONObject manualRead(Harness h) throws Exception {
        return json("slot_id", h.installed.getString("slot_id"), "expected_generation", h.installed.getLong("generation"),
            "document_id", h.sample.material.getJSONArray("documents").getJSONObject(0).getString("id"));
    }

    @Test public void installCreatesHostBindingFromOriginalProducerMetadata() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); JSONObject status = h.store.fallbackStatus(), binding = h.binding();
            assertEquals("unknown", status.getJSONObject("authority").getString("state"));
            assertEquals(1, status.getJSONArray("package_bindings").length()); assertEquals(0, status.getJSONArray("missing_package_bindings").length());
            assertEquals(h.installed.getString("slot_id"), binding.getString("slot_id"));
            assertEquals(h.sample.descriptor.getString("id"), binding.getString("package_id"));
            assertEquals(h.sample.descriptor.getString("sha256"), binding.getString("sha256"));
            assertEquals(1, binding.getLong("generation")); assertEquals(1, binding.getLong("binding_revision"));
            assertEquals(OfflineFallbackValues.scopeFingerprint(h.sample.material.getJSONObject("scope")), binding.getString("history_scope_fingerprint"));
            assertEquals("[\"fixture\",\"nhtsa-us-recalls\",\"synthetic-oem\"]", binding.getJSONArray("source_ids").toString());
            assertEquals(16, status.getJSONObject("capabilities").getInt("max_policies"));
        }
    }

    @Test public void missingBindingNeverBackfillsUntilExplicitManualRead() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty");
            // Simulate an older private QA profile that predates the encrypted journal.
            try (SQLiteConnection sql = h.sql(); SQLiteStatement deletion = sql.prepare("DELETE FROM fallback_state WHERE id=1")) { deletion.step(); }
            h.reopen(); JSONObject cold = h.store.fallbackStatus();
            assertEquals(0, cold.getJSONArray("package_bindings").length()); assertEquals(1, cold.getJSONArray("missing_package_bindings").length());
            h.refresh(); JSONObject own = json("binding_revision", 1, "slot_id", h.installed.getString("slot_id"), "generation", 1,
                "package_id", h.sample.descriptor.getString("id"), "sha256", h.sample.descriptor.getString("sha256"),
                "history_scope_fingerprint", OfflineFallbackValues.scopeFingerprint(h.sample.material.getJSONObject("scope")),
                "source_ids", new JSONArray().put("fixture").put("nhtsa-us-recalls").put("synthetic-oem"));
            fails("OFFLINE_FALLBACK_SCOPE_METADATA_MISSING", () -> h.preview("query_allow", queryScope("fixture"), own, null));
            assertEquals(0, h.store.fallbackStatus().getJSONArray("package_bindings").length());
            JSONObject read = OfflineFallbackWire.decode(h.store.read(manualRead(h)));
            assertEquals("local_snapshot", read.getString("data_state"));
            assertEquals(1, h.store.fallbackStatus().getJSONArray("package_bindings").length());
            assertEquals(0, h.store.fallbackStatus().getJSONArray("missing_package_bindings").length());
            h.preview("query_allow", queryScope("fixture"), h.binding(), null);
        }
    }

    @Test public void corruptBodyColdStatusPreviewAndSchedulingStayMetadataOnly() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); JSONObject binding = h.binding(); h.corruptOnlyOwnBody(); h.reopen();
            assertEquals("unknown", h.store.fallbackStatus().getJSONObject("authority").getString("state"));
            assertEquals(binding.toString(), h.binding().toString());
            JSONObject schedule = h.store.syncSchedulingStatus(); assertEquals(0, schedule.getJSONArray("release_checks").length());
            h.refresh(); JSONObject preview = h.preview("query_allow", queryScope("fixture"), binding, null);
            assertEquals(binding.toString(), preview.getJSONObject("proposed_policy").getJSONObject("binding").toString());
            fails("OFFLINE_CORRUPT", () -> h.store.read(manualRead(h)));
            // The same damaged body is still harmless to metadata after an explicit read failed.
            assertEquals(1, h.store.fallbackStatus().getJSONArray("package_bindings").length());
        }
    }

    @Test public void journalIsEncryptedAndApprovedAuthorityPinsPersist() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); JSONObject authority = h.refresh(); JSONObject saved = h.saveAsk();
            assertEquals("/health", h.server.takeRequest(2, TimeUnit.SECONDS).getPath());
            assertEquals("/v1/source-settings", h.server.takeRequest(2, TimeUnit.SECONDS).getPath());
            assertEquals("/v1/sources", h.server.takeRequest(2, TimeUnit.SECONDS).getPath()); assertEquals(3, h.server.getRequestCount());
            String raw = new String(h.sealedJournal(), StandardCharsets.ISO_8859_1);
            assertFalse(raw.contains(saved.getString("policy_id"))); assertFalse(raw.contains("device-fallback-policy@1"));
            JSONObject entry = h.journal().getJSONArray("policies").getJSONObject(0), approved = entry.getJSONObject("approval_authority");
            assertEquals(saved.getString("policy_id"), entry.getJSONObject("policy").getString("policy_id"));
            assertEquals(saved.getString("owner_scope_id"), approved.getString("owner_scope_id"));
            assertEquals(authority.getString("runtime_session_id"), approved.getString("runtime_session_id"));
            assertEquals(1, approved.getJSONArray("sources").length()); assertEquals(0, source(approved, "fixture").getLong("access_generation"));
            assertTrue(source(approved, "fixture").getBoolean("can_fetch"));
            h.reopen(); assertEquals(saved.getString("policy_id"), h.policies().getJSONObject(0).getString("policy_id"));
        }
    }

    @Test public void malformedScopesPinsKindsAndUnauthorizedAdvanceAreRejected() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject binding = h.binding(); h.corruptOnlyOwnBody();
            JSONObject stale = queryScope("fixture"); stale.getJSONArray("sources").getJSONObject(0).put("access_generation", 1);
            fails("OFFLINE_FALLBACK_INVALID", () -> h.preview("ask", stale, null, null));
            JSONObject duplicate = queryScope("fixture"); duplicate.getJSONArray("sources").put(copy(duplicate.getJSONArray("sources").getJSONObject(0)));
            fails("OFFLINE_FALLBACK_INVALID", () -> h.preview("ask", duplicate, null, null));
            JSONObject wrongKind = queryScope("fixture").put("query_kind", "vehicle_fitments");
            fails("OFFLINE_FALLBACK_INVALID", () -> h.preview("never", wrongKind, null, null));
            fails("OFFLINE_FALLBACK_INVALID", () -> h.preview("ask", queryScope("unregistered-fixture"), null, null));
            JSONObject expanded = h.request("query_allow", queryScope("fixture"), binding, null).put("allow_same_scope_sync_binding_advance", true);
            fails("OFFLINE_FALLBACK_SYNC_ADVANCE_SCOPE_UNAVAILABLE", () -> h.store.fallbackPolicyPreview(expanded));
            JSONObject replacement = copy(binding).put("sha256", "b".repeat(64));
            fails("OFFLINE_FALLBACK_SCOPE_METADATA_MISSING", () -> h.preview("query_allow", queryScope("fixture"), replacement, null));
            assertEquals(0, h.policies().length());
        }
    }

    @Test public void disabledRegisteredSourceKeepsAskNeverButCannotGrantAllow() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); JSONObject authority = h.refresh(false); assertFalse(source(authority, "fixture").getBoolean("can_fetch"));
            assertFalse(source(authority, "fixture").getBoolean("can_query"));
            JSONObject ask = h.save("ask", sourceScope(), null, null), never = h.save("never", queryScope("fixture"), null, null);
            assertEquals("enabled", ask.getString("state")); assertEquals("enabled", never.getString("state"));
            fails("OFFLINE_FALLBACK_INVALID", () -> h.preview("query_allow", queryScope("fixture"), h.binding(), null));
            assertEquals(2, h.policies().length());
        }
    }

    @Test public void explicitAcknowledgmentAndWrongFingerprintStayClosed() throws Exception {
        try (Harness h = new Harness()) {
            h.refresh(); JSONObject preview = h.preview("ask", queryScope("fixture"), null, null);
            JSONObject denied = applyRequest(preview).put("allow_continuous_history_fallback", false);
            fails("OFFLINE_PACKAGE_INVALID", () -> h.store.fallbackPolicyApply(denied)); assertEquals(0, h.policies().length());
            JSONObject saved = h.apply(preview); assertEquals("enabled", saved.getString("state"));
            JSONObject next = h.preview("never", queryScope("fixture"), null, null), wrong = applyRequest(next).put("expected_fingerprint", "b".repeat(64));
            fails("OFFLINE_FALLBACK_POLICY_STALE", () -> h.store.fallbackPolicyApply(wrong));
            fails("OFFLINE_FALLBACK_PREVIEW_USED", () -> h.apply(next)); assertEquals(1, h.policies().length());
            JSONObject mismatched = h.request("ask", queryScope("fixture"), null, null);
            mismatched.put("expected_owner_epoch", mismatched.getLong("expected_owner_epoch") + 1);
            fails("OFFLINE_FALLBACK_MISMATCH", () -> h.store.fallbackPolicyPreview(mismatched));
        }
    }

    @Test public void previewExpiresAtEitherWallOrMonotonicDeadline() throws Exception {
        for (boolean advanceMonotonic : new boolean[]{false, true}) try (Harness h = new Harness()) {
            h.refresh(); JSONObject preview = h.preview("ask", queryScope("fixture"), null, null);
            if (advanceMonotonic) h.clock.mono += 300000; else h.clock.wall += 300000;
            fails("OFFLINE_FALLBACK_PREVIEW_EXPIRED", () -> h.apply(preview));
            fails("OFFLINE_FALLBACK_PREVIEW_USED", () -> h.apply(preview)); assertEquals(0, h.policies().length());
        }
    }

    @Test public void clockRollbackPausesSavedPolicyAndExpiresPendingPreview() throws Exception {
        try (Harness h = new Harness()) {
            h.refresh(); JSONObject saved = h.saveAsk(), preview = h.preview("never", queryScope("fixture"), null, null);
            long originalWall = h.clock.wall; h.clock.wall--;
            fails("OFFLINE_FALLBACK_PREVIEW_EXPIRED", () -> h.apply(preview));
            JSONObject paused = policy(h.policies(), saved.getString("policy_id")); assertNotNull(paused);
            assertEquals("paused", paused.getString("state")); assertEquals("OFFLINE_FALLBACK_CLOCK_ROLLBACK", paused.getString("reason"));
            h.clock.wall = originalWall + 1;
            assertEquals("paused", policy(h.policies(), saved.getString("policy_id")).getString("state"));
        }
    }

    @Test public void concurrentSameIdReapprovalHasExactlyOneCasWinner() throws Exception {
        try (Harness h = new Harness()) {
            h.refresh(); JSONObject saved = h.saveAsk(), a = h.preview("ask", queryScope("fixture"), null, saved), b = h.preview("never", queryScope("fixture"), null, saved);
            ExecutorService workers = Executors.newFixedThreadPool(2); CountDownLatch start = new CountDownLatch(1);
            try {
                List<Future<String>> results = new ArrayList<>();
                for (JSONObject preview : new JSONObject[]{a, b}) results.add(workers.submit(() -> {
                    assertTrue(start.await(3, TimeUnit.SECONDS));
                    try { return h.apply(preview).getString("policy_id"); }
                    catch (NativeFailure failure) { return failure.code; }
                }));
                start.countDown(); int winners = 0, stale = 0;
                for (Future<String> result : results) {
                    String value = result.get(10, TimeUnit.SECONDS);
                    if (value.equals(saved.getString("policy_id"))) winners++;
                    else if (value.equals("OFFLINE_FALLBACK_POLICY_STALE")) stale++;
                    else fail("Unexpected concurrent outcome " + value);
                }
                assertEquals(1, winners); assertEquals(1, stale); assertEquals(1, h.policies().length());
                assertEquals(2, h.policies().getJSONObject(0).getLong("policy_revision"));
            } finally { workers.shutdownNow(); assertTrue(workers.awaitTermination(3, TimeUnit.SECONDS)); }
        }
    }

    @Test public void pauseReapprovalAndRevokeKeepSameIdentityAndRevision() throws Exception {
        try (Harness h = new Harness()) {
            h.refresh(); JSONObject initial = h.saveAsk(), paused = h.change(initial, false);
            assertEquals("paused", paused.getString("state")); assertEquals(2, paused.getLong("policy_revision"));
            fails("OFFLINE_FALLBACK_POLICY_STALE", () -> h.change(initial, true));
            JSONObject resumed = h.save("ask", queryScope("fixture"), null, paused);
            assertEquals(initial.getString("policy_id"), resumed.getString("policy_id")); assertEquals(3, resumed.getLong("policy_revision"));
            JSONObject revoked = h.change(resumed, true); assertEquals("revoked", revoked.getString("state")); assertEquals(4, revoked.getLong("policy_revision"));
            JSONObject reapproved = h.save("never", queryScope("fixture"), null, revoked);
            assertEquals(initial.getString("policy_id"), reapproved.getString("policy_id")); assertEquals(5, reapproved.getLong("policy_revision"));
            assertEquals("enabled", reapproved.getString("state")); assertEquals(1, h.policies().length());
        }
    }

    @Test public void pausedRecordsCountTowardSixteenUntilRevocationFreesCapacity() throws Exception {
        try (Harness h = new Harness()) {
            h.refresh(); List<JSONObject> saved = new ArrayList<>(); for (int at = 0; at < 16; at++) saved.add(h.saveAsk());
            JSONObject paused = h.change(saved.get(0), false); assertEquals(16, h.policies().length());
            JSONObject extra = h.preview("ask", queryScope("fixture"), null, null);
            fails("OFFLINE_FALLBACK_POLICY_CAPACITY", () -> h.apply(extra)); assertEquals(16, h.policies().length());
            JSONObject revoked = h.change(paused, true); assertEquals("revoked", revoked.getString("state"));
            JSONObject added = h.saveAsk(); assertEquals("enabled", added.getString("state"));
            int nonrevoked = 0; JSONArray all = h.policies();
            for (int at = 0; at < all.length(); at++) if (!all.getJSONObject(at).getString("state").equals("revoked")) nonrevoked++;
            assertEquals(16, nonrevoked); assertEquals(17, all.length());
        }
    }

    @Test public void retentionPrunesOnlyOldRevokedAndPrunedIdentityCannotBeRecreated() throws Exception {
        try (Harness h = new Harness()) {
            h.refresh(); JSONObject protectedPolicy = h.change(h.saveAsk(), false), firstRevoked = null, latestRevoked = null;
            for (int at = 0; at < 65; at++) {
                h.clock.advance(1); JSONObject created = h.saveAsk(); h.clock.advance(1); latestRevoked = h.change(created, true);
                if (firstRevoked == null) firstRevoked = latestRevoked;
            }
            JSONArray retained = h.policies(); assertEquals(64, retained.length());
            assertNotNull(policy(retained, protectedPolicy.getString("policy_id")));
            assertNull(policy(retained, firstRevoked.getString("policy_id"))); assertNotNull(policy(retained, latestRevoked.getString("policy_id")));
            final JSONObject pruned = firstRevoked;
            fails("OFFLINE_FALLBACK_POLICY_STALE", () -> h.preview("ask", queryScope("fixture"), null, pruned));
            JSONObject reapproved = h.save("ask", queryScope("fixture"), null, latestRevoked);
            assertEquals(latestRevoked.getString("policy_id"), reapproved.getString("policy_id"));
            assertEquals(latestRevoked.getLong("policy_revision") + 1, reapproved.getLong("policy_revision"));
            assertEquals("paused", policy(h.policies(), protectedPolicy.getString("policy_id")).getString("state"));
        }
    }

    @Test public void ownerResetRevokesOldEpochAtomicallyAndReleasesCapacity() throws Exception {
        try (Harness h = new Harness()) {
            h.refresh(); List<JSONObject> old = new ArrayList<>(); for (int at = 0; at < 16; at++) old.add(h.saveAsk());
            assertEquals(2, h.store.resetOwnerEpoch()); assertEquals(0, h.policies().length());
            JSONArray journal = h.journal().getJSONArray("policies"); assertEquals(16, journal.length());
            for (int at = 0; at < journal.length(); at++) {
                JSONObject revoked = journal.getJSONObject(at).getJSONObject("policy");
                assertEquals(1, revoked.getLong("owner_epoch")); assertEquals("revoked", revoked.getString("state"));
                assertEquals("OFFLINE_FALLBACK_OWNER_CHANGED", revoked.getString("reason"));
            }
            h.refresh(); fails("OFFLINE_FALLBACK_POLICY_STALE", () -> h.preview("ask", queryScope("fixture"), null, old.get(0)));
            for (int at = 0; at < 16; at++) assertEquals(2, h.saveAsk().getLong("owner_epoch"));
            assertEquals(16, h.policies().length());
        }
        // Fault injection is confined to another fresh QA journal, proving epoch and policies commit together.
        try (Harness h = new Harness()) {
            h.refresh(); JSONObject saved = h.saveAsk();
            try (SQLiteConnection sql = h.sql(); SQLiteStatement trigger = sql.prepare("CREATE TRIGGER qa_reject_policy_reset BEFORE UPDATE ON fallback_state BEGIN SELECT RAISE(ABORT,'qa_atomic_reset'); END")) { trigger.step(); }
            fails("OFFLINE_STORE_UNAVAILABLE", () -> h.store.resetOwnerEpoch());
            try (SQLiteConnection sql = h.sql(); SQLiteStatement drop = sql.prepare("DROP TRIGGER qa_reject_policy_reset")) { drop.step(); }
            assertEquals(1, h.store.fallbackStatus().getLong("owner_epoch"));
            assertEquals("enabled", policy(h.policies(), saved.getString("policy_id")).getString("state"));
        }
    }

    @Test public void coldRestartPausesSessionPreferencesButPersistentNeverBlocksLegacyFalsePin() throws Exception {
        try (Harness h = new Harness()) {
            h.install("legacy"); h.refresh();
            JSONObject sourceNever = h.save("never", sourceScope(), null, null), queryNever = h.save("never", queryScope("fixture"), null, null);
            JSONObject sessionAsk = h.save("ask", sessionScope(), null, null), sessionNever = h.save("never", sessionScope(), null, null);
            h.corruptOnlyOwnBody(); h.reopen(); JSONObject cold = h.store.fallbackStatus(); JSONArray policies = cold.getJSONArray("policies");
            assertEquals("unknown", cold.getJSONObject("authority").getString("state"));
            for (JSONObject session : new JSONObject[]{sessionAsk, sessionNever}) {
                JSONObject paused = policy(policies, session.getString("policy_id")); assertEquals("paused", paused.getString("state"));
                assertEquals("OFFLINE_FALLBACK_SESSION_CHANGED", paused.getString("reason"));
            }
            assertEquals("enabled", policy(policies, sourceNever.getString("policy_id")).getString("state"));
            assertEquals("enabled", policy(policies, queryNever.getString("policy_id")).getString("state"));
            JSONObject forgedPin = h.legacyRequest(999); fails("OFFLINE_FALLBACK_NEVER", () -> h.store.decideFallback(forgedPin));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.decideFallback(forgedPin));
            JSONObject revoked = h.change(policy(h.policies(), sourceNever.getString("policy_id")), true);
            assertEquals("revoked", revoked.getString("state"));
            fails("OFFLINE_FALLBACK_NEVER", () -> h.store.decideFallback(h.legacyRequest(999)));
        }
    }

    @Test public void newNeverBlocksOldLegacyGrantAfterDurableConsumptionAndBeforeBodyRead() throws Exception {
        try (Harness h = new Harness()) {
            h.install("legacy"); h.refresh(); JSONObject request = h.legacyRequest(0), grant = h.store.decideFallback(request);
            h.save("never", queryScope("fixture"), null, null); h.corruptOnlyOwnBody();
            JSONObject consume = json("grant_id", grant.getString("id"), "intent", request.getJSONObject("intent"));
            fails("OFFLINE_FALLBACK_NEVER", () -> h.store.consumeFallback(consume));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.consumeFallback(consume));
            try (SQLiteConnection sql = h.sql(); SQLiteStatement rows = sql.prepare("SELECT id,value FROM fallback_audit")) {
                boolean found = false; OfflineCipher cipher = new OfflineCipher(h.context, h.namespace);
                while (rows.step()) if (rows.getText(0).equals(grant.getString("id"))) {
                    byte[] clear = cipher.open(rows.getBlob(1), "fallback-audit@1:" + rows.getText(0));
                    try { assertEquals("consumed", OfflinePackageValidator.response(clear).getString("state")); found = true; }
                    finally { Arrays.fill(clear, (byte) 0); }
                }
                assertTrue("Terminal audit exists despite a policy rejection before corrupt body access", found);
            }
        }
    }
}
