package org.taiji.tireintelligence.mobile;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.function.LongSupplier;

/** Application-owned account/document publication gate. No picker, provider or stream I/O under its lock. */
public final class DownloadAuthority {
    private static final long TTL = 120_000_000_000L;
    private static final String CHANGED = "DOWNLOAD_CONTEXT_CHANGED", UNAVAILABLE = "DOWNLOAD_AUTHORITY_UNAVAILABLE";
    private final SecureRandom random = new SecureRandom();
    private final LongSupplier clock;
    private final Map<String, Lease> leases = new HashMap<>();
    private final Set<String> documents = new HashSet<>(), pending = new HashSet<>();
    private long revision;
    private boolean closed;
    private enum Phase { PREPARED, RESERVED, COMMITTING }
    private static final class Lease {
        final String document; final long revision, issued; Phase phase = Phase.PREPARED;
        Lease(String document, long revision, long issued) { this.document = document; this.revision = revision; this.issued = issued; }
    }
    public DownloadAuthority() { this(System::nanoTime); }
    DownloadAuthority(LongSupplier clock) { this.clock = clock; }
    private String opaque() {
        byte[] bytes = new byte[32]; random.nextBytes(bytes);
        StringBuilder token = new StringBuilder(64);
        for (byte value : bytes) token.append(Character.forDigit((value >>> 4) & 15, 16)).append(Character.forDigit(value & 15, 16));
        return token.toString();
    }
    private void prune() {
        long now = clock.getAsLong();
        leases.values().removeIf(lease -> lease.phase != Phase.COMMITTING && (now - lease.issued < 0 || now - lease.issued >= TTL));
    }
    private void bump() throws NativeFailure {
        leases.values().removeIf(lease -> lease.phase != Phase.COMMITTING);
        if (closed || revision == Long.MAX_VALUE) { closed = true; throw new NativeFailure(UNAVAILABLE); }
        revision++;
    }
    public synchronized String document() throws NativeFailure {
        if (closed || documents.size() >= 16) throw new NativeFailure(UNAVAILABLE);
        String token = opaque(); documents.add(token); return token;
    }
    public synchronized void endDocument(String document) {
        documents.remove(document);
        leases.values().removeIf(lease -> lease.document.equals(document) && lease.phase != Phase.COMMITTING);
    }
    public synchronized void invalidate() throws NativeFailure { bump(); }
    public synchronized void close() {
        try { bump(); } catch (NativeFailure ignored) { }
        closed = true; documents.clear();
    }
    public synchronized Transition beginTransition() throws NativeFailure {
        bump();
        if (pending.size() >= 128) { closed = true; throw new NativeFailure(UNAVAILABLE); }
        String token = opaque(); pending.add(token); return new Transition(token);
    }
    public final class Transition implements AutoCloseable {
        private final String ticket;
        private Transition(String ticket) { this.ticket = ticket; }
        @Override public void close() {
            synchronized (DownloadAuthority.this) {
                if (pending.remove(ticket)) { try { bump(); } catch (NativeFailure ignored) { } }
            }
        }
    }
    public synchronized String prepare(String document) throws NativeFailure {
        prune();
        if (closed || !pending.isEmpty() || !documents.contains(document)) throw new NativeFailure(CHANGED);
        if (leases.size() >= 128) throw new NativeFailure("DOWNLOAD_DIALOG_BUSY");
        String token = opaque(); leases.put(token, new Lease(document, revision, clock.getAsLong())); return token;
    }
    private synchronized void advance(String token, String document, Phase from, Phase to) throws NativeFailure {
        prune(); Lease lease = leases.get(token);
        if (closed || !pending.isEmpty() || !documents.contains(document) || lease == null
            || !lease.document.equals(document) || lease.revision != revision || lease.phase != from) throw new NativeFailure(CHANGED);
        lease.phase = to;
    }
    public synchronized Reservation reserve(String token, String document) throws NativeFailure {
        advance(token, document, Phase.PREPARED, Phase.RESERVED); return new Reservation(token, document);
    }
    /** Returns true only when a pre-commit operation was actually revoked. Unknown release is idempotent. */
    public synchronized boolean release(String token, String document) {
        Lease lease = leases.get(token);
        if (lease != null && lease.document.equals(document) && lease.phase != Phase.COMMITTING) { leases.remove(token); return true; }
        return false;
    }
    public final class Reservation implements AutoCloseable {
        private final String token, document;
        private Reservation(String token, String document) { this.token = token; this.document = document; }
        /** Linearization point: later release/invalidation cannot promise rollback of an authorized write. */
        public void commit() throws NativeFailure { advance(token, document, Phase.RESERVED, Phase.COMMITTING); }
        public boolean revokeBeforeCommit() {
            synchronized (DownloadAuthority.this) {
                Lease lease = leases.get(token);
                if (lease != null && lease.phase == Phase.COMMITTING) return false;
                leases.remove(token); return true;
            }
        }
        @Override public void close() { synchronized (DownloadAuthority.this) { leases.remove(token); } }
    }
    /** Run only on a validated request. Decode exactly once without treating '+' as a space. */
    public static boolean identityRequest(String method, String path) throws NativeFailure {
        NativePolicy.path(path);
        String raw = path.split("\\?", 2)[0]; ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        for (int i = 0; i < raw.length();) {
            if (raw.charAt(i) == '%') { bytes.write((Character.digit(raw.charAt(i + 1), 16) << 4) | Character.digit(raw.charAt(i + 2), 16)); i += 3; }
            else { int cp = raw.codePointAt(i); byte[] encoded = new String(Character.toChars(cp)).getBytes(StandardCharsets.UTF_8); bytes.write(encoded, 0, encoded.length); i += Character.charCount(cp); }
        }
        String route = NativePolicy.utf8(bytes.toByteArray(), "INVALID_API_PATH");
        if (method.equals("GET") && route.equals("/v1/auth/me")) return true;
        if (method.equals("POST") && (route.equals("/v1/auth/register") || route.equals("/v1/auth/login") || route.equals("/v1/auth/logout") || route.equals("/v1/auth/profile"))) return true;
        String[] parts = route.split("/", -1);
        return parts.length >= 5 && parts[0].isEmpty() && parts[1].equals("v1") && parts[2].equals("auth") && parts[3].equals("users") && !parts[4].isEmpty()
            && ((method.equals("DELETE") && parts.length == 5) || (method.equals("POST") && parts.length == 6 && (parts[5].equals("role") || parts[5].equals("password"))));
    }
}
