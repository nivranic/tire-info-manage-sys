package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Enumeration;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import org.junit.After;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Runs against the dedicated offlineQa application; never reads the normal app's aliases. */
@RunWith(AndroidJUnit4.class)
public final class OfflineCipherTest {
    private final List<OfflineCipher> keys = new ArrayList<>();
    private OfflineCipher cipher() throws Exception {
        android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue("Dedicated QA application required", context.getPackageName().endsWith(".offlineqa"));
        OfflineCipher cipher = new OfflineCipher(context, "qa-" + UUID.randomUUID());
        keys.add(cipher);
        return cipher;
    }
    private static void fails(String code, Checked action) throws Exception {
        try { action.run(); fail("Expected " + code); }
        catch (NativeFailure failure) { assertEquals(code, failure.code); }
    }
    private interface Checked { void run() throws Exception; }
    /** Read-only snapshot of the OfflineCipher alias family; never deletes or creates credentials. */
    private static Set<String> offlineKeyAliases() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        Set<String> names = new TreeSet<>();
        for (Enumeration<String> aliases = store.aliases(); aliases.hasMoreElements(); ) {
            String alias = aliases.nextElement();
            if (alias.startsWith("tire.offline.v1.")) names.add(alias);
        }
        return names;
    }
    /** User approval 2026-10-03: retain synthetic QA Keystore aliases as evidence instead of deleting them. */
    @After public void cleanup() throws Exception { for (OfflineCipher key : keys) assertTrue(key.hasKey()); }

    @Test public void realKeystoreRoundTripUsesFreshNonceAndBindsSlotGeneration() throws Exception {
        OfflineCipher cipher = cipher();
        byte[] clear = "SYNTHETIC-ONLY 合成离线证据；适用性未评估".getBytes(StandardCharsets.UTF_8);
        byte[] first = cipher.seal(clear, "slot:1:opaque-file-id");
        byte[] second = cipher.seal(clear, "slot:1:opaque-file-id");
        assertFalse(Arrays.equals(first, second));
        assertArrayEquals(clear, cipher.open(first, "slot:1:opaque-file-id"));
        assertFalse(new String(first, StandardCharsets.ISO_8859_1).contains("SYNTHETIC-ONLY"));
        fails("OFFLINE_CORRUPT", () -> cipher.open(first, "slot:2:opaque-file-id"));
        first[first.length - 1] ^= 1;
        fails("OFFLINE_CORRUPT", () -> cipher.open(first, "slot:1:opaque-file-id"));
    }
    /** Destroys only run-scoped destroytest- material; retained QA aliases are asserted untouched. */
    @Test public void otherProfileAndMissingKeyCannotReadOrRegenerateOldData() throws Exception {
        android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue("Dedicated QA application required", context.getPackageName().endsWith(".offlineqa"));
        Set<String> retained = offlineKeyAliases();
        // Run-scoped destroy target: a fresh destroytest- profile (not tracked by the
        // cleanup retention patch, whose kept ciphers must never be deleted here).
        OfflineCipher first = new OfflineCipher(context, "qa-destroytest-" + UUID.randomUUID());
        OfflineCipher second = cipher();
        byte[] clear = "Synthetic old private snapshot".getBytes(StandardCharsets.UTF_8);
        byte[] sealed = first.seal(clear, "slot:1:file");
        second.seal(clear, "slot:1:file");
        fails("OFFLINE_CORRUPT", () -> second.open(sealed, "slot:1:file"));
        assertTrue(first.hasKey());
        first.deleteQaKey();
        assertFalse("run-scoped destroytest key must be gone", first.hasKey());
        fails("OFFLINE_KEY_MISSING", () -> first.open(sealed, "slot:1:file"));
        fails("OFFLINE_KEY_MISSING", () -> first.open(sealed, "slot:1:file"));
        // Retained QA credentials unaffected: the sibling control profile still
        // seals/opens and every pre-existing offline alias survives the destruction.
        assertArrayEquals(clear, second.open(second.seal(clear, "slot:2:file"), "slot:2:file"));
        assertTrue(second.hasKey());
        assertTrue(offlineKeyAliases().containsAll(retained));
    }
    @Test public void unknownHeaderTruncationAndOverLimitFailBeforeDecryption() throws Exception {
        OfflineCipher cipher = cipher();
        fails("OFFLINE_CORRUPT", () -> cipher.open(new byte[12], "slot:1:file"));
        byte[] sealed = cipher.seal(new byte[] {1, 2, 3}, "slot:1:file");
        sealed[4] = 2;
        fails("OFFLINE_CORRUPT", () -> cipher.open(sealed, "slot:1:file"));
        fails("OFFLINE_TOO_LARGE", () -> cipher.seal(new byte[8 * 1024 * 1024 + 1], "slot:1:file"));
    }
}
