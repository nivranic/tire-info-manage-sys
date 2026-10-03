package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.Test;

/**
 * JVM replay of the device-ai Host SDK selftest
 * (.artifacts/device-ai50/host-sdk-selftest/device-ai-host-selftest.mts) against
 * the Java Host wiring DeviceAiHost:
 *
 *  - question trim-once + bare sha256 parity against the Python reference
 *    digests in host-expected-fingerprints.json (file bytes pinned by SHA-256,
 *    same binding convention as DeviceAiJsonParserParityTest);
 *  - selection_sha256 / device_context_fingerprint / local_preview_fingerprint
 *    parity with the same Python reference vectors (fingerprint-spec 2/3/4);
 *  - computeLocalPreview over a mini envelope (positive + fail-closed);
 *  - DeviceAiJournal five fences: append/readAll/verify + tamper + chain break
 *    + clock regression + owner/generation/session fences + wrong-key corrupt;
 *  - DeviceAiHostClient over an in-memory transport fake: paths, Idempotency-Key
 *    canonicalization, closed request bodies (field names AND key order),
 *    error passthrough, response checks;
 *  - resolveUnknownOutcome (N18): lookup-first, never resubmit.
 *
 * The AES-GCM journal runs on an injected software key (the AndroidKeyStore
 * sealer is device-only), exactly like the TS sibling where the Web host
 * injects a non-extractable CryptoKey.
 */
public final class DeviceAiHostTest {
    private static final String FINGERPRINTS_REPOSITORY_PATH =
        ".artifacts/device-ai50/host-sdk-selftest/host-expected-fingerprints.json";
    private static final String FINGERPRINTS_SHA256 =
        "8f8cf08b39cf978fc326ebfb7d94c14ad4b1bfec1519da4395aa2e60b7aa0160";

    // Shared mini inputs - must stay in lockstep with device-ai-host-selftest.mts
    // and gen-expected-fingerprints.py.
    private static final String MK_A = "ab".repeat(32), MK_B = "cd".repeat(32);
    private static final String QUESTION = "P225 这条轮胎的历史参数如何解析？";
    private static final String SOURCE_JSON =
        "{\"source_id\":\"src-1\",\"observed_at\":\"2026-01-01T00:00:00Z\",\"verified_at\":null,"
            + "\"verification_id\":\"ver-1\",\"load_index_9007199254740993\":9007199254740993,"
            + "\"pressure\":0.1000000000000000001,\"negative_zero\":-0}";
    private static final String KEY_CANONICAL = "9999aaaa-bbbb-4ccc-8ddd-5555eee66666";

    private static JSONObject document;

    private static synchronized JSONObject expected() {
        if (document != null) return document;
        Path path = locate();
        byte[] raw;
        try { raw = Files.readAllBytes(path); }
        catch (Exception unreadable) { throw new IllegalStateException("fingerprint vectors unreadable: " + path, unreadable); }
        String actual;
        try { actual = sha256Hex(raw); }
        catch (Exception failure) { throw new IllegalStateException("digest failed", failure); }
        assertEquals("expected fingerprints sha256 drift: " + path, FINGERPRINTS_SHA256, actual);
        document = parseJson(raw);
        assertEquals("device-ai-host-expected-fingerprints@1", document.optString("schema"));
        System.out.println("host fingerprints bound: " + path + " (sha256 " + FINGERPRINTS_SHA256 + ")");
        return document;
    }

    private static Path locate() {
        List<Path> candidates = new ArrayList<>();
        String configured = System.getProperty("tire.test.hostFingerprints");
        if (configured != null) candidates.add(Path.of(configured));
        Path directory = Path.of("").toAbsolutePath();
        for (int up = 0; up <= 8 && directory != null; up++) {
            candidates.add(directory.resolve(FINGERPRINTS_REPOSITORY_PATH).normalize());
            directory = directory.getParent();
        }
        for (Path candidate : candidates) if (Files.isRegularFile(candidate)) return candidate;
        throw new IllegalStateException("fingerprint vector file not found above the working directory; pass -Dtire.test.hostFingerprints=<path>");
    }

    private static String sha256Hex(byte[] data) throws Exception {
        StringBuilder out = new StringBuilder(64);
        for (byte value : MessageDigest.getInstance("SHA-256").digest(data))
            out.append(String.format("%02x", value & 255));
        return out.toString();
    }

    // ---------------------------------------------------------------------
    // fixtures and small helpers
    // ---------------------------------------------------------------------

    private static JSONObject json(Object... pairs) {
        JSONObject value = new JSONObject();
        for (int at = 0; at + 1 < pairs.length; at += 2)
            put(value, (String) pairs[at], pairs[at + 1] == null ? JSONObject.NULL : pairs[at + 1]);
        return value;
    }

    /** Unchecked bridges: android.jar's org.json declares checked JSONException; the test artifact does not. */
    private static JSONObject put(JSONObject target, String key, Object value) {
        try { return target.put(key, value); } catch (JSONException invalid) { throw new IllegalStateException(invalid); }
    }

    private static JSONArray put(JSONArray target, Object value) {
        return target.put(value); // put(Object) declares no checked exception on either org.json
    }

    private static JSONObject parseJson(byte[] bytes) {
        try { return new JSONObject(new String(bytes, StandardCharsets.UTF_8)); }
        catch (JSONException invalid) { throw new IllegalStateException(invalid); }
    }

    private static JSONArray selectors(JSONObject... items) {
        JSONArray out = new JSONArray();
        for (JSONObject item : items) put(out, item);
        return out;
    }

    private static JSONObject selector(String memberKey, String documentId, String snapshot, String variant, String verification) {
        return json("kind", "tire", "member_key", memberKey, "document_id", documentId, "record_index", null,
            "reference", json("kind", "tire", "snapshot_id", snapshot, "variant_id", variant, "verification_id", verification));
    }

    private static JSONObject selectorA() { return selector(MK_A, null, "snap-1", "var-1", "ver-1"); }
    private static JSONObject selectorB() { return selector(MK_B, "doc-2", "snap-2", "var-2", "ver-2"); }

    // ---------------------------------------------------------------------
    // P1-4c four-domain fixtures (TS selftest section I parity: vehicle /
    // recall / recall_search wire shapes over the same closed DTO semantics).
    // ---------------------------------------------------------------------

    private static JSONObject domainSelector(String kind, String memberKey, String documentId, Object recordIndex, JSONObject reference) {
        return json("kind", kind, "member_key", memberKey, "document_id", documentId, "record_index", recordIndex,
            "reference", reference);
    }

    private static JSONObject vehicleSelector() {
        return domainSelector("vehicle", "0a".repeat(32), null, null,
            json("kind", "vehicle", "snapshot_id", "snap-v", "verification_id", "ver-v"));
    }

    private static JSONObject recallSelector(String revision, String documentId, Object recordIndex) {
        return domainSelector("recall", "0d".repeat(32), documentId, recordIndex,
            json("kind", "recall", "snapshot_id", "snap-r", "recall_revision_id", revision, "verification_id", "ver-r"));
    }

    private static JSONObject recallSearchSelector(Object recordIndex) {
        return domainSelector("recall_search", "0b".repeat(32), "doc-rs", recordIndex,
            json("kind", "recall_search", "snapshot_id", "snap-rs", "verification_id", "ver-rs"));
    }

    private static JSONObject prepareBodyWith(String projectionMode, Object selectorsValue, Object approvedClosure) {
        JSONObject body = prepareBodyFixture();
        put(body, "projection_mode", projectionMode);
        put(body, "selectors", selectorsValue);
        put(body, "approved_closure", approvedClosure == null ? JSONObject.NULL : approvedClosure);
        return body;
    }

    private static JSONObject origin() {
        return json("expected_profile_id", "11111111-2222-4333-8444-555555555555",
            "expected_owner_epoch", 1L, "slot_id", "slot-1", "expected_generation", 2L,
            "package_id", "pkg-1", "expected_sha256", "ef".repeat(32), "expected_byte_count", 1234L,
            "owner_scope_id", "9a".repeat(32), "package_schema", "offline-pack@2");
    }

    private interface ThrowingRunnable { void run() throws Exception; }

    private static void assertHostFail(String code, ThrowingRunnable action) {
        try {
            action.run();
            fail("expected DeviceAiHostException " + code);
        } catch (DeviceAiHost.DeviceAiHostException error) {
            assertEquals(code, error.code);
        } catch (Exception error) {
            throw new AssertionError("unexpected exception type", error);
        }
    }

    private static void assertClosedFail(ThrowingRunnable action) {
        try {
            action.run();
            fail("expected closed-DTO IllegalStateException");
        } catch (IllegalStateException expected) {
            assertTrue("closed DTO message: " + expected.getMessage(), expected.getMessage().contains("closed DTO"));
        } catch (Exception error) {
            throw new AssertionError("unexpected exception type", error);
        }
    }

    /** TS selftest asserts fence violations with `.some(...)`; mirror that with containment. */
    private static List<String> violationCodes(DeviceAiHost.JournalVerification verification) {
        List<String> codes = new ArrayList<>();
        for (String[] violation : verification.violations) codes.add(violation[0]);
        return codes;
    }

    // ---------------------------------------------------------------------
    // in-memory fakes (no JVM HTTP-mock convention exists in this source set)
    // ---------------------------------------------------------------------

    static final class SoftwareSealer implements DeviceAiHost.Sealer {
        private final SecretKey key;
        SoftwareSealer(SecretKey key) { this.key = key; }
        static SoftwareSealer fresh() throws Exception {
            KeyGenerator generator = KeyGenerator.getInstance("AES");
            generator.init(256);
            return new SoftwareSealer(generator.generateKey());
        }
        @Override public byte[] seal(byte[] clear, byte[] aad) throws Exception {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key);
            cipher.updateAAD(aad);
            byte[] iv = cipher.getIV(), ciphertext = cipher.doFinal(clear);
            byte[] out = new byte[12 + ciphertext.length];
            System.arraycopy(iv, 0, out, 0, 12);
            System.arraycopy(ciphertext, 0, out, 12, ciphertext.length);
            return out;
        }
        @Override public byte[] open(byte[] sealed, byte[] aad) throws Exception {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, Arrays.copyOfRange(sealed, 0, 12)));
            cipher.updateAAD(aad);
            return cipher.doFinal(sealed, 12, sealed.length - 12);
        }
    }

    static final class MemoryStore implements DeviceAiHost.Store {
        byte[] blob;
        @Override public byte[] load() { return blob == null ? null : blob.clone(); }
        @Override public void save(byte[] value) { blob = value.clone(); }
    }

    static final class FakeTransport implements DeviceAiHost.Transport {
        static final class Call {
            final String method, path;
            final Map<String, String> headers;
            final byte[] body;
            Call(String method, String path, Map<String, String> headers, byte[] body) {
                this.method = method; this.path = path; this.headers = headers; this.body = body;
            }
        }
        interface Responder { DeviceAiHost.HttpExchange respond(Call call) throws Exception; }
        final List<Call> calls = new ArrayList<>();
        Responder responder;
        @Override public DeviceAiHost.HttpExchange exchange(String method, String path, Map<String, String> headers, byte[] body) throws Exception {
            Call call = new Call(method, path, new LinkedHashMap<>(headers), body);
            calls.add(call);
            return responder.respond(call);
        }
        Call last() { return calls.get(calls.size() - 1); }
    }

    private static DeviceAiHost.HttpExchange jsonResponse(int status, JSONObject body) {
        return new DeviceAiHost.HttpExchange(status, body.toString().getBytes(StandardCharsets.UTF_8));
    }

    private static JSONObject prepareViewFixture(JSONObject prepareBody) {
        return json("id", "prep-1", "created_at", "2026-10-02T12:00:00Z", "expires_at", "2026-10-02T12:30:00Z",
            "expired", false, "idempotency_key", KEY_CANONICAL, "host_receipt_id", prepareBody.optString("host_receipt_id"),
            "intent_id", prepareBody.optString("intent_id"), "pack_id", "pack-1", "offline_pack_id", "pkg-1",
            "question_sha256", prepareBody.optString("question_sha256"), "selection_sha256", "02".repeat(32),
            "projection_sha256", "99".repeat(32), "projection_byte_count", 1000L,
            "device_context_fingerprint", "03".repeat(32), "request_hash", "04".repeat(32),
            "contract", json(), "pack", json(), "replayed", false,
            "provider_preview", json("model", json("provider", "openai_responses")));
    }

    private static JSONObject streamDetailFixture() {
        return json("schema", "ai-streams@1", "scope", "session",
            "execution", json("state", "accepted", "terminal", false, "deadline_at", "2026-10-02T12:30:00Z",
                "last_event_at", null, "projection_only", false),
            "cursor", "cursor-1", "server_time", "2026-10-02T12:00:00Z",
            "analysis", json("id", "req-1", "pack_id", "pack-1", "question", "问题", "provider", "openai_responses",
                "model", "m-1", "created_at", "2026-10-02T12:00:00Z", "completed_at", null, "state", "pending",
                "reserved_tokens", 100L, "usage", null, "error_code", null, "answer", null),
            "draft_claims", new JSONArray(), "draft_uncertainty", null, "replayed", false);
    }

    private static JSONObject prepareBodyFixture() {
        return json("package_id", "pkg-1", "expected_sha256", "ef".repeat(32), "expected_byte_count", 1234L,
            "expected_schema", "offline-pack@2", "expected_owner_scope_id", "9a".repeat(32),
            "selectors", selectors(selectorA()), "projection_mode", "single_observation",
            "approved_closure", null, "expected_projection_sha256", "99".repeat(32), "question_sha256", "01".repeat(32),
            "host_receipt_id", "11111111-2222-4333-8444-555555555555",
            "intent_id", "22222222-3333-4444-8555-666666666666");
    }

    private static JSONObject consentFixture() {
        return json("expected_pack_fingerprint", "aa".repeat(32), "expected_device_context_fingerprint", "03".repeat(32),
            "question_sha256", expected().optJSONObject("question_sha256").optString(QUESTION),
            "provider", "openai_responses", "model", "m-1", "expected_provider_policy_fingerprint", "05".repeat(32));
    }

    // journal test helpers (unseal/reseal under the software key, TS selftest F/H parity)

    private static byte[] journalAad(String owner) {
        List<Object> binding = new ArrayList<>();
        binding.add(DeviceAiHost.JOURNAL_SCHEMA);
        binding.add(owner);
        return DeviceAiJsonParser.canonicalBytes(binding);
    }

    private static JSONObject unsealWire(MemoryStore store, SoftwareSealer sealer) throws Exception {
        JSONObject wire = new JSONObject(new String(store.blob, StandardCharsets.UTF_8));
        String ivHex = wire.getString("iv_hex");
        byte[] nonce = new byte[12];
        for (int at = 0; at < 12; at++) nonce[at] = (byte) Integer.parseInt(ivHex.substring(at * 2, at * 2 + 2), 16);
        byte[] ciphertext = java.util.Base64.getDecoder().decode(wire.getString("ciphertext_base64"));
        byte[] sealed = new byte[12 + ciphertext.length];
        System.arraycopy(nonce, 0, sealed, 0, 12);
        System.arraycopy(ciphertext, 0, sealed, 12, ciphertext.length);
        byte[] plaintext = sealer.open(sealed, journalAad(wire.getString("owner")));
        JSONObject entries = new JSONObject(new String(plaintext, StandardCharsets.UTF_8));
        JSONObject out = DeviceAiHost.copyOf(wire);
        out.put("entries", entries.getJSONArray("entries"));
        return out;
    }

    private static void resealWire(MemoryStore store, JSONObject wire, JSONArray entries, SoftwareSealer sealer) throws Exception {
        byte[] plaintext = json("entries", entries).toString().getBytes(StandardCharsets.UTF_8);
        byte[] sealed = sealer.seal(plaintext, journalAad(wire.getString("owner")));
        StringBuilder ivHex = new StringBuilder(24);
        for (byte value : Arrays.copyOfRange(sealed, 0, 12))
            ivHex.append(String.format("%02x", value & 255));
        JSONObject blob = json("schema", wire.getString("schema"), "owner", wire.getString("owner"),
            "generation", wire.getLong("generation"), "iv_hex", ivHex.toString(),
            "ciphertext_base64", java.util.Base64.getEncoder().encodeToString(Arrays.copyOfRange(sealed, 12, sealed.length)));
        store.save(blob.toString().getBytes(StandardCharsets.UTF_8));
    }

    /** Wire bytes keep document order through the strict parser (org.json map order is not contractual). */
    private static Map<?, ?> wireAst(byte[] body) {
        Object parsed = DeviceAiJsonParser.parse(body);
        assertTrue(parsed instanceof Map);
        return (Map<?, ?>) parsed;
    }

    private static List<String> mapKeys(Map<?, ?> value) {
        List<String> keys = new ArrayList<>();
        for (Object key : value.keySet()) keys.add((String) key);
        return keys;
    }

    // ---------------------------------------------------------------------
    // B. question trim-once + sha256 parity (Python reference digests)
    // ---------------------------------------------------------------------

    @Test
    public void questionTrimOnceMatchesPinnedWhitespaceSet() {
        assertEquals("历史问题", DeviceAiHost.trimOnceQuestion("  历史问题  "));
        assertEquals("历史问题", DeviceAiHost.trimOnceQuestion("　历史问题\u000B"));
        assertEquals("问题  内容", DeviceAiHost.trimOnceQuestion("问题  内容"));
        assertEquals("问题   内容", DeviceAiHost.trimOnceQuestion("   问题   内容   "));
        assertEquals("问题", DeviceAiHost.trimOnceQuestion("\u001c问题\u001c"));
        assertEquals("\ufeff问题", DeviceAiHost.trimOnceQuestion("\ufeff问题"));
    }

    @Test
    public void normalizeQuestionCountsCodepointsNotUnits() {
        assertEquals("ab", DeviceAiHost.normalizeQuestion("ab"));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.normalizeQuestion("a"));
        assertEquals("𐀀".repeat(2000), DeviceAiHost.normalizeQuestion("𐀀".repeat(2000)));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.normalizeQuestion("𐀀".repeat(2001)));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.normalizeQuestion("𐀀𐀀".repeat(1001)));
    }

    @Test
    public void questionSha256ParityAgainstPythonReference() throws Exception {
        JSONObject vectors = expected().getJSONObject("question_sha256");
        for (String question : DeviceAiHost.keyNames(vectors))
            assertEquals("question digest drift for " + question.substring(0, Math.min(12, question.length())),
                vectors.getString(question), DeviceAiHost.questionSha256(question));
        // NFKC must not be applied; lookalike and fullwidth pairs must differ.
        assertNotEquals(DeviceAiHost.questionSha256("ﬃ 轮胎历史"), DeviceAiHost.questionSha256("ffi 轮胎历史"));
        assertNotEquals(DeviceAiHost.questionSha256("２０００ 年"), DeviceAiHost.questionSha256("2000 年"));
        // no JSON quoting wrapper
        assertNotEquals(DeviceAiHost.questionSha256("text"), DeviceAiHost.questionSha256("\"text\""));
    }

    // ---------------------------------------------------------------------
    // C. fingerprint parity vs Python reference.
    // ---------------------------------------------------------------------

    @Test
    public void selectionSha256SortsByMemberKeyAndMatchesPython() {
        String expected = expected().optString("selection_sha256");
        // request order (B first) must not matter - spec sorts by member_key.
        assertEquals(expected, DeviceAiHost.selectionSha256(selectors(selectorB(), selectorA())));
        assertEquals(expected, DeviceAiHost.selectionSha256(selectors(selectorA(), selectorB())));
        assertHostFail("device_ai_host_invalid_argument",
            () -> DeviceAiHost.selectionSha256(selectors(selectorA(), selectorA())));
    }

    @Test
    public void deviceContextFingerprintPreservesNumericLexemes() throws Exception {
        Object source = DeviceAiJsonParser.parse(SOURCE_JSON.getBytes(StandardCharsets.UTF_8));
        JSONObject input = json("package_id", "pkg-1", "package_schema", "offline-pack@2",
            "package_sha256", "ef".repeat(32), "projection_mode", "single_observation",
            "projection_sha256", "99".repeat(32), "selection_sha256", "01".repeat(32),
            "receipt_sources", new JSONArray().put(json("selector", selectorA(), "selection_reason", "requested", "source", source)),
            "device_citations", new JSONArray(), "domain_boundaries", new JSONArray());
        assertEquals(expected().getString("device_context_fingerprint"), DeviceAiHost.deviceContextFingerprint(input));
    }

    @Test
    public void localPreviewFingerprintMatchesPythonAndBindsState() throws Exception {
        String questionHash = DeviceAiHost.questionSha256(QUESTION);
        JSONObject base = json("question_sha256", questionHash, "include_context_ids", new JSONArray(),
            "projection_mode", "single_observation", "query_context", null, "origin", origin(),
            "selected", new JSONArray().put(selectorB()), "resolved_closure", new JSONArray().put(selectorA()),
            "state", "ready", "projection_sha256", null);
        assertEquals(expected().getString("local_preview_fingerprint"), DeviceAiHost.localPreviewFingerprint(base));
        JSONObject blocked = DeviceAiHost.copyOf(base);
        blocked.put("state", "blocked");
        assertNotEquals("blocked vs ready must differ (state stays in the input)",
            DeviceAiHost.localPreviewFingerprint(blocked), DeviceAiHost.localPreviewFingerprint(base));
        // M4 (decoder-spec section 3): include_context_ids must stay EMPTY; a
        // non-empty list fails closed before entering the fingerprint AST.
        JSONObject withIds = DeviceAiHost.copyOf(base);
        put(withIds, "include_context_ids", new JSONArray().put("archive-1"));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.localPreviewFingerprint(withIds));
    }

    // ---------------------------------------------------------------------
    // C2. P1-4c four-domain selector/prepare-body semantics (TS selftest
    // section I parity: closed four-domain set, five prepare modes,
    // record_index rules, approved_closure fences, per-domain reference keys).
    // ---------------------------------------------------------------------

    @Test
    public void prepareBodyAcceptsFourOpenDomainsAndFiveModes() {
        // I14 vehicle-domain body under its locked converter mode.
        DeviceAiHost.assertPrepareBody(prepareBodyWith("complete_observation", selectors(vehicleSelector()), null));
        // recall domain: nullable recall_revision_id both spellings + record_index on the record path.
        DeviceAiHost.assertPrepareBody(prepareBodyWith("complete_formal_observation", selectors(recallSelector(null, null, null)), null));
        DeviceAiHost.assertPrepareBody(prepareBodyWith("complete_formal_observation",
            selectors(recallSelector("rev-9", "doc-r", 0L)), null));
        // I15 recall_search record selector under its locked mode.
        DeviceAiHost.assertPrepareBody(prepareBodyWith("candidate_page_context", selectors(recallSearchSelector(2L)), null));
        // tire single observation (existing fixture) and frozen closure with an approved list.
        DeviceAiHost.assertPrepareBody(prepareBodyWith("single_observation", selectors(selectorA()), null));
        DeviceAiHost.assertPrepareBody(prepareBodyWith("frozen_decision_closure",
            selectors(selectorA()), selectors(selectorA(), selectorB())));
    }

    @Test
    public void prepareBodyStaysClosedToTestEventAndCompleteEventContext() {
        JSONObject testEvent = domainSelector("test_event", "0c".repeat(32), null, null,
            json("kind", "test_event", "event_id", "evt-1", "event_revision", 1L));
        // I16 test_event selector stays closed on the prepare wire (N27).
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("complete_event_context", selectors(testEvent), null)));
        // test_event is closed even when the mode itself is an open one.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("single_observation", selectors(testEvent), null)));
        // I17 complete_event_context is not a prepare mode.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("complete_event_context", selectors(selectorA()), null)));
        // unknown mode strings stay closed.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("frozen_observation", selectors(selectorA()), null)));
    }

    @Test
    public void canonicalUuidAcceptsBracedUppercaseAndRejectsNonCanonical() {
        // Positive: uppercase and braced spellings normalize to canonical lowercase.
        assertEquals(KEY_CANONICAL, DeviceAiHost.canonicalUuid("9999AAAA-BBBB-4CCC-8DDD-5555EEE66666"));
        assertEquals(KEY_CANONICAL, DeviceAiHost.canonicalUuid("{" + KEY_CANONICAL + "}"));
        // M6 (decoder-spec section 3): UUID negative family — non-UUID shapes and
        // non-canonical spellings (no-hyphen / version 0 / variant c / separators)
        // fail closed (the server UUID() would accept the simple form — D1).
        for (String bad : new String[] {"", "not-a-uuid", "9999aaaa0bbbb0cccc0dddd055555eee66666",
            "9999aaaa-bbbb-0ccc-8ddd-5555eee66666", "9999aaaa-bbbb-4ccc-cddd-5555eee66666",
            "9999aaaa bbbb 4ccc 8ddd 5555eee66666"}) {
            String value = bad;
            assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.canonicalUuid(value));
        }
    }

    @Test
    public void prepareBodyRejectsWholeObservationRecordIndex() {
        // I18 tire selector with record_index rejected (whole-observation domain).
        JSONObject tireWithRecord = DeviceAiHost.copyOf(selectorA());
        put(tireWithRecord, "document_id", "doc-1");
        put(tireWithRecord, "record_index", 3L);
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("single_observation", selectors(tireWithRecord), null)));
        // I19 vehicle selector with record_index rejected.
        JSONObject vehicleWithRecord = DeviceAiHost.copyOf(vehicleSelector());
        put(vehicleWithRecord, "document_id", "doc-v");
        put(vehicleWithRecord, "record_index", 0L);
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("complete_observation", selectors(vehicleWithRecord), null)));
        // record-carrying domains reject out-of-range indices (StrictInt 0..3999).
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("candidate_page_context", selectors(recallSearchSelector(4000L)), null)));
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("candidate_page_context", selectors(recallSearchSelector(-1L)), null)));
    }

    @Test
    public void prepareBodyRejectsRecordIndexWithoutDocumentId() {
        // I20 '缺少 document_id 时不能携带 record_index' (model_validator).
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("complete_formal_observation", selectors(recallSelector(null, null, 1L)), null)));
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("candidate_page_context", selectors(recallSearchSelectorWithDocument(null, 1L)), null)));
    }

    private static JSONObject recallSearchSelectorWithDocument(String documentId, Object recordIndex) {
        return domainSelector("recall_search", "0b".repeat(32), documentId, recordIndex,
            json("kind", "recall_search", "snapshot_id", "snap-rs", "verification_id", "ver-rs"));
    }

    @Test
    public void prepareBodyCapacityAndDuplicateFences() {
        // I21 selector capacity 6 exceeded.
        JSONArray seven = new JSONArray();
        for (int index = 0; index < 7; index++) put(seven, with(selectorA(), "member_key", String.format("%064d", index).replace(' ', '0')));
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("single_observation", seven, null)));
        // I22 duplicate member keys rejected.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("single_observation", selectors(selectorA(), selectorA()), null)));
        // I23 approved_closure capacity 6 exceeded in closure mode.
        JSONArray closureSeven = new JSONArray();
        for (int index = 0; index < 7; index++) put(closureSeven, with(selectorA(), "member_key", String.format("%064d", index).replace(' ', '0')));
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("frozen_decision_closure", selectors(selectorA()), closureSeven)));
        // closure mode without an approved list stays closed.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("frozen_decision_closure", selectors(selectorA()), null)));
        // approved_closure forbidden outside closure mode.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("single_observation", selectors(selectorA()), selectors(selectorA()))));
        // I25 the per-selector prepare assertion is exported and closed
        // (tire stays a whole-observation domain even with document_id present).
        assertHostFail("device_ai_host_invalid_argument", () -> {
            JSONObject closed = with(selectorA(), "record_index", 1L);
            put(closed, "document_id", "doc-x");
            DeviceAiHost.assertDeviceAiPrepareSelector(closed);
        });
        // M8 (decoder-spec section 3): hash64 negative family — uppercase and
        // wrong-length spellings fail the closed-body assertion like the server 422.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(with(prepareBodyFixture(), "expected_sha256", "EF".repeat(32))));
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("single_observation",
                selectors(with(selectorA(), "member_key", "a".repeat(63))), null)));
    }

    @Test
    public void prepareBodyClosureItemsCarryClosedSelectorShape() {
        // I24 approved_closure items carry the same closed selector shape:
        // a tire closure item with record_index fails like a requested one.
        JSONObject invalidClosureItem = DeviceAiHost.copyOf(selectorA());
        put(invalidClosureItem, "document_id", "doc-x");
        put(invalidClosureItem, "record_index", 2L);
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("frozen_decision_closure", selectors(selectorA()), selectors(invalidClosureItem))));
        // a test_event closure item is equally closed.
        JSONObject testEvent = domainSelector("test_event", "0c".repeat(32), null, null,
            json("kind", "test_event", "event_id", "evt-1", "event_revision", 1L));
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("frozen_decision_closure", selectors(selectorA()), selectors(testEvent))));
        // D5 (decoder-spec 2.6): approved_closure member_key uniqueness — the
        // same fence as the requested selector list, at the decoder layer.
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.assertPrepareBody(prepareBodyWith("frozen_decision_closure",
                selectors(selectorA()), selectors(selectorB(), with(selectorA(), "member_key", MK_B)))));
    }

    @Test
    public void selectorAstCarriesPerDomainReferenceKeySets() {
        // vehicle: no variant_id, ids verbatim.
        assertEquals("{\"document_id\":null,\"kind\":\"vehicle\",\"member_key\":\"" + "0a".repeat(32)
                + "\",\"record_index\":null,\"reference\":{\"kind\":\"vehicle\",\"snapshot_id\":\"snap-v\",\"verification_id\":\"ver-v\"}}",
            DeviceAiJsonParser.canonical(DeviceAiHost.selectorAst(vehicleSelector())));
        // recall: explicitly nullable recall_revision_id, both spellings.
        assertEquals("{\"document_id\":null,\"kind\":\"recall\",\"member_key\":\"" + "0d".repeat(32)
                + "\",\"record_index\":null,\"reference\":{\"kind\":\"recall\",\"recall_revision_id\":null,\"snapshot_id\":\"snap-r\",\"verification_id\":\"ver-r\"}}",
            DeviceAiJsonParser.canonical(DeviceAiHost.selectorAst(recallSelector(null, null, null))));
        assertEquals("{\"document_id\":\"doc-r\",\"kind\":\"recall\",\"member_key\":\"" + "0d".repeat(32)
                + "\",\"record_index\":0,\"reference\":{\"kind\":\"recall\",\"recall_revision_id\":\"rev-9\",\"snapshot_id\":\"snap-r\",\"verification_id\":\"ver-r\"}}",
            DeviceAiJsonParser.canonical(DeviceAiHost.selectorAst(recallSelector("rev-9", "doc-r", 0L))));
        // recall_search record selector keeps its lexeme verbatim.
        assertEquals("{\"document_id\":\"doc-rs\",\"kind\":\"recall_search\",\"member_key\":\"" + "0b".repeat(32)
                + "\",\"record_index\":2,\"reference\":{\"kind\":\"recall_search\",\"snapshot_id\":\"snap-rs\",\"verification_id\":\"ver-rs\"}}",
            DeviceAiJsonParser.canonical(DeviceAiHost.selectorAst(recallSearchSelector(2L))));
        // test_event enters the digest layer (preview restricted-rejection) with a bounded revision lexeme.
        JSONObject testEvent = domainSelector("test_event", "0c".repeat(32), null, null,
            json("kind", "test_event", "event_id", "evt-1", "event_revision", 3L));
        assertEquals("{\"document_id\":null,\"kind\":\"test_event\",\"member_key\":\"" + "0c".repeat(32)
                + "\",\"record_index\":null,\"reference\":{\"event_id\":\"evt-1\",\"event_revision\":3,\"kind\":\"test_event\"}}",
            DeviceAiJsonParser.canonical(DeviceAiHost.selectorAst(testEvent)));

        // closed reference key sets: extra keys, missing per-kind keys and kind
        // mismatch all fail (fail-closed digests, never a silent key drift).
        JSONObject vehicleWithVariant = DeviceAiHost.copyOf(vehicleSelector());
        put(vehicleWithVariant, "reference", json("kind", "vehicle", "snapshot_id", "snap-v",
            "variant_id", "var-v", "verification_id", "ver-v"));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.selectorAst(vehicleWithVariant));
        JSONObject recallWithoutRevision = DeviceAiHost.copyOf(recallSelector(null, null, null));
        put(recallWithoutRevision, "reference", json("kind", "recall", "snapshot_id", "snap-r", "verification_id", "ver-r"));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.selectorAst(recallWithoutRevision));
        JSONObject kindMismatch = DeviceAiHost.copyOf(vehicleSelector());
        put(kindMismatch, "reference", json("kind", "tire", "snapshot_id", "snap-v", "variant_id", "v", "verification_id", "ver-v"));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.selectorAst(kindMismatch));
        // test_event revision bounds (1..2^31-1) hold at the digest layer.
        JSONObject badRevision = DeviceAiHost.copyOf(testEvent);
        put(badRevision, "reference", json("kind", "test_event", "event_id", "evt-1", "event_revision", 0L));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.selectorAst(badRevision));
    }

    @Test
    public void selectionSha256SortsMixedDomainClosuresAndAllowsExpansionTo200() {
        // Mixed-domain resolved closure: request order must not matter (member_key sort).
        String ab = DeviceAiHost.selectionSha256(selectors(selectorB(), vehicleSelector(), selectorA()));
        String ba = DeviceAiHost.selectionSha256(selectors(vehicleSelector(), selectorA(), selectorB()));
        assertEquals(ab, ba);
        // duplicate member keys across domains still rejected.
        JSONObject vehicleAsA = with(vehicleSelector(), "member_key", MK_A);
        assertHostFail("device_ai_host_invalid_argument", () ->
            DeviceAiHost.selectionSha256(selectors(selectorA(), vehicleAsA)));
        // resolved closure may expand to the pack member bound 200 (requested selectors stay <= 6).
        JSONArray expanded = new JSONArray();
        for (int index = 0; index < 200; index++)
            put(expanded, with(selectorA(), "member_key", String.format("%064d", index).replace(' ', '0')));
        assertEquals(64, DeviceAiHost.selectionSha256(expanded).length());
        JSONArray tooMany = new JSONArray();
        for (int index = 0; index < 201; index++)
            put(tooMany, with(selectorA(), "member_key", String.format("%064d", index).replace(' ', '0')));
        JSONArray finalTooMany = tooMany;
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.selectionSha256(finalTooMany));
    }

    // ---------------------------------------------------------------------
    // E. computeLocalPreview over a mini envelope.
    // ---------------------------------------------------------------------

    @Test
    public void computeLocalPreviewRecalculatesThreeFingerprints() throws Exception {
        JSONObject envelope = json("schema", "offline-pack@2", "package_id", "pkg-1",
            "owner_scope_id", "9a".repeat(32),
            "members", new JSONArray()
                .put(json("member_key", MK_A, "reference", selectorA().getJSONObject("reference")))
                .put(json("member_key", MK_B, "reference", selectorB().getJSONObject("reference"))));
        byte[] bytes = envelope.toString().getBytes(StandardCharsets.UTF_8);
        String realSha = sha256Hex(bytes);
        JSONObject origin = DeviceAiHost.copyOf(origin());
        origin.put("expected_byte_count", (long) bytes.length);
        origin.put("expected_sha256", realSha);

        JSONObject summary = DeviceAiHost.computeLocalPreview(bytes,
            json("question", "  " + QUESTION + "  ", "selectors", new JSONArray().put(selectorA()), "origin", origin));
        assertEquals(List.of(MK_A), stringsOf(summary.getJSONArray("located_member_keys")));
        assertEquals(bytes.length, summary.getLong("package_byte_count"));
        assertEquals("offline-pack@2", summary.getString("package_schema"));
        assertEquals(expected().getJSONObject("question_sha256").getString(QUESTION), summary.getString("question_sha256"));
        assertEquals(DeviceAiHost.selectionSha256(new JSONArray().put(selectorA())), summary.getString("selection_sha256"));
        assertEquals("not_recomputed", summary.getString("projection_binding"));
        // self-consistent with an independent localPreviewFingerprint call
        JSONObject independent = json("question_sha256", summary.getString("question_sha256"),
            "include_context_ids", new JSONArray(), "projection_mode", "single_observation", "query_context", null,
            "origin", origin, "selected", new JSONArray().put(selectorA()), "resolved_closure", new JSONArray().put(selectorA()),
            "state", "ready", "projection_sha256", null);
        assertEquals(DeviceAiHost.localPreviewFingerprint(independent), summary.getString("local_preview_fingerprint"));

        assertHostFail("device_ai_host_package_mismatch", () -> DeviceAiHost.computeLocalPreview(bytes,
            json("question", QUESTION, "selectors", new JSONArray().put(selectorA()),
                "origin", with(origin, "expected_sha256", "ff".repeat(32)))));
        assertHostFail("device_ai_host_package_mismatch", () -> DeviceAiHost.computeLocalPreview(bytes,
            json("question", QUESTION, "selectors", new JSONArray().put(selectorA()),
                "origin", with(origin, "expected_byte_count", (long) bytes.length + 1))));
        assertHostFail("device_ai_host_package_mismatch", () -> DeviceAiHost.computeLocalPreview(bytes,
            json("question", QUESTION, "selectors", new JSONArray().put(with(selectorA(), "member_key", "ee".repeat(32))), "origin", origin)));
        assertHostFail("device_ai_host_package_mismatch", () -> DeviceAiHost.computeLocalPreview(bytes,
            json("question", QUESTION, "selectors", new JSONArray().put(withReference(selectorA(), "ver-9")), "origin", origin)));
        assertHostFail("device_ai_host_preview_unsupported", () -> DeviceAiHost.computeLocalPreview(bytes,
            json("question", QUESTION, "selectors", new JSONArray().put(selectorA()).put(selectorB()), "origin", origin)));
        assertHostFail("device_ai_host_preview_unsupported", () -> DeviceAiHost.computeLocalPreview(bytes,
            json("question", QUESTION, "selectors", new JSONArray().put(selectorA()), "origin", origin,
                "projection_mode", "frozen_decision_closure")));
    }

    private static List<String> stringsOf(JSONArray array) {
        List<String> out = new ArrayList<>(array.length());
        for (int at = 0; at < array.length(); at++) out.add(array.optString(at));
        return out;
    }

    private static JSONObject with(JSONObject source, String key, Object value) {
        JSONObject out = DeviceAiHost.copyOf(source);
        return put(out, key, value);
    }

    private static JSONObject withReference(JSONObject selector, String verification) {
        JSONObject out = DeviceAiHost.copyOf(selector);
        JSONObject reference = DeviceAiHost.copyOf(selector.optJSONObject("reference"));
        put(reference, "verification_id", verification);
        return put(out, "reference", reference);
    }

    // ---------------------------------------------------------------------
    // F. Journal: append / verify / tamper / five fences.
    // ---------------------------------------------------------------------

    @Test
    public void journalStampsChainsAndClones() throws Exception {
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        DeviceAiHost.DeviceAiJournal journal = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            sealer, store, () -> clock[0] += 10, () -> "2026-10-02T00:00:00Z");

        DeviceAiHost.JournalVerification empty = journal.verifyIntegrity();
        assertTrue("empty journal verifies", empty.ok && empty.length == 0);

        JSONObject first = journal.append(json("type", "preview_shown", "intent_id", "i-1",
            "local_preview_fingerprint", "aa".repeat(32), "question_sha256", "bb".repeat(32), "package_sha256", "cc".repeat(32)));
        JSONObject second = journal.append(json("type", "decision_made", "intent_id", "i-1", "decision", "allow",
            "local_preview_fingerprint", "aa".repeat(32)));
        JSONObject third = journal.append(json("type", "claim_submitted", "intent_id", "i-1", "prepare_id", "prep-1",
            "analysis_key", "11111111-2222-4333-8444-555555555555", "question_sha256", "bb".repeat(32)));
        assertEquals(List.of(1L, 2L, 3L), List.of(first.getLong("sequence"), second.getLong("sequence"), third.getLong("sequence")));
        assertEquals("0".repeat(64), first.getString("prev_sha256"));
        assertEquals(first.getString("entry_sha256"), second.getString("prev_sha256"));
        assertEquals(second.getString("entry_sha256"), third.getString("prev_sha256"));
        assertEquals("profile-1", third.getString("owner"));
        assertEquals(1L, third.getLong("generation"));
        assertEquals("session-1", third.getString("session_id"));
        assertEquals(List.of(10L, 20L, 30L), List.of(first.getLong("clock"), second.getLong("clock"), third.getLong("clock")));

        List<JSONObject> readBack = journal.readAll();
        assertEquals(3, readBack.size());
        readBack.get(0).getJSONObject("event").put("type", "failure_observed"); // mutate the returned clone only
        assertEquals("preview_shown", journal.readAll().get(0).getJSONObject("event").getString("type"));

        DeviceAiHost.JournalVerification verified = journal.verifyIntegrity();
        assertTrue(verified.ok && verified.length == 3 && verified.crossSessionEntries.isEmpty());
    }

    @Test
    public void journalDetectsTamperAndChainBreak() throws Exception {
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        DeviceAiHost.DeviceAiJournal journal = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            sealer, store, () -> clock[0] += 10, () -> "2026-10-02T00:00:00Z");
        journal.append(json("type", "preview_shown", "intent_id", "i-1",
            "local_preview_fingerprint", "aa".repeat(32), "question_sha256", "bb".repeat(32), "package_sha256", "cc".repeat(32)));
        journal.append(json("type", "decision_made", "intent_id", "i-1", "decision", "allow",
            "local_preview_fingerprint", "aa".repeat(32)));
        journal.append(json("type", "claim_submitted", "intent_id", "i-1", "prepare_id", "prep-1",
            "analysis_key", "11111111-2222-4333-8444-555555555555", "question_sha256", "bb".repeat(32)));

        // Fence 3 - tamper with entry content (entry_sha256 kept stale).
        JSONObject wire = unsealWire(store, sealer);
        JSONArray entries = wire.getJSONArray("entries");
        entries.getJSONObject(1).getJSONObject("event").put("decision", "deny");
        resealWire(store, wire, entries, sealer);
        DeviceAiHost.JournalVerification tampered = journal.verifyIntegrity();
        assertFalse(tampered.ok);
        assertTrue(violationCodes(tampered).contains("device_ai_host_journal_entry_tampered"));
        assertHostFail("device_ai_host_journal_entry_tampered", () -> journal.readAll());
        entries.getJSONObject(1).getJSONObject("event").put("decision", "allow");
        resealWire(store, wire, entries, sealer);
        assertTrue(journal.verifyIntegrity().ok);

        // Fence 3 - break the chain link.
        wire = unsealWire(store, sealer);
        entries = wire.getJSONArray("entries");
        entries.getJSONObject(2).put("prev_sha256", "ee".repeat(32));
        resealWire(store, wire, entries, sealer);
        DeviceAiHost.JournalVerification broken = journal.verifyIntegrity();
        assertFalse(broken.ok);
        assertTrue(violationCodes(broken).contains("device_ai_host_journal_chain_broken"));
        entries.getJSONObject(2).put("prev_sha256", entries.getJSONObject(1).getString("entry_sha256"));
        resealWire(store, wire, entries, sealer);
        assertTrue(journal.verifyIntegrity().ok);
    }

    @Test
    public void journalClockFence() throws Exception {
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        DeviceAiHost.DeviceAiJournal journal = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            sealer, store, () -> clock[0] += 10, () -> "2026-10-02T00:00:00Z");
        for (int at = 0; at < 3; at++)
            journal.append(json("type", "outcome_observed", "intent_id", "i-1", "analysis_key",
                "11111111-2222-4333-8444-555555555555", "request_id", "r-" + at, "state", "accepted"));

        // Fence 4 - clock regression at write time.
        clock[0] = 5;
        assertHostFail("device_ai_host_journal_clock_regression", () ->
            journal.append(json("type", "failure_observed", "intent_id", "i-1", "stage", "submit", "code", "api_network_unavailable")));
        clock[0] = 40;
        assertEquals(4L, journal.append(json("type", "failure_observed", "intent_id", "i-1", "stage", "submit",
            "code", "api_network_unavailable")).getLong("sequence"));

        // Fence 4 - reordered entries (older clock after newer) detected on read.
        JSONObject wire = unsealWire(store, sealer);
        JSONArray entries = wire.getJSONArray("entries");
        JSONArray reordered = new JSONArray();
        reordered.put(entries.get(3));
        for (int at = 0; at < 3; at++) reordered.put(entries.get(at));
        resealWire(store, wire, reordered, sealer);
        DeviceAiHost.JournalVerification check = journal.verifyIntegrity();
        assertFalse(check.ok);
        assertTrue("clock regression in stored order detected",
            violationCodes(check).contains("device_ai_host_journal_clock_regression"));
        resealWire(store, wire, entries, sealer);
        assertTrue(journal.verifyIntegrity().ok);
    }

    @Test
    public void journalOwnerGenerationKeyAndSessionFences() throws Exception {
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        DeviceAiHost.DeviceAiJournal journal = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            sealer, store, () -> clock[0] += 10, () -> "2026-10-02T00:00:00Z");
        for (int at = 0; at < 4; at++)
            journal.append(json("type", "outcome_observed", "intent_id", "i-1", "analysis_key",
                "11111111-2222-4333-8444-555555555555", "request_id", "r-" + at, "state", "accepted"));

        // Fence 1 - wrong owner (explicit header + AAD layer).
        DeviceAiHost.DeviceAiJournal wrongOwner = new DeviceAiHost.DeviceAiJournal("profile-2", 1L, "session-1",
            sealer, store, () -> clock[0] += 10, null);
        assertFalse(wrongOwner.verifyIntegrity().ok);
        assertEquals("device_ai_host_journal_owner_mismatch", wrongOwner.verifyIntegrity().violations.get(0)[0]);
        assertHostFail("device_ai_host_journal_owner_mismatch", wrongOwner::readAll);

        // Fence 2 - stale generation after a rebuild.
        DeviceAiHost.DeviceAiJournal staleGeneration = new DeviceAiHost.DeviceAiJournal("profile-1", 2L, "session-1",
            sealer, store, () -> clock[0] += 10, null);
        assertEquals("device_ai_host_journal_generation_mismatch", staleGeneration.verifyIntegrity().violations.get(0)[0]);

        // Wrong key: AES-GCM AAD/authentication failure => corrupt.
        DeviceAiHost.DeviceAiJournal wrongKey = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            SoftwareSealer.fresh(), store, () -> clock[0] += 10, null);
        assertEquals("device_ai_host_journal_corrupt", wrongKey.verifyIntegrity().violations.get(0)[0]);

        // Fence 5 - session binding: recovery reads stay possible, authorization does not.
        DeviceAiHost.DeviceAiJournal nextSession = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-2",
            sealer, store, () -> clock[0] += 10, null);
        DeviceAiHost.JournalVerification cross = nextSession.verifyIntegrity();
        assertTrue("recovery read allowed across sessions (structure ok)", cross.ok);
        assertEquals(4, cross.crossSessionEntries.size());
        List<JSONObject> fresh = nextSession.readAll();
        assertHostFail("device_ai_host_journal_session_mismatch", () -> nextSession.assertSameSession(fresh));
        JSONObject appended = nextSession.append(json("type", "failure_observed", "intent_id", null,
            "stage", "recover", "code", "none"));
        assertEquals("session-2", appended.getString("session_id"));
    }

    @Test
    public void journalRejectsUnknownOrOpenEventShapes() throws Exception {
        SoftwareSealer sealer = SoftwareSealer.fresh();
        DeviceAiHost.DeviceAiJournal journal = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            sealer, new MemoryStore(), () -> 10L, null);
        assertHostFail("device_ai_host_invalid_argument", () -> journal.append(json("type", "invented_event", "intent_id", "i-1")));
        assertHostFail("device_ai_host_invalid_argument", () -> journal.append(json("type", "decision_made", "intent_id", "i-1",
            "decision", "allow", "local_preview_fingerprint", "aa".repeat(32), "extra", "x")));
        assertHostFail("device_ai_host_invalid_argument", () -> journal.append(json("type", "decision_made", "intent_id", "i-1",
            "decision", "allow")));
        JSONObject valid = journal.append(json("type", "decision_made", "intent_id", "i-1", "decision", "deny",
            "local_preview_fingerprint", "aa".repeat(32)));
        assertEquals("decision_made", valid.getJSONObject("event").getString("type"));
    }

    // ---------------------------------------------------------------------
    // G. Host client over a mock transport.
    // ---------------------------------------------------------------------

    @Test
    public void clientPrepareShapeHeaderAndReplay() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        JSONObject prepareBody = prepareBodyFixture();
        JSONObject view = prepareViewFixture(prepareBody);

        transport.responder = call -> jsonResponse(201, view);
        JSONObject result = client.prepare(prepareBody, "9999AAAA-BBBB-4CCC-8DDD-5555EEE66666");
        assertEquals("prep-1", result.getString("id"));
        assertFalse(result.getBoolean("replayed"));
        FakeTransport.Call call = transport.last();
        assertEquals("POST", call.method);
        assertEquals("/v1/ai/device-evidence-packs", call.path);
        assertEquals(KEY_CANONICAL, call.headers.get("idempotency-key"));
        assertEquals("application/json", call.headers.get("content-type"));
        Map<?, ?> body = wireAst(call.body);
        assertEquals(DeviceAiHost.PREPARE_REQUEST_FIELDS, mapKeys(body)); // field names AND key order
        assertEquals("11111111-2222-4333-8444-555555555555", body.get("host_receipt_id"));

        // replay branch omits provider_preview and still passes
        JSONObject replayed = DeviceAiHost.copyOf(view);
        replayed.remove("provider_preview");
        replayed.put("replayed", true);
        transport.responder = ignored -> jsonResponse(200, replayed);
        JSONObject replayView = client.prepare(prepareBody, KEY_CANONICAL);
        assertTrue(replayView.getBoolean("replayed"));
        assertFalse(replayView.has("provider_preview"));

        // malformed view rejected
        JSONObject malformed = DeviceAiHost.copyOf(view);
        malformed.put("expires_at", "not-a-date");
        transport.responder = ignored -> jsonResponse(200, malformed);
        try {
            client.prepare(prepareBody, KEY_CANONICAL);
            fail("malformed view must be rejected");
        } catch (IllegalStateException expected) { /* view shape error */ }

        // M7 (decoder-spec section 3): a naive timestamp (no timezone offset)
        // is rejected exactly like an unparsable one (OffsetDateTime.parse
        // requires the offset; Date.parse-style leniency is out).
        JSONObject naive = DeviceAiHost.copyOf(view);
        naive.put("expires_at", "2026-10-02T12:30:00");
        transport.responder = ignored -> jsonResponse(200, naive);
        try {
            client.prepare(prepareBody, KEY_CANONICAL);
            fail("naive view timestamp must be rejected");
        } catch (IllegalStateException expected) { /* view shape error */ }

        // 409 closed code passthrough
        transport.responder = ignored -> jsonResponse(409, json("detail",
            json("code", "device_ai_prepare_conflict", "message", "已绑定既有准备记录")));
        try {
            client.prepare(with(prepareBody, "intent_id", "33333333-3333-4444-8555-666666666666"), KEY_CANONICAL);
            fail("409 must throw");
        } catch (DeviceAiHost.DeviceAiHostException error) {
            assertEquals(Integer.valueOf(409), error.httpStatus);
            assertEquals("device_ai_prepare_conflict", error.serverCode);
        }

        // closed-body assertion anchors
        assertClosedFail(() -> client.prepare(with(prepareBody, "local_preview_fingerprint", "x".repeat(64)), KEY_CANONICAL));
        JSONObject missing = DeviceAiHost.copyOf(prepareBody);
        missing.remove("question_sha256");
        assertClosedFail(() -> client.prepare(missing, KEY_CANONICAL));
    }

    @Test
    public void clientPrepareDispatchesFourDomainBodiesInFrozenKeyOrder() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        transport.responder = call -> jsonResponse(201, prepareViewFixture(prepareBodyFixture()));

        // vehicle domain under its locked mode: wire key order stays the frozen list.
        JSONObject vehicleBody = prepareBodyWith("complete_observation", selectors(vehicleSelector()), null);
        client.prepare(vehicleBody, KEY_CANONICAL);
        Map<?, ?> body = wireAst(transport.last().body);
        assertEquals(DeviceAiHost.PREPARE_REQUEST_FIELDS, mapKeys(body));
        Map<?, ?> selector = (Map<?, ?>) ((List<?>) body.get("selectors")).get(0);
        // nested selector/reference key order is org.json map order (not contractual) - assert the closed SETS.
        assertEquals(new java.util.HashSet<>(List.of("document_id", "kind", "member_key", "record_index", "reference")),
            new java.util.HashSet<>(mapKeys(selector)));
        Map<?, ?> reference = (Map<?, ?>) selector.get("reference");
        assertEquals(new java.util.HashSet<>(List.of("kind", "snapshot_id", "verification_id")),
            new java.util.HashSet<>(mapKeys(reference)));
        assertEquals("vehicle", selector.get("kind"));
        assertNull(selector.get("record_index"));

        // frozen closure over tire + recall: approved_closure rides the same frozen order.
        JSONObject closureBody = prepareBodyWith("frozen_decision_closure",
            selectors(selectorA()), selectors(selectorB(), recallSelector("rev-9", null, null)));
        client.prepare(closureBody, KEY_CANONICAL);
        Map<?, ?> closureWire = wireAst(transport.last().body);
        assertEquals(DeviceAiHost.PREPARE_REQUEST_FIELDS, mapKeys(closureWire));
        List<?> approved = (List<?>) closureWire.get("approved_closure");
        assertEquals(2, approved.size());
        Map<?, ?> recallWire = (Map<?, ?>) ((Map<?, ?>) approved.get(1)).get("reference");
        assertEquals(new java.util.HashSet<>(List.of("kind", "snapshot_id", "recall_revision_id", "verification_id")),
            new java.util.HashSet<>(mapKeys(recallWire)));
        assertEquals("rev-9", recallWire.get("recall_revision_id"));

        // a four-domain violation still fails before dispatch (zero transport calls).
        int callsBefore = transport.calls.size();
        assertHostFail("device_ai_host_invalid_argument", () ->
            client.prepare(prepareBodyWith("candidate_page_context", selectors(recallSearchSelectorWithDocument(null, 2L)), null), KEY_CANONICAL));
        assertEquals(callsBefore, transport.calls.size());
    }

    @Test
    public void clientLookupAndReadPaths() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        transport.responder = call -> jsonResponse(200, prepareViewFixture(prepareBodyFixture()));

        client.lookupPrepare("9999AAAA-BBBB-4CCC-8DDD-5555EEE66666");
        assertEquals("GET", transport.last().method);
        assertEquals("/v1/ai/device-evidence-packs/lookup?mode=history&idempotency_key=" + KEY_CANONICAL, transport.last().path);

        client.readPrepare("prep-1");
        assertEquals("/v1/ai/device-evidence-packs/prep-1?mode=history", transport.last().path);

        transport.responder = call -> jsonResponse(404, json("detail", "未找到本会话的设备 AI 准备记录"));
        try {
            client.lookupPrepare(KEY_CANONICAL);
            fail("404 must throw");
        } catch (DeviceAiHost.DeviceAiHostException error) {
            assertEquals(Integer.valueOf(404), error.httpStatus);
        }
    }

    @Test
    public void clientSubmitStreamBodyShapeAndNormalization() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        transport.responder = call -> jsonResponse(202, streamDetailFixture());
        JSONObject consent = consentFixture();

        JSONObject acceptance = client.submitStream(json("pack_id", "pack-1", "question", "　" + QUESTION + "　",
            "prepare_id", "prep-1", "host_receipt_id", "11111111-2222-4333-8444-555555555555",
            "device_context_fingerprint", "03".repeat(32), "provider_consent", consent),
            "9999AAAA-BBBB-4CCC-8DDD-5555EEE66666");
        assertFalse(acceptance.getBoolean("replayed"));
        Map<?, ?> body = wireAst(transport.last().body);
        assertEquals(DeviceAiHost.ANALYSIS_REQUEST_FIELDS, mapKeys(body));
        Map<?, ?> deviceSubmission = (Map<?, ?>) body.get("device_submission");
        assertEquals(DeviceAiHost.SUBMISSION_FIELDS, mapKeys(deviceSubmission));
        Map<?, ?> consentView = (Map<?, ?>) deviceSubmission.get("provider_consent");
        assertEquals(DeviceAiHost.PROVIDER_CONSENT_FIELDS, mapKeys(consentView));
        assertEquals("allow_external_processing literal true", Boolean.TRUE, body.get("allow_external_processing"));
        assertEquals("question normalized exactly once (trim-once)", QUESTION, body.get("question"));
        assertEquals(KEY_CANONICAL, transport.last().headers.get("idempotency-key"));

        // acceptance without the replayed flag rejected
        JSONObject withoutReplayed = DeviceAiHost.copyOf(streamDetailFixture());
        withoutReplayed.remove("replayed");
        transport.responder = call -> jsonResponse(202, withoutReplayed);
        try {
            client.submitStream(json("pack_id", "pack-1", "question", QUESTION, "prepare_id", "prep-1",
                "host_receipt_id", "11111111-2222-4333-8444-555555555555", "device_context_fingerprint", "03".repeat(32),
                "provider_consent", consent), KEY_CANONICAL);
            fail("acceptance without replayed flag must be rejected");
        } catch (IllegalStateException expected) { /* closed acceptance shape */ }

        // submit 409 closed code passthrough
        transport.responder = call -> jsonResponse(409, json("detail",
            json("code", "device_ai_consent_mismatch", "message", "六元组不一致")));
        try {
            client.submitStream(json("pack_id", "pack-1", "question", QUESTION, "prepare_id", "prep-1",
                "host_receipt_id", "11111111-2222-4333-8444-555555555555", "device_context_fingerprint", "03".repeat(32),
                "provider_consent", with(consent, "model", "other")), KEY_CANONICAL);
            fail("submit 409 must throw");
        } catch (DeviceAiHost.DeviceAiHostException error) {
            assertEquals("device_ai_consent_mismatch", error.serverCode);
        }
    }

    @Test
    public void clientAttemptLookupPath() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        transport.responder = call -> jsonResponse(200, streamDetailFixture());
        JSONObject detail = client.lookupAttempt("9999AAAA-BBBB-4CCC-8DDD-5555EEE66666");
        assertEquals("req-1", detail.getJSONObject("analysis").getString("id"));
        assertEquals("GET", transport.last().method);
        assertEquals("/v1/ai/analysis-streams/lookup?mode=history&idempotency_key=" + KEY_CANONICAL, transport.last().path);
    }

    // ---------------------------------------------------------------------
    // H. resolveUnknownOutcome (N18): lookup-first, never resubmit.
    // ---------------------------------------------------------------------

    @Test
    public void resolveUnknownOutcomeHitsWithSingleLookupAndZeroSubmits() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        String analysisKey = "12345678-1234-4234-8345-123456789abc";
        int[] lookups = {0}, submits = {0};
        transport.responder = call -> {
            if (call.path.startsWith("/v1/ai/analysis-streams/lookup")) { lookups[0]++; return jsonResponse(200, streamDetailFixture()); }
            if ("/v1/ai/analysis-streams".equals(call.path) && "POST".equals(call.method)) { submits[0]++; return jsonResponse(202, streamDetailFixture()); }
            return jsonResponse(500, json("detail", "unexpected"));
        };
        JSONObject resolved = DeviceAiHost.resolveUnknownOutcome(client, analysisKey.toUpperCase(), null, null);
        assertEquals("resolved", resolved.getString("kind"));
        assertEquals("req-1", resolved.getJSONObject("detail").getJSONObject("analysis").getString("id"));
        assertEquals(1, lookups[0]);
        assertEquals(0, submits[0]);
    }

    @Test
    public void resolveUnknownOutcomeMissWithoutLocalClaimAllowsFreshDecision() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        transport.responder = call -> jsonResponse(404, json("detail", "未找到"));
        String analysisKey = "12345678-1234-4234-8345-123456789abc";

        assertEquals("not_submitted", DeviceAiHost.resolveUnknownOutcome(client, analysisKey, null, null).getString("kind"));

        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        DeviceAiHost.DeviceAiJournal journal = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            sealer, store, () -> clock[0] += 10, null);
        assertEquals("not_submitted", DeviceAiHost.resolveUnknownOutcome(client, analysisKey, journal, null).getString("kind"));
    }

    @Test
    public void resolveUnknownOutcomeLocalClaimRequiresSameKeyUserDecision() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        int[] submits = {0};
        transport.responder = call -> {
            if ("/v1/ai/analysis-streams".equals(call.path) && "POST".equals(call.method)) { submits[0]++; return jsonResponse(202, streamDetailFixture()); }
            return jsonResponse(404, json("detail", "未找到"));
        };
        String analysisKey = "12345678-1234-4234-8345-123456789abc";
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        DeviceAiHost.DeviceAiJournal journal = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-1",
            sealer, store, () -> clock[0] += 10, null);
        journal.append(json("type", "claim_submitted", "intent_id", "intent-1", "prepare_id", "prep-1",
            "analysis_key", analysisKey, "question_sha256", "bb".repeat(32)));

        JSONObject localClaim = DeviceAiHost.resolveUnknownOutcome(client, analysisKey, journal, "intent-1");
        assertEquals("unknown_local_claim", localClaim.getString("kind"));
        assertEquals(analysisKey, localClaim.getString("analysis_key"));
        assertEquals("same_key_same_body_user_decision_only", localClaim.getString("resubmission"));
        assertEquals("no automatic resubmit happened", 0, submits[0]);

        assertEquals("claim filtered by intent id", "not_submitted",
            DeviceAiHost.resolveUnknownOutcome(client, analysisKey, journal, "intent-other").getString("kind"));

        // fence 5: cross-session claim never replays
        DeviceAiHost.DeviceAiJournal nextSession = new DeviceAiHost.DeviceAiJournal("profile-1", 1L, "session-2",
            sealer, store, () -> clock[0] += 10, null);
        assertEquals("cross_session_replay_blocked",
            DeviceAiHost.resolveUnknownOutcome(client, analysisKey, nextSession, "intent-1").getString("kind"));

        // tampered journal => integrity failure surfaced, still zero submits
        JSONObject wire = unsealWire(store, sealer);
        wire.getJSONArray("entries").getJSONObject(0).getJSONObject("event").put("analysis_key", "forged");
        resealWire(store, wire, wire.getJSONArray("entries"), sealer);
        JSONObject integrity = DeviceAiHost.resolveUnknownOutcome(client, analysisKey, journal, "intent-1");
        assertEquals("journal_integrity_failed", integrity.getString("kind"));
        assertTrue(integrity.getJSONArray("violations").length() > 0);
        assertEquals(0, submits[0]);
    }

    @Test
    public void resolveUnknownOutcomePropagatesNon404Failures() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        transport.responder = call -> jsonResponse(409, json("detail", json("code", "device_ai_consent_mismatch")));
        try {
            DeviceAiHost.resolveUnknownOutcome(client, "12345678-1234-4234-8345-123456789abc", null, null);
            fail("non-404 failures must propagate (state stays genuinely unknown)");
        } catch (DeviceAiHost.DeviceAiHostException error) {
            assertEquals(Integer.valueOf(409), error.httpStatus);
        }
    }

    // ---------------------------------------------------------------------
    // I. Command layer: journal append/read round-trip (five fences) and the
    // N18 resolve command branches over the same injected sealer/store cores
    // the Android wrappers (keystore sealer + no-backup AtomicFile) call.
    // ---------------------------------------------------------------------

    @Test
    public void journalAppendCommandRoundTripsThroughJournalRead() throws Exception {
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        String analysisKey = "12345678-1234-4234-8345-123456789abc";

        JSONObject previewEntry = DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "preview_shown", "intent_id", "intent-1",
                "local_preview_fingerprint", "aa".repeat(32), "question_sha256", "bb".repeat(32), "package_sha256", "cc".repeat(32)),
            sealer, store, () -> clock[0] += 10, () -> "2026-10-02T00:00:00Z");
        assertEquals(1L, previewEntry.getLong("sequence"));
        assertEquals("preview_shown", previewEntry.getJSONObject("event").getString("type"));

        JSONObject claimEntry = DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "claim_submitted", "intent_id", "intent-1", "prepare_id", "prep-1",
                "analysis_key", analysisKey, "question_sha256", "bb".repeat(32)),
            sealer, store, () -> clock[0] += 10, () -> "2026-10-02T00:00:00Z");
        assertEquals(2L, claimEntry.getLong("sequence"));
        // the append chained onto the first entry (fence 3 continuity at write time)
        assertEquals(previewEntry.getString("entry_sha256"), claimEntry.getString("prev_sha256"));

        // the journalRead command core sees both entries and all five fences pass
        JSONObject report = DeviceAiHost.journalRead("profile-1", 1L, "session-1", sealer, store, () -> clock[0] += 10);
        assertTrue(report.getBoolean("ok"));
        assertEquals(2L, report.getLong("length"));
        assertEquals(0, report.getJSONArray("violations").length());
        JSONArray entries = report.getJSONArray("entries");
        assertEquals("preview_shown", entries.getJSONObject(0).getJSONObject("event").getString("type"));
        assertEquals("claim_submitted", entries.getJSONObject(1).getJSONObject("event").getString("type"));
        assertEquals(analysisKey, entries.getJSONObject(1).getJSONObject("event").getString("analysis_key"));

        // a different session still verifies (fence 5 is recorded, never fatal to a read)
        JSONObject crossReport = DeviceAiHost.journalRead("profile-1", 1L, "session-2", sealer, store, () -> clock[0] += 10);
        assertTrue(crossReport.getBoolean("ok"));
        assertEquals(2, crossReport.getJSONArray("cross_session_entries").length());

        // a stale generation journal (rebuilt ledger) fails the generation fence instead
        JSONObject stale = DeviceAiHost.journalRead("profile-1", 2L, "session-1", sealer, store, () -> clock[0] += 10);
        assertFalse(stale.getBoolean("ok"));
        assertEquals("device_ai_host_journal_generation_mismatch", stale.getJSONArray("violations").getJSONObject(0).getString("code"));
    }

    @Test
    public void journalAppendCommandRejectsOpenPayloadShapes() throws Exception {
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};
        java.util.function.LongSupplier tick = () -> clock[0] += 10;

        // unknown event type stays closed
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "invented_event", "intent_id", "intent-1"), sealer, store, tick, null));
        // extra field / missing field (key-set closure rides the journal's assertEvent)
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "decision_made", "intent_id", "intent-1", "decision", "allow",
                "local_preview_fingerprint", "aa".repeat(32), "extra", "x"), sealer, store, tick, null));
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "decision_made", "intent_id", "intent-1", "decision", "allow"), sealer, store, tick, null));
        // payload closure: non-64hex fingerprint
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "decision_made", "intent_id", "intent-1", "decision", "allow",
                "local_preview_fingerprint", "zz".repeat(32)), sealer, store, tick, null));
        // open decision value
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "decision_made", "intent_id", "intent-1", "decision", "maybe",
                "local_preview_fingerprint", "aa".repeat(32)), sealer, store, tick, null));
        // non-canonical analysis_key
        assertHostFail("device_ai_host_invalid_argument", () -> DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "claim_submitted", "intent_id", "intent-1", "prepare_id", "prep-1",
                "analysis_key", "not-a-uuid", "question_sha256", "bb".repeat(32)), sealer, store, tick, null));
        // outcome_observed accepts the empty intent spelling (web recordTerminal intentId ?? "")
        JSONObject outcome = DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "outcome_observed", "intent_id", "", "analysis_key", "12345678-1234-4234-8345-123456789abc",
                "request_id", "req-1", "state", "accepted"), sealer, store, tick, null);
        assertEquals("", outcome.getJSONObject("event").getString("intent_id"));
        // failure_observed keeps the nullable intent slot (pre-intent failures)
        JSONObject failure = DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "failure_observed", "intent_id", null, "stage", "submit", "code", "api_network_unavailable"),
            sealer, store, tick, () -> "2026-10-02T00:00:00Z");
        assertTrue(failure.getJSONObject("event").isNull("intent_id"));
        // nothing above may have persisted a rejected entry (all-or-nothing writes)
        JSONObject report = DeviceAiHost.journalRead("profile-1", 1L, "session-1", sealer, store, tick);
        assertEquals(2L, report.getLong("length"));
    }

    @Test
    public void resolveUnknownCommandCoversTheBranches() throws Exception {
        FakeTransport transport = new FakeTransport();
        DeviceAiHost.DeviceAiHostClient client = new DeviceAiHost.DeviceAiHostClient(transport);
        String analysisKey = "12345678-1234-4234-8345-123456789abc";
        int[] lookups = {0}, submits = {0};
        transport.responder = call -> {
            if (call.path.startsWith("/v1/ai/analysis-streams/lookup")) { lookups[0]++; return jsonResponse(404, json("detail", "未找到")); }
            if ("/v1/ai/analysis-streams".equals(call.path) && "POST".equals(call.method)) { submits[0]++; return jsonResponse(202, streamDetailFixture()); }
            return jsonResponse(500, json("detail", "unexpected"));
        };
        SoftwareSealer sealer = SoftwareSealer.fresh();
        MemoryStore store = new MemoryStore();
        long[] clock = {0};

        // Branch 1: miss + empty journal => not_submitted (a fresh user decision is legitimate)
        assertEquals("not_submitted", DeviceAiHost.resolveUnknown(analysisKey.toUpperCase(), null, "profile-1", 1L,
            "session-1", client, sealer, store, () -> clock[0] += 10, null).getString("kind"));

        // record a local claim through the append command core
        DeviceAiHost.journalAppend("profile-1", 1L, "session-1",
            json("type", "claim_submitted", "intent_id", "intent-1", "prepare_id", "prep-1",
                "analysis_key", analysisKey, "question_sha256", "bb".repeat(32)),
            sealer, store, () -> clock[0] += 10, null);

        // Branch 2: miss + local claim => unknown_local_claim, same key + explicit user decision only
        JSONObject localClaim = DeviceAiHost.resolveUnknown(analysisKey, "intent-1", "profile-1", 1L, "session-1",
            client, sealer, store, () -> clock[0] += 10, null);
        assertEquals("unknown_local_claim", localClaim.getString("kind"));
        assertEquals(analysisKey, localClaim.getString("analysis_key"));
        assertEquals("same_key_same_body_user_decision_only", localClaim.getString("resubmission"));
        // the intent filter narrows the claim away
        assertEquals("not_submitted", DeviceAiHost.resolveUnknown(analysisKey, "intent-other", "profile-1", 1L,
            "session-1", client, sealer, store, () -> clock[0] += 10, null).getString("kind"));

        // Branch 3: cross-session claim never replays (fence 5)
        assertEquals("cross_session_replay_blocked", DeviceAiHost.resolveUnknown(analysisKey, "intent-1", "profile-1",
            1L, "session-2", client, sealer, store, () -> clock[0] += 10, null).getString("kind"));

        // Branch 4: lookup hit => resolved with the checked stream detail (single lookup, zero submits)
        transport.responder = call -> {
            if (call.path.startsWith("/v1/ai/analysis-streams/lookup")) { lookups[0]++; return jsonResponse(200, streamDetailFixture()); }
            if ("/v1/ai/analysis-streams".equals(call.path) && "POST".equals(call.method)) { submits[0]++; return jsonResponse(202, streamDetailFixture()); }
            return jsonResponse(500, json("detail", "unexpected"));
        };
        JSONObject resolved = DeviceAiHost.resolveUnknown(analysisKey, "intent-1", "profile-1", 1L, "session-1",
            client, sealer, store, () -> clock[0] += 10, null);
        assertEquals("resolved", resolved.getString("kind"));
        assertEquals("req-1", resolved.getJSONObject("detail").getJSONObject("analysis").getString("id"));

        // Branch 5: tampered journal under a fresh miss => integrity failure surfaced, still zero submits
        transport.responder = call -> {
            if (call.path.startsWith("/v1/ai/analysis-streams/lookup")) { lookups[0]++; return jsonResponse(404, json("detail", "未找到")); }
            if ("/v1/ai/analysis-streams".equals(call.path) && "POST".equals(call.method)) { submits[0]++; return jsonResponse(202, streamDetailFixture()); }
            return jsonResponse(500, json("detail", "unexpected"));
        };
        JSONObject wire = unsealWire(store, sealer);
        wire.getJSONArray("entries").getJSONObject(0).getJSONObject("event").put("analysis_key", "forged");
        resealWire(store, wire, wire.getJSONArray("entries"), sealer);
        JSONObject integrity = DeviceAiHost.resolveUnknown(analysisKey, "intent-1", "profile-1", 1L, "session-1",
            client, sealer, store, () -> clock[0] += 10, null);
        assertEquals("journal_integrity_failed", integrity.getString("kind"));
        assertTrue(integrity.getJSONArray("violations").length() > 0);

        assertEquals("exactly one lookup per resolve, never a submit", 6, lookups[0]);
        assertEquals(0, submits[0]);
    }
}
