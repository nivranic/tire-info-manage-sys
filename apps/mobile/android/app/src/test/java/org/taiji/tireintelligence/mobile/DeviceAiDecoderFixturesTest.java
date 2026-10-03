package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;

/**
 * Replays the unified closed-decoder fixtures of
 * .artifacts/device-ai50/specs/decoder-fixtures-a/fixtures.json (decoder-spec
 * section 4.3-3 Root decision, M1-M10 matrix) through the Java Host decoder
 * layer named by each case's message:
 *
 *  - "prepare_body"     - payload -> DeviceAiHost.assertPrepareBody (the
 *                         DeviceAIPrepareRequest closed decoder);
 *  - "provider_consent" - payload wrapped as the provider_consent of a valid
 *                         DeviceAiHostClient.submitStream submission (the
 *                         ProviderConsent decode block), over a guard
 *                         transport so any dispatch attempt fails loudly.
 *
 * The observed jv outcome token is compared against expected.jv: a clean pass
 * is "accept" (a registered divergence when the verdict is reject), a
 * DeviceAiHostException carries its closed code (in practice
 * device_ai_host_invalid_argument), and the closed key-set fence throws
 * IllegalStateException with a message containing 'closed DTO' — recorded by
 * the fixtures as "closed_fields_error" (a plain programming error, not a
 * Host fence code). accept verdicts must carry null expectations and pass
 * clean (UUID canonicalization included).
 *
 * Fixture location: system property tire.test.decoderFixtures (absolute
 * path), else an upward search from the test working directory (the same
 * convention as DeviceAiJsonParserParityTest's E1 vector binding; Gradle's
 * ordinary Test working directory is the app project). Unlike the sealed E1
 * vectors the fixtures file is young (created in the same round this runner
 * lands), so its bytes are not pinned by SHA-256; the schema id
 * device-ai-decoder-fixtures@1, the counts block and the per-case expected
 * tokens bind instead.
 */
@RunWith(Parameterized.class)
public final class DeviceAiDecoderFixturesTest {
    private static final String FIXTURES_REPOSITORY_PATH = ".artifacts/device-ai50/specs/decoder-fixtures-a/fixtures.json";
    private static final String FIXTURES_SCHEMA = "device-ai-decoder-fixtures@1";
    private static final String CLOSED_FIELDS_TOKEN = "closed_fields_error";
    private static final String ACCEPT_TOKEN = "accept";
    /** Valid wrapper identity for the provider_consent path (submitStream inputs before the consent block). */
    private static final String WRAPPER_UUID = "123e4567-e89b-42d3-a456-426614174000";

    private static Map<String, JSONObject> cases;

    private final String id;

    public DeviceAiDecoderFixturesTest(String id) { this.id = id; }

    @Parameterized.Parameters(name = "{0}")
    public static List<String> caseIds() {
        loadFixtures();
        return new ArrayList<>(cases.keySet());
    }

    private static synchronized void loadFixtures() {
        if (cases != null) return;
        try { loadFixturesChecked(); }
        catch (Exception failure) { throw new IllegalStateException("decoder fixtures binding failed", failure); }
    }

    private static void loadFixturesChecked() throws Exception {
        if (cases != null) return;
        Path path = locate();
        byte[] raw;
        try { raw = Files.readAllBytes(path); }
        catch (Exception unreadable) { throw new IllegalStateException("decoder fixtures unreadable: " + path, unreadable); }
        JSONObject document = new JSONObject(new String(raw, StandardCharsets.UTF_8));
        assertEquals("decoder fixtures schema", FIXTURES_SCHEMA, document.getString("schema"));
        JSONArray list = document.getJSONArray("cases");
        assertTrue("decoder fixtures must carry at least one case", list.length() > 0);
        cases = new LinkedHashMap<>();
        int accepted = 0, rejected = 0;
        for (int at = 0; at < list.length(); at++) {
            JSONObject fixture = list.getJSONObject(at);
            String caseId = fixture.getString("id");
            assertNull("duplicate decoder fixture id " + caseId, cases.put(caseId, fixture));
            String verdict = fixture.getString("verdict");
            if ("accept".equals(verdict)) accepted++;
            else if ("reject".equals(verdict)) rejected++;
            else throw new IllegalStateException("unknown verdict in fixture " + caseId + ": " + verdict);
        }
        JSONObject counts = document.getJSONObject("counts");
        assertEquals("case total must match the file's own counts", counts.getInt("total"), list.length());
        assertEquals("accepted count", counts.getInt("accept"), accepted);
        assertEquals("rejected count", counts.getInt("reject"), rejected);
        System.out.println("decoder fixtures bound: " + path + " (" + list.length() + " cases, "
            + accepted + " accept / " + rejected + " reject)");
    }

    private static Path locate() {
        List<Path> candidates = new ArrayList<>();
        String configured = System.getProperty("tire.test.decoderFixtures");
        if (configured != null) candidates.add(Path.of(configured));
        Path directory = Path.of("").toAbsolutePath();
        for (int up = 0; up <= 8 && directory != null; up++) {
            candidates.add(directory.resolve(FIXTURES_REPOSITORY_PATH).normalize());
            directory = directory.getParent();
        }
        for (Path candidate : candidates) if (Files.isRegularFile(candidate)) return candidate;
        throw new IllegalStateException("decoder fixture file not found above the working directory; pass -Dtire.test.decoderFixtures=<path>");
    }

    @Test public void replayCase() throws Exception {
        JSONObject fixture = cases.get(id);
        assertNotNull("decoder fixture " + id + " missing", fixture);
        JSONObject payload = fixture.getJSONObject("payload");
        boolean acceptVerdict = "accept".equals(fixture.getString("verdict"));
        JSONObject expected = fixture.optJSONObject("expected");
        String expectedOutcome;
        if (acceptVerdict) {
            // accept 时四端 expectation 恒 null。
            assertTrue(id + " accept case must carry a null jv expectation", expected == null || expected.isNull("jv"));
            expectedOutcome = ACCEPT_TOKEN;
        } else {
            assertNotNull(id + " reject case must carry expected codes", expected);
            Object code = expected.opt("jv");
            assertTrue(id + " reject case must carry a non-null expected.jv", code instanceof String && !((String) code).isEmpty());
            expectedOutcome = (String) code;
        }

        String message = fixture.getString("message");
        String observed;
        switch (message) {
            case "prepare_body":
                try {
                    DeviceAiHost.assertPrepareBody(payload);
                    observed = ACCEPT_TOKEN;
                    if (acceptVerdict) {
                        // Optional canonicalization coverage: both UUIDs must
                        // canonicalize (uppercase/braced spellings accepted).
                        DeviceAiHost.canonicalUuid(payload.optString("host_receipt_id"));
                        DeviceAiHost.canonicalUuid(payload.optString("intent_id"));
                    }
                } catch (DeviceAiHost.DeviceAiHostException failure) {
                    observed = failure.code;
                } catch (IllegalStateException failure) {
                    // The closed key-set fence (assertClosedFields) throws a
                    // plain programming error whose message carries 'closed
                    // DTO'; anything else is an unexpected failure, not a
                    // fixture outcome.
                    assertTrue(id + " unexpected IllegalStateException: " + failure.getMessage(),
                        failure.getMessage() != null && failure.getMessage().contains("closed DTO"));
                    observed = CLOSED_FIELDS_TOKEN;
                }
                break;
            case "provider_consent":
                DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(
                    (method, path, headers, body) -> {
                        throw new AssertionError(id + ": consent decode must reject before any dispatch");
                    });
                JSONObject submission = new JSONObject();
                submission.put("pack_id", "pack-1");
                submission.put("question", "consent fixture wrapper question");
                submission.put("prepare_id", "prep-1");
                submission.put("host_receipt_id", WRAPPER_UUID);
                submission.put("device_context_fingerprint", "03".repeat(32));
                submission.put("provider_consent", payload);
                try {
                    client.submitStream(submission, WRAPPER_UUID);
                    observed = ACCEPT_TOKEN;
                } catch (DeviceAiHost.DeviceAiHostException failure) {
                    observed = failure.code;
                } catch (IllegalStateException failure) {
                    assertTrue(id + " unexpected IllegalStateException: " + failure.getMessage(),
                        failure.getMessage() != null && failure.getMessage().contains("closed DTO"));
                    observed = CLOSED_FIELDS_TOKEN;
                }
                break;
            default:
                throw new IllegalStateException(id + ": unknown message family " + message);
        }
        assertEquals(id + " observed jv decoder outcome", expectedOutcome, observed);
    }
}
