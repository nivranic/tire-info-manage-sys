package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.stream.Stream;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

/** Real default-capacity bytes and pure helpers; no native full projector or device claim. */
public final class DeviceAiCapacityParityTest {
    @Test public void boundaryRecipesReplayActualRawBytes() throws Exception {
        JSONObject document = DeviceAiCapacityCorpus.document("boundary-recipes.json", "device-ai-capacity-recipes@1");
        assertEquals(DeviceAiJsonParser.MAX_PACKAGE_BYTES, document.getInt("max_package_bytes"));
        JSONArray cases = document.getJSONArray("cases");
        assertEquals(10, cases.length());
        for (int at = 0; at < cases.length(); at++) {
            JSONObject vector = cases.getJSONObject(at);
            JSONObject expected = vector.getJSONObject("expected");
            byte[] raw = DeviceAiCapacityCorpus.expandBoundary(vector);
            if ("rejected".equals(expected.getString("state"))) {
                assertParserRejected(vector.getString("id"), raw, expected.getString("error_code"));
            } else {
                Object ast = DeviceAiJsonParser.parse(raw);
                assertEquals(vector.getString("id"), expected.getString("canonical_text"), DeviceAiJsonParser.canonical(ast));
                assertArrayEquals(HexFormat.of().parseHex(expected.getString("canonical_utf8_hex")), DeviceAiJsonParser.canonicalBytes(ast));
                assertEquals(expected.getString("canonical_sha256"), DeviceAiJsonParser.digest(ast));
            }
        }
    }

    @Test public void completePackagesKeepAstAtActualCapacityBoundary() throws Exception {
        JSONObject document = DeviceAiCapacityCorpus.document("formal-package.json", "device-ai-formal-capacity@1");
        String baseCanonical = DeviceAiJsonParser.canonical(DeviceAiJsonParser.parse(DeviceAiCapacityCorpus.read(document.getString("base_pack"))));
        JSONArray cases = document.getJSONArray("cases");
        assertEquals(4, cases.length());
        for (int at = 0; at < cases.length(); at++) {
            JSONObject vector = cases.getJSONObject(at);
            byte[] raw = DeviceAiCapacityCorpus.expandFormal(document, vector);
            // The native parser is a separate layer from expected.projection_* and its metadata gate.
            JSONObject expected = vector.getJSONObject("parser_expected");
            if ("rejected".equals(expected.getString("state"))) {
                assertParserRejected(vector.getString("id"), raw, expected.getString("error_code"));
            } else {
                assertEquals(vector.getString("id"), baseCanonical, DeviceAiJsonParser.canonical(DeviceAiJsonParser.parse(raw)));
            }
        }
    }

    @Test public void selectionFingerprintSortsWithoutChangingInput() throws Exception {
        JSONObject document = fingerprints();
        JSONArray selectors = document.getJSONArray("selection_input");
        JSONObject expected = document.getJSONObject("selection_expected");
        assertExpectedLiteral(expected, "device-ai-selection@1");
        String before = selectors.toString();
        assertEquals(expected.getString("sha256"), DeviceAiHost.selectionSha256(selectors));
        JSONArray reversed = new JSONArray();
        for (int at = selectors.length() - 1; at >= 0; at--) reversed.put(selectors.get(at));
        assertEquals(expected.getString("sha256"), DeviceAiHost.selectionSha256(reversed));
        assertEquals(before, selectors.toString());
    }

    @Test public void previewFingerprintSortsClosureButBindsRequestedOrder() throws Exception {
        JSONArray cases = fingerprints().getJSONArray("preview_cases");
        assertEquals(3, cases.length());
        String ascending = null, descending = null, selectedChanged = null;
        for (int at = 0; at < cases.length(); at++) {
            JSONObject vector = cases.getJSONObject(at);
            JSONObject input = vector.getJSONObject("input");
            JSONObject expected = vector.getJSONObject("expected");
            assertExpectedLiteral(expected, "device-ai-local-preview@1");
            String before = input.toString();
            String actual = DeviceAiHost.localPreviewFingerprint(input);
            assertEquals(vector.getString("id"), expected.getString("sha256"), actual);
            assertEquals(before, input.toString());
            switch (vector.getString("id")) {
                case "closure-ascending": ascending = actual; break;
                case "closure-descending": descending = actual; break;
                case "selected-order-change": selectedChanged = actual; break;
                default: fail("unknown preview vector");
            }
        }
        assertNotNull(ascending);
        assertEquals(ascending, descending);
        assertNotEquals(ascending, selectedChanged);
    }

    @Test public void contextFingerprintUsesUtf8OrderForCurrentRecallBoundaries() throws Exception {
        JSONArray cases = fingerprints().getJSONArray("context_cases");
        assertEquals(1, cases.length());
        for (int at = 0; at < cases.length(); at++) {
            JSONObject vector = cases.getJSONObject(at);
            JSONObject expected = vector.getJSONObject("expected");
            assertExpectedLiteral(expected, "device-ai-context@1");
            assertEquals(vector.getString("id"), expected.getString("sha256"), DeviceAiHost.deviceContextFingerprint(vector.getJSONObject("input")));
        }
    }

    @Test public void corpusIntegrityRejectsMissingChangedAndUnboundedInputs() throws Exception {
        byte[] raw = DeviceAiCapacityCorpus.read("boundary-recipes.json");
        String sha256 = DeviceAiCapacityCorpus.sha256(raw);
        byte[] changed = raw.clone();
        changed[0] ^= 1;
        assertThrows(IllegalStateException.class, () -> DeviceAiCapacityCorpus.verifyBytes(changed, raw.length, sha256));
        assertThrows(IllegalStateException.class, () -> DeviceAiCapacityCorpus.verifyBytes(Arrays.copyOf(raw, raw.length + 1), raw.length, sha256));
        assertThrows(IllegalStateException.class, () -> DeviceAiCapacityCorpus.verifyManifest(raw));
        assertThrows(IllegalStateException.class, () -> DeviceAiCapacityCorpus.read("missing.json"));
        assertThrows(IllegalStateException.class, () -> DeviceAiCapacityCorpus.read("../manifest.json"));
        JSONObject document = DeviceAiCapacityCorpus.document("boundary-recipes.json", "device-ai-capacity-recipes@1");
        JSONObject vector = new JSONObject(document.getJSONArray("cases").getJSONObject(0).toString());
        vector.put("input_sha256", "0".repeat(64));
        assertThrows(IllegalStateException.class, () -> DeviceAiCapacityCorpus.expandBoundary(vector));
        vector.getJSONObject("input").put("repeat_count", Long.MAX_VALUE);
        assertThrows(IllegalStateException.class, () -> DeviceAiCapacityCorpus.expandBoundary(vector));
    }

    @Test public void readRejectsMissingProjectionBeforeReturningUnrelatedRecipe() throws Exception {
        try (IsolatedCorpus isolated = new IsolatedCorpus()) {
            assertTrue(DeviceAiCapacityCorpus.readFromRoot(isolated.root, "boundary-recipes.json").length > 0);
            Files.delete(isolated.root.resolve("projections/formal-n.canonical.json"));
            assertThrows(NoSuchFileException.class,
                () -> DeviceAiCapacityCorpus.readFromRoot(isolated.root, "boundary-recipes.json"));
        }
    }

    @Test public void readRejectsSameSizeProjectionCorruptionBeforeReturningUnrelatedRecipe() throws Exception {
        try (IsolatedCorpus isolated = new IsolatedCorpus()) {
            assertTrue(DeviceAiCapacityCorpus.readFromRoot(isolated.root, "boundary-recipes.json").length > 0);
            Path projection = isolated.root.resolve("projections/formal-n.canonical.json");
            byte[] changed = Files.readAllBytes(projection);
            long originalSize = Files.size(projection);
            changed[0] ^= 1;
            Files.write(projection, changed);
            assertEquals(originalSize, Files.size(projection));
            assertThrows(IllegalStateException.class,
                () -> DeviceAiCapacityCorpus.readFromRoot(isolated.root, "boundary-recipes.json"));
        }
    }

    private static final class IsolatedCorpus implements AutoCloseable {
        final Path root;

        IsolatedCorpus() throws Exception {
            Path source = DeviceAiCapacityCorpus.locate().toRealPath();
            JSONObject manifest = DeviceAiCapacityCorpus.verifyAll(source);
            root = Files.createTempDirectory("r73-capacity-corpus-").toRealPath();
            Files.copy(source.resolve("manifest.json"), root.resolve("manifest.json"));
            JSONArray files = manifest.getJSONArray("files");
            for (int at = 0; at < files.length(); at++) {
                String relative = files.getJSONObject(at).getString("path");
                Path target = root.resolve(relative);
                Files.createDirectories(target.getParent());
                Files.copy(source.resolve(relative), target);
            }
        }

        @Override public void close() throws Exception {
            // This root was created above; walk does not follow symlinks and never visits the source corpus.
            try (Stream<Path> paths = Files.walk(root)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(path);
            }
        }
    }

    private static JSONObject fingerprints() throws Exception {
        return DeviceAiCapacityCorpus.document("closure-fingerprints.json", "device-ai-closure-fingerprints@1");
    }

    private static void assertParserRejected(String id, byte[] raw, String expected) {
        DeviceAiJsonParser.ProjectionException failure = assertThrows(id, DeviceAiJsonParser.ProjectionException.class, () -> DeviceAiJsonParser.parse(raw));
        assertEquals(id, expected, failure.code);
    }

    /** Independently bind the fixture's literal preimage using only java.security SHA-256. */
    private static void assertExpectedLiteral(JSONObject expected, String namespace) throws Exception {
        byte[] canonical = expected.getString("canonical_text").getBytes(StandardCharsets.UTF_8);
        assertEquals(expected.getInt("byte_count"), canonical.length);
        assertArrayEquals(HexFormat.of().parseHex(expected.getString("canonical_utf8_hex")), canonical);
        byte[] prefix = (namespace + "\0").getBytes(StandardCharsets.UTF_8);
        byte[] preimage = Arrays.copyOf(prefix, prefix.length + canonical.length);
        System.arraycopy(canonical, 0, preimage, prefix.length, canonical.length);
        assertEquals(expected.getString("sha256"), DeviceAiCapacityCorpus.sha256(preimage));
    }
}
