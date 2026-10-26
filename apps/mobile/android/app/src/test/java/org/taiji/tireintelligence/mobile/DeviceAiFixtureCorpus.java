package org.taiji.tireintelligence.mobile;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import org.json.JSONArray;
import org.json.JSONObject;

/** Test-only reader for exact tracked synthetic bytes; no artifact/property fallback. */
final class DeviceAiFixtureCorpus {
    private static final String ROOT = "packages/domain-types/fixtures/device-ai-v1";
    private static final String PROVENANCE_SHA256 =
        "278e8cacad9a8537264781e49ce381111e6ed50b17a224aa32ccdf066012172d";

    private DeviceAiFixtureCorpus() {}

    static byte[] read(String relative) throws Exception {
        requireRelative(relative);
        Path root = locate().toRealPath();
        byte[] provenanceBytes = Files.readAllBytes(root.resolve("provenance.json"));
        if (!PROVENANCE_SHA256.equals(sha256(provenanceBytes))) {
            throw new IllegalStateException("corpus provenance SHA-256 drift");
        }
        JSONObject provenance = new JSONObject(new String(provenanceBytes, StandardCharsets.UTF_8));
        if (!"device-ai-test-corpus-provenance@1".equals(provenance.getString("schema"))
                || !".artifacts/device-ai50".equals(provenance.getString("source_root"))
                || !provenance.getBoolean("synthetic_only")) {
            throw new IllegalStateException("unexpected corpus provenance contract");
        }
        JSONArray files = provenance.getJSONArray("files");
        if (files.length() != provenance.getInt("file_count")) {
            throw new IllegalStateException("corpus file_count drift");
        }
        JSONObject entry = null;
        for (int at = 0; at < files.length(); at++) {
            JSONObject candidate = files.getJSONObject(at);
            if (!relative.equals(candidate.getString("path"))) continue;
            if (entry != null) throw new IllegalStateException("duplicate corpus provenance entry");
            entry = candidate;
        }
        if (entry == null || !(".artifacts/device-ai50/" + relative).equals(entry.getString("source_path"))) {
            throw new IllegalStateException("unlisted corpus file: " + relative);
        }
        Path path = root.resolve(relative).toRealPath();
        if (!path.startsWith(root)) throw new IllegalStateException("corpus file escaped its root");
        byte[] raw = Files.readAllBytes(path);
        verifyBytes(raw, entry);
        return raw;
    }

    static void verifyBytes(byte[] raw, JSONObject entry) throws Exception {
        if (raw.length != entry.getLong("byte_count") || !sha256(raw).equals(entry.getString("sha256"))) {
            throw new IllegalStateException("corpus file byte count or SHA-256 drift");
        }
    }

    private static void requireRelative(String relative) {
        if (relative == null || relative.isEmpty() || relative.indexOf('\\') >= 0
                || relative.indexOf(':') >= 0 || Path.of(relative).isAbsolute()) {
            throw new IllegalStateException("corpus path must stay relative");
        }
        for (String part : relative.split("/", -1)) {
            if (part.isEmpty() || part.equals(".") || part.equals("..")) {
                throw new IllegalStateException("corpus path traversal rejected");
            }
        }
    }

    private static Path locate() {
        Path directory = Path.of("").toAbsolutePath();
        for (int up = 0; up <= 8 && directory != null; up++, directory = directory.getParent()) {
            Path candidate = directory.resolve(ROOT);
            if (Files.isRegularFile(candidate.resolve("provenance.json"))) return candidate;
        }
        throw new IllegalStateException("tracked device-AI corpus not found above working directory");
    }

    private static String sha256(byte[] raw) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));
    }
}
