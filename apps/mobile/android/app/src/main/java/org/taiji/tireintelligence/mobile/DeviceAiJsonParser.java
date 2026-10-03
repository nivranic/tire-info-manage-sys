package org.taiji.tireintelligence.mobile;

import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * device-ai internal, wire not frozen (draft-b DeviceAIValue strategy: internal module first).
 *
 * Strict exact-JSON pipeline closing the architecture gap named by
 * .artifacts/device-ai50/architecture-approved-b.json clarification B06 ("current
 * Android criteria parser is not a float-lexeme preserving implementation"):
 * OfflineTireCriteria's JsonReader number path collapses every non-integer token
 * to a double (OfflineTireCriteria.java parse() NUMBER case, Double.valueOf(token))
 * and its number() normalizes integral floats through binary64
 * (BigDecimal(floating).toBigIntegerExact()), so the archived spelling is destroyed
 * before any projection digest could be computed. This module instead keeps every
 * number as its original lexeme string and mirrors, byte for byte, the sealed Python
 * reference apps/api/tire_api/device_ai_projection.py (parse_exact_json /
 * canonical_exact_json / exact_digest) and device_ai_value_encoder.py (encode_value):
 *
 *  - capacity (0 or > 8 MiB) -> BOM -> strict UTF-8 -> text depth pre-scan
 *    (MAX_DEPTH + 1 = 33 simultaneously open brackets) -> syntax / duplicate key
 *    (judged after unescaping, at object close) / NaN-Infinity constants / number
 *    grammar + binary64 finiteness (1e-5000 keeps its token, 1e309 rejects) ->
 *    tree walk (AST depth <= 32 with root = 0, node budget <= 250_000 counting
 *    every node but not object key names, lone-surrogate strings reject);
 *  - canonical object keys sort by codepoint (== UTF-8 byte order). Java
 *    String.compareTo is UTF-16 code-unit order and orders supplementary
 *    characters (U+10000+) BEFORE U+E000..U+FFFF - wrong for this contract, so a
 *    hand-written codepoint comparator is mandatory (encoder-spec.md section 8);
 *  - canonical string escaping matches json.dumps(ensure_ascii=False): \" \\ and
 *    the backspace/formfeed/newline/return/tab shortcuts, other control chars
 *    below 0x20 as lowercase u00XX escapes, everything else (/, 0x7F, U+2028/U+2029,
 *    non-BMP) raw UTF-8;
 *  - sha256 is computed with java.security.MessageDigest over the canonical bytes
 *    of the ORIGINAL AST, never over the encoded DeviceAIValue; the namespaced
 *    form is sha256(namespace_utf8 + 0x00 + canonical);
 *  - encodeValue() decides ONLY on the AST node type, so a source 5 and a source
 *    {"schema":"device-number-token@1","token":"5"} encode differently (number vs
 *    structured); lexemes are never rewritten (1.2300 stays 1.2300, -0 stays -0).
 *
 * Locked by the authoritative vectors in
 * .artifacts/device-ai50/specs/e1-canonical-vectors-a.json (68/68 parity, replayed
 * by DeviceAiJsonParserParityTest). Declared deviation outside vector coverage:
 * canonical/encodeValue reject bare Java numeric nodes (Long/Integer/Double...)
 * with device_ai_number_or_type_unsupported, mirroring the fail-closed TypeScript
 * sibling packages/api-client/src/device-ai-exact.ts (the Python metadata channel
 * that accepts bounded bare ints has no Java counterpart here).
 *
 * Pure java.* only - no android.util.JsonReader - so plain JVM unit tests can
 * execute it against the "not mocked" android.jar stub. The legacy
 * OfflineTireCriteria is deliberately NOT refactored: its double semantics serve
 * the existing offline filter matching, and lexeme retention adds no measurement
 * precision (B02/B03). Both modules coexist (same strategy as the TS side, where
 * exact-json.ts stays the permissive channel).
 */
final class DeviceAiJsonParser {
    static final int MAX_DEPTH = 32;
    static final int MAX_NODES = 250_000;
    static final int MAX_PACKAGE_BYTES = 8 * 1024 * 1024;
    static final String NUMBER_TOKEN_SCHEMA = "device-number-token@1";

    /** Closed failure; the message carries only the code, never source content. */
    static final class ProjectionException extends RuntimeException {
        final String code;
        ProjectionException(String code) { super(code); this.code = code; }
    }

    private static ProjectionException fail(String code) { return new ProjectionException(code); }

    /**
     * Exact-AST number node: the original lexeme only. No added numeric meaning;
     * float tokens (containing . e E) must merely stay finite under binary64.
     */
    static final class NumberLexeme {
        final String token;
        final boolean isFloat;
        NumberLexeme(String token) {
            if (token == null || !numberGrammar(token)) throw fail("device_ai_number_invalid");
            this.token = token;
            this.isFloat = token.indexOf('.') >= 0 || token.indexOf('e') >= 0 || token.indexOf('E') >= 0;
            if (this.isFloat && !finiteBinary64(token)) throw fail("device_ai_number_nonfinite");
        }
        @Override public String toString() { return this.token; }
    }

    /** Strict bounded UTF-8 JSON AST with original integer/float lexemes. */
    static Object parse(byte[] raw) {
        if (raw == null || raw.length == 0 || raw.length > MAX_PACKAGE_BYTES) throw fail("device_ai_package_capacity");
        if (raw.length >= 3 && (raw[0] & 0xFF) == 0xEF && (raw[1] & 0xFF) == 0xBB && (raw[2] & 0xFF) == 0xBF)
            throw fail("device_ai_json_bom");
        String text = decodeStrictUtf8(raw);
        scanDepth(text);
        Cursor cursor = new Cursor(text);
        Object value = cursor.value();
        cursor.whitespace();
        if (cursor.position != text.length()) throw fail("device_ai_json_invalid");
        checkTree(value, 0, new int[] {0});
        return value;
    }

    /** String input is processed as its own strict UTF-8 encoding (a U+FEFF prefix fails as a BOM). */
    static Object parse(String json) {
        if (json == null) throw fail("device_ai_package_capacity");
        ByteBuffer encoded;
        try {
            encoded = StandardCharsets.UTF_8.newEncoder()
                .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(json));
        } catch (CharacterCodingException invalid) { throw fail("device_ai_json_unicode"); }
        byte[] raw = new byte[encoded.remaining()];
        encoded.get(raw);
        return parse(raw);
    }

    /** Codepoint-sorted canonical JSON text; lexemes verbatim, arrays in source order. */
    static String canonical(Object ast) { return encodeCanonical(ast, 0); }

    static byte[] canonicalBytes(Object ast) { return canonical(ast).getBytes(StandardCharsets.UTF_8); }

    /** sha256(canonical(ast)) hex; the DeviceProjection.sha256 form, no prefix. */
    static String digest(Object ast) { return sha256Hex(canonicalBytes(ast)); }

    /** sha256(namespace_utf8 + 0x00 + canonical(ast)) hex (exact_digest form). */
    static String digest(Object ast, String namespace) {
        if (namespace == null || namespace.isEmpty() || namespace.indexOf('\0') >= 0)
            throw fail("device_ai_material_invalid");
        byte[] head = namespace.getBytes(StandardCharsets.UTF_8), body = canonicalBytes(ast);
        byte[] all = new byte[head.length + 1 + body.length];
        System.arraycopy(head, 0, all, 0, head.length);
        all[head.length] = 0;
        System.arraycopy(body, 0, all, head.length + 1, body.length);
        return sha256Hex(all);
    }

    /**
     * Encode one exact-AST node into the draft-b DeviceAIValue tagged tree
     * ({kind,value}/{kind,items}/{kind,fields} maps over the same AST node domain),
     * so canonical(encodeValue(ast)) reproduces the reference encoded_canonical_text.
     */
    static Object encodeValue(Object ast) { return encodeTagged(ast, 0); }

    // ---- shared helpers -----------------------------------------------------

    private static final String HEX = "0123456789abcdef";

    private static String decodeStrictUtf8(byte[] raw) {
        try {
            return StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(raw)).toString();
        } catch (CharacterCodingException invalid) { throw fail("device_ai_json_utf8"); }
    }

    /** Text pre-scan: at most MAX_DEPTH + 1 simultaneously open brackets (Python _scan_depth). */
    private static void scanDepth(String text) {
        int depth = 0;
        boolean quoted = false, escaped = false;
        for (int at = 0; at < text.length(); at++) {
            char character = text.charAt(at);
            if (quoted) {
                if (escaped) escaped = false;
                else if (character == '\\') escaped = true;
                else if (character == '"') quoted = false;
            } else if (character == '"') quoted = true;
            else if (character == '[' || character == '{') {
                depth++;
                if (depth > MAX_DEPTH + 1) throw fail("device_ai_json_depth");
            } else if (character == ']' || character == '}') depth--;
        }
    }

    /** Tree walk: node budget, AST depth (root = 0), lone-surrogate strings and keys. */
    private static void checkTree(Object node, int depth, int[] budget) {
        budget[0]++;
        if (depth > MAX_DEPTH) throw fail("device_ai_json_depth");
        if (budget[0] > MAX_NODES) throw fail("device_ai_json_nodes");
        if (node instanceof Map) {
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) node).entrySet()) {
                if (!(entry.getKey() instanceof String)) throw fail("device_ai_json_unicode");
                checkString((String) entry.getKey());
                checkTree(entry.getValue(), depth + 1, budget);
            }
        } else if (node instanceof List) {
            for (Object child : (List<?>) node) checkTree(child, depth + 1, budget);
        } else if (node instanceof String) {
            checkString((String) node);
        }
    }

    /** Lone surrogates can only enter via U+D800-style escapes; they never survive the UTF-8 channel. */
    static void checkString(String value) {
        for (int at = 0; at < value.length(); at++) {
            char character = value.charAt(at);
            if (Character.isHighSurrogate(character)) {
                if (++at >= value.length() || !Character.isLowSurrogate(value.charAt(at)))
                    throw fail("device_ai_json_unicode");
            } else if (Character.isLowSurrogate(character)) throw fail("device_ai_json_unicode");
        }
    }

    /**
     * Codepoint order (== UTF-8 byte order). Java String.compareTo is UTF-16
     * code-unit order and would place U+10000+ before U+E000..U+FFFF - wrong here.
     */
    static int compareCodepoints(String left, String right) {
        int first = 0, second = 0;
        while (first < left.length() && second < right.length()) {
            int a = left.codePointAt(first), b = right.codePointAt(second);
            if (a != b) return a < b ? -1 : 1;
            first += Character.charCount(a);
            second += Character.charCount(b);
        }
        return Integer.compare(left.length() - first, right.length() - second);
    }

    private static String encodeCanonical(Object node, int depth) {
        if (depth > MAX_DEPTH) throw fail("device_ai_json_depth");
        if (node instanceof NumberLexeme) return ((NumberLexeme) node).token;
        if (node == null) return "null";
        if (node instanceof Boolean) return ((Boolean) node) ? "true" : "false";
        if (node instanceof String) {
            String value = (String) node;
            checkString(value);
            return quoted(value);
        }
        if (node instanceof List) {
            StringBuilder out = new StringBuilder("[");
            boolean head = true;
            for (Object child : (List<?>) node) {
                if (!head) out.append(',');
                head = false;
                out.append(encodeCanonical(child, depth + 1));
            }
            return out.append(']').toString();
        }
        if (node instanceof Map) {
            Map<?, ?> map = (Map<?, ?>) node;
            for (Object key : map.keySet()) if (!(key instanceof String)) throw fail("device_ai_json_invalid");
            List<String> keys = new ArrayList<>();
            for (Object key : map.keySet()) keys.add((String) key);
            keys.sort(DeviceAiJsonParser::compareCodepoints);
            StringBuilder out = new StringBuilder("{");
            boolean head = true;
            for (String key : keys) {
                if (!head) out.append(',');
                head = false;
                out.append(encodeCanonical(key, depth + 1)).append(':')
                    .append(encodeCanonical(map.get(key), depth + 1));
            }
            return out.append('}').toString();
        }
        throw fail("device_ai_number_or_type_unsupported");
    }

    /** json.dumps(ensure_ascii=False) escaping: quote, backslash and the five one-letter control
     *  shortcuts; other chars below 0x20 as lowercase u00XX; everything else raw. */
    private static String quoted(String value) {
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
                    if (character < 0x20)
                        out.append("\\u00").append(HEX.charAt((character >>> 4) & 0xF)).append(HEX.charAt(character & 0xF));
                    else out.append(character);
            }
        }
        return out.append('"').toString();
    }

    private static Object encodeTagged(Object node, int depth) {
        if (depth > MAX_DEPTH) throw fail("device_ai_json_depth");
        if (node instanceof NumberLexeme) {
            Map<String, Object> token = new LinkedHashMap<>();
            token.put("schema", NUMBER_TOKEN_SCHEMA);
            token.put("token", ((NumberLexeme) node).token);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kind", "number");
            out.put("value", token);
            return out;
        }
        if (node == null) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kind", "null");
            out.put("value", null);
            return out;
        }
        if (node instanceof Boolean) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kind", "boolean");
            out.put("value", node);
            return out;
        }
        if (node instanceof String) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kind", "text");
            out.put("value", node);
            return out;
        }
        if (node instanceof List) {
            List<Object> items = new ArrayList<>();
            for (Object child : (List<?>) node) items.add(encodeTagged(child, depth + 1));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kind", "array");
            out.put("items", items);
            return out;
        }
        if (node instanceof Map) {
            Map<?, ?> map = (Map<?, ?>) node;
            for (Object key : map.keySet()) if (!(key instanceof String)) throw fail("device_ai_value_type_unsupported");
            List<String> keys = new ArrayList<>();
            for (Object key : map.keySet()) keys.add((String) key);
            keys.sort(DeviceAiJsonParser::compareCodepoints);
            List<Object> fields = new ArrayList<>();
            for (String key : keys) {
                Map<String, Object> field = new LinkedHashMap<>();
                field.put("name", key);
                field.put("value", encodeTagged(map.get(key), depth + 1));
                fields.add(field);
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kind", "structured");
            out.put("fields", fields);
            return out;
        }
        throw fail("device_ai_value_type_unsupported");
    }

    private static String sha256Hex(byte[] data) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder out = new StringBuilder(hash.length * 2);
            for (byte value : hash)
                out.append(HEX.charAt((value >> 4) & 0xF)).append(HEX.charAt(value & 0xF));
            return out.toString();
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("SHA-256 unavailable", unavailable);
        }
    }

    /** JSON number grammar: -?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)? */
    private static boolean numberGrammar(String token) {
        int at = 0, length = token.length();
        if (at < length && token.charAt(at) == '-') at++;
        if (at >= length) return false;
        char digit = token.charAt(at);
        if (digit == '0') at++;
        else if (digit >= '1' && digit <= '9') { while (at < length && decimal(token.charAt(at))) at++; }
        else return false;
        if (at < length && token.charAt(at) == '.') {
            at++;
            int start = at;
            while (at < length && decimal(token.charAt(at))) at++;
            if (at == start) return false;
        }
        if (at < length && (token.charAt(at) == 'e' || token.charAt(at) == 'E')) {
            at++;
            if (at < length && (token.charAt(at) == '+' || token.charAt(at) == '-')) at++;
            int start = at;
            while (at < length && decimal(token.charAt(at))) at++;
            if (at == start) return false;
        }
        return at == length;
    }

    private static boolean decimal(char character) { return character >= '0' && character <= '9'; }

    private static boolean finiteBinary64(String token) {
        try { return Double.isFinite(Double.parseDouble(token)); }
        catch (NumberFormatException unreachable) { return false; } // grammar-valid tokens always parse; fail closed
    }

    /** Hand-rolled recursive-descent cursor; duplicate keys judged at object close (object_pairs_hook timing). */
    private static final class Cursor {
        final String text;
        final int length;
        int position = 0;
        int numberCount = 0;

        Cursor(String text) { this.text = text; this.length = text.length(); }

        private void whitespace() {
            while (position < length) {
                char character = text.charAt(position);
                if (character == ' ' || character == '\t' || character == '\n' || character == '\r') position++;
                else break;
            }
        }

        private char take() {
            if (position >= length) throw fail("device_ai_json_invalid");
            return text.charAt(position++);
        }

        private char peek() { return position < length ? text.charAt(position) : '\0'; }

        private boolean word(String literal) {
            if (!text.startsWith(literal, position)) return false;
            position += literal.length();
            return true;
        }

        Object value() {
            whitespace();
            char first = peek();
            if (first == '"') return string();
            if (first == '{') return object();
            if (first == '[') return array();
            if (word("true")) return Boolean.TRUE;
            if (word("false")) return Boolean.FALSE;
            if (word("null")) return null;
            // Python's parse_constant hook: the three constants are scanned as numbers, then rejected.
            if (word("NaN") || word("Infinity") || word("-Infinity")) throw fail("device_ai_number_invalid");
            String token = scanNumber();
            if (token.isEmpty()) throw fail("device_ai_json_invalid");
            position += token.length();
            numberCount++;
            if (numberCount > MAX_NODES) throw fail("device_ai_json_nodes");
            return new NumberLexeme(token);
        }

        private String string() {
            if (take() != '"') throw fail("device_ai_json_invalid");
            StringBuilder out = new StringBuilder();
            boolean escaped = false;
            while (position < length) {
                char character = text.charAt(position++);
                if (escaped) {
                    switch (character) {
                        case '"': out.append('"'); break;
                        case '\\': out.append('\\'); break;
                        case '/': out.append('/'); break;
                        case 'b': out.append('\b'); break;
                        case 'f': out.append('\f'); break;
                        case 'n': out.append('\n'); break;
                        case 'r': out.append('\r'); break;
                        case 't': out.append('\t'); break;
                        case 'u':
                            if (position + 4 > length) throw fail("device_ai_json_invalid");
                            int code = 0;
                            for (int at = 0; at < 4; at++) {
                                char digit = text.charAt(position++);
                                int value = digit >= '0' && digit <= '9' ? digit - '0'
                                    : digit >= 'a' && digit <= 'f' ? digit - 'a' + 10
                                    : digit >= 'A' && digit <= 'F' ? digit - 'A' + 10 : -1;
                                if (value < 0) throw fail("device_ai_json_invalid");
                                code = (code << 4) | value;
                            }
                            out.append((char) code);
                            break;
                        default: throw fail("device_ai_json_invalid");
                    }
                    escaped = false;
                } else if (character == '\\') {
                    escaped = true;
                } else if (character == '"') {
                    return out.toString();
                } else if (character < 0x20) {
                    throw fail("device_ai_json_invalid"); // raw control characters (Python json strict)
                } else {
                    out.append(character);
                }
            }
            throw fail("device_ai_json_invalid"); // unterminated string
        }

        private Object object() {
            position++; // '{'
            whitespace();
            Map<String, Object> result = new LinkedHashMap<>();
            if (peek() == '}') { position++; return result; }
            List<String> keys = new ArrayList<>();
            List<Object> values = new ArrayList<>();
            for (;;) {
                whitespace();
                if (peek() != '"') throw fail("device_ai_json_invalid");
                keys.add(string());
                whitespace();
                if (take() != ':') throw fail("device_ai_json_invalid");
                values.add(value());
                whitespace();
                char next = take();
                if (next == '}') break;
                if (next != ',') throw fail("device_ai_json_invalid");
                if (position >= length) throw fail("device_ai_json_invalid");
            }
            // Duplicate keys judged after unescaping at object close; unclosed objects fail as json_invalid first.
            for (int at = 0; at < keys.size(); at++) {
                if (result.containsKey(keys.get(at))) throw fail("device_ai_json_duplicate_key");
                result.put(keys.get(at), values.get(at));
            }
            return result;
        }

        private Object array() {
            position++; // '['
            List<Object> array = new ArrayList<>();
            whitespace();
            if (peek() == ']') { position++; return array; }
            for (;;) {
                array.add(value());
                whitespace();
                char next = take();
                if (next == ']') break;
                if (next != ',') throw fail("device_ai_json_invalid");
                if (position >= length) throw fail("device_ai_json_invalid");
            }
            return array;
        }

        /** Longest JSON number token at the cursor, or "" (hand-rolled to avoid regex on hot paths). */
        private String scanNumber() {
            int end = position;
            if (end < length && text.charAt(end) == '-') end++;
            if (end < length && text.charAt(end) == '0') end++;
            else if (end < length && text.charAt(end) >= '1' && text.charAt(end) <= '9') {
                while (end < length && decimal(text.charAt(end))) end++;
            } else return "";
            if (end < length && text.charAt(end) == '.') {
                end++;
                int stop = end;
                while (stop < length && decimal(text.charAt(stop))) stop++;
                if (stop == end) return "";
                end = stop;
            }
            if (end < length && (text.charAt(end) == 'e' || text.charAt(end) == 'E')) {
                end++;
                if (end < length && (text.charAt(end) == '+' || text.charAt(end) == '-')) end++;
                int stop = end;
                while (stop < length && decimal(text.charAt(stop))) stop++;
                if (stop == end) return "";
                end = stop;
            }
            return text.substring(position, end);
        }
    }
}
