package org.taiji.tireintelligence.mobile;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import org.json.JSONArray;
import org.json.JSONObject;

/** Explicit native @2 transport. Mirrors never make a criteria or authority decision. */
final class OfflineFallbackWire {
    static final int MAX_CORE_BYTES = 8 * 1024 * 1024;
    static final int MAX_TRANSPORT_BYTES = 32 * 1024 * 1024;
    private static void require(boolean valid) throws NativeFailure {
        if (!valid) throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
    }
    private static byte[] utf8(String value) throws NativeFailure {
        require(value != null && OfflineTireCriteria.validSurrogates(value));
        return value.getBytes(StandardCharsets.UTF_8);
    }
    private static boolean integer(Object value) {
        return OfflineJsonInteger.integer(value) != null;
    }
    private static BigDecimal exactNumber(Number value) {
        return integer(value) ? new BigDecimal(value.toString()) : new BigDecimal(value.doubleValue());
    }
    private static Object project(Object value) throws Exception {
        if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value, projected = new JSONObject();
            Iterator<String> keys = object.keys();
            while (keys.hasNext()) { String key = keys.next(); projected.put(key, project(object.get(key))); }
            return projected;
        }
        if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value, projected = new JSONArray();
            for (int at = 0; at < array.length(); at++) projected.put(project(array.get(at)));
            return projected;
        }
        if (OfflineJsonInteger.isNumber(value)) {
            double projected = OfflineJsonInteger.number(value).doubleValue();
            if (!Double.isFinite(projected)) { require(integer(value)); return JSONObject.NULL; }
            return projected == 0 ? 0 : projected;
        }
        return value;
    }
    private static boolean mirror(Object exact, Object mirrored, boolean top) throws Exception {
        if (exact instanceof JSONObject) {
            if (!(mirrored instanceof JSONObject)) return false;
            JSONObject object = (JSONObject) exact, projection = (JSONObject) mirrored;
            if (projection.length() != object.length() + (top ? 1 : 0)) return false;
            Iterator<String> keys = object.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                if (!projection.has(key) || !mirror(object.get(key), projection.get(key), false)) return false;
            }
            return !top || projection.has("raw_json");
        }
        if (exact instanceof JSONArray) {
            if (!(mirrored instanceof JSONArray)) return false;
            JSONArray array = (JSONArray) exact, projection = (JSONArray) mirrored;
            if (array.length() != projection.length()) return false;
            for (int at = 0; at < array.length(); at++) if (!mirror(array.get(at), projection.get(at), false)) return false;
            return true;
        }
        if (OfflineJsonInteger.isNumber(exact)) {
            double expected = OfflineJsonInteger.number(exact).doubleValue();
            if (!Double.isFinite(expected)) return integer(exact) && mirrored == JSONObject.NULL;
            if (!(mirrored instanceof Number) || !Double.isFinite(((Number) mirrored).doubleValue())) return false;
            return exactNumber((Number) mirrored).compareTo(new BigDecimal(expected == 0 ? 0 : expected)) == 0;
        }
        return exact == JSONObject.NULL ? mirrored == JSONObject.NULL : exact.equals(mirrored);
    }
    private static void noRecursiveTransport(JSONObject core) throws NativeFailure {
        require(!core.has("raw_json"));
        for (String key : new String[]{"intent", "grant"}) {
            Object protocol = core.opt(key);
            if (protocol instanceof JSONObject) require(!((JSONObject) protocol).has("raw_json"));
        }
        // An ordinary payload.facts.raw_json remains data, not a transport wrapper.
    }
    static JSONObject decode(JSONObject outer) throws NativeFailure {
        try {
            require(outer != null && outer.opt("raw_json") instanceof String);
            String raw = outer.getString("raw_json");
            require(raw.length() <= MAX_CORE_BYTES && utf8(raw).length <= MAX_CORE_BYTES);
            Object parsed = OfflineTireCriteria.parse(raw, MAX_CORE_BYTES, 1000000);
            require(parsed instanceof JSONObject);
            JSONObject core = (JSONObject) parsed;
            noRecursiveTransport(core);
            require(mirror(core, outer, true));
            require(utf8(outer.toString()).length <= MAX_TRANSPORT_BYTES);
            return core;
        } catch (NativeFailure failure) { throw failure; }
        catch (Exception invalid) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
    }
    static JSONObject encode(JSONObject core) throws NativeFailure {
        try {
            require(core != null); noRecursiveTransport(core);
            String raw = OfflineJsonInteger.stringify(core);
            require(raw != null && raw.length() <= MAX_CORE_BYTES && utf8(raw).length <= MAX_CORE_BYTES);
            // Parsing validates serialized grammar/duplicates/surrogates and rejects nonfinite floats.
            Object checked = OfflineTireCriteria.parse(raw, MAX_CORE_BYTES, 1000000);
            require(checked instanceof JSONObject);
            JSONObject result = (JSONObject) project((JSONObject) checked);
            result.put("raw_json", raw);
            require(utf8(result.toString()).length <= MAX_TRANSPORT_BYTES);
            return result;
        } catch (NativeFailure failure) { throw failure; }
        catch (Exception invalid) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
    }
}
