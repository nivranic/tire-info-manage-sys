package org.taiji.tireintelligence.mobile;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.InputStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
import static org.junit.Assert.*;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Real producer preview admitted by the actual Android consumer before confirmation. */
@RunWith(AndroidJUnit4.class)
public final class OfflineSyncConsumerContractTest {
    private JSONObject asset(String name) throws Exception {
        try (InputStream input=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("device-sync48/"+name)) {
            return new JSONObject(new String(input.readAllBytes(),StandardCharsets.UTF_8));
        }
    }
    private JSONObject response() throws Exception {
        JSONObject plan=asset("producer-plan-real.json"), policy=asset("producer-policy-real.json"), base=asset("producer-base-real.json");
        // Keep the producer's explicit UTC offset and microsecond precision while making
        // this frozen contract sample independent of its original ten-minute expiry.
        plan.put("expires_at",java.time.OffsetDateTime.now(java.time.ZoneOffset.UTC).plusSeconds(600)
            .format(java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSSSSSxxx")));
        return new JSONObject().put("schema","offline-pack-update@1").put("state","planned").put("mode","history")
            .put("base_pack_id",base.getString("id")).put("base_semantic_digest","a".repeat(64)).put("current_semantic_digest","b".repeat(64))
            .put("base_pack",base).put("plan",plan).put("source_refresh_performed",false);
    }
    private void gate(JSONObject response) throws Exception {
        JSONObject policy=asset("producer-policy-real.json"),base=asset("producer-base-real.json");
        Method gate=OfflineSyncCoordinator.class.getDeclaredMethod("update",JSONObject.class,JSONObject.class,JSONObject.class);
        gate.setAccessible(true);
        try { gate.invoke(null,response,policy,base); }
        catch (InvocationTargetException failure) { throw new AssertionError("Actual producer plan rejected by Android consumer",failure.getCause()); }
    }
    @Test public void actualProducerPlanPassesAndroidConfirmationGate() throws Exception { gate(response()); }
    private void rejected(JSONObject response) throws Exception {
        try { gate(response); fail("Invalid full preview must be rejected before confirmation"); }
        catch(AssertionError failure){assertTrue(failure.getCause() instanceof NativeFailure);}
    }
    @Test public void missingResolvedIsRejectedBeforeConfirmation() throws Exception {
        JSONObject response=response();response.getJSONObject("plan").remove("resolved");rejected(response);
    }
    @Test public void missingDocumentsIsRejectedBeforeConfirmation() throws Exception {
        JSONObject response=response();response.getJSONObject("plan").remove("documents");rejected(response);
    }
    @Test public void missingContextsIsRejectedBeforeConfirmation() throws Exception {
        JSONObject response=response();response.getJSONObject("plan").remove("contexts");rejected(response);
    }
    @Test public void understatedEvidenceCountIsRejectedBeforeConfirmation() throws Exception {
        JSONObject response=response();response.getJSONObject("plan").getJSONObject("counts").put("distinct_evidence",0);rejected(response);
    }
    @Test public void understatedDocumentCountIsRejectedBeforeConfirmation() throws Exception {
        JSONObject response=response();response.getJSONObject("plan").getJSONObject("counts").put("searchable_documents",0);rejected(response);
    }
    @Test public void wrongContextKindIsRejectedBeforeConfirmation() throws Exception {
        JSONObject response=response();response.getJSONObject("plan").getJSONArray("contexts").getJSONObject(0).put("kind","watchlist");rejected(response);
    }
}
