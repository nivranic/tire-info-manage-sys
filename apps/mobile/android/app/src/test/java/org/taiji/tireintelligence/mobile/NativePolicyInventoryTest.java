package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.junit.Test;

/** Pure JVM policy tests: no Android runtime, cookie store, HTTP or provider calls. */
public class NativePolicyInventoryTest {
    private static final String HEADER = "x-tire-expected-account";
    private static NativePolicy.Request request(String path, String method, Map<String, String> headers) throws NativeFailure {
        return NativePolicy.request(UUID.randomUUID().toString(), path, method, headers, null, bytes -> true);
    }
    private static void rejected(String path, String method, Map<String, String> headers) throws Exception {
        try { request(path, method, headers); fail("unexpected accepted native request"); }
        catch (NativeFailure failure) { assertTrue(failure.code.equals("INVALID_API_HEADER") || failure.code.equals("INVALID_API_METHOD")); }
    }

    @Test public void onlyCanonicalGetInventoryRoutesAcceptTheAccountHint() throws Exception {
        for (String path : new String[] {"/v1/api-keys/active", "/v1/api-key-history?mode=history&limit=20&cursor=opaque_-0"}) {
            for (String account : new String[] {"a", "Account_01-safe", "_", "-", "a".repeat(64)}) {
                NativePolicy.Request accepted = request(path, "GET", Map.of("X-Tire-Expected-Account", account));
                assertEquals(account, accepted.headers.get(HEADER));
                assertEquals(path, accepted.path);
            }
        }
    }

    @Test public void invalidAccountIdsAreRejectedWithoutTrimmingOrUnicodeFolding() throws Exception {
        for (String account : new String[] {"", "a".repeat(65), "a b", " leading", "trailing ", "a\t", "a\n", "a\r", "a.b", "a/b", "a,b", "a%20", "é", "账户", "😀"}) {
            rejected("/v1/api-keys/active?mode=history", "GET", Map.of(HEADER, account));
        }
    }

    @Test public void otherRoutesAndMethodsDoNotGainHeaderAccess() throws Exception {
        for (String path : new String[] {"/health", "/v1/api-keys", "/v1/api-keys/active/", "/v1/api-key-history/older", "/v1/api-key-history-extra", "/v1/api-keys/%61ctive", "/v1/%61pi-key-history", "/v1/api-keys?next=/v1/api-keys/active"}) {
            rejected(path, "GET", Map.of(HEADER, "account"));
        }
        for (String method : new String[] {"POST", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS"}) {
            rejected("/v1/api-key-history?mode=history", method, Map.of(HEADER, "account"));
        }
    }

    @Test public void duplicateCredentialsAndArbitraryHeadersRemainRejected() throws Exception {
        for (String name : new String[] {"X-Tire-Expected-Account", "Authorization", "Cookie", "Origin", "Host", "X-Unapproved"}) {
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put(HEADER, "account");
            headers.put(name, "account");
            rejected("/v1/api-keys/active?mode=history", "GET", headers);
        }
    }

    @Test public void threeHeaderCapAndGetBodyRejectionRemainInForce() throws Exception {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put(HEADER, "account");
        headers.put("Content-Type", "application/json");
        headers.put("Idempotency-Key", UUID.randomUUID().toString());
        assertEquals(3, request("/v1/api-keys/active?mode=history", "GET", headers).headers.size());
        try {
            NativePolicy.request(UUID.randomUUID().toString(), "/v1/api-keys/active?mode=history", "GET", headers, "e30=", bytes -> true);
            fail("GET body must remain blocked");
        } catch (NativeFailure failure) { assertEquals("INVALID_API_BODY", failure.code); }
        headers.put("X-Evidence-Metadata", "e30=");
        rejected("/v1/api-keys/active?mode=history", "GET", headers);
    }
}
