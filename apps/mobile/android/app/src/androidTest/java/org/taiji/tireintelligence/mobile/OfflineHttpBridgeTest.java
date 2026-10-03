package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.SocketPolicy;
import okio.Buffer;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Real native HTTP against a loopback synthetic server; no normal API or secrets. */
@RunWith(AndroidJUnit4.class)
public final class OfflineHttpBridgeTest {
    private interface Checked { void run() throws Exception; }
    private static void fails(String code, Checked action) throws Exception {
        try { action.run(); fail("Expected " + code); }
        catch (NativeFailure failure) { assertEquals(code, failure.code); }
    }
    private static final class MemoryStore implements SessionState.Store {
        String value;
        public String load() { return value; }
        public void save(String value) { this.value = value; }
        public void delete() { value = null; }
    }
    private static NativeHttpBridge bridge(MockWebServer server) throws Exception {
        server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
        server.enqueue(new MockResponse().setBody("{}").addHeader("Set-Cookie",
            "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict"));
        return new NativeHttpBridge("http://127.0.0.1:" + server.getPort(), new MemoryStore());
    }
    private static JSONObject descriptor() throws Exception {
        return OfflinePackageValidator.parse(OfflinePackageValidatorTest.asset("valid-descriptor.json"));
    }
    private static MockResponse frozen(byte[] raw, JSONObject descriptor) throws Exception {
        return new MockResponse().setBody(new Buffer().write(raw)).addHeader("Content-Type", "application/json")
            .addHeader("X-Content-SHA256", descriptor.getString("sha256"))
            .addHeader("ETag", "\"" + descriptor.getString("sha256") + "\"")
            .addHeader("Cache-Control", "no-store").addHeader("X-Content-Type-Options", "nosniff");
    }
    @Test public void ownedDescriptorAndOriginalBytesStayInsideNativeAuthority() throws Exception {
        JSONObject descriptor = descriptor(); byte[] raw = OfflinePackageValidatorTest.asset("valid-envelope.json");
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server);
            try {
                server.enqueue(new MockResponse().setBody(descriptor.toString()).addHeader("Content-Type", "application/json"));
                server.enqueue(frozen(raw, descriptor));
                assertEquals(descriptor.getString("sha256"), bridge.offlineDescriptor(descriptor.getString("id")).getString("sha256"));
                assertArrayEquals(raw, bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), raw.length));
                assertEquals("/health", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                assertEquals("/v1/offline-packs/" + descriptor.getString("id") + "?mode=history", server.takeRequest(2, TimeUnit.SECONDS).getPath());
                assertEquals(descriptor.getString("download_path"), server.takeRequest(2, TimeUnit.SECONDS).getPath());
            } finally { bridge.close(); }
        }
    }
    @Test public void incorrectHashHeadersContentTypeCacheAndBodyAreRejected() throws Exception {
        JSONObject descriptor = descriptor(); byte[] raw = OfflinePackageValidatorTest.asset("valid-envelope.json");
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server);
            try {
                for (String header : new String[]{"Content-Type", "X-Content-SHA256", "ETag", "Cache-Control", "X-Content-Type-Options"}) {
                    server.enqueue(frozen(raw, descriptor).setHeader(header, "synthetic-invalid"));
                    fails("OFFLINE_DOWNLOAD_INVALID", () -> bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), raw.length));
                }
                byte[] corrupted = Arrays.copyOf(raw, raw.length); corrupted[100] ^= 1;
                server.enqueue(frozen(corrupted, descriptor));
                fails("OFFLINE_DOWNLOAD_INVALID", () -> bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), raw.length));
            } finally { bridge.close(); }
        }
    }
    @Test public void unknownLengthOverLimitRedirectAndNotOwnedStatusFailClosed() throws Exception {
        JSONObject descriptor = descriptor(); byte[] raw = OfflinePackageValidatorTest.asset("valid-envelope.json");
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server);
            try {
                server.enqueue(frozen(raw, descriptor).setChunkedBody(new Buffer().write(raw), 4096));
                fails("OFFLINE_DOWNLOAD_INVALID", () -> bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), raw.length));
                fails("OFFLINE_INVALID_ARGUMENT", () -> bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), 8 * 1024 * 1024 + 1));
                server.enqueue(new MockResponse().setResponseCode(302).addHeader("Location", "https://example.invalid/never-followed"));
                fails("API_REDIRECT_BLOCKED", () -> bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), raw.length));
                server.enqueue(new MockResponse().setResponseCode(404).setBody("{}"));
                fails("OFFLINE_DOWNLOAD_FAILED", () -> bridge.downloadOffline(descriptor.getString("id"), descriptor.getString("sha256"), raw.length));
                assertEquals(4, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }
    @Test public void descriptorStopsAt64KiBBeforeParsingAndResetCancelsSocket() throws Exception {
        JSONObject descriptor = descriptor();
        try (MockWebServer server = new MockWebServer()) {
            NativeHttpBridge bridge = bridge(server);
            try {
                server.enqueue(new MockResponse().setBody(" ".repeat(64 * 1024 + 1)));
                fails("RESPONSE_TOO_LARGE", () -> bridge.offlineDescriptor(descriptor.getString("id")));
                server.takeRequest(2, TimeUnit.SECONDS); server.takeRequest(2, TimeUnit.SECONDS);
                server.enqueue(new MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE));
                CompletableFuture<String> result = CompletableFuture.supplyAsync(() -> {
                    try { bridge.downloadOffline(descriptor.optString("id"), descriptor.optString("sha256"), descriptor.optInt("byte_count")); return "unexpected-success"; }
                    catch (NativeFailure failure) { return failure.code; }
                });
                assertNotNull(server.takeRequest(3, TimeUnit.SECONDS));
                bridge.registry.beginReset();
                assertEquals("REQUEST_CANCELLED", result.get(2, TimeUnit.SECONDS));
                bridge.finishReset();
            } finally { bridge.close(); }
        }
    }
}
