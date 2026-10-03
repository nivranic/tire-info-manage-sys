package org.taiji.tireintelligence.mobile;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.function.LongSupplier;

/** Bounded cancellation-before-registration and duplicate-completion memory. */
public final class RequestRegistry {
    private static final long LIFETIME_MS = 75_000;
    private final LongSupplier clock;
    private final Map<String,Ticket> active = new HashMap<>();
    private final Map<String,Long> before = new LinkedHashMap<>(), completed = new LinkedHashMap<>();
    private boolean resetting;
    private long generation;
    public RequestRegistry(LongSupplier clock) { this.clock = clock; }
    public static final class Ticket {
        public final String id;
        public final long generation, deadline;
        private boolean cancelled;
        private Runnable cancel;
        Ticket(String id, long generation, long deadline) { this.id = id; this.generation = generation; this.deadline = deadline; }
        public synchronized void attach(Runnable action) { cancel = action; if (cancelled) action.run(); }
        public synchronized void detach() { cancel = null; }
        public synchronized void cancel() { if (cancelled) return; cancelled = true; if (cancel != null) cancel.run(); }
        public synchronized void check() throws NativeFailure { if (cancelled) throw new NativeFailure("REQUEST_CANCELLED"); }
    }
    private void prune() {
        long now = clock.getAsLong();
        before.values().removeIf(at -> now - at >= LIFETIME_MS);
        completed.values().removeIf(at -> now - at >= LIFETIME_MS);
    }
    public synchronized Ticket register(String rawId) throws NativeFailure {
        NativePolicy.requestId(rawId); String id = rawId.toLowerCase(Locale.ROOT); prune();
        if (resetting) throw new NativeFailure("SESSION_RESET_IN_PROGRESS");
        if (before.remove(id) != null) throw new NativeFailure("REQUEST_CANCELLED");
        if (active.containsKey(id) || completed.containsKey(id)) throw new NativeFailure("DUPLICATE_REQUEST_ID");
        if (active.size() >= 8) throw new NativeFailure("TOO_MANY_REQUESTS");
        Ticket ticket = new Ticket(id, generation, clock.getAsLong() + LIFETIME_MS); active.put(id, ticket); return ticket;
    }
    public synchronized void cancel(String rawId) throws NativeFailure {
        NativePolicy.requestId(rawId); String id = rawId.toLowerCase(Locale.ROOT); prune();
        Ticket ticket = active.get(id);
        if (ticket != null) ticket.cancel();
        else if (!completed.containsKey(id)) {
            if (before.size() >= 256 && !before.containsKey(id)) throw new NativeFailure("CANCEL_QUEUE_FULL");
            before.put(id, clock.getAsLong());
        }
    }
    public synchronized void complete(Ticket ticket) {
        ticket.cancel(); active.remove(ticket.id); completed.put(ticket.id, clock.getAsLong());
        if (completed.size() > 256) completed.remove(completed.keySet().iterator().next());
    }
    public synchronized void check(Ticket ticket) throws NativeFailure {
        ticket.check();
        if (ticket.generation != generation) throw new NativeFailure("REQUEST_CANCELLED");
        if (clock.getAsLong() >= ticket.deadline) throw new NativeFailure("API_TIMEOUT");
    }
    public synchronized void beginReset() throws NativeFailure {
        if (resetting) throw new NativeFailure("SESSION_RESET_IN_PROGRESS");
        resetting = true; generation++;
        for (Ticket ticket : active.values()) ticket.cancel();
    }
    public synchronized void endReset() { resetting = false; }
    synchronized long freezeGeneration() throws NativeFailure {
        if (resetting) throw new NativeFailure("SESSION_RESET_IN_PROGRESS");
        return generation;
    }
    synchronized void checkGeneration(long expected) throws NativeFailure {
        if (resetting) throw new NativeFailure("SESSION_RESET_IN_PROGRESS");
        if (expected != generation) throw new NativeFailure("SESSION_CHANGED");
    }
    public synchronized void cancelAll() { for (Ticket ticket : active.values()) ticket.cancel(); }
}
