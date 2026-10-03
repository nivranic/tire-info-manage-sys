package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.BeforeClass;
import org.junit.Test;

/** Object-level product rules on JDK/org.json. Does not verify Android JsonReader, IPC or Store. */
public final class OfflineRulesReferenceTest {
    private static final String PROFILE = "a".repeat(64), OWNER = "b".repeat(64), SHA = "c".repeat(64);
    private static final long WALL = Instant.parse("2026-10-01T08:00:00Z").toEpochMilli();
    private static final String CONFIGURED_ASSETS = System.getProperty("tire.test.assets");
    // Gradle's ordinary Test working directory is this app project.
    private static final Path REFERENCE_ASSETS = Path.of(CONFIGURED_ASSETS == null ? "src/androidTest/assets" : CONFIGURED_ASSETS).toAbsolutePath().normalize();
    @BeforeClass public static void referenceAssetsBinding() {
        assertTrue("Reference assets directory is missing: " + REFERENCE_ASSETS, Files.isDirectory(REFERENCE_ASSETS));
        System.out.println("OfflineRulesReferenceTest assets binding=" + (CONFIGURED_ASSETS == null ? "default" : "property") + "; path=" + REFERENCE_ASSETS);
    }
    private static JSONObject json(Object... pairs) throws Exception {
        JSONObject result = new JSONObject();
        for (int at = 0; at < pairs.length; at += 2) result.put((String) pairs[at], pairs[at + 1] == null ? JSONObject.NULL : pairs[at + 1]);
        return result;
    }
    private static byte[] bytes(String name) throws Exception {
        Path base = REFERENCE_ASSETS, target = base.resolve(name).normalize();
        assertTrue(target.startsWith(base)); return Files.readAllBytes(target);
    }
    private static JSONObject asset(String name) throws Exception {
        return new JSONObject(new String(bytes(name), StandardCharsets.UTF_8));
    }
    private interface Checked { void run() throws Exception; }
    private static void rejects(String code, Checked work) throws Exception {
        try { work.run(); fail("Expected " + code); }
        catch (NativeFailure expected) { assertEquals(code, expected.code); }
    }
    private static JSONObject pin() throws Exception {
        return json("source_id", "fixture", "access_generation", 0, "query_kinds", new JSONArray().put("tire"));
    }
    private static JSONObject authority(String runtime, boolean queryable) throws Exception {
        return json("schema", "device-fallback-source-authority@1", "runtime_session_id", runtime, "authority_revision", 1,
            "state", "last_observed", "observed_at", Instant.ofEpochMilli(WALL).toString(), "profile_id", PROFILE,
            "owner_epoch", 1, "owner_scope_id", OWNER, "sources", new JSONArray().put(pin().put("can_query", queryable).put("can_fetch", queryable)));
    }
    private static JSONObject intent(String kind, JSONObject query) throws Exception {
        return json("schema", "device-fallback-intent@2", "attempt_id", UUID.randomUUID().toString(), "query_fingerprint", SHA,
            "source_id", "fixture", "source_access_generation", 0, "authority", json("runtime_session_id", UUID.randomUUID().toString(), "authority_revision", 1),
            "fallback_policy", "ask", "failure", json("scope", "api_transport", "reason", "api_network_unavailable", "query_id", null),
            "query_kind", kind, "query", query, "filters", new JSONArray());
    }

    private static void oracle(String name, int expectedCases, int expectedRows) throws Exception {
        JSONObject reference = asset("query-filters49/" + name); JSONArray cases = reference.getJSONArray("cases");
        assertEquals(expectedCases, cases.length()); Set<String> fields = new HashSet<>(); int rowsChecked = 0, invalid = 0;
        for (int at = 0; at < cases.length(); at++) {
            JSONObject test = cases.getJSONObject(at); String id = test.getString("id");
            JSONArray draft = new JSONArray(test.getString("input_filters_json"));
            if (!test.isNull("validation_error")) {
                try { OfflineTireCriteria.validateFilters(draft); fail("Accepted invalid reference " + id); }
                catch (IllegalArgumentException expected) { invalid++; }
                continue;
            }
            OfflineTireCriteria.validateFilters(draft);
            JSONArray filters = OfflineTireCriteria.validateFilters(new JSONArray(test.getString("canonical_filters_json")));
            for (int index = 0; index < filters.length(); index++) fields.add(filters.getJSONObject(index).getString("field"));
            JSONArray rows = new JSONArray(test.getString("rows_json")), indexes = new JSONArray();
            int matched = 0, excluded = 0, unknown = 0;
            for (int index = 0; index < rows.length(); index++) {
                OfflineTireCriteria.Truth truth = OfflineTireCriteria.evaluate(rows.getJSONObject(index), filters);
                if (truth == OfflineTireCriteria.Truth.TRUE) { matched++; indexes.put(index); }
                else if (truth == OfflineTireCriteria.Truth.FALSE) excluded++; else unknown++;
                rowsChecked++;
            }
            JSONObject expected = test.getJSONObject("expected").getJSONObject("selection");
            assertEquals(id, test.getJSONObject("expected").getJSONArray("matched_row_indexes").toString(), indexes.toString());
            assertEquals(id, expected.getInt("source_count"), rows.length()); assertEquals(id, expected.getInt("matched_count"), matched);
            assertEquals(id, expected.getInt("excluded_count"), excluded); assertEquals(id, expected.getInt("undetermined_count"), unknown);
        }
        assertEquals(expectedRows, rowsChecked); assertTrue(invalid > 0);
        if (name.equals("reference.json")) assertEquals(28, fields.size());
        System.out.println(name + ": cases=" + cases.length() + ", compared_rows=" + rowsChecked + ", rejected=" + invalid);
    }
    @Test public void pythonPrimaryAllFieldOracle() throws Exception { oracle("reference.json", 242, 591); }
    @Test public void pythonUnicodeExtraOracle() throws Exception { oracle("extra.json", 14, 170); }
    @Test public void pythonNineBasicSizeCasesDoNotGainAdvancedNfkc() throws Exception {
        byte[] raw = bytes("query-filters49/basic-query-reference.json");
        assertEquals("6f24f172069cbdb94c660ab68584700a181cded81df88370e51012297a676cf6", OfflineCipher.sha256(raw));
        JSONArray cases = asset("query-filters49/basic-query-reference.json").getJSONArray("cases"); assertEquals(9, cases.length());
        for (int at = 0; at < cases.length(); at++) {
            JSONObject test = cases.getJSONObject(at), row = test.getJSONObject("row"); String size = test.getJSONObject("canonical_query").getString("size");
            assertEquals(size, OfflineFallbackValues.canonicalTireSize(test.getJSONObject("draft_query").getString("size")));
            assertEquals(test.isNull("basic_match") ? OfflineTireCriteria.Truth.UNKNOWN : test.getBoolean("basic_match") ? OfflineTireCriteria.Truth.TRUE : OfflineTireCriteria.Truth.FALSE,
                OfflineTireCriteria.evaluateBasicSize(row, size));
            assertEquals(test.isNull("advanced_match") ? OfflineTireCriteria.Truth.UNKNOWN : test.getBoolean("advanced_match") ? OfflineTireCriteria.Truth.TRUE : OfflineTireCriteria.Truth.FALSE,
                OfflineTireCriteria.evaluate(row, OfflineTireCriteria.validateFilters(new JSONArray().put(test.getJSONObject("advanced_filter")))));
        }
    }
    @Test public void exactIntegerKernelDoesNotRoundHugeCriterionOrCarrier() throws Exception {
        String huge = "1" + "0".repeat(309), next = huge.substring(0, huge.length() - 1) + "1";
        JSONObject row = new JSONObject("{\"facts\":{\"utqg_treadwear\":" + huge + "}}");
        JSONArray filters = OfflineTireCriteria.validateFilters(new JSONArray("[{\"field\":\"utqg_treadwear\",\"op\":\"eq\",\"value\":" + huge + "}]"));
        assertEquals(OfflineTireCriteria.Truth.TRUE, OfflineTireCriteria.evaluate(row, filters));
        assertTrue(OfflineJsonInteger.stringify(filters).contains(huge));
        row.getJSONObject("facts").put("utqg_treadwear", OfflineJsonInteger.jsonNumber(new java.math.BigInteger(next)));
        assertEquals(OfflineTireCriteria.Truth.FALSE, OfflineTireCriteria.evaluate(row, filters));
        assertFalse(OfflineFallbackValues.same(json("value", new java.math.BigInteger(huge)), json("value", new java.math.BigInteger(next))));
    }
    @Test public void scopeMatchPinsGenerationExceptLegacyNeverAndHashUsesCodepointOrder() throws Exception {
        JSONObject preference = json("mode", "never", "scope", pin().put("kind", "source"));
        JSONObject requested = intent("tire", json("size", "205/55R20")).put("source_access_generation", 99);
        assertFalse(OfflineFallbackValues.matches(preference, requested, false));
        assertTrue(OfflineFallbackValues.matches(preference, requested, true));
        assertEquals("Pilot Sport EV", OfflineFallbackValues.canonicalTireModel("  MICHELIN\u00a0pSeV  "));
        JSONObject unusual = json("\ud800\udc00", "slash/path", "\ue000", "é");
        String stable = "{\"\ue000\":\"é\",\"\ud800\udc00\":\"slash/path\"}";
        assertEquals(OfflineCipher.sha256(("device-fallback-approved-scope@1\0" + stable).getBytes(StandardCharsets.UTF_8)), OfflineFallbackValues.scopeFingerprint(unusual));
    }
    @Test public void originalProducerFourDomainsKeepFrozenReceiptsAndEmptyPage() throws Exception {
        for (String fixture : new String[]{"nonempty", "empty"}) {
            JSONObject descriptor = asset("offline-producer49/" + fixture + "-descriptor.json"); byte[] raw = bytes("offline-producer49/" + fixture + "-pack.json");
            assertEquals(descriptor.getString("sha256"), OfflineCipher.sha256(raw));
            // The frozen producer bytes are hashed, then decoded by the host JSON library.
            // Whole-package validation and the Android parser have separate native tests.
            JSONObject material = new JSONObject(new String(raw, StandardCharsets.UTF_8)); JSONArray members = material.getJSONArray("members");
            String[][] kinds = {{"tire", "tire"}, {"vehicle_fitments", "vehicle"}, {"recall_campaign", "recall"}, {"recall_search", "recall_search"}};
            for (String[] kind : kinds) {
                JSONObject member = null;
                for (int at = 0; at < members.length(); at++) if (kind[1].equals(members.getJSONObject(at).getJSONObject("reference").getString("kind"))) { member = members.getJSONObject(at); break; }
                assertNotNull(member); JSONObject payload = member.getJSONObject("payload"), query;
                if (kind[0].equals("tire")) query = json("model", payload.getJSONObject("variant").getString("model"));
                else if (kind[0].equals("vehicle_fitments")) query = json("vehicle_id", payload.getJSONObject("vehicle").getString("id"));
                else if (kind[0].equals("recall_campaign")) query = json("campaign_number", payload.getJSONObject("evidence").getString("campaign_number"));
                else query = new JSONObject(payload.getJSONObject("query").toString());
                JSONObject request = intent(kind[0], query).put("source_id", member.getJSONObject("source").getString("source_id"));
                JSONObject selected = OfflineFallbackSelection.select(material, request);
                assertTrue(selected.getJSONArray("members").length() > 0);
                if (fixture.equals("empty") && kind[0].equals("recall_search")) {
                    assertTrue(selected.getJSONArray("members").getJSONObject(0).getJSONObject("payload").getBoolean("empty_observation"));
                    request.getJSONObject("query").put("offset", query.getString("offset").equals("0") ? "10" : "0");
                    assertEquals(0, OfflineFallbackSelection.select(material, request).getJSONArray("members").length());
                }
            }
        }
    }
    private static JSONObject preferencePolicy(JSONObject observed, String scope, String state, long time) throws Exception {
        JSONObject choice = json("mode", "never", "scope", scope.equals("session") ? json("kind", "session", "sources", new JSONArray().put(pin())) : pin().put("kind", "source"),
            "binding", null, "allow_same_scope_sync_binding_advance", false);
        return choice.put("schema", "device-fallback-policy@1").put("policy_id", UUID.randomUUID().toString()).put("policy_revision", 1)
            .put("state", state).put("profile_id", PROFILE).put("owner_epoch", 1).put("owner_scope_id", OWNER)
            .put("runtime_session_id", scope.equals("session") ? observed.getString("runtime_session_id") : JSONObject.NULL)
            .put("approved_at", OfflineFallbackJournal.stamp(time)).put("updated_at", OfflineFallbackJournal.stamp(time))
            .put("expires_at", OfflineFallbackJournal.stamp(WALL + 86400000)).put("fingerprint", SHA).put("reason", JSONObject.NULL);
    }
    @Test public void journalKeepsSixteenNonrevokedAndOnlyPrunesOldRevoked() throws Exception {
        JSONObject observed = authority(UUID.randomUUID().toString(), true), state = OfflineFallbackJournal.empty(PROFILE, 1, WALL);
        JSONObject oldest = null;
        for (int at = 0; at < 64; at++) {
            JSONObject policy = preferencePolicy(observed, "source", "revoked", WALL + at);
            if (at == 0) oldest = policy; state.getJSONArray("policies").put(json("policy", policy, "approval_authority", observed));
        }
        JSONObject enabled = preferencePolicy(observed, "source", "enabled", WALL + 64);
        state.getJSONArray("policies").put(json("policy", enabled, "approval_authority", observed)); OfflineFallbackJournal.compact(state);
        assertEquals(64, state.getJSONArray("policies").length()); assertNull(OfflineFallbackJournal.entry(state, oldest.getString("policy_id")));
        for (int at = 0; at < 15; at++) state.getJSONArray("policies").put(json("policy", preferencePolicy(observed, "source", "paused", WALL + 65 + at), "approval_authority", observed));
        OfflineFallbackJournal.compact(state);
        state.getJSONArray("policies").put(json("policy", preferencePolicy(observed, "source", "enabled", WALL + 81), "approval_authority", observed));
        rejects("OFFLINE_FALLBACK_POLICY_CAPACITY", () -> OfflineFallbackJournal.compact(state));
    }
    @Test public void coldRestartPausesSessionScopeAndOwnerChangeRevokesRetainedPolicies() throws Exception {
        JSONObject observed = authority(UUID.randomUUID().toString(), true), state = OfflineFallbackJournal.empty(PROFILE, 1, WALL);
        JSONObject session = preferencePolicy(observed, "session", "enabled", WALL), source = preferencePolicy(observed, "source", "enabled", WALL);
        state.getJSONArray("policies").put(json("policy", session, "approval_authority", observed)).put(json("policy", source, "approval_authority", observed));
        JSONObject cold = authority(UUID.randomUUID().toString(), true).put("state", "unknown").put("observed_at", JSONObject.NULL)
            .put("owner_scope_id", JSONObject.NULL).put("sources", new JSONArray());
        OfflineFallbackJournal.reconcile(state, cold, WALL + 1);
        assertEquals("paused", OfflineFallbackJournal.entry(state, session.getString("policy_id")).getJSONObject("policy").getString("state"));
        assertEquals("enabled", OfflineFallbackJournal.entry(state, source.getString("policy_id")).getJSONObject("policy").getString("state"));
        OfflineFallbackJournal.reconcile(state, cold.put("owner_epoch", 2), WALL + 2);
        assertEquals("revoked", OfflineFallbackJournal.entry(state, source.getString("policy_id")).getJSONObject("policy").getString("state"));
        assertEquals("revoked", OfflineFallbackJournal.entry(state, session.getString("policy_id")).getJSONObject("policy").getString("state"));
    }
}
