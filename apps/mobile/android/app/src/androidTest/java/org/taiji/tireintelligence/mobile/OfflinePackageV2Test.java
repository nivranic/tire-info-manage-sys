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

/** Original FastAPI producer bytes plus bounded structural rejection mutations. */
@RunWith(AndroidJUnit4.class)
public final class OfflinePackageV2Test {
    private static byte[] bytes(String name) throws Exception {
        try (InputStream stream = InstrumentationRegistry.getInstrumentation().getContext().getAssets()
            .open("offline-producer49/" + name)) { return stream.readAllBytes(); }
    }
    private static final class Sample {
        JSONObject descriptor, envelope;
        byte[] original;
        Sample(String kind) throws Exception {
            original = bytes(kind + "-pack.json");
            descriptor = OfflinePackageValidator.response(bytes(kind + "-descriptor.json"));
            envelope = OfflinePackageValidator.envelope(original, descriptor);
        }
    }
    private static JSONObject member(JSONObject envelope, String kind) throws Exception {
        JSONArray members = envelope.getJSONArray("members");
        for (int at = 0; at < members.length(); at++) {
            JSONObject member = members.getJSONObject(at);
            if (kind.equals(member.getJSONObject("reference").getString("kind"))) return member;
        }
        throw new AssertionError("Missing fixture kind: " + kind);
    }
    private static byte[] changedBytes(Sample sample) throws Exception {
        byte[] bytes = sample.envelope.toString().getBytes(StandardCharsets.UTF_8);
        sample.descriptor.put("byte_count", bytes.length).put("sha256", OfflineCipher.sha256(bytes));
        return bytes;
    }
    private static void rejected(Sample sample) throws Exception {
        try { OfflinePackageValidator.envelope(changedBytes(sample), sample.descriptor); fail("Invalid envelope accepted"); }
        catch (NativeFailure expected) { assertEquals("OFFLINE_PACKAGE_INVALID", expected.code); }
    }
    private static JSONObject installRequest(JSONObject descriptor) throws Exception {
        return new JSONObject().put("package_id", descriptor.getString("id"))
            .put("expected_sha256", descriptor.getString("sha256")).put("expected_byte_count", descriptor.getLong("byte_count"))
            .put("approved_plan_fingerprint", descriptor.getString("plan_fingerprint"))
            .put("slot_id", UUID.randomUUID().toString()).put("expected_generation", 0).put("allow_device_storage", true);
    }

    @Test public void originalProducerLegacyAndTwoPagesValidate() throws Exception {
        for (String name : new String[]{"legacy", "nonempty", "empty"}) {
            Sample sample = new Sample(name);
            OfflinePackageValidator.descriptor(sample.descriptor, installRequest(sample.descriptor));
            assertEquals(name, sample.descriptor.getString("sha256"), OfflineCipher.sha256(sample.original));
            assertEquals(name, sample.original.length, sample.descriptor.getInt("byte_count"));
            if (!name.equals("legacy")) {
                JSONObject page = member(sample.envelope, "recall_search").getJSONObject("payload");
                assertEquals(name.equals("empty"), page.getBoolean("empty_observation"));
                assertEquals("not_assessed", page.getJSONObject("boundary").getString("applicability"));
            }
        }
    }
    @Test public void unknownAndMixedVersionsFailClosed() throws Exception {
        Sample unknown = new Sample("nonempty"); unknown.descriptor.put("schema", "offline-pack-descriptor@3"); rejected(unknown);
        Sample mixed = new Sample("nonempty"); mixed.descriptor.put("schema", "offline-pack-descriptor@1"); rejected(mixed);
        Sample legacyWithSearch = new Sample("nonempty");
        legacyWithSearch.envelope.put("schema", "offline-pack@1"); legacyWithSearch.descriptor.put("schema", "offline-pack-descriptor@1");
        rejected(legacyWithSearch);
    }
    @Test public void requiredReceiptAndObservedTimesStayBound() throws Exception {
        Sample missing = new Sample("nonempty"); member(missing.envelope, "recall_search").getJSONObject("reference").remove("verification_id"); rejected(missing);
        Sample changed = new Sample("nonempty");
        member(changed.envelope, "recall_search").getJSONObject("payload").getJSONObject("evidence").put("verified_at", "2020-01-01T00:00:00Z");
        rejected(changed);
    }
    @Test public void pageQueryOffsetAndPaginationStayExact() throws Exception {
        Sample query = new Sample("nonempty"); member(query.envelope, "recall_search").getJSONObject("payload").getJSONObject("query").put("offset", "10"); rejected(query);
        Sample total = new Sample("nonempty");
        member(total.envelope, "recall_search").getJSONObject("payload").getJSONObject("discovery").getJSONObject("pagination").put("total", 999);
        rejected(total);
        Sample leading = new Sample("nonempty"); member(leading.envelope, "recall_search").getJSONObject("payload").getJSONObject("query").put("offset", "00"); rejected(leading);
    }
    @Test public void emptyAndCandidateBoundariesCannotTurnIntoSafetyClaims() throws Exception {
        Sample empty = new Sample("empty"); member(empty.envelope, "recall_search").getJSONObject("payload").put("empty_observation", false); rejected(empty);
        Sample formal = new Sample("nonempty");
        member(formal.envelope, "recall_search").getJSONObject("payload").getJSONObject("boundary").put("formal_campaign_revision", true);
        rejected(formal);
        Sample applicability = new Sample("nonempty");
        member(applicability.envelope, "recall_search").getJSONObject("payload").getJSONObject("boundary").put("applicability", "not_applicable");
        rejected(applicability);
    }
    @Test public void productCountsAndDocumentFacetsStayBound() throws Exception {
        Sample count = new Sample("nonempty");
        member(count.envelope, "recall_search").getJSONObject("payload").getJSONObject("discovery").getJSONArray("products").getJSONObject(0).put("recalls_count", 100);
        rejected(count);
        Sample facets = new Sample("nonempty");
        JSONArray documents = facets.envelope.getJSONArray("documents");
        for (int at = 0; at < documents.length(); at++) {
            JSONObject document = documents.getJSONObject(at);
            if (document.getString("kind").equals("recall_search")) { document.getJSONObject("facets").put("model", "another product"); break; }
        }
        rejected(facets);
    }
    @Test public void versionTwoIntegersRetainPrecisionAndLegacyNumericGateStays() throws Exception {
        BigInteger integer = new BigInteger("1000000000000000000000000000000000000001");
        Sample newer = new Sample("nonempty");
        member(newer.envelope, "tire").getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").put("utqg_treadwear", integer);
        JSONObject parsed = OfflinePackageValidator.envelope(changedBytes(newer), newer.descriptor);
        assertEquals(integer, member(parsed, "tire").getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").get("utqg_treadwear"));
        Sample legacy = new Sample("legacy");
        member(legacy.envelope, "tire").getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").put("utqg_treadwear", integer);
        rejected(legacy);
    }
    @Test public void sourceIdentityAndUnknownPayloadFieldsFailClosed() throws Exception {
        Sample source = new Sample("nonempty"); member(source.envelope, "recall_search").getJSONObject("source").put("source_id", "other-source"); rejected(source);
        Sample extra = new Sample("nonempty"); member(extra.envelope, "recall_search").getJSONObject("payload").put("guessed_total", 100); rejected(extra);
    }
}
