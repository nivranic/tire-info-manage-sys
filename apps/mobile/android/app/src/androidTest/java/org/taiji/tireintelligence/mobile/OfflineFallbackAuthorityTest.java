package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import androidx.sqlite.SQLiteConnection;
import androidx.sqlite.SQLiteStatement;
import androidx.sqlite.driver.bundled.BundledSQLiteDriver;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Fixed native HTTP against loopback fixtures, including real catalog shape and final store races. */
@RunWith(AndroidJUnit4.class)
public final class OfflineFallbackAuthorityTest {
    private static final String OWNER = "a".repeat(64), BINDING = "b".repeat(64);
    private interface Checked { void run() throws Exception; }
    private static void fails(String code, Checked action) throws Exception {
        try { action.run(); fail("Expected " + code); }
        catch (NativeFailure failure) { assertEquals(code, failure.code); }
    }
    private static byte[] asset(String path) throws Exception {
        try (InputStream stream = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(path)) { return stream.readAllBytes(); }
    }
    private static JSONObject fixture(String name) throws Exception {
        return OfflinePackageValidator.response(asset("source-authority49/" + name + ".json"));
    }
    private static OfflinePackStore store(String namespace) throws Exception {
        return new OfflinePackStore(InstrumentationRegistry.getInstrumentation().getTargetContext(), namespace);
    }
    private static String namespace() { return "qa-r49-authority-" + UUID.randomUUID(); }
    private static final class MemorySession implements SessionState.Store {
        String cookie;
        public String load() { return cookie; }
        public void save(String replacement) { cookie = replacement; }
        public void delete() { cookie = null; }
    }
    private static NativeHttpBridge bridge(MockWebServer server) throws Exception {
        server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
        server.enqueue(new MockResponse().setBody("{}").addHeader("Set-Cookie", "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict"));
        return new NativeHttpBridge("http://127.0.0.1:" + server.getPort(), new MemorySession());
    }
    private static MockResponse response(JSONObject body) { return new MockResponse().setBody(body.toString()).addHeader("Content-Type", "application/json"); }
    private static void metadata(MockWebServer server) throws Exception {
        server.enqueue(response(fixture("source-settings")).addHeader("X-Tire-Offline-Owner-Scope", OWNER));
        server.enqueue(response(fixture("sources")));
    }
    private static JSONObject source(JSONObject authority, String id) throws Exception {
        JSONArray all = authority.getJSONArray("sources");
        for (int at = 0; at < all.length(); at++) if (id.equals(all.getJSONObject(at).getString("source_id"))) return all.getJSONObject(at);
        throw new AssertionError("Registered fixture source not found");
    }
    private static JSONObject observe(OfflinePackStore store, OfflineFallbackAuthority.Capture capture, JSONObject settings) throws Exception {
        return store.observeFallbackAuthority(capture, settings, fixture("sources"), OWNER, BINDING, () -> true);
    }

    @Test public void fixedTwoGetsAcceptActualElevenCatalogAndZeroPinWithoutPackageAuthority() throws Exception {
        try (OfflinePackStore store = store(namespace()); MockWebServer server = new MockWebServer()) {
            NativeHttpBridge http = bridge(server);
            try {
                assertEquals("unknown", store.fallbackAuthoritySnapshot().getString("state"));
                assertEquals(0, store.list().getJSONArray("items").length()); metadata(server);
                JSONObject authority = OfflineFallbackAuthorityCoordinator.refresh(store, http, () -> true);
                assertEquals("last_observed", authority.getString("state")); assertEquals(11, authority.getJSONArray("sources").length());
                JSONObject vehicle = source(authority, "xiaomi-cn-vehicles");
                assertEquals(0, vehicle.getLong("access_generation")); assertTrue(vehicle.getBoolean("can_query"));
                assertEquals("vehicle_fitments", vehicle.getJSONArray("query_kinds").getString(0));
                assertFalse(source(authority, "eprel").getBoolean("can_query"));
                assertEquals("/health", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                assertEquals("/v1/source-settings", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                assertEquals("/v1/sources", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                assertEquals(3, server.getRequestCount()); assertEquals(0, store.list().getJSONArray("items").length());
            } finally { http.close(); }
        }
    }

    @Test public void unchangedRefreshKeepsRevisionWhileActualPermissionChangeAdvancesIt() throws Exception {
        try (OfflinePackStore store = store(namespace())) {
            JSONObject first = observe(store, store.captureFallbackAuthority(), fixture("source-settings"));
            JSONObject same = observe(store, store.captureFallbackAuthority(), fixture("source-settings"));
            assertEquals(first.getLong("authority_revision"), same.getLong("authority_revision"));
            JSONObject settings = fixture("source-settings"); JSONArray items = settings.getJSONArray("items");
            for (int at = 0; at < items.length(); at++) if (items.getJSONObject(at).getString("source_id").equals("xiaomi-cn-vehicles"))
                items.getJSONObject(at).put("can_fetch", false).put("effective_status", "paused");
            JSONObject changed = observe(store, store.captureFallbackAuthority(), settings);
            assertEquals(first.getLong("authority_revision") + 1, changed.getLong("authority_revision"));
            assertFalse(source(changed, "xiaomi-cn-vehicles").getBoolean("can_fetch"));
            assertFalse(source(changed, "xiaomi-cn-vehicles").getBoolean("can_query"));
        }
    }

    @Test public void staleOwnerAndConcurrentCaptureCannotPublishIntoNewAuthority() throws Exception {
        try (OfflinePackStore store = store(namespace())) {
            OfflineFallbackAuthority.Capture first = store.captureFallbackAuthority(), parallel = store.captureFallbackAuthority();
            observe(store, first, fixture("source-settings"));
            fails("OFFLINE_FALLBACK_AUTHORITY_INVALID", () -> observe(store, parallel, fixture("source-settings")));
            OfflineFallbackAuthority.Capture old = store.captureFallbackAuthority(); store.resetOwnerEpoch();
            fails("OFFLINE_FALLBACK_AUTHORITY_INVALID", () -> observe(store, old, fixture("source-settings")));
            assertEquals("unknown", store.fallbackAuthoritySnapshot().getString("state"));
        }
    }

    @Test public void cookieChangeOnSecondGetCannotCombineTwoSessions() throws Exception {
        try (OfflinePackStore store = store(namespace()); MockWebServer server = new MockWebServer()) {
            NativeHttpBridge http = bridge(server);
            try {
                server.enqueue(response(fixture("source-settings")).addHeader("X-Tire-Offline-Owner-Scope", OWNER));
                server.enqueue(response(fixture("sources")).addHeader("Set-Cookie", "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict"));
                fails("SESSION_CHANGED", () -> OfflineFallbackAuthorityCoordinator.refresh(store, http, () -> true));
                assertEquals("unknown", store.fallbackAuthoritySnapshot().getString("state")); assertEquals(3, server.getRequestCount());
            } finally { http.close(); }
        }
    }

    @Test public void ownerResetDuringSourcesAwaitRejectsFinalStoreCas() throws Exception {
        try (OfflinePackStore store = store(namespace()); MockWebServer server = new MockWebServer()) {
            NativeHttpBridge http = bridge(server);
            try {
                server.enqueue(response(fixture("source-settings")).addHeader("X-Tire-Offline-Owner-Scope", OWNER));
                server.enqueue(response(fixture("sources")).setBodyDelay(700, TimeUnit.MILLISECONDS));
                CompletableFuture<String> result = CompletableFuture.supplyAsync(() -> {
                    try { OfflineFallbackAuthorityCoordinator.refresh(store, http, () -> true); return "unexpected_published"; }
                    catch (NativeFailure failure) { return failure.code; }
                    catch (Exception failure) { return failure.getClass().getSimpleName(); }
                });
                assertEquals("/health", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                assertEquals("/v1/source-settings", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                assertEquals("/v1/sources", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                store.resetOwnerEpoch();
                assertEquals("OFFLINE_FALLBACK_AUTHORITY_INVALID", result.get(3, TimeUnit.SECONDS));
                assertEquals("unknown", store.fallbackAuthoritySnapshot().getString("state"));
            } finally { http.close(); }
        }
    }

    @Test public void duplicateConflictAndOversizedCatalogFailClosedWithoutTruncation() throws Exception {
        try (OfflinePackStore store = store(namespace())) {
            JSONObject duplicate = fixture("source-settings"); duplicate.getJSONArray("items").put(duplicate.getJSONArray("items").getJSONObject(0));
            fails("OFFLINE_FALLBACK_AUTHORITY_INVALID", () -> observe(store, store.captureFallbackAuthority(), duplicate));
            JSONObject sources = fixture("sources"); sources.getJSONArray("sources").getJSONObject(0).put("target_kind", "vehicle");
            fails("OFFLINE_FALLBACK_AUTHORITY_INVALID", () -> store.observeFallbackAuthority(store.captureFallbackAuthority(), fixture("source-settings"), sources, OWNER, BINDING, () -> true));
            JSONObject oversized = fixture("source-settings");
            while (oversized.getJSONArray("items").length() <= 200) oversized.getJSONArray("items").put(oversized.getJSONArray("items").getJSONObject(0));
            fails("OFFLINE_PACKAGE_INVALID", () -> observe(store, store.captureFallbackAuthority(), oversized));
            assertEquals("unknown", store.fallbackAuthoritySnapshot().getString("state"));
        }
    }

    @Test public void failedRefreshPreservesLastObservedAndOnlyFixedMetadataPathsExist() throws Exception {
        try (OfflinePackStore store = store(namespace()); MockWebServer server = new MockWebServer()) {
            NativeHttpBridge http = bridge(server);
            try {
                metadata(server); JSONObject original = OfflineFallbackAuthorityCoordinator.refresh(store, http, () -> true);
                server.enqueue(new MockResponse().setResponseCode(403).setBody("{}"));
                fails("OFFLINE_FALLBACK_AUTHORITY_UNAVAILABLE", () -> OfflineFallbackAuthorityCoordinator.refresh(store, http, () -> true));
                assertEquals(original.toString(), store.fallbackAuthoritySnapshot().toString());
                fails("OFFLINE_INVALID_ARGUMENT", () -> http.fallbackMetadata("/v1/query/fixture", http.freezeSession()));
                fails("OFFLINE_INVALID_ARGUMENT", () -> http.fallbackMetadata(null, http.freezeSession()));
                assertEquals(4, server.getRequestCount());
            } finally { http.close(); }
        }
    }

    @Test public void cancellationPublishesNothingAndProcessRestartStartsUnknown() throws Exception {
        String namespace = namespace();
        try (OfflinePackStore store = store(namespace)) {
            fails("OFFLINE_OPERATION_CANCELLED", () -> store.observeFallbackAuthority(store.captureFallbackAuthority(), fixture("source-settings"), fixture("sources"), OWNER, BINDING, () -> false));
            assertEquals("unknown", store.fallbackAuthoritySnapshot().getString("state"));
            observe(store, store.captureFallbackAuthority(), fixture("source-settings"));
        }
        try (OfflinePackStore reloaded = store(namespace)) { assertEquals("unknown", reloaded.fallbackAuthoritySnapshot().getString("state")); }
    }

    @Test public void legacyGrantForV2PackageIsDurablyConsumedBeforeZeroBodyUnsupported() throws Exception {
        String namespace = namespace(); byte[] raw = asset("offline-producer49/nonempty-pack.json");
        JSONObject descriptor = OfflinePackageValidator.response(asset("offline-producer49/nonempty-descriptor.json"));
        try (OfflinePackStore store = store(namespace)) {
            JSONObject install = new JSONObject().put("package_id", descriptor.getString("id")).put("expected_sha256", descriptor.getString("sha256"))
                .put("expected_byte_count", raw.length).put("approved_plan_fingerprint", descriptor.getString("plan_fingerprint"))
                .put("slot_id", UUID.randomUUID().toString()).put("expected_generation", 0).put("allow_device_storage", true);
            JSONObject slot = store.install(install, descriptor, raw), status = store.status();
            JSONObject intent = new JSONObject().put("schema", "device-fallback-intent@1").put("attempt_id", UUID.randomUUID().toString())
                .put("query_fingerprint", "c".repeat(64)).put("source_id", "fixture").put("source_access_generation", 0)
                .put("query", new JSONObject().put("model", "Fixture Tire").put("size", JSONObject.NULL)).put("filters", new JSONArray())
                .put("failure", new JSONObject().put("scope", "api_transport").put("reason", "api_timeout").put("query_id", JSONObject.NULL));
            JSONObject request = new JSONObject().put("intent", intent).put("decision", "allow").put("slot_id", slot.getString("slot_id"))
                .put("expected_generation", slot.getLong("generation")).put("expected_sha256", slot.getString("sha256"))
                .put("expected_profile_id", status.getString("profile_id")).put("expected_owner_epoch", status.getLong("owner_epoch"));
            java.lang.reflect.Field field = OfflinePackStore.class.getDeclaredField("directory"); field.setAccessible(true);
            File directory = (File) field.get(store), blob = new File(directory, "blobs").listFiles()[0];
            byte[] sealed = Files.readAllBytes(blob.toPath()); sealed[sealed.length - 1] ^= 1; Files.write(blob.toPath(), sealed);
            JSONObject receipt = store.decideFallback(request), consume = new JSONObject().put("grant_id", receipt.getString("id")).put("intent", intent);
            // A release check/body decrypt would see the bad ciphertext and fail CORRUPT instead.
            fails("OFFLINE_FALLBACK_UNSUPPORTED", () -> store.consumeFallback(consume));
            fails("OFFLINE_FALLBACK_USED", () -> store.consumeFallback(consume));
            try (SQLiteConnection sql = new BundledSQLiteDriver().open(new File(directory, "catalog.sqlite").getAbsolutePath());
                 SQLiteStatement rows = sql.prepare("SELECT id,value FROM fallback_audit")) {
                boolean found = false; OfflineCipher cipher = new OfflineCipher(InstrumentationRegistry.getInstrumentation().getTargetContext(), namespace);
                while (rows.step()) if (rows.getText(0).equals(receipt.getString("id"))) {
                    JSONObject durable = OfflinePackageValidator.parse(cipher.open(rows.getBlob(1), "fallback-audit@1:" + rows.getText(0)));
                    assertEquals("consumed", durable.getString("state")); found = true;
                }
                assertTrue(found);
            }
        }
    }
}
