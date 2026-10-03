package org.taiji.tireintelligence.mobile;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.LongSupplier;
import java.util.function.Supplier;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * device-ai internal, wire not frozen (roundtable D15 layered strategy).
 *
 * Android Host-side wiring for the device-AI bridge (round 50, P1-3, Java
 * counterpart of packages/api-client/src/device-ai-host.ts). Four concerns,
 * none of them a Provider call and none of them a new wire:
 *
 *  1. DeviceAiHostClient - metadata-only prepare + lookup/read against the
 *     implemented server routes, and the device branch of the existing stream
 *     entry. Request bodies match the closed server DTOs in
 *     apps/api/tire_api/device_ai.py (DeviceAIPrepareRequest / DeviceSubmission
 *     / ProviderConsent) and ai_analysis.py (AnalysisRequest) verbatim; the
 *     frozen field lists double as the request-body key ORDER (org.json
 *     JSONObject preserves insertion order, mirroring the TS object literals).
 *     The transport is injected: production uses NativeHttpBridge (the only
 *     native network authority - session cookie bootstrap, request registry,
 *     NativePolicy header/path admission and the closed NativeFailure error
 *     mapping); JVM tests inject an in-memory fake (no JVM HTTP-mock
 *     convention exists in this source set).
 *  2. computeLocalPreview + fingerprint helpers - question_sha256 (bare
 *     sha256 of trim-once UTF-8, no namespace, no JSON wrapping, no NFKC),
 *     selection_sha256 / device_context_fingerprint / local_preview_fingerprint
 *     per .artifacts/device-ai50/specs/fingerprint-spec.md sections 2/3/4,
 *     recomputed through the strict DeviceAiJsonParser exact-AST (68/68 E1
 *     parity). The three namespaces are proposals pending Root approval.
 *  3. DeviceAiJournal - AES-GCM encrypted append-only journal with the five
 *     fences: owner, generation, SHA chain, monotonic clock, session. The key
 *     is Host-injected via the Sealer interface: Android uses an
 *     AndroidKeyStore AES-256-GCM key (same KeyGenParameterSpec conventions as
 *     OfflineCipher/EncryptedSessionStore, alias derived from the app package);
 *     the AAD pins ["device-ai-journal@1", owner] so a blob copied across
 *     owners fails outright (cryptographic owner fence below the explicit one).
 *     AAD bytes are the canonical (json.dumps ensure_ascii=False) encoding -
 *     NOT JSON.stringify, which additionally escapes U+2028/U+2029; this store
 *     is Host-internal, and the canonical form matches the Python/TS reference
 *     family used for every other digest in this module.
 *  4. resolveUnknownOutcome - N18 lookup-first recovery: a miss plus a local
 *     claim allows exactly one recovery path (same key, same body, explicit
 *     user decision); a cross-session claim never replays; nothing is ever
 *     resubmitted automatically.
 *
 * Deliberately not reachable through any frozen product wire (D15): the
 * TireNativePlugin command entries are dormant thin wrappers until the JS host
 * flow imports the TS SDK module by path.
 *
 * P1-4c (round 50): the prepare-wire shape checks mirror the four-domain
 * server DTO and the TS SDK assertDeviceAiPrepareSelector /
 * assertDeviceAiPrepareBody semantics verbatim — selector kinds tire / vehicle
 * / recall / recall_search (test_event stays closed, N27), record_index 0..3999
 * only on record-carrying domains and never without document_id, the five
 * prepare projection modes (no complete_event_context), approved_closure a
 * required 1..SELECTOR_CAPACITY list exactly in frozen_decision_closure. The
 * four frozen field lists themselves are unchanged; only the shape validation
 * around them widens, mirroring the TS/Rust host siblings.
 *
 * Android's org.json declares JSONException on put/get while the JVM unit-test
 * org.json artifact does not, so every org.json mutation goes through the
 * put() helper below (constant keys only - the checked exception is
 * unreachable) and every read is opt-based after closed validation.
 */
final class DeviceAiHost {
    static final String SELECTION_NAMESPACE = "device-ai-selection@1";
    static final String CONTEXT_NAMESPACE = "device-ai-context@1";
    static final String LOCAL_PREVIEW_NAMESPACE = "device-ai-local-preview@1";
    static final String JOURNAL_SCHEMA = "device-ai-journal@1";
    static final String JOURNAL_ENTRY_SCHEMA = "device-ai-journal-entry@1";
    static final String PROJECTION_POLICY_VERSION = "device-ai-projection@1";
    static final String CONTEXT_SCHEMA = "device-ai-context@1";
    static final long SAFE_INTEGER = 9_007_199_254_740_991L; // 2^53 - 1 (Number.isSafeInteger parity)
    static final int QUESTION_MIN_CODEPOINTS = 2;
    static final int QUESTION_MAX_CODEPOINTS = 2000;
    static final int SELECTOR_CAPACITY = 6;
    /** Server DeviceSelector.record_index bound (StrictInt ge=0 le=3999, device_ai.py L124). */
    static final int SELECTOR_MAX_RECORD_INDEX = 3999;
    /** test_event event_revision bound (1..2^31-1, projection core _reference). */
    static final long EVENT_REVISION_MAX = 2_147_483_647L;
    /**
     * Resolved-closure member bound (pack member cap 200): REQUESTED selectors are
     * capped at SELECTOR_CAPACITY by the DTO, but a frozen_decision_closure may
     * expand past that (fingerprint-spec section 2, TS/Rust parity).
     */
    static final int RESOLVED_CLOSURE_CAPACITY = 200;
    static final int JOURNAL_MAX_BYTES = 8 * 1024 * 1024;

    /** Prepare-wire domain set (device_ai.py DeviceSelector Literal; test_event stays out - N27). */
    static final Set<String> PREPARE_SELECTOR_KINDS = Set.of("tire", "vehicle", "recall", "recall_search");
    /** Digest-layer domain set: the four open domains plus test_event (preview restricted-rejection parity). */
    static final Set<String> ANY_SELECTOR_KINDS = Set.of("tire", "vehicle", "recall", "recall_search", "test_event");
    /** Server DeviceAIPrepareRequest.projection_mode Literal, verbatim (five values; no complete_event_context). */
    static final List<String> PREPARE_PROJECTION_MODES = List.of(
        "single_observation", "frozen_decision_closure", "complete_observation",
        "complete_formal_observation", "candidate_page_context");
    /** Closed per-kind reference key sets (device_ai.py reference models; order = canonical-irrelevant). */
    static final Map<String, List<String>> REFERENCE_FIELDS = java.util.Collections.unmodifiableMap(new LinkedHashMap<>(Map.of(
        "tire", List.of("kind", "snapshot_id", "variant_id", "verification_id"),
        "vehicle", List.of("kind", "snapshot_id", "verification_id"),
        "recall", List.of("kind", "snapshot_id", "recall_revision_id", "verification_id"),
        "recall_search", List.of("kind", "snapshot_id", "verification_id"),
        "test_event", List.of("kind", "event_id", "event_revision"))));

    /** Closed server DTO field lists (apps/api/tire_api/device_ai.py + ai_analysis.py, verbatim; order = body key order). */
    static final List<String> PREPARE_REQUEST_FIELDS = List.of(
        "package_id", "expected_sha256", "expected_byte_count", "expected_schema", "expected_owner_scope_id",
        "selectors", "projection_mode", "approved_closure", "expected_projection_sha256", "question_sha256",
        "host_receipt_id", "intent_id");
    static final List<String> SUBMISSION_FIELDS = List.of(
        "prepare_id", "host_receipt_id", "device_context_fingerprint", "provider_consent");
    static final List<String> PROVIDER_CONSENT_FIELDS = List.of(
        "expected_pack_fingerprint", "expected_device_context_fingerprint", "question_sha256",
        "provider", "model", "expected_provider_policy_fingerprint");
    static final List<String> ANALYSIS_REQUEST_FIELDS = List.of(
        "pack_id", "question", "allow_external_processing", "device_submission");

    private DeviceAiHost() {}

    // ---------------------------------------------------------------------
    // Closed failure. The message carries only fixed descriptions, never source content.
    // ---------------------------------------------------------------------

    static final class DeviceAiHostException extends RuntimeException {
        final String code;
        /** Present when the server answered a non-2xx status (TS ApiError passthrough carrier). */
        final Integer httpStatus;
        /** Closed server error code from detail.code, when the server sent one. */
        final String serverCode;
        DeviceAiHostException(String code) { this(code, null, null, code); }
        static DeviceAiHostException http(int status, String serverCode, String detail) {
            return new DeviceAiHostException("device_ai_host_http_error", status, serverCode,
                detail == null || detail.isEmpty() ? "HTTP " + status : detail);
        }
        private DeviceAiHostException(String code, Integer httpStatus, String serverCode, String message) {
            super(message);
            this.code = code; this.httpStatus = httpStatus; this.serverCode = serverCode;
        }
    }

    private static DeviceAiHostException fail(String code) { return new DeviceAiHostException(code); }

    // ---------------------------------------------------------------------
    // org.json bridge helpers (Android checked JSONException becomes an
    // unreachable programming error; keys are always compile-time constants).
    // ---------------------------------------------------------------------

    /** Android org.json has no keySet()/getNames(); keys() iteration is the shared API. */
    static List<String> keyNames(JSONObject object) {
        List<String> keys = new ArrayList<>();
        java.util.Iterator<String> iterator = object.keys();
        while (iterator.hasNext()) keys.add(iterator.next());
        return keys;
    }

    private static JSONObject put(JSONObject target, String key, Object value) {
        try { return target.put(key, value); }
        catch (JSONException unreachable) { throw new IllegalStateException("org.json put failed", unreachable); }
    }

    private static JSONArray put(JSONArray target, Object value) {
        return target.put(value); // put(Object) declares no checked exception on either org.json
    }

    /** Shallow copy preserving insertion order (values keep NULL sentinels). */
    static JSONObject copyOf(JSONObject source) {
        JSONObject out = new JSONObject();
        for (String key : keyNames(source)) put(out, key, source.opt(key));
        return out;
    }

    // ---------------------------------------------------------------------
    // Small closed predicates.
    // ---------------------------------------------------------------------

    static boolean isHash64(Object value) {
        if (!(value instanceof String)) return false;
        String text = (String) value;
        if (text.length() != 64) return false;
        for (int at = 0; at < 64; at++) {
            char character = text.charAt(at);
            if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) return false;
        }
        return true;
    }

    /** TS isPlainString parity: 1..max UTF-16 units, no CR/LF/NUL. */
    static boolean isPlainString(Object value, int max) {
        if (!(value instanceof String)) return false;
        String text = (String) value;
        if (text.isEmpty() || text.length() > max) return false;
        return text.indexOf('\r') < 0 && text.indexOf('\n') < 0 && text.indexOf('\0') < 0;
    }

    private static void requireHash64(Object value) {
        if (!isHash64(value)) throw fail("device_ai_host_invalid_argument");
    }

    /** Bounded metadata integer (safe-integer parity); rejects fractions and oversized values. */
    static long metaLong(Object value) {
        long result;
        if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long)
            result = ((Number) value).longValue();
        else if (value instanceof Float || value instanceof Double) {
            double raw = ((Number) value).doubleValue();
            if (Math.rint(raw) != raw) throw fail("device_ai_host_invalid_argument");
            result = (long) raw;
        } else if (value instanceof java.math.BigDecimal) {
            try { result = ((java.math.BigDecimal) value).longValueExact(); }
            catch (ArithmeticException notIntegral) { throw fail("device_ai_host_invalid_argument"); }
        } else throw fail("device_ai_host_invalid_argument");
        if (result > SAFE_INTEGER || result < -SAFE_INTEGER) throw fail("device_ai_host_invalid_argument");
        return result;
    }

    private static long positiveMetaLong(JSONObject object, String key) {
        if (!object.has(key)) throw fail("device_ai_host_invalid_argument");
        long value = metaLong(object.opt(key));
        if (value < 1) throw fail("device_ai_host_invalid_argument");
        return value;
    }

    private static String plainString(JSONObject object, String key, int max) {
        Object value = object.opt(key);
        if (!isPlainString(value, max)) throw fail("device_ai_host_invalid_argument");
        return (String) value;
    }

    /**
     * Canonical lowercase UUID normalization, mirroring device_ai.py canonical_uuid and the
     * TS canonicalDeviceAiUuid (accepts uppercase and braced spellings; output is the canonical
     * hyphenated lowercase form so idempotency keys never drift by spelling).
     */
    static String canonicalUuid(String value) {
        if (value == null || value.isEmpty() || value.length() > 68) throw fail("device_ai_host_invalid_argument");
        String text = value.trim().toLowerCase(java.util.Locale.ROOT);
        if (text.startsWith("{") && text.endsWith("}")) text = text.substring(1, text.length() - 1);
        if (!text.matches("[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"))
            throw fail("device_ai_host_invalid_argument");
        return text;
    }

    static String sha256Hex(byte[] data) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder out = new StringBuilder(hash.length * 2);
            for (byte value : hash) out.append(Character.forDigit((value >> 4) & 0xF, 16)).append(Character.forDigit(value & 0xF, 16));
            return out.toString();
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("SHA-256 unavailable", unavailable);
        }
    }

    // ---------------------------------------------------------------------
    // question: trim-once over the pinned Python whitespace set + codepoint counting
    // + bare UTF-8 sha256 (fingerprint-spec section 5).
    // ---------------------------------------------------------------------

    /** Python str.strip() whitespace set, explicit (roundtable D3). JS String.trim() differs (U+FEFF, U+001C..1F). */
    private static boolean pythonWhitespace(char character) {
        switch (character) {
            case '\t': case '\n': case '\u000B': case '\f': case '\r': case ' ':
            case '\u001C': case '\u001D': case '\u001E': case '\u001F': case '\u0085': case '\u00A0':
            case '\u1680': case '\u2028': case '\u2029': case '\u202F': case '\u205F': case '\u3000':
                return true;
            default:
                return character >= '\u2000' && character <= '\u200A';
        }
    }

    /** Exactly one trim pass over the pinned whitespace set (no double trim). */
    static String trimOnceQuestion(String text) {
        if (text == null) throw fail("device_ai_host_invalid_argument");
        int start = 0, end = text.length();
        while (start < end && pythonWhitespace(text.charAt(start))) start++;
        while (end > start && pythonWhitespace(text.charAt(end - 1))) end--;
        return text.substring(start, end);
    }

    /** Unicode codepoint count (Python len()), never UTF-16 code units. */
    static int questionCodepoints(String text) { return text.codePointCount(0, text.length()); }

    /** The single normalization point before any digest or submit body. */
    static String normalizeQuestion(String text) {
        if (!(text instanceof String)) throw fail("device_ai_host_invalid_argument");
        String trimmed = trimOnceQuestion(text);
        int count = questionCodepoints(trimmed);
        if (count < QUESTION_MIN_CODEPOINTS || count > QUESTION_MAX_CODEPOINTS)
            throw fail("device_ai_host_invalid_argument");
        return trimmed;
    }

    /** Bare sha256(UTF-8 bytes): no namespace, no JSON quoting, no NFKC (spec section 5). */
    static String questionSha256(String normalizedQuestion) {
        if (!(normalizedQuestion instanceof String)) throw fail("device_ai_host_invalid_argument");
        return sha256Hex(normalizedQuestion.getBytes(StandardCharsets.UTF_8));
    }

    // ---------------------------------------------------------------------
    // org.json <-> exact-AST conversion (canonical SHA is always computed over
    // the exact AST; org.json numbers may only carry bounded metadata integers).
    // ---------------------------------------------------------------------

    static Object jsonToAst(Object value) {
        if (value == null || value == JSONObject.NULL) return null;
        if (value instanceof String || value instanceof Boolean) return value;
        if (value instanceof Number) return new DeviceAiJsonParser.NumberLexeme(Long.toString(metaLong(value)));
        if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value;
            Map<String, Object> out = new LinkedHashMap<>();
            for (String key : keyNames(object)) out.put(key, jsonToAst(object.opt(key)));
            return out;
        }
        if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value;
            List<Object> out = new ArrayList<>(array.length());
            for (int at = 0; at < array.length(); at++) out.add(jsonToAst(array.opt(at)));
            return out;
        }
        throw fail("device_ai_host_invalid_argument");
    }

    /** Exact-AST inputs pass through untouched; org.json values are converted. */
    static Object exactAst(Object value) {
        if (value == null || value == JSONObject.NULL) return null;
        if (value instanceof Map || value instanceof List || value instanceof DeviceAiJsonParser.NumberLexeme
            || value instanceof String || value instanceof Boolean) return value;
        return jsonToAst(value);
    }

    static Object astToJson(Object node) {
        if (node == null) return JSONObject.NULL;
        if (node instanceof String || node instanceof Boolean) return node;
        if (node instanceof DeviceAiJsonParser.NumberLexeme) {
            String token = ((DeviceAiJsonParser.NumberLexeme) node).token;
            if (token.indexOf('.') >= 0 || token.indexOf('e') >= 0 || token.indexOf('E') >= 0)
                throw fail("device_ai_host_journal_corrupt"); // events carry metadata integers only
            return Long.parseLong(token);
        }
        if (node instanceof List) {
            JSONArray out = new JSONArray();
            for (Object child : (List<?>) node) put(out, astToJson(child));
            return out;
        }
        if (node instanceof Map) {
            JSONObject out = new JSONObject();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) node).entrySet())
                put(out, (String) entry.getKey(), astToJson(entry.getValue()));
            return out;
        }
        throw fail("device_ai_host_invalid_argument");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asAstObject(Object node, String code) {
        if (!(node instanceof Map)) throw fail(code);
        for (Object key : ((Map<?, ?>) node).keySet()) if (!(key instanceof String)) throw fail(code);
        return (Map<String, Object>) node;
    }

    // ---------------------------------------------------------------------
    // selector wire shape (server DeviceSelector). P1-4c: the prepare wire is
    // four-domain (tire / vehicle / recall / recall_search, device_ai.py L121);
    // the digest layer (selectorAst) additionally accepts test_event so a local
    // preview can reproduce the projection port's restricted-rejection for it.
    // ---------------------------------------------------------------------

    static void assertDeviceAiSelector(JSONObject selector) {
        // tire branch (phase A computeLocalPreview; TS assertDeviceAiSelector parity).
        if (selector == null || !"tire".equals(selector.optString("kind"))) throw fail("device_ai_host_invalid_argument");
        assertDeviceAiPrepareSelector(selector);
    }

    /**
     * Closed per-kind selector check over the five reference kinds (TS
     * assertDeviceAiAnySelector mirror): member_key 64-hex, bounded document
     * ids, record_index 0..3999, per-kind closed reference key set with
     * reference.kind == selector.kind, test_event event_revision 1..2^31-1.
     */
    static void assertDeviceAiAnySelector(JSONObject selector) {
        if (selector == null) throw fail("device_ai_host_invalid_argument");
        String kind = selector.optString("kind");
        if (!ANY_SELECTOR_KINDS.contains(kind)) throw fail("device_ai_host_invalid_argument");
        if (!isHash64(selector.opt("member_key"))) throw fail("device_ai_host_invalid_argument");
        Object documentId = selector.opt("document_id");
        if (!(documentId == null || documentId == JSONObject.NULL) && !isPlainString(documentId, 200))
            throw fail("device_ai_host_invalid_argument");
        Object recordIndex = selector.opt("record_index");
        boolean hasRecordIndex = !(recordIndex == null || recordIndex == JSONObject.NULL);
        if (hasRecordIndex) {
            long index = metaLong(recordIndex);
            if (index < 0 || index > SELECTOR_MAX_RECORD_INDEX) throw fail("device_ai_host_invalid_argument");
        }
        JSONObject reference = selector.optJSONObject("reference");
        if (reference == null || !kind.equals(reference.optString("kind")))
            throw fail("device_ai_host_invalid_argument"); // 'selector kind 与引用 kind 必须一致'
        List<String> expectedKeys = REFERENCE_FIELDS.get(kind);
        Set<String> expected = new LinkedHashSet<>(expectedKeys);
        List<String> actual = keyNames(reference);
        for (String key : actual) if (!expected.contains(key)) throw fail("device_ai_host_invalid_argument");
        for (String key : expectedKeys) if (!reference.has(key)) throw fail("device_ai_host_invalid_argument");
        switch (kind) {
            case "tire":
                requirePlainReference(reference, "snapshot_id");
                requirePlainReference(reference, "variant_id");
                requirePlainReference(reference, "verification_id");
                break;
            case "vehicle":
            case "recall_search":
                requirePlainReference(reference, "snapshot_id");
                requirePlainReference(reference, "verification_id");
                break;
            case "recall":
                requirePlainReference(reference, "snapshot_id");
                requirePlainReference(reference, "verification_id");
                Object revision = reference.opt("recall_revision_id");
                if (!(revision == null || revision == JSONObject.NULL) && !isPlainString(revision, 64))
                    throw fail("device_ai_host_invalid_argument"); // explicitly nullable
                break;
            case "test_event":
                requirePlainReference(reference, "event_id");
                long revisionNumber = metaLong(reference.opt("event_revision"));
                if (revisionNumber < 1 || revisionNumber > EVENT_REVISION_MAX)
                    throw fail("device_ai_host_invalid_argument");
                break;
            default:
                throw fail("device_ai_host_invalid_argument");
        }
    }

    private static void requirePlainReference(JSONObject reference, String key) {
        if (!isPlainString(reference.opt(key), 64)) throw fail("device_ai_host_invalid_argument");
    }

    /**
     * Closed prepare-wire selector check (P1-4c): the four open domains of the
     * server DeviceSelector Literal plus its model_validator semantics -
     * document_id absent => record_index must be absent, and tire/vehicle never
     * carry record_index (whole-observation domains). test_event fails here the
     * same way it fails the server DTO (N27 closed set, 422).
     */
    static void assertDeviceAiPrepareSelector(JSONObject selector) {
        if (selector == null || !PREPARE_SELECTOR_KINDS.contains(selector.optString("kind")))
            throw fail("device_ai_host_invalid_argument");
        assertDeviceAiAnySelector(selector);
        boolean hasDocumentId = !(selector.opt("document_id") == null || selector.opt("document_id") == JSONObject.NULL);
        boolean hasRecordIndex = !(selector.opt("record_index") == null || selector.opt("record_index") == JSONObject.NULL);
        if (!hasDocumentId && hasRecordIndex) throw fail("device_ai_host_invalid_argument");
        if (("tire".equals(selector.optString("kind")) || "vehicle".equals(selector.optString("kind"))) && hasRecordIndex)
            throw fail("device_ai_host_invalid_argument");
    }

    /** Selector as canonical AST input (fingerprint-spec section 2 item shape). */
    static Map<String, Object> selectorAst(JSONObject selector) {
        assertDeviceAiAnySelector(selector);
        String kind = selector.optString("kind");
        JSONObject reference = selector.optJSONObject("reference");
        Map<String, Object> referenceAst = new LinkedHashMap<>();
        putAst(referenceAst, "kind", reference.opt("kind"));
        if (!"test_event".equals(kind)) {
            putAst(referenceAst, "snapshot_id", reference.opt("snapshot_id"));
            if ("tire".equals(kind)) putAst(referenceAst, "variant_id", reference.opt("variant_id"));
            if ("recall".equals(kind)) {
                Object revision = reference.opt("recall_revision_id");
                putAst(referenceAst, "recall_revision_id", revision == JSONObject.NULL ? null : revision);
            }
            putAst(referenceAst, "verification_id", reference.opt("verification_id"));
        } else {
            putAst(referenceAst, "event_id", reference.opt("event_id"));
            referenceAst.put("event_revision", new DeviceAiJsonParser.NumberLexeme(
                Long.toString(metaLong(reference.opt("event_revision")))));
        }
        Object recordIndex = selector.opt("record_index");
        Map<String, Object> out = new LinkedHashMap<>();
        Object documentId = selector.opt("document_id");
        out.put("document_id", documentId == JSONObject.NULL ? null : documentId);
        out.put("kind", kind);
        out.put("member_key", selector.optString("member_key"));
        out.put("record_index", recordIndex == null || recordIndex == JSONObject.NULL
            ? null : new DeviceAiJsonParser.NumberLexeme(Long.toString(metaLong(recordIndex))));
        out.put("reference", referenceAst);
        return out;
    }

    private static void putAst(Map<String, Object> ast, String key, Object value) {
        ast.put(key, value == JSONObject.NULL ? null : value);
    }

    private static int byMemberKey(JSONObject left, JSONObject right) {
        return DeviceAiJsonParser.compareCodepoints(left.optString("member_key"), right.optString("member_key"));
    }

    private static List<JSONObject> selectorList(Object value) {
        if (!(value instanceof JSONArray)) throw fail("device_ai_host_invalid_argument");
        JSONArray array = (JSONArray) value;
        List<JSONObject> out = new ArrayList<>(array.length());
        for (int at = 0; at < array.length(); at++) {
            if (!(array.opt(at) instanceof JSONObject)) throw fail("device_ai_host_invalid_argument");
            out.add((JSONObject) array.opt(at));
        }
        return out;
    }

    /** fingerprint-spec section 2: member_key-ascending resolved closure digest. */
    static String selectionSha256(JSONArray resolved) {
        List<JSONObject> selectors = selectorList(resolved);
        // REQUESTED selectors are capped at 6 by the DTO; the RESOLVED closure may
        // grow past that after frozen_decision_closure dependency expansion (the
        // pack member bound is 200), so only non-empty/uniqueness fences apply.
        if (selectors.isEmpty() || selectors.size() > RESOLVED_CLOSURE_CAPACITY) throw fail("device_ai_host_invalid_argument");
        selectors.sort(DeviceAiHost::byMemberKey);
        Set<String> keys = new HashSet<>();
        List<Object> asts = new ArrayList<>(selectors.size());
        for (JSONObject selector : selectors) {
            if (!keys.add(selector.optString("member_key"))) throw fail("device_ai_host_invalid_argument");
            asts.add(selectorAst(selector));
        }
        return DeviceAiJsonParser.digest(asts, SELECTION_NAMESPACE);
    }

    // ---------------------------------------------------------------------
    // device_context_fingerprint (spec section 3). The SERVER value is
    // authoritative; this helper exists so a decoder can independently verify
    // it once the inputs are exposed. Archived numbers must enter as lexemes
    // (exact-AST inputs pass through untouched by exactAst()).
    // ---------------------------------------------------------------------

    static String deviceContextFingerprint(JSONObject input) {
        if (input == null || !isHash64(input.opt("package_sha256")) || !isHash64(input.opt("projection_sha256"))
            || !isHash64(input.opt("selection_sha256"))) throw fail("device_ai_host_invalid_argument");
        // Spec section 3: sort by the node's canonical bytes (codepoint/UTF-8 byte order),
        // but keep the ORIGINAL AST nodes (a JSON round-trip would destroy number lexemes).
        List<Object> citations = canonicalBytesOrdered(input.opt("device_citations"));
        List<Object> boundaries = canonicalBytesOrdered(input.opt("domain_boundaries"));
        JSONArray receiptSources = input.optJSONArray("receipt_sources");
        if (receiptSources == null) throw fail("device_ai_host_invalid_argument");
        List<JSONObject> sources = new ArrayList<>(receiptSources.length());
        for (int at = 0; at < receiptSources.length(); at++) {
            if (!(receiptSources.opt(at) instanceof JSONObject)) throw fail("device_ai_host_invalid_argument");
            sources.add((JSONObject) receiptSources.opt(at));
        }
        sources.sort((left, right) -> byMemberKey((JSONObject) left.opt("selector"), (JSONObject) right.opt("selector")));
        List<Object> sourceAsts = new ArrayList<>(sources.size());
        for (JSONObject source : sources) {
            Object selector = source.opt("selector");
            if (!(selector instanceof JSONObject) || !isPlainString(source.opt("selection_reason"), 256))
                throw fail("device_ai_host_invalid_argument");
            Map<String, Object> ast = new LinkedHashMap<>();
            ast.put("selection_reason", source.opt("selection_reason"));
            ast.put("selector", selectorAst((JSONObject) selector));
            ast.put("source", exactAst(source.opt("source")));
            sourceAsts.add(ast);
        }
        Map<String, Object> ast = new LinkedHashMap<>();
        ast.put("device_citations", citations);
        ast.put("domain_boundaries", boundaries);
        ast.put("numeric_encoding", DeviceAiJsonParser.NUMBER_TOKEN_SCHEMA);
        ast.put("package_id", plainString(input, "package_id", 64));
        ast.put("package_schema", plainString(input, "package_schema", 64));
        ast.put("package_sha256", input.opt("package_sha256"));
        ast.put("projection_mode", plainString(input, "projection_mode", 64));
        ast.put("projection_sha256", input.opt("projection_sha256"));
        ast.put("receipt_sources", sourceAsts);
        ast.put("schema", CONTEXT_SCHEMA);
        ast.put("selection_sha256", input.opt("selection_sha256"));
        return DeviceAiJsonParser.digest(ast, CONTEXT_NAMESPACE);
    }

    private static List<Object> canonicalBytesOrdered(Object value) {
        if (value == null || value == JSONObject.NULL) throw fail("device_ai_host_invalid_argument");
        List<?> nodes = (List<?>) exactAst(value);
        List<Object> out = new ArrayList<>(nodes.size());
        List<String> texts = new ArrayList<>(nodes.size());
        for (Object node : nodes) texts.add(DeviceAiJsonParser.canonical(node));
        List<Integer> order = new ArrayList<>(nodes.size());
        for (int at = 0; at < nodes.size(); at++) order.add(at);
        order.sort((left, right) -> DeviceAiJsonParser.compareCodepoints(texts.get(left), texts.get(right)));
        for (int index : order) out.add(nodes.get(index));
        return out;
    }

    // ---------------------------------------------------------------------
    // local_preview_fingerprint (spec section 4): frozen intent + origin +
    // selection closure + projection digest. `state` and the nullable
    // projection_sha256 stay in the input: blocked and ready are different
    // authorization objects and must never share a fingerprint.
    // ---------------------------------------------------------------------

    static String localPreviewFingerprint(JSONObject input) {
        if (input == null || !isHash64(input.opt("question_sha256"))) throw fail("device_ai_host_invalid_argument");
        String state = plainString(input, "state", 16);
        if (!state.equals("ready") && !state.equals("blocked")) throw fail("device_ai_host_invalid_argument");
        Object projection = input.opt("projection_sha256");
        if (projection == JSONObject.NULL) projection = null;
        if (projection != null && !isHash64(projection)) throw fail("device_ai_host_invalid_argument");
        if (state.equals("blocked") && projection != null) throw fail("device_ai_host_invalid_argument");
        List<JSONObject> selected = selectorList(input.opt("selected"));
        List<JSONObject> closure = selectorList(input.opt("resolved_closure"));
        if (selected.isEmpty() || closure.isEmpty()) throw fail("device_ai_host_invalid_argument");
        JSONObject origin = input.optJSONObject("origin");
        requireOrigin(origin);
        Map<String, Object> intent = new LinkedHashMap<>();
        List<Object> includeIds = new ArrayList<>();
        JSONArray rawIds = input.optJSONArray("include_context_ids");
        // M4 (decoder-spec section 3): include_context_ids must stay EMPTY until the
        // frozen wire opens the archive-id intent channel; a non-empty list fails
        // closed before entering the fingerprint AST.
        if (rawIds != null && rawIds.length() > 0) throw fail("device_ai_host_invalid_argument");
        if (rawIds != null) for (int at = 0; at < rawIds.length(); at++)
            includeIds.add(plainString(rawIds, at, 128));
        intent.put("include_context_ids", includeIds);
        intent.put("policy_version", PROJECTION_POLICY_VERSION);
        intent.put("purpose", "device_history_analysis");
        intent.put("question_sha256", input.opt("question_sha256"));
        Map<String, Object> originAst = new LinkedHashMap<>();
        originAst.put("expected_byte_count", new DeviceAiJsonParser.NumberLexeme(
            Long.toString(positiveMetaLong(origin, "expected_byte_count"))));
        originAst.put("expected_generation", new DeviceAiJsonParser.NumberLexeme(
            Long.toString(positiveMetaLong(origin, "expected_generation"))));
        originAst.put("expected_owner_epoch", new DeviceAiJsonParser.NumberLexeme(
            Long.toString(positiveMetaLong(origin, "expected_owner_epoch"))));
        originAst.put("expected_profile_id", plainString(origin, "expected_profile_id", 64));
        originAst.put("expected_sha256", origin.opt("expected_sha256"));
        originAst.put("owner_scope_id", origin.opt("owner_scope_id"));
        originAst.put("package_id", plainString(origin, "package_id", 64));
        originAst.put("package_schema", plainString(origin, "package_schema", 64));
        originAst.put("slot_id", plainString(origin, "slot_id", 64));
        List<Object> closureAsts = new ArrayList<>(closure.size());
        for (JSONObject selector : closure) closureAsts.add(selectorAst(selector));
        List<Object> selectedAsts = new ArrayList<>(selected.size());
        for (JSONObject selector : selected) selectedAsts.add(selectorAst(selector));
        Map<String, Object> ast = new LinkedHashMap<>();
        ast.put("intent", intent);
        ast.put("origin", originAst);
        ast.put("projection_mode", plainString(input, "projection_mode", 64));
        ast.put("projection_sha256", projection);
        ast.put("query_context", exactAst(input.opt("query_context")));
        ast.put("resolved_closure", closureAsts);
        ast.put("selected", selectedAsts);
        ast.put("state", state);
        return DeviceAiJsonParser.digest(ast, LOCAL_PREVIEW_NAMESPACE);
    }

    private static void requireOrigin(JSONObject origin) {
        if (origin == null || !isHash64(origin.opt("expected_sha256")) || !isHash64(origin.opt("owner_scope_id"))
            || !isPlainString(origin.opt("package_id"), 64) || !isPlainString(origin.opt("slot_id"), 64)
            || !isPlainString(origin.opt("expected_profile_id"), 64)
            || !isPlainString(origin.opt("package_schema"), 64)) throw fail("device_ai_host_invalid_argument");
        positiveMetaLong(origin, "expected_byte_count");
        positiveMetaLong(origin, "expected_owner_epoch");
        positiveMetaLong(origin, "expected_generation");
    }

    private static String plainString(JSONArray array, int index, int max) {
        if (!isPlainString(array.opt(index), max)) throw fail("device_ai_host_invalid_argument");
        return array.optString(index);
    }

    // ---------------------------------------------------------------------
    // computeLocalPreview - local recomputation from the ORIGINAL package
    // bytes, for showing "the fingerprints about to leave this device" BEFORE
    // any export consent. Server-independent; makes no attestation claim (B01).
    // ---------------------------------------------------------------------

    static JSONObject computeLocalPreview(byte[] packageBytes, JSONObject request) {
        if (packageBytes == null || packageBytes.length == 0) throw fail("device_ai_host_invalid_argument");
        if (request == null) throw fail("device_ai_host_invalid_argument");
        JSONObject origin = request.optJSONObject("origin");
        if (origin == null || !isHash64(origin.opt("expected_sha256"))) throw fail("device_ai_host_invalid_argument");
        long expectedBytes = positiveMetaLong(origin, "expected_byte_count");
        if (expectedBytes != packageBytes.length) throw fail("device_ai_host_package_mismatch");
        Object requestedMode = request.opt("projection_mode");
        if (requestedMode != null && requestedMode != JSONObject.NULL && !"single_observation".equals(requestedMode))
            throw fail("device_ai_host_preview_unsupported"); // frozen_decision_closure needs the full closure re-computation (phase B)
        Object rawSelectors = request.opt("selectors");
        List<JSONObject> selectors = selectorList(rawSelectors);
        if (selectors.size() != 1) throw fail("device_ai_host_preview_unsupported"); // phase A: exactly one tire selector
        for (JSONObject selector : selectors) assertDeviceAiSelector(selector);
        String packageSha = sha256Hex(packageBytes);
        if (!packageSha.equals(origin.opt("expected_sha256"))) throw fail("device_ai_host_package_mismatch");

        Object envelope = DeviceAiJsonParser.parse(packageBytes); // closed DeviceAiProjectionError codes propagate
        Map<String, Object> record = asAstObject(envelope, "device_ai_host_invalid_argument");
        Object schema = record.get("schema");
        if (!"offline-pack@1".equals(schema) && !"offline-pack@2".equals(schema))
            throw fail("device_ai_host_invalid_argument");
        if (!java.util.Objects.equals(record.get("package_id"), origin.opt("package_id"))
            || !java.util.Objects.equals(record.get("owner_scope_id"), origin.opt("owner_scope_id")))
            throw fail("device_ai_host_package_mismatch");
        if (!(record.get("members") instanceof List)) throw fail("device_ai_host_invalid_argument");
        List<?> members = (List<?>) record.get("members");

        List<String> located = new ArrayList<>(selectors.size());
        for (JSONObject selector : selectors) {
            Map<String, Object> expected = selectorAst(selector);
            String expectedReference = DeviceAiJsonParser.canonical(expected.get("reference"));
            boolean found = false;
            for (Object rawMember : members) {
                if (!(rawMember instanceof Map)) continue;
                Map<?, ?> member = (Map<?, ?>) rawMember;
                if (!java.util.Objects.equals(member.get("member_key"), selector.opt("member_key"))) continue;
                Object reference = member.get("reference");
                if (reference == null || !expectedReference.equals(DeviceAiJsonParser.canonical(reference))) continue;
                found = true;
                break;
            }
            if (!found) throw fail("device_ai_host_package_mismatch");
            located.add(selector.optString("member_key"));
        }

        String normalized = normalizeQuestion(request.optString("question"));
        String questionHash = questionSha256(normalized);
        // single_observation: resolved closure == requested selection (no dependency
        // expansion in phase A); selection_sha256 therefore binds exactly what the
        // server recomputes for the same selectors.
        String selectionHash = selectionSha256((JSONArray) rawSelectors);
        JSONObject previewInput = new JSONObject();
        put(previewInput, "question_sha256", questionHash);
        put(previewInput, "include_context_ids", request.optJSONArray("include_context_ids") == null
            ? new JSONArray() : request.optJSONArray("include_context_ids"));
        put(previewInput, "projection_mode", "single_observation");
        put(previewInput, "query_context", JSONObject.NULL);
        put(previewInput, "origin", origin);
        put(previewInput, "selected", rawSelectors);
        put(previewInput, "resolved_closure", rawSelectors);
        put(previewInput, "state", "ready");
        put(previewInput, "projection_sha256", JSONObject.NULL);
        String previewFingerprint = localPreviewFingerprint(previewInput);

        JSONObject summary = new JSONObject();
        put(summary, "question_sha256", questionHash);
        put(summary, "selection_sha256", selectionHash);
        put(summary, "local_preview_fingerprint", previewFingerprint);
        put(summary, "package_sha256", packageSha);
        put(summary, "package_byte_count", (long) packageBytes.length);
        put(summary, "package_schema", schema);
        JSONArray locatedKeys = new JSONArray();
        for (String key : located) put(locatedKeys, key);
        put(summary, "located_member_keys", locatedKeys);
        put(summary, "projection_binding", "not_recomputed");
        JSONArray notices = new JSONArray();
        put(notices, "本预览为本地重算：question_sha256 / selection_sha256 / local_preview_fingerprint 均不依赖服务端。");
        put(notices, "projection_sha256 未在本机重算（需投影核完整复刻并通过向量对拍）；服务端 prepare 会以 expected_projection_sha256 复核为准。");
        put(notices, "device_context_fingerprint 由服务端从自有投影权威计算（fingerprint-spec 第 3 节），Host 只读取/转发。");
        put(summary, "notices", notices);
        return summary;
    }

    // ---------------------------------------------------------------------
    // DeviceAiJournal - encrypted append-only journal with five fences.
    //
    // Storage layout (one opaque byte blob, Host-owned store):
    //   { "schema": "device-ai-journal@1", "owner": <str>, "generation": <int>,
    //     "iv_hex": <24 hex chars>, "ciphertext_base64": <str> }
    // ciphertext = AES-GCM(canonical({entries:[...]}), aad = canonical(
    //   ["device-ai-journal@1", owner]) ). Key and store are Host-injected.
    // ---------------------------------------------------------------------

    /** Six journal event classes with closed key sets (Java strengthening of the TS discriminated union). */
    static final Map<String, List<String>> JOURNAL_EVENT_FIELDS = java.util.Collections.unmodifiableMap(new LinkedHashMap<>(Map.of(
        "preview_shown", List.of("type", "intent_id", "local_preview_fingerprint", "question_sha256", "package_sha256"),
        "decision_made", List.of("type", "intent_id", "decision", "local_preview_fingerprint"),
        "prepare_created", List.of("type", "intent_id", "prepare_id", "idempotency_key", "projection_sha256", "device_context_fingerprint"),
        "claim_submitted", List.of("type", "intent_id", "prepare_id", "analysis_key", "question_sha256"),
        "outcome_observed", List.of("type", "intent_id", "analysis_key", "request_id", "state"),
        "failure_observed", List.of("type", "intent_id", "stage", "code"))));

    /** AES-GCM sealing with 12-byte random nonce; sealed = nonce || ciphertext+tag. Key is Host-injected. */
    public interface Sealer {
        byte[] seal(byte[] clear, byte[] aad) throws Exception;
        byte[] open(byte[] sealed, byte[] aad) throws Exception;
    }

    /** Host-owned whole-blob store (load whole encrypted blob or null; persist atomically). */
    public interface Store {
        byte[] load() throws Exception;
        void save(byte[] blob) throws Exception;
    }

    static final class JournalVerification {
        final boolean ok;
        final int length;
        final List<String[]> violations; // {code, sequence-or-null}
        final List<String[]> crossSessionEntries; // {sequence, session_id}
        JournalVerification(boolean ok, int length, List<String[]> violations, List<String[]> crossSessionEntries) {
            this.ok = ok; this.length = length; this.violations = violations; this.crossSessionEntries = crossSessionEntries;
        }
        JSONObject toJson() {
            JSONObject out = new JSONObject();
            put(out, "ok", ok);
            put(out, "length", (long) length);
            JSONArray rawViolations = new JSONArray();
            for (String[] violation : violations) {
                JSONObject row = new JSONObject();
                put(row, "code", violation[0]);
                put(row, "sequence", violation[1] == null ? JSONObject.NULL : Long.parseLong(violation[1]));
                put(rawViolations, row);
            }
            put(out, "violations", rawViolations);
            JSONArray cross = new JSONArray();
            for (String[] entry : crossSessionEntries) {
                JSONObject row = new JSONObject();
                put(row, "sequence", Long.parseLong(entry[0]));
                put(row, "session_id", entry[1]);
                put(cross, row);
            }
            put(out, "cross_session_entries", cross);
            return out;
        }
    }

    static final class DeviceAiJournal {
        static final String GENESIS_HASH = "0".repeat(64);
        private final String owner;
        private final long generation;
        private final String sessionId;
        private final Sealer sealer;
        private final Store store;
        private final LongSupplier monotonicNow;
        private final Supplier<String> wallNow;

        DeviceAiJournal(String owner, long generation, String sessionId, Sealer sealer, Store store,
            LongSupplier monotonicNow, Supplier<String> wallNow) {
            if (!isPlainString(owner, 128) || generation < 1 || generation > SAFE_INTEGER
                || !isPlainString(sessionId, 128) || sealer == null || store == null || monotonicNow == null)
                throw fail("device_ai_host_invalid_argument");
            this.owner = owner; this.generation = generation; this.sessionId = sessionId;
            this.sealer = sealer; this.store = store; this.monotonicNow = monotonicNow;
            this.wallNow = wallNow == null ? () -> java.time.Instant.now().toString() : wallNow;
        }

        String owner() { return owner; }
        long generation() { return generation; }
        String sessionId() { return sessionId; }

        private byte[] aad() {
            List<Object> binding = new ArrayList<>(2);
            binding.add(JOURNAL_SCHEMA);
            binding.add(owner);
            return DeviceAiJsonParser.canonicalBytes(binding);
        }

        private byte[] seal(List<JSONObject> entries) throws Exception {
            List<Object> entryAsts = new ArrayList<>(entries.size());
            for (JSONObject entry : entries) entryAsts.add(jsonToAst(entry));
            Map<String, Object> plaintextAst = new LinkedHashMap<>();
            plaintextAst.put("entries", entryAsts);
            byte[] ivAndCiphertext = sealer.seal(DeviceAiJsonParser.canonicalBytes(plaintextAst), aad());
            if (ivAndCiphertext.length < 12 + 16) throw fail("device_ai_host_journal_corrupt");
            byte[] nonce = java.util.Arrays.copyOfRange(ivAndCiphertext, 0, 12);
            StringBuilder ivHex = new StringBuilder(24);
            for (byte value : nonce) ivHex.append(Character.forDigit((value >> 4) & 0xF, 16)).append(Character.forDigit(value & 0xF, 16));
            JSONObject blob = new JSONObject();
            put(blob, "schema", JOURNAL_SCHEMA);
            put(blob, "owner", owner);
            put(blob, "generation", generation);
            put(blob, "iv_hex", ivHex.toString());
            put(blob, "ciphertext_base64", Base64.getEncoder().encodeToString(
                java.util.Arrays.copyOfRange(ivAndCiphertext, 12, ivAndCiphertext.length)));
            return blob.toString().getBytes(StandardCharsets.UTF_8);
        }

        private List<JSONObject> unseal(byte[] blob) throws Exception {
            JSONObject wire;
            try { wire = new JSONObject(new String(blob, StandardCharsets.UTF_8)); }
            catch (JSONException invalid) { throw fail("device_ai_host_journal_corrupt"); }
            if (!JOURNAL_SCHEMA.equals(wire.optString("schema")) || !isPlainString(wire.opt("owner"), 128)
                || !(wire.opt("generation") instanceof Number) || metaLong(wire.opt("generation")) < 1
                || !(wire.opt("iv_hex") instanceof String) || ((String) wire.opt("iv_hex")).length() != 24
                || !((String) wire.opt("iv_hex")).matches("[0-9a-f]+")
                || !(wire.opt("ciphertext_base64") instanceof String))
                throw fail("device_ai_host_journal_corrupt");
            // Fence 1 (owner) - explicit header check; the AAD below is the
            // cryptographic layer of the same fence: a blob saved under another
            // owner simply fails to decrypt.
            if (!owner.equals(wire.opt("owner"))) throw fail("device_ai_host_journal_owner_mismatch");
            // Fence 2 (generation) - a rebuilt journal (generation+1) voids old blobs.
            if (metaLong(wire.opt("generation")) != generation) throw fail("device_ai_host_journal_generation_mismatch");
            String ivHex = (String) wire.opt("iv_hex");
            byte[] nonce = new byte[12];
            for (int at = 0; at < 12; at++) nonce[at] = (byte) Integer.parseInt(ivHex.substring(at * 2, at * 2 + 2), 16);
            byte[] ciphertext;
            try { ciphertext = Base64.getDecoder().decode((String) wire.opt("ciphertext_base64")); }
            catch (IllegalArgumentException invalid) { throw fail("device_ai_host_journal_corrupt"); }
            byte[] sealed = new byte[12 + ciphertext.length];
            System.arraycopy(nonce, 0, sealed, 0, 12);
            System.arraycopy(ciphertext, 0, sealed, 12, ciphertext.length);
            byte[] plaintext;
            try { plaintext = sealer.open(sealed, aad()); }
            catch (Exception denied) { throw fail("device_ai_host_journal_corrupt"); }
            Object parsed;
            try { parsed = DeviceAiJsonParser.parse(plaintext); }
            catch (RuntimeException invalid) { throw fail("device_ai_host_journal_corrupt"); }
            if (!(parsed instanceof Map) || !(((Map<?, ?>) parsed).get("entries") instanceof List))
                throw fail("device_ai_host_journal_corrupt");
            List<?> rawEntries = (List<?>) ((Map<?, ?>) parsed).get("entries");
            List<JSONObject> entries = new ArrayList<>(rawEntries.size());
            for (Object entry : rawEntries) {
                if (!(entry instanceof Map)) throw fail("device_ai_host_journal_corrupt");
                entries.add((JSONObject) astToJson(entry));
            }
            return entries;
        }

        /** Structural verification (fences 1/2/4/5 + chain shape of fence 3) without hash re-computation. */
        private JournalVerification structureCheck(List<JSONObject> entries) {
            List<String[]> violations = new ArrayList<>();
            List<String[]> crossSession = new ArrayList<>();
            String previousHash = GENESIS_HASH;
            long previousClock = Long.MIN_VALUE;
            for (int index = 0; index < entries.size(); index++) {
                JSONObject entry = entries.get(index);
                long sequence = index + 1;
                if (entry == null || !JOURNAL_ENTRY_SCHEMA.equals(entry.optString("schema"))
                    || !(entry.opt("sequence") instanceof Number) || !isHash64(entry.opt("entry_sha256"))
                    || !isHash64(entry.opt("prev_sha256"))) {
                    violations.add(new String[] {"device_ai_host_journal_corrupt", Long.toString(sequence)});
                    continue;
                }
                // Fence 3 (SHA): chain continuity + sequence numbering (hash re-computation in verifyIntegrityOf).
                if (metaLong(entry.opt("sequence")) != sequence) violations.add(new String[] {"device_ai_host_journal_chain_broken", Long.toString(sequence)});
                if (!entry.optString("prev_sha256").equals(previousHash)) violations.add(new String[] {"device_ai_host_journal_chain_broken", Long.toString(sequence)});
                // Fences 1/2 apply per entry as well (defense in depth under the header).
                if (!owner.equals(entry.optString("owner"))) violations.add(new String[] {"device_ai_host_journal_owner_mismatch", Long.toString(sequence)});
                if (!(entry.opt("generation") instanceof Number) || metaLong(entry.opt("generation")) != generation)
                    violations.add(new String[] {"device_ai_host_journal_generation_mismatch", Long.toString(sequence)});
                // Fence 4 (clock): strictly increasing monotonic timestamps, no replay of an
                // older entry after a newer one, no clock rollback.
                if (!(entry.opt("clock") instanceof Number) || metaLong(entry.opt("clock")) <= previousClock)
                    violations.add(new String[] {"device_ai_host_journal_clock_regression", Long.toString(sequence)});
                // Fence 5 (session): recorded, but never fails readAll - recovery reads the
                // ledger; cross-session authorization is blocked at consumption.
                if (!sessionId.equals(entry.optString("session_id")))
                    crossSession.add(new String[] {Long.toString(sequence), entry.optString("session_id")});
                previousHash = entry.optString("entry_sha256");
                previousClock = metaLong(entry.opt("clock"));
            }
            return new JournalVerification(violations.isEmpty(), entries.size(), violations, crossSession);
        }

        /** Entry hash input: the entry WITHOUT entry_sha256, canonicalized. */
        private Object entryHashAst(JSONObject entry) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("clock", new DeviceAiJsonParser.NumberLexeme(Long.toString(metaLong(entry.opt("clock")))));
            out.put("event", jsonToAst(entry.opt("event")));
            out.put("generation", new DeviceAiJsonParser.NumberLexeme(Long.toString(metaLong(entry.opt("generation")))));
            out.put("owner", entry.optString("owner"));
            out.put("prev_sha256", entry.optString("prev_sha256"));
            out.put("schema", entry.optString("schema"));
            out.put("sequence", new DeviceAiJsonParser.NumberLexeme(Long.toString(metaLong(entry.opt("sequence")))));
            out.put("session_id", entry.optString("session_id"));
            out.put("wall_clock", entry.optString("wall_clock"));
            return out;
        }

        private JournalVerification verifyIntegrityOf(List<JSONObject> entries) {
            JournalVerification verification = structureCheck(entries);
            List<String[]> violations = new ArrayList<>(verification.violations);
            // Fence 3 (SHA): full per-entry hash re-computation over the canonical form.
            for (int index = 0; index < entries.size(); index++) {
                JSONObject entry = entries.get(index);
                if (entry == null || !isHash64(entry.opt("entry_sha256"))) continue;
                String hash = sha256Hex(DeviceAiJsonParser.canonicalBytes(entryHashAst(entry)));
                if (!hash.equals(entry.optString("entry_sha256")))
                    violations.add(new String[] {"device_ai_host_journal_entry_tampered", Long.toString(index + 1)});
            }
            return new JournalVerification(violations.isEmpty(), entries.size(), violations, verification.crossSessionEntries);
        }

        private static void assertEvent(JSONObject event) {
            if (event == null) throw fail("device_ai_host_invalid_argument");
            String type = event.optString("type");
            List<String> fields = JOURNAL_EVENT_FIELDS.get(type);
            if (fields == null) throw fail("device_ai_host_invalid_argument");
            Set<String> expected = new LinkedHashSet<>(fields);
            for (String key : keyNames(event)) if (!expected.contains(key)) throw fail("device_ai_host_invalid_argument");
            for (String key : fields) if (!event.has(key)) throw fail("device_ai_host_invalid_argument");
        }

        JSONObject append(JSONObject event) throws Exception {
            assertEvent(event);
            byte[] blob = store.load();
            List<JSONObject> entries = blob == null ? new ArrayList<>() : unseal(blob);
            JournalVerification structural = structureCheck(entries);
            if (!structural.ok) throw fail(structural.violations.get(0)[0]);
            JSONObject tail = entries.isEmpty() ? null : entries.get(entries.size() - 1);
            long clock = monotonicNow.getAsLong();
            // Fence 4 at write time: the new entry must strictly advance the clock.
            if (tail != null && clock <= metaLong(tail.opt("clock"))) throw fail("device_ai_host_journal_clock_regression");
            JSONObject draft = new JSONObject();
            put(draft, "schema", JOURNAL_ENTRY_SCHEMA);
            put(draft, "sequence", (long) entries.size() + 1);
            put(draft, "owner", owner);           // fence 1 stamped at write time
            put(draft, "generation", generation); // fence 2 stamped at write time
            put(draft, "session_id", sessionId);  // fence 5 stamped at write time
            put(draft, "clock", clock);
            put(draft, "wall_clock", wallNow.get());
            put(draft, "event", event);
            put(draft, "prev_sha256", tail == null ? GENESIS_HASH : tail.optString("entry_sha256"));
            JSONObject entry = copyOf(draft);
            put(entry, "entry_sha256", sha256Hex(DeviceAiJsonParser.canonicalBytes(entryHashAst(draft))));
            List<JSONObject> all = new ArrayList<>(entries);
            all.add(entry);
            store.save(seal(all));
            return (JSONObject) cloneJson(entry);
        }

        /** Decrypt + full verification. Fence violations throw their closed code. */
        List<JSONObject> readAll() throws Exception {
            byte[] blob = store.load();
            if (blob == null) return new ArrayList<>();
            List<JSONObject> entries = unseal(blob);
            JournalVerification verification = verifyIntegrityOf(entries);
            if (!verification.ok) throw fail(verification.violations.get(0)[0]);
            List<JSONObject> out = new ArrayList<>(entries.size());
            for (JSONObject entry : entries) out.add((JSONObject) cloneJson(entry));
            return out;
        }

        /** Full five-fence report; never throws on fence violations (audit view). */
        JournalVerification verifyIntegrity() {
            byte[] blob;
            try { blob = store.load(); }
            catch (Exception unreadable) { throw new IllegalStateException("journal store unreadable", unreadable); }
            if (blob == null) return new JournalVerification(true, 0, new ArrayList<>(), new ArrayList<>());
            try {
                return verifyIntegrityOf(unseal(blob));
            } catch (DeviceAiHostException cause) {
                // owner/generation/corrupt fences surface from unseal itself.
                List<String[]> violations = new ArrayList<>();
                violations.add(new String[] {cause.code, null});
                return new JournalVerification(false, 0, violations, new ArrayList<>());
            } catch (Exception cause) {
                throw new IllegalStateException("journal store unreadable", cause);
            }
        }

        /** Fence 5 hard gate: every entry must belong to the current session. */
        void assertSameSession(List<JSONObject> entries) {
            for (JSONObject entry : entries)
                if (!sessionId.equals(entry.optString("session_id"))) throw fail("device_ai_host_journal_session_mismatch");
        }
    }

    static Object cloneJson(Object value) {
        if (value instanceof JSONObject) {
            JSONObject source = (JSONObject) value, out = new JSONObject();
            for (String key : keyNames(source)) put(out, key, cloneJson(source.opt(key)));
            return out;
        }
        if (value instanceof JSONArray) {
            JSONArray source = (JSONArray) value, out = new JSONArray();
            for (int at = 0; at < source.length(); at++) put(out, cloneJson(source.opt(at)));
            return out;
        }
        return value;
    }

    // ---------------------------------------------------------------------
    // DeviceAiHostClient - prepare/lookup/read + stream submit + attempt lookup.
    // ---------------------------------------------------------------------

    public interface Transport {
        HttpExchange exchange(String method, String path, Map<String, String> headers, byte[] body) throws Exception;
    }

    public static final class HttpExchange {
        public final int status;
        public final byte[] body;
        public HttpExchange(int status, byte[] body) { this.status = status; this.body = body; }
    }

    /** Production transport over the single native network authority (NativeHttpBridge). */
    static final class NativeBridgeTransport implements Transport {
        private final NativeHttpBridge bridge;
        NativeBridgeTransport(NativeHttpBridge bridge) { this.bridge = bridge; }
        @Override public HttpExchange exchange(String method, String path, Map<String, String> headers, byte[] body) throws Exception {
            String id = java.util.UUID.randomUUID().toString();
            RequestRegistry.Ticket ticket = bridge.registry.register(id);
            try {
                NativePolicy.Request request = NativePolicy.request(id, path, method, new LinkedHashMap<>(headers),
                    body == null ? null : Base64.getEncoder().encodeToString(body), bytes -> true);
                com.getcapacitor.JSObject result = bridge.request(request, ticket);
                byte[] received = NativePolicy.decode(result.getString("body_base64"),
                    NativePolicy.MAX_RESPONSE_BYTES, "RESPONSE_TOO_LARGE");
                return new HttpExchange(result.getInteger("status", 0), received);
            } finally {
                bridge.registry.complete(ticket);
            }
        }
    }

    static DeviceAiHostClient clientOver(NativeHttpBridge bridge) {
        return new DeviceAiHostClient(new NativeBridgeTransport(bridge));
    }

    /** Closed-body assertion against the frozen server field lists (self-test anchor). */
    static void assertClosedFields(JSONObject body, List<String> fields, String label) {
        Set<String> expected = new LinkedHashSet<>(fields);
        List<String> extra = new ArrayList<>(), missing = new ArrayList<>();
        for (String key : keyNames(body)) if (!expected.contains(key)) extra.add(key);
        for (String key : fields) if (!body.has(key)) missing.add(key);
        if (!extra.isEmpty() || !missing.isEmpty())
            throw new IllegalStateException(label + " 字段与服务端 closed DTO 不一致（多余: " + String.join(",", extra)
                + (extra.isEmpty() ? "无" : "") + "; 缺失: " + (missing.isEmpty() ? "无" : String.join(",", missing)) + "）");
    }

    static void assertPrepareBody(JSONObject body) {
        assertClosedFields(body, PREPARE_REQUEST_FIELDS, "DeviceAIPrepareRequest");
        if (!isPlainString(body.opt("package_id"), 64)) throw fail("device_ai_host_invalid_argument");
        requireHash64(body.opt("expected_sha256"));
        requireHash64(body.opt("expected_owner_scope_id"));
        requireHash64(body.opt("expected_projection_sha256"));
        requireHash64(body.opt("question_sha256"));
        positiveMetaLong(body, "expected_byte_count");
        String schema = body.optString("expected_schema");
        if (!schema.equals("offline-pack@1") && !schema.equals("offline-pack@2")) throw fail("device_ai_host_invalid_argument");
        if (!PREPARE_PROJECTION_MODES.contains(body.optString("projection_mode"))) throw fail("device_ai_host_invalid_argument");
        List<JSONObject> selectors = selectorList(body.opt("selectors"));
        if (selectors.isEmpty() || selectors.size() > SELECTOR_CAPACITY) throw fail("device_ai_host_invalid_argument");
        Set<String> keys = new HashSet<>();
        for (JSONObject selector : selectors) {
            assertDeviceAiPrepareSelector(selector);
            if (!keys.add(selector.optString("member_key"))) throw fail("device_ai_host_invalid_argument");
        }
        Object closure = body.opt("approved_closure");
        boolean hasClosure = closure != null && closure != JSONObject.NULL;
        if (body.optString("projection_mode").equals("frozen_decision_closure")) {
            // frozen mode: approved_closure is a REQUIRED, exact, 1..SELECTOR_CAPACITY
            // list of four-domain selectors ('必须显式提供 approved_closure（精确相等清单）').
            if (!hasClosure) throw fail("device_ai_host_invalid_argument");
            List<JSONObject> closureSelectors = selectorList(closure);
            if (closureSelectors.isEmpty() || closureSelectors.size() > SELECTOR_CAPACITY)
                throw fail("device_ai_host_invalid_argument");
            // D5 (decoder-spec 2.6): closure member_key uniqueness — the same fence
            // as the requested selector list, asserted at the decoder layer (Rust
            // parity) instead of relying only on the builder's equality gate.
            Set<String> closureKeys = new HashSet<>();
            for (JSONObject selector : closureSelectors) {
                assertDeviceAiPrepareSelector(selector);
                if (!closureKeys.add(selector.optString("member_key"))) throw fail("device_ai_host_invalid_argument");
            }
        } else if (hasClosure) throw fail("device_ai_host_invalid_argument");
        canonicalUuid(body.optString("host_receipt_id"));
        canonicalUuid(body.optString("intent_id"));
    }

    /** Ordered copy carrying exactly the closed fields (used for closed-set validation). */
    static JSONObject orderedCopy(JSONObject source, List<String> fields) {
        JSONObject out = new JSONObject();
        for (String field : fields) {
            Object value = source.opt(field);
            if (value != null) put(out, field, value);
        }
        return out;
    }

    /**
     * Deterministic closed-DTO wire emission: keys serialized in the frozen field
     * list order. org.json's backing map order is NOT contractual (the JVM test
     * artifact is HashMap-backed while Android's runtime is LinkedHashMap), so the
     * wire bytes are emitted by walking the frozen list; rawOverrides carry
     * already-encoded nested DTOs. Mirrors the TS object literal field order.
     */
    private static String objectWire(List<String> fields, JSONObject source, Map<String, String> rawOverrides) {
        StringBuilder out = new StringBuilder("{");
        boolean head = true;
        for (String field : fields) {
            Object value = source.opt(field);
            String raw = rawOverrides.get(field);
            if (raw == null && value == null) continue;
            if (!head) out.append(',');
            head = false;
            out.append('"').append(field).append("\":");
            if (raw != null) out.append(raw);
            else if (value instanceof String) out.append(JSONObject.quote((String) value));
            else out.append(value.toString()); // JSONObject/JSONArray/Long/Boolean/NULL sentinel
        }
        return out.append('}').toString();
    }

    static JSONObject checkedPrepareView(JSONObject value) {
        if (value == null) throw new IllegalStateException("设备 AI 准备记录响应格式不完整。");
        if (!isPlainString(value.opt("id"), 64) || !isPlainString(value.opt("pack_id"), 64)
            || !isHash64(value.opt("projection_sha256")) || !isHash64(value.opt("device_context_fingerprint"))
            || !isHash64(value.opt("question_sha256")) || !isHash64(value.opt("selection_sha256"))
            || !(value.opt("replayed") instanceof Boolean) || !(value.opt("expired") instanceof Boolean)
            || !isPlainString(value.opt("expires_at"), 64) || !parseableTime(value.optString("expires_at")))
            throw new IllegalStateException("设备 AI 准备记录响应格式不完整。");
        return value;
    }

    /** Closed subset of the sealed TS checkedAIStreamDetail shape check. */
    static JSONObject checkedStreamDetail(JSONObject value) {
        if (value == null || !"ai-streams@1".equals(value.optString("schema")) || !"session".equals(value.optString("scope")))
            throw new IllegalStateException("AI 进度记录与当前请求不匹配或格式不完整。");
        JSONObject execution = value.optJSONObject("execution");
        if (execution == null || !(execution.opt("terminal") instanceof Boolean) || !isPlainString(execution.opt("state"), 64))
            throw new IllegalStateException("AI 进度记录与当前请求不匹配或格式不完整。");
        if (!isPlainString(value.opt("cursor"), 512) || !isPlainString(value.opt("server_time"), 64)
            || !parseableTime(value.optString("server_time")))
            throw new IllegalStateException("AI 进度记录与当前请求不匹配或格式不完整。");
        JSONObject analysis = value.optJSONObject("analysis");
        if (analysis == null || !isPlainString(analysis.opt("id"), 64) || !isPlainString(analysis.opt("pack_id"), 64)
            || !(analysis.opt("question") instanceof String) || !isPlainString(analysis.opt("state"), 64))
            throw new IllegalStateException("AI 进度记录与当前请求不匹配或格式不完整。");
        JSONArray claims = value.optJSONArray("draft_claims");
        if (claims == null || claims.length() > 12) throw new IllegalStateException("AI 进度记录与当前请求不匹配或格式不完整。");
        Object uncertainty = value.opt("draft_uncertainty");
        if (!(uncertainty == null || uncertainty == JSONObject.NULL
            || (uncertainty instanceof String && questionCodepoints((String) uncertainty) <= 2000)))
            throw new IllegalStateException("AI 进度记录与当前请求不匹配或格式不完整。");
        String state = execution.optString("state");
        String expected = state.equals("accepted") || state.equals("running") ? "pending" : state;
        if (!analysis.optString("state").equals(expected)) throw new IllegalStateException("AI 进度记录与当前请求不匹配或格式不完整。");
        return value;
    }

    private static boolean parseableTime(String value) {
        try { OffsetDateTime.parse(value); return true; }
        catch (Exception invalid) { return false; }
    }

    static final class DeviceAiHostClient {
        private final Transport transport;
        DeviceAiHostClient(Transport transport) {
            if (transport == null) throw fail("device_ai_host_invalid_argument");
            this.transport = transport;
        }

        private JSONObject dispatch(String method, String path, Map<String, String> headers, byte[] body) throws NativeFailure {
            HttpExchange exchange;
            try {
                exchange = transport.exchange(method, path, headers, body);
            } catch (NativeFailure passthrough) {
                throw passthrough; // existing closed transport error mapping stays untouched
            } catch (Exception failure) {
                throw new IllegalStateException("device-ai transport failed", failure);
            }
            if (exchange.status < 200 || exchange.status > 299) throw parseHttpFailure(exchange);
            try {
                return new JSONObject(new String(exchange.body, StandardCharsets.UTF_8));
            } catch (JSONException invalid) {
                throw new IllegalStateException("设备 AI 响应不是完整 JSON。");
            }
        }

        private static DeviceAiHostException parseHttpFailure(HttpExchange exchange) {
            String serverCode = null, message = null;
            try {
                JSONObject parsed = new JSONObject(new String(exchange.body, StandardCharsets.UTF_8));
                Object detail = parsed.opt("detail");
                if (detail instanceof String) message = (String) detail;
                else if (detail instanceof JSONObject) {
                    JSONObject object = (JSONObject) detail;
                    if (object.opt("message") instanceof String) message = object.optString("message");
                    Object code = object.opt("code");
                    if (code instanceof String && ((String) code).matches("[a-zA-Z0-9_@.-]{1,100}")) serverCode = (String) code;
                }
            } catch (Exception ignored) { /* a proxy may answer a non-JSON body */ }
            return DeviceAiHostException.http(exchange.status, serverCode, message);
        }

        /**
         * POST /v1/ai/device-evidence-packs - metadata-only prepare. `key` is the
         * Idempotency-Key UUID (same key + same body replays the original result;
         * same key + different body is a server 409 surfaced as a closed HTTP failure).
         */
        JSONObject prepare(JSONObject body, String key) throws NativeFailure {
            assertPrepareBody(body);
            String idempotencyKey = canonicalUuid(key);
            JSONObject wire = copyOf(body);
            put(wire, "host_receipt_id", canonicalUuid(body.optString("host_receipt_id")));
            put(wire, "intent_id", canonicalUuid(body.optString("intent_id")));
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put("content-type", "application/json");
            headers.put("idempotency-key", idempotencyKey);
            return checkedPrepareView(dispatch("POST", "/v1/ai/device-evidence-packs", headers,
                objectWire(PREPARE_REQUEST_FIELDS, wire, new LinkedHashMap<>()).getBytes(StandardCharsets.UTF_8)));
        }

        /** GET /v1/ai/device-evidence-packs/lookup - read-only recovery by key. */
        JSONObject lookupPrepare(String key) throws NativeFailure {
            String idempotencyKey = canonicalUuid(key);
            return checkedPrepareView(dispatch("GET",
                "/v1/ai/device-evidence-packs/lookup?mode=history&idempotency_key=" + idempotencyKey,
                new LinkedHashMap<>(), null));
        }

        /** GET /v1/ai/device-evidence-packs/{prepare_id} - owned immutable read. */
        JSONObject readPrepare(String prepareId) throws NativeFailure {
            if (!isPlainString(prepareId, 64)) throw fail("device_ai_host_invalid_argument");
            return checkedPrepareView(dispatch("GET",
                "/v1/ai/device-evidence-packs/" + prepareId + "?mode=history", new LinkedHashMap<>(), null));
        }

        /**
         * POST /v1/ai/analysis-streams with the closed device branch: the existing
         * AnalysisRequest plus device_submission. The question is normalized
         * (trim-once, codepoint-counted) exactly once here so the server's triple
         * binding digest(trim_once(question)) == preparation.question_sha256 ==
         * consent.question_sha256 can hold. allow_external_processing is the
         * literal true of the closed device branch.
         */
        JSONObject submitStream(JSONObject submission, String key) throws NativeFailure {
            if (submission == null || !isPlainString(submission.opt("pack_id"), 64)
                || !isPlainString(submission.opt("prepare_id"), 64)) throw fail("device_ai_host_invalid_argument");
            String question = normalizeQuestion(submission.optString("question"));
            JSONObject consent = submission.optJSONObject("provider_consent");
            if (consent == null) throw fail("device_ai_host_invalid_argument");
            assertClosedFields(consent, PROVIDER_CONSENT_FIELDS, "ProviderConsent");
            requireHash64(consent.opt("expected_pack_fingerprint"));
            requireHash64(consent.opt("expected_device_context_fingerprint"));
            requireHash64(consent.opt("question_sha256"));
            requireHash64(consent.opt("expected_provider_policy_fingerprint"));
            if (!isPlainString(consent.opt("provider"), 32) || !isPlainString(consent.opt("model"), 120))
                throw fail("device_ai_host_invalid_argument");
            if (!isHash64(submission.opt("device_context_fingerprint"))) throw fail("device_ai_host_invalid_argument");
            JSONObject deviceSubmission = new JSONObject();
            put(deviceSubmission, "prepare_id", submission.opt("prepare_id"));
            put(deviceSubmission, "host_receipt_id", canonicalUuid(submission.optString("host_receipt_id")));
            put(deviceSubmission, "device_context_fingerprint", submission.opt("device_context_fingerprint"));
            put(deviceSubmission, "provider_consent", orderedCopy(consent, PROVIDER_CONSENT_FIELDS));
            assertClosedFields(deviceSubmission, SUBMISSION_FIELDS, "DeviceSubmission");
            JSONObject body = new JSONObject();
            put(body, "pack_id", submission.opt("pack_id"));
            put(body, "question", question);
            put(body, "allow_external_processing", true);
            put(body, "device_submission", deviceSubmission);
            assertClosedFields(body, ANALYSIS_REQUEST_FIELDS, "AnalysisRequest");
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put("content-type", "application/json");
            headers.put("idempotency-key", canonicalUuid(key));
            String consentWire = objectWire(PROVIDER_CONSENT_FIELDS, consent, new LinkedHashMap<>());
            Map<String, String> submissionOverrides = new LinkedHashMap<>();
            submissionOverrides.put("provider_consent", consentWire);
            String submissionWire = objectWire(SUBMISSION_FIELDS, deviceSubmission, submissionOverrides);
            Map<String, String> bodyOverrides = new LinkedHashMap<>();
            bodyOverrides.put("device_submission", submissionWire);
            JSONObject result = dispatch("POST", "/v1/ai/analysis-streams", headers,
                objectWire(ANALYSIS_REQUEST_FIELDS, body, bodyOverrides).getBytes(StandardCharsets.UTF_8));
            JSONObject detail = checkedStreamDetail(result);
            if (!(detail.opt("replayed") instanceof Boolean))
                throw new IllegalStateException("AI 受理结果缺少同请求核对信息。");
            return detail;
        }

        /** GET /v1/ai/analysis-streams/lookup - read-only attempt recovery by the frozen analysis key. */
        JSONObject lookupAttempt(String key) throws NativeFailure {
            String idempotencyKey = canonicalUuid(key);
            return checkedStreamDetail(dispatch("GET",
                "/v1/ai/analysis-streams/lookup?mode=history&idempotency_key=" + idempotencyKey,
                new LinkedHashMap<>(), null));
        }
    }

    // ---------------------------------------------------------------------
    // N18: unknown-outcome resolution. Lookup first, never resubmit on its own.
    // ---------------------------------------------------------------------

    /**
     * After a disconnect or crash: read-only lookup with the SAME idempotency key
     * first. A hit returns the existing attempt reference and NOTHING is ever
     * resubmitted automatically. On a miss, only the absence of a local
     * claim_submitted entry makes a fresh user decision legitimate; a recorded
     * claim allows exactly one recovery path - same key, same body, explicit
     * user decision - and a cross-session claim is never replayed (fence 5).
     * Transport failures propagate untouched: the caller retries later and the
     * state stays genuinely unknown.
     */
    static JSONObject resolveUnknownOutcome(DeviceAiHostClient client, String analysisKey,
        DeviceAiJournal journal, String intentId) throws NativeFailure {
        String key = canonicalUuid(analysisKey);
        JSONObject detail = null;
        try {
            detail = client.lookupAttempt(key);
        } catch (DeviceAiHostException failure) {
            if (failure.httpStatus == null || failure.httpStatus != 404) throw failure;
        }
        if (detail != null) {
            JSONObject out = new JSONObject();
            put(out, "kind", "resolved");
            put(out, "detail", detail);
            return out;
        }
        if (journal == null) return kindOnly("not_submitted");
        JournalVerification verification = journal.verifyIntegrity();
        if (!verification.ok) return kindWithViolations("journal_integrity_failed", verification.toJson().optJSONArray("violations"));
        List<JSONObject> entries;
        try {
            entries = journal.readAll();
        } catch (DeviceAiHostException integrity) {
            JSONObject violation = new JSONObject();
            put(violation, "code", integrity.code);
            put(violation, "sequence", JSONObject.NULL);
            return kindWithViolations("journal_integrity_failed", new JSONArray().put(violation));
        } catch (Exception store) {
            throw new IllegalStateException("journal store unreadable", store);
        }
        List<JSONObject> claims = new ArrayList<>();
        for (JSONObject entry : entries) {
            JSONObject event = entry.optJSONObject("event");
            if (event == null || !"claim_submitted".equals(event.optString("type"))) continue;
            if (!key.equals(event.optString("analysis_key"))) continue;
            if (intentId != null && !intentId.equals(event.optString("intent_id"))) continue;
            claims.add(entry);
        }
        if (claims.isEmpty()) return kindOnly("not_submitted");
        // Fence 5: a claim recorded under a different session never replays here.
        for (JSONObject claim : claims)
            if (!journal.sessionId().equals(claim.optString("session_id")))
                return kindOnly("cross_session_replay_blocked");
        JSONObject out = new JSONObject();
        put(out, "kind", "unknown_local_claim");
        put(out, "analysis_key", key);
        put(out, "resubmission", "same_key_same_body_user_decision_only");
        return out;
    }

    private static JSONObject kindOnly(String kind) {
        JSONObject out = new JSONObject();
        put(out, "kind", kind);
        return out;
    }

    private static JSONObject kindWithViolations(String kind, JSONArray violations) {
        JSONObject out = new JSONObject();
        put(out, "kind", kind);
        put(out, "violations", violations);
        return out;
    }

    // ---------------------------------------------------------------------
    // Command-shaped thin wrappers for the TireNativePlugin entries (dormant
    // until the JS host flow imports the TS SDK module by path; D15).
    // ---------------------------------------------------------------------

    static JSONObject prepareCommand(DeviceAiHostClient client, JSONObject request) throws NativeFailure {
        if (!isPlainString(request.opt("idempotency_key"), 68)) throw fail("device_ai_host_invalid_argument");
        return client.prepare(orderedCopy(request, PREPARE_REQUEST_FIELDS), request.optString("idempotency_key"));
    }

    static JSONObject submitCommand(DeviceAiHostClient client, JSONObject request) throws NativeFailure {
        if (!isPlainString(request.opt("idempotency_key"), 68)) throw fail("device_ai_host_invalid_argument");
        List<String> fields = new ArrayList<>(List.of("pack_id", "question", "prepare_id", "host_receipt_id",
            "device_context_fingerprint", "provider_consent"));
        JSONObject submission = orderedCopy(request, fields);
        return client.submitStream(submission, request.optString("idempotency_key"));
    }

    static JSONObject lookupCommand(DeviceAiHostClient client, JSONObject request) throws NativeFailure {
        // Closed discriminator: extra keys rejected, the one key the chosen kind
        // consumes must be a bounded plain string, the alternates stay unused.
        Set<String> allowed = Set.of("kind", "idempotency_key", "prepare_id");
        for (String key : keyNames(request))
            if (!allowed.contains(key)) throw fail("device_ai_host_invalid_argument");
        String kind = request.optString("kind");
        if (kind.equals("prepare")) return client.lookupPrepare(requiredPlain(request, "idempotency_key"));
        if (kind.equals("attempt")) return client.lookupAttempt(requiredPlain(request, "idempotency_key"));
        if (kind.equals("prepare_read")) return client.readPrepare(requiredPlain(request, "prepare_id"));
        throw fail("device_ai_host_invalid_argument");
    }

    private static String requiredPlain(JSONObject request, String key) {
        if (!isPlainString(request.opt(key), 68)) throw fail("device_ai_host_invalid_argument");
        return request.optString(key);
    }

    /** Journal read command: keystore-sealed ledger verification + recovery read (never writes). */
    static JSONObject journalReadCommand(android.content.Context context, JSONObject request) throws Exception {
        assertClosedFields(request, List.of("owner", "generation", "session_id"), "DeviceAiJournalReadRequest");
        if (!isPlainString(request.opt("owner"), 128) || !isPlainString(request.opt("session_id"), 128))
            throw fail("device_ai_host_invalid_argument");
        String owner = request.optString("owner");
        return journalRead(owner, positiveMetaLong(request, "generation"), request.optString("session_id"),
            androidJournalSealer(context), fileStore(journalFile(context, owner)),
            android.os.SystemClock::elapsedRealtime);
    }

    /** Core verification + recovery read over an injected sealer/store (JVM tests use the software-key fake). */
    static JSONObject journalRead(String owner, long generation, String sessionId, Sealer sealer, Store store,
        LongSupplier monotonicNow) throws Exception {
        DeviceAiJournal journal = new DeviceAiJournal(owner, generation, sessionId, sealer, store, monotonicNow, null);
        JournalVerification verification = journal.verifyIntegrity();
        if (!verification.ok) return verification.toJson();
        JSONObject out = verification.toJson();
        JSONArray entries = new JSONArray();
        for (JSONObject entry : journal.readAll()) put(entries, entry);
        put(out, "entries", entries);
        return out;
    }

    /** Journal append command: the ONLY write path into the keystore-sealed ledger. */
    static JSONObject journalAppendCommand(android.content.Context context, JSONObject request) throws Exception {
        assertClosedFields(request, List.of("owner", "generation", "session_id", "event"), "DeviceAiJournalAppendRequest");
        if (!isPlainString(request.opt("owner"), 128) || !isPlainString(request.opt("session_id"), 128))
            throw fail("device_ai_host_invalid_argument");
        JSONObject event = request.optJSONObject("event");
        if (event == null) throw fail("device_ai_host_invalid_argument");
        String owner = request.optString("owner");
        return journalAppend(owner, positiveMetaLong(request, "generation"), request.optString("session_id"), event,
            androidJournalSealer(context), fileStore(journalFile(context, owner)),
            android.os.SystemClock::elapsedRealtime, null);
    }

    /** Core five-fence append over an injected sealer/store. */
    static JSONObject journalAppend(String owner, long generation, String sessionId, JSONObject event,
        Sealer sealer, Store store, LongSupplier monotonicNow, Supplier<String> wallNow) throws Exception {
        assertJournalEventPayload(event);
        return new DeviceAiJournal(owner, generation, sessionId, sealer, store, monotonicNow, wallNow).append(event);
    }

    /**
     * Command-layer closed event payload check (the wire is not frozen, D15, but
     * the ledger itself stays closed): per-type value shapes on top of the
     * journal's own key-set closure - fingerprints 64-hex, bounded plain-string
     * ids, idempotency/analysis keys canonical UUIDs, decision exactly
     * allow/deny, failure_observed intent nullable and outcome_observed intent
     * possibly empty (web sibling recordTerminal passes intentId ?? "").
     */
    static void assertJournalEventPayload(JSONObject event) {
        if (event == null) throw fail("device_ai_host_invalid_argument");
        String type = event.optString("type");
        if (!JOURNAL_EVENT_FIELDS.containsKey(type)) throw fail("device_ai_host_invalid_argument");
        switch (type) {
            case "preview_shown":
                eventString(event, "intent_id", 128);
                requireHash64(event.opt("local_preview_fingerprint"));
                requireHash64(event.opt("question_sha256"));
                requireHash64(event.opt("package_sha256"));
                break;
            case "decision_made":
                eventString(event, "intent_id", 128);
                if (!"allow".equals(event.opt("decision")) && !"deny".equals(event.opt("decision")))
                    throw fail("device_ai_host_invalid_argument");
                requireHash64(event.opt("local_preview_fingerprint"));
                break;
            case "prepare_created":
                eventString(event, "intent_id", 128);
                eventString(event, "prepare_id", 64);
                canonicalUuid(event.optString("idempotency_key"));
                requireHash64(event.opt("projection_sha256"));
                requireHash64(event.opt("device_context_fingerprint"));
                break;
            case "claim_submitted":
                eventString(event, "intent_id", 128);
                eventString(event, "prepare_id", 64);
                canonicalUuid(event.optString("analysis_key"));
                requireHash64(event.opt("question_sha256"));
                break;
            case "outcome_observed":
                Object outcomeIntent = event.opt("intent_id");
                if (!(outcomeIntent instanceof String)
                    || (!outcomeIntent.equals("") && !isPlainString(outcomeIntent, 128)))
                    throw fail("device_ai_host_invalid_argument");
                canonicalUuid(event.optString("analysis_key"));
                eventString(event, "request_id", 128);
                eventString(event, "state", 64);
                break;
            default: // failure_observed
                Object intent = event.opt("intent_id");
                if (!(intent == null || intent == JSONObject.NULL) && !isPlainString(intent, 128))
                    throw fail("device_ai_host_invalid_argument");
                eventString(event, "stage", 64);
                eventString(event, "code", 128);
                break;
        }
    }

    private static void eventString(JSONObject event, String key, int max) {
        if (!isPlainString(event.opt(key), max)) throw fail("device_ai_host_invalid_argument");
    }

    /**
     * N18 recovery command: read-only lookup FIRST (never a resubmit), then the
     * journal claim branches. The journal binding travels with the request
     * because the Android ledger is Host-owned (keystore key + no-backup file).
     */
    static JSONObject resolveUnknownCommand(android.content.Context context, NativeHttpBridge bridge,
        JSONObject request) throws NativeFailure {
        Set<String> allowed = Set.of("analysis_key", "intent_id", "owner", "generation", "session_id");
        for (String key : keyNames(request))
            if (!allowed.contains(key)) throw fail("device_ai_host_invalid_argument");
        Object rawIntent = request.opt("intent_id");
        String intentId;
        if (rawIntent == null || rawIntent == JSONObject.NULL) intentId = null;
        else if (isPlainString(rawIntent, 128)) intentId = (String) rawIntent;
        else throw fail("device_ai_host_invalid_argument");
        String owner = request.optString("owner");
        if (!isPlainString(owner, 128) || !isPlainString(request.opt("session_id"), 128))
            throw fail("device_ai_host_invalid_argument");
        return resolveUnknown(request.optString("analysis_key"), intentId, owner,
            positiveMetaLong(request, "generation"), request.optString("session_id"), clientOver(bridge),
            androidJournalSealer(context), fileStore(journalFile(context, owner)),
            android.os.SystemClock::elapsedRealtime, null);
    }

    /** Core resolve over an injected transport/sealer/store (four-branch N18 semantics). */
    static JSONObject resolveUnknown(String analysisKey, String intentId, String owner, long generation,
        String sessionId, DeviceAiHostClient client, Sealer sealer, Store store, LongSupplier monotonicNow,
        Supplier<String> wallNow) throws NativeFailure {
        DeviceAiJournal journal = new DeviceAiJournal(owner, generation, sessionId, sealer, store, monotonicNow, wallNow);
        return resolveUnknownOutcome(client, analysisKey, journal, intentId);
    }

    static File journalFile(android.content.Context context, String owner) {
        return new File(context.getNoBackupFilesDir(),
            "device-ai-journal-" + sha256Hex(owner.getBytes(StandardCharsets.UTF_8)) + ".bin");
    }

    /**
     * AndroidKeyStore AES-256-GCM sealer (OfflineCipher/EncryptedSessionStore precedent:
     * per-app alias, randomized encryption required, GCM/no-padding). The owner pin
     * lives in the AAD, so one app-owned key serves every journal owner.
     */
    static Sealer androidJournalSealer(android.content.Context context) {
        return new AndroidKeystoreSealer(context);
    }

    /** Host-owned whole-blob store: app-private no-backup directory, AtomicFile persistence. */
    static Store fileStore(File file) {
        return new Store() {
            @Override public byte[] load() throws Exception {
                if (!file.exists()) return null;
                if (file.length() > JOURNAL_MAX_BYTES) throw fail("device_ai_host_journal_corrupt");
                return Files.readAllBytes(file.toPath());
            }
            @Override public void save(byte[] blob) throws Exception {
                android.util.AtomicFile atomic = new android.util.AtomicFile(file);
                FileOutputStream stream = atomic.startWrite();
                boolean done = false;
                try {
                    stream.write(blob);
                    stream.getFD().sync();
                    atomic.finishWrite(stream);
                    done = true;
                } finally {
                    if (!done) atomic.failWrite(stream);
                }
            }
        };
    }

    static final class AndroidKeystoreSealer implements Sealer {
        private final String alias;
        AndroidKeystoreSealer(android.content.Context context) {
            String profile = context.getPackageName() + ":device-ai-journal-v1";
            alias = "tire.deviceai.v1." + sha256Hex(profile.getBytes(StandardCharsets.UTF_8));
        }
        private javax.crypto.SecretKey key() throws Exception {
            java.security.KeyStore store = java.security.KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            if (!store.containsAlias(alias)) {
                javax.crypto.KeyGenerator generator = javax.crypto.KeyGenerator.getInstance(
                    android.security.keystore.KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
                generator.init(new android.security.keystore.KeyGenParameterSpec.Builder(alias,
                    android.security.keystore.KeyProperties.PURPOSE_ENCRYPT | android.security.keystore.KeyProperties.PURPOSE_DECRYPT)
                    .setKeySize(256).setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true).build());
                generator.generateKey();
            }
            Object loaded = store.getKey(alias, null);
            if (!(loaded instanceof javax.crypto.SecretKey)) throw fail("device_ai_host_journal_corrupt");
            return (javax.crypto.SecretKey) loaded;
        }
        @Override public byte[] seal(byte[] clear, byte[] aad) throws Exception {
            javax.crypto.Cipher cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(javax.crypto.Cipher.ENCRYPT_MODE, key());
            cipher.updateAAD(aad);
            byte[] iv = cipher.getIV();
            if (iv.length != 12) throw fail("device_ai_host_journal_corrupt");
            byte[] ciphertext = cipher.doFinal(clear);
            byte[] out = new byte[12 + ciphertext.length];
            System.arraycopy(iv, 0, out, 0, 12);
            System.arraycopy(ciphertext, 0, out, 12, ciphertext.length);
            return out;
        }
        @Override public byte[] open(byte[] sealed, byte[] aad) throws Exception {
            if (sealed == null || sealed.length < 12 + 16) throw fail("device_ai_host_journal_corrupt");
            javax.crypto.Cipher cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(javax.crypto.Cipher.DECRYPT_MODE, key(), new javax.crypto.spec.GCMParameterSpec(128,
                java.util.Arrays.copyOfRange(sealed, 0, 12)));
            cipher.updateAAD(aad);
            return cipher.doFinal(sealed, 12, sealed.length - 12);
        }
    }
}
