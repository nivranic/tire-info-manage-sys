package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.sqlite.SQLiteConnection;
import androidx.sqlite.SQLiteStatement;
import androidx.sqlite.driver.bundled.BundledSQLiteDriver;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.InputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Real Android Keystore and bundled SQLite policy metadata, with fixed loopback HTTP fixtures.
 * Every harness owns a fresh random QA profile. Profiles and keys are deliberately retained.
 * These tests exercise the Store with exact original producer payloads. They are source-only
 * until the root agent runs the dedicated instrumentation application; no real backend is used.
 */
@RunWith(AndroidJUnit4.class)
public final class OfflineFallbackV2StoreTest {
    private interface Checked { void run() throws Exception; }
    private static void fails(String code, Checked action) throws Exception {
        try { action.run(); fail("Expected " + code); }
        catch (NativeFailure failure) { assertEquals(code, failure.code); }
    }
    private static JSONObject json(Object... values) throws Exception {
        JSONObject result = new JSONObject();
        for (int at = 0; at < values.length; at += 2)
            result.put((String) values[at], values[at + 1] == null ? JSONObject.NULL : values[at + 1]);
        return result;
    }
    private static JSONObject copy(JSONObject value) throws Exception {
        return (JSONObject) OfflineTireCriteria.parse(OfflineJsonInteger.stringify(value), 2 * 1024 * 1024, 250000);
    }
    private static byte[] asset(String path) throws Exception {
        try (InputStream stream = InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(path)) {
            return stream.readAllBytes();
        }
    }
    private static final class Sample {
        final byte[] bytes;
        final JSONObject descriptor, material;
        Sample(String prefix) throws Exception {
            bytes = asset("offline-producer49/" + prefix + "-pack.json");
            descriptor = OfflinePackageValidator.response(asset("offline-producer49/" + prefix + "-descriptor.json"));
            assertEquals("Original producer bytes", descriptor.getString("sha256"), OfflineCipher.sha256(bytes));
            assertEquals(descriptor.getLong("byte_count"), bytes.length);
            material = OfflinePackageValidator.envelope(bytes, descriptor);
        }
    }
    private static final class Clock implements OfflineFallbackGrant.Clock {
        long wall = System.currentTimeMillis(), mono = android.os.SystemClock.elapsedRealtime();
        public long wall() { return wall; }
        public long monotonic() { return mono; }
        void advance(long millis) { wall += millis; mono += millis; }
    }
    private static final class MemorySession implements SessionState.Store {
        String cookie;
        public String load() { return cookie; }
        public void save(String value) { cookie = value; }
        public void delete() { cookie = null; }
    }
    private static JSONObject queryScope(String source) throws Exception {
        return json("kind", "query", "query_kind", "tire", "sources", new JSONArray().put(json("source_id", source, "access_generation", 0)));
    }
    private static JSONObject sourceScope() throws Exception {
        return json("kind", "source", "source_id", "fixture", "access_generation", 0, "query_kinds", new JSONArray().put("tire"));
    }
    private static JSONObject sessionScope() throws Exception {
        return json("kind", "session", "sources", new JSONArray().put(json("source_id", "fixture", "access_generation", 0,
            "query_kinds", new JSONArray().put("tire"))));
    }
    private static JSONObject source(JSONObject authority, String id) throws Exception {
        JSONArray sources = authority.getJSONArray("sources");
        for (int at = 0; at < sources.length(); at++)
            if (id.equals(sources.getJSONObject(at).getString("source_id"))) return sources.getJSONObject(at);
        throw new AssertionError("Missing explicit synthetic source " + id);
    }
    private static final class Harness implements AutoCloseable {
        final Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        final String namespace = "qa-r49-policy-" + UUID.randomUUID();
        final Clock clock = new Clock();
        final MockWebServer server = new MockWebServer();
        final NativeHttpBridge http;
        OfflinePackStore store;
        JSONObject installed;
        Sample sample;
        Harness() throws Exception {
            assertTrue("Only the dedicated QA application may run these tests", context.getPackageName().endsWith(".offlineqa"));
            store = new OfflinePackStore(context, namespace, clock);
            server.start(java.net.InetAddress.getByName("127.0.0.1"), 0);
            server.enqueue(new MockResponse().setBody("{}").addHeader("Set-Cookie",
                "tire_local_session=" + UUID.randomUUID() + "; HttpOnly; Path=/; SameSite=Strict"));
            http = new NativeHttpBridge("http://127.0.0.1:" + server.getPort(), new MemorySession());
        }
        void install(String prefix) throws Exception {
            sample = new Sample(prefix);
            installed = store.install(json("package_id", sample.descriptor.getString("id"),
                "expected_sha256", sample.descriptor.getString("sha256"), "expected_byte_count", sample.bytes.length,
                "approved_plan_fingerprint", sample.descriptor.getString("plan_fingerprint"),
                "slot_id", UUID.randomUUID().toString(), "expected_generation", 0, "allow_device_storage", true),
                sample.descriptor, sample.bytes);
        }
        JSONObject refresh() throws Exception { return refresh(true); }
        JSONObject refresh(boolean fixtureCanFetch) throws Exception {
            JSONObject settings = OfflinePackageValidator.response(asset("source-authority49/source-settings.json"));
            JSONObject directory = OfflinePackageValidator.response(asset("source-authority49/sources.json"));
            JSONArray items = settings.getJSONArray("items"); JSONObject tire = null, vehicle = null;
            for (int at = 0; at < items.length(); at++) {
                JSONObject row = items.getJSONObject(at);
                if (tire == null && row.getString("target_kind").equals("tire") && row.getBoolean("can_fetch")) tire = copy(row);
                if (row.getString("source_id").equals("xiaomi-cn-vehicles")) vehicle = copy(row);
            }
            assertNotNull(tire); assertNotNull(vehicle);
            tire.put("source_id", "fixture").put("name", "Explicit synthetic tire policy fixture")
                .put("source_class", "test_fixture").put("supported_models", new JSONArray().put("Fixture Tire"))
                .put("can_fetch", fixtureCanFetch).put("effective_status", fixtureCanFetch ? "ready" : "paused");
            tire.getJSONObject("management").put("access_generation", 0);
            vehicle.put("source_id", "synthetic-oem").put("name", "Explicit synthetic OEM policy fixture")
                .put("source_class", "test_fixture");
            vehicle.getJSONObject("management").put("access_generation", 0);
            items.put(tire).put(vehicle); settings.put("total", items.length());
            directory.getJSONArray("sources").put(json("id", "fixture", "name", tire.getString("name"),
                "status", "ready", "target_kind", "tire", "region", tire.getString("region"),
                "supported_models", new JSONArray().put("Fixture Tire"), "source_setting", copy(tire)));
            String owner = new Sample("nonempty").descriptor.getString("owner_scope_id");
            server.enqueue(new MockResponse().setBody(settings.toString()).addHeader("Content-Type", "application/json")
                .addHeader("X-Tire-Offline-Owner-Scope", owner));
            server.enqueue(new MockResponse().setBody(directory.toString()).addHeader("Content-Type", "application/json"));
            return OfflineFallbackAuthorityCoordinator.refresh(store, http, () -> true);
        }
        JSONObject binding() throws Exception { return store.fallbackStatus().getJSONArray("package_bindings").getJSONObject(0); }
        JSONObject request(String mode, JSONObject scope, JSONObject binding, JSONObject existing) throws Exception {
            JSONObject status = store.fallbackStatus(), authority = status.getJSONObject("authority");
            return json("mode", mode, "scope", copy(scope), "binding", binding == null ? null : copy(binding),
                "allow_same_scope_sync_binding_advance", false, "expected_profile_id", status.getString("profile_id"),
                "expected_owner_epoch", status.getLong("owner_epoch"), "authority", json("runtime_session_id", authority.getString("runtime_session_id"),
                    "authority_revision", authority.getLong("authority_revision")),
                "policy_id", existing == null ? null : existing.getString("policy_id"),
                "expected_policy_revision", existing == null ? 0 : existing.getLong("policy_revision"), "expires_in_seconds", 3600);
        }
        JSONObject preview(String mode, JSONObject scope, JSONObject binding, JSONObject existing) throws Exception {
            return store.fallbackPolicyPreview(request(mode, scope, binding, existing));
        }
        JSONObject apply(JSONObject preview) throws Exception { return store.fallbackPolicyApply(applyRequest(preview)); }
        JSONObject save(String mode, JSONObject scope, JSONObject binding, JSONObject existing) throws Exception {
            return apply(preview(mode, scope, binding, existing));
        }
        JSONObject saveAsk() throws Exception { return save("ask", queryScope("fixture"), null, null); }
        JSONObject change(JSONObject policy, boolean revoke) throws Exception {
            return store.fallbackPolicyChange(json("policy_id", policy.getString("policy_id"),
                "expected_policy_revision", policy.getLong("policy_revision")), revoke);
        }
        JSONArray policies() throws Exception { return store.fallbackStatus().getJSONArray("policies"); }
        void reopen() throws Exception { store.close(); store = new OfflinePackStore(context, namespace, clock); }
        File directory() throws Exception {
            java.lang.reflect.Field field = OfflinePackStore.class.getDeclaredField("directory"); field.setAccessible(true);
            File directory = (File) field.get(store);
            assertEquals(directory.getCanonicalFile(), directory.getAbsoluteFile());
            assertTrue(directory.getPath().startsWith(context.getNoBackupFilesDir().getCanonicalPath() + File.separator));
            return directory;
        }
        SQLiteConnection sql() throws Exception { return new BundledSQLiteDriver().open(new File(directory(), "catalog.sqlite").getAbsolutePath()); }
        void corruptOnlyOwnBody() throws Exception {
            File[] files = new File(directory(), "blobs").listFiles(); assertNotNull(files); assertEquals(1, files.length);
            byte[] sealed = Files.readAllBytes(files[0].toPath()); sealed[sealed.length - 1] ^= 1; Files.write(files[0].toPath(), sealed);
        }
        byte[] sealedJournal() throws Exception {
            try (SQLiteConnection sql = sql(); SQLiteStatement row = sql.prepare("SELECT value FROM fallback_state WHERE id=1")) {
                assertTrue(row.step()); return row.getBlob(0);
            }
        }
        JSONObject journal() throws Exception {
            String profile = store.fallbackStatus().getString("profile_id");
            byte[] clear = new OfflineCipher(context, namespace).open(sealedJournal(), "device-fallback-journal@1:" + profile);
            try { return (JSONObject) OfflineTireCriteria.parse(new String(clear, StandardCharsets.UTF_8), 2 * 1024 * 1024, 250000); }
            finally { Arrays.fill(clear, (byte) 0); }
        }
        JSONObject legacyRequest(long generation) throws Exception {
            JSONObject status = store.fallbackStatus();
            JSONObject intent = json("schema", "device-fallback-intent@1", "attempt_id", UUID.randomUUID().toString(),
                "query_fingerprint", "c".repeat(64), "source_id", "fixture", "source_access_generation", generation,
                "query", json("model", "Fixture Tire", "size", null), "filters", new JSONArray(),
                "failure", json("scope", "api_transport", "reason", "api_timeout", "query_id", null));
            return json("intent", intent, "decision", "allow", "slot_id", installed.getString("slot_id"),
                "expected_generation", installed.getLong("generation"), "expected_sha256", installed.getString("sha256"),
                "expected_profile_id", status.getString("profile_id"), "expected_owner_epoch", status.getLong("owner_epoch"));
        }
        public void close() throws Exception { try { store.close(); } finally { try { http.close(); } finally { server.close(); } } }
    }
    private static JSONObject applyRequest(JSONObject preview) throws Exception {
        return json("preview_id", preview.getString("preview_id"), "expected_fingerprint", preview.getString("fingerprint"),
            "expected_policy_revision", preview.getLong("expected_policy_revision"), "allow_continuous_history_fallback", true);
    }
    private static JSONObject policy(JSONArray policies, String id) throws Exception {
        for (int at = 0; at < policies.length(); at++) if (id.equals(policies.getJSONObject(at).getString("policy_id"))) return policies.getJSONObject(at);
        return null;
    }
    private static JSONObject manualRead(Harness h) throws Exception {
        return json("slot_id", h.installed.getString("slot_id"), "expected_generation", h.installed.getLong("generation"),
            "document_id", h.sample.material.getJSONArray("documents").getJSONObject(0).getString("id"));
    }


    private static JSONObject intent(Harness h, String kind) throws Exception {
        String reference = kind.equals("vehicle_fitments") ? "vehicle" : kind.equals("recall_campaign") ? "recall" : kind;
        JSONObject member = null; JSONArray all = h.sample.material.getJSONArray("members");
        for (int at = 0; at < all.length(); at++) if (all.getJSONObject(at).getJSONObject("reference").getString("kind").equals(reference)) {
            member = all.getJSONObject(at); break;
        }
        assertNotNull("Original producer fixture for " + kind, member);
        JSONObject payload = member.getJSONObject("payload"), query;
        if (kind.equals("tire")) query = json("model", payload.getJSONObject("variant").getString("model"), "size", payload.getJSONObject("variant").getString("size"));
        else if (kind.equals("vehicle_fitments")) query = json("vehicle_id", payload.getJSONObject("vehicle").getString("id"));
        else if (kind.equals("recall_campaign")) query = json("campaign_number", payload.getJSONObject("evidence").getString("campaign_number"));
        else query = copy(payload.getJSONObject("query"));
        JSONObject authority = h.store.fallbackStatus().getJSONObject("authority");
        String sourceId = member.getJSONObject("source").getString("source_id");
        return json("schema", "device-fallback-intent@2", "attempt_id", UUID.randomUUID().toString(),
            // This fingerprint is an opaque fixture token; it is never a fabricated API QueryRun key.
            "query_fingerprint", "c".repeat(64), "query_kind", kind, "query", query, "filters", new JSONArray(),
            "source_id", sourceId, "source_access_generation", source(authority, sourceId).getLong("access_generation"),
            "authority", json("runtime_session_id", authority.getString("runtime_session_id"), "authority_revision", authority.getLong("authority_revision")),
            "fallback_policy", "ask", "failure", json("scope", "api_transport", "reason", "api_timeout", "query_id", null));
    }
    private static JSONObject request(Harness h, JSONObject intent, String decision) throws Exception {
        JSONObject status = h.store.fallbackStatus();
        JSONObject value = json("intent", copy(intent), "slot_id", h.installed.getString("slot_id"),
            "expected_generation", h.installed.getLong("generation"), "expected_sha256", h.installed.getString("sha256"),
            "expected_profile_id", status.getString("profile_id"), "expected_owner_epoch", status.getLong("owner_epoch"));
        if (decision != null) value.put("decision", decision);
        return value;
    }
    private static JSONObject consume(JSONObject grant) throws Exception {
        return json("grant_id", grant.getString("id"), "intent", copy(grant.getJSONObject("intent")));
    }
    private static JSONObject audit(Harness h, String id) throws Exception {
        try (SQLiteConnection sql = h.sql(); SQLiteStatement rows = sql.prepare("SELECT id,value FROM fallback_audit")) {
            OfflineCipher cipher = new OfflineCipher(h.context, h.namespace);
            while (rows.step()) if (rows.getText(0).equals(id)) {
                byte[] clear = cipher.open(rows.getBlob(1), "fallback-audit@1:" + id);
                try { return OfflinePackageValidator.response(clear); }
                finally { Arrays.fill(clear, (byte) 0); }
            }
        }
        throw new AssertionError("Missing private durable audit " + id);
    }
    private static void closed(Checked action, String... codes) throws Exception {
        try { action.run(); fail("Expected terminal closed result"); }
        catch (NativeFailure failure) { assertTrue("Unexpected failure " + failure.code, Arrays.asList(codes).contains(failure.code)); }
    }
    private static int auditCount(Harness h) throws Exception {
        try (SQLiteConnection sql = h.sql(); SQLiteStatement rows = sql.prepare("SELECT count(*) FROM fallback_audit")) { assertTrue(rows.step()); return (int) rows.getLong(0); }
    }

    @Test public void originalFourKindsUseExplicitOnceAndBoundDeviceCitations() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh();
            for (String kind : new String[]{"tire", "vehicle_fitments", "recall_campaign", "recall_search"}) {
                JSONObject submitted = request(h, intent(h, kind), "allow");
                JSONObject decoded = OfflineFallbackWire.decode(OfflineFallbackWire.encode(submitted));
                JSONObject grant = h.store.decideFallback(decoded), result = h.store.consumeFallback(consume(grant));
                assertEquals("device-fallback-grant@2", grant.getString("schema")); assertEquals("explicit_once", grant.getJSONObject("fallback_authorization").getString("type"));
                assertEquals("device-fallback-result@2", result.getString("schema")); assertEquals("offline-pack@2", result.getString("package_schema"));
                assertEquals(kind, result.getString("query_kind")); assertFalse(result.getBoolean("complete_query_result"));
                assertEquals(kind.equals("recall_campaign") ? 2 : 1, result.getJSONArray("members").length());
                assertEquals("consumed", result.getJSONObject("grant").getString("state"));
                JSONArray citations = result.getJSONArray("citations"); assertTrue(citations.length() >= result.getJSONArray("members").length());
                for (int at = 0; at < citations.length(); at++) {
                    JSONObject citation = citations.getJSONObject(at); assertTrue(citation.getString("id").startsWith("device:"));
                    assertEquals(h.installed.getString("slot_id"), citation.getString("slot_id"));
                    assertEquals(h.sample.descriptor.getString("sha256"), citation.getString("package_sha256"));
                }
                fails("OFFLINE_FALLBACK_USED", () -> h.store.consumeFallback(consume(grant)));
            }
            assertEquals(3, h.server.getRequestCount());
        }
    }

    @Test public void originalEmptyRecallSearchPreservesExactPageObservation() throws Exception {
        try (Harness h = new Harness()) {
            h.install("empty"); h.refresh(); JSONObject criteria = intent(h, "recall_search");
            JSONObject grant = h.store.decideFallback(request(h, criteria, "allow")), result = h.store.consumeFallback(consume(grant));
            assertEquals(1, result.getJSONArray("members").length());
            JSONObject payload = result.getJSONArray("members").getJSONObject(0).getJSONObject("payload");
            assertEquals(0, payload.getJSONObject("discovery").getJSONArray("products").length());
            assertEquals(criteria.getJSONObject("query").getString("offset"), result.getJSONObject("query").getString("offset"));
            assertEquals(criteria.getJSONObject("query").getString("search"), result.getJSONObject("query").getString("search"));
            assertFalse(result.getBoolean("complete_query_result")); assertTrue(result.getJSONArray("citations").length() > 0);
        }
    }

    @Test public void askDoesNotBurnAttemptAndExplicitOnceCanFollow() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject criteria = intent(h, "tire"), authorization = h.store.authorizeFallback(request(h, criteria, null));
            assertEquals("ask", authorization.getString("state")); assertTrue(authorization.isNull("grant")); assertEquals(0, auditCount(h));
            JSONObject grant = h.store.decideFallback(request(h, criteria, "allow")), result = h.store.consumeFallback(consume(grant));
            assertEquals(1, result.getJSONArray("members").length());
            fails("OFFLINE_FALLBACK_USED", () -> h.store.authorizeFallback(request(h, criteria, null)));
        }
    }

    @Test public void explicitDenySharesAttemptTombstoneAcrossSchemaAndAnotherSlot() throws Exception {
        try (Harness h = new Harness()) {
            h.install("legacy"); h.refresh(); JSONObject criteria = intent(h, "tire");
            JSONObject denied = h.store.decideFallback(request(h, criteria, "deny")); assertEquals("denied", denied.getString("state"));
            assertEquals("denied", audit(h, denied.getString("id")).getString("state"));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.consumeFallback(consume(denied)));
            JSONObject legacy = h.legacyRequest(0); legacy.getJSONObject("intent").put("attempt_id", criteria.getString("attempt_id"));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.decideFallback(legacy));
            h.install("legacy");
            fails("OFFLINE_FALLBACK_USED", () -> h.store.decideFallback(request(h, criteria, "allow")));
        }
    }

    @Test public void policySelectionRespectsScopePriorityNewestAskAndNever() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject binding = h.binding();
            h.save("session_allow", sessionScope(), binding, null); h.clock.advance(1);
            h.save("source_allow", sourceScope(), binding, null); h.clock.advance(1);
            JSONObject query = h.save("query_allow", queryScope("fixture"), binding, null);
            JSONObject selected = h.store.authorizeFallback(request(h, intent(h, "tire"), null));
            assertEquals("allowed", selected.getString("state"));
            assertEquals(query.getString("policy_id"), selected.getJSONObject("grant").getJSONObject("fallback_authorization").getString("policy_id"));
            h.store.consumeFallback(consume(selected.getJSONObject("grant")));
            h.clock.advance(1); JSONObject newest = h.save("query_allow", queryScope("fixture"), binding, null);
            JSONObject moreRecent = h.store.authorizeFallback(request(h, intent(h, "tire"), null));
            assertEquals(newest.getString("policy_id"), moreRecent.getJSONObject("grant").getJSONObject("fallback_authorization").getString("policy_id"));
            h.store.revokeFallback(json("grant_id", moreRecent.getJSONObject("grant").getString("id")));
            h.save("ask", sourceScope(), null, null); JSONObject same = intent(h, "tire");
            JSONObject ask = h.store.authorizeFallback(request(h, same, null)); assertEquals("ask", ask.getString("state")); assertTrue(ask.isNull("grant"));
            JSONObject once = h.store.decideFallback(request(h, same, "allow")); h.store.consumeFallback(consume(once));
            h.save("never", queryScope("fixture"), null, null); JSONObject rejected = intent(h, "tire");
            JSONObject blocked = h.store.authorizeFallback(request(h, rejected, null)); assertEquals("blocked", blocked.getString("state")); assertTrue(blocked.isNull("grant"));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.decideFallback(request(h, rejected, "allow")));
        }
    }

    @Test public void policyGrantRequiresCurrentRevisionBindingAndUnpausedRecord() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject binding = h.binding(), original = h.save("query_allow", queryScope("fixture"), binding, null);
            JSONObject old = h.store.authorizeFallback(request(h, intent(h, "tire"), null)).getJSONObject("grant");
            assertEquals(original.getString("policy_id"), old.getJSONObject("fallback_authorization").getString("policy_id"));
            assertEquals(original.getLong("policy_revision"), old.getJSONObject("fallback_authorization").getLong("policy_revision"));
            JSONObject updated = h.save("query_allow", queryScope("fixture"), binding, original);
            closed(() -> h.store.consumeFallback(consume(old)), "OFFLINE_FALLBACK_POLICY_CHANGED", "OFFLINE_FALLBACK_USED");
            JSONObject fresh = h.store.authorizeFallback(request(h, intent(h, "tire"), null)).getJSONObject("grant");
            assertEquals(updated.getLong("policy_revision"), fresh.getJSONObject("fallback_authorization").getLong("policy_revision"));
            assertEquals(h.installed.getLong("generation"), fresh.getLong("generation"));
            assertEquals(binding.getString("sha256"), fresh.getString("package_sha256"));
            h.store.consumeFallback(consume(fresh));
            JSONObject pausedGrant = h.store.authorizeFallback(request(h, intent(h, "tire"), null)).getJSONObject("grant");
            h.change(updated, false); h.corruptOnlyOwnBody();
            closed(() -> h.store.consumeFallback(consume(pausedGrant)), "OFFLINE_FALLBACK_POLICY_CHANGED", "OFFLINE_FALLBACK_USED");
            assertEquals("ask", h.store.authorizeFallback(request(h, intent(h, "tire"), null)).getString("state"));
        }
    }

    @Test public void newNeverRejectsOldV2GrantWithConsumedAuditBeforeBody() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject grant = h.store.decideFallback(request(h, intent(h, "tire"), "allow"));
            h.save("never", queryScope("fixture"), null, null); h.corruptOnlyOwnBody();
            fails("OFFLINE_FALLBACK_NEVER", () -> h.store.consumeFallback(consume(grant)));
            assertEquals("consumed", audit(h, grant.getString("id")).getString("state"));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.consumeFallback(consume(grant)));
        }
    }

    @Test public void corruptBodyStillHasDurableConsumedAuditAndNoReusableGrant() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); h.corruptOnlyOwnBody();
            JSONObject grant = h.store.decideFallback(request(h, intent(h, "tire"), "allow"));
            assertEquals("allowed", audit(h, grant.getString("id")).getString("state"));
            fails("OFFLINE_CORRUPT", () -> h.store.consumeFallback(consume(grant)));
            assertEquals("consumed", audit(h, grant.getString("id")).getString("state"));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.consumeFallback(consume(grant)));
            assertEquals(3, h.server.getRequestCount());
        }
    }

    @Test public void auditCommitFailurePrecedesCorruptBodyAndBurnsRuntimeClaim() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject grant = h.store.decideFallback(request(h, intent(h, "tire"), "allow"));
            h.corruptOnlyOwnBody();
            try (SQLiteConnection sql = h.sql(); SQLiteStatement trigger = sql.prepare("CREATE TRIGGER qa_reject_v2_audit BEFORE UPDATE ON fallback_audit BEGIN SELECT RAISE(ABORT,'qa_audit_commit'); END")) { trigger.step(); }
            fails("OFFLINE_STORE_UNAVAILABLE", () -> h.store.consumeFallback(consume(grant)));
            fails("OFFLINE_FALLBACK_USED", () -> h.store.consumeFallback(consume(grant)));
            assertEquals("allowed", audit(h, grant.getString("id")).getString("state"));
            // The last durable receipt remains allowed because its UPDATE rolled back; no body was exposed.
            // No key/profile cleanup is performed, so the fault remains available for root review.
        }
    }

    @Test public void staleAuthorityPinsRejectAdmissionWithoutBodyOrAudit() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject valid = intent(h, "tire"); h.corruptOnlyOwnBody();
            JSONObject authority = copy(valid); authority.getJSONObject("authority").put("authority_revision", authority.getJSONObject("authority").getLong("authority_revision") + 1);
            fails("OFFLINE_FALLBACK_AUTHORITY_CHANGED", () -> h.store.decideFallback(request(h, authority, "allow")));
            JSONObject generation = copy(valid).put("source_access_generation", 999);
            fails("OFFLINE_FALLBACK_SOURCE_CHANGED", () -> h.store.decideFallback(request(h, generation, "allow")));
            JSONObject wrongOwner = request(h, valid, "allow").put("expected_owner_epoch", h.store.fallbackStatus().getLong("owner_epoch") + 1);
            fails("OFFLINE_FALLBACK_MISMATCH", () -> h.store.decideFallback(wrongOwner));
            assertEquals(0, auditCount(h));
            assertEquals("ask", h.store.authorizeFallback(request(h, valid, null)).getString("state"));
        }
    }

    @Test public void expiryRollbackOwnerResetDocumentEndAndRestartFailBeforeBody() throws Exception {
        for (String boundary : new String[]{"wall_expiry", "mono_expiry", "rollback", "owner_reset", "document_end", "restart"}) try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject grant = h.store.decideFallback(request(h, intent(h, "tire"), "allow")); h.corruptOnlyOwnBody();
            if (boundary.equals("wall_expiry")) h.clock.wall += 300000;
            else if (boundary.equals("mono_expiry")) h.clock.mono += 300000;
            else if (boundary.equals("rollback")) h.clock.wall--;
            else if (boundary.equals("owner_reset")) h.store.resetOwnerEpoch();
            else if (boundary.equals("document_end")) h.store.invalidateFallbackGrants();
            else h.reopen();
            if (boundary.endsWith("expiry") || boundary.equals("rollback")) fails("OFFLINE_FALLBACK_EXPIRED", () -> h.store.consumeFallback(consume(grant)));
            else closed(() -> h.store.consumeFallback(consume(grant)), "OFFLINE_FALLBACK_USED", "OFFLINE_FALLBACK_AUTHORITY_UNKNOWN", "OFFLINE_FALLBACK_AUTHORITY_CHANGED", "OFFLINE_FALLBACK_MISMATCH");
            fails("OFFLINE_FALLBACK_USED", () -> h.store.consumeFallback(consume(grant)));
        }
    }

    @Test public void originalHugeIntegerSurvivesCoreAndRealWireRoundtrip() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject grant = h.store.decideFallback(request(h, intent(h, "tire"), "allow"));
            JSONObject result = h.store.consumeFallback(consume(grant));
            JSONObject facts = result.getJSONArray("members").getJSONObject(0).getJSONObject("payload").getJSONObject("variant").getJSONObject("facts");
            assertEquals(new BigInteger("9007199254740993"), new BigInteger(facts.get("reference_int").toString()));
            JSONObject transport = OfflineFallbackWire.encode(result); assertTrue(transport.getString("raw_json").contains("9007199254740993"));
            JSONObject restored = OfflineFallbackWire.decode(transport);
            assertTrue(OfflineJsonInteger.stringify(restored).contains("9007199254740993"));
            transport.getJSONArray("members").getJSONObject(0).getJSONObject("payload").getJSONObject("variant").getJSONObject("facts").put("reference_int", 1);
            fails("OFFLINE_FALLBACK_INVALID", () -> OfflineFallbackWire.decode(transport));
        }
    }

    @Test public void concurrentSingleConsumeHasOneResultAndCanRunBesideAuthorization() throws Exception {
        try (Harness h = new Harness()) {
            h.install("nonempty"); h.refresh(); JSONObject grant = h.store.decideFallback(request(h, intent(h, "tire"), "allow"));
            JSONObject a = consume(grant), b = consume(grant), other = request(h, intent(h, "tire"), null);
            ExecutorService workers = Executors.newFixedThreadPool(3); CountDownLatch start = new CountDownLatch(1);
            try {
                List<Future<String>> consumers = new ArrayList<>();
                for (JSONObject request : new JSONObject[]{a, b}) consumers.add(workers.submit(() -> {
                    assertTrue(start.await(3, TimeUnit.SECONDS));
                    try { return h.store.consumeFallback(request).getString("schema"); }
                    catch (NativeFailure failure) { return failure.code; }
                }));
                Future<String> authorizer = workers.submit(() -> { assertTrue(start.await(3, TimeUnit.SECONDS)); return h.store.authorizeFallback(other).getString("state"); });
                start.countDown(); int successful = 0, alreadyUsed = 0;
                for (Future<String> future : consumers) {
                    String outcome = future.get(15, TimeUnit.SECONDS);
                    if (outcome.equals("device-fallback-result@2")) successful++;
                    else if (outcome.equals("OFFLINE_FALLBACK_USED")) alreadyUsed++;
                    else fail("Unexpected consume outcome " + outcome);
                }
                assertEquals("ask", authorizer.get(15, TimeUnit.SECONDS)); assertEquals(1, successful); assertEquals(1, alreadyUsed);
                assertEquals("consumed", audit(h, grant.getString("id")).getString("state"));
            } finally { workers.shutdownNow(); assertTrue(workers.awaitTermination(3, TimeUnit.SECONDS)); }
        }
    }
}
