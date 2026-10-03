package org.taiji.tireintelligence.mobile;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONObject;

/** Pure closed values only. Store owns authority, runtime, binding CAS, clocks and durable claims. */
final class OfflineFallbackValues {
    private static final Set<String> KINDS = Set.of("tire", "vehicle_fitments", "recall_campaign", "recall_search");
    private static final Set<String> MODES = Set.of("ask", "never", "session_allow", "source_allow", "query_allow");
    private static final BigInteger SAFE = BigInteger.valueOf(OfflineFallbackGrant.SAFE);
    private static final Pattern SIZE = Pattern.compile("([0-9]{3})/([0-9]{2})(ZR|R)([0-9]{2}(?:\\.5)?)");
    private OfflineFallbackValues() {}

    private static void require(boolean valid) throws NativeFailure {
        if (!valid) throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
    }
    private static void keys(JSONObject value, String... expected) throws NativeFailure {
        require(value != null); Set<String> names = Set.of(expected); require(value.length() == names.size());
        Iterator<String> keys = value.keys(); while (keys.hasNext()) require(names.contains(keys.next()));
    }
    private static String text(JSONObject value, String key, int maximum) throws NativeFailure {
        Object field = value.opt(key); require(field instanceof String);
        String result = (String) field;
        require(OfflineTireCriteria.validSurrogates(result) && result.codePointCount(0, result.length()) <= maximum);
        return result;
    }
    private static JSONObject object(JSONObject value, String key) throws NativeFailure {
        Object field = value.opt(key); require(field instanceof JSONObject); return (JSONObject) field;
    }
    private static JSONArray array(JSONObject value, String key, int maximum) throws NativeFailure {
        Object field = value.opt(key); require(field instanceof JSONArray && ((JSONArray) field).length() <= maximum);
        return (JSONArray) field;
    }
    private static long integer(JSONObject value, String key, boolean positive) throws NativeFailure {
        BigInteger result = OfflineJsonInteger.integer(value.opt(key));
        require(result != null && result.signum() >= (positive ? 1 : 0) && result.compareTo(SAFE) <= 0);
        return result.longValueExact();
    }
    private static String uuid(JSONObject value, String key) throws NativeFailure {
        String result = text(value, key, 36);
        require(result.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"));
        try { require(UUID.fromString(result).toString().equals(result)); }
        catch (IllegalArgumentException invalid) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
        return result;
    }
    private static String hash(JSONObject value, String key) throws NativeFailure {
        String result = text(value, key, 64); require(result.matches("[0-9a-f]{64}")); return result;
    }
    private static String profile(JSONObject value, String key) throws NativeFailure {
        String result = text(value, key, 80);
        // Android's established profile identifier is the SHA-256 namespace digest.
        // UUID profiles remain valid closed values for other native implementations.
        if (result.matches("[0-9a-f]{64}")) return result;
        return uuid(value, key);
    }
    private static String source(JSONObject value, String key) throws NativeFailure {
        String result = text(value, key, 80); require(result.matches("[a-z0-9-]{1,80}")); return result;
    }
    private static JSONObject copy(JSONObject value) throws Exception {
        String raw = OfflineJsonInteger.stringify(value);
        require(raw.getBytes(StandardCharsets.UTF_8).length <= OfflineFallbackWire.MAX_CORE_BYTES);
        Object copied = OfflineTireCriteria.parse(raw, OfflineFallbackWire.MAX_CORE_BYTES, 1000000);
        require(copied instanceof JSONObject); return (JSONObject) copied;
    }
    private static String collapse(String value) {
        StringBuilder out = new StringBuilder(); boolean pending = false;
        for (int at = 0; at < value.length();) {
            int codepoint = value.codePointAt(at); at += Character.charCount(codepoint);
            if (OfflineFilterUnicode.isWhitespace(codepoint)) { pending = out.length() > 0; continue; }
            if (pending) out.append(' '); out.appendCodePoint(codepoint); pending = false;
        }
        return out.toString();
    }
    private static String trim(String value) {
        int start = 0, end = value.length();
        while (start < end && OfflineFilterUnicode.isWhitespace(value.codePointAt(start))) start += Character.charCount(value.codePointAt(start));
        while (end > start && OfflineFilterUnicode.isWhitespace(value.codePointBefore(end))) end -= Character.charCount(value.codePointBefore(end));
        return value.substring(start, end);
    }
    /** TireQuery model alias normalization, without advanced-filter NFKC/category inference. */
    static String canonicalTireModel(String value) throws NativeFailure {
        require(value != null && OfflineTireCriteria.validSurrogates(value) && value.codePointCount(0, value.length()) <= 120);
        String result = collapse(value); require(!result.isEmpty()); String alias = OfflineFilterUnicode.fold(result);
        if (alias.startsWith("michelin ")) alias = alias.substring(9);
        if (alias.equals("psev") || alias.equals("pilot sport ev")) return "Pilot Sport EV";
        if (alias.equals("ps4s") || alias.equals("pilot sport 4 s")) return "Pilot Sport 4 S";
        return result;
    }
    /** Raw TireQuery parse_size: Unicode Nd, ASCII separators/.5; retain original rim Nd spelling. */
    static String canonicalTireSize(String value) throws NativeFailure {
        require(value != null && OfflineTireCriteria.validSurrogates(value) && value.codePointCount(0, value.length()) <= 24);
        StringBuilder digits = new StringBuilder(), original = new StringBuilder();
        value.codePoints().forEach(cp -> {
            if (OfflineFilterUnicode.isWhitespace(cp)) return;
            int digit = OfflineFilterUnicode.decimalDigit(cp), upper = cp == 'r' ? 'R' : cp == 'z' ? 'Z' : cp;
            original.appendCodePoint(upper); digits.appendCodePoint(digit >= 0 ? '0' + digit : upper);
        });
        Matcher match = SIZE.matcher(digits); require(match.matches());
        int width = Integer.parseInt(match.group(1)), aspect = Integer.parseInt(match.group(2));
        double rim = Double.parseDouble(match.group(4));
        require(width >= 100 && width <= 455 && aspect >= 20 && aspect <= 95 && rim >= 10 && rim <= 30);
        String originalRim = original.substring(original.lastIndexOf("R") + 1);
        require(!originalRim.contains(".") || originalRim.endsWith(".5"));
        return width + "/" + aspect + match.group(3) + originalRim;
    }

    static JSONObject validateIntent(JSONObject input) throws Exception {
        try {
            keys(input, "schema", "attempt_id", "query_fingerprint", "source_id", "source_access_generation",
                "authority", "fallback_policy", "failure", "query_kind", "query", "filters");
            require("device-fallback-intent@2".equals(input.opt("schema")));
            uuid(input, "attempt_id"); hash(input, "query_fingerprint"); source(input, "source_id");
            integer(input, "source_access_generation", false);
            require(Set.of("ask", "never").contains(text(input, "fallback_policy", 5)));
            JSONObject authority = object(input, "authority"); keys(authority, "runtime_session_id", "authority_revision");
            uuid(authority, "runtime_session_id"); integer(authority, "authority_revision", true);
            JSONObject failure = object(input, "failure"); keys(failure, "scope", "reason", "query_id");
            String scope = text(failure, "scope", 32), reason = text(failure, "reason", 40);
            if (scope.equals("api_transport")) require(failure.isNull("query_id") && Set.of("api_network_unavailable", "api_timeout").contains(reason));
            else { require(scope.equals("source_response") && Set.of("upstream_network_error", "upstream_timeout").contains(reason)); uuid(failure, "query_id"); }
            String kind = text(input, "query_kind", 32); require(KINDS.contains(kind));
            JSONObject query = object(input, "query"); JSONArray filters = array(input, "filters", 16);
            if (kind.equals("tire")) {
                require(query.length() >= 1 && query.length() <= 2);
                Iterator<String> names = query.keys(); while (names.hasNext()) require(Set.of("model", "size").contains(names.next()));
                if (query.has("model")) {String model = text(query, "model", 120); require(model.equals(canonicalTireModel(model)));}
                if (query.has("size")) {String size = text(query, "size", 24); require(size.equals(canonicalTireSize(size)));}
                JSONArray canonical = OfflineTireCriteria.validateFilters(filters);
                require(sameValue(filters, canonical, 0));
            } else {
                require(filters.length() == 0);
                if (kind.equals("vehicle_fitments")) {
                    keys(query, "vehicle_id"); String id = text(query, "vehicle_id", 100);
                    require(!id.isEmpty() && id.equals(trim(id)) && !id.codePoints().anyMatch(OfflineFilterUnicode::categoryC));
                } else if (kind.equals("recall_campaign")) {
                    keys(query, "campaign_number"); require(text(query, "campaign_number", 9).matches("[0-9]{2}T[0-9]{6}"));
                } else {
                    keys(query, "search", "offset"); String search = text(query, "search", 120);
                    require(!search.isEmpty() && search.equals(collapse(search)) && search.codePoints().noneMatch(cp -> cp < 32));
                    String offset = text(query, "offset", 5); require(offset.matches("0|[1-9][0-9]{0,4}"));
                    int page = Integer.parseInt(offset); require(page <= 10000 && page % 10 == 0);
                }
            }
            return copy(input);
        } catch (NativeFailure failure) {throw failure;}
        catch (Exception invalid) {throw new NativeFailure("OFFLINE_FALLBACK_INVALID");}
    }

    /** Validates an exact core after transport decode. decisionFlag=true is decide, false authorize. */
    static void slotRequest(JSONObject request, boolean decisionFlag) throws Exception {
        if (decisionFlag) keys(request, "intent", "slot_id", "expected_generation", "expected_sha256",
            "expected_profile_id", "expected_owner_epoch", "decision");
        else keys(request, "intent", "slot_id", "expected_generation", "expected_sha256", "expected_profile_id", "expected_owner_epoch");
        validateIntent(object(request, "intent")); uuid(request, "slot_id"); profile(request, "expected_profile_id");
        integer(request, "expected_generation", true); integer(request, "expected_owner_epoch", false); hash(request, "expected_sha256");
        if (decisionFlag) require(Set.of("allow", "deny").contains(text(request, "decision", 5)));
    }

    private static void kinds(JSONObject value) throws Exception {
        JSONArray list = array(value, "query_kinds", 4); require(list.length() > 0); Set<String> seen = new HashSet<>();
        for (int at = 0; at < list.length(); at++) {Object kind = list.get(at); require(kind instanceof String && KINDS.contains(kind) && seen.add((String) kind));}
    }
    private static List<JSONObject> pins(JSONObject scope) throws Exception {
        String kind = text(scope, "kind", 7); List<JSONObject> pins = new ArrayList<>();
        if (kind.equals("source")) {keys(scope, "kind", "source_id", "access_generation", "query_kinds"); pins.add(scope);}
        else {
            require(kind.equals("session") || kind.equals("query"));
            if (kind.equals("session")) keys(scope, "kind", "sources");
            else {keys(scope, "kind", "query_kind", "sources"); require(KINDS.contains(text(scope, "query_kind", 32)));}
            JSONArray list = array(scope, "sources", 10); require(list.length() > 0);
            for (int at = 0; at < list.length(); at++) {Object row = list.get(at); require(row instanceof JSONObject); JSONObject pin = (JSONObject) row;
                if (kind.equals("query")) keys(pin, "source_id", "access_generation"); else keys(pin, "source_id", "access_generation", "query_kinds"); pins.add(pin);}
        }
        Set<String> seen = new HashSet<>(); for (JSONObject pin : pins) {require(seen.add(source(pin, "source_id"))); integer(pin, "access_generation", false); if (!kind.equals("query")) kinds(pin);}
        return pins;
    }

    static JSONObject validateChoice(JSONObject authority, JSONObject choice) throws Exception {
        try {
            keys(choice, "mode", "scope", "binding", "allow_same_scope_sync_binding_advance");
            String mode = text(choice, "mode", 16); require(MODES.contains(mode)); JSONObject scope = object(choice, "scope");
            List<JSONObject> pins = pins(scope); boolean preference = mode.equals("ask") || mode.equals("never");
            require(choice.opt("allow_same_scope_sync_binding_advance") instanceof Boolean);
            boolean advance = choice.getBoolean("allow_same_scope_sync_binding_advance");
            if (preference) require(choice.isNull("binding") && !advance);
            else {
                require(mode.equals(scope.getString("kind") + "_allow"));
                JSONObject binding = object(choice, "binding"); keys(binding, "binding_revision", "slot_id", "generation", "package_id", "sha256", "history_scope_fingerprint", "source_ids");
                integer(binding, "binding_revision", true); integer(binding, "generation", true); uuid(binding, "slot_id"); uuid(binding, "package_id"); hash(binding, "sha256"); hash(binding, "history_scope_fingerprint");
                JSONArray ids = array(binding, "source_ids", 200); String previous = null;
                for (int at = 0; at < ids.length(); at++) {Object id = ids.get(at); require(id instanceof String && ((String) id).matches("[a-z0-9-]{1,80}"));
                    String current = (String) id; require(previous == null || previous.compareTo(current) < 0); previous = current;
                    if (advance && pins.stream().noneMatch(pin -> current.equals(pin.opt("source_id")))) throw new NativeFailure("OFFLINE_FALLBACK_SYNC_ADVANCE_SCOPE_UNAVAILABLE");}
            }
            keys(authority, "schema", "runtime_session_id", "authority_revision", "state", "observed_at", "profile_id", "owner_epoch", "owner_scope_id", "sources");
            require("device-fallback-source-authority@1".equals(authority.opt("schema")) && "last_observed".equals(authority.opt("state")));
            uuid(authority, "runtime_session_id"); integer(authority, "authority_revision", true); profile(authority, "profile_id"); integer(authority, "owner_epoch", false); hash(authority, "owner_scope_id");
            OffsetDateTime.parse(text(authority, "observed_at", 80)); JSONArray catalog = array(authority, "sources", 200); Set<String> registered = new HashSet<>();
            for (int at = 0; at < catalog.length(); at++) {JSONObject row = catalog.getJSONObject(at); keys(row, "source_id", "access_generation", "query_kinds", "can_query", "can_fetch"); require(registered.add(source(row, "source_id"))); integer(row, "access_generation", false); kinds(row); require(row.opt("can_query") instanceof Boolean && row.opt("can_fetch") instanceof Boolean);}
            for (JSONObject pin : pins) {
                JSONObject current = null; for (int at = 0; at < catalog.length(); at++) {JSONObject row = catalog.getJSONObject(at); if (pin.getString("source_id").equals(row.getString("source_id"))) current = row;}
                require(current != null && integer(pin, "access_generation", false) == integer(current, "access_generation", false));
                require(preference || current.getBoolean("can_query"));
                JSONArray supported = current.getJSONArray("query_kinds"); Set<String> allowed = new HashSet<>(); for (int at = 0; at < supported.length(); at++) allowed.add(supported.getString(at));
                if (scope.getString("kind").equals("query")) require(allowed.contains(scope.getString("query_kind")));
                else {JSONArray requested = pin.getJSONArray("query_kinds"); for (int at = 0; at < requested.length(); at++) require(allowed.contains(requested.getString(at)));}
            }
            return copy(choice);
        } catch (NativeFailure failure) {throw failure;}
        catch (Exception invalid) {throw new NativeFailure("OFFLINE_FALLBACK_INVALID");}
    }

    /** Pure scope/pin/kind match. Store separately enforces current owner/runtime/state/expiry. */
    static boolean matches(JSONObject policy, JSONObject intent, boolean legacyIgnoresPin) throws Exception {
        JSONObject scope = object(policy, "scope"); List<JSONObject> pins = pins(scope);
        String source = source(intent, "source_id"), kind = legacyIgnoresPin ? "tire" : text(intent, "query_kind", 32);
        require(KINDS.contains(kind)); if (scope.getString("kind").equals("query") && !kind.equals(scope.getString("query_kind"))) return false;
        for (JSONObject pin : pins) {
            if (!source.equals(pin.getString("source_id")) || (!legacyIgnoresPin && integer(intent, "source_access_generation", false) != integer(pin, "access_generation", false))) continue;
            if (scope.getString("kind").equals("query")) return true;
            JSONArray supported = pin.getJSONArray("query_kinds"); for (int at = 0; at < supported.length(); at++) if (kind.equals(supported.getString(at))) return true;
        }
        return false;
    }

    static boolean same(JSONObject left, JSONObject right) throws Exception {return sameValue(left, right, 0);}
    private static BigDecimal number(Object value) throws NativeFailure {
        BigInteger integer = OfflineJsonInteger.integer(value); if (integer != null) return new BigDecimal(integer);
        require(value instanceof Number); double floating = ((Number) value).doubleValue(); require(Double.isFinite(floating));
        return new BigDecimal(floating); // exact binary64 value; never cast a JSON integer to double
    }
    private static boolean sameValue(Object left, Object right, int depth) throws Exception {
        require(depth <= 32);
        if (left instanceof JSONObject) {if (!(right instanceof JSONObject)) return false; JSONObject a = (JSONObject) left, b = (JSONObject) right; if (a.length() != b.length()) return false;
            Iterator<String> keys = a.keys(); while (keys.hasNext()) {String key = keys.next(); if (!b.has(key) || !sameValue(a.get(key), b.get(key), depth + 1)) return false;} return true;}
        if (left instanceof JSONArray) {if (!(right instanceof JSONArray)) return false; JSONArray a = (JSONArray) left, b = (JSONArray) right; if (a.length() != b.length()) return false;
            for (int at = 0; at < a.length(); at++) if (!sameValue(a.get(at), b.get(at), depth + 1)) return false; return true;}
        if (OfflineJsonInteger.isNumber(left)) return OfflineJsonInteger.isNumber(right) && number(left).compareTo(number(right)) == 0;
        if (left == null || left == JSONObject.NULL) return right == null || right == JSONObject.NULL;
        return left.getClass().equals(right == null ? null : right.getClass()) && left.equals(right);
    }

    static String scopeFingerprint(JSONObject approvedScope) throws Exception {
        require(approvedScope != null); StringBuilder stable = new StringBuilder(); stable(stable, approvedScope, 0);
        byte[] material = ("device-fallback-approved-scope@1\0" + stable).getBytes(StandardCharsets.UTF_8);
        require(material.length <= OfflineFallbackWire.MAX_CORE_BYTES); return OfflineCipher.sha256(material);
    }
    private static int codepointOrder(String left, String right) {
        for (int a = 0, b = 0; a < left.length() || b < right.length();) {
            if (a >= left.length()) return -1; if (b >= right.length()) return 1;
            int x = left.codePointAt(a), y = right.codePointAt(b); if (x != y) return Integer.compare(x, y);
            a += Character.charCount(x); b += Character.charCount(y);
        }
        return 0;
    }
    private static void quote(StringBuilder out, String value) throws NativeFailure {
        require(OfflineTireCriteria.validSurrogates(value)); out.append('"');
        for (int at = 0; at < value.length(); at++) {char c = value.charAt(at); switch (c) {
            case '"': out.append("\\\""); break; case '\\': out.append("\\\\"); break;
            case '\b': out.append("\\b"); break; case '\f': out.append("\\f"); break;
            case '\n': out.append("\\n"); break; case '\r': out.append("\\r"); break; case '\t': out.append("\\t"); break;
            default: if (c < 32) out.append(String.format(java.util.Locale.ROOT, "\\u%04x", (int) c)); else out.append(c);
        }} out.append('"');
    }
    private static void stable(StringBuilder out, Object value, int depth) throws Exception {
        require(depth <= 32);
        if (value instanceof JSONObject) {JSONObject object = (JSONObject) value; List<String> keys = new ArrayList<>(); object.keys().forEachRemaining(keys::add); keys.sort(OfflineFallbackValues::codepointOrder); out.append('{');
            for (int at = 0; at < keys.size(); at++) {if (at > 0) out.append(','); String key = keys.get(at); quote(out, key); out.append(':'); stable(out, object.get(key), depth + 1);} out.append('}');}
        else if (value instanceof JSONArray) {JSONArray array = (JSONArray) value; out.append('['); for (int at = 0; at < array.length(); at++) {if (at > 0) out.append(','); stable(out, array.get(at), depth + 1);} out.append(']');}
        else if (value == null || value == JSONObject.NULL) out.append("null");
        else if (value instanceof String) quote(out, (String) value);
        else if (value instanceof Boolean) out.append(value);
        else {BigInteger integer = OfflineJsonInteger.integer(value); require(integer != null && integer.signum() >= 0 && integer.compareTo(SAFE) <= 0); out.append(integer);}
    }
}
