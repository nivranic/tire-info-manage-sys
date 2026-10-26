package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.Test;

/** Pure policy checks only; these do not start Android, HTTP, auth or a database. */
public class NativePolicyQuarantineReviewTest {
    private static final String ID = "123e4567-e89b-42d3-a456-426614174000";
    private static final String HEADER = "x-tire-expected-account";
    private static final String PATH = "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2";
    private static NativePolicy.Request request(String path, String method, Map<String, String> headers, String body) throws NativeFailure {
        return NativePolicy.request(ID, path, method, headers, body, bytes -> true);
    }
    private static void rejected(String path, String method, Map<String, String> headers) throws Exception {
        try { request(path, method, headers, null); fail("unexpected accepted native request"); }
        catch (NativeFailure failure) {
            assertTrue(failure.code, failure.code.equals("INVALID_API_HEADER") || failure.code.equals("INVALID_API_METHOD") || failure.code.equals("INVALID_API_PATH"));
        }
    }

    @Test public void exactPostPreservesRawPathAccountAndJsonBytes() throws Exception {
        String json = "{\"action\":\"approve\",\"expected_revision\":0,\"operator\":\"复核员\",\"reason\":\"证据已核对\",\"confirmed_loss\":true,\"expected_binding_hash\":\"" + "a".repeat(64) + "\"}";
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        for (String id : new String[] {"q", "Quarantine_01-safe", "_", "-", "q".repeat(64)}) {
            String path = "/v1/quarantines/" + id + "/reviews?mode=history&format=raw-evidence-v2";
            for (String account : new String[] {"a", "Account_01-safe", "_", "-", "a".repeat(64)}) {
                Map<String, String> headers = new LinkedHashMap<>();
                headers.put("X-Tire-Expected-Account", account);
                headers.put("Content-Type", "application/json");
                headers.put("Idempotency-Key", ID);
                NativePolicy.Request accepted = request(path, "POST", headers, Base64.getEncoder().encodeToString(body));
                assertEquals("POST", accepted.method);
                assertEquals(path, accepted.path);
                assertEquals(3, accepted.headers.size());
                assertEquals(account, accepted.headers.get(HEADER));
                assertEquals("application/json", accepted.headers.get("content-type"));
                assertEquals(ID, accepted.headers.get("idempotency-key"));
                assertArrayEquals(body, accepted.body);
            }
        }
    }

    @Test public void rawPathQueryAliasesAndOtherMethodsCannotCarryTheHint() throws Exception {
        for (String path : new String[] {
                "/v1/quarantines/q/reviews",
                "/v1/quarantines/q/review?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/q/reviews/?mode=history&format=raw-evidence-v2",
                "/v1/quarantines//reviews?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/q.extra/reviews?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/账户/reviews?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/q/other/reviews?mode=history&format=raw-evidence-v2",
                "/v1/%71uarantines/q/reviews?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/%71/reviews?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/q/%72eviews?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/q%2Fother/reviews?mode=history&format=raw-evidence-v2",
                "/v1/quarantines/q/reviews?format=raw-evidence-v2&mode=history",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&extra=1",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&mode=history",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&format=raw-evidence-v2",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2?",
                "/v1/quarantines/q/reviews?mode=%68istory&format=raw-evidence-v2",
                "/v1/quarantines/q/reviews?%6dode=history&format=raw-evidence-v2",
                "/v1/quarantines/q/reviews?mode=history&format=raw%2Devidence-v2",
                "/v1/quarantines/q/reviews?mode=history%26format%3Draw-evidence-v2",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2\n",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2#fragment",
                "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v1",
                "/v1/quarantines/" + "q".repeat(65) + "/reviews?mode=history&format=raw-evidence-v2"}) {
            rejected(path, "POST", Map.of(HEADER, "account"));
        }
        for (String method : new String[] {"GET", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS", "post"}) {
            rejected(PATH, method, Map.of(HEADER, "account"));
        }
    }

    @Test public void badAccountValuesDuplicatesAndCredentialHeadersRemainRejected() throws Exception {
        for (String account : new String[] {"", "a".repeat(65), "a b", " leading", "trailing ", "a\t", "a\n", "a\r", "a.b", "a/b", "a,b", "a%20", "é", "账户", "😀"}) {
            rejected(PATH, "POST", Map.of(HEADER, account));
        }
        for (String name : new String[] {"X-Tire-Expected-Account", "Authorization", "Cookie", "Origin", "Host", "X-Unapproved"}) {
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put(HEADER, "account");
            headers.put(name, "account");
            rejected(PATH, "POST", headers);
        }
    }

    @Test public void fourthHeaderAndMissingContentTypeRemainRejected() throws Exception {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put(HEADER, "account");
        headers.put("Content-Type", "application/json");
        headers.put("Idempotency-Key", ID);
        assertEquals(3, request(PATH, "POST", headers, "e30=").headers.size());
        headers.put("X-Evidence-Metadata", "e30=");
        rejected(PATH, "POST", headers);
        try {
            request(PATH, "POST", Map.of(HEADER, "account"), "e30=");
            fail("body still requires content type");
        } catch (NativeFailure failure) { assertEquals("INVALID_API_BODY", failure.code); }
        try {
            request(PATH, "GET", Map.of("Content-Type", "application/json"), "e30=");
            fail("GET body must remain blocked");
        } catch (NativeFailure failure) { assertEquals("INVALID_API_BODY", failure.code); }
    }

    @Test public void missingHintAndLegacyTextRequestsStillReachTheBackendPolicyBoundary() throws Exception {
        for (String path : new String[] {PATH, "/v1/quarantines/q/reviews", "/v1/quarantines/q/reviews?mode=history"}) {
            NativePolicy.Request accepted = request(path, "POST", Map.of("Content-Type", "application/json"), "e30=");
            assertEquals(path, accepted.path);
            assertFalse(accepted.headers.containsKey(HEADER));
            assertArrayEquals("{}".getBytes(StandardCharsets.UTF_8), accepted.body);
        }
    }
}
