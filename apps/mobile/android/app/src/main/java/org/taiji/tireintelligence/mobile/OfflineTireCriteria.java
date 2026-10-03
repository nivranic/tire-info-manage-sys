package org.taiji.tireintelligence.mobile;

import android.util.JsonReader;
import android.util.JsonToken;
import java.io.StringReader;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONObject;

/** Pure projection of original variant/facts. No storage, FTS, source or consent I/O. */
final class OfflineTireCriteria {
    enum Truth { TRUE, FALSE, UNKNOWN }
    private enum Status { KNOWN, UNKNOWN, INVALID, CONFLICT }
    private static final Set<String> FIELDS = set("brand", "family", "model", "variant_id", "region",
        "manufacturer_product_code", "gtin", "eprel_id", "size", "construction", "load_index",
        "speed_rating", "oe_mark", "acoustic_technology", "technology_features", "xl", "hl",
        "run_flat", "acoustic_foam", "ev_marketing_mark", "season", "utqg_treadwear",
        "utqg_traction", "utqg_temperature", "eu_fuel_class", "eu_wet_grip", "eu_external_noise_db", "eu_noise_class");
    private static final Set<String> IDENTITY = set("brand", "model", "region", "manufacturer_product_code",
        "size", "load_index", "speed_rating", "oe_mark", "acoustic_technology", "xl", "hl", "run_flat");
    private static final Set<String> TECHNICAL = set("family", "construction", "load_index", "speed_rating",
        "oe_mark", "acoustic_technology", "season", "utqg_traction", "utqg_temperature",
        "eu_fuel_class", "eu_wet_grip", "eu_noise_class");
    private static final Set<String> BOOLEAN = set("xl", "hl", "run_flat", "acoustic_foam", "ev_marketing_mark");
    private static final Set<String> NUMBER = set("utqg_treadwear", "eu_external_noise_db");
    private static final Set<String> SPEED = set("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8",
        "b", "c", "d", "e", "f", "g", "j", "k", "l", "m", "n", "p", "q", "r", "s", "t",
        "u", "h", "v", "w", "y", "(y)", "zr");
    private static final Pattern SIZE = Pattern.compile("([0-9]{3})/([0-9]{2})(ZR|R)([0-9]{2}(?:\\.5)?)");

    private static Set<String> set(String... values) { return new HashSet<>(Arrays.asList(values)); }
    private static boolean absent(Object value) { return value == null || value == JSONObject.NULL; }
    private static void require(boolean valid) {
        if (!valid) throw new IllegalArgumentException("tire_criteria_invalid");
    }
    private static final class Read {
        final Status status;
        final Object value;
        Read(Status status, Object value) { this.status = status; this.value = value; }
    }

    /** Accepts only finite JSON numbers; integers retain their original precision. */
    private static Number number(Object value) {
        require(OfflineJsonInteger.isNumber(value));
        value = OfflineJsonInteger.number(value);
        if (value instanceof BigInteger || value instanceof Long || value instanceof Integer
            || value instanceof Short || value instanceof Byte) return (Number) value;
        double floating = ((Number) value).doubleValue();
        require(Double.isFinite(floating));
        if (floating == Math.rint(floating)) return new BigDecimal(floating).toBigIntegerExact();
        return floating;
    }
    private static BigDecimal exact(Number value) {
        if (value instanceof BigInteger) return new BigDecimal((BigInteger) value);
        if (value instanceof Long || value instanceof Integer || value instanceof Short || value instanceof Byte)
            return BigDecimal.valueOf(value.longValue());
        // Python compares a non-integral binary float with an integer exactly.
        return new BigDecimal(value.doubleValue());
    }
    private static String size(String value) {
        StringBuilder digits = new StringBuilder(), original = new StringBuilder();
        value.codePoints().forEach(codepoint -> {
            if (OfflineFilterUnicode.isWhitespace(codepoint)) return;
            int digit = OfflineFilterUnicode.decimalDigit(codepoint);
            int upper = codepoint == 'r' ? 'R' : codepoint == 'z' ? 'Z' : codepoint;
            original.appendCodePoint(upper);
            digits.appendCodePoint(digit >= 0 ? '0' + digit : upper);
        });
        Matcher match = SIZE.matcher(digits);
        require(match.matches());
        int width = Integer.parseInt(match.group(1)), aspect = Integer.parseInt(match.group(2));
        double rim = Double.parseDouble(match.group(4));
        require(width >= 100 && width <= 455 && aspect >= 20 && aspect <= 95 && rim >= 10 && rim <= 30);
        // Python retains the requested rim's decimal digits after normalizing width/aspect.
        String originalRim = original.substring(original.lastIndexOf("R") + 1);
        require(!originalRim.contains(".") || originalRim.endsWith(".5"));
        return width + "/" + aspect + match.group(3) + originalRim;
    }
    private static Object normalize(String field, Object value) {
        if (BOOLEAN.contains(field)) { require(value instanceof Boolean); return value; }
        if (NUMBER.contains(field)) return number(value);
        String text = OfflineFilterUnicode.text(value);
        if (field.equals("size")) return size(text);
        if (field.equals("load_index")) require(text.matches("[0-9]{2,3}(?:/[0-9]{2,3})?"));
        if (field.equals("speed_rating")) require(SPEED.contains(text));
        return text;
    }
    static JSONArray validateFilters(JSONArray filters) throws Exception {
        require(filters != null && filters.length() <= 16);
        JSONArray normalized = new JSONArray();
        for (int at = 0; at < filters.length(); at++) {
            Object raw = filters.get(at); require(raw instanceof JSONObject);
            JSONObject condition = (JSONObject) raw;
            Object fieldValue = condition.opt("field"), opValue = condition.opt("op");
            require(fieldValue instanceof String && opValue instanceof String);
            String field = (String) fieldValue, op = (String) opValue;
            require(FIELDS.contains(field));
            boolean presence = op.equals("is_known") || op.equals("is_unknown");
            require(presence || op.equals("eq") || (NUMBER.contains(field) && (op.equals("gte") || op.equals("lte"))));
            require(condition.length() == (presence ? 2 : 3) && condition.has("field") && condition.has("op")
                && (presence ? !condition.has("value") : condition.has("value")));
            JSONObject row = new JSONObject().put("field", field).put("op", op);
            if (!presence) row.put("value", OfflineJsonInteger.jsonNumber(normalize(field, condition.get("value"))));
            normalized.put(row);
        }
        // Caller freezes canonical ordering/fingerprint. This module never reencodes them.
        return normalized;
    }
    private static Read read(JSONObject row, String field) {
        Object rawFacts = row.has("facts") ? row.opt("facts") : new JSONObject();
        if (!(rawFacts instanceof JSONObject)) return new Read(Status.INVALID, null);
        JSONObject facts = (JSONObject) rawFacts;
        Object rawConflicts = facts.has("source_field_conflicts") ? facts.opt("source_field_conflicts") : new JSONArray();
        if (!(rawConflicts instanceof JSONArray)) return new Read(Status.INVALID, null);
        JSONArray conflicts = (JSONArray) rawConflicts;
        for (int at = 0; at < conflicts.length(); at++) {
            Object conflict = conflicts.opt(at);
            if (conflict instanceof JSONObject) {
                Object key = ((JSONObject) conflict).opt("field");
                if (field.equals(key) || ("facts." + field).equals(key) || ("identity." + field).equals(key))
                    return new Read(Status.CONFLICT, null);
            }
        }
        Object value = field.equals("variant_id") ? row.opt("id") : IDENTITY.contains(field) ? row.opt(field) : facts.opt(field);
        if (absent(value) || (value instanceof String && OfflineFilterUnicode.blank((String) value)))
            return new Read(Status.UNKNOWN, null);
        try {
            if (TECHNICAL.contains(field) && value instanceof String) {
                String text = OfflineFilterUnicode.text(value);
                if (text.equals("unknown") || text.equals("unspecified")) return new Read(Status.UNKNOWN, null);
            }
            if (field.equals("technology_features")) {
                if (!(value instanceof JSONArray)) return new Read(Status.INVALID, null);
                JSONArray input = (JSONArray) value, texts = new JSONArray();
                if (input.length() == 0) return new Read(Status.UNKNOWN, null);
                for (int at = 0; at < input.length(); at++) texts.put(OfflineFilterUnicode.text(input.get(at)));
                return new Read(Status.KNOWN, texts);
            }
            return new Read(Status.KNOWN, normalize(field, value));
        } catch (Exception invalid) { return new Read(Status.INVALID, null); }
    }
    private static Truth condition(JSONObject row, JSONObject condition) throws Exception {
        String field = condition.getString("field"), op = condition.getString("op");
        Read actual = read(row, field);
        if (actual.status == Status.INVALID || actual.status == Status.CONFLICT) return Truth.UNKNOWN;
        if (op.equals("is_known")) return actual.status == Status.KNOWN ? Truth.TRUE : Truth.FALSE;
        if (op.equals("is_unknown")) return actual.status == Status.UNKNOWN ? Truth.TRUE : Truth.FALSE;
        if (actual.status != Status.KNOWN) return Truth.UNKNOWN;
        Object expected = condition.get("value");
        boolean matched;
        if (NUMBER.contains(field)) {
            int order = exact((Number) actual.value).compareTo(exact(number(expected)));
            matched = op.equals("eq") ? order == 0 : op.equals("gte") ? order >= 0 : order <= 0;
        } else if (field.equals("technology_features")) {
            matched = false;
            JSONArray values = (JSONArray) actual.value;
            for (int at = 0; at < values.length(); at++) if (expected.equals(values.get(at))) matched = true;
        } else matched = expected.equals(actual.value);
        return matched ? Truth.TRUE : Truth.FALSE;
    }
    static Truth evaluate(JSONObject variant, JSONArray validatedFilters) throws Exception {
        boolean unknown = false;
        for (int at = 0; at < validatedFilters.length(); at++) {
            Truth result = condition(variant, validatedFilters.getJSONObject(at));
            if (result == Truth.FALSE) return Truth.FALSE;
            unknown |= result == Truth.UNKNOWN;
        }
        return unknown ? Truth.UNKNOWN : Truth.TRUE;
    }
    static Truth evaluateBasicSize(JSONObject variant, String canonicalQuerySize) throws Exception {
        // TireQuery parse_size preserves rim Nd spelling; this is not an advanced TireFilter value.
        return condition(variant, new JSONObject().put("field", "size").put("op", "eq").put("value", canonicalQuerySize));
    }
    static Truth evaluateVariantJson(String variantJson, String filtersJson) throws Exception {
        Object row = parse(variantJson), filters = parse(filtersJson);
        require(row instanceof JSONObject && filters instanceof JSONArray);
        return evaluate((JSONObject) row, validateFilters((JSONArray) filters));
    }

    /** Internal lossless scalar decoder. Integer and floating JSON tokens stay distinct. */
    static Object parse(String json) throws Exception {
        return parse(json, 1024 * 1024, 250000);
    }
    static Object parse(String json, int maxCharacters, int maxNodes) throws Exception {
        require(json != null && json.length() <= maxCharacters);
        try (JsonReader reader = new JsonReader(new StringReader(json))) {
            reader.setLenient(false);
            Object value = parse(reader, 0, new int[] {0}, maxNodes);
            require(reader.peek() == JsonToken.END_DOCUMENT);
            return value;
        }
    }
    static boolean validSurrogates(String value) {
        for (int at = 0; at < value.length(); at++) {
            char character = value.charAt(at);
            if (Character.isHighSurrogate(character)) {
                if (++at >= value.length() || !Character.isLowSurrogate(value.charAt(at))) return false;
            } else if (Character.isLowSurrogate(character)) return false;
        }
        return true;
    }
    private static Object parse(JsonReader reader, int depth, int[] nodes, int maxNodes) throws Exception {
        require(depth <= 32 && ++nodes[0] <= maxNodes);
        switch (reader.peek()) {
            case BEGIN_OBJECT:
                reader.beginObject(); JSONObject object = new JSONObject(); Set<String> seen = new HashSet<>();
                while (reader.hasNext()) {
                    String key = reader.nextName(); require(key.length() <= 256 && validSurrogates(key) && seen.add(key));
                    object.put(key, parse(reader, depth + 1, nodes, maxNodes));
                }
                reader.endObject(); return object;
            case BEGIN_ARRAY:
                reader.beginArray(); JSONArray array = new JSONArray();
                while (reader.hasNext()) { require(array.length() < 40000); array.put(parse(reader, depth + 1, nodes, maxNodes)); }
                reader.endArray(); return array;
            case STRING:
                String string = reader.nextString(); require(validSurrogates(string)); return string;
            case BOOLEAN: return reader.nextBoolean();
            case NULL: reader.nextNull(); return JSONObject.NULL;
            case NUMBER:
                String token = reader.nextString();
                if (token.matches("-?(0|[1-9][0-9]*)")) {
                    BigInteger integer = new BigInteger(token);
                    return OfflineJsonInteger.jsonNumber(integer.bitLength() <= 63 ? integer.longValue() : integer);
                }
                return Double.valueOf(token);
            default: throw new IllegalArgumentException("tire_json_invalid");
        }
    }
}
