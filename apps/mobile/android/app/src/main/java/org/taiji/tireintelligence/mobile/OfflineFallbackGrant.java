package org.taiji.tireintelligence.mobile;

import android.os.SystemClock;
import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

/** One host lifetime only. Caller-observed failure is not trusted upstream proof. */
final class OfflineFallbackGrant {
    static final long SAFE = 9007199254740990L;
    static final long TTL_MILLIS = 300000L;
    interface Clock { long wall(); long monotonic(); }
    static final Clock SYSTEM_CLOCK = new Clock() {
        public long wall() { return System.currentTimeMillis(); }
        public long monotonic() { return SystemClock.elapsedRealtime(); }
    };
    private final Clock clock;
    private final Map<String, Pending> pending = new HashMap<>();
    private final Set<String> attempts = new HashSet<>();

    static final class Pending {
        final JSONObject receipt;
        final long wallStarted;
        final long monotonicStarted;
        Pending(JSONObject receipt, long wall, long monotonic) {
            this.receipt = receipt; wallStarted = wall; monotonicStarted = monotonic;
        }
    }

    OfflineFallbackGrant(Clock clock) { this.clock = clock; }
    private static void invalid(boolean valid) throws NativeFailure {
        if (!valid) throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
    }
    private static String nonempty(JSONObject row, String key, int bound) throws NativeFailure {
        String value = OfflinePackageValidator.text(row, key, bound);
        invalid(!value.trim().isEmpty() && value.codePoints().noneMatch(Character::isISOControl));
        return value;
    }
    static JSONObject intent(JSONObject row) throws NativeFailure {
        try {
            if ("device-fallback-intent@2".equals(row.optString("schema")))
                return OfflineFallbackValues.validateIntent(row);
            OfflinePackageValidator.keys(row, "schema", "attempt_id", "query_fingerprint", "source_id",
                "source_access_generation", "query", "filters", "failure");
            OfflinePackageValidator.equal(row, "schema", "device-fallback-intent@1");
            OfflinePackageValidator.uuid(row, "attempt_id"); OfflinePackageValidator.hash(row, "query_fingerprint");
            invalid(nonempty(row, "source_id", 80).matches("[a-z0-9-]{1,80}"));
            OfflinePackageValidator.number(row, "source_access_generation", SAFE);
            JSONObject query = OfflinePackageValidator.object(row, "query");
            OfflinePackageValidator.keys(query, "model", "size"); nonempty(query, "model", 200);
            OfflinePackageValidator.nullableText(query, "size", 80);
            if (!query.isNull("size")) nonempty(query, "size", 80);
            JSONArray filters = OfflinePackageValidator.array(row, "filters", 16);
            if (filters.length() != 0) throw new NativeFailure("OFFLINE_FALLBACK_UNSUPPORTED");
            JSONObject failure = OfflinePackageValidator.object(row, "failure");
            OfflinePackageValidator.keys(failure, "scope", "reason", "query_id");
            String scope = nonempty(failure, "scope", 30), reason = nonempty(failure, "reason", 80);
            if (scope.equals("api_transport")) {
                invalid(failure.isNull("query_id") && (reason.equals("api_network_unavailable") || reason.equals("api_timeout")));
            } else {
                invalid(scope.equals("source_response") && (reason.equals("upstream_timeout") || reason.equals("upstream_network_error")));
                OfflinePackageValidator.uuid(failure, "query_id");
            }
            return new JSONObject(row.toString());
        } catch (NativeFailure failure) {
            if (failure.code.startsWith("OFFLINE_FALLBACK_")) throw failure;
            throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
        } catch (Exception ignored) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
    }
    static JSONObject decideRequest(JSONObject request) throws NativeFailure {
        try {
            JSONObject submitted = request.optJSONObject("intent");
            if (submitted != null && "device-fallback-intent@2".equals(submitted.optString("schema"))) {
                OfflineFallbackValues.slotRequest(request, true);
                return intent(submitted);
            }
            OfflinePackageValidator.keys(request, "intent", "slot_id", "expected_generation", "expected_sha256",
                "expected_profile_id", "expected_owner_epoch", "decision");
            JSONObject intent = intent(OfflinePackageValidator.object(request, "intent"));
            OfflinePackageValidator.uuid(request, "slot_id"); OfflinePackageValidator.hash(request, "expected_sha256");
            invalid(OfflinePackageValidator.number(request, "expected_generation", SAFE) >= 1);
            OfflinePackageValidator.number(request, "expected_owner_epoch", SAFE);
            nonempty(request, "expected_profile_id", 80);
            String decision = nonempty(request, "decision", 10);
            invalid(decision.equals("allow") || decision.equals("deny"));
            return intent;
        } catch (NativeFailure failure) {
            if (failure.code.startsWith("OFFLINE_FALLBACK_")) throw failure;
            throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
        } catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
    }
    static String requestId(JSONObject row, boolean consuming) throws NativeFailure {
        try {
            OfflinePackageValidator.keys(row, consuming ? new String[]{"grant_id", "intent"} : new String[]{"grant_id"});
            if (consuming) intent(OfflinePackageValidator.object(row, "intent"));
            return OfflinePackageValidator.uuid(row, "grant_id");
        } catch (NativeFailure failure) {
            if (failure.code.startsWith("OFFLINE_FALLBACK_")) throw failure;
            throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
        }
    }

    // Order-independent, field-complete comparison after strict nested validation.
    static boolean sameIntent(JSONObject a, JSONObject b) throws Exception {
        if ("device-fallback-intent@2".equals(a.optString("schema")) || "device-fallback-intent@2".equals(b.optString("schema")))
            return OfflineFallbackValues.same(a, b);
        for (String key : new String[]{"schema", "attempt_id", "query_fingerprint", "source_id"}) {
            if (!a.get(key).equals(b.get(key))) return false;
        }
        if (a.getLong("source_access_generation") != b.getLong("source_access_generation")) return false;
        JSONObject qa = a.getJSONObject("query"), qb = b.getJSONObject("query");
        JSONObject fa = a.getJSONObject("failure"), fb = b.getJSONObject("failure");
        return qa.get("model").equals(qb.get("model")) && qa.get("size").equals(qb.get("size")) &&
            fa.get("scope").equals(fb.get("scope")) && fa.get("reason").equals(fb.get("reason")) &&
            fa.get("query_id").equals(fb.get("query_id"));
    }

    void checkCapacity(JSONObject intent, boolean allow) throws Exception {
        String attempt = intent.getString("attempt_id");
        if (attempts.contains(attempt)) throw new NativeFailure("OFFLINE_FALLBACK_USED");
        pending.entrySet().removeIf(item -> expired(item.getValue()));
        if (attempts.size() >= 1024 || (allow && pending.size() >= 16)) throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
    }
    void burnAttempt(JSONObject intent) throws Exception {
        checkCapacity(intent, false); attempts.add(intent.getString("attempt_id"));
    }
    void invalidatePolicy(String policyId) {
        pending.entrySet().removeIf(entry -> {
            JSONObject authorization = entry.getValue().receipt.optJSONObject("fallback_authorization");
            return authorization != null && "policy_once".equals(authorization.optString("type"))
                && policyId.equals(authorization.optString("policy_id"));
        });
    }
    void invalidateV2() { pending.entrySet().removeIf(entry -> "device-fallback-grant@2".equals(entry.getValue().receipt.optString("schema"))); }
    void invalidateLegacySources(Set<String> sources) {
        pending.entrySet().removeIf(entry -> "device-fallback-grant@1".equals(entry.getValue().receipt.optString("schema"))
            && sources.contains(entry.getValue().receipt.optJSONObject("intent").optString("source_id")));
    }
    Pending receipt(JSONObject intent, JSONObject request, String profile, long epoch) throws Exception {
        long monotonic = clock.monotonic(), wall = clock.wall();
        JSONObject receipt = new JSONObject();
        receipt.put("schema", "device-fallback-grant@1"); receipt.put("id", UUID.randomUUID().toString());
        receipt.put("scope", "local_once"); receipt.put("state", request.getString("decision").equals("allow") ? "allowed" : "denied");
        receipt.put("intent", new JSONObject(intent.toString())); receipt.put("profile_id", profile); receipt.put("owner_epoch", epoch);
        receipt.put("slot_id", request.getString("slot_id")); receipt.put("generation", request.getLong("expected_generation"));
        receipt.put("package_sha256", request.getString("expected_sha256")); receipt.put("decided_at", Instant.ofEpochMilli(wall).toString());
        receipt.put("expires_at", Instant.ofEpochMilli(wall + TTL_MILLIS).toString()); receipt.put("consumed_at", JSONObject.NULL);
        return new Pending(receipt, wall, monotonic);
    }
    Pending receiptV2(JSONObject intent, JSONObject request, String profile, long epoch,
        JSONObject authorization, boolean allow) throws Exception {
        long wall = clock.wall(), mono = clock.monotonic();
        JSONObject receipt = new JSONObject().put("schema", "device-fallback-grant@2")
            .put("id", UUID.randomUUID().toString()).put("scope", "local_once").put("state", allow ? "allowed" : "denied")
            .put("fallback_authorization", copy(authorization)).put("intent", copy(intent)).put("profile_id", profile)
            .put("owner_epoch", epoch).put("slot_id", request.getString("slot_id"))
            .put("generation", request.getLong("expected_generation")).put("package_sha256", request.getString("expected_sha256"))
            .put("decided_at", Instant.ofEpochMilli(wall).toString()).put("expires_at", Instant.ofEpochMilli(wall + TTL_MILLIS).toString())
            .put("consumed_at", JSONObject.NULL);
        return new Pending(receipt, wall, mono);
    }
    static JSONObject copy(JSONObject value) throws Exception {
        return (JSONObject) OfflineTireCriteria.parse(OfflineJsonInteger.stringify(value), OfflineFallbackWire.MAX_CORE_BYTES, 1000000);
    }
    void register(Pending prepared) throws Exception {
        JSONObject receipt = prepared.receipt;
        attempts.add(receipt.getJSONObject("intent").getString("attempt_id"));
        if (receipt.getString("state").equals("allowed")) {
            // Retain both actual decision clocks across persistence; no wall-based reconstruction.
            pending.put(receipt.getString("id"), new Pending(copy(receipt),
                prepared.wallStarted, prepared.monotonicStarted));
        }
    }
    private boolean expired(Pending grant) {
        long wall = clock.wall(), mono = clock.monotonic();
        return wall < grant.wallStarted || mono < grant.monotonicStarted ||
            wall - grant.wallStarted >= TTL_MILLIS || mono - grant.monotonicStarted >= TTL_MILLIS;
    }
    void checkExpiry(Pending grant) throws NativeFailure {
        if (expired(grant)) throw new NativeFailure("OFFLINE_FALLBACK_EXPIRED");
    }
    Pending take(String id, JSONObject intent) throws Exception {
        // Removing is deliberately before any fallible checks, audit or payload access.
        Pending grant = pending.remove(id);
        if (grant == null) throw new NativeFailure("OFFLINE_FALLBACK_USED");
        checkExpiry(grant);
        if (!sameIntent(grant.receipt.getJSONObject("intent"), intent)) throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
        return grant;
    }
    Pending revoke(String id) { return pending.remove(id); }
    JSONObject consumed(Pending pending) throws Exception {
        JSONObject receipt = copy(pending.receipt);
        receipt.put("state", "consumed"); receipt.put("consumed_at", Instant.ofEpochMilli(clock.wall()).toString());
        return receipt;
    }
    static JSONArray matching(JSONObject envelope, JSONObject intent) throws Exception {
        JSONObject query = intent.getJSONObject("query"); JSONArray all = envelope.getJSONArray("members"), result = new JSONArray();
        for (int index = 0; index < all.length(); index++) {
            JSONObject member = all.getJSONObject(index), reference = member.getJSONObject("reference");
            if (!reference.getString("kind").equals("tire")) continue;
            JSONObject source = member.getJSONObject("source"), variant = member.getJSONObject("payload").getJSONObject("variant");
            if (!intent.getString("source_id").equals(source.opt("source_id")) || !query.getString("model").equals(variant.opt("model"))) continue;
            if (!query.isNull("size") && !query.getString("size").equals(variant.opt("size"))) continue;
            result.put(member);
        }
        return result;
    }
    void clear() { pending.clear(); /* attempts stay terminal for this host lifetime. */ }
}
