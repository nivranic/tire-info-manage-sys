package org.taiji.tireintelligence.mobile;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.Iterator;
import org.json.JSONArray;
import org.json.JSONObject;

/** JSONObject rejects Number values above finite double range; retain the JSON integer token. */
final class OfflineJsonInteger {
    private final BigInteger value;
    private OfflineJsonInteger(BigInteger value) { this.value = value; }
    static Object jsonNumber(Object value) {
        if (value instanceof BigInteger && !Double.isFinite(((BigInteger) value).doubleValue()))
            return new OfflineJsonInteger((BigInteger) value);
        return value;
    }
    static BigInteger integer(Object value) {
        if (value instanceof OfflineJsonInteger) return ((OfflineJsonInteger) value).value;
        if (value instanceof BigInteger) return (BigInteger) value;
        if (value instanceof Long || value instanceof Integer || value instanceof Short || value instanceof Byte)
            return BigInteger.valueOf(((Number) value).longValue());
        return null;
    }
    static Number number(Object value) {
        return value instanceof OfflineJsonInteger ? ((OfflineJsonInteger) value).value : (Number) value;
    }
    static boolean isNumber(Object value) { return value instanceof Number || value instanceof OfflineJsonInteger; }
    @Override public String toString() { return value.toString(); }

    /** Exact primitive writer, never JSONObject's quoted fallback for integer token carriers. */
    static String stringify(Object value) throws Exception {
        StringBuilder output = new StringBuilder(); write(output, value, 0); return output.toString();
    }
    private static void write(StringBuilder output, Object value, int depth) throws Exception {
        if (depth > 32) throw new IllegalArgumentException("json_depth");
        if (value == null || value == JSONObject.NULL) output.append("null");
        else if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value; output.append('{');
            Iterator<String> keys = object.keys(); boolean first = true;
            while (keys.hasNext()) {
                String key = keys.next();
                if (!first) output.append(','); first = false;
                write(output, key, depth + 1); output.append(':'); write(output, object.get(key), depth + 1);
            }
            output.append('}');
        } else if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value; output.append('[');
            for (int at = 0; at < array.length(); at++) {
                if (at > 0) output.append(','); write(output, array.get(at), depth + 1);
            }
            output.append(']');
        } else if (value instanceof String) {
            if (!OfflineTireCriteria.validSurrogates((String) value)) throw new IllegalArgumentException("json_surrogate");
            output.append(JSONObject.quote((String) value));
        } else if (value instanceof Boolean || value instanceof OfflineJsonInteger
            || value instanceof BigInteger || value instanceof Long || value instanceof Integer
            || value instanceof Short || value instanceof Byte) output.append(value.toString());
        else if (value instanceof BigDecimal) output.append(((BigDecimal) value).toString());
        else if (value instanceof Double || value instanceof Float) {
            if (!Double.isFinite(((Number) value).doubleValue())) throw new IllegalArgumentException("json_nonfinite");
            output.append(value.toString());
        } else throw new IllegalArgumentException("json_type");
    }
}
