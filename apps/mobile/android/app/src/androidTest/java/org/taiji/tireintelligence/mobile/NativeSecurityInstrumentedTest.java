package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okhttp3.mockwebserver.SocketPolicy;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class NativeSecurityInstrumentedTest {
    private interface Failing { void run() throws Exception; }
    private static void fails(String code, Failing action) throws Exception {
        try { action.run(); fail("Expected " + code); } catch (NativeFailure error) { assertEquals(code, error.code); }
    }
    private static NativePolicy.Request request(String id, String path) throws Exception { return NativePolicy.request(id, path, "GET", Collections.emptyMap(), null, bytes -> true); }
    private static String cookieHeader(String cookie) { return NativeHttpBridge.COOKIE_NAME + "=" + cookie + "; HttpOnly; Path=/; SameSite=Strict"; }
    // MockWebServer.url() uses InetAddress.getCanonicalHostName(), which can reverse-resolve this bind
    // address to localhost. Production Debug cleartext is intentionally limited to 127.0.0.1.
    private static String loopbackBase(MockWebServer server) { return "http://127.0.0.1:" + server.getPort(); }
    private static final class MemoryStore implements SessionState.Store {
        String value;
        @Override public String load() { return value; }
        @Override public void save(String value) { this.value = value; }
        @Override public void delete() { value = null; }
    }
    @Test public void encryptedSessionSurvivesRecreationAndCorruptionFailsClosed() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        String namespace = "test-" + UUID.randomUUID(), value = UUID.randomUUID().toString();
        EncryptedSessionStore store = new EncryptedSessionStore(context, namespace);
        StringBuilder digest = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest((context.getPackageName() + ":" + namespace).getBytes(StandardCharsets.UTF_8))) digest.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        File file = new File(context.getNoBackupFilesDir(), "session-" + digest + ".enc");
        try {
            SessionState first = new SessionState(store); assertNull(first.error()); first.persist(value);
            assertFalse(new String(Files.readAllBytes(file.toPath()), StandardCharsets.ISO_8859_1).contains(value));
            SessionState next = new SessionState(new EncryptedSessionStore(context, namespace)); assertEquals(value, next.cookie());
            byte[] damaged = {1, 2, 3}; Files.write(file.toPath(), damaged);
            SessionState closed = new SessionState(store); assertEquals("SESSION_STORE_INVALID", closed.error());
            fails("SESSION_STORE_INVALID", closed::recover); assertArrayEquals(damaged, Files.readAllBytes(file.toPath()));
            closed.reset(); assertNull(closed.error()); assertFalse(file.exists());
        } finally {
            store.delete(); java.security.KeyStore keys = java.security.KeyStore.getInstance("AndroidKeyStore"); keys.load(null); keys.deleteEntry("tire.session." + digest);
        }
    }
    @Test public void nativeHttpBootstrapsPrivatelyAndBlocksRedirects() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
            String cookie = UUID.randomUUID().toString();
            server.enqueue(new MockResponse().setBody("{}").addHeader("Set-Cookie", cookieHeader(cookie)));
            server.enqueue(new MockResponse().setBody("{\"ok\":true}").addHeader("Content-Type", "application/json").addHeader("Set-Cookie", "ignored=private; Path=/"));
            MemoryStore store = new MemoryStore(); NativeHttpBridge bridge = new NativeHttpBridge(loopbackBase(server), store);
            try {
                String id = UUID.randomUUID().toString(); JSObject response = bridge.request(request(id, "/v1/query"), bridge.registry.register(id));
                assertEquals(Integer.valueOf(200), response.getInteger("status")); assertFalse(response.getJSObject("headers").has("set-cookie"));
                RecordedRequest health = server.takeRequest(2, TimeUnit.SECONDS), api = server.takeRequest(2, TimeUnit.SECONDS);
                assertNotNull(health); assertNotNull(api); assertEquals("/health", health.getPath()); assertNull(health.getHeader("Cookie"));
                assertEquals("close", health.getHeader("Connection")); assertEquals("close", api.getHeader("Connection"));
                assertEquals(0, health.getSequenceNumber()); assertEquals(0, api.getSequenceNumber());
                assertEquals(NativeHttpBridge.COOKIE_NAME + "=" + cookie, api.getHeader("Cookie")); assertEquals(cookie, store.value);
                server.enqueue(new MockResponse().setResponseCode(302).addHeader("Location", "https://example.invalid/secret"));
                String redirected = UUID.randomUUID().toString(); fails("API_REDIRECT_BLOCKED", () -> bridge.request(request(redirected, "/v1/redirect"), bridge.registry.register(redirected)));
                bridge.reset(); assertNull(store.value);
            } finally { bridge.close(); }
        }
    }
    @Test public void nativeHttpUsesFreshConnectionsAfterIdleAndDoesNotReplayFailedWrites() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
            server.enqueue(new MockResponse().setBody("{}").addHeader("Set-Cookie", cookieHeader(UUID.randomUUID().toString())));
            server.enqueue(new MockResponse().setBody("first").setSocketPolicy(SocketPolicy.DISCONNECT_AT_END));
            NativeHttpBridge bridge = new NativeHttpBridge(loopbackBase(server), new MemoryStore());
            try {
                String first = UUID.randomUUID().toString();
                assertEquals(Integer.valueOf(200), bridge.request(request(first, "/v1/first"), bridge.registry.register(first)).getInteger("status"));
                RecordedRequest health = server.takeRequest(2, TimeUnit.SECONDS), initial = server.takeRequest(2, TimeUnit.SECONDS);
                assertNotNull(health); assertNotNull(initial);
                assertEquals("close", initial.getHeader("Connection")); assertEquals(0, initial.getSequenceNumber());
                Thread.sleep(6100); // Exceeds the development API's five-second keep-alive timeout.
                server.enqueue(new MockResponse().setBody("after-idle"));
                String afterIdle = UUID.randomUUID().toString();
                assertEquals(Integer.valueOf(200), bridge.request(request(afterIdle, "/v1/after-idle"), bridge.registry.register(afterIdle)).getInteger("status"));
                RecordedRequest fresh = server.takeRequest(2, TimeUnit.SECONDS);
                assertNotNull(fresh); assertEquals("close", fresh.getHeader("Connection")); assertEquals(0, fresh.getSequenceNumber());

                server.enqueue(new MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_DURING_REQUEST_BODY));
                String write = UUID.randomUUID().toString();
                NativePolicy.Request post = NativePolicy.request(write, "/v1/write", "POST", Collections.singletonMap("content-type", "application/pdf"), java.util.Base64.getEncoder().encodeToString(new byte[256 * 1024]), bytes -> true);
                fails("API_REQUEST_FAILED", () -> bridge.request(post, bridge.registry.register(write)));
                RecordedRequest failedWrite = server.takeRequest(2, TimeUnit.SECONDS);
                assertNotNull(failedWrite); assertEquals("POST", failedWrite.getMethod()); assertEquals(0, failedWrite.getSequenceNumber());
                assertNull(server.takeRequest(500, TimeUnit.MILLISECONDS));
                assertEquals(4, server.getRequestCount());
            } finally { bridge.close(); }
        }
    }
    @Test public void nativeCancelStopsRequestAndBootstrapWaiter() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.start(java.net.InetAddress.getByName("127.0.0.1"), 0); server.enqueue(new MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE));
            NativeHttpBridge bridge = new NativeHttpBridge(loopbackBase(server), new MemoryStore());
            try {
                String first = UUID.randomUUID().toString(), waiting = UUID.randomUUID().toString();
                RequestRegistry.Ticket one = bridge.registry.register(first), two = bridge.registry.register(waiting);
                CompletableFuture<String> firstResult = CompletableFuture.supplyAsync(() -> executeCode(bridge, first, one));
                assertNotNull(server.takeRequest(3, TimeUnit.SECONDS));
                CompletableFuture<String> waitingResult = CompletableFuture.supplyAsync(() -> executeCode(bridge, waiting, two));
                bridge.registry.cancel(waiting); assertEquals("REQUEST_CANCELLED", waitingResult.get(2, TimeUnit.SECONDS));
                bridge.registry.cancel(first); assertEquals("REQUEST_CANCELLED", firstResult.get(2, TimeUnit.SECONDS));
            } finally { bridge.close(); }
        }
    }
    @Test public void resetReservationCancelsOldPayloadAndClosesRegistrationBeforeQueuedWork() throws Exception {
        MemoryStore store = new MemoryStore(); store.value = UUID.randomUUID().toString();
        NativeHttpBridge bridge = new NativeHttpBridge("http://127.0.0.1:8000", store);
        try {
            String oldId = UUID.randomUUID().toString(); RequestRegistry.Ticket old = bridge.registry.register(oldId);
            bridge.registry.beginReset();
            fails("REQUEST_CANCELLED", () -> bridge.registry.check(old));
            fails("SESSION_RESET_IN_PROGRESS", () -> bridge.registry.register(UUID.randomUUID().toString()));
            fails("SESSION_RESET_IN_PROGRESS", bridge.registry::beginReset);
            bridge.finishReset();
            assertNull(store.value); assertNull(bridge.session.cookie());
            // An old queued payload cannot bootstrap or send under the newly cleared session.
            fails("REQUEST_CANCELLED", () -> bridge.request(request(oldId, "/v1/query"), old));
            RequestRegistry.Ticket fresh = bridge.registry.register(UUID.randomUUID().toString());
            bridge.registry.check(fresh); bridge.registry.complete(fresh);
        } finally { bridge.close(); }
    }
    private static String executeCode(NativeHttpBridge bridge, String id, RequestRegistry.Ticket ticket) {
        try { bridge.request(request(id, "/v1/query"), ticket); return "unexpected-success"; }
        catch (NativeFailure error) { return error.code; } catch (Exception error) { return "unexpected-error"; }
    }
    @Test public void cookiePolicyRejectsWeakenedAndDuplicateSessionCookies() throws Exception {
        NativeHttpBridge bridge = new NativeHttpBridge("http://127.0.0.1:8000", new MemoryStore());
        try {
            String cookie = UUID.randomUUID().toString();
            for (String bad : new String[]{NativeHttpBridge.COOKIE_NAME + "=" + cookie + "; Path=/; SameSite=Strict", cookieHeader(cookie) + "; Domain=127.0.0.1", cookieHeader(cookie) + "; Secure", cookieHeader(cookie).replace("Strict", "Lax"), cookieHeader(cookie) + "; Path=/v1"}) {
                fails("INVALID_SESSION_COOKIE", () -> bridge.updateCookie(new okhttp3.Headers.Builder().add("Set-Cookie", bad).build()));
            }
            fails("INVALID_SESSION_COOKIE", () -> bridge.updateCookie(new okhttp3.Headers.Builder().add("Set-Cookie", cookieHeader(cookie)).add("Set-Cookie", cookieHeader(cookie)).build()));
        } finally { bridge.close(); }
    }
    @Test public void webViewDeniesBuiltinCapabilitiesAndNativeProxyPaths() throws Exception {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                assertTrue(activity.getBridge().getPlugin("CapacitorHttp").getInstance() instanceof BlockedPlugins.Http);
                assertTrue(activity.getBridge().getPlugin("CapacitorCookies").getInstance() instanceof BlockedPlugins.Cookies);
                assertTrue(activity.getBridge().getPlugin("WebView").getInstance() instanceof BlockedPlugins.WebView);
                assertTrue(activity.getBridge().getPlugin("SystemBars").getInstance() instanceof BlockedPlugins.SystemBars);
                assertFalse(activity.getBridge().getConfig().isUsingLegacyBridge());
                assertEquals(Collections.singleton("https://localhost"), activity.getBridge().getAllowedOriginRules());
                assertTrue(androidx.webkit.WebViewFeature.isFeatureSupported(androidx.webkit.WebViewFeature.WEB_MESSAGE_LISTENER));
                assertFalse(activity.getBridge().getWebView().getSettings().getAllowFileAccess());
                assertFalse(activity.getBridge().getWebView().getSettings().getAllowContentAccess());
                assertFalse(activity.getBridge().getConfig().isLoggingEnabled());
                for (String url : new String[]{"https://localhost/_capacitor_file_/data/data/secret", "https://localhost/_capacitor_content_/content/secret", "https://localhost/_capacitor_http_interceptor_?u=http://example.com", "https://localhost/%5Fcapacitor_file_/secret", "http://127.0.0.1:8000/health", "https://example.com/"}) {
                    WebResourceResponse response = activity.getBridge().getWebViewClient().shouldInterceptRequest(activity.getBridge().getWebView(), resource(url));
                    assertNotNull(response); assertEquals(403, response.getStatusCode());
                    assertTrue(activity.getBridge().getWebViewClient().shouldOverrideUrlLoading(activity.getBridge().getWebView(), resource(url)));
                }
            });
        }
    }
    @Test public void webViewInsetsResizeLayoutForSystemBarsAndKeyboard() throws Exception {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                android.webkit.WebView view = activity.getBridge().getWebView();
                assertTrue(view.getLayoutParams() instanceof android.view.ViewGroup.MarginLayoutParams);
                androidx.core.view.WindowInsetsCompat keyboard = new androidx.core.view.WindowInsetsCompat.Builder()
                        .setInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars() | androidx.core.view.WindowInsetsCompat.Type.displayCutout(), androidx.core.graphics.Insets.of(2, 11, 3, 17))
                        .setInsets(androidx.core.view.WindowInsetsCompat.Type.ime(), androidx.core.graphics.Insets.of(0, 0, 0, 23)).build();
                androidx.core.view.ViewCompat.dispatchApplyWindowInsets(view, keyboard);
                android.view.ViewGroup.MarginLayoutParams layout = (android.view.ViewGroup.MarginLayoutParams) view.getLayoutParams();
                assertEquals(2, layout.leftMargin); assertEquals(11, layout.topMargin); assertEquals(3, layout.rightMargin); assertEquals(23, layout.bottomMargin);
                assertEquals(0, view.getPaddingLeft()); assertEquals(0, view.getPaddingTop()); assertEquals(0, view.getPaddingRight()); assertEquals(0, view.getPaddingBottom());
                androidx.core.view.WindowInsetsCompat closed = new androidx.core.view.WindowInsetsCompat.Builder(keyboard)
                        .setInsets(androidx.core.view.WindowInsetsCompat.Type.ime(), androidx.core.graphics.Insets.NONE).build();
                androidx.core.view.ViewCompat.dispatchApplyWindowInsets(view, closed);
                assertEquals(17, ((android.view.ViewGroup.MarginLayoutParams) view.getLayoutParams()).bottomMargin);
            });
        }
    }
    private static WebResourceRequest resource(String value) {
        return new WebResourceRequest() {
            @Override public Uri getUrl() { return Uri.parse(value); }
            @Override public boolean isForMainFrame() { return true; }
            @Override public boolean isRedirect() { return false; }
            @Override public boolean hasGesture() { return false; }
            @Override public String getMethod() { return "GET"; }
            @Override public Map<String,String> getRequestHeaders() { return Collections.emptyMap(); }
        };
    }
}
