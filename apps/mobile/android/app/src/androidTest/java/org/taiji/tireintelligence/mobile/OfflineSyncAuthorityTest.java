package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.core.app.ActivityScenario;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okhttp3.mockwebserver.SocketPolicy;
import okio.Buffer;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Synthetic loopback only. Exercises real native lifecycle without normal credentials. */
@RunWith(AndroidJUnit4.class)
public final class OfflineSyncAuthorityTest {
    private interface Checked { void run() throws Exception; }
    private static void fails(String code, Checked action) throws Exception {
        try { action.run(); fail("Expected " + code); } catch (NativeFailure failure) { assertEquals(code, failure.code); }
    }
    private static final class MemoryStore implements SessionState.Store {
        String value;
        MemoryStore(String value) { this.value = value; }
        public String load() { return value; }
        public void save(String replacement) { value = replacement; }
        public void delete() { value = null; }
    }
    private static NativeHttpBridge bridge(MockWebServer server, MemoryStore store) throws Exception {
        server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
        return new NativeHttpBridge("http://127.0.0.1:" + server.getPort(), store);
    }
    private static NativePolicy.Request prepare() {
        return new NativePolicy.Request(UUID.randomUUID().toString(), "/v1/offline-pack-updates:prepare", "POST",
            Collections.singletonMap("content-type", "application/json"), "{}".getBytes(StandardCharsets.UTF_8));
    }
    private static MockResponse json(String owner) { return new MockResponse().setBody("{}").addHeader("Content-Type", "application/json").addHeader("X-Tire-Offline-Owner-Scope", owner); }
    private static String owner() { return "a".repeat(64); }

    @Test public void missingCookieAndChangedGenerationNeverBootstrapOrReplay() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            MemoryStore store = new MemoryStore(null); NativeHttpBridge bridge = bridge(server, store);
            try {
                fails("SESSION_COOKIE_MISSING", bridge::freezeSession);
                assertEquals(0, server.getRequestCount());
                String initial = UUID.randomUUID().toString(); bridge.session.persist(initial);
                NativeHttpBridge.SessionFence fence = bridge.freezeSession();
                String binding = bridge.sessionBinding(fence);
                bridge.reset(); bridge.session.persist(initial);
                assertEquals(binding, bridge.sessionBinding(bridge.freezeSession()));
                fails("SESSION_CHANGED", () -> bridge.syncRequest(prepare(), fence, owner()));
                assertEquals(0, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }

    @Test public void responseCookieChangeKillsWholeRunAndCannotContinueWithNewOwner() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()));
            try {
                NativeHttpBridge.SessionFence fence = bridge.freezeSession();
                server.enqueue(json(owner()).addHeader("Set-Cookie", "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict"));
                fails("SESSION_CHANGED", () -> bridge.syncRequest(prepare(), fence, owner()));
                fails("SESSION_CHANGED", () -> bridge.syncRequest(prepare(), fence, owner()));
                assertEquals(1, server.getRequestCount());
                assertEquals("/v1/offline-pack-updates:prepare", server.takeRequest(2, TimeUnit.SECONDS).getPath());
            } finally { bridge.close(); }
        }
    }

    @Test public void allHistoryStagesUseSamePrivateCookieAndStrictOwnerHeaders() throws Exception {
        byte[] raw = OfflinePackageValidatorTest.asset("valid-envelope.json");
        JSONObject descriptor = OfflinePackageValidator.parse(OfflinePackageValidatorTest.asset("valid-descriptor.json"));
        String scope = descriptor.getString("owner_scope_id");
        try (MockWebServer server = new MockWebServer()) {
            String cookie = UUID.randomUUID().toString(); NativeHttpBridge bridge = bridge(server, new MemoryStore(cookie));
            try {
                NativeHttpBridge.SessionFence fence = bridge.freezeSession();
                server.enqueue(json(scope));
                JSObject response = bridge.syncRequest(prepare(), fence, scope);
                assertFalse(response.toString().contains(cookie)); assertFalse(response.getJSObject("headers").has("set-cookie"));
                server.enqueue(json(scope));
                NativePolicy.Request confirm = new NativePolicy.Request(UUID.randomUUID().toString(), "/v1/offline-packs", "POST",
                    Collections.singletonMap("idempotency-key", UUID.randomUUID().toString()), "{}".getBytes(StandardCharsets.UTF_8));
                bridge.syncRequest(confirm, fence, scope);
                server.enqueue(json(scope));
                NativePolicy.Request described = new NativePolicy.Request(UUID.randomUUID().toString(), "/v1/offline-packs/" + descriptor.getString("id") + "?mode=history", "GET", Collections.emptyMap(), new byte[0]);
                bridge.syncRequest(described, fence, scope);
                server.enqueue(new MockResponse().setBody(new Buffer().write(raw)).addHeader("Content-Type", "application/json")
                    .addHeader("X-Tire-Offline-Owner-Scope", scope).addHeader("X-Content-SHA256", descriptor.getString("sha256"))
                    .addHeader("ETag", "\"" + descriptor.getString("sha256") + "\"")
                    .addHeader("Cache-Control", "no-store").addHeader("X-Content-Type-Options", "nosniff"));
                assertArrayEquals(raw, bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), raw.length, fence, scope));
                for (int i = 0; i < 4; i++) {
                    RecordedRequest sent = server.takeRequest(2, TimeUnit.SECONDS); assertNotNull(sent);
                    assertNotEquals("/health", sent.getPath()); assertEquals("1", sent.getHeader("X-Tire-Offline-Sync"));
                    assertEquals(scope, sent.getHeader("X-Tire-Offline-Expected-Owner"));
                    assertEquals("tire_local_session=" + cookie, sent.getHeader("Cookie"));
                }
                server.enqueue(json("b".repeat(64)));
                fails("OFFLINE_SYNC_OWNER_MISMATCH", () -> bridge.syncRequest(prepare(), fence, scope));
                NativePolicy.Request forbidden = new NativePolicy.Request(UUID.randomUUID().toString(), "/v1/query", "POST", Collections.emptyMap(), new byte[0]);
                fails("OFFLINE_INVALID_ARGUMENT", () -> bridge.syncRequest(forbidden, fence, scope));
                assertEquals(5, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }

    @Test public void resetCancelsPendingRunAndPreventsLateCookieSave() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            MemoryStore store = new MemoryStore(UUID.randomUUID().toString()); NativeHttpBridge bridge = bridge(server, store);
            try {
                NativeHttpBridge.SessionFence fence = bridge.freezeSession();
                server.enqueue(new MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE));
                CompletableFuture<String> result = CompletableFuture.supplyAsync(() -> {
                    try { bridge.syncRequest(prepare(), fence, owner()); return "unexpected-success"; }
                    catch (NativeFailure failure) { return failure.code; }
                });
                assertNotNull(server.takeRequest(3, TimeUnit.SECONDS)); bridge.registry.beginReset();
                assertEquals("REQUEST_CANCELLED", result.get(3, TimeUnit.SECONDS)); bridge.finishReset(); assertNull(store.value);
                fails("SESSION_CHANGED", () -> bridge.checkSession(fence));
            } finally { bridge.close(); }
        }
    }

    @Test public void explicitConditionsAreAndUnknownFailsAndExternalPowerIsDistinct() throws Exception {
        JSONObject both = new JSONObject("{\"network\":\"wifi\",\"power\":\"battery_charging\"}");
        assertNull(OfflineSyncConditions.blocked(both, new OfflineSyncConditions.Sample(true, true, true)));
        assertEquals("OFFLINE_SYNC_CONDITION_UNMET", OfflineSyncConditions.blocked(both, new OfflineSyncConditions.Sample(false, true, true)));
        assertEquals("OFFLINE_SYNC_CONDITION_UNKNOWN", OfflineSyncConditions.blocked(both, new OfflineSyncConditions.Sample(null, true, true)));
        assertEquals("OFFLINE_SYNC_CONDITION_UNMET", OfflineSyncConditions.blocked(both, new OfflineSyncConditions.Sample(true, true, false)));
        JSONObject external = new JSONObject("{\"network\":\"wifi\",\"power\":\"external_power\"}");
        assertNull(OfflineSyncConditions.blocked(external, new OfflineSyncConditions.Sample(true, true, false)));
        JSONObject any = new JSONObject("{\"network\":\"any\",\"power\":\"any\"}");
        assertNull(OfflineSyncConditions.blocked(any, new OfflineSyncConditions.Sample(null, null, null)));
        fails("OFFLINE_INVALID_ARGUMENT", () -> OfflineSyncConditions.validate(new JSONObject("{\"network\":\"unmetered\",\"power\":\"any\"}")));
        fails("OFFLINE_INVALID_ARGUMENT", () -> OfflineSyncConditions.validate(new JSONObject("{\"network\":\"any\",\"power\":\"full\"}")));
    }

    @Test public void applicationRuntimeSurvivesDocumentAndReusesHttpAndStore() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        OfflineRuntime first = OfflineRuntime.get(context); OfflineRuntime second = OfflineRuntime.get(context.getApplicationContext());
        assertSame(first, second); assertSame(first.http(), second.http()); assertSame(first.store(), second.store());
        long before = first.documentGeneration.get(); first.documentEnded();
        assertEquals(before + 1, second.documentGeneration.get());
        assertFalse(first.offlineTasks.isShutdown()); assertFalse(first.syncTasks.isShutdown());
        OfflineSyncConditions.Sample sample = OfflineSyncConditions.sample(context);
        assertNotNull(sample); // Actual sensor sample; no particular emulator transport is assumed.
    }

    @Test public void actualActivityTeardownDoesNotCloseApplicationAuthority() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        OfflineRuntime runtime = OfflineRuntime.get(context);
        NativeHttpBridge authority = runtime.http(); OfflinePackStore store = runtime.store();
        try (ActivityScenario<MainActivity> first = ActivityScenario.launch(MainActivity.class)) {
            first.onActivity(activity -> assertSame(runtime, OfflineRuntime.get(activity)));
        }
        assertFalse(runtime.offlineTasks.isShutdown()); assertFalse(runtime.syncTasks.isShutdown());
        assertSame(authority, runtime.http()); assertSame(store, runtime.store());
        try (ActivityScenario<MainActivity> second = ActivityScenario.launch(MainActivity.class)) {
            second.onActivity(activity -> assertSame(runtime, OfflineRuntime.get(activity)));
        }
        assertFalse(runtime.offlineTasks.isShutdown()); assertSame(store, runtime.store());
    }
}
