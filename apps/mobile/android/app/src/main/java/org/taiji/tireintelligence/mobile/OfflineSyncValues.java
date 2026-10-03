package org.taiji.tireintelligence.mobile;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.List;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

/** Policy/journal values only. Original producer bytes are never re-encoded for their SHA. */
final class OfflineSyncValues {
    static final long MAX_REVISION = 9007199254740990L;
    static final String PROCESS = UUID.randomUUID().toString();
    static final String VALIDATOR = "offline-validator@2";
    static JSONObject json(Object... pairs) throws Exception {
        JSONObject value = new JSONObject();
        for (int i = 0; i < pairs.length; i += 2) value.put((String) pairs[i], pairs[i+1] == null ? JSONObject.NULL : pairs[i+1]);
        return value;
    }
    static JSONObject copy(JSONObject value) throws Exception {
        Object result = OfflineTireCriteria.parse(OfflineJsonInteger.stringify(value), NativePolicy.MAX_RESPONSE_BYTES, 1000000);
        OfflinePackageValidator.require(result instanceof JSONObject); return (JSONObject) result;
    }
    static int version(JSONObject value, String prefix) throws NativeFailure {
        String schema = OfflinePackageValidator.text(value, "schema", 64);
        if (schema.equals(prefix + "1")) return 1;
        if (schema.equals(prefix + "2")) return 2;
        throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
    }
    static String packSchema(JSONObject descriptor) throws NativeFailure {
        return "offline-pack@" + version(descriptor, "offline-pack-descriptor@");
    }
    static String now() { return Instant.now().toString(); }
    static String due(long seconds) { return Instant.now().plusSeconds(seconds).toString(); }
    static long increment(long value) throws NativeFailure {
        if (value >= MAX_REVISION) throw new NativeFailure("OFFLINE_GENERATION_EXHAUSTED");
        return value + 1;
    }
    static void time(JSONObject value, String name, boolean nullable) throws Exception {
        String text = nullable ? OfflinePackageValidator.nullableText(value, name, 80) : OfflinePackageValidator.text(value, name, 80);
        if (text != null) Instant.parse(text);
    }
    static JSONObject capacity() throws Exception {
        return json("version", "offline-policy@1", "max_package_bytes", 8*1024*1024, "max_distinct_evidence", 200,
            "max_garage_profiles", 50, "max_watch_items", 100, "max_recent_query_candidates", 20,
            "max_searchable_documents", 4000, "plan_ttl_seconds", 600, "raw_policy", "exclude");
    }
    static JSONObject capabilities() throws Exception {
        return json("schema", "device-sync-capabilities@1", "scheduler", BuildConfig.DEBUG ? "os_background" : "unsupported",
            "wifi", true, "external_power", true, "battery_charging", true, "min_interval_seconds", 900,
            "max_interval_seconds", 604800, "host_build", BuildConfig.OFFLINE_HOST_BUILD, "validator_version", VALIDATOR);
    }
    static void previewRequest(JSONObject value) throws Exception {
        OfflinePackageValidator.keys(value, "slot_id", "expected_generation", "expected_profile_id", "expected_owner_epoch", "interval_seconds", "conditions");
        OfflinePackageValidator.uuid(value, "slot_id"); OfflinePackageValidator.number(value, "expected_generation", MAX_REVISION);
        OfflinePackageValidator.hash(value, "expected_profile_id"); OfflinePackageValidator.number(value, "expected_owner_epoch", MAX_REVISION);
        long seconds = OfflinePackageValidator.number(value, "interval_seconds", 604800);
        if (seconds < 900) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        OfflineSyncConditions.validate(OfflinePackageValidator.object(value, "conditions"));
    }
    static void policyRequest(JSONObject value, boolean trigger) throws Exception {
        if (trigger) OfflinePackageValidator.keys(value, "policy_id", "expected_policy_revision", "trigger");
        else OfflinePackageValidator.keys(value, "policy_id", "expected_policy_revision");
        OfflinePackageValidator.uuid(value, "policy_id"); OfflinePackageValidator.number(value, "expected_policy_revision", MAX_REVISION);
        if (trigger && !List.of("manual", "timer", "resume", "online", "os_job").contains(OfflinePackageValidator.text(value, "trigger", 20))) {
            throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        }
    }
    static JSONObject emptyState() throws Exception {
        return json("schema", "device-sync-sidecar@1", "policies", new JSONArray(), "runs", new JSONArray(), "active", null);
    }
    static void state(JSONObject state) throws Exception {
        OfflinePackageValidator.keys(state, "schema", "policies", "runs", "active");
        OfflinePackageValidator.equal(state, "schema", "device-sync-sidecar@1");
        JSONArray policies = OfflinePackageValidator.array(state, "policies", 16), runs = OfflinePackageValidator.array(state, "runs", 64);
        java.util.Set<String> policyIds = new java.util.HashSet<>(), slotIds = new java.util.HashSet<>(), runIds = new java.util.HashSet<>();
        for (int i = 0; i < policies.length(); i++) {
            JSONObject entry = policies.getJSONObject(i);
            OfflinePackageValidator.keys(entry, "policy", "session_binding_hash"); OfflinePackageValidator.hash(entry, "session_binding_hash");
            JSONObject policy = entry.getJSONObject("policy");
            OfflinePackageValidator.keys(policy, "schema", "policy_id", "policy_revision", "state", "profile_id", "owner_epoch", "owner_scope_id", "slot_id",
                "scope", "capacity", "interval_seconds", "conditions", "approved_at", "updated_at", "binding", "next_due_at", "reason");
            OfflinePackageValidator.equal(policy, "schema", "device-sync-policy@1");
            OfflinePackageValidator.require(policyIds.add(OfflinePackageValidator.uuid(policy, "policy_id")) && slotIds.add(OfflinePackageValidator.uuid(policy, "slot_id")));
            OfflinePackageValidator.require(OfflinePackageValidator.number(policy, "policy_revision", MAX_REVISION) >= 1);
            OfflinePackageValidator.hash(policy, "profile_id"); OfflinePackageValidator.hash(policy, "owner_scope_id");
            OfflinePackageValidator.number(policy, "owner_epoch", MAX_REVISION);
            OfflinePackageValidator.require(List.of("enabled", "paused", "revoked").contains(policy.getString("state")));
            // The @1 policy wire stays unchanged. The authenticated installed
            // descriptor pins the actual version again before each run/commit.
            OfflinePackageValidator.scope(policy.getJSONObject("scope"), true);
            OfflinePackageValidator.require(equal(policy.getJSONObject("capacity"), capacity()));
            long seconds = OfflinePackageValidator.number(policy, "interval_seconds", 604800); OfflinePackageValidator.require(seconds >= 900);
            OfflineSyncConditions.validate(policy.getJSONObject("conditions"));
            time(policy, "approved_at", false); time(policy, "updated_at", false); time(policy, "next_due_at", true);
            OfflinePackageValidator.nullableText(policy, "reason", 100);
            JSONObject binding = policy.getJSONObject("binding"); OfflinePackageValidator.keys(binding, "binding_revision", "generation", "package_id", "sha256");
            OfflinePackageValidator.require(OfflinePackageValidator.number(binding, "binding_revision", MAX_REVISION) >= 1);
            OfflinePackageValidator.number(binding, "generation", MAX_REVISION); OfflinePackageValidator.uuid(binding, "package_id"); OfflinePackageValidator.hash(binding, "sha256");
        }
        for (int i = 0; i < runs.length(); i++) {
            JSONObject entry = runs.getJSONObject(i);
            OfflinePackageValidator.keys(entry, "run", "process_id", "confirmation_key", "plan_fingerprint", "expires_at", "monotonic_deadline");
            OfflinePackageValidator.uuid(entry, "process_id"); time(entry, "expires_at", false);
            OfflinePackageValidator.number(entry, "monotonic_deadline", Long.MAX_VALUE);
            if (!entry.isNull("confirmation_key")) OfflinePackageValidator.uuid(entry, "confirmation_key");
            if (!entry.isNull("plan_fingerprint")) OfflinePackageValidator.hash(entry, "plan_fingerprint");
            JSONObject run = entry.getJSONObject("run");
            OfflinePackageValidator.keys(run, "schema", "run_id", "policy_id", "policy_revision", "trigger", "state", "stage", "reason", "started_at", "finished_at", "before_generation", "after_generation", "plan_id", "package_id");
            OfflinePackageValidator.equal(run, "schema", "device-sync-run@1");
            OfflinePackageValidator.require(runIds.add(OfflinePackageValidator.uuid(run, "run_id")));
            OfflinePackageValidator.uuid(run, "policy_id"); OfflinePackageValidator.number(run, "policy_revision", MAX_REVISION);
            OfflinePackageValidator.require(List.of("manual", "timer", "resume", "online", "os_job").contains(run.getString("trigger")));
            OfflinePackageValidator.require(List.of("running", "succeeded", "no_change", "deferred", "blocked", "failed", "cancelled", "interrupted").contains(run.getString("state")));
            OfflinePackageValidator.require(List.of("checking", "preparing", "confirming", "downloading", "committing", "finished").contains(run.getString("stage")));
            OfflinePackageValidator.nullableText(run, "reason", 100); time(run, "started_at", false); time(run, "finished_at", true);
            OfflinePackageValidator.number(run, "before_generation", MAX_REVISION); if (!run.isNull("after_generation")) OfflinePackageValidator.number(run, "after_generation", MAX_REVISION);
            if (!run.isNull("plan_id")) OfflinePackageValidator.uuid(run, "plan_id"); if (!run.isNull("package_id")) OfflinePackageValidator.uuid(run, "package_id");
        }
        OfflinePackageValidator.require(state.has("active"));
        if (!state.isNull("active")) OfflinePackageValidator.require(runIds.contains(OfflinePackageValidator.uuid(state, "active")));
    }
    static JSONObject entry(JSONArray entries, String object, String field, String id) throws Exception {
        for (int i = 0; i < entries.length(); i++) {
            JSONObject value = entries.getJSONObject(i); if (id.equals(value.getJSONObject(object).optString(field))) return value;
        }
        return null;
    }
    static void finish(JSONObject state, JSONObject entry, String status, String reason) throws Exception {
        JSONObject run = entry.getJSONObject("run"); run.put("state", status); run.put("stage", "finished"); run.put("reason", reason == null ? JSONObject.NULL : reason);
        run.put("finished_at", now()); if (run.getString("run_id").equals(state.optString("active"))) state.put("active", JSONObject.NULL);
    }
    static void cancel(JSONObject state, String policyId, String reason) throws Exception {
        if (state.isNull("active")) return;
        JSONObject entry = entry(state.getJSONArray("runs"), "run", "run_id", state.getString("active"));
        if (entry == null) throw new NativeFailure("OFFLINE_SYNC_STATE_INVALID");
        if (policyId == null || policyId.equals(entry.getJSONObject("run").getString("policy_id"))) finish(state, entry, "cancelled", reason);
    }
    static JSONObject scope(JSONObject envelope) throws Exception {
        boolean versionTwo = version(envelope, "offline-pack@") == 2;
        JSONObject scope = copy(envelope.getJSONObject("scope")); JSONArray fixed = new JSONArray();
        OfflinePackageValidator.scope(scope, versionTwo);
        java.util.Set<String> seen = new java.util.HashSet<>(); JSONArray members = envelope.getJSONArray("members");
        JSONArray requested=scope.getJSONArray("references");
        for(int r=0;r<requested.length();r++) {
            JSONObject requestedRef=requested.getJSONObject(r);boolean resolved=false;
            for (int i = 0; i < members.length(); i++) {
                JSONObject member = members.getJSONObject(i); JSONArray reasons = member.getJSONArray("member_reasons");boolean explicit = false;
                for (int n = 0; n < reasons.length(); n++) if ("explicit".equals(reasons.getJSONObject(n).optString("selector"))) explicit = true;
                JSONObject reference=member.getJSONObject("reference");boolean matches=explicit;Iterator<String> keys=requestedRef.keys();
                while(keys.hasNext()) {String key=keys.next();if(!equal(requestedRef.get(key),reference.opt(key)))matches=false;}
                if(matches) {resolved=true;if(seen.add(canonical(reference)))fixed.put(copy(reference));}
            }
            if(!resolved)throw new NativeFailure("OFFLINE_SYNC_SCOPE_UNRESOLVED");
        }
        // No unresolved explicit selector can silently become another receipt later.
        JSONArray omissions = envelope.getJSONArray("omissions");
        for (int i = 0; i < omissions.length(); i++) if ("explicit".equals(omissions.getJSONObject(i).optString("selector"))) throw new NativeFailure("OFFLINE_SYNC_SCOPE_UNRESOLVED");
        if (requested.length() > 0 && fixed.length() == 0) throw new NativeFailure("OFFLINE_SYNC_SCOPE_UNRESOLVED");
        scope.put("references", fixed); OfflinePackageValidator.scope(scope, versionTwo); return scope;
    }
    static boolean equal(Object left, Object right) throws Exception { return canonical(left).equals(canonical(right)); }
    static String canonical(Object value) throws Exception {
        if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value; List<String> keys = new ArrayList<>(); Iterator<String> names = object.keys(); while (names.hasNext()) keys.add(names.next()); Collections.sort(keys);
            StringBuilder result = new StringBuilder("{");
            for (String key : keys) { if (result.length() > 1) result.append(','); result.append(JSONObject.quote(key)).append(':').append(canonical(object.get(key))); }
            return result.append('}').toString();
        }
        if (value instanceof JSONArray) { JSONArray array = (JSONArray) value; StringBuilder result = new StringBuilder("["); for (int i=0;i<array.length();i++) { if(i>0) result.append(','); result.append(canonical(array.get(i))); } return result.append(']').toString(); }
        if (value == null || value == JSONObject.NULL) return "null";
        if (value instanceof String) return JSONObject.quote((String) value);
        return value.toString();
    }
    static String fingerprint(JSONObject value) throws Exception { return OfflineCipher.sha256(canonical(value).getBytes(StandardCharsets.UTF_8)); }
}
