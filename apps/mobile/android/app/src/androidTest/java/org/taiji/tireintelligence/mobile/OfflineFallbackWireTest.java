package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.getcapacitor.JSObject;
import java.math.BigInteger;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Tests transport only; strict domain/owner/policy admission is a separate gate. */
@RunWith(AndroidJUnit4.class)
public final class OfflineFallbackWireTest {
    private static JSONObject core(String raw) throws Exception { return (JSONObject) OfflineTireCriteria.parse(raw); }
    private static void rejected(JSONObject wire) throws Exception {
        try { OfflineFallbackWire.decode(wire); fail("Malformed mirror/raw transport accepted"); }
        catch (NativeFailure expected) { assertEquals("OFFLINE_FALLBACK_INVALID", expected.code); }
    }
    @Test public void nativeJSONObjectRoundtripPreservesIntegersAndFloatingSemantics() throws Exception {
        JSONObject raw = core("{\"schema\":\"device-fallback-result@2\",\"generation\":1,\"numbers\":{"
            + "\"above_safe\":9007199254740993,\"above_long\":1000000000000000000000000000000000000001,"
            + "\"tiny\":5e-324,\"fraction\":0.1,\"integral_float\":1e23,\"zero\":-0.0}}");
        JSONObject wire = JSObject.fromJSONObject(OfflineFallbackWire.encode(raw));
        wire = new JSObject(wire.toString());
        JSONObject decoded = OfflineFallbackWire.decode(wire), numbers = decoded.getJSONObject("numbers");
        assertEquals(9007199254740993L, ((Number) numbers.get("above_safe")).longValue());
        assertEquals(new BigInteger("1000000000000000000000000000000000000001"), numbers.get("above_long"));
        assertEquals(Double.MIN_VALUE, numbers.getDouble("tiny"), 0);
        assertEquals(0.1, numbers.getDouble("fraction"), 0);
        assertEquals(1e23, numbers.getDouble("integral_float"), 0);
        assertEquals(0, numbers.getDouble("zero"), 0);
        assertTrue("Bounded integer metadata remains compatible with strict host DTO", decoded.get("generation") instanceof Long);
    }
    @Test public void integerAboveFiniteJsRangeUsesOnlyDeterministicNullMirror() throws Exception {
        BigInteger integer = new BigInteger("1" + "0".repeat(310) + "1");
        JSONObject raw = core("{\"value\":" + integer.toString() + "}");
        JSONObject wire = JSObject.fromJSONObject(OfflineFallbackWire.encode(raw));
        assertTrue(wire.isNull("value"));
        assertEquals(integer, OfflineJsonInteger.integer(OfflineFallbackWire.decode(wire).get("value")));
        wire.put("value", 0); rejected(wire);
        JSONObject metadata = OfflineFallbackWire.encode(new JSONObject().put("owner_epoch", 0));
        metadata.put("owner_epoch", JSONObject.NULL); rejected(metadata);
    }
    @Test public void wrongMirrorsTypesKeysAndStructureRejectBeforeBusinessUse() throws Exception {
        JSONObject number = OfflineFallbackWire.encode(core("{\"value\":9007199254740993}"));
        number.put("value", 9007199254740993L); rejected(number); // Expected JS projection is 9007199254740992.
        JSONObject type = OfflineFallbackWire.encode(core("{\"value\":1}")); type.put("value", "1"); rejected(type);
        JSONObject string = OfflineFallbackWire.encode(core("{\"source_id\":\"nhtsa-us-recalls\"}"));
        string.put("source_id", "other-source"); rejected(string);
        JSONObject extra = OfflineFallbackWire.encode(core("{\"value\":1}")); extra.put("extra", true); rejected(extra);
        JSONObject missing = OfflineFallbackWire.encode(core("{\"value\":1}")); missing.remove("value"); rejected(missing);
    }
    @Test public void duplicateSurrogateNonfiniteAndRecursiveProtocolRawReject() throws Exception {
        for (String bad : new String[]{"{\"value\":1,\"value\":2}", "{\"value\":\"\\ud800\"}",
                "{\"value\":1e400}", "{\"raw_json\":\"x\"}", "{\"intent\":{\"raw_json\":\"x\"}}", "{} {}"}) {
            rejected(new JSONObject().put("value", 1).put("raw_json", bad));
        }
        JSONObject facts = core("{\"members\":[{\"payload\":{\"facts\":{\"raw_json\":\"ordinary fact\"}}}]}");
        assertEquals("ordinary fact", OfflineFallbackWire.decode(OfflineFallbackWire.encode(facts))
            .getJSONArray("members").getJSONObject(0).getJSONObject("payload").getJSONObject("facts").getString("raw_json"));
    }
    @Test public void rawCoreLimitAndExcessiveDepthStayBounded() throws Exception {
        JSONObject oversized = new JSONObject().put("raw_json", " ".repeat(OfflineFallbackWire.MAX_CORE_BYTES + 1));
        rejected(oversized);
        String deep = "[".repeat(34) + "0" + "]".repeat(34);
        rejected(new JSONObject().put("value", 1).put("raw_json", "{\"value\":" + deep + "}"));
        assertEquals(8 * 1024 * 1024, OfflineFallbackWire.MAX_CORE_BYTES);
        assertEquals(32 * 1024 * 1024, OfflineFallbackWire.MAX_TRANSPORT_BYTES);
    }
}
