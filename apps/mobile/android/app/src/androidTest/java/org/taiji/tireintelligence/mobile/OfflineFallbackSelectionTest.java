package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.InputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Original producer receipts exercise projections; mutations isolate the pure tri-state kernel. */
@RunWith(AndroidJUnit4.class)
public final class OfflineFallbackSelectionTest {
    private static byte[] bytes(String name) throws Exception {
        try (InputStream stream = InstrumentationRegistry.getInstrumentation().getContext().getAssets()
            .open("offline-producer49/" + name)) { return stream.readAllBytes(); }
    }
    private static final class Sample {
        final byte[] original;
        final JSONObject descriptor, material;
        Sample(String prefix) throws Exception {
            original = bytes(prefix + "-pack.json");
            descriptor = OfflinePackageValidator.response(bytes(prefix + "-descriptor.json"));
            material = OfflinePackageValidator.envelope(original, descriptor);
        }
    }
    private static JSONObject clone(JSONObject value) throws Exception {
        return (JSONObject) OfflineTireCriteria.parse(OfflineJsonInteger.stringify(value), OfflinePackageValidator.MAX_BYTES, 1000000);
    }
    private static JSONObject member(Sample sample, String kind) throws Exception {
        JSONArray all = sample.material.getJSONArray("members");
        for (int at = 0; at < all.length(); at++)
            if (kind.equals(all.getJSONObject(at).getJSONObject("reference").getString("kind"))) return all.getJSONObject(at);
        throw new AssertionError("Missing producer fixture kind");
    }
    private static JSONObject intent(String kind, JSONObject member) throws Exception {
        JSONObject payload = member.getJSONObject("payload"), query;
        if (kind.equals("tire")) query = new JSONObject().put("model", payload.getJSONObject("variant").getString("model"));
        else if (kind.equals("vehicle_fitments")) query = new JSONObject().put("vehicle_id", payload.getJSONObject("vehicle").getString("id"));
        else if (kind.equals("recall_campaign")) query = new JSONObject().put("campaign_number", payload.getJSONObject("evidence").getString("campaign_number"));
        else query = clone(payload.getJSONObject("query"));
        return new JSONObject().put("query_kind", kind).put("source_id", member.getJSONObject("source").getString("source_id"))
            .put("query", query).put("filters", new JSONArray());
    }
    private static JSONObject receipt(Sample sample) throws Exception {
        return new JSONObject().put("schema", "device-fallback-grant@2").put("id", UUID.randomUUID().toString())
            .put("state", "consumed").put("consumed_at", "2026-10-01T08:00:00Z")
            .put("profile_id", "qa-selection-profile").put("owner_epoch", 1).put("slot_id", UUID.randomUUID().toString())
            .put("generation", 1).put("package_sha256", sample.descriptor.getString("sha256"))
            .put("fallback_authorization", new JSONObject().put("type", "explicit_once"));
    }
    private static JSONObject observation(JSONObject original, int index) throws Exception {
        JSONObject value = clone(original);
        value.put("key", OfflineCipher.sha256(("qa-observation:" + index).getBytes(StandardCharsets.UTF_8)));
        value.getJSONObject("reference").put("snapshot_id", UUID.randomUUID().toString());
        return value;
    }

    @Test public void originalFourDomainsKeepReceiptsAndBoundCitations() throws Exception {
        Sample sample = new Sample("nonempty");
        String[][] pairs = {{"tire", "tire"}, {"vehicle_fitments", "vehicle"}, {"recall_campaign", "recall"}, {"recall_search", "recall_search"}};
        for (String[] pair : pairs) {
            JSONObject request = intent(pair[0], member(sample, pair[1])), grant = receipt(sample);
            JSONObject result = OfflineFallbackSelection.result(sample.material, request, grant, new JSONObject());
            assertEquals(pair[0], result.getString("query_kind"));
            assertEquals(pair[0], pair[0].equals("recall_campaign") ? 2 : 1, result.getJSONArray("members").length());
            assertFalse(result.getBoolean("complete_query_result"));
            assertEquals(pair[0].equals("tire"), !result.isNull("selection"));
            JSONArray citations = result.getJSONArray("citations");
            assertTrue(citations.length() >= result.getJSONArray("members").length());
            for (int at = 0; at < citations.length(); at++) {
                JSONObject citation = citations.getJSONObject(at);
                assertTrue(citation.getString("id").startsWith("device:"));
                assertEquals(grant.getString("profile_id"), citation.getString("profile_id"));
                assertEquals(grant.getString("slot_id"), citation.getString("slot_id"));
                assertEquals(sample.descriptor.getString("sha256"), citation.getString("package_sha256"));
                assertFalse(citation.isNull("document_id"));
            }
        }
    }

    @Test public void countsAllSourceObservationsWithBasicAndAdvancedFalseBeforeUnknown() throws Exception {
        Sample sample = new Sample("nonempty"); JSONObject original = member(sample, "tire");
        JSONObject request = intent("tire", original);
        request.put("filters", new JSONArray().put(new JSONObject().put("field", "eu_external_noise_db").put("op", "lte").put("value", 72)));
        JSONObject matching = observation(original, 1); matching.getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").put("eu_external_noise_db", 70);
        JSONObject excluded = observation(original, 2); excluded.getJSONObject("payload").getJSONObject("variant").put("model", "Different model");
        JSONObject otherSource = observation(original, 3); otherSource.getJSONObject("source").put("source_id", "different-source");
        sample.material.getJSONArray("members").put(matching).put(excluded).put(otherSource);
        JSONObject selected = OfflineFallbackSelection.select(sample.material, request), counts = selected.getJSONObject("selection");
        assertEquals(3, counts.getInt("source_count")); assertEquals(1, counts.getInt("matched_count"));
        assertEquals(1, counts.getInt("excluded_count")); assertEquals(1, counts.getInt("undetermined_count"));
        assertEquals(1, counts.getJSONArray("filters").length());
        assertEquals(matching.getString("key"), selected.getJSONArray("members").getJSONObject(0).getString("key"));
        // The same variant id in a new receipt remains a second observation.
        request.put("filters", new JSONArray());
        assertEquals(2, OfflineFallbackSelection.select(sample.material, request).getJSONArray("members").length());
    }

    @Test public void sizeOnlyAndAllSixteenAdvancedConditionsDoNotDropBasicQuery() throws Exception {
        Sample sample = new Sample("nonempty"); JSONObject tire = member(sample, "tire");
        JSONObject request = intent("tire", tire).put("query", new JSONObject().put("size", tire.getJSONObject("payload").getJSONObject("variant").getString("size")));
        JSONArray filters = new JSONArray();
        for (int at = 0; at < 16; at++) filters.put(new JSONObject().put("field", "model").put("op", "is_known"));
        request.put("filters", filters);
        assertEquals(1, OfflineFallbackSelection.select(sample.material, request).getJSONArray("members").length());
        request.getJSONObject("query").put("size", "225/50R17");
        JSONObject counts = OfflineFallbackSelection.select(sample.material, request).getJSONObject("selection");
        assertEquals(1, counts.getInt("source_count")); assertEquals(1, counts.getInt("excluded_count"));
    }

    @Test public void exactSearchPageAndEmptyAreNotCampaignOrCompleteBaseline() throws Exception {
        Sample sample = new Sample("empty"); JSONObject search = member(sample, "recall_search");
        JSONObject request = intent("recall_search", search), result = OfflineFallbackSelection.result(sample.material, request, receipt(sample), new JSONObject());
        JSONObject page = result.getJSONArray("members").getJSONObject(0).getJSONObject("payload");
        assertTrue(page.getBoolean("empty_observation")); assertFalse(result.getBoolean("complete_query_result"));
        assertEquals("not_assessed", page.getJSONObject("boundary").getString("applicability"));
        assertEquals(1, result.getJSONArray("citations").length());
        String previousOffset = request.getJSONObject("query").getString("offset");
        request.getJSONObject("query").put("offset", previousOffset.equals("0") ? "10" : "0");
        assertEquals(0, OfflineFallbackSelection.select(sample.material, request).getJSONArray("members").length());
        request.getJSONObject("query").put("offset", previousOffset).put("search", request.getJSONObject("query").getString("search").toLowerCase(java.util.Locale.ROOT));
        assertEquals(0, OfflineFallbackSelection.select(sample.material, request).getJSONArray("members").length());
    }

    @Test public void recallBothEmptyAndRecordReceiptsRemainNotAssessed() throws Exception {
        Sample sample = new Sample("nonempty"); JSONObject request = intent("recall_campaign", member(sample, "recall"));
        JSONObject result = OfflineFallbackSelection.result(sample.material, request, receipt(sample), new JSONObject());
        boolean empty = false, records = false;
        for (int at = 0; at < result.getJSONArray("members").length(); at++) {
            JSONObject payload = result.getJSONArray("members").getJSONObject(at).getJSONObject("payload");
            assertEquals("not_assessed", payload.getJSONObject("boundary").getString("applicability"));
            empty |= payload.getJSONArray("records").length() == 0;
            records |= payload.getJSONArray("records").length() > 0;
        }
        assertTrue(empty && records); assertEquals(3, result.getJSONArray("citations").length());
        request.getJSONObject("query").put("campaign_number", "23T999999");
        assertEquals(0, OfflineFallbackSelection.select(sample.material, request).getJSONArray("members").length());
    }

    @Test public void hugeIntegerFactsAndCriterionSurviveResultTransport() throws Exception {
        Sample sample = new Sample("nonempty"); JSONObject tire = member(sample, "tire");
        String token = "1" + "0".repeat(309), greater = token.substring(0, token.length() - 1) + "1";
        tire.getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").put("utqg_treadwear", OfflineJsonInteger.jsonNumber(new BigInteger(token)));
        JSONObject request = intent("tire", tire);
        request.put("filters", (JSONArray) OfflineTireCriteria.parse("[{\"field\":\"utqg_treadwear\",\"op\":\"eq\",\"value\":" + token + "}]"));
        JSONObject result = OfflineFallbackSelection.result(sample.material, request, receipt(sample), new JSONObject());
        assertEquals(1, result.getJSONObject("selection").getInt("matched_count"));
        JSONObject exact = OfflineFallbackWire.decode(OfflineFallbackWire.encode(result));
        Object actual = exact.getJSONArray("members").getJSONObject(0).getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").get("utqg_treadwear");
        assertEquals(new BigInteger(token), OfflineJsonInteger.number(actual));
        request.put("filters", (JSONArray) OfflineTireCriteria.parse("[{\"field\":\"utqg_treadwear\",\"op\":\"gte\",\"value\":" + greater + "}]"));
        assertEquals(1, OfflineFallbackSelection.select(sample.material, request).getJSONObject("selection").getInt("excluded_count"));
    }

    @Test public void futureSchemasAndLegacySearchFailClosed() throws Exception {
        Sample sample = new Sample("nonempty"); JSONObject request = intent("recall_search", member(sample, "recall_search"));
        sample.material.put("schema", "offline-pack@3");
        try { OfflineFallbackSelection.select(sample.material, request); fail("Future package accepted"); }
        catch (NativeFailure expected) { assertEquals("OFFLINE_PACKAGE_INVALID", expected.code); }
        sample.material.put("schema", "offline-pack@1");
        try { OfflineFallbackSelection.select(sample.material, request); fail("Legacy search accepted"); }
        catch (NativeFailure expected) { assertEquals("OFFLINE_FALLBACK_UNSUPPORTED", expected.code); }
        request.put("query_kind", "future");
        try { OfflineFallbackSelection.select(sample.material, request); fail("Future query accepted"); }
        catch (NativeFailure expected) { assertEquals("OFFLINE_FALLBACK_UNSUPPORTED", expected.code); }
    }

    private static JSONObject installRequest(Sample sample) throws Exception {
        return new JSONObject().put("package_id", sample.descriptor.getString("id"))
            .put("expected_sha256", sample.descriptor.getString("sha256")).put("expected_byte_count", sample.original.length)
            .put("approved_plan_fingerprint", sample.descriptor.getString("plan_fingerprint"))
            .put("slot_id", UUID.randomUUID().toString()).put("expected_generation", 0).put("allow_device_storage", true);
    }
    @Test public void realEncryptedStoreManualV2ReadReturnsMandatoryExactCoreAndSearchPage() throws Exception {
        Sample sample = new Sample("nonempty");
        try (OfflinePackStore store = new OfflinePackStore(InstrumentationRegistry.getInstrumentation().getTargetContext(), "qa-r49-manual-v2-" + UUID.randomUUID())) {
            JSONObject slot = store.install(installRequest(sample), sample.descriptor, sample.original);
            JSONObject search = store.search(new JSONObject().put("slot_id", slot.getString("slot_id")).put("expected_generation", slot.getLong("generation"))
                .put("query", "").put("kind", "recall_search").put("limit", 50).put("offset", 0));
            assertEquals(1, search.getInt("total"));
            String tireKey = member(sample, "tire").getString("key"), documentId = null;
            JSONArray docs = sample.material.getJSONArray("documents");
            for (int at = 0; at < docs.length(); at++) if (tireKey.equals(docs.getJSONObject(at).opt("member_key"))) documentId = docs.getJSONObject(at).getString("id");
            assertNotNull(documentId);
            JSONObject wire = store.read(new JSONObject().put("slot_id", slot.getString("slot_id")).put("expected_generation", slot.getLong("generation")).put("document_id", documentId));
            assertEquals("offline-read-result@2", wire.getString("schema")); assertTrue(wire.has("raw_json"));
            JSONObject exact = OfflineFallbackWire.decode(wire);
            Object integer = exact.getJSONObject("member").getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").get("reference_int");
            assertEquals(new BigInteger("9007199254740993"), new BigInteger(OfflineJsonInteger.number(integer).toString()));
        }
    }
    @Test public void legacyManualReadKeepsOriginalShape() throws Exception {
        Sample sample = new Sample("legacy");
        try (OfflinePackStore store = new OfflinePackStore(InstrumentationRegistry.getInstrumentation().getTargetContext(), "qa-r49-manual-v1-" + UUID.randomUUID())) {
            JSONObject slot = store.install(installRequest(sample), sample.descriptor, sample.original);
            JSONObject result = store.read(new JSONObject().put("slot_id", slot.getString("slot_id")).put("expected_generation", slot.getLong("generation"))
                .put("document_id", sample.material.getJSONArray("documents").getJSONObject(0).getString("id")));
            assertFalse(result.has("schema")); assertFalse(result.has("raw_json")); assertFalse(result.has("package_schema"));
        }
    }
}
