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

/** Closed values and source oracle transport; no network, grant, or policy ownership claims. */
@RunWith(AndroidJUnit4.class)
public final class OfflineFallbackValuesTest {
    private static final String HASH = "a".repeat(64);
    private static JSONObject parse(String text) throws Exception { return (JSONObject) OfflineTireCriteria.parse(text); }
    private static JSONObject clone(JSONObject value) throws Exception { return parse(OfflineJsonInteger.stringify(value)); }
    private static JSONObject asset(String path) throws Exception {
        try (InputStream stream = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(path)) {
            return parse(new String(stream.readAllBytes(), StandardCharsets.UTF_8));
        }
    }
    private static JSONObject intent(String kind, JSONObject query) throws Exception {
        return new JSONObject().put("schema", "device-fallback-intent@2").put("attempt_id", UUID.randomUUID().toString())
            .put("query_fingerprint", HASH).put("source_id", "fixture").put("source_access_generation", 0)
            .put("authority", new JSONObject().put("runtime_session_id", UUID.randomUUID().toString()).put("authority_revision", 1))
            .put("fallback_policy", "ask").put("failure", new JSONObject().put("scope", "api_transport")
                .put("reason", "api_network_unavailable").put("query_id", JSONObject.NULL))
            .put("query_kind", kind).put("query", query).put("filters", new JSONArray());
    }
    private static JSONObject pin(String id, long generation) throws Exception {
        return new JSONObject().put("source_id", id).put("access_generation", generation).put("query_kinds", new JSONArray().put("tire"));
    }
    private static JSONObject authority(boolean enabled) throws Exception {
        JSONObject row = pin("fixture", 0).put("can_query", enabled).put("can_fetch", enabled);
        return new JSONObject().put("schema", "device-fallback-source-authority@1").put("runtime_session_id", UUID.randomUUID().toString())
            .put("authority_revision", 1).put("state", "last_observed").put("observed_at", "2026-10-01T08:00:00Z")
            .put("profile_id", UUID.randomUUID().toString()).put("owner_epoch", 0).put("owner_scope_id", HASH)
            .put("sources", new JSONArray().put(row));
    }
    private static JSONObject choice(String mode) throws Exception {
        return new JSONObject().put("mode", mode).put("scope", pin("fixture", 0).put("kind", "source"))
            .put("binding", JSONObject.NULL).put("allow_same_scope_sync_binding_advance", false);
    }
    private static JSONObject binding() throws Exception {
        return new JSONObject().put("binding_revision", 1).put("slot_id", UUID.randomUUID().toString()).put("generation", 1)
            .put("package_id", UUID.randomUUID().toString()).put("sha256", HASH).put("history_scope_fingerprint", HASH)
            .put("source_ids", new JSONArray().put("fixture"));
    }
    private interface Action { void run() throws Exception; }
    private static void rejected(Action action) throws Exception {
        try { action.run(); fail("Invalid value accepted"); }
        catch (NativeFailure failure) { assertEquals("OFFLINE_FALLBACK_INVALID", failure.code); }
    }

    @Test public void fourCanonicalQueryKindsAndClosedFailureShapes() throws Exception {
        JSONObject[] requests = {
            intent("tire", new JSONObject().put("model", "Pilot Sport EV").put("size", "245/40R20")),
            intent("vehicle_fitments", new JSONObject().put("vehicle_id", "Case  sensitive ID")),
            intent("recall_campaign", new JSONObject().put("campaign_number", "23T001000")),
            intent("recall_search", new JSONObject().put("search", "Exact Search").put("offset", "10000"))
        };
        for (JSONObject request : requests) assertTrue(OfflineFallbackValues.same(request, OfflineFallbackValues.validateIntent(request)));
        JSONObject sourceFailure = clone(requests[0]).put("failure", new JSONObject().put("scope", "source_response")
            .put("reason", "upstream_timeout").put("query_id", UUID.randomUUID().toString()));
        OfflineFallbackValues.validateIntent(sourceFailure);
        rejected(() -> OfflineFallbackValues.validateIntent(clone(sourceFailure).put("unexpected", true)));
        rejected(() -> OfflineFallbackValues.validateIntent(clone(sourceFailure).put("schema", "device-fallback-intent@3")));
        rejected(() -> OfflineFallbackValues.validateIntent(clone(sourceFailure).put("failure", new JSONObject().put("scope", "source_response")
            .put("reason", "api_timeout").put("query_id", UUID.randomUUID().toString()))));
        rejected(() -> OfflineFallbackValues.validateIntent(clone(requests[3]).put("query", new JSONObject().put("search", "Exact Search").put("offset", "01"))));
        rejected(() -> OfflineFallbackValues.validateIntent(clone(requests[1]).put("filters", new JSONArray().put(new JSONObject().put("field", "model").put("op", "is_known")))));
    }

    @Test public void rawBasicSizeAndAliasesPreservePythonSpelling() throws Exception {
        assertEquals("Pilot Sport EV", OfflineFallbackValues.canonicalTireModel("  MICHELIN\u00a0pSeV  "));
        assertEquals("Pilot Sport 4 S", OfflineFallbackValues.canonicalTireModel("ps4s"));
        assertEquals("245/40R٢٠", OfflineFallbackValues.canonicalTireSize("٢٤٥ / ٤٠ r ٢٠"));
        assertEquals("245/40R２０", OfflineFallbackValues.canonicalTireSize("２４５/４０R２０"));
        assertEquals("245/40R20.5", OfflineFallbackValues.canonicalTireSize("245/40r20.5"));
        rejected(() -> OfflineFallbackValues.canonicalTireSize("２４５／４０Ｒ２０"));
        rejected(() -> OfflineFallbackValues.canonicalTireSize("245/40R20.５"));
        rejected(() -> OfflineFallbackValues.validateIntent(intent("tire", new JSONObject().put("model", "psev"))));
        OfflineFallbackValues.validateIntent(intent("tire", new JSONObject().put("size", "245/40R２０")));
    }

    @Test public void primaryAndExtraCanonicalOracleConditionsSurviveIntentCopyExactly() throws Exception {
        int count = 0;
        for (String file : new String[]{"reference.json", "extra.json"}) {
            JSONArray cases = asset("query-filters49/" + file).getJSONArray("cases");
            for (int at = 0; at < cases.length(); at++) {
                JSONObject test = cases.getJSONObject(at); if (!test.isNull("validation_error")) continue;
                JSONArray filters = (JSONArray) OfflineTireCriteria.parse(test.getString("canonical_filters_json"));
                JSONObject input = intent("tire", new JSONObject().put("model", "Pilot Sport EV")).put("filters", filters);
                JSONObject output = OfflineFallbackValues.validateIntent(input);
                assertTrue(test.getString("id"), OfflineFallbackValues.same(input, output));
                assertEquals(test.getString("id"), OfflineJsonInteger.stringify(filters), OfflineJsonInteger.stringify(output.getJSONArray("filters")));
                count++;
            }
        }
        assertTrue(count > 100);
    }

    @Test public void hugeIntegerEqualityDoesNotRoundThroughDouble() throws Exception {
        String huge = "1" + "0".repeat(309);
        JSONObject input = intent("tire", new JSONObject().put("size", "245/40R20"));
        input.put("filters", OfflineTireCriteria.parse("[{\"field\":\"utqg_treadwear\",\"op\":\"eq\",\"value\":" + huge + "}]"));
        assertTrue(OfflineJsonInteger.stringify(OfflineFallbackValues.validateIntent(input)).contains(huge));
        assertFalse(OfflineFallbackValues.same(parse("{\"value\":9007199254740993}"), parse("{\"value\":9007199254740992.0}")));
        assertFalse(OfflineFallbackValues.same(parse("{\"value\":100000000000000000000000}"), parse("{\"value\":1e23}")));
        assertTrue(OfflineFallbackValues.same(parse("{\"value\":1}"), parse("{\"value\":1.0}")));
        assertFalse(OfflineFallbackValues.same(parse("{\"value\":true}"), parse("{\"value\":1}")));
        assertFalse(OfflineFallbackValues.same(parse("{\"value\":[1,2]}"), parse("{\"value\":[2,1]}")));
    }

    @Test public void preferencesCanUseRegisteredDisabledZeroPinSourcesButAllowCannot() throws Exception {
        OfflineFallbackValues.validateChoice(authority(false), choice("ask"));
        OfflineFallbackValues.validateChoice(authority(false), choice("never"));
        JSONObject allow = choice("source_allow").put("binding", binding());
        rejected(() -> OfflineFallbackValues.validateChoice(authority(false), allow));
        OfflineFallbackValues.validateChoice(authority(true), allow);
        JSONObject badPin = choice("never"); badPin.getJSONObject("scope").put("access_generation", 1);
        rejected(() -> OfflineFallbackValues.validateChoice(authority(true), badPin));
        rejected(() -> OfflineFallbackValues.validateChoice(authority(true), choice("never").put("allow_same_scope_sync_binding_advance", true)));
        rejected(() -> OfflineFallbackValues.validateChoice(authority(true), choice("ask").put("binding", binding())));
    }

    @Test public void catalogTwoHundredIsIndependentFromWhitelistTenAndAdvanceNeedsEverySource() throws Exception {
        JSONObject observed = authority(true); JSONArray catalog = observed.getJSONArray("sources");
        for (int at = 1; at < 200; at++) catalog.put(pin("registered-" + at, 0).put("can_query", false).put("can_fetch", false));
        OfflineFallbackValues.validateChoice(observed, choice("never"));
        catalog.put(pin("registered-overflow", 0).put("can_query", false).put("can_fetch", false));
        rejected(() -> OfflineFallbackValues.validateChoice(observed, choice("never")));
        JSONObject session = choice("ask").put("scope", new JSONObject().put("kind", "session").put("sources", new JSONArray()));
        for (int at = 0; at < 11; at++) session.getJSONObject("scope").getJSONArray("sources").put(pin("registered-" + at, 0));
        rejected(() -> OfflineFallbackValues.validateChoice(authority(true), session));
        JSONObject allow = choice("source_allow").put("binding", binding()).put("allow_same_scope_sync_binding_advance", true);
        allow.getJSONObject("binding").getJSONArray("source_ids").put("synthetic-oem");
        try { OfflineFallbackValues.validateChoice(authority(true), allow); fail("Partial whitelist advanced multisource binding"); }
        catch (NativeFailure expected) { assertEquals("OFFLINE_FALLBACK_SYNC_ADVANCE_SCOPE_UNAVAILABLE", expected.code); }
    }

    @Test public void legacyNeverIgnoresCallerGenerationAndScopeKindsRemainPinned() throws Exception {
        JSONObject policy = choice("never"), request = intent("tire", new JSONObject().put("size", "245/40R20"));
        request.put("source_access_generation", 9);
        assertFalse(OfflineFallbackValues.matches(policy, request, false));
        assertTrue(OfflineFallbackValues.matches(policy, request, true));
        request.put("source_id", "other"); assertFalse(OfflineFallbackValues.matches(policy, request, true));
        JSONObject query = choice("never").put("scope", new JSONObject().put("kind", "query").put("query_kind", "tire")
            .put("sources", new JSONArray().put(new JSONObject().put("source_id", "fixture").put("access_generation", 0))));
        request.put("source_id", "fixture").put("source_access_generation", 0).put("query_kind", "recall_search");
        assertFalse(OfflineFallbackValues.matches(query, request, false));
    }

    @Test public void exactRequestShapesAndSafeMetadataBounds() throws Exception {
        JSONObject request = new JSONObject().put("intent", intent("tire", new JSONObject().put("size", "245/40R20")))
            .put("slot_id", UUID.randomUUID().toString()).put("expected_generation", 1).put("expected_sha256", HASH)
            .put("expected_profile_id", UUID.randomUUID().toString()).put("expected_owner_epoch", 0);
        OfflineFallbackValues.slotRequest(request, false);
        rejected(() -> OfflineFallbackValues.slotRequest(request, true));
        request.put("decision", "allow"); OfflineFallbackValues.slotRequest(request, true);
        rejected(() -> OfflineFallbackValues.slotRequest(request, false));
        request.put("expected_generation", 0); rejected(() -> OfflineFallbackValues.slotRequest(request, true));
        JSONObject tooBig = intent("tire", new JSONObject().put("size", "245/40R20")).put("source_access_generation", 9007199254740991L);
        rejected(() -> OfflineFallbackValues.validateIntent(tooBig));
    }

    @Test public void originalApprovedScopeFingerprintUsesStableCodepointOrderAndUnescapedSlash() throws Exception {
        JSONObject pack = asset("offline-producer49/nonempty-pack.json"); JSONObject original = pack.getJSONObject("scope");
        JSONObject reordered = new JSONObject(); java.util.List<String> keys = new java.util.ArrayList<>(); original.keys().forEachRemaining(keys::add);
        java.util.Collections.reverse(keys); for (String key : keys) reordered.put(key, original.get(key));
        assertEquals(OfflineFallbackValues.scopeFingerprint(original), OfflineFallbackValues.scopeFingerprint(reordered));
        JSONObject unusual = new JSONObject().put("\ud800\udc00", "slash/path").put("\ue000", "é");
        String stable = "{\"\ue000\":\"é\",\"\ud800\udc00\":\"slash/path\"}";
        assertEquals(OfflineCipher.sha256(("device-fallback-approved-scope@1\0" + stable).getBytes(StandardCharsets.UTF_8)),
            OfflineFallbackValues.scopeFingerprint(unusual));
        reordered.put("changed", true); assertNotEquals(OfflineFallbackValues.scopeFingerprint(original), OfflineFallbackValues.scopeFingerprint(reordered));
    }
}
