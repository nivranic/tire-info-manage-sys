package org.taiji.tireintelligence.mobile;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Only AES-GCM ciphertext is written to the app-private, non-backup directory. */
public final class EncryptedSessionStore implements SessionState.Store {
    private final AtomicFile file;
    private final String alias;
    private final byte[] aad;
    public EncryptedSessionStore(Context context, String namespace) throws NativeFailure {
        try {
            aad = (context.getPackageName() + ":" + namespace).getBytes(StandardCharsets.UTF_8);
            StringBuilder digest = new StringBuilder();
            for (byte value : MessageDigest.getInstance("SHA-256").digest(aad)) digest.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            alias = "tire.session." + digest;
            file = new AtomicFile(new File(context.getNoBackupFilesDir(), "session-" + digest + ".enc"));
        } catch (Exception ignored) { throw new NativeFailure("SESSION_STORE_UNAVAILABLE"); }
    }
    private SecretKey key(boolean create) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias(alias)) return (SecretKey) store.getKey(alias, null);
        if (!create) throw new NativeFailure("SESSION_STORE_INVALID");
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).setRandomizedEncryptionRequired(true).build());
        return generator.generateKey();
    }
    private boolean exists() { return file.getBaseFile().exists() || new File(file.getBaseFile().getPath() + ".bak").exists(); }
    @Override public synchronized String load() throws NativeFailure {
        if (!exists()) return null;
        try {
            if (file.getBaseFile().length() > 8192 || new File(file.getBaseFile().getPath() + ".bak").length() > 8192) throw new NativeFailure("SESSION_STORE_INVALID");
            byte[] encoded = file.readFully();
            if (encoded.length < 30 || encoded.length > 8192 || encoded[0] != 1) throw new NativeFailure("SESSION_STORE_INVALID");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, Arrays.copyOfRange(encoded, 1, 13)));
            cipher.updateAAD(aad);
            byte[] clear = cipher.doFinal(encoded, 13, encoded.length - 13);
            try {
                String envelope = NativePolicy.utf8(clear, "SESSION_STORE_INVALID");
                if (!envelope.startsWith("1\n")) throw new NativeFailure("SESSION_STORE_INVALID");
                String cookie = envelope.substring(2);
                if (cookie.isEmpty()) return null;
                try { NativePolicy.requestId(cookie); } catch (NativeFailure ignored) { throw new NativeFailure("SESSION_STORE_INVALID"); }
                return cookie;
            } finally { Arrays.fill(clear, (byte) 0); }
        } catch (NativeFailure error) { throw error; }
        catch (javax.crypto.AEADBadTagException ignored) { throw new NativeFailure("SESSION_STORE_INVALID"); }
        catch (Exception ignored) { throw new NativeFailure("SESSION_STORE_READ_FAILED"); }
    }
    @Override public synchronized void save(String cookie) throws NativeFailure {
        if (cookie != null) { try { NativePolicy.requestId(cookie); } catch (NativeFailure ignored) { throw new NativeFailure("SESSION_STORE_INVALID"); } }
        FileOutputStream stream = null;
        byte[] clear = ("1\n" + (cookie == null ? "" : cookie)).getBytes(StandardCharsets.UTF_8);
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key(!exists())); cipher.updateAAD(aad);
            byte[] ciphertext = cipher.doFinal(clear), iv = cipher.getIV();
            if (iv.length != 12) throw new NativeFailure("SESSION_STORE_WRITE_FAILED");
            stream = file.startWrite(); stream.write(1); stream.write(iv); stream.write(ciphertext); stream.getFD().sync(); file.finishWrite(stream); stream = null;
            if (!exists() || !java.util.Objects.equals(load(), cookie)) throw new NativeFailure("SESSION_STORE_WRITE_FAILED");
        } catch (Exception ignored) {
            if (stream != null) file.failWrite(stream);
            throw new NativeFailure("SESSION_STORE_WRITE_FAILED");
        } finally { Arrays.fill(clear, (byte) 0); }
    }
    @Override public synchronized void delete() throws NativeFailure {
        // Keeping the app-owned key is harmless and avoids deleting shared platform credentials.
        file.delete();
        if (exists()) throw new NativeFailure("SESSION_STORE_DELETE_FAILED");
    }
}
