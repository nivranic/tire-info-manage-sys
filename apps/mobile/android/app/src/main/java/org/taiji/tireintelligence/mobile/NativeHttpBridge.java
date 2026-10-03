package org.taiji.tireintelligence.mobile;

import android.os.SystemClock;
import com.getcapacitor.JSObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.Proxy;
import java.util.Base64;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import java.util.concurrent.locks.ReentrantLock;
import okhttp3.Call;
import okhttp3.CookieJar;
import okhttp3.Headers;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Protocol;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;

/** The only native network authority. No WebView/global cookie manager is consulted. */
public final class NativeHttpBridge {
    static final String COOKIE_NAME = "tire_local_session";
    final SessionState session;
    final RequestRegistry registry = new RequestRegistry(SystemClock::elapsedRealtime);
    private final ReentrantReadWriteLock lifecycle = new ReentrantReadWriteLock(true);
    private final ReentrantLock bootstrapLock = new ReentrantLock(true);
    private final NativeQueryDenials queryDenials;
    private long fallbackPublicationRevision;
    private boolean fallbackPublicationClosed;
    private final String baseUrl;
    private final OkHttpClient client = new OkHttpClient.Builder()
            .proxy(Proxy.NO_PROXY).followRedirects(false).followSslRedirects(false).cookieJar(CookieJar.NO_COOKIES)
            .retryOnConnectionFailure(false).connectTimeout(3, TimeUnit.SECONDS).callTimeout(75, TimeUnit.SECONDS)
            .readTimeout(75, TimeUnit.SECONDS).writeTimeout(75, TimeUnit.SECONDS).protocols(java.util.Collections.singletonList(Protocol.HTTP_1_1)).build();
    public NativeHttpBridge(String baseUrl, SessionState.Store store) { this(baseUrl, store, new NativeQueryDenials()); }
    NativeHttpBridge(String baseUrl, SessionState.Store store, NativeQueryDenials queryDenials) {
        this.baseUrl = baseUrl; session = new SessionState(store); this.queryDenials = queryDenials;
    }
    /** Shared UI/Worker authority, fixed for the whole history-only update run. */
    static final class SessionFence {
        private final SessionState.Fence session;
        private final long registryGeneration;
        private SessionFence(SessionState.Fence session, long registryGeneration) {
            this.session = session; this.registryGeneration = registryGeneration;
        }
    }
    SessionFence freezeSession() throws NativeFailure {
        long generation = registry.freezeGeneration();
        SessionFence fence = new SessionFence(session.freeze(), generation);
        checkSession(fence);
        return fence;
    }
    void checkSession(SessionFence fence) throws NativeFailure {
        if (fence == null) throw new NativeFailure("SESSION_CHANGED");
        registry.checkGeneration(fence.registryGeneration);
        session.check(fence.session);
    }
    String sessionBinding(SessionFence fence) throws NativeFailure {
        checkSession(fence);
        return session.binding(fence.session);
    }
    <T> T publish(SessionFence fence,java.util.concurrent.Callable<T> publication) throws Exception {
        // Matches the response-cookie lock order. Reset/cookie changes cannot
        // interleave between the last authority check and the catalog COMMIT.
        synchronized(session) { synchronized(registry) {checkSession(fence);return publication.call();} }
    }
    /** A local publication boundary, independent of cookie availability and source admission. */
    static final class FallbackPublicationFence {
        private final NativeHttpBridge bridge;
        private final long revision, registryGeneration;
        private FallbackPublicationFence(NativeHttpBridge bridge, long revision, long registryGeneration) {
            this.bridge = bridge; this.revision = revision; this.registryGeneration = registryGeneration;
        }
    }
    FallbackPublicationFence captureFallbackPublication() throws NativeFailure {
        synchronized (session) { synchronized (registry) {
            if (fallbackPublicationClosed) throw new NativeFailure("SESSION_CHANGED");
            return new FallbackPublicationFence(this, fallbackPublicationRevision, registry.freezeGeneration());
        } }
    }
    <T> T publishFallback(FallbackPublicationFence fence, java.util.concurrent.Callable<T> publication) throws Exception {
        synchronized (session) { synchronized (registry) {
            if (fence == null || fence.bridge != this || fence.revision != fallbackPublicationRevision || fallbackPublicationClosed)
                throw new NativeFailure("SESSION_CHANGED");
            registry.checkGeneration(fence.registryGeneration);
            return publication.call();
        } }
    }
    void checkFallbackDenial(org.json.JSONObject intent) throws NativeFailure {
        synchronized (session) { synchronized (registry) { queryDenials.check(intent); } }
    }
    SessionFence fallbackMetadataFence() throws NativeFailure {
        RequestRegistry.Ticket ticket = registry.register(java.util.UUID.randomUUID().toString());
        boolean locked = false;
        try {
            while (!(locked = lifecycle.readLock().tryLock(100, TimeUnit.MILLISECONDS))) registry.check(ticket);
            registry.check(ticket); session.check(); bootstrap(ticket);
            return freezeSession();
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt(); throw new NativeFailure("REQUEST_CANCELLED");
        } finally { if (locked) lifecycle.readLock().unlock(); registry.complete(ticket); }
    }
    JSObject fallbackMetadata(String path, SessionFence fence) throws NativeFailure {
        if (!"/v1/source-settings".equals(path) && !"/v1/sources".equals(path)) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        String id = java.util.UUID.randomUUID().toString();
        NativePolicy.Request request = NativePolicy.request(id, path, "GET", java.util.Collections.emptyMap(), null, bytes -> true);
        return requestBounded(request, registry.register(id), 1024 * 1024, fence);
    }
    public JSObject request(NativePolicy.Request request, RequestRegistry.Ticket ticket) throws NativeFailure {
        return requestBounded(request, ticket, NativePolicy.MAX_RESPONSE_BYTES);
    }
    private JSObject requestBounded(NativePolicy.Request request, RequestRegistry.Ticket ticket, int maximumBytes) throws NativeFailure {
        return requestBounded(request, ticket, maximumBytes, null);
    }
    JSObject syncRequest(NativePolicy.Request request, SessionFence fence, String ownerScope) throws NativeFailure {
        // Callers construct these requests inside the coordinator, never from arbitrary IPC.
        boolean permitted = ("POST".equals(request.method) &&
            (request.path.equals("/v1/offline-pack-updates:prepare") || request.path.equals("/v1/offline-packs"))) ||
            ("GET".equals(request.method) && request.path.matches("/v1/offline-packs/[0-9a-f-]{36}\\?mode=history"));
        if (!permitted) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        if (ownerScope == null || !ownerScope.matches("[0-9a-f]{64}")) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        checkSession(fence);
        Map<String, String> headers = new HashMap<>(request.headers);
        headers.put("x-tire-offline-sync", "1");
        headers.put("x-tire-offline-expected-owner", ownerScope);
        NativePolicy.Request bound = new NativePolicy.Request(request.id, request.path, request.method, headers, request.body);
        RequestRegistry.Ticket ticket = registry.register(request.id);
        JSObject result = requestBounded(bound, ticket, NativePolicy.MAX_RESPONSE_BYTES, fence);
        if (!ownerScope.equals(result.getJSObject("headers").getString("x-tire-offline-owner-scope"))) {
            throw new NativeFailure("OFFLINE_SYNC_OWNER_MISMATCH");
        }
        return result;
    }
    private JSObject requestBounded(NativePolicy.Request request, RequestRegistry.Ticket ticket, int maximumBytes, SessionFence fence) throws NativeFailure {
        boolean locked = false;
        try {
            while (!(locked = lifecycle.readLock().tryLock(100, TimeUnit.MILLISECONDS))) registry.check(ticket);
            registry.check(ticket); session.check();
            if (fence == null) bootstrap(ticket); else checkSession(fence);
            registry.check(ticket);
            NativeQueryDenials.Capture denial = NativeQueryDenials.capture(request);
            SessionFence denialSession = denial == null ? null : freezeSession();
            String cookie = session.cookie();
            try (Response response = send(request.method, request.path, request.headers, request.body, cookie, ticket)) {
                synchronized (session) {
                    registry.check(ticket); session.check();
                    if (!Objects.equals(cookie, session.cookie())) throw new NativeFailure("SESSION_CHANGED");
                    updateCookie(response.headers());
                    if (fence != null) checkSession(fence);
                }
                JSObject result = read(response, ticket, maximumBytes, denial, denialSession);
                if (fence != null) checkSession(fence);
                return result;
            }
        } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); throw new NativeFailure("REQUEST_CANCELLED"); }
        finally { if (locked) lifecycle.readLock().unlock(); registry.complete(ticket); }
    }
    private void bootstrap(RequestRegistry.Ticket ticket) throws NativeFailure {
        boolean locked = false;
        try {
            while (!(locked = bootstrapLock.tryLock(100, TimeUnit.MILLISECONDS))) registry.check(ticket);
            registry.check(ticket); session.check(); if (session.bootstrapped()) return;
            try (Response response = send("GET", "/health", java.util.Collections.emptyMap(), new byte[0], session.cookie(), ticket)) {
                registry.check(ticket); updateCookie(response.headers());
                JSObject result = read(response, ticket);
                if (result.getInteger("status", 0) != 200) throw new NativeFailure("API_HEALTH_FAILED");
                if (session.cookie() == null) throw new NativeFailure("SESSION_COOKIE_MISSING");
                session.markBootstrapped();
            }
        } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); throw new NativeFailure("REQUEST_CANCELLED"); }
        finally { if (locked) bootstrapLock.unlock(); }
    }
    private Response send(String method, String path, Map<String,String> headers, byte[] body, String cookie, RequestRegistry.Ticket ticket) throws NativeFailure {
        registry.check(ticket);
        // The local API closes idle HTTP/1.1 connections sooner than OkHttp's default pool.
        // A fresh connection prevents a stale socket failure without replaying any write.
        Request.Builder builder = new Request.Builder().url(baseUrl + path).header("Accept", "application/json, application/pdf, text/plain, text/html").header("Cache-Control", "no-store").header("Connection", "close");
        for (Map.Entry<String,String> header : headers.entrySet()) builder.header(header.getKey(), header.getValue());
        if (cookie != null) builder.header("Cookie", COOKIE_NAME + "=" + cookie);
        RequestBody requestBody = method.equals("GET") ? null : RequestBody.create(body, headers.containsKey("content-type") ? MediaType.parse(headers.get("content-type")) : null);
        Call call = client.newCall(builder.method(method, requestBody).build());
        call.timeout().timeout(Math.max(1, ticket.deadline - SystemClock.elapsedRealtime()), TimeUnit.MILLISECONDS);
        ticket.attach(call::cancel);
        try {
            Response response = call.execute();
            try { registry.check(ticket); } catch (NativeFailure failure) { response.close(); throw failure; }
            if (response.code() >= 300 && response.code() < 400) { response.close(); throw new NativeFailure("API_REDIRECT_BLOCKED"); }
            return response;
        } catch (IOException error) { throw networkError(error, ticket); }
    }
    private NativeFailure networkError(IOException error, RequestRegistry.Ticket ticket) {
        try { registry.check(ticket); } catch (NativeFailure failure) { return failure; }
        if (error instanceof java.io.InterruptedIOException) return new NativeFailure("API_TIMEOUT");
        if (error instanceof java.net.ConnectException || error instanceof java.net.UnknownHostException) return new NativeFailure("API_UNAVAILABLE");
        return new NativeFailure("API_REQUEST_FAILED");
    }
    /** Fixed owned endpoint; plaintext stays in native memory and is never returned through IPC. */
    org.json.JSONObject offlineDescriptor(String packageId) throws NativeFailure {
        NativePolicy.requestId(packageId);
        String id = java.util.UUID.randomUUID().toString();
        RequestRegistry.Ticket ticket = registry.register(id);
        NativePolicy.Request request = NativePolicy.request(id, "/v1/offline-packs/" + packageId + "?mode=history",
            "GET", java.util.Collections.emptyMap(), null, bytes -> true);
        JSObject result = requestBounded(request, ticket, 64 * 1024);
        if (result.getInteger("status", 0) != 200) throw new NativeFailure("OFFLINE_DOWNLOAD_FAILED");
        byte[] bytes = NativePolicy.decode(result.getString("body_base64"), 64 * 1024, "OFFLINE_DOWNLOAD_INVALID");
        try { return OfflinePackageValidator.parse(bytes); }
        finally { Arrays.fill(bytes, (byte) 0); }
    }
    byte[] downloadOffline(String packageId, String expectedHash, int expectedBytes) throws NativeFailure {
        return downloadOffline(packageId, expectedHash, expectedBytes, null, null);
    }
    byte[] downloadOffline(String packageId, String expectedHash, int expectedBytes, SessionFence fence, String ownerScope) throws NativeFailure {
        NativePolicy.requestId(packageId);
        if (expectedHash == null || !expectedHash.matches("[0-9a-f]{64}") ||
            expectedBytes < 1 || expectedBytes > 8 * 1024 * 1024) {
            throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        }
        if (fence != null && (ownerScope == null || !ownerScope.matches("[0-9a-f]{64}"))) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        RequestRegistry.Ticket ticket = registry.register(java.util.UUID.randomUUID().toString());
        boolean locked = false;
        try {
            while (!(locked = lifecycle.readLock().tryLock(100, TimeUnit.MILLISECONDS))) registry.check(ticket);
            registry.check(ticket); session.check();
            if (fence == null) bootstrap(ticket); else checkSession(fence);
            registry.check(ticket);
            String cookie = session.cookie();
            String path = "/v1/offline-packs/" + packageId + "/download?mode=history";
            Map<String, String> headers = new HashMap<>();
            if (fence != null) { headers.put("x-tire-offline-sync", "1"); headers.put("x-tire-offline-expected-owner", ownerScope); }
            try (Response response = send("GET", path, headers, new byte[0], cookie, ticket)) {
                synchronized (session) {
                    registry.check(ticket); session.check();
                    if (!Objects.equals(cookie, session.cookie())) throw new NativeFailure("SESSION_CHANGED");
                    updateCookie(response.headers());
                    if (fence != null) checkSession(fence);
                }
                if (response.code() != 200) throw new NativeFailure("OFFLINE_DOWNLOAD_FAILED");
                if (fence != null && !ownerScope.equals(response.header("X-Tire-Offline-Owner-Scope"))) throw new NativeFailure("OFFLINE_SYNC_OWNER_MISMATCH");
                ResponseBody body = response.body();
                String type = response.header("Content-Type", "").split(";", 2)[0].trim();
                if (body == null || !type.equalsIgnoreCase("application/json") ||
                    !expectedHash.equals(response.header("X-Content-SHA256")) ||
                    !("\"" + expectedHash + "\"").equals(response.header("ETag")) ||
                    !Integer.toString(expectedBytes).equals(response.header("Content-Length")) ||
                    !"no-store".equalsIgnoreCase(response.header("Cache-Control")) ||
                    !"nosniff".equalsIgnoreCase(response.header("X-Content-Type-Options")) ||
                    body.contentLength() != expectedBytes) {
                    throw new NativeFailure("OFFLINE_DOWNLOAD_INVALID");
                }
                try (InputStream input = body.byteStream()) {
                    ByteArrayOutputStream bytes = new ByteArrayOutputStream(Math.min(expectedBytes, 64 * 1024));
                    byte[] buffer = new byte[16 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        registry.check(ticket);
                        if (count > expectedBytes - bytes.size()) throw new NativeFailure("OFFLINE_TOO_LARGE");
                        bytes.write(buffer, 0, count);
                    }
                    registry.check(ticket);
                    if (fence != null) checkSession(fence);
                    byte[] result = bytes.toByteArray();
                    if (result.length != expectedBytes || !OfflineCipher.sha256(result).equals(expectedHash)) {
                        Arrays.fill(result, (byte) 0);
                        throw new NativeFailure("OFFLINE_DOWNLOAD_INVALID");
                    }
                    return result;
                } catch (IOException error) { throw networkError(error, ticket); }
                finally { ticket.detach(); }
            }
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt(); throw new NativeFailure("REQUEST_CANCELLED");
        } finally {
            if (locked) lifecycle.readLock().unlock();
            registry.complete(ticket);
        }
    }
    private JSObject read(Response response, RequestRegistry.Ticket ticket) throws NativeFailure {
        return read(response, ticket, NativePolicy.MAX_RESPONSE_BYTES);
    }
    private JSObject read(Response response, RequestRegistry.Ticket ticket, int maximumBytes) throws NativeFailure {
        return read(response, ticket, maximumBytes, null, null);
    }
    private JSObject read(Response response, RequestRegistry.Ticket ticket, int maximumBytes,
        NativeQueryDenials.Capture denial, SessionFence denialSession) throws NativeFailure {
        ResponseBody body = response.body();
        if (body == null) throw new NativeFailure("API_REQUEST_FAILED");
        if (body.contentLength() > maximumBytes) throw new NativeFailure("RESPONSE_TOO_LARGE");
        JSObject headers = new JSObject();
        for (String name : new String[]{"content-type", "content-disposition", "cache-control", "x-content-type-options", "retry-after", "x-tire-offline-owner-scope"}) {
            String value = response.header(name);
            if (value == null) continue;
            if (value.length() > 4096 || NativePolicy.control(value)) throw new NativeFailure("INVALID_RESPONSE_HEADER");
            headers.put(name, value);
        }
        try {
            InputStream input = body.byteStream(); ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[16 * 1024]; int count;
            while ((count = input.read(buffer)) != -1) {
                registry.check(ticket);
                if (count > maximumBytes - bytes.size()) throw new NativeFailure("RESPONSE_TOO_LARGE");
                bytes.write(buffer, 0, count);
            }
            // Once an owned complete response has arrived, caller cancellation
            // may suppress delivery but cannot erase a confirmed terminal denial.
            if (denial == null) registry.check(ticket);
            byte[] received = bytes.toByteArray();
            try {
                if (denial != null) {
                    synchronized (session) { synchronized (registry) {
                        checkSession(denialSession);
                        queryDenials.observeOwnedResponse(denial, response.code(), received);
                        // Cancellation after an owned complete denial cannot undo that observation.
                        registry.check(ticket);
                    } }
                }
                JSObject result = new JSObject(); result.put("status", response.code()); result.put("headers", headers);
                result.put("body_base64", Base64.getEncoder().encodeToString(received)); return result;
            } finally { Arrays.fill(received, (byte) 0); }
        } catch (IOException error) { throw networkError(error, ticket); }
        finally { ticket.detach(); }
    }
    void updateCookie(Headers headers) throws NativeFailure {
        boolean seen = false; String replacement = null;
        for (String raw : headers.values("Set-Cookie")) {
            if (raw.length() > 4096 || NativePolicy.control(raw)) throw new NativeFailure("INVALID_SESSION_COOKIE");
            String[] parts = raw.split(";", -1); int first = parts[0].indexOf('=');
            if (first < 1) throw new NativeFailure("INVALID_SESSION_COOKIE");
            if (!parts[0].substring(0, first).trim().equals(COOKIE_NAME)) continue;
            if (seen) throw new NativeFailure("INVALID_SESSION_COOKIE"); seen = true;
            String value = parts[0].substring(first + 1).trim();
            Map<String,String> attributes = new HashMap<>();
            for (int i = 1; i < parts.length; i++) {
                String attribute = parts[i].trim(); if (attribute.isEmpty()) continue; int equal = attribute.indexOf('=');
                String name = (equal < 0 ? attribute : attribute.substring(0, equal)).trim().toLowerCase(Locale.ROOT);
                String content = equal < 0 ? "" : attribute.substring(equal + 1).trim();
                if (attributes.put(name, content) != null) throw new NativeFailure("INVALID_SESSION_COOKIE");
            }
            if (!attributes.containsKey("httponly") || !attributes.get("httponly").isEmpty() || !"Strict".equalsIgnoreCase(attributes.get("samesite")) || !"/".equals(attributes.get("path")) || attributes.containsKey("domain") || attributes.containsKey("secure")) throw new NativeFailure("INVALID_SESSION_COOKIE");
            boolean deleted = false;
            if (attributes.containsKey("max-age")) {
                try { deleted = Long.parseLong(attributes.get("max-age")) <= 0; } catch (NumberFormatException ignored) { throw new NativeFailure("INVALID_SESSION_COOKIE"); }
            }
            if (!deleted) { try { NativePolicy.requestId(value); } catch (NativeFailure ignored) { throw new NativeFailure("INVALID_SESSION_COOKIE"); } replacement = value; }
        }
        if (seen) {
            synchronized (session) { synchronized (registry) {
                boolean changed = !Objects.equals(session.cookie(), replacement);
                try { session.persist(replacement); }
                finally { if (changed) fallbackPublicationRevision++; }
            } }
        }
    }
    public void recover() throws NativeFailure {
        if (session.error() == null) return;
        lifecycle.writeLock().lock();
        try { synchronized (session) { synchronized (registry) {
            try { session.recover(); } finally { fallbackPublicationRevision++; }
        } } } finally { lifecycle.writeLock().unlock(); }
    }
    public void reset() throws NativeFailure {
        registry.beginReset();
        finishReset();
    }
    /** A plugin reserves the generation synchronously before queued control work can wait. */
    void finishReset() throws NativeFailure {
        lifecycle.writeLock().lock();
        try { synchronized (session) { synchronized (registry) {
            try { session.reset(); } finally { fallbackPublicationRevision++; }
        } } } finally { lifecycle.writeLock().unlock(); registry.endReset(); }
    }
    public void close() {
        synchronized (session) { synchronized (registry) { fallbackPublicationClosed = true; fallbackPublicationRevision++; registry.cancelAll(); } }
        client.dispatcher().executorService().shutdown(); client.connectionPool().evictAll();
    }
}
