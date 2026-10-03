package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;

/**
 * Replays the authoritative cross-host vectors in
 * .artifacts/device-ai50/specs/e1-canonical-vectors-a.json (68 entries, Python
 * reference generated_and_self_checked) against the Java device-ai strict parser
 * DeviceAiJsonParser: accepted vectors must reproduce canonical bytes/text,
 * sha256, sha256_namespaced and encoded_canonical_text byte for byte (the
 * 250000-node vector binds via digests only, output_binding=sha256_only_size);
 * rejected vectors must fail closed with the exact listed error code. The
 * cross_vector_invariants and counts sections bind as well.
 *
 * Fixture location: system property tire.test.e1vectors (absolute path), else an
 * upward search from the test working directory (Gradle's ordinary Test working
 * directory is the app project, like OfflineRulesReferenceTest's relative asset
 * binding). The file bytes are pinned by SHA-256, so the run reads the
 * authoritative artifact itself and no copy is embedded.
 */
@RunWith(Parameterized.class)
public final class DeviceAiJsonParserParityTest {
    private static final String VECTORS_REPOSITORY_PATH = ".artifacts/device-ai50/specs/e1-canonical-vectors-a.json";
    private static final String VECTORS_SHA256 = "9e5efce6c9d9a2faa016da8b2ed851d13a0620194d97d96dccd09e851272fe3b";

    private static JSONObject document;
    private static Map<String, JSONObject> vectors;
    private static Map<String, List<List<String>>> invariants;

    private final String id;

    public DeviceAiJsonParserParityTest(String id) { this.id = id; }

    @Parameterized.Parameters(name = "{0}")
    public static List<String> vectorIds() {
        loadVectors();
        return new ArrayList<>(vectors.keySet());
    }

    private static synchronized void loadVectors() {
        if (vectors != null) return;
        try { loadVectorsChecked(); }
        catch (Exception failure) { throw new IllegalStateException("E1 vector binding failed", failure); }
    }

    private static void loadVectorsChecked() throws Exception {
        if (vectors != null) return;
        Path path = locate();
        byte[] raw;
        try { raw = Files.readAllBytes(path); }
        catch (Exception unreadable) { throw new IllegalStateException("E1 vectors unreadable: " + path, unreadable); }
        assertEquals("E1 vectors sha256 drift: " + path, VECTORS_SHA256, sha256Hex(raw));
        document = new JSONObject(new String(raw, StandardCharsets.UTF_8));
        JSONArray list = document.getJSONArray("vectors");
        vectors = new LinkedHashMap<>();
        int accepted = 0, rejected = 0;
        for (int at = 0; at < list.length(); at++) {
            JSONObject vector = list.getJSONObject(at);
            assertNull("duplicate vector id " + vector.getString("id"), vectors.put(vector.getString("id"), vector));
            if ("accepted".equals(vector.getString("state"))) accepted++;
            else rejected++;
        }
        JSONObject counts = document.getJSONObject("counts");
        assertEquals("total vectors", counts.getInt("total"), list.length());
        assertEquals("accepted vectors", counts.getInt("accepted"), accepted);
        assertEquals("rejected vectors", counts.getInt("rejected"), rejected);
        invariants = new LinkedHashMap<>();
        JSONObject cross = document.getJSONObject("cross_vector_invariants");
        bindInvariant(cross, "canonical_must_match");
        bindInvariant(cross, "encoded_must_differ");
        bindInvariant(cross, "sha256_must_differ");
        System.out.println("E1 vectors bound: " + path + " (sha256 " + VECTORS_SHA256 + ", " + list.length() + " vectors)");
    }

    private static void bindInvariant(JSONObject cross, String name) throws Exception {
        List<List<String>> pairs = new ArrayList<>();
        JSONArray raw = cross.getJSONArray(name);
        for (int at = 0; at < raw.length(); at++) {
            JSONArray pair = raw.getJSONArray(at);
            assertEquals(name + " arity", 2, pair.length());
            pairs.add(List.of(pair.getString(0), pair.getString(1)));
        }
        invariants.put(name, pairs);
    }

    private static Path locate() {
        List<Path> candidates = new ArrayList<>();
        String configured = System.getProperty("tire.test.e1vectors");
        if (configured != null) candidates.add(Path.of(configured));
        Path directory = Path.of("").toAbsolutePath();
        for (int up = 0; up <= 8 && directory != null; up++) {
            candidates.add(directory.resolve(VECTORS_REPOSITORY_PATH).normalize());
            directory = directory.getParent();
        }
        for (Path candidate : candidates) if (Files.isRegularFile(candidate)) return candidate;
        throw new IllegalStateException("E1 vector file not found above the working directory; pass -Dtire.test.e1vectors=<path>");
    }

    private static byte[] sha256(byte[] data) throws Exception {
        return MessageDigest.getInstance("SHA-256").digest(data);
    }

    private static String sha256Hex(byte[] data) throws Exception {
        StringBuilder out = new StringBuilder(64);
        for (byte value : sha256(data))
            out.append("0123456789abcdef".charAt((value >> 4) & 0xF)).append("0123456789abcdef".charAt(value & 0xF));
        return out.toString();
    }

    /** replay_instructions: literal text/hex or (prefix + repeat*count + suffix) template. */
    private static byte[] expand(JSONObject input) throws Exception {
        String form = input.getString("form");
        byte[] fromHex = null;
        if (input.has("utf8_hex") && !input.isNull("utf8_hex") && input.getString("utf8_hex").length() > 0)
            fromHex = HexFormat.of().parseHex(input.getString("utf8_hex"));
        if (form.equals("bytes")) {
            assertNotNull("bytes form requires utf8_hex", fromHex);
            return fromHex;
        }
        byte[] fromText;
        if (form.equals("literal")) {
            fromText = input.getString("text").getBytes(StandardCharsets.UTF_8);
        } else if (form.equals("template")) {
            StringBuilder text = new StringBuilder(input.getString("prefix"));
            for (int at = 0; at < input.getInt("count"); at++) text.append(input.getString("repeat"));
            text.append(input.getString("suffix"));
            fromText = text.toString().getBytes(StandardCharsets.UTF_8);
        } else throw new IllegalStateException("unknown input form " + form);
        if (fromHex != null) assertArrayEquals("literal text/hex expansion disagree", fromHex, fromText);
        return fromText;
    }

    @Test public void replayVector() throws Exception {
        JSONObject vector = vectors.get(id);
        byte[] input = expand(vector.getJSONObject("input"));
        if (vector.has("input_byte_count")) assertEquals(id + " input_byte_count", vector.getInt("input_byte_count"), input.length);
        if ("accepted".equals(vector.getString("state"))) replayAccepted(vector, input);
        else replayRejected(vector, input);
        checkInvariantsFor(id);
    }

    private static void replayAccepted(JSONObject vector, byte[] input) throws Exception {
        String vectorId = vector.getString("id");
        Object ast = DeviceAiJsonParser.parse(input);
        assertEquals(vectorId + " sha256", vector.getString("sha256"), DeviceAiJsonParser.digest(ast));
        String namespace = document.getJSONObject("constants").getString("namespaced_sha256_namespace");
        assertEquals(vectorId + " sha256_namespaced", vector.getString("sha256_namespaced"), DeviceAiJsonParser.digest(ast, namespace));
        if ("sha256_only_size".equals(vector.optString("output_binding", ""))) {
            assertFalse(vectorId + " canonical must be omitted for sha256_only_size", vector.has("canonical"));
            return;
        }
        byte[] canonical = DeviceAiJsonParser.canonicalBytes(ast);
        assertArrayEquals(vectorId + " canonical utf8_hex",
            HexFormat.of().parseHex(vector.getJSONObject("canonical").getString("utf8_hex")), canonical);
        assertEquals(vectorId + " canonical text", vector.getJSONObject("canonical").getString("text"),
            new String(canonical, StandardCharsets.UTF_8));
        // The authoritative generator serializes the encoded DeviceAIValue tree with
        // json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False) and NO depth
        // bound: the depth_32 vector's encoded tree is ~65 levels deep, which the bounded
        // canonicalExactJson guard would reject (same note as the TS strict runner). So
        // encoded_canonical_text is compared through dumpSortedKeys plus a structural
        // tree comparison against vec.encoded; canonical(ast) itself keeps the bounded form.
        Object encoded = DeviceAiJsonParser.encodeValue(ast);
        assertTrue(vectorId + " encoded tree shape", deepEqual(encoded, vector.get("encoded")));
        assertEquals(vectorId + " encoded_canonical_text", vector.getString("encoded_canonical_text"), dumpSortedKeys(encoded));
    }

    private static void replayRejected(JSONObject vector, byte[] input) throws Exception {
        JSONArray errors = vector.getJSONArray("errors");
        assertEquals(vector.getString("id") + " single error code", 1, errors.length());
        try {
            DeviceAiJsonParser.parse(input);
            fail(vector.getString("id") + " unexpectedly accepted");
        } catch (DeviceAiJsonParser.ProjectionException expected) {
            assertEquals(vector.getString("id"), errors.getString(0), expected.code);
        }
    }

    /** Cross-vector invariants are evaluated once, when the second member of each pair replays. */
    private void checkInvariantsFor(String vectorId) throws Exception {
        for (Map.Entry<String, List<List<String>>> group : invariants.entrySet())
            for (List<String> pair : group.getValue())
                if (vectorId.equals(pair.get(1))) checkInvariant(group.getKey(), pair.get(0), pair.get(1));
    }

    private static void checkInvariant(String name, String firstId, String secondId) throws Exception {
        JSONObject first = vectors.get(firstId), second = vectors.get(secondId);
        assertNotNull(firstId + " missing", first);
        assertNotNull(secondId + " missing", second);
        byte[] firstInput = expand(first.getJSONObject("input")), secondInput = expand(second.getJSONObject("input"));
        Object firstAst = DeviceAiJsonParser.parse(firstInput), secondAst = DeviceAiJsonParser.parse(secondInput);
        switch (name) {
            case "canonical_must_match":
                assertArrayEquals(name + " " + firstId + "/" + secondId,
                    DeviceAiJsonParser.canonicalBytes(firstAst), DeviceAiJsonParser.canonicalBytes(secondAst));
                break;
            case "encoded_must_differ":
                assertFalse(name + " " + firstId + "/" + secondId,
                    dumpSortedKeys(DeviceAiJsonParser.encodeValue(firstAst))
                        .equals(dumpSortedKeys(DeviceAiJsonParser.encodeValue(secondAst))));
                break;
            case "sha256_must_differ":
                assertFalse(name + " " + firstId + "/" + secondId,
                    DeviceAiJsonParser.digest(firstAst).equals(DeviceAiJsonParser.digest(secondAst)));
                break;
            default: throw new IllegalStateException("unknown invariant " + name);
        }
    }

    /** Mirror of the generator's json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False) over the encoded tree (unbounded depth). */
    private static String dumpSortedKeys(Object node) {
        if (node == null) return "null";
        if (node instanceof Boolean) return ((Boolean) node) ? "true" : "false";
        if (node instanceof String) return dumpString((String) node);
        if (node instanceof List) {
            StringBuilder out = new StringBuilder("[");
            boolean head = true;
            for (Object child : (List<?>) node) {
                if (!head) out.append(',');
                head = false;
                out.append(dumpSortedKeys(child));
            }
            return out.append(']').toString();
        }
        if (node instanceof Map) {
            List<String> keys = new ArrayList<>(((Map<?, ?>) node).size());
            for (Object key : ((Map<?, ?>) node).keySet()) keys.add((String) key);
            keys.sort(DeviceAiJsonParser::compareCodepoints);
            StringBuilder out = new StringBuilder("{");
            boolean head = true;
            for (String key : keys) {
                if (!head) out.append(',');
                head = false;
                out.append(dumpString(key)).append(':').append(dumpSortedKeys(((Map<?, ?>) node).get(key)));
            }
            return out.append('}').toString();
        }
        throw new IllegalStateException("unexpected encoded node " + node.getClass());
    }

    /** JSON.stringify escaping == json.dumps(ensure_ascii=False): quote, backslash, five control shortcuts, other <0x20 as lowercase u00XX. */
    private static String dumpString(String value) {
        StringBuilder out = new StringBuilder(value.length() + 2).append('"');
        for (int at = 0; at < value.length(); at++) {
            char character = value.charAt(at);
            switch (character) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\b': out.append("\\b"); break;
                case '\f': out.append("\\f"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (character < 0x20) out.append("\\u00")
                        .append("0123456789abcdef".charAt((character >>> 4) & 0xF))
                        .append("0123456789abcdef".charAt(character & 0xF));
                    else out.append(character);
            }
        }
        return out.append('"').toString();
    }

    /** Structural comparison of the encoded tree against the org.json-parsed expected value. */
    private static boolean deepEqual(Object actual, Object expected) throws Exception {
        if (actual == null || expected == null || expected == JSONObject.NULL) return actual == null && (expected == null || expected == JSONObject.NULL);
        if (actual instanceof Boolean || actual instanceof String)
            return actual.equals(expected) && (actual.getClass().isInstance(expected) || expected instanceof Boolean || expected instanceof String);
        if (actual instanceof List) {
            if (!(expected instanceof JSONArray)) return false;
            JSONArray array = (JSONArray) expected;
            List<?> list = (List<?>) actual;
            if (list.size() != array.length()) return false;
            for (int at = 0; at < list.size(); at++) if (!deepEqual(list.get(at), array.get(at))) return false;
            return true;
        }
        if (actual instanceof Map) {
            if (!(expected instanceof JSONObject)) return false;
            JSONObject object = (JSONObject) expected;
            Map<?, ?> map = (Map<?, ?>) actual;
            if (map.size() != object.length()) return false;
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!object.has((String) entry.getKey())) return false;
                if (!deepEqual(entry.getValue(), object.get((String) entry.getKey()))) return false;
            }
            return true;
        }
        return false;
    }
}
