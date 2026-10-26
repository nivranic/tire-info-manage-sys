package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import org.json.JSONObject;
import org.junit.Test;

/** Pure integrity/path checks; no Android, transport, credentials or database. */
public final class DeviceAiFixtureCorpusTest {
    @Test public void rejectsTraversalAndUnlistedPaths() {
        for (String path : new String[] {"../provenance.json", "/specs/test.json", "specs//test.json",
                "specs/./test.json", "specs\\test.json", "C:/test.json", "unlisted.json"}) {
            assertThrows(path, IllegalStateException.class, () -> DeviceAiFixtureCorpus.read(path));
        }
    }

    @Test public void rejectsChangedPayloadBytes() throws Exception {
        byte[] raw = "fixture".getBytes(StandardCharsets.UTF_8);
        JSONObject entry = new JSONObject().put("byte_count", raw.length)
            .put("sha256", HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw)));
        DeviceAiFixtureCorpus.verifyBytes(raw, entry);
        assertThrows(IllegalStateException.class,
            () -> DeviceAiFixtureCorpus.verifyBytes("fixturE".getBytes(StandardCharsets.UTF_8), entry));
        assertThrows(IllegalStateException.class,
            () -> DeviceAiFixtureCorpus.verifyBytes("fixture!".getBytes(StandardCharsets.UTF_8), entry));
    }
}
