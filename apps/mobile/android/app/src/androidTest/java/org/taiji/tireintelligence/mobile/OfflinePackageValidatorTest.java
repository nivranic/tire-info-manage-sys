package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public final class OfflinePackageValidatorTest {
    private interface Checked { void run() throws Exception; }
    private static void invalid(Checked action) throws Exception {
        try { action.run(); fail("Expected rejected frozen package"); }
        catch (NativeFailure failure) { assertEquals("OFFLINE_PACKAGE_INVALID", failure.code); }
    }
    static byte[] asset(String name) throws Exception {
        assertTrue(InstrumentationRegistry.getInstrumentation().getTargetContext().getPackageName().endsWith(".offlineqa"));
        try (InputStream input = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("offline-producer-v2/" + name)) {
            return input.readAllBytes();
        }
    }
    private static JSONObject descriptor() throws Exception { return OfflinePackageValidator.parse(asset("valid-descriptor.json")); }
    private static JSONObject request(JSONObject descriptor) throws Exception {
        return new JSONObject().put("package_id", descriptor.getString("id"))
            .put("expected_sha256", descriptor.getString("sha256")).put("expected_byte_count", descriptor.getLong("byte_count"))
            .put("approved_plan_fingerprint", descriptor.getString("plan_fingerprint"))
            .put("slot_id", UUID.randomUUID().toString()).put("expected_generation", 0).put("allow_device_storage", true);
    }
    private static void invalidEnvelope(JSONObject envelope) throws Exception {
        byte[] bytes = envelope.toString().getBytes(StandardCharsets.UTF_8);
        JSONObject descriptor = descriptor().put("sha256", OfflineCipher.sha256(bytes)).put("byte_count", bytes.length);
        invalid(() -> OfflinePackageValidator.envelope(bytes, descriptor));
    }
    @Test public void exactProducerBytesKeepFourDomainsRevisionOriginAndPrivateContexts() throws Exception {
        byte[] bytes = asset("valid-envelope.json"); JSONObject descriptor = descriptor(); JSONObject request = request(descriptor);
        assertEquals(80152, bytes.length); assertEquals("0076612dde0739fa4f3f1ea22514d102e4d6bc5204f823dbc0ae3e56821fb014", OfflineCipher.sha256(bytes));
        OfflinePackageValidator.installRequest(request); OfflinePackageValidator.descriptor(descriptor, request);
        JSONObject envelope = OfflinePackageValidator.envelope(bytes, descriptor);
        assertEquals(5, envelope.getJSONArray("members").length()); assertEquals(9, envelope.getJSONArray("documents").length());
        assertEquals(2, envelope.getJSONArray("contexts").length());
    }
    @Test public void malformedTransportBindingStorageConsentAndBooleanNumbersAreRejected() throws Exception {
        JSONObject descriptor = descriptor(), request = request(descriptor);
        invalid(() -> OfflinePackageValidator.installRequest(new JSONObject(request.toString()).put("allow_device_storage", 1)));
        invalid(() -> OfflinePackageValidator.installRequest(new JSONObject(request.toString()).put("expected_generation", true)));
        invalid(() -> OfflinePackageValidator.installRequest(new JSONObject(request.toString()).put("expected_generation", 0.0)));
        invalid(() -> OfflinePackageValidator.descriptor(new JSONObject(descriptor.toString()).put("sha256", "0".repeat(64)), request));
        byte[] damaged = asset("valid-envelope.json"); damaged[damaged.length - 1] ^= 1;
        invalid(() -> OfflinePackageValidator.envelope(damaged, descriptor));
    }
    @Test public void duplicateKeysCredentialsBomAndDeepTreesFailBeforeMaterialization() throws Exception {
        for (String raw : new String[]{"{\"schema\":1,\"schema\":2}", "{\"nested\":{\"AUTHORIZATION\":\"synthetic\"}}", "\uFEFF{}", "{\"x\":".repeat(35) + "{}" + "}".repeat(35)}) {
            invalid(() -> OfflinePackageValidator.parse(raw.getBytes(StandardCharsets.UTF_8)));
        }
    }
    @Test public void unknownSchemaUnexpectedKeysRawMaterialAndFalseFreshnessAreRejected() throws Exception {
        JSONObject source = OfflinePackageValidator.parse(asset("valid-envelope.json"));
        invalidEnvelope(new JSONObject(source.toString()).put("schema", "offline-pack@2"));
        invalidEnvelope(new JSONObject(source.toString()).put("raw_body", "synthetic forbidden full body"));
        invalidEnvelope(new JSONObject(source.toString()).put("source_refresh_performed", true));
        invalidEnvelope(new JSONObject(source.toString()).put("unknown", 1));
    }
    @Test public void recallAndTestParticipantFacetsCannotCrossRecords() throws Exception {
        for (String kind : new String[]{"recall", "test_event"}) {
            JSONObject envelope = OfflinePackageValidator.parse(asset("valid-envelope.json"));
            JSONArray docs = envelope.getJSONArray("documents");
            boolean mutated = false;
            for (int i = 0; i < docs.length(); i++) {
                JSONObject doc = docs.getJSONObject(i);
                if (kind.equals(doc.getString("kind")) && !doc.isNull("record_index")) {
                    doc.getJSONObject("facets").put("brand", "synthetic other record brand"); mutated = true; break;
                }
            }
            assertTrue(mutated); invalidEnvelope(envelope);
        }
    }
    @Test public void documentDanglingBindingsAndWrongCountsAreRejected() throws Exception {
        JSONObject envelope = OfflinePackageValidator.parse(asset("valid-envelope.json"));
        envelope.getJSONArray("documents").getJSONObject(0).put("member_key", "0".repeat(64)); invalidEnvelope(envelope);
        JSONObject descriptor = descriptor(); descriptor.getJSONObject("counts").put("searchable_documents", 8);
        invalid(() -> OfflinePackageValidator.envelope(asset("valid-envelope.json"), descriptor));
    }
}
