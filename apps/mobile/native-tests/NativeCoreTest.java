package org.taiji.tireintelligence.mobile;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

/** Runs with the JDK alone, exercising production policy/session/registry code. */
public final class NativeCoreTest {
    private static int checks;
    private static String id() { return UUID.randomUUID().toString(); }
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("check " + checks); }
    private static void fails(String code, Throwing action) throws Exception {
        checks++;
        try { action.run(); throw new AssertionError("Expected " + code); }
        catch (NativeFailure error) { if (!code.equals(error.code)) throw new AssertionError(error.code + " != " + code); }
    }
    interface Throwing { void run() throws Exception; }
    static final class Store implements SessionState.Store {
        String cookie;
        String failure;
        int writes;
        public String load() throws NativeFailure { if (failure != null) throw new NativeFailure(failure); return cookie; }
        public void save(String value) throws NativeFailure { if (failure != null) throw new NativeFailure(failure); cookie = value; writes++; }
        public void delete() throws NativeFailure { if (failure != null) throw new NativeFailure(failure); cookie = null; }
    }
    public static void main(String[] args) throws Exception {
        NativePolicy.path("/health");
        NativePolicy.path("/v1/query?q=%E8%BD%AE%E8%83%8E");
        for (String value : new String[]{"https://bad/v1/x", "//bad/v1/x", "/v1", "/health/x", "/v1//x", "/v1/../x", "/v1/%2e%2e/x", "/v1/%252e/x", "/v1/%2Fx", "/v1/%5cx", "/v1/x#x", "/v1/x?q=%00", "/v1/%C0%AFx", "/v1/%x1"}) {
            fails("INVALID_API_PATH", () -> NativePolicy.path(value));
        }
        NativePolicy.requestId(id());
        fails("INVALID_REQUEST_ID", () -> NativePolicy.requestId("1-1-1-1-1"));
        Map<String,String> headers = new LinkedHashMap<>();
        headers.put("Content-Type", "application/json");
        NativePolicy.Request valid = NativePolicy.request(id(), "/v1/query", "POST", headers, "e30=", bytes -> true);
        check(new String(valid.body, StandardCharsets.UTF_8).equals("{}"));
        fails("INVALID_API_METHOD", () -> NativePolicy.request(id(), "/health", "PATCH", Map.of(), null, bytes -> true));
        fails("INVALID_API_BODY", () -> NativePolicy.request(id(), "/health", "GET", headers, "", bytes -> true));
        fails("INVALID_API_BODY", () -> NativePolicy.request(id(), "/v1/x", "POST", Map.of(), "e30=", bytes -> true));
        for (String header : new String[]{"Cookie", "Authorization", "Origin", "Host", "Referer", "X-Tire-Offline-Sync", "X-Tire-Offline-Expected-Owner"}) {
            fails("INVALID_API_HEADER", () -> NativePolicy.request(id(), "/health", "GET", Map.of(header, "x"), null, bytes -> true));
        }
        headers.put("content-type", "application/json");
        fails("INVALID_API_HEADER", () -> NativePolicy.request(id(), "/health", "GET", headers, null, bytes -> true));
        fails("INVALID_API_HEADER", () -> NativePolicy.request(id(), "/health", "GET", Map.of("x-evidence-metadata", "e30="), null, bytes -> false));
        fails("INVALID_BASE64", () -> NativePolicy.decode("not base64", 10, "TOO_LARGE"));
        fails("INVALID_BASE64", () -> NativePolicy.decode("Zg", 10, "TOO_LARGE"));
        fails("TOO_LARGE", () -> NativePolicy.decode("Zm9v", 2, "TOO_LARGE"));
        NativePolicy.externalUrl("https://example.com/a?q=x");
        for (String url : new String[]{"file:///x", "intent://x", "javascript:alert(1)", "https://a:b@example.com", "https://example.com\\@bad", "https://example.com\n"}) {
            fails("INVALID_EXTERNAL_URL", () -> NativePolicy.externalUrl(url));
        }
        check(NativePolicy.allowedNavigation("https://localhost/"));
        for (String url : new String[]{"http://localhost/", "https://localhost:444/", "https://user@localhost/", "https://example.com/", "file:///x", "https://localhost.evil/"}) check(!NativePolicy.allowedNavigation(url));
        NativePolicy.download("报告.pdf", "application/pdf");
        fails("INVALID_DOWNLOAD_NAME", () -> NativePolicy.download("../report.pdf", "application/pdf"));
        fails("INVALID_DOWNLOAD_NAME", () -> NativePolicy.download("CON.pdf", "application/pdf"));
        fails("INVALID_DOWNLOAD_TYPE", () -> NativePolicy.download("report.html", "application/pdf"));

        long[] now = {1};
        RequestRegistry registry = new RequestRegistry(() -> now[0]);
        String before = id(); registry.cancel(before);
        fails("REQUEST_CANCELLED", () -> registry.register(before));
        String first = id(); RequestRegistry.Ticket ticket = registry.register(first);
        AtomicInteger cancelled = new AtomicInteger(); ticket.attach(cancelled::incrementAndGet);
        registry.cancel(first); check(cancelled.get() == 1);
        fails("REQUEST_CANCELLED", ticket::check);
        registry.complete(ticket);
        fails("DUPLICATE_REQUEST_ID", () -> registry.register(first));
        now[0] += 75_001; RequestRegistry.Ticket reused = registry.register(first); registry.complete(reused);
        RequestRegistry.Ticket[] tickets = new RequestRegistry.Ticket[8];
        for (int i = 0; i < 8; i++) tickets[i] = registry.register(id());
        fails("TOO_MANY_REQUESTS", () -> registry.register(id()));
        registry.beginReset();
        fails("SESSION_RESET_IN_PROGRESS", registry::beginReset);
        for (RequestRegistry.Ticket value : tickets) fails("REQUEST_CANCELLED", value::check);
        fails("SESSION_RESET_IN_PROGRESS", () -> registry.register(id()));
        registry.endReset();
        for (RequestRegistry.Ticket value : tickets) registry.complete(value);
        String late = id(); RequestRegistry.Ticket lateTicket = registry.register(late); registry.cancel(late);
        lateTicket.attach(cancelled::incrementAndGet); check(cancelled.get() == 2); registry.complete(lateTicket);
        RequestRegistry bounded = new RequestRegistry(() -> 1);
        for (int i = 0; i < 256; i++) bounded.cancel(id());
        fails("CANCEL_QUEUE_FULL", () -> bounded.cancel(id()));
        RequestRegistry deadlineRegistry = new RequestRegistry(() -> now[0]);
        RequestRegistry.Ticket deadline = deadlineRegistry.register(id()); now[0] = deadline.deadline;
        fails("API_TIMEOUT", () -> deadlineRegistry.check(deadline)); deadlineRegistry.complete(deadline);

        Store store = new Store(); SessionState session = new SessionState(store);
        check(session.error() == null && store.writes == 1);
        String cookie = id(); session.persist(cookie); session.markBootstrapped(); check(session.bootstrapped());
        check(cookie.equals(new SessionState(store).cookie()));
        store.failure = "SESSION_STORE_WRITE_FAILED";
        fails("SESSION_STORE_WRITE_FAILED", () -> session.persist(id()));
        fails("SESSION_STORE_WRITE_FAILED", session::check);
        check(session.cookie() == null && !session.bootstrapped());
        store.failure = null; session.recover(); check(cookie.equals(session.cookie()));
        session.reset(); check(session.cookie() == null && store.cookie == null);
        store.cookie = "corrupt"; SessionState corrupt = new SessionState(store);
        check("SESSION_STORE_INVALID".equals(corrupt.error()));
        check("corrupt".equals(store.cookie)); // failed startup does not overwrite durable state
        fails("SESSION_STORE_INVALID", corrupt::recover);
        Store fixedStore = new Store(); SessionState fixed = new SessionState(fixedStore);
        fails("SESSION_COOKIE_MISSING", fixed::freeze);
        String original = id(); fixed.persist(original);
        SessionState.Fence frozen = fixed.freeze(); String binding = fixed.binding(frozen);
        check(binding.matches("[0-9a-f]{64}") && !binding.contains(original));
        fixed.persist(original); fixed.check(frozen); // unchanged durable cookie retains authority
        fixed.persist(id());
        fails("SESSION_CHANGED", () -> fixed.check(frozen));
        fixed.persist(original);
        fails("SESSION_CHANGED", () -> fixed.check(frozen)); // cookie A -> B -> A is still a new authority
        SessionState.Fence beforeReset = fixed.freeze(); fixed.reset(); fixed.persist(original);
        fails("SESSION_CHANGED", () -> fixed.check(beforeReset));
        check(binding.equals(fixed.binding(fixed.freeze())));
        RequestRegistry generations = new RequestRegistry(() -> 1);
        long frozenGeneration = generations.freezeGeneration(); generations.beginReset();
        fails("SESSION_RESET_IN_PROGRESS", () -> generations.checkGeneration(frozenGeneration));
        generations.endReset();
        fails("SESSION_CHANGED", () -> generations.checkGeneration(frozenGeneration));
        System.out.println("Native core checks passed: " + checks);
    }
}
