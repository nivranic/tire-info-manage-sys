package org.taiji.tireintelligence.mobile;

import android.content.Context;
import android.system.Os;
import android.system.OsConstants;
import androidx.sqlite.SQLiteConnection;
import androidx.sqlite.SQLiteStatement;
import androidx.sqlite.driver.bundled.BundledSQLiteDriver;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.RandomAccessFile;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.BooleanSupplier;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Device-owned encrypted originals and metadata; disk SQLite stores only opaque
 * pointers/generations and AEAD blobs. All document/FTS tables live in memory.
 * Each call is serialized locally and by a cross-process profile file lock.
 */
final class OfflinePackStore implements AutoCloseable {
    private static final int MAX_SLOTS = 16;
    private static final long MAX_STORE_BYTES = 32L * 1024 * 1024;
    private static final long MAX_GENERATION = 9007199254740990L;
    private static final Set<String> KINDS = new HashSet<>(Arrays.asList(
        "tire", "vehicle", "test_event", "recall", "recall_search", "garage", "watchlist"));
    private static final Map<String, Object> PROCESS_LOCKS = new ConcurrentHashMap<>();
    private final String profileId;
    private final File directory;
    private final File blobs;
    private final File catalogPath;
    private final Object processLock;
    private final OfflineCipher cipher;
    private final OfflineFallbackGrant fallback;
    private final OfflineFallbackAuthority fallbackAuthority;
    private final OfflineFallbackGrant.Clock fallbackClock;
    private FallbackNetwork fallbackNetwork;
    private NativeHttpBridge fallbackHttp;
    private long fallbackDocumentVersion;
    private final Map<String, FallbackPreview> fallbackPreviews = new HashMap<>();
    private static final class FallbackPreview {
        JSONObject value, request;
        long wall, monotonic;
    }
    static final class FallbackNetwork {
        final NativeHttpBridge http;
        final NativeHttpBridge.SessionFence fence;
        final String runtime;
        final long revision;
        FallbackNetwork(NativeHttpBridge http, NativeHttpBridge.SessionFence fence, JSONObject authority) throws Exception {
            this.http = http; this.fence = fence; runtime = authority.getString("runtime_session_id"); revision = authority.getLong("authority_revision");
        }
        boolean current() { try { http.checkSession(fence); return true; } catch (NativeFailure failure) { return false; } }
    }
    private final Map<String, SyncPreview> syncPreviews = new HashMap<>();
    private static final class SyncPreview {
        JSONObject value; String sessionBinding; long wall, monotonic;
    }
    private boolean closed;

    OfflinePackStore(Context context, String namespace) throws NativeFailure {
        this(context, namespace, OfflineFallbackGrant.SYSTEM_CLOCK);
    }

    OfflinePackStore(Context context, String namespace, OfflineFallbackGrant.Clock clock) throws NativeFailure {
        fallback = new OfflineFallbackGrant(clock);
        fallbackAuthority = new OfflineFallbackAuthority(clock);
        fallbackClock = clock;
        cipher = new OfflineCipher(context, namespace);
        profileId = OfflineCipher.sha256((context.getPackageName() + ":offline-profile@1:" + namespace)
            .getBytes(StandardCharsets.UTF_8));
        try {
            // Android exposes /data/data as a legitimate alias of /data/user/0.
            // Canonicalize that trusted app root first, then reject redirects
            // in every profile-owned child instead of rejecting the OS alias.
            File noBackupRoot = context.getNoBackupFilesDir().getCanonicalFile();
            File expectedDirectory = new File(new File(noBackupRoot, "offline-v1"), profileId);
            directory = expectedDirectory.getCanonicalFile();
            if (!directory.equals(expectedDirectory.getAbsoluteFile()) ||
                !directory.getPath().startsWith(noBackupRoot.getPath() + File.separator)) {
                throw new NativeFailure("OFFLINE_INVALID_PROFILE");
            }
            File expectedBlobs = new File(directory, "blobs");
            blobs = expectedBlobs.getCanonicalFile();
            if (!blobs.equals(expectedBlobs.getAbsoluteFile())) throw new NativeFailure("OFFLINE_INVALID_PROFILE");
            catalogPath = new File(directory, "catalog.sqlite");
            if (!catalogPath.getCanonicalFile().equals(catalogPath.getAbsoluteFile())) throw new NativeFailure("OFFLINE_CORRUPT");
            if (!blobs.isDirectory() && !blobs.mkdirs()) throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE");
            if (!directory.getCanonicalFile().equals(directory) || !blobs.getCanonicalFile().equals(blobs)) {
                throw new NativeFailure("OFFLINE_INVALID_PROFILE");
            }
        } catch (NativeFailure failure) { throw failure; }
        catch (Exception ignored) { throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE"); }
        processLock = PROCESS_LOCKS.computeIfAbsent(directory.getAbsolutePath(), ignored -> new Object());
        withCatalog(connection -> {
            File[] existingBlobs = blobs.listFiles();
            if (existingBlobs == null) throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE");
            long tables = OfflineSql.scalar(connection, "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('owner_state','slots')");
            if (tables == 0) {
                if (existingBlobs.length > 0 || cipher.hasKey()) throw new NativeFailure("OFFLINE_CORRUPT");
                OfflineSql.execute(connection, "BEGIN IMMEDIATE");
                try {
                    OfflineSql.execute(connection, "CREATE TABLE owner_state (id INTEGER PRIMARY KEY CHECK(id=1), epoch INTEGER NOT NULL CHECK(epoch>=1), proof BLOB)");
                    OfflineSql.execute(connection, "INSERT INTO owner_state(id,epoch,proof) VALUES(1,1,NULL)");
                    OfflineSql.execute(connection, "CREATE TABLE slots (slot_id TEXT PRIMARY KEY, generation INTEGER NOT NULL CHECK(generation>=1), blob_id TEXT, metadata BLOB, CHECK((blob_id IS NULL)=(metadata IS NULL)))");
                    OfflineSql.execute(connection, "COMMIT");
                } catch (Exception failure) { OfflineSql.execute(connection, "ROLLBACK"); throw failure; }
            }
            if ((tables != 0 && tables != 2) || OfflineSql.scalar(connection, "SELECT count(*) FROM owner_state WHERE id=1") != 1) {
                throw new NativeFailure("OFFLINE_CORRUPT");
            }
            if (OfflineSql.scalar(connection, "SELECT count(*) FROM owner_state WHERE epoch<1 OR epoch>9007199254740990") != 0) {
                throw new NativeFailure("OFFLINE_CORRUPT");
            }
            // A separate bounded encrypted audit leaves original offline-pack@1 bytes untouched.
            OfflineSql.execute(connection, "CREATE TABLE IF NOT EXISTS fallback_audit (id TEXT PRIMARY KEY, value BLOB NOT NULL)");
            OfflineSql.execute(connection, "CREATE TABLE IF NOT EXISTS fallback_state (id INTEGER PRIMARY KEY CHECK(id=1), value BLOB NOT NULL)");
            OfflineSql.execute(connection, "CREATE TABLE IF NOT EXISTS sync_state (id INTEGER PRIMARY KEY CHECK(id=1), value BLOB NOT NULL)");
            OfflineSql.execute(connection, "CREATE TABLE IF NOT EXISTS release_checks (slot_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, value BLOB NOT NULL)");
            try (SQLiteStatement state = connection.prepare("SELECT proof FROM owner_state WHERE id=1")) {
                state.step();
                if (state.isNull(0) && (cipher.hasKey() || existingBlobs.length > 0)) throw new NativeFailure("OFFLINE_CORRUPT");
            }
            cleanup(connection);
            try (SQLiteConnection memory = memoryIndex()) { /* Actual FTS5 compile/create/MATCH probe. */ }
            if (OfflineSql.scalar(connection, "SELECT count(*) FROM slots WHERE blob_id IS NOT NULL") > 0) {
                try { epoch(connection); }
                catch(NativeFailure failure) {
                    // Unauthenticated owner/key state stays closed in every status/read
                    // path. Construction still permits exact opaque-slot removal.
                    if(!List.of("OFFLINE_CORRUPT","OFFLINE_KEY_MISSING").contains(failure.code)) throw failure;
                }
            }
            return null;
        });
    }

    private interface CatalogWork<T> { T run(SQLiteConnection connection) throws Exception; }

    private <T> T withCatalog(CatalogWork<T> work) throws NativeFailure {
        if (closed) throw new NativeFailure("OFFLINE_STORE_CLOSED");
        synchronized (processLock) {
            File lockPath = new File(directory, "profile.lock");
            try {
                if (!directory.getCanonicalFile().equals(directory) || !blobs.getCanonicalFile().equals(blobs) ||
                    !catalogPath.getCanonicalFile().equals(catalogPath) || !lockPath.getCanonicalFile().equals(lockPath)) {
                    throw new NativeFailure("OFFLINE_CORRUPT");
                }
            } catch (NativeFailure failure) { throw failure; }
            catch (Exception ignored) { throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE"); }
            try (RandomAccessFile lockFile = new RandomAccessFile(lockPath, "rw");
                 FileLock lock = lockFile.getChannel().lock();
                 SQLiteConnection connection = new BundledSQLiteDriver().open(catalogPath.getAbsolutePath())) {
                OfflineSql.execute(connection, "PRAGMA busy_timeout=5000");
                OfflineSql.execute(connection, "PRAGMA journal_mode=DELETE");
                OfflineSql.execute(connection, "PRAGMA synchronous=FULL");
                OfflineSql.execute(connection, "PRAGMA temp_store=MEMORY");
                return work.run(connection);
            } catch (NativeFailure failure) { throw failure; }
            catch (Exception ignored) { throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE"); }
        }
    }

    private static JSONObject json(Object... pairs) throws Exception {
        JSONObject result = new JSONObject();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1] == null ? JSONObject.NULL : pairs[i + 1]);
        return result;
    }

    private long epoch(SQLiteConnection connection) throws Exception {
        try (SQLiteStatement state = connection.prepare("SELECT epoch,proof FROM owner_state WHERE id=1")) {
            if (!state.step()) throw new NativeFailure("OFFLINE_CORRUPT");
            long epoch = state.getLong(0);
            if (epoch < 1 || epoch > MAX_GENERATION) throw new NativeFailure("OFFLINE_CORRUPT");
            if (state.isNull(1)) {
                if (cipher.hasKey() || OfflineSql.scalar(connection, "SELECT count(*) FROM slots WHERE blob_id IS NOT NULL") > 0) {
                    throw new NativeFailure("OFFLINE_CORRUPT");
                }
            } else {
                JSONObject proof = OfflinePackageValidator.parse(cipher.open(state.getBlob(1), "owner-state@1"));
                OfflinePackageValidator.keys(proof, "epoch");
                if (OfflinePackageValidator.number(proof, "epoch", MAX_GENERATION) != epoch) throw new NativeFailure("OFFLINE_CORRUPT");
            }
            return epoch;
        }
    }

    private void ensureOwnerProof(SQLiteConnection connection) throws Exception {
        long epoch = epoch(connection);
        if (OfflineSql.scalar(connection, "SELECT count(*) FROM owner_state WHERE proof IS NULL") != 0) {
            // Invoked only after explicit validated install or policy approval. A key
            // exists even if a later installation stage is cancelled, but the
            // authenticated owner epoch remains a complete durable receipt.
            byte[] proof = cipher.seal(json("epoch", epoch).toString().getBytes(StandardCharsets.UTF_8), "owner-state@1");
            OfflineSql.execute(connection, "UPDATE owner_state SET proof=? WHERE id=1", proof);
        }
    }

    private static final class Row {
        String slot;
        long generation;
        String blob;
        byte[] sealedMetadata;
        JSONObject metadata;
    }

    private Row row(SQLiteConnection connection, String slot) throws Exception {
        try (SQLiteStatement statement = OfflineSql.statement(connection,
            "SELECT slot_id,generation,blob_id,metadata FROM slots WHERE slot_id=?", slot)) {
            if (!statement.step()) return null;
            Row row = new Row();
            row.slot = statement.getText(0); row.generation = statement.getLong(1);
            row.blob = statement.isNull(2) ? null : statement.getText(2);
            row.sealedMetadata = statement.isNull(3) ? null : statement.getBlob(3);
            if (row.generation < 1 || row.generation > MAX_GENERATION || (row.blob == null) != (row.sealedMetadata == null)) {
                throw new NativeFailure("OFFLINE_CORRUPT");
            }
            return row;
        }
    }

    private String purpose(Row row, String type) { return type + ":" + row.slot + ":" + row.generation + ":" + row.blob; }

    private JSONObject metadata(Row row) throws Exception {
        if (row.blob == null) throw new NativeFailure("OFFLINE_NOT_FOUND");
        if (row.metadata == null) {
            row.metadata = OfflinePackageValidator.parse(cipher.open(row.sealedMetadata, purpose(row, "metadata")));
            OfflinePackageValidator.keys(row.metadata, "descriptor", "installed_at", "created_epoch", "allowed_epoch", "title");
            OfflinePackageValidator.object(row.metadata, "descriptor");
            OfflinePackageValidator.number(row.metadata, "created_epoch", MAX_GENERATION);
            OfflinePackageValidator.number(row.metadata, "allowed_epoch", MAX_GENERATION);
            OfflinePackageValidator.text(row.metadata, "installed_at", 80);
            OfflinePackageValidator.text(row.metadata, "title", 200);
        }
        return row.metadata;
    }

    private static void slotRequest(JSONObject request, String... additional) throws NativeFailure {
        List<String> fields = new ArrayList<>(Arrays.asList("slot_id", "expected_generation"));
        fields.addAll(Arrays.asList(additional));
        OfflinePackageValidator.keys(request, fields.toArray(new String[0]));
        OfflinePackageValidator.uuid(request, "slot_id");
        OfflinePackageValidator.number(request, "expected_generation", MAX_GENERATION);
    }

    private Row expected(SQLiteConnection connection, JSONObject request, boolean unlocked) throws Exception {
        return expected(connection,request,unlocked,true);
    }
    private Row expected(SQLiteConnection connection, JSONObject request, boolean unlocked, boolean verifyRelease) throws Exception {
        Row row = row(connection, OfflinePackageValidator.uuid(request, "slot_id"));
        long expected = OfflinePackageValidator.number(request, "expected_generation", MAX_GENERATION);
        if (row == null) {
            if (expected != 0) throw new NativeFailure("OFFLINE_STALE_GENERATION");
            throw new NativeFailure("OFFLINE_NOT_FOUND");
        }
        if (row.generation != expected) throw new NativeFailure("OFFLINE_STALE_GENERATION");
        if (row.blob == null) throw new NativeFailure("OFFLINE_NOT_FOUND");
        JSONObject metadata = metadata(row);
        if (unlocked && metadata.getLong("allowed_epoch") != epoch(connection)) throw new NativeFailure("OFFLINE_OWNER_LOCKED");
        if (unlocked && verifyRelease) requireRelease(connection, row);
        return row;
    }

    private JSONObject slot(Row row, long epoch) throws Exception {
        JSONObject metadata = metadata(row), descriptor = metadata.getJSONObject("descriptor");
        return json("slot_id", row.slot, "generation", row.generation, "package_id", descriptor.getString("id"),
            "sha256", descriptor.getString("sha256"), "byte_count", descriptor.getLong("byte_count"),
            "title", metadata.getString("title"), "created_at", descriptor.getString("content_created_at"),
            "installed_at", metadata.getString("installed_at"), "privacy_class", descriptor.getString("privacy_class"),
            "owner_scope_id", descriptor.getString("owner_scope_id"), "locked", metadata.getLong("allowed_epoch") != epoch,
            "previous_owner", metadata.getLong("created_epoch") != epoch, "counts", descriptor.getJSONObject("counts"));
    }

    private List<Row> active(SQLiteConnection connection) throws Exception {
        List<Row> rows = new ArrayList<>();
        try (SQLiteStatement statement = connection.prepare("SELECT slot_id FROM slots WHERE blob_id IS NOT NULL ORDER BY slot_id")) {
            while (statement.step()) rows.add(row(connection, statement.getText(0)));
        }
        if (rows.size() > MAX_SLOTS) throw new NativeFailure("OFFLINE_CORRUPT");
        return rows;
    }

    private long total(List<Row> rows) throws Exception {
        long bytes = 0;
        for (Row row : rows) bytes += OfflinePackageValidator.number(metadata(row).getJSONObject("descriptor"), "byte_count", OfflinePackageValidator.MAX_BYTES);
        if (bytes > MAX_STORE_BYTES) throw new NativeFailure("OFFLINE_CORRUPT");
        return bytes;
    }

    synchronized JSONObject status() throws NativeFailure {
        return withCatalog(connection -> json("schema", "offline-host@1", "available", true, "state", "ready",
            "storage", "native_encrypted_files", "profile_id", profileId, "owner_epoch", epoch(connection),
            "total_bytes", total(active(connection)), "max_store_bytes", MAX_STORE_BYTES,
            "max_package_bytes", OfflinePackageValidator.MAX_BYTES, "max_slots", MAX_SLOTS,
            "encryption", "android_keystore", "persistence", "app_private", "manual_updates", true,
            "background_updates", false, "error", null));
    }

    synchronized JSONObject list() throws NativeFailure {
        return withCatalog(connection -> {
            long epoch = epoch(connection); JSONArray rows = new JSONArray();
            for (Row row : active(connection)) rows.put(slot(row, epoch));
            return json("schema", "offline-host@1", "data_state", "local_snapshot", "profile_id", profileId,
                "owner_epoch", epoch, "items", rows);
        });
    }

    synchronized JSONObject fallbackAuthoritySnapshot() throws NativeFailure {
        return withCatalog(connection -> fallbackAuthority.snapshot(profileId, epoch(connection)));
    }
    synchronized OfflineFallbackAuthority.Capture captureFallbackAuthority() throws NativeFailure {
        return withCatalog(connection -> fallbackAuthority.capture(profileId, epoch(connection)));
    }
    synchronized FallbackNetwork observedFallbackNetwork() { return fallbackNetwork; }
    synchronized void attachFallbackHttp(NativeHttpBridge http) throws NativeFailure {
        if (http == null) return;
        if (fallbackHttp != null && fallbackHttp != http) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
        fallbackHttp = http;
    }
    private synchronized NativeHttpBridge attachedFallbackHttp() { return fallbackHttp; }
    synchronized JSONObject observeFallbackAuthority(OfflineFallbackAuthority.Capture capture, JSONObject settings,
        JSONObject sources, String owner, String networkBinding, BooleanSupplier stillCurrent) throws NativeFailure {
        return observeFallbackAuthority(capture, settings, sources, owner, networkBinding, stillCurrent, null, null, false);
    }
    synchronized JSONObject observeFallbackAuthority(OfflineFallbackAuthority.Capture capture, JSONObject settings,
        JSONObject sources, String owner, String networkBinding, BooleanSupplier stillCurrent,
        NativeHttpBridge bridge, NativeHttpBridge.SessionFence fence, boolean knownSessionChanged) throws NativeFailure {
        if (bridge != null && fallbackHttp != null && fallbackHttp != bridge)
            throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
        return withCatalog(connection -> {
            current(stillCurrent);
            JSONObject previousAuthority = fallbackAuthority.snapshot(profileId, epoch(connection));
            OfflineFallbackAuthority.Prepared prepared = fallbackAuthority.prepare(capture, profileId, epoch(connection),
                settings, sources, owner, networkBinding, knownSessionChanged);
            current(stillCurrent);
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                JSONObject state = fallbackState(connection);
                OfflineFallbackJournal.observe(state, prepared.value, networkBinding, knownSessionChanged, fallbackClock.wall());
                if (cipher.hasKey()) saveFallbackState(connection, state);
                current(stillCurrent);
                OfflineSql.execute(connection, "COMMIT"); committed = true;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
            if (prepared.changed) {
                fallback.invalidateV2(); fallbackPreviews.clear();
                if (knownSessionChanged || (previousAuthority.getString("state").equals("last_observed")
                    && !java.util.Objects.equals(previousAuthority.opt("owner_scope_id"), prepared.value.opt("owner_scope_id")))) fallback.clear();
                else if (previousAuthority.getString("state").equals("last_observed")) {
                    Set<String> changedSources = new HashSet<>();
                    JSONArray priorSources = previousAuthority.getJSONArray("sources"), nextSources = prepared.value.getJSONArray("sources");
                    for (int at = 0; at < priorSources.length(); at++) {
                        JSONObject priorSource = priorSources.getJSONObject(at); JSONObject match = null;
                        for (int index = 0; index < nextSources.length(); index++) if (priorSource.getString("source_id").equals(nextSources.getJSONObject(index).getString("source_id"))) match = nextSources.getJSONObject(index);
                        if (match == null || !OfflineFallbackValues.same(priorSource, match)) changedSources.add(priorSource.getString("source_id"));
                    }
                    fallback.invalidateLegacySources(changedSources);
                }
            }
            fallbackAuthority.publish(prepared);
            if (bridge != null) attachFallbackHttp(bridge);
            fallbackNetwork = bridge == null || fence == null ? null : new FallbackNetwork(bridge, fence, prepared.value);
            return fallbackAuthority.snapshot(profileId, epoch(connection));
        });
    }

    private JSONObject fallbackState(SQLiteConnection connection) throws Exception {
        try (SQLiteStatement row = connection.prepare("SELECT value FROM fallback_state WHERE id=1")) {
            if (!row.step()) return OfflineFallbackJournal.empty(profileId, epoch(connection), fallbackClock.wall());
            byte[] plaintext = cipher.open(row.getBlob(0), "device-fallback-journal@1:" + profileId);
            try {
                if (plaintext.length > OfflineFallbackJournal.MAX_BYTES) throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID");
                JSONObject value = (JSONObject) OfflineTireCriteria.parse(NativePolicy.utf8(plaintext, "OFFLINE_FALLBACK_STATE_INVALID"), OfflineFallbackJournal.MAX_BYTES, 250000);
                return OfflineFallbackJournal.validate(value, profileId);
            } catch (NativeFailure failure) { throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID"); }
            catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_STATE_INVALID"); }
            finally { Arrays.fill(plaintext, (byte) 0); }
        }
    }
    private void saveFallbackState(SQLiteConnection connection, JSONObject state) throws Exception {
        OfflineFallbackJournal.validate(state, profileId);
        if (!cipher.hasKey()) throw new NativeFailure("OFFLINE_KEY_MISSING");
        byte[] plaintext = OfflineJsonInteger.stringify(state).getBytes(StandardCharsets.UTF_8);
        try {
            byte[] sealed = cipher.seal(plaintext, "device-fallback-journal@1:" + profileId);
            OfflineSql.execute(connection, "INSERT INTO fallback_state(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value", sealed);
        } finally { Arrays.fill(plaintext, (byte) 0); }
    }
    private interface FallbackWork<T> { T run(SQLiteConnection connection, JSONObject state, JSONObject authority) throws Exception; }
    private <T> T fallbackTx(FallbackWork<T> work) throws NativeFailure {
        return withCatalog(connection -> {
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                JSONObject state = fallbackState(connection), authority = fallbackAuthority.snapshot(profileId, epoch(connection));
                if (OfflineFallbackJournal.reconcile(state, authority, fallbackClock.wall())) fallback.invalidateV2();
                T result = work.run(connection, state, authority);
                if (cipher.hasKey()) saveFallbackState(connection, state);
                OfflineSql.execute(connection, "COMMIT"); committed = true; return result;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }
    private void backfillFallbackBinding(SQLiteConnection connection, Row row, JSONObject material) throws Exception {
        long currentEpoch = epoch(connection);
        if (metadata(row).getLong("created_epoch") != currentEpoch || metadata(row).getLong("allowed_epoch") != currentEpoch) return;
        JSONObject state = fallbackState(connection);
        OfflineFallbackJournal.putBinding(state, slot(row, currentEpoch), currentEpoch, material, false, fallbackClock.wall());
        saveFallbackState(connection, state);
    }
    private void requireFallbackBinding(SQLiteConnection connection, JSONObject state, JSONObject binding, JSONObject authority) throws Exception {
        JSONObject entry = OfflineFallbackJournal.bindingEntry(state, binding.getString("slot_id"));
        if (entry == null || entry.getLong("owner_epoch") != authority.getLong("owner_epoch")
            || !OfflineFallbackValues.same(entry.getJSONObject("binding"), binding)) throw new NativeFailure("OFFLINE_FALLBACK_SCOPE_METADATA_MISSING");
        Row row = expected(connection, json("slot_id", binding.getString("slot_id"), "expected_generation", binding.getLong("generation")), true, false);
        JSONObject meta = metadata(row), descriptor = meta.getJSONObject("descriptor");
        if (meta.getLong("created_epoch") != authority.getLong("owner_epoch") || !descriptor.getString("sha256").equals(binding.getString("sha256"))
            || !descriptor.getString("id").equals(binding.getString("package_id"))
            || !descriptor.getString("owner_scope_id").equals(authority.getString("owner_scope_id"))) throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
    }
    private synchronized FallbackNetwork requireFallbackNetwork() throws NativeFailure {
        if (fallbackNetwork == null) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_UNKNOWN");
        return fallbackNetwork;
    }
    private void checkFallbackNetwork(FallbackNetwork network, JSONObject authority) throws NativeFailure {
        if (network == null) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_UNKNOWN");
        if (fallbackNetwork != network || !authority.optString("state").equals("last_observed")
            || !network.runtime.equals(authority.optString("runtime_session_id")) || network.revision != authority.optLong("authority_revision"))
            throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
        network.http.checkSession(network.fence);
    }
    private interface NetworkFallbackWork { JSONObject run(FallbackNetwork network) throws Exception; }
    private JSONObject withFallbackNetwork(NetworkFallbackWork work) throws NativeFailure {
        FallbackNetwork network = requireFallbackNetwork();
        try { return network.http.publish(network.fence, () -> work.run(network)); }
        catch (NativeFailure failure) { throw failure; }
        catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
    }
    synchronized JSONObject fallbackStatus() throws NativeFailure {
        return fallbackTx((connection, state, authority) -> {
            JSONArray policies = new JSONArray(), bindings = new JSONArray(), missing = new JSONArray();
            long epoch = epoch(connection);
            for (int at = 0; at < state.getJSONArray("policies").length(); at++) {
                JSONObject policy = state.getJSONArray("policies").getJSONObject(at).getJSONObject("policy");
                if (policy.getLong("owner_epoch") == epoch && profileId.equals(policy.getString("profile_id"))) policies.put(OfflineFallbackJournal.copy(policy));
            }
            for (Row row : active(connection)) {
                JSONObject meta = metadata(row);
                if (meta.getLong("created_epoch") != epoch || meta.getLong("allowed_epoch") != epoch) continue;
                JSONObject saved = OfflineFallbackJournal.bindingEntry(state, row.slot);
                if (saved == null || saved.getLong("owner_epoch") != epoch || saved.getJSONObject("binding").getLong("generation") != row.generation
                    || !saved.getJSONObject("binding").getString("sha256").equals(meta.getJSONObject("descriptor").getString("sha256")))
                    missing.put(json("slot_id", row.slot, "generation", row.generation, "reason", "scope_metadata_missing"));
                else bindings.put(OfflineFallbackJournal.copy(saved.getJSONObject("binding")));
            }
            return json("schema", "device-fallback-status@1", "profile_id", profileId, "owner_epoch", epoch, "authority", authority,
                "capabilities", json("schema", "device-fallback-capabilities@1", "intent_schemas", new JSONArray().put("device-fallback-intent@1").put("device-fallback-intent@2"),
                    "supported_pack_schemas", new JSONArray().put("offline-pack@1").put("offline-pack@2"),
                    "query_kinds", new JSONArray().put("tire").put("vehicle_fitments").put("recall_campaign").put("recall_search"),
                    "filter_contract", "tire-query-filters@1", "unicode_contract", "tire-query-unicode@1", "continuous_policies", false,
                    "max_filters", 16, "max_policies", 16, "max_sources", 10, "max_pending_grants", 16, "max_attempts_per_runtime", 1024,
                    "max_audit_receipts", 64, "grant_ttl_seconds", 300), "policies", policies, "package_bindings", bindings, "missing_package_bindings", missing);
        });
    }
    JSONObject fallbackPolicyPreview(JSONObject request) throws NativeFailure {
        return withFallbackNetwork(network -> fallbackPolicyPreviewLocked(request, network));
    }
    private synchronized JSONObject fallbackPolicyPreviewLocked(JSONObject request, FallbackNetwork network) throws NativeFailure {
        return fallbackTx((connection, state, authority) -> {
            OfflinePackageValidator.keys(request, "mode", "scope", "binding", "allow_same_scope_sync_binding_advance", "expected_profile_id", "expected_owner_epoch",
                "authority", "policy_id", "expected_policy_revision", "expires_in_seconds");
            checkFallbackNetwork(network, authority);
            if (!profileId.equals(request.getString("expected_profile_id")) || epoch(connection) != OfflinePackageValidator.number(request, "expected_owner_epoch", MAX_GENERATION)) throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
            JSONObject pin = OfflinePackageValidator.object(request, "authority"); OfflinePackageValidator.keys(pin, "runtime_session_id", "authority_revision");
            if (!network.runtime.equals(pin.getString("runtime_session_id")) || network.revision != OfflinePackageValidator.number(pin, "authority_revision", MAX_GENERATION)) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
            long revision = OfflinePackageValidator.number(request, "expected_policy_revision", MAX_GENERATION);
            if (request.isNull("policy_id")) { if (revision != 0) throw new NativeFailure("OFFLINE_FALLBACK_POLICY_STALE"); }
            else {
                String id = OfflinePackageValidator.uuid(request, "policy_id"); JSONObject old = OfflineFallbackJournal.entry(state, id);
                if (old == null || old.getJSONObject("policy").getLong("policy_revision") != revision
                    || old.getJSONObject("policy").getLong("owner_epoch") != authority.getLong("owner_epoch")) throw new NativeFailure("OFFLINE_FALLBACK_POLICY_STALE");
            }
            long seconds = OfflinePackageValidator.number(request, "expires_in_seconds", 604800);
            if (seconds < 900) throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
            if (fallbackClock.wall() < state.getLong("last_wall")) throw new NativeFailure("OFFLINE_FALLBACK_CLOCK_ROLLBACK");
            JSONObject choice = OfflineFallbackValues.validateChoice(authority, json("mode", request.get("mode"), "scope", request.get("scope"), "binding", request.get("binding"),
                "allow_same_scope_sync_binding_advance", request.get("allow_same_scope_sync_binding_advance")));
            if (!choice.isNull("binding")) requireFallbackBinding(connection, state, choice.getJSONObject("binding"), authority);
            long wall = fallbackClock.wall(), mono = fallbackClock.monotonic();
            fallbackPreviews.entrySet().removeIf(entry -> wall < entry.getValue().wall || mono < entry.getValue().monotonic || wall - entry.getValue().wall >= 300000 || mono - entry.getValue().monotonic >= 300000);
            if (fallbackPreviews.size() >= 16) throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
            String id = UUID.randomUUID().toString();
            JSONObject frozen = json("id", id, "request", request, "choice", choice, "authority", authority, "wall", wall, "monotonic", mono);
            String fingerprint = OfflineCipher.sha256(OfflineJsonInteger.stringify(frozen).getBytes(StandardCharsets.UTF_8));
            JSONObject value = json("schema", "device-fallback-policy-preview@1", "preview_id", id, "fingerprint", fingerprint,
                "expires_at", OfflineFallbackJournal.stamp(wall + 300000), "policy_expires_at", OfflineFallbackJournal.stamp(wall + seconds * 1000),
                "expected_policy_revision", revision, "profile_id", profileId, "owner_epoch", authority.getLong("owner_epoch"),
                "authority", authority, "proposed_policy", choice, "notice", "仅对所选范围和包版本允许设备历史回退；安装、同步、AI 外发和操作系统任务均需独立许可。来源权限为本机最后成功观察，不代表断网时服务器当前权限。");
            FallbackPreview preview = new FallbackPreview(); preview.wall = wall; preview.monotonic = mono; preview.value = OfflineFallbackJournal.copy(value); preview.request = OfflineFallbackJournal.copy(request);
            fallbackPreviews.put(id, preview); return value;
        });
    }
    JSONObject fallbackPolicyApply(JSONObject request) throws NativeFailure {
        return withFallbackNetwork(network -> fallbackPolicyApplyLocked(request, network));
    }
    private synchronized JSONObject fallbackPolicyApplyLocked(JSONObject request, FallbackNetwork network) throws NativeFailure {
        OfflinePackageValidator.keys(request, "preview_id", "expected_fingerprint", "expected_policy_revision", "allow_continuous_history_fallback");
        OfflinePackageValidator.equal(request, "allow_continuous_history_fallback", true);
        String id = OfflinePackageValidator.uuid(request, "preview_id"); OfflinePackageValidator.hash(request, "expected_fingerprint");
        OfflinePackageValidator.number(request, "expected_policy_revision", MAX_GENERATION);
        FallbackPreview preview = fallbackPreviews.remove(id);
        if (preview == null) throw new NativeFailure("OFFLINE_FALLBACK_PREVIEW_USED");
        // A newly minted Keystore key cannot be rolled back with SQLite. Establish
        // its authenticated owner proof before the policy transaction, after the
        // existing explicit preview consent and private authority are checked.
        withCatalog(connection -> {
            if (!cipher.hasKey()) {
                JSONObject authority = fallbackAuthority.snapshot(profileId, epoch(connection)); checkFallbackNetwork(network, authority);
                long wall = fallbackClock.wall(), mono = fallbackClock.monotonic();
                if (wall < preview.wall || mono < preview.monotonic || wall - preview.wall >= 300000 || mono - preview.monotonic >= 300000)
                    throw new NativeFailure("OFFLINE_FALLBACK_PREVIEW_EXPIRED");
                if (!preview.value.getString("fingerprint").equals(request.getString("expected_fingerprint"))
                    || request.getLong("expected_policy_revision") != preview.value.getLong("expected_policy_revision")
                    || preview.value.getLong("owner_epoch") != authority.getLong("owner_epoch")
                    || preview.value.getJSONObject("authority").getLong("authority_revision") != network.revision)
                    throw new NativeFailure("OFFLINE_FALLBACK_POLICY_STALE");
                ensureOwnerProof(connection);
            }
            return null;
        });
        return fallbackTx((connection, state, authority) -> {
            checkFallbackNetwork(network, authority);
            long wall = fallbackClock.wall(), mono = fallbackClock.monotonic();
            if (wall < preview.wall || mono < preview.monotonic || wall - preview.wall >= 300000 || mono - preview.monotonic >= 300000) throw new NativeFailure("OFFLINE_FALLBACK_PREVIEW_EXPIRED");
            JSONObject value = preview.value, oldRequest = preview.request;
            if (!value.getString("fingerprint").equals(request.getString("expected_fingerprint"))
                || request.getLong("expected_policy_revision") != value.getLong("expected_policy_revision")
                || value.getLong("owner_epoch") != authority.getLong("owner_epoch")
                || !value.getJSONObject("authority").getString("runtime_session_id").equals(network.runtime)
                || value.getJSONObject("authority").getLong("authority_revision") != network.revision) throw new NativeFailure("OFFLINE_FALLBACK_POLICY_STALE");
            String policyId = oldRequest.isNull("policy_id") ? UUID.randomUUID().toString() : oldRequest.getString("policy_id");
            JSONObject existing = OfflineFallbackJournal.entry(state, policyId);
            if ((oldRequest.isNull("policy_id") && existing != null) || (!oldRequest.isNull("policy_id") && (existing == null
                || existing.getJSONObject("policy").getLong("policy_revision") != oldRequest.getLong("expected_policy_revision")
                || existing.getJSONObject("policy").getLong("owner_epoch") != authority.getLong("owner_epoch")))) throw new NativeFailure("OFFLINE_FALLBACK_POLICY_STALE");
            JSONObject choice = OfflineFallbackValues.validateChoice(authority, value.getJSONObject("proposed_policy"));
            if (!choice.isNull("binding")) requireFallbackBinding(connection, state, choice.getJSONObject("binding"), authority);
            JSONObject policy = OfflineFallbackJournal.copy(choice);
            policy.put("schema", "device-fallback-policy@1").put("policy_id", policyId).put("policy_revision", OfflineFallbackJournal.next(oldRequest.getLong("expected_policy_revision")))
                .put("state", "enabled").put("profile_id", profileId).put("owner_epoch", authority.getLong("owner_epoch")).put("owner_scope_id", authority.getString("owner_scope_id"))
                .put("runtime_session_id", choice.getJSONObject("scope").getString("kind").equals("session") ? network.runtime : JSONObject.NULL)
                .put("approved_at", OfflineFallbackJournal.stamp(wall)).put("updated_at", OfflineFallbackJournal.stamp(wall))
                .put("expires_at", value.getString("policy_expires_at")).put("fingerprint", value.getString("fingerprint")).put("reason", JSONObject.NULL);
            ensureOwnerProof(connection); OfflineFallbackJournal.putPolicy(state, policy, authority); saveFallbackState(connection, state);
            checkFallbackNetwork(network, authority); return OfflineFallbackJournal.copy(policy);
        });
    }
    synchronized JSONObject fallbackPolicyChange(JSONObject request, boolean revoke) throws NativeFailure {
        OfflinePackageValidator.keys(request, "policy_id", "expected_policy_revision"); String id = OfflinePackageValidator.uuid(request, "policy_id");
        long revision = OfflinePackageValidator.number(request, "expected_policy_revision", MAX_GENERATION);
        JSONObject result = fallbackTx((connection, state, authority) -> {
            JSONObject entry = OfflineFallbackJournal.entry(state, id);
            if (entry == null || entry.getJSONObject("policy").getLong("owner_epoch") != authority.getLong("owner_epoch")
                || entry.getJSONObject("policy").getLong("policy_revision") != revision) throw new NativeFailure("OFFLINE_FALLBACK_POLICY_STALE");
            JSONObject policy = entry.getJSONObject("policy");
            OfflineFallbackJournal.change(policy, revoke ? "revoked" : "paused", revoke ? "OFFLINE_FALLBACK_POLICY_REVOKED" : "OFFLINE_FALLBACK_POLICY_PAUSED", fallbackClock.wall());
            state.put("revision", OfflineFallbackJournal.next(state.getLong("revision")));
            return OfflineFallbackJournal.copy(policy);
        });
        fallback.invalidatePolicy(id); return result;
    }
    private void requireNotNever(SQLiteConnection connection, JSONObject intent, boolean legacy) throws Exception {
        JSONObject state = fallbackState(connection), authority = fallbackAuthority.snapshot(profileId, epoch(connection));
        if (OfflineFallbackJournal.reconcile(state, authority, fallbackClock.wall()) && cipher.hasKey()) saveFallbackState(connection, state);
        JSONArray entries = state.getJSONArray("policies");
        for (int at = 0; at < entries.length(); at++) {
            JSONObject policy = entries.getJSONObject(at).getJSONObject("policy");
            if (policy.getLong("owner_epoch") == authority.getLong("owner_epoch") && policy.getString("state").equals("enabled")
                && policy.getString("mode").equals("never") && OfflineFallbackValues.matches(policy, intent, legacy))
                throw new NativeFailure("OFFLINE_FALLBACK_NEVER");
        }
    }

    private JSONObject requireIntentAuthority(JSONObject intent, JSONObject authority, FallbackNetwork network) throws Exception {
        checkFallbackNetwork(network, authority);
        return requireIntentAuthorityValues(intent, authority);
    }
    private JSONObject requireIntentAuthorityValues(JSONObject intent, JSONObject authority) throws Exception {
        if (!"last_observed".equals(authority.optString("state"))) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_UNKNOWN");
        JSONObject pin = intent.getJSONObject("authority");
        if (!pin.getString("runtime_session_id").equals(authority.getString("runtime_session_id"))
            || pin.getLong("authority_revision") != authority.getLong("authority_revision"))
            throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
        JSONArray sources = authority.getJSONArray("sources");
        for (int at = 0; at < sources.length(); at++) {
            JSONObject source = sources.getJSONObject(at);
            if (!intent.getString("source_id").equals(source.getString("source_id"))) continue;
            if (intent.getLong("source_access_generation") != source.getLong("access_generation"))
                throw new NativeFailure("OFFLINE_FALLBACK_SOURCE_CHANGED");
            boolean supported = false; JSONArray kinds = source.getJSONArray("query_kinds");
            for (int index = 0; index < kinds.length(); index++) supported |= intent.getString("query_kind").equals(kinds.getString(index));
            if (!supported || !source.getBoolean("can_query") || !source.getBoolean("can_fetch"))
                throw new NativeFailure("OFFLINE_FALLBACK_SOURCE_UNAVAILABLE");
            return source;
        }
        throw new NativeFailure("OFFLINE_FALLBACK_SOURCE_UNAVAILABLE");
    }
    private Row fallbackSlot(SQLiteConnection connection, JSONObject request, JSONObject authority) throws Exception {
        Row row = expected(connection, request, true, false); JSONObject meta = metadata(row), descriptor = meta.getJSONObject("descriptor");
        if (!profileId.equals(request.getString("expected_profile_id")) || request.getLong("expected_owner_epoch") != authority.getLong("owner_epoch")
            || !request.getString("expected_sha256").equals(descriptor.getString("sha256"))) throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
        if (meta.getLong("created_epoch") != authority.getLong("owner_epoch") || meta.getLong("allowed_epoch") != authority.getLong("owner_epoch"))
            throw new NativeFailure("OFFLINE_OWNER_LOCKED");
        if (!authority.getString("owner_scope_id").equals(descriptor.getString("owner_scope_id"))) throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
        return row;
    }
    private static int fallbackPriority(JSONObject policy) throws Exception {
        String mode = policy.getString("mode");
        return mode.equals("never") ? 0 : mode.equals("ask") ? 1 : mode.equals("query_allow") ? 2 : mode.equals("source_allow") ? 3 : 4;
    }
    private JSONObject selectedFallbackPolicy(JSONObject state, JSONObject intent, JSONObject request, JSONObject authority) throws Exception {
        JSONObject selected = null; JSONArray entries = state.getJSONArray("policies");
        for (int at = 0; at < entries.length(); at++) {
            JSONObject candidate = entries.getJSONObject(at).getJSONObject("policy");
            if (!candidate.getString("state").equals("enabled") || candidate.getLong("owner_epoch") != authority.getLong("owner_epoch")
                || !profileId.equals(candidate.getString("profile_id")) || !OfflineFallbackValues.matches(candidate, intent, false)) continue;
            if (!candidate.isNull("binding")) {
                JSONObject binding = candidate.getJSONObject("binding");
                if (!binding.getString("slot_id").equals(request.getString("slot_id")) || binding.getLong("generation") != request.getLong("expected_generation")
                    || !binding.getString("sha256").equals(request.getString("expected_sha256"))) continue;
            }
            if (selected == null) selected = candidate;
            else {
                int priority = Integer.compare(fallbackPriority(candidate), fallbackPriority(selected));
                int approval = Long.compare(OfflineFallbackJournal.time(candidate.getString("approved_at")), OfflineFallbackJournal.time(selected.getString("approved_at")));
                if (priority < 0 || (priority == 0 && (approval > 0 || (approval == 0 && candidate.getString("policy_id").compareTo(selected.getString("policy_id")) < 0)))) selected = candidate;
            }
        }
        return selected;
    }
    private void fallbackNeverGate(SQLiteConnection connection, JSONObject intent) throws Exception {
        if ("never".equals(intent.optString("fallback_policy"))) throw new NativeFailure("OFFLINE_FALLBACK_NEVER");
        requireNotNever(connection, intent, false);
    }
    private void checkObservedQueryDenial(JSONObject intent) throws NativeFailure {
        if (fallbackHttp != null) fallbackHttp.checkFallbackDenial(intent);
    }
    private interface FallbackPublicationWork<T> { T run() throws Exception; }
    private <T> T withFallbackPublication(FallbackPublicationWork<T> work) throws NativeFailure {
        NativeHttpBridge bridge = attachedFallbackHttp();
        try {
            if (bridge == null) return work.run();
            NativeHttpBridge.FallbackPublicationFence fence = bridge.captureFallbackPublication();
            return bridge.publishFallback(fence, work::run);
        } catch (NativeFailure failure) { throw failure; }
        catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
    }
    private void requireFallbackPolicy(SQLiteConnection connection, JSONObject state, JSONObject intent, JSONObject request,
        JSONObject authority, JSONObject authorization) throws Exception {
        if (authorization.getString("type").equals("explicit_once")) return;
        JSONObject policy = selectedFallbackPolicy(state, intent, request, authority);
        if (policy == null || !policy.getString("policy_id").equals(authorization.getString("policy_id"))
            || policy.getLong("policy_revision") != authorization.getLong("policy_revision") || policy.isNull("binding"))
            throw new NativeFailure("OFFLINE_FALLBACK_POLICY_CHANGED");
        requireFallbackBinding(connection, state, policy.getJSONObject("binding"), authority);
    }

    JSONObject authorizeFallback(JSONObject request) throws NativeFailure {
        try { OfflineFallbackValues.slotRequest(request, false); }
        catch (NativeFailure failure) { throw failure; }
        catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
        return withFallbackPublication(() -> authorizeFallbackLocked(request, observedFallbackNetwork()));
    }
    private synchronized JSONObject authorizeFallbackLocked(JSONObject request, FallbackNetwork network) throws NativeFailure {
        OfflineFallbackGrant.Pending[] preparedGrant = new OfflineFallbackGrant.Pending[1];
        JSONObject result = fallbackTx((connection, state, authority) -> {
            JSONObject intent = request.getJSONObject("intent"); fallback.checkCapacity(intent, false);
            try { checkObservedQueryDenial(intent); fallbackNeverGate(connection, intent); }
            catch (NativeFailure failure) {
                if (!failure.code.equals("OFFLINE_FALLBACK_NEVER")) throw failure;
                fallback.burnAttempt(intent);
                return json("schema", "device-fallback-authorization@1", "state", "blocked", "reason", failure.code, "grant", null);
            }
            requireIntentAuthority(intent, authority, network); fallbackSlot(connection, request, authority);
            JSONObject policy = selectedFallbackPolicy(state, intent, request, authority);
            if (policy == null || policy.getString("mode").equals("ask"))
                return json("schema", "device-fallback-authorization@1", "state", "ask", "reason", "OFFLINE_FALLBACK_EXPLICIT_REQUIRED", "grant", null);
            requireFallbackBinding(connection, state, policy.getJSONObject("binding"), authority); fallback.checkCapacity(intent, true);
            JSONObject authorization = json("type", "policy_once", "policy_id", policy.getString("policy_id"), "policy_revision", policy.getLong("policy_revision"));
            OfflineFallbackGrant.Pending prepared = fallback.receiptV2(intent, request, profileId, authority.getLong("owner_epoch"), authorization, true);
            fallbackAudit(connection, prepared.receipt);
            preparedGrant[0] = prepared;
            return json("schema", "device-fallback-authorization@1", "state", "allowed", "reason", null,
                "grant", prepared.receipt);
        });
        // Registration follows the durable transaction, including journal reconciliation.
        try { if (preparedGrant[0] != null) fallback.register(preparedGrant[0]); }
        catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
        return result;
    }

    private File blobFile(String identifier) throws Exception {
        if (identifier == null || !identifier.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.sealed")) {
            throw new NativeFailure("OFFLINE_CORRUPT");
        }
        File file = new File(blobs, identifier);
        if (!file.getCanonicalPath().equals(file.getAbsolutePath())) throw new NativeFailure("OFFLINE_CORRUPT");
        return file;
    }

    private static byte[] bytes(File file) throws Exception {
        long length = file.length();
        if (length < 1 || length > OfflinePackageValidator.MAX_BYTES + 128) throw new NativeFailure("OFFLINE_CORRUPT");
        try (FileInputStream input = new FileInputStream(file)) {
            ByteArrayOutputStream output = new ByteArrayOutputStream((int) length);
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > length) throw new NativeFailure("OFFLINE_CORRUPT");
                output.write(buffer, 0, count);
            }
            byte[] result = output.toByteArray();
            if (result.length != length) throw new NativeFailure("OFFLINE_CORRUPT");
            return result;
        }
    }

    private JSONObject envelope(Row row) throws Exception {
        try {
            JSONObject descriptor = metadata(row).getJSONObject("descriptor");
            byte[] raw = cipher.open(bytes(blobFile(row.blob)), purpose(row, "body"));
            return OfflinePackageValidator.envelope(raw, descriptor);
        } catch (NativeFailure failure) { throw failure; }
        catch (Exception ignored) { throw new NativeFailure("OFFLINE_CORRUPT"); }
    }

    private static void syncDirectory(File directory) throws Exception {
        // O_DIRECTORY is not exposed by Android's public SDK. The path is an
        // app-owned canonical directory, never supplied through IPC.
        if (!directory.isDirectory() || !directory.getCanonicalPath().equals(directory.getAbsolutePath())) {
            throw new NativeFailure("OFFLINE_CORRUPT");
        }
        FileDescriptor descriptor = Os.open(directory.getAbsolutePath(), OsConstants.O_RDONLY, 0);
        try { Os.fsync(descriptor); } finally { Os.close(descriptor); }
    }

    private void cleanup(SQLiteConnection connection) throws Exception {
        Set<String> referenced = new HashSet<>();
        try (SQLiteStatement statement = connection.prepare("SELECT blob_id FROM slots WHERE blob_id IS NOT NULL")) {
            while (statement.step()) referenced.add(statement.getText(0));
        }
        File[] files = blobs.listFiles();
        if (files == null) throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE");
        for (File file : files) {
            String name = file.getName();
            if (name.matches("[0-9a-f-]{36}\\.sealed") && !referenced.contains(name)) {
                File checked = blobFile(name);
                if (!checked.delete() && checked.exists()) throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE");
            }
        }
    }

    synchronized JSONObject install(JSONObject request, JSONObject descriptor, byte[] originalBytes) throws NativeFailure {
        return install(request, descriptor, originalBytes, () -> true);
    }

    synchronized JSONObject install(JSONObject request, JSONObject descriptor, byte[] originalBytes,
                                   BooleanSupplier stillCurrent) throws NativeFailure {
        current(stillCurrent);
        OfflinePackageValidator.installRequest(request);
        OfflinePackageValidator.descriptor(descriptor, request);
        JSONObject material = OfflinePackageValidator.envelope(originalBytes, descriptor);
        // Verify the real native FTS parser/index accepts every document before
        // publishing a new generation. The indexed data never reaches disk.
        try (SQLiteConnection memory = index(material)) { /* Validated staging. */ }
        catch (NativeFailure failure) { throw failure; }
        catch (Exception ignored) { throw new NativeFailure("OFFLINE_SEARCH_UNAVAILABLE"); }
        current(stillCurrent);
        return withCatalog(connection -> {
            current(stillCurrent);
            cleanup(connection);
            ensureOwnerProof(connection);
            OfflineSql.execute(connection, "BEGIN IMMEDIATE");
            File staged = null; boolean committed = false;
            try {
                String slotId = OfflinePackageValidator.uuid(request, "slot_id");
                Row prior = row(connection, slotId);
                long generation = prior == null ? 0 : prior.generation;
                if (generation != request.getLong("expected_generation")) throw new NativeFailure("OFFLINE_STALE_GENERATION");
                if (generation >= MAX_GENERATION) throw new NativeFailure("OFFLINE_GENERATION_EXHAUSTED");
                List<Row> active = active(connection);
                long previousBytes = prior == null || prior.blob == null ? 0 : metadata(prior).getJSONObject("descriptor").getLong("byte_count");
                if (active.size() + (prior == null || prior.blob == null ? 1 : 0) > MAX_SLOTS ||
                    total(active) - previousBytes + originalBytes.length > MAX_STORE_BYTES) throw new NativeFailure("OFFLINE_STORE_LIMIT");
                long epoch = epoch(connection);
                if (prior != null && prior.blob != null && metadata(prior).getLong("allowed_epoch") != epoch) {
                    throw new NativeFailure("OFFLINE_OWNER_LOCKED");
                }
                current(stillCurrent);
                Row next = new Row(); next.slot = slotId; next.generation = generation + 1;
                next.blob = UUID.randomUUID() + ".sealed";
                next.metadata = json("descriptor", new JSONObject(descriptor.toString()), "installed_at", Instant.now().toString(),
                    "created_epoch", epoch, "allowed_epoch", epoch, "title", "设备历史证据");
                next.sealedMetadata = cipher.seal(next.metadata.toString().getBytes(StandardCharsets.UTF_8), purpose(next, "metadata"));
                byte[] sealed = cipher.seal(originalBytes, purpose(next, "body"));
                staged = blobFile(next.blob);
                if (!staged.createNewFile()) throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE");
                try (FileOutputStream output = new FileOutputStream(staged)) { output.write(sealed); output.getFD().sync(); }
                syncDirectory(blobs);
                OfflineSql.execute(connection, "INSERT INTO slots(slot_id,generation,blob_id,metadata) VALUES(?,?,?,?) ON CONFLICT(slot_id) DO UPDATE SET generation=excluded.generation,blob_id=excluded.blob_id,metadata=excluded.metadata",
                    next.slot, next.generation, next.blob, next.sealedMetadata);
                JSONObject fallbackState = fallbackState(connection);
                OfflineFallbackJournal.putBinding(fallbackState, slot(next, epoch), epoch, material, false, fallbackClock.wall());
                saveFallbackState(connection, fallbackState);
                current(stillCurrent);
                OfflineSql.execute(connection, "COMMIT"); committed = true;
                cleanupAfterCommit(connection);
                return slot(next, epoch);
            } finally {
                if (!committed) {
                    OfflineSql.execute(connection, "ROLLBACK");
                    if (staged != null) staged.delete();
                }
            }
        });
    }

    private static void current(BooleanSupplier stillCurrent) throws NativeFailure {
        if (stillCurrent == null || !stillCurrent.getAsBoolean()) throw new NativeFailure("OFFLINE_OPERATION_CANCELLED");
    }

    private void cleanupAfterCommit(SQLiteConnection connection) {
        // Publication already committed. A cleanup problem must not be reported
        // as failed installation after changing the active generation. The next
        // install must successfully clean owned orphans before staging again.
        try { cleanup(connection); } catch (Exception ignored) { /* Ciphertext only; next startup retries. */ }
    }

    private static SQLiteConnection memoryIndex() throws NativeFailure {
        SQLiteConnection memory = null;
        try {
            memory = new BundledSQLiteDriver().open(":memory:");
            OfflineSql.execute(memory, "PRAGMA temp_store=MEMORY");
            if (OfflineSql.scalar(memory, "SELECT sqlite_compileoption_used('ENABLE_FTS5')") != 1 ||
                OfflineSql.scalar(memory, "PRAGMA temp_store") != 2) throw new NativeFailure("OFFLINE_FTS5_UNAVAILABLE");
            OfflineSql.execute(memory, "CREATE VIRTUAL TABLE probe USING fts5(value)");
            OfflineSql.execute(memory, "INSERT INTO probe(value) VALUES(?)", "fts5 probe");
            if (OfflineSql.scalar(memory, "SELECT count(*) FROM probe WHERE probe MATCH ?", "\"probe\"") != 1) {
                throw new NativeFailure("OFFLINE_FTS5_UNAVAILABLE");
            }
            OfflineSql.execute(memory, "DROP TABLE probe");
            OfflineSql.execute(memory, "CREATE TABLE docs (ordinal INTEGER PRIMARY KEY, id TEXT UNIQUE, kind TEXT, document TEXT)");
            OfflineSql.execute(memory, "CREATE VIRTUAL TABLE search_docs USING fts5(terms,tokenize='unicode61 remove_diacritics 2')");
            return memory;
        } catch (Exception ignored) {
            if (memory != null) memory.close();
            throw new NativeFailure("OFFLINE_FTS5_UNAVAILABLE");
        }
    }

    private static String cjkTerms(String value) {
        StringBuilder terms = new StringBuilder(value);
        value.codePoints().filter(code -> Character.UnicodeScript.of(code) == Character.UnicodeScript.HAN)
            .forEach(code -> terms.append(' ').appendCodePoint(code));
        return terms.toString();
    }

    private static String expression(String query) {
        Set<String> tokens = new LinkedHashSet<>(); StringBuilder word = new StringBuilder();
        query.codePoints().forEach(code -> {
            if (Character.UnicodeScript.of(code) == Character.UnicodeScript.HAN) {
                if (word.length() > 0) { tokens.add(word.toString()); word.setLength(0); }
                tokens.add(new String(Character.toChars(code)));
            } else if (Character.isLetterOrDigit(code)) word.appendCodePoint(code);
            else if (word.length() > 0) { tokens.add(word.toString()); word.setLength(0); }
        });
        if (word.length() > 0) tokens.add(word.toString());
        List<String> quoted = new ArrayList<>();
        for (String token : tokens) quoted.add("\"" + token.replace("\"", "\"\"") + "\"");
        return String.join(" AND ", quoted);
    }

    private static SQLiteConnection index(JSONObject envelope) throws Exception {
        SQLiteConnection memory = memoryIndex();
        try {
            JSONArray documents = envelope.getJSONArray("documents");
            OfflineSql.execute(memory, "BEGIN");
            for (int i = 0; i < documents.length(); i++) {
                JSONObject doc = documents.getJSONObject(i);
                OfflineSql.execute(memory, "INSERT INTO docs(ordinal,id,kind,document) VALUES(?,?,?,?)", i + 1,
                    doc.getString("id"), doc.getString("kind"), doc.toString());
                OfflineSql.execute(memory, "INSERT INTO search_docs(rowid,terms) VALUES(?,?)", i + 1,
                    cjkTerms(doc.getString("title") + " " + doc.getString("text") + " " + doc.getJSONObject("facets")));
            }
            OfflineSql.execute(memory, "COMMIT");
            return memory;
        } catch (Exception failure) { memory.close(); throw failure; }
    }

    synchronized JSONObject search(JSONObject request) throws NativeFailure {
        slotRequest(request, request.has("kind") ? new String[] {"query", "kind", "limit", "offset"} : new String[] {"query", "limit", "offset"});
        String query = OfflinePackageValidator.text(request, "query", 500);
        String kind = request.has("kind") ? OfflinePackageValidator.text(request, "kind", 16) : null;
        if (kind != null && !KINDS.contains(kind)) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        long limit = OfflinePackageValidator.number(request, "limit", 50), offset = OfflinePackageValidator.number(request, "offset", 4000);
        if (limit < 1) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        return withCatalog(connection -> {
            Row row = expected(connection, request, true);
            JSONObject material = envelope(row); backfillFallbackBinding(connection, row, material); JSONArray items = new JSONArray();
            String match = expression(query);
            boolean punctuationOnly = !query.trim().isEmpty() && match.isEmpty();
            try (SQLiteConnection memory = index(material)) {
                String where = punctuationOnly ? " WHERE 0" : match.isEmpty() ? " WHERE 1" : " WHERE search_docs MATCH ?";
                List<Object> parameters = new ArrayList<>();
                if (!match.isEmpty()) parameters.add(match);
                if (kind != null) { where += " AND docs.kind=?"; parameters.add(kind); }
                String from = " FROM docs JOIN search_docs ON search_docs.rowid=docs.ordinal";
                long total = OfflineSql.scalar(memory, "SELECT count(*)" + from + where, parameters.toArray());
                parameters.add(limit); parameters.add(offset);
                try (SQLiteStatement statement = OfflineSql.statement(memory, "SELECT docs.document" + from + where + " ORDER BY docs.ordinal LIMIT ? OFFSET ?", parameters.toArray())) {
                    while (statement.step()) items.put(new JSONObject(statement.getText(0)));
                }
                return json("data_state", "local_snapshot", "slot", slot(row, epoch(connection)), "items", items,
                    "total", total, "offset", offset, "limit", limit, "has_more", offset + items.length() < total);
            }
        });
    }

    synchronized JSONObject read(JSONObject request) throws NativeFailure {
        slotRequest(request, "document_id");
        String identifier = OfflinePackageValidator.text(request, "document_id", 256);
        return withCatalog(connection -> {
            Row row = expected(connection, request, true); JSONObject material = envelope(row);
            backfillFallbackBinding(connection, row, material);
            JSONObject found = null, member = null, context = null;
            JSONArray docs = material.getJSONArray("documents");
            for (int i = 0; i < docs.length(); i++) if (identifier.equals(docs.getJSONObject(i).getString("id"))) { found = docs.getJSONObject(i); break; }
            if (found == null) throw new NativeFailure("OFFLINE_DOCUMENT_NOT_FOUND");
            if (!found.isNull("member_key")) {
                JSONArray members = material.getJSONArray("members");
                for (int i = 0; i < members.length(); i++) if (found.getString("member_key").equals(members.getJSONObject(i).getString("key"))) { member = members.getJSONObject(i); break; }
            } else {
                JSONArray contexts = material.getJSONArray("contexts");
                for (int i = 0; i < contexts.length(); i++) if (found.getString("context_id").equals(contexts.getJSONObject(i).getString("id"))) { context = contexts.getJSONObject(i); break; }
            }
            JSONObject result = json("data_state", "local_snapshot", "slot", slot(row, epoch(connection)), "document", found,
                "member", member, "context", context);
            if (material.getString("schema").equals("offline-pack@2")) {
                result.put("schema", "offline-read-result@2").put("package_schema", "offline-pack@2");
                return OfflineFallbackWire.encode(result);
            }
            return result;
        });
    }

    synchronized JSONObject remove(JSONObject request) throws NativeFailure {
        slotRequest(request);
        return withCatalog(connection -> {
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                Row row = row(connection, OfflinePackageValidator.uuid(request, "slot_id"));
                if (row == null || row.generation != request.getLong("expected_generation")) throw new NativeFailure("OFFLINE_STALE_GENERATION");
                if (row.blob == null) throw new NativeFailure("OFFLINE_NOT_FOUND");
                if (row.generation >= MAX_GENERATION) throw new NativeFailure("OFFLINE_GENERATION_EXHAUSTED");
                // Deletion is allowed for a locked or unreadable ciphertext;
                // it needs the exact opaque slot generation, never the key.
                long generation = row.generation + 1;
                OfflineSql.execute(connection, "UPDATE slots SET generation=?,blob_id=NULL,metadata=NULL WHERE slot_id=? AND generation=?", generation, row.slot, row.generation);
                try {
                    JSONObject fallbackState = fallbackState(connection);
                    OfflineFallbackJournal.removeBinding(fallbackState, row.slot, fallbackClock.wall());
                    if (cipher.hasKey()) saveFallbackState(connection, fallbackState);
                } catch (NativeFailure failure) {
                    // Exact opaque removal remains possible when an old encrypted sidecar/key is unreadable.
                    if (!List.of("OFFLINE_KEY_MISSING", "OFFLINE_CORRUPT", "OFFLINE_FALLBACK_STATE_INVALID").contains(failure.code)) throw failure;
                }
                OfflineSql.execute(connection, "COMMIT"); committed = true; cleanupAfterCommit(connection);
                return json("removed", true, "slot_id", row.slot, "generation", generation);
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }

    private void fallbackAudit(SQLiteConnection connection, JSONObject receipt) throws Exception {
        String id = receipt.getString("id");
        byte[] sealed = cipher.seal(OfflineJsonInteger.stringify(receipt).getBytes(StandardCharsets.UTF_8), "fallback-audit@1:" + id);
        OfflineSql.execute(connection, "INSERT INTO fallback_audit(id,value) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value", id, sealed);
        OfflineSql.execute(connection, "DELETE FROM fallback_audit WHERE rowid NOT IN (SELECT rowid FROM fallback_audit ORDER BY rowid DESC LIMIT 64)");
    }

    JSONObject decideFallback(JSONObject request) throws NativeFailure {
        JSONObject intent = OfflineFallbackGrant.decideRequest(request);
        if ("device-fallback-intent@2".equals(intent.optString("schema")))
            return withFallbackPublication(() -> decideFallbackV2Locked(request, observedFallbackNetwork()));
        return withFallbackPublication(() -> decideFallbackLegacyLocked(request, intent));
    }
    private synchronized JSONObject decideFallbackLegacyLocked(JSONObject request, JSONObject intent) throws NativeFailure {
        return withCatalog(connection -> {
            boolean allow = request.getString("decision").equals("allow");
            fallback.checkCapacity(intent, allow);
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                // A decision reads authenticated metadata only. Body/release/index
                // validation belongs after the one-shot consume has been burned.
                long currentEpoch = epoch(connection); Row row = expected(connection, request, true, false);
                JSONObject metadata = metadata(row), descriptor = metadata.getJSONObject("descriptor");
                if (!profileId.equals(request.getString("expected_profile_id")) || currentEpoch != request.getLong("expected_owner_epoch") ||
                    !descriptor.getString("sha256").equals(request.getString("expected_sha256"))) throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
                if (metadata.getLong("created_epoch") != currentEpoch) throw new NativeFailure("OFFLINE_OWNER_LOCKED");
                try { checkObservedQueryDenial(intent); requireNotNever(connection, intent, true); }
                catch (NativeFailure failure) {
                    if ("OFFLINE_FALLBACK_NEVER".equals(failure.code)) fallback.burnAttempt(intent);
                    throw failure;
                }
                OfflineFallbackGrant.Pending prepared = fallback.receipt(intent, request, profileId, currentEpoch);
                JSONObject receipt = prepared.receipt;
                fallbackAudit(connection, receipt); // Does not decrypt body or build FTS.
                OfflineSql.execute(connection, "COMMIT"); committed = true; fallback.register(prepared);
                return receipt;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }

    private synchronized JSONObject decideFallbackV2Locked(JSONObject request, FallbackNetwork network) throws NativeFailure {
        OfflineFallbackGrant.Pending[] preparedGrant = new OfflineFallbackGrant.Pending[1];
        JSONObject result = fallbackTx((connection, state, authority) -> {
            JSONObject intent = request.getJSONObject("intent"); boolean allow = request.getString("decision").equals("allow");
            fallback.checkCapacity(intent, allow);
            try { checkObservedQueryDenial(intent); fallbackNeverGate(connection, intent); }
            catch (NativeFailure failure) { if (failure.code.equals("OFFLINE_FALLBACK_NEVER")) fallback.burnAttempt(intent); throw failure; }
            requireIntentAuthority(intent, authority, network); fallbackSlot(connection, request, authority);
            OfflineFallbackGrant.Pending prepared = fallback.receiptV2(intent, request, profileId, authority.getLong("owner_epoch"), json("type", "explicit_once"), allow);
            fallbackAudit(connection, prepared.receipt); preparedGrant[0] = prepared; return prepared.receipt;
        });
        try { fallback.register(preparedGrant[0]); }
        catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
        return result;
    }

    private static final class FallbackConsumption {
        OfflineFallbackGrant.Pending pending;
        JSONObject receipt, intent, slotRequest, result;
        FallbackNetwork network;
        long documentVersion;
        boolean v2;
    }
    JSONObject consumeFallback(JSONObject request) throws NativeFailure {
        String id = OfflineFallbackGrant.requestId(request, true);
        NativeHttpBridge bridge = attachedFallbackHttp();
        try {
            NativeHttpBridge.FallbackPublicationFence fence = bridge == null ? null : bridge.captureFallbackPublication();
            FallbackConsumption consumed = bridge == null ? claimFallbackLocked(request, id)
                : bridge.publishFallback(fence, () -> claimFallbackLocked(request, id));
            // Package work holds only Store/catalog locks. HTTP can observe a denial
            // while this already-authorized body is being checked and projected.
            projectFallbackLocked(consumed);
            return bridge == null ? publishConsumedFallbackLocked(consumed)
                : bridge.publishFallback(fence, () -> publishConsumedFallbackLocked(consumed));
        } catch (NativeFailure failure) { throw failure; }
        catch (Exception failure) { throw new NativeFailure("OFFLINE_FALLBACK_INVALID"); }
    }
    private synchronized FallbackConsumption claimFallbackLocked(JSONObject request, String id) throws NativeFailure {
        return withCatalog(connection -> {
            FallbackConsumption consumed = new FallbackConsumption();
            consumed.intent = OfflineFallbackGrant.intent(request.getJSONObject("intent"));
            consumed.v2 = "device-fallback-intent@2".equals(consumed.intent.optString("schema"));
            consumed.pending = fallback.take(id, consumed.intent); consumed.receipt = fallback.consumed(consumed.pending);
            consumed.network = fallbackNetwork; consumed.documentVersion = fallbackDocumentVersion;
            consumed.slotRequest = json("slot_id", consumed.receipt.getString("slot_id"), "expected_generation", consumed.receipt.getLong("generation"),
                "expected_sha256", consumed.receipt.getString("package_sha256"), "expected_profile_id", profileId,
                "expected_owner_epoch", consumed.receipt.getLong("owner_epoch"));
            // This COMMIT is independent of subsequent body/gate failures.
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean audited = false;
            try { fallbackAudit(connection, consumed.receipt); OfflineSql.execute(connection, "COMMIT"); audited = true; }
            finally { if (!audited) OfflineSql.execute(connection, "ROLLBACK"); }
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                checkConsumedFallback(connection, consumed, true);
                OfflineSql.execute(connection, "COMMIT"); committed = true; return consumed;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }
    private Row checkConsumedFallback(SQLiteConnection connection, FallbackConsumption consumed, boolean privateHttpGate) throws Exception {
        long currentEpoch = epoch(connection);
        if (consumed.documentVersion != fallbackDocumentVersion) throw new NativeFailure("OFFLINE_FALLBACK_USED");
        if (!profileId.equals(consumed.receipt.getString("profile_id")) || currentEpoch != consumed.receipt.getLong("owner_epoch"))
            throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
        fallback.checkExpiry(consumed.pending);
        if (privateHttpGate) checkObservedQueryDenial(consumed.intent);
        if (consumed.v2) {
            JSONObject authority = fallbackAuthority.snapshot(profileId, currentEpoch), state = fallbackState(connection);
            if (OfflineFallbackJournal.reconcile(state, authority, fallbackClock.wall())) saveFallbackState(connection, state);
            fallbackNeverGate(connection, consumed.intent);
            if (privateHttpGate) requireIntentAuthority(consumed.intent, authority, consumed.network);
            else requireIntentAuthorityValues(consumed.intent, authority);
            Row row = fallbackSlot(connection, consumed.slotRequest, authority);
            requireFallbackPolicy(connection, state, consumed.intent, consumed.slotRequest, authority, consumed.receipt.getJSONObject("fallback_authorization"));
            return row;
        }
        requireNotNever(connection, consumed.intent, true);
        Row row = expected(connection, consumed.slotRequest, true, false); JSONObject meta = metadata(row);
        if (meta.getLong("created_epoch") != currentEpoch) throw new NativeFailure("OFFLINE_OWNER_LOCKED");
        if (!meta.getJSONObject("descriptor").getString("sha256").equals(consumed.receipt.getString("package_sha256")))
            throw new NativeFailure("OFFLINE_FALLBACK_MISMATCH");
        if (meta.getJSONObject("descriptor").getString("schema").equals("offline-pack-descriptor@2"))
            throw new NativeFailure("OFFLINE_FALLBACK_UNSUPPORTED");
        return row;
    }
    private synchronized void projectFallbackLocked(FallbackConsumption consumed) throws NativeFailure {
        withCatalog(connection -> {
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                Row row = checkConsumedFallback(connection, consumed, false); requireRelease(connection, row);
                JSONObject material = envelope(row);
                consumed.result = consumed.v2 ? OfflineFallbackSelection.result(material, consumed.intent, consumed.receipt, slot(row, epoch(connection)))
                    : json("schema", "device-fallback-result@1", "data_state", "local_snapshot", "fallback_consent", "local_once",
                        "grant", consumed.receipt, "slot", slot(row, epoch(connection)), "members", OfflineFallbackGrant.matching(material, consumed.intent),
                        "complete_query_result", false,
                        "notice", "仅为所选设备包的精确匹配历史子集；附带字段依据是整包历史上下文，可能包含其他来源，不表示完整在线结果、当前参数或AI授权。");
                if (OfflineJsonInteger.stringify(consumed.result).getBytes(StandardCharsets.UTF_8).length > OfflinePackageValidator.MAX_BYTES)
                    throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
                OfflineSql.execute(connection, "COMMIT"); committed = true; return null;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }
    private synchronized JSONObject publishConsumedFallbackLocked(FallbackConsumption consumed) throws NativeFailure {
        return withCatalog(connection -> {
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                checkConsumedFallback(connection, consumed, true);
                OfflineSql.execute(connection, "COMMIT"); committed = true; return consumed.result;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }

    synchronized JSONObject revokeFallback(JSONObject request) throws NativeFailure {
        String id = OfflineFallbackGrant.requestId(request, false);
        return withCatalog(connection -> {
            OfflineFallbackGrant.Pending pending = fallback.revoke(id);
            if (pending != null) {
                JSONObject receipt = OfflineFallbackGrant.copy(pending.receipt); receipt.put("state", "revoked");
                OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
                try { fallbackAudit(connection, receipt); OfflineSql.execute(connection, "COMMIT"); committed = true; }
                finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
            }
            return json("revoked", true, "grant_id", id);
        });
    }

    synchronized long resetOwnerEpoch() throws NativeFailure {
        fallback.clear();
        fallbackAuthority.reset();
        fallbackNetwork = null; fallbackPreviews.clear();
        return withCatalog(connection -> {
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                long epoch = epoch(connection);
                if (epoch >= MAX_GENERATION) throw new NativeFailure("OFFLINE_GENERATION_EXHAUSTED");
                boolean authenticated = cipher.hasKey();
                byte[] proof = authenticated ? cipher.seal(json("epoch", epoch + 1).toString().getBytes(StandardCharsets.UTF_8), "owner-state@1") : null;
                OfflineSql.execute(connection, "UPDATE owner_state SET epoch=?,proof=? WHERE id=1", epoch + 1, proof);
                if (authenticated) {
                    try {
                        JSONObject fallbackState = fallbackState(connection);
                        OfflineFallbackJournal.reconcile(fallbackState, fallbackAuthority.snapshot(profileId, epoch + 1), fallbackClock.wall());
                        saveFallbackState(connection, fallbackState);
                    } catch (NativeFailure failure) {
                        if (!"OFFLINE_FALLBACK_STATE_INVALID".equals(failure.code)) throw failure;
                    }
                    try {
                        JSONObject state = syncState(connection);
                        for(int i=0;i<state.getJSONArray("policies").length();i++) {
                            JSONObject policy = state.getJSONArray("policies").getJSONObject(i).getJSONObject("policy");
                            policy.put("state", "revoked"); policy.put("policy_revision", OfflineSyncValues.increment(policy.getLong("policy_revision")));
                            policy.put("next_due_at", JSONObject.NULL); policy.put("reason", "OFFLINE_SYNC_OWNER_CHANGED"); policy.put("updated_at", OfflineSyncValues.now());
                        }
                        OfflineSyncValues.cancel(state, null, "OFFLINE_SYNC_OWNER_CHANGED"); saveSync(connection,state);
                    } catch(NativeFailure failure) {
                        // Unreadable sidecar remains closed and retained. The committed
                        // owner epoch still durably invalidates every old policy anchor.
                        if(!"OFFLINE_SYNC_STATE_INVALID".equals(failure.code)) throw failure;
                    }
                }
                OfflineSql.execute(connection, "COMMIT"); committed = true; return epoch + 1;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }

    synchronized JSONObject unlockPreviousOwner(JSONObject request) throws NativeFailure {
        slotRequest(request, "allow_previous_owner");
        OfflinePackageValidator.equal(request, "allow_previous_owner", true);
        return withCatalog(connection -> {
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                Row row = expected(connection, request, false); envelope(row); // Wrong key/corrupt copy never becomes readable.
                long epoch = epoch(connection); JSONObject metadata = metadata(row); metadata.put("allowed_epoch", epoch);
                row.sealedMetadata = cipher.seal(metadata.toString().getBytes(StandardCharsets.UTF_8), purpose(row, "metadata"));
                OfflineSql.execute(connection, "UPDATE slots SET metadata=? WHERE slot_id=? AND generation=?", row.sealedMetadata, row.slot, row.generation);
                OfflineSql.execute(connection, "COMMIT"); committed = true; return slot(row, epoch);
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }

    synchronized void invalidateFallbackGrants() { fallbackDocumentVersion++; fallback.clear(); fallbackPreviews.clear(); syncPreviews.clear(); }

    @Override public synchronized void close() { fallback.clear(); fallbackPreviews.clear(); syncPreviews.clear(); closed = true; }

    private JSONObject releaseCheck(SQLiteConnection connection, Row row, boolean force) throws Exception {
        String hash = null;
        try { hash = metadata(row).getJSONObject("descriptor").getString("sha256"); } catch (Exception ignored) { /* Unknown metadata cannot supply a SHA. */ }
        if (!force && cipher.hasKey()) {
            try (SQLiteStatement saved = OfflineSql.statement(connection, "SELECT generation,value FROM release_checks WHERE slot_id=?", row.slot)) {
                if (saved.step() && saved.getLong(0) == row.generation) {
                    JSONObject check = OfflinePackageValidator.parse(cipher.open(saved.getBlob(1), "release-check@1:" + row.slot + ":" + row.generation));
                    OfflinePackageValidator.keys(check, "slot_id", "generation", "sha256", "host_build", "validator_version", "checked_at", "state", "reason");
                    if (row.slot.equals(check.optString("slot_id")) && row.generation == check.optLong("generation") &&
                        java.util.Objects.equals(hash, check.isNull("sha256") ? null : check.optString("sha256")) &&
                        BuildConfig.OFFLINE_HOST_BUILD.equals(check.optString("host_build")) && OfflineSyncValues.VALIDATOR.equals(check.optString("validator_version")) &&
                        (("passed".equals(check.optString("state")) && hash != null && check.isNull("reason")) ||
                         ("failed".equals(check.optString("state")) && check.optString("reason").matches("[A-Z_]{1,100}")))) return check;
                }
            } catch (Exception ignored) { /* Corrupt/old check is not evidence; validate the original again. */ }
        }
        String reason = null;
        try {
            JSONObject descriptor = metadata(row).getJSONObject("descriptor");
            JSONObject request = json("package_id", descriptor.getString("id"), "expected_sha256", descriptor.getString("sha256"),
                "expected_byte_count", descriptor.getLong("byte_count"), "approved_plan_fingerprint", descriptor.getString("plan_fingerprint"));
            OfflinePackageValidator.descriptor(descriptor, request);
            JSONObject original = envelope(row);
            try (SQLiteConnection memory = index(original)) { /* Complete index for every document, including locked previous owners. */ }
        } catch (NativeFailure failure) { reason = failure.code; }
        catch (Exception ignored) { reason = "OFFLINE_CORRUPT"; }
        JSONObject result = json("slot_id", row.slot, "generation", row.generation, "sha256", hash,
            "host_build", BuildConfig.OFFLINE_HOST_BUILD, "validator_version", OfflineSyncValues.VALIDATOR,
            "checked_at", OfflineSyncValues.now(), "state", reason == null ? "passed" : "failed", "reason", reason);
        // A missing key never causes key creation while attempting to record validation.
        if (cipher.hasKey()) {
            byte[] sealed = cipher.seal(result.toString().getBytes(StandardCharsets.UTF_8), "release-check@1:" + row.slot + ":" + row.generation);
            OfflineSql.execute(connection, "INSERT INTO release_checks(slot_id,generation,value) VALUES(?,?,?) ON CONFLICT(slot_id) DO UPDATE SET generation=excluded.generation,value=excluded.value", row.slot, row.generation, sealed);
        }
        return result;
    }
    private void requireRelease(SQLiteConnection connection, Row row) throws Exception {
        JSONObject check = releaseCheck(connection, row, false);
        if (!"passed".equals(check.getString("state"))) throw new NativeFailure(check.getString("reason"));
    }
    private JSONArray releaseSweep(SQLiteConnection connection, boolean force) throws Exception {
        JSONArray checks = new JSONArray();
        for (Row row : active(connection)) checks.put(releaseCheck(connection, row, force));
        return checks;
    }
    private JSONObject syncState(SQLiteConnection connection) throws Exception {
        JSONObject state;
        try {
            try (SQLiteStatement stored = connection.prepare("SELECT value FROM sync_state WHERE id=1")) {
                state = stored.step() ? OfflinePackageValidator.parse(cipher.open(stored.getBlob(0), "device-sync-state@1")) : OfflineSyncValues.emptyState();
            }
        } catch(Exception ignored) { throw new NativeFailure("OFFLINE_SYNC_STATE_INVALID"); }
        try { OfflineSyncValues.state(state); } catch (Exception ignored) { throw new NativeFailure("OFFLINE_SYNC_STATE_INVALID"); }
        if (!state.isNull("active")) {
            JSONObject entry = OfflineSyncValues.entry(state.getJSONArray("runs"), "run", "run_id", state.getString("active"));
            if (entry == null || !"running".equals(entry.getJSONObject("run").getString("state"))) throw new NativeFailure("OFFLINE_SYNC_STATE_INVALID");
            if (!OfflineSyncValues.PROCESS.equals(entry.getString("process_id")) ||
                android.os.SystemClock.elapsedRealtime() >= entry.getLong("monotonic_deadline") ||
                !Instant.now().isBefore(Instant.parse(entry.getString("expires_at")))) {
                JSONObject policyEntry = OfflineSyncValues.entry(state.getJSONArray("policies"), "policy", "policy_id", entry.getJSONObject("run").getString("policy_id"));
                if (policyEntry != null) {
                    JSONObject policy = policyEntry.getJSONObject("policy"); policy.put("state", "paused");
                    policy.put("policy_revision", OfflineSyncValues.increment(policy.getLong("policy_revision")));
                    policy.put("reason", "OFFLINE_SYNC_INTERRUPTED"); policy.put("next_due_at", JSONObject.NULL); policy.put("updated_at", OfflineSyncValues.now());
                }
                OfflineSyncValues.finish(state, entry, "interrupted", "OFFLINE_SYNC_INTERRUPTED");
            }
        }
        return state;
    }
    private void saveSync(SQLiteConnection connection, JSONObject state) throws Exception {
        OfflineSyncValues.state(state);
        if (!cipher.hasKey()) throw new NativeFailure("OFFLINE_KEY_MISSING");
        byte[] sealed = cipher.seal(state.toString().getBytes(StandardCharsets.UTF_8), "device-sync-state@1");
        OfflineSql.execute(connection, "INSERT INTO sync_state(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value", sealed);
    }
    private interface SyncWork<T> { T run(SQLiteConnection connection, JSONObject state) throws Exception; }
    private interface SyncCommitGuard { void check(SQLiteConnection connection, JSONObject state) throws Exception; }
    private <T> T syncTx(SyncWork<T> work) throws NativeFailure {
        return syncTx(work, null);
    }
    private <T> T syncTx(SyncWork<T> work, SyncCommitGuard beforeCommit) throws NativeFailure {
        return withCatalog(connection -> {
            OfflineSql.execute(connection, "BEGIN IMMEDIATE"); boolean committed = false;
            try {
                JSONObject state = syncState(connection); T result = work.run(connection, state);
                if (cipher.hasKey()) saveSync(connection, state);
                if (beforeCommit != null) beforeCommit.check(connection, state);
                OfflineSql.execute(connection, "COMMIT"); committed = true; return result;
            } finally { if (!committed) OfflineSql.execute(connection, "ROLLBACK"); }
        });
    }
    private JSONObject syncStatusValue(SQLiteConnection connection, JSONObject state, boolean force) throws Exception {
        JSONArray policies = new JSONArray(), runs = new JSONArray();
        for (int i=0;i<state.getJSONArray("policies").length();i++) policies.put(OfflineSyncValues.copy(state.getJSONArray("policies").getJSONObject(i).getJSONObject("policy")));
        for (int i=0;i<state.getJSONArray("runs").length();i++) runs.put(OfflineSyncValues.copy(state.getJSONArray("runs").getJSONObject(i).getJSONObject("run")));
        return json("schema", "device-sync-status@1", "capabilities", OfflineSyncValues.capabilities(), "profile_id", profileId,
            "owner_epoch", epoch(connection), "policies", policies, "runs", runs, "release_checks", releaseSweep(connection, force));
    }
    synchronized JSONObject syncStatus(boolean force) throws NativeFailure { return syncTx((connection,state) -> syncStatusValue(connection, state, force)); }
    synchronized JSONObject syncSchedulingStatus() throws NativeFailure {
        return syncTx((connection, state) -> {
            JSONArray policies = new JSONArray(), runs = new JSONArray();
            for (int at = 0; at < state.getJSONArray("policies").length(); at++) policies.put(OfflineSyncValues.copy(state.getJSONArray("policies").getJSONObject(at).getJSONObject("policy")));
            for (int at = 0; at < state.getJSONArray("runs").length(); at++) runs.put(OfflineSyncValues.copy(state.getJSONArray("runs").getJSONObject(at).getJSONObject("run")));
            return json("schema", "device-sync-status@1", "capabilities", OfflineSyncValues.capabilities(), "profile_id", profileId,
                "owner_epoch", epoch(connection), "policies", policies, "runs", runs, "release_checks", new JSONArray());
        });
    }
    synchronized JSONObject syncPreview(JSONObject request, String sessionBinding) throws NativeFailure {
        try { OfflineSyncValues.previewRequest(request); if (sessionBinding == null || !sessionBinding.matches("[0-9a-f]{64}")) throw new NativeFailure("SESSION_CHANGED"); }
        catch (NativeFailure failure) { throw failure; } catch (Exception ignored) { throw new NativeFailure("OFFLINE_INVALID_ARGUMENT"); }
        return syncTx((connection, state) -> {
            if (!BuildConfig.DEBUG) throw new NativeFailure("OFFLINE_SYNC_UNSUPPORTED");
            if (!profileId.equals(request.getString("expected_profile_id")) || epoch(connection) != request.getLong("expected_owner_epoch")) throw new NativeFailure("OFFLINE_OWNER_LOCKED");
            Row selected = expected(connection, json("slot_id", request.getString("slot_id"), "expected_generation", request.getLong("expected_generation")), true);
            JSONObject metadata = metadata(selected), descriptor = metadata.getJSONObject("descriptor");
            if (metadata.getLong("created_epoch") != epoch(connection)) throw new NativeFailure("OFFLINE_OWNER_LOCKED");
            JSONObject material = envelope(selected), old = OfflineSyncValues.entry(state.getJSONArray("policies"), "policy", "slot_id", selected.slot);
            long revision = old == null ? 0 : old.getJSONObject("policy").getLong("policy_revision");
            syncPreviews.values().removeIf(value -> System.currentTimeMillis() - value.wall >= 300000 || android.os.SystemClock.elapsedRealtime() - value.monotonic >= 300000);
            if (syncPreviews.size() >= 16) throw new NativeFailure("OFFLINE_SYNC_BUSY");
            SyncPreview prepared = new SyncPreview(); prepared.wall = System.currentTimeMillis(); prepared.monotonic = android.os.SystemClock.elapsedRealtime(); prepared.sessionBinding = sessionBinding;
            prepared.value = json("schema", "device-sync-preview@1", "preview_id", UUID.randomUUID().toString(), "expires_at", Instant.ofEpochMilli(prepared.wall + 300000).toString(),
                "expected_policy_revision", revision, "profile_id", profileId, "owner_epoch", epoch(connection), "owner_scope_id", descriptor.getString("owner_scope_id"),
                "slot_id", selected.slot, "generation", selected.generation, "package_sha256", descriptor.getString("sha256"), "scope", OfflineSyncValues.scope(material),
                "capacity", OfflineSyncValues.capacity(), "interval_seconds", request.getLong("interval_seconds"), "conditions", OfflineSyncValues.copy(request.getJSONObject("conditions")),
                "capabilities", OfflineSyncValues.capabilities(), "counts", OfflineSyncValues.copy(descriptor.getJSONObject("counts")),
                "notice", "仅按已安装范围持续重打包已有历史，不抓取官网或调用AI。Garage/关注null与recent为动态范围；显式证据固定核验回执。显示安装包现有计数，不代表最新服务器预览。条件全部满足才执行，许可直到暂停或撤销；系统可能延迟，强制停止后不保证执行。");
            prepared.value.put("fingerprint", OfflineSyncValues.fingerprint(prepared.value)); syncPreviews.put(prepared.value.getString("preview_id"), prepared);
            return OfflineSyncValues.copy(prepared.value);
        });
    }
    synchronized JSONObject syncApply(JSONObject request, String sessionBinding) throws NativeFailure {
        try {
            OfflinePackageValidator.keys(request, "preview_id", "expected_fingerprint", "expected_policy_revision", "allow_continuous_history_updates");
            OfflinePackageValidator.equal(request, "allow_continuous_history_updates", true); OfflinePackageValidator.uuid(request, "preview_id");
            OfflinePackageValidator.hash(request, "expected_fingerprint"); OfflinePackageValidator.number(request, "expected_policy_revision", MAX_GENERATION);
        } catch (NativeFailure failure) { throw failure; } catch (Exception ignored) { throw new NativeFailure("OFFLINE_INVALID_ARGUMENT"); }
        SyncPreview prepared = syncPreviews.remove(request.optString("preview_id"));
        if (prepared == null || System.currentTimeMillis() < prepared.wall || System.currentTimeMillis() - prepared.wall >= 300000 ||
            android.os.SystemClock.elapsedRealtime() < prepared.monotonic || android.os.SystemClock.elapsedRealtime() - prepared.monotonic >= 300000) throw new NativeFailure("OFFLINE_SYNC_PREVIEW_EXPIRED");
        return syncTx((connection,state) -> {
            JSONObject preview = prepared.value;
            if (!prepared.sessionBinding.equals(sessionBinding) || !preview.getString("fingerprint").equals(request.getString("expected_fingerprint"))) throw new NativeFailure("SESSION_CHANGED");
            Row row = expected(connection, json("slot_id", preview.getString("slot_id"), "expected_generation", preview.getLong("generation")), true);
            JSONObject descriptor = metadata(row).getJSONObject("descriptor");
            if (epoch(connection) != preview.getLong("owner_epoch") || metadata(row).getLong("created_epoch") != epoch(connection) ||
                !descriptor.getString("sha256").equals(preview.getString("package_sha256")) || !descriptor.getString("owner_scope_id").equals(preview.getString("owner_scope_id"))) throw new NativeFailure("OFFLINE_OWNER_LOCKED");
            JSONArray policies = state.getJSONArray("policies"); JSONObject old = OfflineSyncValues.entry(policies, "policy", "slot_id", row.slot);
            long revision = old == null ? 0 : old.getJSONObject("policy").getLong("policy_revision");
            if (revision != request.getLong("expected_policy_revision") || revision != preview.getLong("expected_policy_revision")) throw new NativeFailure("OFFLINE_SYNC_STALE_POLICY");
            if (old == null && policies.length() >= 16) {
                int removed = -1; for(int i=0;i<policies.length();i++) if("revoked".equals(policies.getJSONObject(i).getJSONObject("policy").getString("state"))) { removed=i; break; }
                if (removed < 0) throw new NativeFailure("OFFLINE_SYNC_LIMIT"); policies.remove(removed);
            }
            String id = old == null ? UUID.randomUUID().toString() : old.getJSONObject("policy").getString("policy_id");
            OfflineSyncValues.cancel(state, id, "OFFLINE_SYNC_POLICY_CHANGED");
            JSONObject policy = json("schema", "device-sync-policy@1", "policy_id", id, "policy_revision", OfflineSyncValues.increment(revision), "state", "enabled", "profile_id", profileId,
                "owner_epoch", epoch(connection), "owner_scope_id", descriptor.getString("owner_scope_id"), "slot_id", row.slot, "scope", OfflineSyncValues.copy(preview.getJSONObject("scope")),
                "capacity", OfflineSyncValues.copy(preview.getJSONObject("capacity")), "interval_seconds", preview.getLong("interval_seconds"), "conditions", OfflineSyncValues.copy(preview.getJSONObject("conditions")),
                "approved_at", OfflineSyncValues.now(), "updated_at", OfflineSyncValues.now(), "binding", json("binding_revision", old == null ? 1 : OfflineSyncValues.increment(old.getJSONObject("policy").getJSONObject("binding").getLong("binding_revision")),
                    "generation", row.generation, "package_id", descriptor.getString("id"), "sha256", descriptor.getString("sha256")), "next_due_at", OfflineSyncValues.due(preview.getLong("interval_seconds")), "reason", null);
            JSONObject entry = json("policy", policy, "session_binding_hash", sessionBinding);
            if (old == null) policies.put(entry); else { old.put("policy", policy); old.put("session_binding_hash", sessionBinding); }
            return OfflineSyncValues.copy(policy);
        });
    }
    synchronized JSONObject syncChange(JSONObject request, boolean revoke) throws NativeFailure {
        try { OfflineSyncValues.policyRequest(request, false); } catch (NativeFailure failure) { throw failure; } catch (Exception ignored) { throw new NativeFailure("OFFLINE_INVALID_ARGUMENT"); }
        return syncTx((connection,state) -> {
            JSONObject entry = OfflineSyncValues.entry(state.getJSONArray("policies"), "policy", "policy_id", request.getString("policy_id"));
            if (entry == null) throw new NativeFailure("OFFLINE_NOT_FOUND"); JSONObject policy = entry.getJSONObject("policy");
            if (policy.getLong("policy_revision") != request.getLong("expected_policy_revision")) throw new NativeFailure("OFFLINE_SYNC_STALE_POLICY");
            policy.put("policy_revision", OfflineSyncValues.increment(policy.getLong("policy_revision"))); policy.put("state", revoke ? "revoked" : "paused");
            policy.put("next_due_at", JSONObject.NULL); policy.put("updated_at", OfflineSyncValues.now()); policy.put("reason", revoke ? "OFFLINE_SYNC_REVOKED" : "OFFLINE_SYNC_PAUSED");
            OfflineSyncValues.cancel(state, policy.getString("policy_id"), policy.getString("reason")); return OfflineSyncValues.copy(policy);
        });
    }
    private JSONObject runEntry(JSONObject state, String id) throws Exception {
        JSONObject entry = OfflineSyncValues.entry(state.getJSONArray("runs"), "run", "run_id", id);
        if(entry == null) throw new NativeFailure("OFFLINE_NOT_FOUND"); return entry;
    }
    private void checkSyncLease(JSONObject entry) throws Exception {
        long monotonic=android.os.SystemClock.elapsedRealtime(),deadline=entry.getLong("monotonic_deadline");Instant wall=Instant.now();
        if(!OfflineSyncValues.PROCESS.equals(entry.getString("process_id"))||monotonic<deadline-240000||monotonic>=deadline||
            wall.isBefore(Instant.parse(entry.getJSONObject("run").getString("started_at")))||!wall.isBefore(Instant.parse(entry.getString("expires_at")))) {
            throw new NativeFailure("OFFLINE_SYNC_LEASE_EXPIRED");
        }
    }
    private JSONObject currentSync(SQLiteConnection connection, JSONObject state, String runId) throws Exception {
        JSONObject entry = runEntry(state,runId), run=entry.getJSONObject("run");
        if (!runId.equals(state.optString("active")) || !"running".equals(run.getString("state")) || !OfflineSyncValues.PROCESS.equals(entry.getString("process_id"))) throw new NativeFailure("OFFLINE_SYNC_CANCELLED");
        checkSyncLease(entry);
        JSONObject policyEntry = OfflineSyncValues.entry(state.getJSONArray("policies"), "policy", "policy_id", run.getString("policy_id"));
        if (policyEntry == null) throw new NativeFailure("OFFLINE_SYNC_CANCELLED"); JSONObject policy=policyEntry.getJSONObject("policy");
        if (!"enabled".equals(policy.getString("state")) || policy.getLong("policy_revision") != run.getLong("policy_revision") ||
            !profileId.equals(policy.getString("profile_id")) || epoch(connection) != policy.getLong("owner_epoch")) throw new NativeFailure("OFFLINE_SYNC_CANCELLED");
        JSONObject binding=policy.getJSONObject("binding"); Row row=expected(connection,json("slot_id",policy.getString("slot_id"),"expected_generation",binding.getLong("generation")),true);
        JSONObject meta=metadata(row), descriptor=meta.getJSONObject("descriptor");
        if(meta.getLong("created_epoch")!=epoch(connection) || !descriptor.getString("id").equals(binding.getString("package_id")) ||
            !descriptor.getString("sha256").equals(binding.getString("sha256")) || !descriptor.getString("owner_scope_id").equals(policy.getString("owner_scope_id"))) throw new NativeFailure("OFFLINE_SYNC_CANCELLED");
        return policyEntry;
    }
    synchronized JSONObject syncBegin(JSONObject request, String sessionBinding, OfflineSyncConditions.Sample sample) throws NativeFailure {
        try { OfflineSyncValues.policyRequest(request,true); } catch(NativeFailure failure){throw failure;} catch(Exception ignored){throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");}
        return syncTx((connection,state)-> {
            if(!state.isNull("active")) throw new NativeFailure("OFFLINE_SYNC_BUSY");
            JSONObject policyEntry=OfflineSyncValues.entry(state.getJSONArray("policies"),"policy","policy_id",request.getString("policy_id"));
            if(policyEntry==null) throw new NativeFailure("OFFLINE_NOT_FOUND"); JSONObject policy=policyEntry.getJSONObject("policy");
            if(policy.getLong("policy_revision")!=request.getLong("expected_policy_revision")) throw new NativeFailure("OFFLINE_SYNC_STALE_POLICY");
            if(!"enabled".equals(policy.getString("state"))) throw new NativeFailure("OFFLINE_SYNC_DISABLED");
            if(!policyEntry.getString("session_binding_hash").equals(sessionBinding)) throw new NativeFailure("SESSION_CHANGED");
            String id=UUID.randomUUID().toString(); JSONObject run=json("schema","device-sync-run@1","run_id",id,"policy_id",policy.getString("policy_id"),
                "policy_revision",policy.getLong("policy_revision"),"trigger",request.getString("trigger"),"state","running","stage","checking","reason",null,
                "started_at",OfflineSyncValues.now(),"finished_at",null,"before_generation",policy.getJSONObject("binding").getLong("generation"),"after_generation",null,"plan_id",null,"package_id",null);
            JSONObject entry=json("run",run,"process_id",OfflineSyncValues.PROCESS,"confirmation_key",null,"plan_fingerprint",null,
                "expires_at",OfflineSyncValues.due(240),"monotonic_deadline",android.os.SystemClock.elapsedRealtime()+240000);
            JSONArray runs=state.getJSONArray("runs"); if(runs.length()>=64) runs.remove(0); runs.put(entry); state.put("active",id);
            try { currentSync(connection,state,id); }
            catch(NativeFailure failure) { OfflineSyncValues.finish(state,entry,"blocked",failure.code); policy.put("state","paused"); policy.put("reason",failure.code); policy.put("next_due_at",JSONObject.NULL); return json("run",run,"policy",OfflineSyncValues.copy(policy)); }
            String reason=OfflineSyncConditions.blocked(policy.getJSONObject("conditions"),sample);
            if(reason==null && !"manual".equals(request.getString("trigger")) && !policy.isNull("next_due_at") && Instant.now().isBefore(Instant.parse(policy.getString("next_due_at")))) reason="OFFLINE_SYNC_NOT_DUE";
            if(reason!=null) { OfflineSyncValues.finish(state,entry,"deferred",reason); if(!reason.equals("OFFLINE_SYNC_NOT_DUE")) policy.put("next_due_at",OfflineSyncValues.due(policy.getLong("interval_seconds"))); policy.put("reason",reason); }
            return json("run",OfflineSyncValues.copy(run),"policy",OfflineSyncValues.copy(policy),"base_pack",
                "running".equals(run.getString("state")) ? OfflineSyncValues.copy(metadata(row(connection,policy.getString("slot_id"))).getJSONObject("descriptor")) : null);
        });
    }
    synchronized JSONObject syncBlocked(JSONObject request,String reason) throws NativeFailure {
        try{OfflineSyncValues.policyRequest(request,true);if(reason==null||!reason.matches("[A-Z_]{1,100}"))throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");}
        catch(NativeFailure failure){throw failure;}catch(Exception ignored){throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");}
        return syncTx((connection,state)-> {
            if(!state.isNull("active"))throw new NativeFailure("OFFLINE_SYNC_BUSY");
            JSONObject policyEntry=OfflineSyncValues.entry(state.getJSONArray("policies"),"policy","policy_id",request.getString("policy_id"));
            if(policyEntry==null)throw new NativeFailure("OFFLINE_NOT_FOUND");JSONObject policy=policyEntry.getJSONObject("policy");
            if(policy.getLong("policy_revision")!=request.getLong("expected_policy_revision"))throw new NativeFailure("OFFLINE_SYNC_STALE_POLICY");
            if(!"enabled".equals(policy.getString("state")))throw new NativeFailure("OFFLINE_SYNC_DISABLED");
            JSONObject run=json("schema","device-sync-run@1","run_id",UUID.randomUUID().toString(),"policy_id",policy.getString("policy_id"),"policy_revision",policy.getLong("policy_revision"),
                "trigger",request.getString("trigger"),"state","blocked","stage","finished","reason",reason,"started_at",OfflineSyncValues.now(),"finished_at",OfflineSyncValues.now(),
                "before_generation",policy.getJSONObject("binding").getLong("generation"),"after_generation",null,"plan_id",null,"package_id",null);
            JSONObject entry=json("run",run,"process_id",OfflineSyncValues.PROCESS,"confirmation_key",null,"plan_fingerprint",null,"expires_at",OfflineSyncValues.due(240),"monotonic_deadline",android.os.SystemClock.elapsedRealtime()+240000);
            JSONArray runs=state.getJSONArray("runs");if(runs.length()>=64)runs.remove(0);runs.put(entry);
            policy.put("state","paused");policy.put("policy_revision",OfflineSyncValues.increment(policy.getLong("policy_revision")));policy.put("reason",reason);policy.put("next_due_at",JSONObject.NULL);policy.put("updated_at",OfflineSyncValues.now());return OfflineSyncValues.copy(run);
        });
    }
    synchronized JSONObject syncStage(String runId,String stage,JSONObject plan,String confirmationKey) throws NativeFailure {
        return syncTx((connection,state)-> {
            JSONObject policyEntry=currentSync(connection,state,runId), entry=runEntry(state,runId), run=entry.getJSONObject("run");
            if(!List.of("preparing","confirming","downloading","committing").contains(stage)) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT"); run.put("stage",stage);
            if(plan!=null) { run.put("plan_id",OfflinePackageValidator.uuid(plan,"id")); run.put("package_id",OfflinePackageValidator.uuid(plan,"package_id")); entry.put("plan_fingerprint",OfflinePackageValidator.hash(plan,"fingerprint")); NativePolicy.requestId(confirmationKey); entry.put("confirmation_key",confirmationKey); }
            return json("run",OfflineSyncValues.copy(run),"policy",OfflineSyncValues.copy(policyEntry.getJSONObject("policy")));
        });
    }
    synchronized JSONObject syncFinish(String runId,String status,String reason,boolean pause) throws NativeFailure {
        return syncTx((connection,state)-> {
            JSONObject entry=runEntry(state,runId), run=entry.getJSONObject("run"); if(!"running".equals(run.getString("state"))) return OfflineSyncValues.copy(run);
            JSONObject policyEntry=OfflineSyncValues.entry(state.getJSONArray("policies"),"policy","policy_id",run.getString("policy_id"));
            if(policyEntry!=null && policyEntry.getJSONObject("policy").getLong("policy_revision")==run.getLong("policy_revision")) {
                JSONObject policy=policyEntry.getJSONObject("policy"); policy.put("reason",reason==null?JSONObject.NULL:reason); policy.put("updated_at",OfflineSyncValues.now());
                if(pause) { policy.put("state","paused");policy.put("policy_revision",OfflineSyncValues.increment(policy.getLong("policy_revision")));policy.put("next_due_at",JSONObject.NULL); }
                else policy.put("next_due_at",OfflineSyncValues.due(policy.getLong("interval_seconds")));
            }
            OfflineSyncValues.finish(state,entry,status,reason); return OfflineSyncValues.copy(run);
        });
    }
    synchronized JSONObject syncNoChange(String runId,BooleanSupplier stillCurrent,java.util.function.Supplier<OfflineSyncConditions.Sample> conditions) throws NativeFailure {
        return syncTx((connection,state)-> {
            current(stillCurrent); JSONObject policy=currentSync(connection,state,runId).getJSONObject("policy");
            String blocked=OfflineSyncConditions.blocked(policy.getJSONObject("conditions"),conditions.get()); if(blocked!=null) throw new NativeFailure(blocked);
            JSONObject entry=runEntry(state,runId); entry.getJSONObject("run").put("after_generation",policy.getJSONObject("binding").getLong("generation"));
            OfflineSyncValues.finish(state,entry,"no_change",null);policy.put("next_due_at",OfflineSyncValues.due(policy.getLong("interval_seconds")));policy.put("reason",JSONObject.NULL);
            current(stillCurrent);checkSyncLease(entry);return OfflineSyncValues.copy(entry.getJSONObject("run"));
        }, (connection,state)-> {
            JSONObject entry=runEntry(state,runId);
            JSONObject policy=OfflineSyncValues.entry(state.getJSONArray("policies"),"policy","policy_id",entry.getJSONObject("run").getString("policy_id")).getJSONObject("policy");
            String blocked=OfflineSyncConditions.blocked(policy.getJSONObject("conditions"),conditions.get());if(blocked!=null)throw new NativeFailure(blocked);
            current(stillCurrent);checkSyncLease(entry);
        });
    }
    synchronized JSONObject syncCommit(String runId,JSONObject descriptor,byte[] original,BooleanSupplier stillCurrent,java.util.function.Supplier<OfflineSyncConditions.Sample> conditions) throws NativeFailure {
        JSONObject request;
        try { request=json("package_id",descriptor.getString("id"),"expected_sha256",descriptor.getString("sha256"),"expected_byte_count",descriptor.getLong("byte_count"),"approved_plan_fingerprint",descriptor.getString("plan_fingerprint")); OfflinePackageValidator.descriptor(descriptor,request); }
        catch(NativeFailure failure){throw failure;} catch(Exception ignored){throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");}
        JSONObject material=OfflinePackageValidator.envelope(original,descriptor);
        try(SQLiteConnection memory=index(material)) { /* Original/index validated before the publication lock. */ }
        catch(NativeFailure failure){throw failure;} catch(Exception ignored){throw new NativeFailure("OFFLINE_SEARCH_UNAVAILABLE");}
        return withCatalog(connection-> {
            cleanup(connection); OfflineSql.execute(connection,"BEGIN IMMEDIATE"); boolean committed=false;File staged=null;
            try {
                current(stillCurrent);JSONObject state=syncState(connection),entry=runEntry(state,runId),run=entry.getJSONObject("run"),policy=currentSync(connection,state,runId).getJSONObject("policy");
                if(!"committing".equals(run.getString("stage")) || !descriptor.getString("id").equals(run.getString("package_id")) ||
                    !descriptor.getString("plan_id").equals(run.getString("plan_id")) || !descriptor.getString("plan_fingerprint").equals(entry.getString("plan_fingerprint")) ||
                    !descriptor.getString("owner_scope_id").equals(policy.getString("owner_scope_id")) ||
                    !descriptor.getString("base_pack_id").equals(policy.getJSONObject("binding").getString("package_id")) ||
                    !OfflineSyncValues.equal(material.getJSONObject("scope"),policy.getJSONObject("scope"))) throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
                String blocked=OfflineSyncConditions.blocked(policy.getJSONObject("conditions"),conditions.get());if(blocked!=null) throw new NativeFailure(blocked);
                Row prior=row(connection,policy.getString("slot_id"));
                if (!metadata(prior).getJSONObject("descriptor").getString("schema").equals(descriptor.getString("schema")))
                    throw new NativeFailure("OFFLINE_SYNC_PACKAGE_MISMATCH");
                long generation=prior.generation; if(generation>=MAX_GENERATION) throw new NativeFailure("OFFLINE_GENERATION_EXHAUSTED");
                if(total(active(connection))-metadata(prior).getJSONObject("descriptor").getLong("byte_count")+original.length>MAX_STORE_BYTES) throw new NativeFailure("OFFLINE_STORE_LIMIT");
                Row next=new Row();next.slot=prior.slot;next.generation=generation+1;next.blob=UUID.randomUUID()+".sealed";long epoch=epoch(connection);
                next.metadata=json("descriptor",OfflineSyncValues.copy(descriptor),"installed_at",OfflineSyncValues.now(),"created_epoch",epoch,"allowed_epoch",epoch,"title",metadata(prior).getString("title"));
                next.sealedMetadata=cipher.seal(next.metadata.toString().getBytes(StandardCharsets.UTF_8),purpose(next,"metadata"));byte[] sealed=cipher.seal(original,purpose(next,"body"));
                staged=blobFile(next.blob);if(!staged.createNewFile())throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE");try(FileOutputStream output=new FileOutputStream(staged)){output.write(sealed);output.getFD().sync();}syncDirectory(blobs);
                current(stillCurrent); blocked=OfflineSyncConditions.blocked(policy.getJSONObject("conditions"),conditions.get()); if(blocked!=null) throw new NativeFailure(blocked);
                checkSyncLease(entry);
                OfflineSql.execute(connection,"UPDATE slots SET generation=?,blob_id=?,metadata=? WHERE slot_id=? AND generation=?",next.generation,next.blob,next.sealedMetadata,next.slot,generation);
                JSONObject fallbackState = fallbackState(connection);
                OfflineFallbackJournal.putBinding(fallbackState, slot(next, epoch), epoch, material, true, fallbackClock.wall());
                saveFallbackState(connection, fallbackState);
                JSONObject binding=policy.getJSONObject("binding");binding.put("binding_revision",OfflineSyncValues.increment(binding.getLong("binding_revision")));binding.put("generation",next.generation);binding.put("package_id",descriptor.getString("id"));binding.put("sha256",descriptor.getString("sha256"));
                policy.put("next_due_at",OfflineSyncValues.due(policy.getLong("interval_seconds")));policy.put("reason",JSONObject.NULL);policy.put("updated_at",OfflineSyncValues.now());run.put("after_generation",next.generation);OfflineSyncValues.finish(state,entry,"succeeded",null);
                saveSync(connection,state);JSONObject check=releaseCheck(connection,next,true);
                if(!"passed".equals(check.getString("state")))throw new NativeFailure(check.getString("reason"));
                blocked=OfflineSyncConditions.blocked(policy.getJSONObject("conditions"),conditions.get());if(blocked!=null)throw new NativeFailure(blocked);
                current(stillCurrent);checkSyncLease(entry);
                OfflineSql.execute(connection,"COMMIT");committed=true;cleanupAfterCommit(connection);return OfflineSyncValues.copy(run);
            }finally{if(!committed){OfflineSql.execute(connection,"ROLLBACK");if(staged!=null)staged.delete();}}
        });
    }

    /** Fixed SQL only; values and FTS expressions are always bound parameters. */
    private static final class OfflineSql {
        static SQLiteStatement statement(SQLiteConnection connection, String sql, Object... values) {
            SQLiteStatement statement = connection.prepare(sql);
            try {
                for (int i = 0; i < values.length; i++) {
                    Object value = values[i];
                    if (value == null) statement.bindNull(i + 1);
                    else if (value instanceof byte[]) statement.bindBlob(i + 1, (byte[]) value);
                    else if (value instanceof Number) statement.bindLong(i + 1, ((Number) value).longValue());
                    else statement.bindText(i + 1, (String) value);
                }
                return statement;
            } catch (RuntimeException error) { statement.close(); throw error; }
        }
        static void execute(SQLiteConnection connection, String sql, Object... values) {
            try (SQLiteStatement statement = statement(connection, sql, values)) { while (statement.step()) { /* Drain PRAGMA. */ } }
        }
        static long scalar(SQLiteConnection connection, String sql, Object... values) {
            try (SQLiteStatement statement = statement(connection, sql, values)) {
                if (!statement.step()) throw new IllegalStateException("Missing SQLite scalar");
                return statement.getLong(0);
            }
        }
    }
}
