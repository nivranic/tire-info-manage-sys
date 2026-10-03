package org.taiji.tireintelligence.mobile;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Bounded policy metadata. The Store owns encryption, transactions, slot CAS and HTTP authority. */
final class OfflineFallbackJournal {
    static final int MAX_ACTIVE = 16, MAX_RECORDS = 64, MAX_BYTES = 2 * 1024 * 1024;
    private OfflineFallbackJournal() {}
    static JSONObject json(Object... pairs) throws Exception {
        JSONObject value = new JSONObject();
        for (int at = 0; at < pairs.length; at += 2) value.put((String) pairs[at], pairs[at + 1] == null ? JSONObject.NULL : pairs[at + 1]);
        return value;
    }
    static JSONObject copy(JSONObject value) throws Exception {
        return (JSONObject) OfflineTireCriteria.parse(OfflineJsonInteger.stringify(value), MAX_BYTES, 250000);
    }
    static long next(long revision) throws NativeFailure {
        if (revision < 0 || revision >= OfflineFallbackGrant.SAFE) throw new NativeFailure("OFFLINE_FALLBACK_REVISION_EXHAUSTED");
        return revision + 1;
    }
    static long time(String value) throws Exception { return OffsetDateTime.parse(value).toInstant().toEpochMilli(); }
    static String stamp(long wall) { return Instant.ofEpochMilli(wall).toString(); }
    static JSONObject empty(String profile, long epoch, long wall) throws Exception {
        return json("schema", "device-fallback-journal@1", "profile_id", profile, "owner_epoch", epoch,
            "revision", 0, "policies", new JSONArray(), "bindings", new JSONArray(), "last_authority", null, "last_wall", wall);
    }
    static JSONObject entry(JSONObject state, String policyId) throws Exception {
        JSONArray rows = state.getJSONArray("policies");
        for (int at = 0; at < rows.length(); at++) {
            JSONObject entry = rows.getJSONObject(at);
            if (policyId.equals(entry.getJSONObject("policy").getString("policy_id"))) return entry;
        }
        return null;
    }
    static JSONObject bindingEntry(JSONObject state, String slotId) throws Exception {
        JSONArray rows = state.getJSONArray("bindings");
        for (int at = 0; at < rows.length(); at++) if (slotId.equals(rows.getJSONObject(at).getJSONObject("binding").getString("slot_id"))) return rows.getJSONObject(at);
        return null;
    }
    static Set<String> sourceIds(JSONObject scope) throws Exception {
        Set<String> ids = new HashSet<>();
        if (scope.getString("kind").equals("source")) ids.add(scope.getString("source_id"));
        else {
            JSONArray sources = scope.getJSONArray("sources");
            for (int at = 0; at < sources.length(); at++) ids.add(sources.getJSONObject(at).getString("source_id"));
        }
        return ids;
    }
    private static JSONObject source(JSONObject authority, String id) throws Exception {
        JSONArray sources = authority.getJSONArray("sources");
        for (int at = 0; at < sources.length(); at++) if (id.equals(sources.getJSONObject(at).getString("source_id"))) return sources.getJSONObject(at);
        return null;
    }
    static JSONObject approval(JSONObject policy, JSONObject authority) throws Exception {
        JSONObject snapshot = copy(authority); JSONArray sources = new JSONArray();
        List<String> ids = new ArrayList<>(sourceIds(policy.getJSONObject("scope"))); java.util.Collections.sort(ids);
        for (String id : ids) {
            JSONObject row = source(authority, id);
            if (row == null) throw new NativeFailure("OFFLINE_FALLBACK_SOURCE_CHANGED");
            sources.put(copy(row));
        }
        snapshot.put("sources", sources);
        return json("policy", copy(policy), "approval_authority", snapshot);
    }
    static boolean change(JSONObject policy, String state, String reason, long wall) throws Exception {
        if (state.equals(policy.getString("state")) && reason.equals(policy.optString("reason"))) return false;
        policy.put("state", state).put("reason", reason).put("updated_at", stamp(wall))
            .put("policy_revision", next(policy.getLong("policy_revision")));
        return true;
    }
    static void compact(JSONObject state) throws Exception {
        JSONArray all = state.getJSONArray("policies"); List<JSONObject> revoked = new ArrayList<>(), retained = new ArrayList<>();
        for (int at = 0; at < all.length(); at++) {
            JSONObject entry = all.getJSONObject(at);
            if (entry.getJSONObject("policy").getString("state").equals("revoked")) revoked.add(entry); else retained.add(entry);
        }
        if (retained.size() > MAX_ACTIVE) throw new NativeFailure("OFFLINE_FALLBACK_POLICY_CAPACITY");
        revoked.sort((a, b) -> {
            try {
                JSONObject first = a.getJSONObject("policy"), second = b.getJSONObject("policy");
                int order = Long.compare(time(first.getString("updated_at")), time(second.getString("updated_at")));
                return order == 0 ? first.getString("policy_id").compareTo(second.getString("policy_id")) : order;
            } catch (Exception failure) { throw new IllegalArgumentException("Invalid policy time"); }
        });
        int skip = Math.max(0, retained.size() + revoked.size() - MAX_RECORDS);
        retained.addAll(revoked.subList(skip, revoked.size()));
        retained.sort(Comparator.comparing(value -> value.optJSONObject("policy").optString("policy_id")));
        JSONArray values = new JSONArray(); for (JSONObject value : retained) values.put(value); state.put("policies", values);
    }
    static boolean reconcile(JSONObject state, JSONObject authority, long wall) throws Exception {
        String profile = authority.getString("profile_id"), runtime = authority.getString("runtime_session_id");
        long epoch = authority.getLong("owner_epoch"); boolean changed = false;
        JSONArray policies = state.getJSONArray("policies");
        for (int at = 0; at < policies.length(); at++) {
            JSONObject entry = policies.getJSONObject(at), policy = entry.getJSONObject("policy");
            if (policy.getString("state").equals("revoked")) continue;
            String reason = null, target = "paused";
            if (!profile.equals(policy.getString("profile_id")) || epoch != policy.getLong("owner_epoch")) {
                reason = "OFFLINE_FALLBACK_OWNER_CHANGED"; target = "revoked";
            } else if (policy.getJSONObject("scope").getString("kind").equals("session")
                && !runtime.equals(policy.opt("runtime_session_id"))) reason = "OFFLINE_FALLBACK_SESSION_CHANGED";
            else if (wall < state.getLong("last_wall") || wall < time(policy.getString("approved_at")) || wall < time(policy.getString("updated_at"))) reason = "OFFLINE_FALLBACK_CLOCK_ROLLBACK";
            else if (wall >= time(policy.getString("expires_at"))) reason = "OFFLINE_FALLBACK_POLICY_EXPIRED";
            else if (!policy.isNull("binding")) {
                JSONObject saved = bindingEntry(state, policy.getJSONObject("binding").getString("slot_id"));
                if (saved == null || saved.getLong("owner_epoch") != epoch || !OfflineFallbackValues.same(saved.getJSONObject("binding"), policy.getJSONObject("binding")))
                    reason = "OFFLINE_FALLBACK_PACKAGE_CHANGED";
            }
            if (reason == null && authority.getString("state").equals("last_observed")) {
                JSONObject approved = entry.getJSONObject("approval_authority");
                if (!authority.getString("owner_scope_id").equals(policy.getString("owner_scope_id"))) reason = "OFFLINE_FALLBACK_OWNER_CHANGED";
                for (String id : sourceIds(policy.getJSONObject("scope"))) {
                    JSONObject original = source(approved, id), current = source(authority, id);
                    if (current == null || original == null || !OfflineFallbackValues.same(original, current)) reason = "OFFLINE_FALLBACK_SOURCE_CHANGED";
                }
            }
            // Paused records are not auto-resumed or rewritten on every metadata status read.
            if (reason != null && (policy.getString("state").equals("enabled") || target.equals("revoked"))) changed |= change(policy, target, reason, wall);
        }
        if (state.getLong("owner_epoch") != epoch) { state.put("owner_epoch", epoch); changed = true; }
        state.put("last_wall", Math.max(wall, state.getLong("last_wall")));
        if (changed) state.put("revision", next(state.getLong("revision")));
        compact(state); return changed;
    }
    static boolean observe(JSONObject state, JSONObject authority, String networkBinding, boolean knownSessionChanged, long wall) throws Exception {
        JSONObject prior = state.isNull("last_authority") ? null : state.getJSONObject("last_authority");
        boolean sessionChanged = knownSessionChanged || (prior != null && !networkBinding.equals(prior.getString("network_binding")));
        boolean changed = false;
        if (sessionChanged) {
            JSONArray policies = state.getJSONArray("policies");
            for (int at = 0; at < policies.length(); at++) {
                JSONObject policy = policies.getJSONObject(at).getJSONObject("policy");
                if (policy.getString("state").equals("enabled")) changed |= change(policy, "paused", "OFFLINE_FALLBACK_SESSION_CHANGED", wall);
            }
        }
        changed |= reconcile(state, authority, wall);
        state.put("last_authority", json("network_binding", networkBinding, "authority", copy(authority)));
        if (sessionChanged) state.put("revision", next(state.getLong("revision")));
        return changed;
    }
    static void putPolicy(JSONObject state, JSONObject policy, JSONObject authority) throws Exception {
        JSONObject existing = entry(state, policy.getString("policy_id"));
        JSONArray all = state.getJSONArray("policies");
        if (existing == null) all.put(approval(policy, authority));
        else {
            existing.put("policy", copy(policy)).put("approval_authority", approval(policy, authority).getJSONObject("approval_authority"));
        }
        compact(state); state.put("revision", next(state.getLong("revision")));
    }
    static void removeBinding(JSONObject state, String slotId, long wall) throws Exception {
        JSONArray old = state.getJSONArray("bindings"), next = new JSONArray();
        for (int at = 0; at < old.length(); at++) if (!slotId.equals(old.getJSONObject(at).getJSONObject("binding").getString("slot_id"))) next.put(old.getJSONObject(at));
        state.put("bindings", next);
        JSONArray policies = state.getJSONArray("policies");
        for (int at = 0; at < policies.length(); at++) {
            JSONObject policy = policies.getJSONObject(at).getJSONObject("policy");
            if (policy.getString("state").equals("enabled") && !policy.isNull("binding") && slotId.equals(policy.getJSONObject("binding").getString("slot_id")))
                change(policy, "paused", "OFFLINE_FALLBACK_PACKAGE_CHANGED", wall);
        }
        state.put("revision", next(state.getLong("revision")));
    }
    static JSONObject putBinding(JSONObject state, JSONObject slot, long epoch, JSONObject material, boolean approvedSync, long wall) throws Exception {
        String slotId = slot.getString("slot_id"); JSONObject old = bindingEntry(state, slotId);
        long revision = old == null ? 0 : old.getJSONObject("binding").getLong("binding_revision");
        Set<String> ids = new HashSet<>(); JSONArray members = material.getJSONArray("members");
        for (int at = 0; at < members.length(); at++) {
            JSONObject source = members.getJSONObject(at).getJSONObject("source");
            if (!source.isNull("source_id")) ids.add(source.getString("source_id"));
        }
        List<String> ordered = new ArrayList<>(ids); java.util.Collections.sort(ordered); JSONArray sources = new JSONArray();
        for (String id : ordered) sources.put(id);
        JSONObject binding = json("binding_revision", next(revision), "slot_id", slotId, "generation", slot.getLong("generation"),
            "package_id", slot.getString("package_id"), "sha256", slot.getString("sha256"),
            "history_scope_fingerprint", OfflineFallbackValues.scopeFingerprint(material.getJSONObject("scope")), "source_ids", sources);
        if (old != null && old.getLong("owner_epoch") == epoch) {
            JSONObject previous = old.getJSONObject("binding");
            // An authorized read backfill of an already saved binding is a no-op.
            if (previous.getLong("generation") == binding.getLong("generation") && previous.getString("sha256").equals(binding.getString("sha256"))) return copy(previous);
        }
        JSONArray policies = state.getJSONArray("policies");
        for (int at = 0; at < policies.length(); at++) {
            JSONObject policy = policies.getJSONObject(at).getJSONObject("policy");
            if (!policy.getString("state").equals("enabled") || policy.isNull("binding") || !slotId.equals(policy.getJSONObject("binding").getString("slot_id"))) continue;
            boolean advance = approvedSync && old != null && old.getLong("owner_epoch") == epoch
                && policy.getLong("owner_epoch") == epoch && policy.getBoolean("allow_same_scope_sync_binding_advance")
                && OfflineFallbackValues.same(policy.getJSONObject("binding"), old.getJSONObject("binding"))
                && binding.getString("history_scope_fingerprint").equals(policy.getJSONObject("binding").getString("history_scope_fingerprint"))
                && sourceIds(policy.getJSONObject("scope")).containsAll(ids);
            if (advance) policy.put("binding", copy(binding));
            else change(policy, "paused", "OFFLINE_FALLBACK_PACKAGE_CHANGED", wall);
        }
        JSONObject entry = json("owner_epoch", epoch, "binding", binding);
        if (old == null) state.getJSONArray("bindings").put(entry);
        else old.put("owner_epoch", epoch).put("binding", binding);
        if (state.getJSONArray("bindings").length() > 16) throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
        state.put("revision", next(state.getLong("revision"))); return copy(binding);
    }
    static JSONObject validate(JSONObject state, String profile) throws Exception {
        OfflinePackageValidator.keys(state, "schema", "profile_id", "owner_epoch", "revision", "policies", "bindings", "last_authority", "last_wall");
        OfflinePackageValidator.equal(state, "schema", "device-fallback-journal@1");
        if (!profile.equals(state.getString("profile_id"))) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID");
        OfflinePackageValidator.number(state, "owner_epoch", OfflineFallbackGrant.SAFE); OfflinePackageValidator.number(state, "revision", OfflineFallbackGrant.SAFE);
        OfflinePackageValidator.number(state, "last_wall", Long.MAX_VALUE);
        JSONArray policies = OfflinePackageValidator.array(state, "policies", MAX_RECORDS), bindings = OfflinePackageValidator.array(state, "bindings", 16);
        Set<String> policyIds = new HashSet<>(), slotIds = new HashSet<>();
        for (int at = 0; at < policies.length(); at++) {
            JSONObject entry = policies.getJSONObject(at); OfflinePackageValidator.keys(entry, "policy", "approval_authority");
            JSONObject policy = entry.getJSONObject("policy");
            OfflinePackageValidator.keys(policy, "schema", "policy_id", "policy_revision", "state", "profile_id", "owner_epoch", "owner_scope_id",
                "runtime_session_id", "approved_at", "updated_at", "expires_at", "fingerprint", "reason", "mode", "scope", "binding", "allow_same_scope_sync_binding_advance");
            OfflinePackageValidator.equal(policy, "schema", "device-fallback-policy@1"); OfflinePackageValidator.uuid(policy, "policy_id");
            if (!policyIds.add(policy.getString("policy_id")) || !profile.equals(policy.getString("profile_id"))) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID");
            if (OfflinePackageValidator.number(policy, "policy_revision", OfflineFallbackGrant.SAFE) < 1) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID");
            OfflinePackageValidator.number(policy, "owner_epoch", OfflineFallbackGrant.SAFE); OfflinePackageValidator.hash(policy, "owner_scope_id"); OfflinePackageValidator.hash(policy, "fingerprint");
            if (!Set.of("enabled", "paused", "revoked").contains(policy.getString("state"))) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID");
            if (!policy.isNull("runtime_session_id")) OfflinePackageValidator.uuid(policy, "runtime_session_id");
            time(policy.getString("approved_at")); time(policy.getString("updated_at")); time(policy.getString("expires_at"));
            if (!policy.isNull("reason") && !policy.getString("reason").matches("[A-Z_]{1,100}")) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID");
            JSONObject choice = json("mode", policy.get("mode"), "scope", policy.get("scope"), "binding", policy.get("binding"),
                "allow_same_scope_sync_binding_advance", policy.get("allow_same_scope_sync_binding_advance"));
            OfflineFallbackValues.validateChoice(entry.getJSONObject("approval_authority"), choice);
        }
        for (int at = 0; at < bindings.length(); at++) {
            JSONObject entry = bindings.getJSONObject(at); OfflinePackageValidator.keys(entry, "owner_epoch", "binding");
            OfflinePackageValidator.number(entry, "owner_epoch", OfflineFallbackGrant.SAFE); JSONObject binding = entry.getJSONObject("binding");
            OfflinePackageValidator.keys(binding, "binding_revision", "slot_id", "generation", "package_id", "sha256", "history_scope_fingerprint", "source_ids");
            OfflinePackageValidator.uuid(binding, "slot_id"); OfflinePackageValidator.uuid(binding, "package_id");
            if (!slotIds.add(binding.getString("slot_id")) || OfflinePackageValidator.number(binding, "binding_revision", OfflineFallbackGrant.SAFE) < 1
                || OfflinePackageValidator.number(binding, "generation", OfflineFallbackGrant.SAFE) < 1) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID");
            OfflinePackageValidator.hash(binding, "sha256"); OfflinePackageValidator.hash(binding, "history_scope_fingerprint");
            JSONArray ids = OfflinePackageValidator.array(binding, "source_ids", 200); String prior = null;
            for (int index = 0; index < ids.length(); index++) {
                String id = ids.getString(index);
                if (!id.matches("[a-z0-9-]{1,80}") || (prior != null && prior.compareTo(id) >= 0)) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID"); prior = id;
            }
        }
        if (!state.isNull("last_authority")) {
            JSONObject last = state.getJSONObject("last_authority"); OfflinePackageValidator.keys(last, "network_binding", "authority");
            OfflinePackageValidator.hash(last, "network_binding"); OfflinePackageValidator.object(last, "authority");
        }
        compact(state);
        if (OfflineJsonInteger.stringify(state).getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
        return state;
    }
}
