package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.getcapacitor.JSObject;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import okhttp3.Headers;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Only synthetic metadata, memory session stores and loopback MockWebServer; no normal state. */
@RunWith(AndroidJUnit4.class)
public final class NativeQueryDenialsTest {
    private interface Checked { void run() throws Exception; }
    private static void fails(String code, Checked action) throws Exception {
        try { action.run(); fail("Expected " + code); }
        catch (NativeFailure failure) { assertEquals(code, failure.code); }
    }
    private static String id(int value) { return String.format(Locale.ROOT, "00000000-0000-4000-8000-%012x", value); }
    private static byte[] utf8(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private static NativePolicy.Request request(String path, String method, String body) {
        return new NativePolicy.Request(UUID.randomUUID().toString(), path, method,
            Collections.singletonMap("content-type", "application/json"), utf8(body));
    }
    private static NativePolicy.Request denial(String queryId) throws Exception {
        return request("/v1/fallback-consents", "POST", new JSONObject().put("query_id", queryId).put("decision", "deny").put("scope", "once").toString());
    }
    private static byte[] accepted() throws Exception {
        return utf8(new JSONObject().put("id", id(49)).put("decision", "deny").put("scope", "once").put("expires_at", "2026-10-01T01:00:00Z").toString());
    }
    private static JSONObject intent(String schema, String queryId) throws Exception {
        return new JSONObject().put("schema", schema).put("attempt_id", UUID.randomUUID().toString())
            .put("failure", new JSONObject().put("scope", "source_response").put("reason", "upstream_timeout").put("query_id", queryId));
    }
    private static JSONObject transport() throws Exception {
        return new JSONObject().put("failure", new JSONObject().put("scope", "api_transport").put("reason", "api_timeout").put("query_id", JSONObject.NULL));
    }
    private static final class MemoryStore implements SessionState.Store {
        String value;
        boolean failDelete;
        MemoryStore(String value) { this.value = value; }
        public String load() { return value; }
        public void save(String value) { this.value = value; }
        public void delete() throws NativeFailure {
            if (failDelete) throw new NativeFailure("SESSION_STORE_DELETE_FAILED");
            value = null;
        }
    }
    private static NativeHttpBridge bridge(MockWebServer server, MemoryStore store, NativeQueryDenials ledger) throws Exception {
        server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
        NativeHttpBridge bridge = new NativeHttpBridge("http://127.0.0.1:" + server.getPort(), store, ledger);
        if (store.value != null) bridge.session.markBootstrapped();
        return bridge;
    }
    private static JSObject exchange(NativeHttpBridge bridge, NativePolicy.Request request) throws NativeFailure {
        return bridge.request(request, bridge.registry.register(request.id));
    }
    private static MockResponse response(byte[] body, int status) {
        return new MockResponse().setResponseCode(status).setBody(new String(body, StandardCharsets.UTF_8)).addHeader("Content-Type", "application/json");
    }

    @Test public void matchingRequestOwned201BindsRequestQueryWithoutResponseQueryField() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials();
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()), ledger);
            try {
                server.enqueue(response(accepted(), 201));
                assertEquals(201, exchange(bridge, denial(id(100))).getInteger("status", 0).intValue());
                assertEquals(1, ledger.count());
                assertEquals("/v1/fallback-consents", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                for (String schema : new String[]{"device-fallback-intent@1", "device-fallback-intent@2"}) {
                    fails("OFFLINE_FALLBACK_NEVER", () -> bridge.checkFallbackDenial(intent(schema, id(100))));
                    fails("OFFLINE_FALLBACK_NEVER", () -> bridge.checkFallbackDenial(intent(schema, id(100))));
                    bridge.checkFallbackDenial(intent(schema, id(101)));
                }
                bridge.checkFallbackDenial(transport()); assertEquals(1, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }

    @Test public void fixedRoutePostOnceAndStrictRequestMetadataAreRequired() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials();
        for (NativePolicy.Request request : new NativePolicy.Request[]{
            request("/v1/fallback-consents?mode=history", "POST", new String(denial(id(100)).body, StandardCharsets.UTF_8)),
            request("/v1/query", "POST", new String(denial(id(100)).body, StandardCharsets.UTF_8)),
            request("/v1/fallback-consents", "GET", new String(denial(id(100)).body, StandardCharsets.UTF_8)),
            request("/v1/fallback-consents", "POST", "{\"query_id\":\"" + id(100) + "\",\"decision\":\"allow\",\"scope\":\"once\"}"),
            request("/v1/fallback-consents", "POST", "{\"query_id\":\"" + id(100) + "\",\"decision\":\"deny\",\"scope\":\"session\"}"),
            request("/v1/fallback-consents", "POST", "{\"query_id\":\"invalid\",\"decision\":\"deny\",\"scope\":\"once\"}"),
            request("/v1/fallback-consents", "POST", "{\"query_id\":\"" + id(100) + "\",\"query_id\":\"" + id(101) + "\",\"decision\":\"deny\",\"scope\":\"once\"}"),
            request("/v1/fallback-consents", "POST", "{\"query_id\":\"" + id(100) + "\",\"decision\":\"deny\",\"scope\":\"once\",\"warehouse_decision\":\"deny\"}")
        }) { assertNull(NativeQueryDenials.capture(request)); ledger.observeOwnedResponse(NativeQueryDenials.capture(request), 201, accepted()); }
        assertEquals(0, ledger.count()); ledger.check(intent("device-fallback-intent@2", id(100)));
    }

    @Test public void onlySuccessful201WithValidTypedIdDecisionAndScopeIsObserved() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials(); NativeQueryDenials.Capture capture = NativeQueryDenials.capture(denial(id(100)));
        assertNotNull(capture);
        for (int status : new int[]{200, 202, 400, 403, 409, 500}) ledger.observeOwnedResponse(capture, status, accepted());
        for (String body : new String[]{"{}", "invalid", "{\"id\":true,\"decision\":\"deny\",\"scope\":\"once\"}",
            "{\"id\":\"invalid\",\"decision\":\"deny\",\"scope\":\"once\"}",
            "{\"id\":\"" + id(49) + "\",\"decision\":\"allow\",\"scope\":\"once\"}",
            "{\"id\":\"" + id(49) + "\",\"decision\":\"deny\",\"scope\":true}",
            "{\"id\":\"" + id(49) + "\",\"id\":\"" + id(50) + "\",\"decision\":\"deny\",\"scope\":\"once\"}"}) ledger.observeOwnedResponse(capture, 201, utf8(body));
        assertEquals(0, ledger.count()); assertFalse(ledger.closed()); ledger.check(intent("device-fallback-intent@1", id(100)));
        ledger.observeOwnedResponse(capture, 201, accepted()); assertEquals(1, ledger.count());
    }

    @Test public void responseQueryIdCannotReplaceActualRequestBinding() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials();
        byte[] response = utf8(new JSONObject(new String(accepted(), StandardCharsets.UTF_8)).put("query_id", id(101)).toString());
        ledger.observeOwnedResponse(NativeQueryDenials.capture(denial(id(100))), 201, response);
        fails("OFFLINE_FALLBACK_NEVER", () -> ledger.check(intent("device-fallback-intent@2", id(100))));
        ledger.check(intent("device-fallback-intent@2", id(101)));
    }

    @Test public void uuidCaseVariantsAndFreshAttemptsCannotBypassSameFormalQueryDenial() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials(); String query = id(0xabcdef);
        ledger.observeOwnedResponse(NativeQueryDenials.capture(denial(query.toUpperCase(Locale.ROOT))), 201, accepted());
        for (int i = 0; i < 3; i++) for (String schema : new String[]{"device-fallback-intent@1", "device-fallback-intent@2"}) {
            fails("OFFLINE_FALLBACK_NEVER", () -> ledger.check(intent(schema, query)));
            fails("OFFLINE_FALLBACK_NEVER", () -> ledger.check(intent(schema, query.toUpperCase(Locale.ROOT))));
        }
        assertEquals(1, ledger.count());
    }

    @Test public void duplicateDenialsDoNotConsumeCapacityAndOverflowNeverEvicts() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials();
        for (int i = 0; i < NativeQueryDenials.MAX_DENIALS; i++) ledger.observeOwnedResponse(NativeQueryDenials.capture(denial(id(i))), 201, accepted());
        for (int i = 0; i < 10; i++) ledger.observeOwnedResponse(NativeQueryDenials.capture(denial(id(0))), 201, accepted());
        assertEquals(1024, ledger.count()); assertFalse(ledger.closed());
        fails("OFFLINE_FALLBACK_NEVER", () -> ledger.check(intent("device-fallback-intent@1", id(0))));
        ledger.observeOwnedResponse(NativeQueryDenials.capture(denial(id(1024))), 201, accepted());
        assertEquals(1024, ledger.count()); assertTrue(ledger.closed());
        for (int query : new int[]{0, 1024, 1025}) fails("OFFLINE_FALLBACK_CAPACITY", () -> ledger.check(intent("device-fallback-intent@2", id(query))));
        ledger.check(transport());
    }

    @Test public void writeFaultPreservesActual201ButClosesSourceFallbackAcrossReset() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials(new LinkedHashSet<String>() {
            @Override public boolean add(String value) { throw new IllegalStateException("Synthetic write fault"); }
        });
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()), ledger);
            try {
                server.enqueue(response(accepted(), 201)); assertEquals(201, exchange(bridge, denial(id(100))).getInteger("status", 0).intValue());
                assertTrue(ledger.closed()); assertEquals(0, ledger.count());
                fails("OFFLINE_FALLBACK_CAPACITY", () -> bridge.checkFallbackDenial(intent("device-fallback-intent@1", id(101))));
                bridge.reset();
                fails("OFFLINE_FALLBACK_CAPACITY", () -> bridge.checkFallbackDenial(intent("device-fallback-intent@2", id(102))));
                bridge.checkFallbackDenial(transport()); assertEquals(1, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }

    @Test public void callerCancellationAfterOwnedDenialObservationDoesNotRestoreFallback() throws Exception {
        NativePolicy.Request request = denial(id(100)); NativeHttpBridge[] owner = new NativeHttpBridge[1];
        NativeQueryDenials ledger = new NativeQueryDenials(new LinkedHashSet<String>() {
            @Override public boolean add(String value) {
                boolean added = super.add(value);
                try { owner[0].registry.cancel(request.id); }
                catch (NativeFailure failure) { throw new IllegalStateException("Synthetic cancellation failed"); }
                return added;
            }
        });
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()), ledger); owner[0] = bridge;
            try {
                server.enqueue(response(accepted(), 201)); fails("REQUEST_CANCELLED", () -> exchange(bridge, request));
                assertEquals(1, ledger.count()); assertFalse(ledger.closed());
                fails("OFFLINE_FALLBACK_NEVER", () -> bridge.checkFallbackDenial(intent("device-fallback-intent@2", id(100))));
                assertEquals(1, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }

    @Test public void legacyLocalPublicationDoesNotBootstrapOrRequireHealthySessionStorage() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(null), new NativeQueryDenials());
            try {
                NativeHttpBridge.FallbackPublicationFence fence = bridge.captureFallbackPublication();
                assertEquals("published", bridge.publishFallback(fence, () -> { bridge.checkFallbackDenial(transport()); return "published"; }));
                assertEquals(0, server.getRequestCount());
            } finally { bridge.close(); }
        }
        SessionState.Store unavailable = new SessionState.Store() {
            public String load() throws NativeFailure { throw new NativeFailure("SESSION_STORE_READ_FAILED"); }
            public void save(String value) { fail("Unavailable fixture must not be rewritten"); }
            public void delete() { fail("No implicit fixture reset"); }
        };
        NativeHttpBridge bridge = new NativeHttpBridge("http://127.0.0.1:9", unavailable);
        try { assertEquals("published", bridge.publishFallback(bridge.captureFallbackPublication(), () -> "published")); }
        finally { bridge.close(); }
    }

    @Test public void explicitCookieAndOwnerResetInvalidateFenceWithoutDroppingKnownDenials() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials();
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()), ledger);
            try {
                server.enqueue(response(accepted(), 201)); exchange(bridge, denial(id(100)));
                NativeHttpBridge.FallbackPublicationFence before = bridge.captureFallbackPublication();
                bridge.updateCookie(new Headers.Builder().add("Set-Cookie", "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict").build());
                fails("SESSION_CHANGED", () -> bridge.publishFallback(before, () -> "late"));
                fails("OFFLINE_FALLBACK_NEVER", () -> bridge.checkFallbackDenial(intent("device-fallback-intent@1", id(100))));
                NativeHttpBridge.FallbackPublicationFence afterCookie = bridge.captureFallbackPublication(); bridge.reset();
                fails("SESSION_CHANGED", () -> bridge.publishFallback(afterCookie, () -> "late"));
                fails("OFFLINE_FALLBACK_NEVER", () -> bridge.checkFallbackDenial(intent("device-fallback-intent@2", id(100))));
                assertEquals("cold", bridge.publishFallback(bridge.captureFallbackPublication(), () -> "cold"));
                assertEquals(1, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }

    @Test public void failedExplicitResetKeepsKnownDenialAndInvalidatesOldPublication() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials(); MemoryStore store = new MemoryStore(UUID.randomUUID().toString());
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, store, ledger);
            try {
                server.enqueue(response(accepted(), 201)); exchange(bridge, denial(id(100)));
                NativeHttpBridge.FallbackPublicationFence fence = bridge.captureFallbackPublication(); store.failDelete = true;
                fails("SESSION_STORE_DELETE_FAILED", bridge::reset);
                fails("SESSION_CHANGED", () -> bridge.publishFallback(fence, () -> "late"));
                fails("OFFLINE_FALLBACK_NEVER", () -> bridge.checkFallbackDenial(intent("device-fallback-intent@1", id(100))));
                assertEquals(1, ledger.count());
            } finally { bridge.close(); }
        }
    }

    @Test public void unowned201AfterCookieRotationPublishesNoDenialForNewSession() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials();
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()), ledger);
            try {
                server.enqueue(response(accepted(), 201).addHeader("Set-Cookie", "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict"));
                fails("SESSION_CHANGED", () -> exchange(bridge, denial(id(100))));
                assertEquals(0, ledger.count()); bridge.checkFallbackDenial(intent("device-fallback-intent@2", id(100)));
            } finally { bridge.close(); }
        }
    }

    @Test public void denialObservedDuringUnlockedBusinessWindowBlocksFinalPublication() throws Exception {
        NativeQueryDenials ledger = new NativeQueryDenials();
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()), ledger);
            try {
                NativeHttpBridge.FallbackPublicationFence fence = bridge.captureFallbackPublication();
                bridge.publishFallback(fence, () -> { bridge.checkFallbackDenial(intent("device-fallback-intent@2", id(100))); return "durable consumed boundary"; });
                server.enqueue(response(accepted(), 201)); exchange(bridge, denial(id(100)));
                for (String schema : new String[]{"device-fallback-intent@1", "device-fallback-intent@2"})
                    fails("OFFLINE_FALLBACK_NEVER", () -> bridge.publishFallback(fence, () -> { bridge.checkFallbackDenial(intent(schema, id(100))); return "must not release"; }));
            } finally { bridge.close(); }
        }
    }

    @Test public void publicationAndPrivateOwnedObservationUseTheSameLock() throws Exception {
        CountDownLatch observed = new CountDownLatch(1), finishObservation = new CountDownLatch(1), publicationEntered = new CountDownLatch(1);
        NativeQueryDenials ledger = new NativeQueryDenials(new LinkedHashSet<String>() {
            @Override public boolean add(String value) {
                observed.countDown();
                try { if (!finishObservation.await(3, TimeUnit.SECONDS)) throw new IllegalStateException("Synthetic latch deadline"); }
                catch (InterruptedException ignored) { Thread.currentThread().interrupt(); throw new IllegalStateException("Synthetic write interrupted"); }
                return super.add(value);
            }
        });
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server, new MemoryStore(UUID.randomUUID().toString()), ledger);
            try {
                NativeHttpBridge.FallbackPublicationFence fence = bridge.captureFallbackPublication();
                server.enqueue(response(accepted(), 201));
                NativePolicy.Request request = denial(id(100));
                CompletableFuture<JSObject> exchange = CompletableFuture.supplyAsync(() -> {
                    try { return exchange(bridge, request); } catch (NativeFailure failure) { throw new RuntimeException(failure); }
                });
                assertTrue(observed.await(2, TimeUnit.SECONDS)); // Actual owned complete response is parsed before this latch.
                CompletableFuture<String> publishing = CompletableFuture.supplyAsync(() -> {
                    try { return bridge.publishFallback(fence, () -> { publicationEntered.countDown(); bridge.checkFallbackDenial(intent("device-fallback-intent@2", id(100))); return "must not release"; }); }
                    catch (NativeFailure failure) { return failure.code; }
                    catch (Exception failure) { throw new RuntimeException(failure); }
                });
                assertFalse(publicationEntered.await(200, TimeUnit.MILLISECONDS));
                finishObservation.countDown(); assertEquals(201, exchange.get(2, TimeUnit.SECONDS).getInteger("status", 0).intValue());
                assertEquals("OFFLINE_FALLBACK_NEVER", publishing.get(2, TimeUnit.SECONDS));
                assertEquals(0, publicationEntered.getCount());
                fails("OFFLINE_FALLBACK_NEVER", () -> bridge.checkFallbackDenial(intent("device-fallback-intent@2", id(100))));
            } finally { finishObservation.countDown(); bridge.close(); }
        }
    }

    @Test public void foreignAndClosedBridgePublicationFencesAreRejected() throws Exception {
        NativeHttpBridge first = new NativeHttpBridge("http://127.0.0.1:9", new MemoryStore(null));
        NativeHttpBridge second = new NativeHttpBridge("http://127.0.0.1:9", new MemoryStore(null));
        try {
            NativeHttpBridge.FallbackPublicationFence fence = first.captureFallbackPublication();
            fails("SESSION_CHANGED", () -> second.publishFallback(fence, () -> "foreign"));
            first.close(); fails("SESSION_CHANGED", () -> first.publishFallback(fence, () -> "closed"));
            fails("SESSION_CHANGED", first::captureFallbackPublication);
        } finally { first.close(); second.close(); }
    }
}
