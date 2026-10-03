package org.taiji.tireintelligence.mobile;

import java.util.LinkedHashSet;
import java.util.Set;
import java.util.UUID;
import org.json.JSONObject;

/** Runtime-only terminal denials observed by the private HTTP authority, never caller IPC. */
final class NativeQueryDenials {
    static final int MAX_DENIALS = 1024;
    private final Set<String> denied;
    private boolean closed;

    /** Constructible only from a parsed fixed HTTP request; no response or caller can supply it. */
    static final class Capture {
        private final String queryId;
        private Capture(String queryId) { this.queryId = queryId; }
    }

    NativeQueryDenials() { this(new LinkedHashSet<>()); }
    /** Package-private write-fault injection; production uses its own bounded in-memory set. */
    NativeQueryDenials(Set<String> denied) {
        if (denied == null || !denied.isEmpty()) throw new IllegalArgumentException("Fresh denial storage required");
        this.denied = denied;
    }

    private static String uuid(Object value) throws NativeFailure {
        if (!(value instanceof String)) throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
        NativePolicy.requestId((String) value);
        return UUID.fromString((String) value).toString();
    }

    static Capture capture(NativePolicy.Request request) {
        if (request == null || !"POST".equals(request.method) || !"/v1/fallback-consents".equals(request.path)) return null;
        try {
            JSONObject body = OfflinePackageValidator.parse(request.body);
            OfflinePackageValidator.keys(body, "query_id", "decision", "scope");
            if (!"deny".equals(body.opt("decision")) || !"once".equals(body.opt("scope"))) return null;
            return new Capture(uuid(body.opt("query_id")));
        } catch (NativeFailure | RuntimeException ignored) { return null; }
    }

    /** Bridge invokes this only while the owned session/publication lock is held. */
    synchronized void observeOwnedResponse(Capture capture, int status, byte[] received) {
        if (capture == null || status != 201 || received == null) return;
        try {
            JSONObject response = OfflinePackageValidator.response(received);
            if (!"deny".equals(response.opt("decision")) || !"once".equals(response.opt("scope"))) return;
            uuid(response.opt("id")); // Actual response has no query_id. The request capture owns that binding.
        } catch (NativeFailure | RuntimeException ignored) { return; }
        if (closed) return;
        try {
            if (denied.contains(capture.queryId)) return;
            if (denied.size() >= MAX_DENIALS) { closed = true; return; }
            if (!denied.add(capture.queryId) || !denied.contains(capture.queryId)) closed = true;
        } catch (RuntimeException ignored) { closed = true; }
    }

    synchronized void check(JSONObject intent) throws NativeFailure {
        Object value = intent == null ? null : intent.opt("failure");
        if (!(value instanceof JSONObject)) throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
        JSONObject failure = (JSONObject) value;
        if (!"source_response".equals(failure.opt("scope"))) return;
        String queryId = uuid(failure.opt("query_id"));
        if (closed) throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
        try {
            if (denied.contains(queryId)) throw new NativeFailure("OFFLINE_FALLBACK_NEVER");
        } catch (RuntimeException ignored) {
            closed = true; throw new NativeFailure("OFFLINE_FALLBACK_CAPACITY");
        }
    }

    synchronized int count() { return denied.size(); }
    synchronized boolean closed() { return closed; }
}
