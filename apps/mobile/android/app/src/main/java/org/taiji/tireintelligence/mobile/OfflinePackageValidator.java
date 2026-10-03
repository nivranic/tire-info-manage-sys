package org.taiji.tireintelligence.mobile;

import android.util.JsonReader;
import android.util.JsonToken;
import java.io.StringReader;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.net.URI;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Validates frozen data only. No URL, embedded instructions or SQL is executed. */
final class OfflinePackageValidator {
    static final int MAX_BYTES = 8 * 1024 * 1024;
    private static final Set<String> KINDS = new HashSet<>(Arrays.asList("tire", "vehicle", "test_event", "recall"));
    private static final Set<String> PRIVATE = new HashSet<>(Arrays.asList("private", "restricted"));
    private static final Set<String> PRIVACY = new HashSet<>(Arrays.asList("public", "private", "restricted"));
    private static final Set<String> FORBIDDEN = new HashSet<>(Arrays.asList(
        "actor_session_id", "session_id", "cookie", "cookies", "authorization", "api_key", "provider_key",
        "body_base64", "raw_body", "full_text", "access_token", "refresh_token"));

    static void require(boolean condition) throws NativeFailure {
        if (!condition) throw new NativeFailure("OFFLINE_PACKAGE_INVALID");
    }
    static void keys(JSONObject object, String... expected) throws NativeFailure {
        Set<String> allowed = new HashSet<>(Arrays.asList(expected));
        require(object.length() == allowed.size());
        Iterator<String> keys = object.keys();
        while (keys.hasNext()) require(allowed.contains(keys.next()));
    }
    static JSONObject object(JSONObject parent, String key) throws NativeFailure {
        Object value = parent.opt(key); require(value instanceof JSONObject); return (JSONObject) value;
    }
    static JSONArray array(JSONObject parent, String key, int maximum) throws NativeFailure {
        Object value = parent.opt(key); require(value instanceof JSONArray);
        JSONArray result = (JSONArray) value; require(result.length() <= maximum); return result;
    }
    static JSONObject at(JSONArray rows, int index) throws NativeFailure {
        Object value = rows.opt(index); require(value instanceof JSONObject); return (JSONObject) value;
    }
    static String text(JSONObject parent, String key, int maximum) throws NativeFailure {
        Object value = parent.opt(key); require(value instanceof String && ((String) value).length() <= maximum);
        return (String) value;
    }
    static String nullableText(JSONObject parent, String key, int maximum) throws NativeFailure {
        require(parent.has(key)); return parent.isNull(key) ? null : text(parent, key, maximum);
    }
    static long number(JSONObject parent, String key, long maximum) throws NativeFailure {
        Object value = parent.opt(key);
        require(value instanceof Integer || value instanceof Long);
        long result = ((Number) value).longValue(); require(result >= 0 && result <= maximum); return result;
    }
    static String uuid(JSONObject parent, String key) throws NativeFailure {
        String value = text(parent, key, 36); NativePolicy.requestId(value); return value;
    }
    static String hash(JSONObject parent, String key) throws NativeFailure {
        String value = text(parent, key, 64); require(value.matches("[0-9a-f]{64}")); return value;
    }
    static void equal(JSONObject object, String key, Object expected) throws NativeFailure {
        require(expected.equals(object.opt(key)));
    }
    private static void time(JSONObject object, String key, boolean nullable) throws NativeFailure {
        String value = nullable ? nullableText(object, key, 80) : text(object, key, 80);
        if (value != null) {
            try { OffsetDateTime.parse(value); } catch (Exception ignored) { require(false); }
        }
    }
    private static void privacy(JSONObject object, boolean privateOnly) throws NativeFailure {
        require((privateOnly ? PRIVATE : PRIVACY).contains(text(object, "privacy_class", 16)));
    }

    /** Duplicate keys/deep trees/credential-shaped keys fail before JSONObject construction. */
    static JSONObject parse(byte[] bytes) throws NativeFailure {
        return parse(bytes, MAX_BYTES);
    }
    static JSONObject response(byte[] bytes) throws NativeFailure { return parse(bytes, NativePolicy.MAX_RESPONSE_BYTES); }
    private static JSONObject parse(byte[] bytes, int maximumBytes) throws NativeFailure {
        return parse(bytes, maximumBytes, false);
    }
    private static JSONObject parse(byte[] bytes, int maximumBytes, boolean versionTwoNumbers) throws NativeFailure {
        require(bytes != null && bytes.length > 0 && bytes.length <= maximumBytes);
        require(!(bytes.length >= 3 && (bytes[0] & 255) == 239 && (bytes[1] & 255) == 187 && (bytes[2] & 255) == 191));
        try (JsonReader reader = new JsonReader(new StringReader(NativePolicy.utf8(bytes, "OFFLINE_PACKAGE_INVALID")))) {
            reader.setLenient(false);
            Object result = read(reader, 0, new int[] {0}, versionTwoNumbers);
            require(result instanceof JSONObject && reader.peek() == JsonToken.END_DOCUMENT);
            return (JSONObject) result;
        } catch (NativeFailure failure) { throw failure; }
        catch (Exception ignored) { throw new NativeFailure("OFFLINE_PACKAGE_INVALID"); }
    }
    private static Object read(JsonReader reader, int depth, int[] nodes, boolean versionTwoNumbers) throws Exception {
        require(depth <= 32 && ++nodes[0] <= 1000000);
        switch (reader.peek()) {
            case BEGIN_OBJECT:
                reader.beginObject(); JSONObject object = new JSONObject(); Set<String> seen = new HashSet<>();
                while (reader.hasNext()) {
                    String key = reader.nextName();
                    require(key.length() <= 256 && seen.add(key) && !FORBIDDEN.contains(key.toLowerCase(Locale.ROOT)));
                    object.put(key, read(reader, depth + 1, nodes, versionTwoNumbers));
                }
                reader.endObject(); return object;
            case BEGIN_ARRAY:
                reader.beginArray(); JSONArray array = new JSONArray();
                while (reader.hasNext()) { require(array.length() < 40000); array.put(read(reader, depth + 1, nodes, versionTwoNumbers)); }
                reader.endArray(); return array;
            case STRING: return reader.nextString();
            case BOOLEAN: return reader.nextBoolean();
            case NULL: reader.nextNull(); return JSONObject.NULL;
            case NUMBER:
                String value = reader.nextString();
                if (value.matches("-?(0|[1-9][0-9]*)")) {
                    if (!versionTwoNumbers) return Long.parseLong(value);
                    BigInteger integer = new BigInteger(value);
                    return OfflineJsonInteger.jsonNumber(integer.bitLength() <= 63 ? integer.longValue() : integer);
                }
                return new BigDecimal(value);
            default: throw new NativeFailure("OFFLINE_PACKAGE_INVALID");
        }
    }

    static void descriptor(JSONObject descriptor, JSONObject request) throws NativeFailure {
        keys(descriptor, "schema", "id", "plan_id", "created_at", "content_created_at", "plan_fingerprint",
            "owner_scope_id", "privacy_class", "sha256", "byte_count", "base_pack_id", "counts", "download_path",
            "data_state", "source_refresh_performed");
        packVersion(descriptor, "offline-pack-descriptor@");
        equal(descriptor, "data_state", "local_snapshot"); equal(descriptor, "source_refresh_performed", false);
        equal(descriptor, "id", uuid(request, "package_id")); uuid(descriptor, "plan_id");
        equal(descriptor, "sha256", hash(request, "expected_sha256"));
        require(number(descriptor, "byte_count", MAX_BYTES) == number(request, "expected_byte_count", MAX_BYTES));
        equal(descriptor, "plan_fingerprint", hash(request, "approved_plan_fingerprint"));
        hash(descriptor, "owner_scope_id"); privacy(descriptor, true);
        time(descriptor, "created_at", false); time(descriptor, "content_created_at", false);
        require(descriptor.has("base_pack_id")); if (!descriptor.isNull("base_pack_id")) uuid(descriptor, "base_pack_id");
        equal(descriptor, "download_path", "/v1/offline-packs/" + uuid(request, "package_id") + "/download?mode=history");
        counts(object(descriptor, "counts"));
    }
    private static void counts(JSONObject counts) throws NativeFailure {
        keys(counts, "garage_profiles", "watch_items", "recent_queries", "distinct_evidence", "searchable_documents");
        number(counts, "garage_profiles", 50); number(counts, "watch_items", 100); number(counts, "recent_queries", 20);
        number(counts, "distinct_evidence", 200); number(counts, "searchable_documents", 4000);
    }
    static void installRequest(JSONObject request) throws NativeFailure {
        keys(request, "package_id", "expected_sha256", "expected_byte_count", "approved_plan_fingerprint",
            "slot_id", "expected_generation", "allow_device_storage");
        uuid(request, "package_id"); uuid(request, "slot_id"); hash(request, "expected_sha256");
        hash(request, "approved_plan_fingerprint"); require(number(request, "expected_byte_count", MAX_BYTES) > 0);
        number(request, "expected_generation", 9007199254740990L); equal(request, "allow_device_storage", true);
    }

    static JSONObject envelope(byte[] bytes, JSONObject descriptor) throws NativeFailure {
        require(bytes.length == number(descriptor, "byte_count", MAX_BYTES) &&
            OfflineCipher.sha256(bytes).equals(hash(descriptor, "sha256")));
        boolean versionTwo = packVersion(descriptor, "offline-pack-descriptor@");
        JSONObject root = parse(bytes, MAX_BYTES, versionTwo);
        keys(root, "schema", "package_id", "created_at", "plan_fingerprint", "owner_scope_id", "privacy_class",
            "data_state", "source_refresh_performed", "base_pack_id", "scope", "contracts", "contexts", "members",
            "documents", "omissions");
        equal(root, "schema", versionTwo ? "offline-pack@2" : "offline-pack@1"); equal(root, "data_state", "local_snapshot");
        equal(root, "source_refresh_performed", false); equal(root, "package_id", uuid(descriptor, "id"));
        equal(root, "plan_fingerprint", hash(descriptor, "plan_fingerprint"));
        equal(root, "owner_scope_id", hash(descriptor, "owner_scope_id")); privacy(root, true);
        equal(root, "privacy_class", text(descriptor, "privacy_class", 16));
        equal(root, "created_at", text(descriptor, "content_created_at", 80)); time(root, "created_at", false);
        require(java.util.Objects.equals(root.opt("base_pack_id"), descriptor.opt("base_pack_id")));
        scope(object(root, "scope"), versionTwo);
        JSONObject contracts = object(root, "contracts");
        keys(contracts, "offline_policy", "field_policy", "recall_policy"); equal(contracts, "offline_policy", "offline-policy@1");
        object(contracts, "field_policy"); object(contracts, "recall_policy");
        JSONArray members = array(root, "members", 200), contexts = array(root, "contexts", 150), documents = array(root, "documents", 4000);
        Map<String, JSONObject> memberMap = new HashMap<>(), contextMap = new HashMap<>();
        for (int i = 0; i < members.length(); i++) {
            JSONObject member = at(members, i); member(member, versionTwo);
            require(memberMap.put(hash(member, "key"), member) == null);
        }
        int garages = 0, watches = 0;
        for (int i = 0; i < contexts.length(); i++) {
            JSONObject context = at(contexts, i);
            keys(context, "id", "kind", "scope", "privacy_class", "payload", "evidence_keys");
            String kind = text(context, "kind", 16), id = text(context, "id", 80);
            require(kind.equals("garage") || kind.equals("watchlist"));
            equal(context, "scope", kind.equals("garage") ? "local_workspace" : "current_session");
            equal(context, "privacy_class", "private"); object(context, "payload");
            if (kind.equals("garage")) garages++; else watches++;
            require(id.startsWith(kind + ":") && contextMap.put(id, context) == null);
            JSONArray related = array(context, "evidence_keys", 200);
            for (int n = 0; n < related.length(); n++) require(memberMap.containsKey(related.opt(n)));
        }
        require(garages <= 50 && watches <= 100);
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < documents.length(); i++) {
            JSONObject doc = at(documents, i);
            keys(doc, "id", "category", "kind", "member_key", "context_id", "record_index", "title", "text", "facets",
                "membership", "privacy_class", "observed_at", "verified_at");
            require(ids.add(text(doc, "id", 256))); text(doc, "title", 2000); text(doc, "text", 1000000); privacy(doc, false);
            time(doc, "observed_at", true); time(doc, "verified_at", true);
            JSONObject facets = object(doc, "facets"); keys(facets, "brand", "model", "size", "source_id", "campaign_number");
            for (String facet : new String[] {"brand", "model", "size", "source_id", "campaign_number"}) nullableText(facets, facet, 2000);
            JSONArray membership = array(doc, "membership", 4);
            for (int n = 0; n < membership.length(); n++) require(Arrays.asList("garage", "watchlist", "recent", "explicit").contains(membership.opt(n)));
            String category = text(doc, "category", 16), kind = text(doc, "kind", 16);
            require(doc.has("record_index"));
            if (category.equals("evidence")) {
                String memberKey = nullableText(doc, "member_key", 64); require(memberKey != null && doc.isNull("context_id"));
                JSONObject member = memberMap.get(memberKey); require(member != null);
                equal(object(member, "reference"), "kind", kind);
                JSONObject payload = object(member, "payload");
                require(java.util.Objects.equals(facets.opt("source_id"), object(member, "source").opt("source_id")));
                if (kind.equals("recall") || kind.equals("test_event") || kind.equals("recall_search")) {
                    JSONArray records = kind.equals("recall") ? array(payload, "records", 1000)
                        : kind.equals("recall_search") ? array(object(payload, "discovery"), "products", 10)
                        : array(object(payload, "event"), "participants", 2000);
                    if (records.length() == 0) require(doc.isNull("record_index"));
                    else {
                        int record = (int) number(doc, "record_index", records.length() - 1);
                        if (kind.equals("recall")) {
                            JSONObject row = at(records, record);
                            require(java.util.Objects.equals(row.opt("make"), facets.opt("brand")) &&
                                java.util.Objects.equals(row.opt("model"), facets.opt("model")) &&
                                java.util.Objects.equals(row.opt("campaign_number"), facets.opt("campaign_number")));
                        } else if (kind.equals("recall_search")) {
                            JSONObject row = at(records, record);
                            require(java.util.Objects.equals(row.opt("brand"), facets.opt("brand")) &&
                                java.util.Objects.equals(row.opt("tireline"), facets.opt("model")) &&
                                java.util.Objects.equals(row.opt("size"), facets.opt("size")) && facets.isNull("campaign_number"));
                        } else {
                            JSONObject row = at(records, record);
                            require(java.util.Objects.equals(row.opt("brand"), facets.opt("brand")) &&
                                java.util.Objects.equals(row.opt("model"), facets.opt("model")) && facets.isNull("campaign_number"));
                        }
                    }
                } else require(doc.isNull("record_index"));
            } else {
                require(category.equals("garage") || category.equals("watchlist")); equal(doc, "kind", category);
                require(doc.isNull("member_key") && doc.isNull("record_index"));
                JSONObject context = contextMap.get(nullableText(doc, "context_id", 80)); require(context != null);
                equal(context, "kind", category); require(facets.isNull("source_id") && facets.isNull("campaign_number"));
            }
        }
        JSONObject count = object(descriptor, "counts");
        require(number(count, "garage_profiles", 50) == garages && number(count, "watch_items", 100) == watches &&
            number(count, "distinct_evidence", 200) == members.length() && number(count, "searchable_documents", 4000) == documents.length());
        array(root, "omissions", 2000);
        return root;
    }
    static void scope(JSONObject scope) throws NativeFailure {
        scope(scope, false);
    }
    static void scope(JSONObject scope, boolean versionTwo) throws NativeFailure {
        keys(scope, "garage", "watchlist", "recent", "references");
        for (String kind : new String[] {"garage", "watchlist"}) {
            JSONObject selector = object(scope, kind); String ids = kind.equals("garage") ? "vehicle_ids" : "item_ids";
            keys(selector, "include", ids); require(selector.opt("include") instanceof Boolean);
            if (!selector.isNull(ids)) { JSONArray rows = array(selector, ids, 1000); for (int i=0;i<rows.length();i++) require(rows.opt(i) instanceof String); }
        }
        JSONObject recent = object(scope, "recent"); keys(recent, "include", "limit"); require(recent.opt("include") instanceof Boolean); number(recent, "limit", 20);
        JSONArray refs = array(scope, "references", 1000); for (int i=0;i<refs.length();i++) reference(at(refs,i), false, versionTwo);
    }
    private static boolean packVersion(JSONObject value, String prefix) throws NativeFailure {
        String schema = text(value, "schema", 64);
        require(schema.equals(prefix + "1") || schema.equals(prefix + "2"));
        return schema.equals(prefix + "2");
    }
    private static void reference(JSONObject reference, boolean resolved, boolean versionTwo) throws NativeFailure {
        String kind = text(reference, "kind", 16); require(KINDS.contains(kind) || (versionTwo && kind.equals("recall_search")));
        Set<String> allowed = new HashSet<>(Arrays.asList("kind"));
        if (kind.equals("test_event")) {
            allowed.add("event_id"); allowed.add("event_revision"); uuid(reference, "event_id"); require(number(reference, "event_revision", 1000000) > 0);
        } else {
            allowed.add("snapshot_id"); uuid(reference, "snapshot_id");
            if (kind.equals("tire")) { allowed.add("variant_id"); uuid(reference, "variant_id"); }
            if (kind.equals("recall")) { allowed.add("recall_revision_id"); require(reference.has("recall_revision_id")); if (!reference.isNull("recall_revision_id")) uuid(reference,"recall_revision_id"); }
            if (resolved || kind.equals("recall_search") || reference.has("verification_id")) { allowed.add("verification_id"); uuid(reference, "verification_id"); }
        }
        keys(reference, allowed.toArray(new String[0]));
    }
    private static void member(JSONObject member, boolean versionTwo) throws NativeFailure {
        keys(member, "key", "reference", "member_reasons", "privacy_class", "raw_included", "source", "payload");
        hash(member, "key"); privacy(member, false); equal(member, "raw_included", false);
        JSONObject reference = object(member, "reference"); reference(reference, true, versionTwo);
        JSONArray reasons = array(member, "member_reasons", 1000);
        for (int i=0;i<reasons.length();i++) {
            JSONObject reason=at(reasons,i); keys(reason,"selector","scope","object_id","revision","axle");
            require(Arrays.asList("garage","watchlist","recent","explicit").contains(text(reason,"selector",16)));
            require(Arrays.asList("local_workspace","current_session","explicit").contains(text(reason,"scope",24)));
            nullableText(reason,"object_id",128); require(reason.has("revision") && reason.has("axle"));
            if (!reason.isNull("revision")) number(reason,"revision",1000000);
            String axle=nullableText(reason,"axle",8); require(axle==null||axle.equals("front")||axle.equals("rear"));
        }
        JSONObject source=object(member,"source");
        keys(source,"source_id","source_url","raw_hash","parser_version","parser_identity","observed_at","verified_at","verification_id");
        nullableText(source,"source_id",100); nullableText(source,"parser_version",200); time(source,"observed_at",false); time(source,"verified_at",true);
        String url=nullableText(source,"source_url",4096);
        if (url!=null) { try { URI parsed=new URI(url); require(Arrays.asList("http","https").contains(parsed.getScheme()) && parsed.getHost()!=null && parsed.getUserInfo()==null); } catch(Exception ignored) { require(false); } }
        String raw=nullableText(source,"raw_hash",64); if(raw!=null) require(raw.matches("[0-9a-f]{64}"));
        require(source.has("parser_identity")); if(!source.isNull("parser_identity")) object(source,"parser_identity");
        nullableText(source,"verification_id",36);
        if(reference.has("verification_id")) equal(source,"verification_id",uuid(reference,"verification_id"));
        JSONObject payload=object(member,"payload"); String kind=text(reference,"kind",16);
        if(kind.equals("recall")) {
            keys(payload,"evidence","records","facts","policy","boundary");
            JSONObject evidence=object(payload,"evidence"), boundary=object(payload,"boundary"), policy=object(payload,"policy");
            equal(evidence,"kind","regulatory"); equal(evidence,"evidence_type","recall"); equal(evidence,"applicability","not_assessed");
            equal(evidence,"snapshot_id",uuid(reference,"snapshot_id")); equal(evidence,"verification_id",uuid(reference,"verification_id"));
            require(java.util.Objects.equals(evidence.opt("recall_revision_id"),reference.opt("recall_revision_id")));
            equal(boundary,"policy","recall-fact-selection@1"); equal(boundary,"applicability","not_assessed"); equal(boundary,"mode","announcement_facts_only");
            equal(policy,"version","recall-fact-selection@1"); hash(policy,"digest");
            JSONArray records=array(payload,"records",1000); require(number(evidence,"record_count",1000)==records.length());
            equal(evidence,"observation_kind",records.length()==0?"empty":"records");
            require(records.length()==0?reference.isNull("recall_revision_id"):!reference.isNull("recall_revision_id"));
            JSONArray facts=array(payload,"facts",20000); require(facts.length()==4+records.length()*14);
        } else if(kind.equals("recall_search")) {
            OfflineRecallSearchValidator.validate(payload, reference, source);
        } else if(kind.equals("tire")) {
            keys(payload,"variant","identity_contract","snapshot_identity_contract","field_resolution","lifecycle");
            equal(object(payload,"variant"),"id",uuid(reference,"variant_id")); object(payload,"identity_contract"); object(payload,"field_resolution");
            nullableText(payload,"snapshot_identity_contract",100); text(payload,"lifecycle",100);
        } else if(kind.equals("vehicle")) {
            keys(payload,"vehicle","trims","fitments","footnotes","fact_hash","fact_version","excluded_document_count");
            object(payload,"vehicle"); array(payload,"trims",2000); array(payload,"fitments",10000); array(payload,"footnotes",2000);
            hash(payload,"fact_hash"); require(number(payload,"fact_version",1000000)>0); number(payload,"excluded_document_count",1000000);
        } else {
            keys(payload,"metadata","event"); object(payload,"event"); JSONObject metadata=object(payload,"metadata");
            equal(metadata,"id",uuid(reference,"event_id")); require(number(metadata,"revision",1000000)==number(reference,"event_revision",1000000));
            equal(metadata,"record_kind","manual_transcription"); equal(metadata,"verification_status","unverified"); require(metadata.isNull("verified_at"));
        }
    }
}
