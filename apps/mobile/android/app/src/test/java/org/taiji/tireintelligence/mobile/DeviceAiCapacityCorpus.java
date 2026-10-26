package org.taiji.tireintelligence.mobile;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** New synthetic corpus only; the historical E1 corpus and its pins stay independent. */
final class DeviceAiCapacityCorpus {
    private static final String ROOT = "packages/domain-types/fixtures/device-ai-capacity-v1";
    private static final String MANIFEST_SHA256 =
        "c1d454ce4875a9d9c6e77fc8dd9f59ae4ae147ca0ca030af553e83bae14525d1";
    static final int MAX_PACKAGE_BYTES = 8_388_608;

    private DeviceAiCapacityCorpus() {}

    static byte[] read(String relative) throws Exception {
        return readFromRoot(locate(), relative);
    }

    /** Root injection is test-only, for isolated copies; production test reads still locate the tracked corpus. */
    static byte[] readFromRoot(Path directory, String relative) throws Exception {
        requireRelative(relative);
        Path root = directory.toRealPath();
        JSONObject manifest = verifyAll(root);
        JSONArray files = manifest.getJSONArray("files");
        JSONObject entry = null;
        for (int at = 0; at < files.length(); at++) {
            JSONObject candidate = files.getJSONObject(at);
            if (!relative.equals(candidate.getString("path"))) continue;
            if (entry != null) throw new IllegalStateException("duplicate capacity corpus entry");
            entry = candidate;
        }
        if (entry == null) throw new IllegalStateException("unlisted capacity corpus file");
        byte[] raw = readContained(root, relative);
        verifyBytes(raw, entry.getLong("byte_count"), entry.getString("sha256"));
        return raw;
    }

    /** Bind all 22 files before returning any fixture, including files no native DUT consumes. */
    static JSONObject verifyAll(Path directory) throws Exception {
        Path root = directory.toRealPath();
        JSONObject manifest = verifyManifest(readContained(root, "manifest.json"));
        JSONArray files = manifest.getJSONArray("files");
        if (files.length() != 22) throw new IllegalStateException("capacity corpus file count drift");
        Set<String> seen = new HashSet<>();
        for (int at = 0; at < files.length(); at++) {
            JSONObject entry = files.getJSONObject(at);
            String relative = entry.getString("path");
            if (!seen.add(relative)) throw new IllegalStateException("duplicate capacity corpus entry");
            verifyBytes(readContained(root, relative), entry.getLong("byte_count"), entry.getString("sha256"));
        }
        return manifest;
    }

    private static byte[] readContained(Path root, String relative) throws Exception {
        requireRelative(relative);
        Path path = root.resolve(relative).toRealPath();
        if (!path.startsWith(root)) throw new IllegalStateException("capacity corpus path escaped root");
        return Files.readAllBytes(path);
    }

    static JSONObject document(String relative, String schema) throws Exception {
        JSONObject value = new JSONObject(new String(read(relative), StandardCharsets.UTF_8));
        if (!schema.equals(value.getString("schema"))) throw new IllegalStateException("capacity fixture schema drift");
        return value;
    }

    static JSONObject verifyManifest(byte[] raw) throws Exception {
        if (!MANIFEST_SHA256.equals(sha256(raw))) throw new IllegalStateException("capacity manifest SHA-256 drift");
        JSONObject manifest = new JSONObject(new String(raw, StandardCharsets.UTF_8));
        if (!"device-ai-capacity-corpus@1".equals(manifest.getString("schema"))
                || !manifest.getBoolean("synthetic_only")
                || manifest.getLong("max_package_bytes") != MAX_PACKAGE_BYTES) {
            throw new IllegalStateException("capacity corpus contract drift");
        }
        return manifest;
    }

    static byte[] expandBoundary(JSONObject vector) throws Exception {
        JSONObject input = vector.getJSONObject("input");
        if (!"repeat_hex".equals(input.getString("form"))) throw new IllegalStateException("unknown capacity recipe");
        byte[] prefix = HexFormat.of().parseHex(input.getString("prefix_hex"));
        byte[] repeat = HexFormat.of().parseHex(input.getString("repeat_hex"));
        byte[] suffix = HexFormat.of().parseHex(input.getString("suffix_hex"));
        long count = input.getLong("repeat_count");
        if (count < 0 || count > MAX_PACKAGE_BYTES + 1L || repeat.length == 0)
            throw new IllegalStateException("unbounded capacity recipe");
        long size = Math.addExact(Math.addExact(prefix.length, Math.multiplyExact(count, repeat.length)), suffix.length);
        checkExpandedSize(size);
        byte[] raw = new byte[(int) size];
        System.arraycopy(prefix, 0, raw, 0, prefix.length);
        int offset = prefix.length;
        for (long at = 0; at < count; at++, offset += repeat.length)
            System.arraycopy(repeat, 0, raw, offset, repeat.length);
        System.arraycopy(suffix, 0, raw, offset, suffix.length);
        verifyBytes(raw, vector.getLong("input_byte_count"), vector.getString("input_sha256"));
        return raw;
    }

    static byte[] expandFormal(JSONObject document, JSONObject vector) throws Exception {
        byte[] base = read(document.getString("base_pack"));
        long padding = vector.getLong("padding_spaces");
        if (padding < 0) throw new IllegalStateException("negative package padding");
        long size = Math.addExact(base.length, padding);
        checkExpandedSize(size);
        byte[] raw = Arrays.copyOf(base, (int) size);
        Arrays.fill(raw, base.length, raw.length, (byte) 0x20);
        verifyBytes(raw, vector.getLong("input_byte_count"), vector.getString("input_sha256"));
        return raw;
    }

    private static void checkExpandedSize(long size) {
        if (size < 0 || size > MAX_PACKAGE_BYTES + 1L) throw new IllegalStateException("capacity recipe exceeds test bound");
    }

    static void verifyBytes(byte[] raw, long expectedSize, String expectedSha256) throws Exception {
        if (raw.length != expectedSize || !sha256(raw).equals(expectedSha256))
            throw new IllegalStateException("capacity bytes size or SHA-256 drift");
    }

    static String sha256(byte[] raw) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));
    }

    private static void requireRelative(String relative) {
        if (relative == null || relative.isEmpty() || relative.indexOf('\\') >= 0
                || relative.indexOf(':') >= 0 || Path.of(relative).isAbsolute())
            throw new IllegalStateException("capacity corpus path must stay relative");
        for (String part : relative.split("/", -1))
            if (part.isEmpty() || part.equals(".") || part.equals(".."))
                throw new IllegalStateException("capacity corpus path traversal");
    }

    static Path locate() {
        Path directory = Path.of("").toAbsolutePath();
        for (int up = 0; up <= 8 && directory != null; up++, directory = directory.getParent()) {
            Path candidate = directory.resolve(ROOT);
            if (Files.isRegularFile(candidate.resolve("manifest.json"))) return candidate;
        }
        throw new IllegalStateException("tracked capacity corpus unavailable");
    }
}
