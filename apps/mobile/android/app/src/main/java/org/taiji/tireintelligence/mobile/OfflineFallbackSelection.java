package org.taiji.tireintelligence.mobile;

import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Historical projections only. Admission, durable consumption and final CAS belong to the store. */
final class OfflineFallbackSelection {
    private OfflineFallbackSelection() {}

    private static JSONObject json(Object... pairs) throws Exception {
        JSONObject value = new JSONObject();
        for (int at = 0; at < pairs.length; at += 2)
            value.put((String) pairs[at], pairs[at + 1] == null ? JSONObject.NULL : pairs[at + 1]);
        return value;
    }

    static JSONObject select(JSONObject material, JSONObject intent) throws Exception {
        String schema = material.getString("schema"), kind = intent.getString("query_kind");
        if (!schema.equals("offline-pack@1") && !schema.equals("offline-pack@2"))
            throw new NativeFailure("OFFLINE_PACKAGE_INVALID");
        if (!Set.of("tire", "vehicle_fitments", "recall_campaign", "recall_search").contains(kind))
            throw new NativeFailure("OFFLINE_FALLBACK_UNSUPPORTED");
        if (kind.equals("recall_search") && !schema.equals("offline-pack@2"))
            throw new NativeFailure("OFFLINE_FALLBACK_UNSUPPORTED");
        JSONObject query = intent.getJSONObject("query");
        JSONArray filters = intent.getJSONArray("filters"), basic = new JSONArray(), selected = new JSONArray();
        if (kind.equals("tire")) {
            Set<String> names = new HashSet<>(); query.keys().forEachRemaining(names::add);
            if (names.isEmpty() || !Set.of("model", "size").containsAll(names))
                throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
            if (query.has("model")) basic.put(json("field", "model", "op", "eq", "value", query.getString("model")));
            basic = OfflineTireCriteria.validateFilters(basic);
            filters = OfflineTireCriteria.validateFilters(filters);
        } else {
            if (filters.length() != 0) throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
            OfflinePackageValidator.keys(query, kind.equals("vehicle_fitments") ? new String[]{"vehicle_id"}
                : kind.equals("recall_campaign") ? new String[]{"campaign_number"} : new String[]{"search", "offset"});
        }
        int sourceCount = 0, excluded = 0, undetermined = 0;
        JSONArray members = material.getJSONArray("members");
        for (int at = 0; at < members.length(); at++) {
            JSONObject member = members.getJSONObject(at), reference = member.getJSONObject("reference");
            if (!intent.getString("source_id").equals(member.getJSONObject("source").opt("source_id"))) continue;
            String referenceKind = reference.getString("kind");
            JSONObject payload = member.getJSONObject("payload");
            if (kind.equals("tire") && referenceKind.equals("tire")) {
                // Each receipt is one observation. Never deduplicate different receipts by variant id.
                sourceCount++;
                JSONObject variant = payload.getJSONObject("variant");
                OfflineTireCriteria.Truth first = OfflineTireCriteria.evaluate(variant, basic);
                OfflineTireCriteria.Truth size = query.has("size") ? OfflineTireCriteria.evaluateBasicSize(variant, query.getString("size")) : OfflineTireCriteria.Truth.TRUE;
                OfflineTireCriteria.Truth second = OfflineTireCriteria.evaluate(variant, filters);
                if (first == OfflineTireCriteria.Truth.FALSE || size == OfflineTireCriteria.Truth.FALSE || second == OfflineTireCriteria.Truth.FALSE) excluded++;
                else if (first == OfflineTireCriteria.Truth.UNKNOWN || size == OfflineTireCriteria.Truth.UNKNOWN || second == OfflineTireCriteria.Truth.UNKNOWN) undetermined++;
                else selected.put(member);
            } else if (kind.equals("vehicle_fitments") && referenceKind.equals("vehicle")
                && query.getString("vehicle_id").equals(payload.getJSONObject("vehicle").getString("id"))) selected.put(member);
            else if (kind.equals("recall_campaign") && referenceKind.equals("recall")
                && query.getString("campaign_number").equals(payload.getJSONObject("evidence").getString("campaign_number"))) selected.put(member);
            else if (kind.equals("recall_search") && referenceKind.equals("recall_search")) {
                JSONObject pageQuery = payload.getJSONObject("query");
                if (query.getString("search").equals(pageQuery.getString("search"))
                    && query.getString("offset").equals(pageQuery.getString("offset"))) selected.put(member);
            }
        }
        JSONObject selection = kind.equals("tire") ? json("filters", intent.getJSONArray("filters"),
            "source_count", sourceCount, "matched_count", selected.length(), "excluded_count", excluded,
            "undetermined_count", undetermined) : null;
        return json("members", selected, "selection", selection);
    }

    static JSONObject result(JSONObject material, JSONObject intent, JSONObject consumed, JSONObject slot) throws Exception {
        JSONObject projected = select(material, intent);
        JSONArray citations = new JSONArray(), selected = projected.getJSONArray("members"), docs = material.getJSONArray("documents");
        for (int at = 0; at < selected.length(); at++) {
            JSONObject member = selected.getJSONObject(at); boolean found = false;
            for (int index = 0; index < docs.length(); index++) {
                JSONObject document = docs.getJSONObject(index);
                if (member.getString("key").equals(document.opt("member_key"))) {
                    citations.put(citation(consumed, member, document)); found = true;
                }
            }
            if (!found) citations.put(citation(consumed, member, null));
        }
        JSONObject result = json("schema", "device-fallback-result@2", "data_state", "local_snapshot",
            "fallback_consent", "local_once", "fallback_authorization", consumed.getJSONObject("fallback_authorization"),
            "grant", consumed, "slot", slot, "package_schema", material.getString("schema"),
            "query_kind", intent.getString("query_kind"), "query", intent.getJSONObject("query"),
            "members", selected, "selection", projected.get("selection"), "citations", citations,
            "complete_query_result", false,
            "notice", "仅为本包历史观察的匹配子集；字段依据可能包含其他来源的历史上下文。不表示完整在线结果、当前参数、实物适用性、安全结论或 AI 授权。空页不表示无召回或无风险。");
        if (OfflineJsonInteger.stringify(result).getBytes(StandardCharsets.UTF_8).length > OfflinePackageValidator.MAX_BYTES)
            throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
        return result;
    }

    private static JSONObject citation(JSONObject grant, JSONObject member, JSONObject document) throws Exception {
        JSONObject source = member.getJSONObject("source");
        Object documentId = document == null ? null : document.get("id");
        Object recordIndex = document == null ? null : document.get("record_index");
        String namespace = "device-citation@1\0" + grant.getString("profile_id") + "\0" + grant.getLong("owner_epoch")
            + "\0" + grant.getString("slot_id") + "\0" + grant.getLong("generation") + "\0"
            + grant.getString("package_sha256") + "\0" + member.getString("key") + "\0" + documentId + "\0" + recordIndex;
        return json("schema", "device-citation@1", "id", "device:" + OfflineCipher.sha256(namespace.getBytes(StandardCharsets.UTF_8)),
            "profile_id", grant.getString("profile_id"), "owner_epoch", grant.getLong("owner_epoch"),
            "slot_id", grant.getString("slot_id"), "generation", grant.getLong("generation"),
            "package_sha256", grant.getString("package_sha256"), "member_key", member.getString("key"),
            "document_id", documentId, "record_index", recordIndex,
            "observed_at", document == null ? source.get("observed_at") : document.get("observed_at"),
            "verified_at", document == null ? source.get("verified_at") : document.get("verified_at"),
            "verification_id", source.get("verification_id"));
    }
}
