package org.taiji.tireintelligence.mobile;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

/** Current-runtime metadata only. A saved package never supplies source authority. */
final class OfflineFallbackAuthority {
    private final String runtime = UUID.randomUUID().toString();
    private final OfflineFallbackGrant.Clock clock;
    private long revision;
    private JSONObject observed;
    private String sessionBinding;
    static final class Capture {
        final String profile, runtime;
        final long epoch, revision;
        Capture(String profile, String runtime, long epoch, long revision) {
            this.profile = profile; this.runtime = runtime; this.epoch = epoch; this.revision = revision;
        }
    }
    static final class Prepared {
        final JSONObject value;
        final String sessionBinding;
        final boolean changed;
        Prepared(JSONObject value, String sessionBinding, boolean changed) {
            this.value = value; this.sessionBinding = sessionBinding; this.changed = changed;
        }
    }
    OfflineFallbackAuthority(OfflineFallbackGrant.Clock clock) { this.clock = clock; }
    private static JSONObject json(Object... pairs) throws Exception {
        JSONObject value = new JSONObject();
        for (int at = 0; at < pairs.length; at += 2)
            value.put((String) pairs[at], pairs[at + 1] == null ? JSONObject.NULL : pairs[at + 1]);
        return value;
    }
    private static void require(boolean valid) throws NativeFailure {
        if (!valid) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_INVALID");
    }
    private static JSONObject copy(JSONObject value) throws Exception { return new JSONObject(value.toString()); }
    JSONObject snapshot(String profile, long epoch) throws Exception {
        if (observed != null && observed.getString("profile_id").equals(profile) && observed.getLong("owner_epoch") == epoch)
            return copy(observed);
        return json("schema", "device-fallback-source-authority@1", "runtime_session_id", runtime,
            "authority_revision", revision, "state", "unknown", "observed_at", null, "profile_id", profile,
            "owner_epoch", epoch, "owner_scope_id", null, "sources", new JSONArray());
    }
    Capture capture(String profile, long epoch) { return new Capture(profile, runtime, epoch, revision); }
    Prepared prepare(Capture capture, String profile, long epoch, JSONObject settings, JSONObject directory,
                     String owner, String networkBinding) throws Exception {
        return prepare(capture, profile, epoch, settings, directory, owner, networkBinding, false);
    }
    Prepared prepare(Capture capture, String profile, long epoch, JSONObject settings, JSONObject directory,
                     String owner, String networkBinding, boolean knownSessionChanged) throws Exception {
        require(capture != null && capture.profile.equals(profile) && capture.runtime.equals(runtime)
            && capture.epoch == epoch && capture.revision == revision);
        require(owner != null && owner.matches("[0-9a-f]{64}") && networkBinding != null && networkBinding.matches("[0-9a-f]{64}"));
        JSONArray items = OfflinePackageValidator.array(settings, "items", 200);
        JSONArray registered = OfflinePackageValidator.array(directory, "sources", 200);
        Map<String, JSONObject> catalog = new HashMap<>();
        for (int at = 0; at < registered.length(); at++) {
            JSONObject item = registered.getJSONObject(at); String id = OfflinePackageValidator.text(item, "id", 80);
            require(id.matches("[a-z0-9-]{1,80}") && catalog.put(id, item) == null);
        }
        Map<String, JSONObject> rows = new HashMap<>(); Set<String> seen = new HashSet<>();
        for (int at = 0; at < items.length(); at++) {
            JSONObject item = items.getJSONObject(at); String id = OfflinePackageValidator.text(item, "source_id", 80);
            require(id.matches("[a-z0-9-]{1,80}") && seen.add(id));
            String target = OfflinePackageValidator.text(item, "target_kind", 32);
            JSONObject registeredItem = catalog.get(id);
            // The public source catalog deliberately omits OEM vehicle sources.
            if (!target.equals("vehicle") && registeredItem == null) continue;
            if (registeredItem != null && registeredItem.has("target_kind")) require(target.equals(registeredItem.get("target_kind")));
            JSONArray kinds = new JSONArray();
            if (target.equals("tire")) kinds.put("tire");
            else if (target.equals("vehicle")) kinds.put("vehicle_fitments");
            else if (target.equals("recall") && id.equals("nhtsa-us-recalls")) kinds.put("recall_campaign").put("recall_search");
            else continue;
            JSONObject management = OfflinePackageValidator.object(item, "management");
            long generation = OfflinePackageValidator.number(management, "access_generation", OfflineFallbackGrant.SAFE);
            require(item.opt("can_fetch") instanceof Boolean);
            boolean canFetch = item.getBoolean("can_fetch");
            boolean canQuery = canFetch && "enabled".equals(management.opt("state")) && "ready".equals(item.opt("effective_status"));
            rows.put(id, json("source_id", id, "access_generation", generation, "query_kinds", kinds,
                "can_query", canQuery, "can_fetch", canFetch));
        }
        List<String> ids = new ArrayList<>(rows.keySet()); java.util.Collections.sort(ids);
        JSONArray sources = new JSONArray(); for (String id : ids) sources.put(rows.get(id));
        JSONObject current = snapshot(profile, epoch);
        boolean changed = knownSessionChanged || !current.getString("state").equals("last_observed") || !owner.equals(current.opt("owner_scope_id"))
            || !networkBinding.equals(sessionBinding) || !sources.toString().equals(current.getJSONArray("sources").toString());
        require(!changed || revision < OfflineFallbackGrant.SAFE);
        JSONObject next = json("schema", "device-fallback-source-authority@1", "runtime_session_id", runtime,
            "authority_revision", changed ? revision + 1 : revision, "state", "last_observed",
            "observed_at", Instant.ofEpochMilli(clock.wall()).toString(), "profile_id", profile, "owner_epoch", epoch,
            "owner_scope_id", owner, "sources", sources);
        return new Prepared(next, networkBinding, changed);
    }
    void publish(Prepared prepared) throws Exception {
        observed = copy(prepared.value); revision = prepared.value.getLong("authority_revision"); sessionBinding = prepared.sessionBinding;
    }
    void reset() {
        observed = null; sessionBinding = null;
        if (revision < OfflineFallbackGrant.SAFE) revision++;
    }
}
