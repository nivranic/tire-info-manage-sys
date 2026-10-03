package org.taiji.tireintelligence.mobile;

/** Durable storage failure always closes the native API; recovery never deletes or mints state. */
public final class SessionState {
    public interface Store { String load() throws NativeFailure; void save(String cookie) throws NativeFailure; void delete() throws NativeFailure; }
    private final Store store;
    private String cookie, failure;
    private boolean bootstrapped;
    private long generation;
    /** Opaque in-memory authority. Never serialize this object or its cookie. */
    static final class Fence {
        private final String cookie;
        private final long generation;
        private Fence(String cookie, long generation) { this.cookie = cookie; this.generation = generation; }
    }
    public SessionState(Store store) {
        this.store = store;
        try { loadAndVerify(); } catch (NativeFailure error) { failure = error.code; }
    }
    private void loadAndVerify() throws NativeFailure {
        String saved = store.load();
        if (saved != null) { try { NativePolicy.requestId(saved); } catch (NativeFailure ignored) { throw new NativeFailure("SESSION_STORE_INVALID"); } }
        store.save(saved); cookie = saved; bootstrapped = false; failure = null; generation++;
    }
    public synchronized String error() { return failure; }
    public synchronized String cookie() { return cookie; }
    public synchronized boolean bootstrapped() { return bootstrapped; }
    public synchronized void markBootstrapped() throws NativeFailure { check(); bootstrapped = true; }
    public synchronized void check() throws NativeFailure { if (failure != null) throw new NativeFailure(failure); }
    synchronized Fence freeze() throws NativeFailure {
        check();
        if (cookie == null) throw new NativeFailure("SESSION_COOKIE_MISSING");
        return new Fence(cookie, generation);
    }
    synchronized void check(Fence fence) throws NativeFailure {
        check();
        if (fence == null || fence.generation != generation || !java.util.Objects.equals(cookie, fence.cookie)) {
            throw new NativeFailure("SESSION_CHANGED");
        }
    }
    synchronized String binding(Fence fence) throws NativeFailure {
        check(fence);
        try {
            byte[] hash = java.security.MessageDigest.getInstance("SHA-256").digest(
                ("device-sync-session@1:" + fence.cookie).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(64);
            for (byte value : hash) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return hex.toString();
        } catch (java.security.NoSuchAlgorithmException ignored) { throw new NativeFailure("OFFLINE_CRYPTO_UNAVAILABLE"); }
    }
    public synchronized void recover() throws NativeFailure {
        if (failure == null) return;
        try { loadAndVerify(); } catch (NativeFailure error) { failure = error.code; throw error; }
    }
    public synchronized void persist(String replacement) throws NativeFailure {
        check();
        if (java.util.Objects.equals(cookie, replacement)) return;
        try { store.save(replacement); cookie = replacement; generation++; if (replacement == null) bootstrapped = false; }
        catch (NativeFailure error) { failure = error.code; cookie = null; bootstrapped = false; generation++; throw error; }
    }
    public synchronized void reset() throws NativeFailure {
        generation++;
        try { store.delete(); cookie = null; bootstrapped = false; failure = null; }
        catch (NativeFailure error) { failure = error.code; throw error; }
    }
}
