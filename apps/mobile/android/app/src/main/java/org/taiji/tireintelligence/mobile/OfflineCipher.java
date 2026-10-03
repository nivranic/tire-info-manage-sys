package org.taiji.tireintelligence.mobile;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** App/profile-owned device-data key. No cookie, provider secret or session key is read. */
final class OfflineCipher {
    private static final byte[] MAGIC = new byte[] {'T', 'I', 'O', 'F', 1};
    private static final int NONCE_BYTES = 12;
    private static final int TAG_BYTES = 16;
    private static final int MAX_BYTES = 8 * 1024 * 1024;
    private final String alias;
    private final byte[] profile;

    OfflineCipher(Context context, String namespace) throws NativeFailure {
        if (namespace == null || !namespace.matches("[a-z0-9][a-z0-9:-]{0,120}")) {
            throw new NativeFailure("OFFLINE_INVALID_PROFILE");
        }
        profile = (context.getPackageName() + ":offline-data-v1:" + namespace).getBytes(StandardCharsets.UTF_8);
        alias = "tire.offline.v1." + sha256(profile);
    }

    static String sha256(byte[] bytes) throws NativeFailure {
        try {
            StringBuilder digest = new StringBuilder();
            for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) {
                digest.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            }
            return digest.toString();
        } catch (Exception ignored) { throw new NativeFailure("OFFLINE_CRYPTO_UNAVAILABLE"); }
    }

    /** Check this profile's alias only; never creates a key or enumerates credentials. */
    boolean hasKey() throws NativeFailure {
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            return store.containsAlias(alias);
        } catch (Exception ignored) { throw new NativeFailure("OFFLINE_CRYPTO_UNAVAILABLE"); }
    }

    private SecretKey key(boolean create) throws NativeFailure {
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            if (!store.containsAlias(alias)) {
                if (!create) throw new NativeFailure("OFFLINE_KEY_MISSING");
                KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
                generator.init(new KeyGenParameterSpec.Builder(alias,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true).build());
                generator.generateKey();
            }
            Object loaded = store.getKey(alias, null);
            if (!(loaded instanceof SecretKey)) throw new NativeFailure("OFFLINE_KEY_MISSING");
            return (SecretKey) loaded;
        } catch (NativeFailure error) { throw error; }
        catch (Exception ignored) { throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE"); }
    }

    private byte[] aad(String purpose) throws NativeFailure {
        if (purpose == null || purpose.length() > 256 || purpose.codePoints().anyMatch(Character::isISOControl)) {
            throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        }
        return (new String(profile, StandardCharsets.UTF_8) + ":" + purpose).getBytes(StandardCharsets.UTF_8);
    }

    byte[] seal(byte[] clear, String purpose) throws NativeFailure {
        if (clear == null || clear.length > MAX_BYTES) throw new NativeFailure("OFFLINE_TOO_LARGE");
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key(true));
            cipher.updateAAD(aad(purpose));
            byte[] nonce = cipher.getIV();
            if (nonce.length != NONCE_BYTES) throw new NativeFailure("OFFLINE_CRYPTO_UNAVAILABLE");
            byte[] sealed = cipher.doFinal(clear);
            return ByteBuffer.allocate(MAGIC.length + NONCE_BYTES + sealed.length)
                .put(MAGIC).put(nonce).put(sealed).array();
        } catch (NativeFailure error) { throw error; }
        catch (Exception ignored) { throw new NativeFailure("OFFLINE_ENCRYPT_FAILED"); }
    }

    byte[] open(byte[] sealed, String purpose) throws NativeFailure {
        if (sealed == null || sealed.length < MAGIC.length + NONCE_BYTES + TAG_BYTES ||
            sealed.length > MAX_BYTES + MAGIC.length + NONCE_BYTES + TAG_BYTES ||
            !Arrays.equals(Arrays.copyOfRange(sealed, 0, MAGIC.length), MAGIC)) {
            throw new NativeFailure("OFFLINE_CORRUPT");
        }
        try {
            byte[] nonce = Arrays.copyOfRange(sealed, MAGIC.length, MAGIC.length + NONCE_BYTES);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, nonce));
            cipher.updateAAD(aad(purpose));
            return cipher.doFinal(sealed, MAGIC.length + NONCE_BYTES, sealed.length - MAGIC.length - NONCE_BYTES);
        } catch (NativeFailure error) { throw error; }
        catch (Exception ignored) { throw new NativeFailure("OFFLINE_CORRUPT"); }
    }

    /** Exact app-owned QA key only; production removal does not enumerate or delete credentials. */
    void deleteQaKey() throws NativeFailure {
        if (!new String(profile, StandardCharsets.UTF_8).contains(".offlineqa:offline-data-v1:qa-")) {
            throw new NativeFailure("OFFLINE_QA_SCOPE_REQUIRED");
        }
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            store.deleteEntry(alias);
        } catch (Exception ignored) { throw new NativeFailure("OFFLINE_STORE_UNAVAILABLE"); }
    }
}
