package org.taiji.tireintelligence.mobile;

import com.getcapacitor.JSObject;
import java.util.Arrays;
import java.util.function.BooleanSupplier;
import org.json.JSONObject;

/** Two fixed metadata reads share one HTTP fence and a final owner/store CAS. */
final class OfflineFallbackAuthorityCoordinator {
    private OfflineFallbackAuthorityCoordinator() {}
    private static JSONObject body(JSObject response) throws NativeFailure {
        if (response.getInteger("status", 0) != 200) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_UNAVAILABLE");
        byte[] raw = NativePolicy.decode(response.getString("body_base64"), 1024 * 1024, "OFFLINE_FALLBACK_AUTHORITY_INVALID");
        try { return OfflinePackageValidator.response(raw); }
        finally { Arrays.fill(raw, (byte) 0); }
    }
    static JSONObject refresh(OfflinePackStore store, NativeHttpBridge http, BooleanSupplier stillCurrent) throws Exception {
        OfflineFallbackAuthority.Capture capture = store.captureFallbackAuthority();
        OfflinePackStore.FallbackNetwork previousNetwork = store.observedFallbackNetwork();
        NativeHttpBridge.SessionFence fence = http.fallbackMetadataFence();
        JSObject settingsResponse = http.fallbackMetadata("/v1/source-settings", fence);
        JSONObject settings = body(settingsResponse);
        String owner = settingsResponse.getJSObject("headers").getString("x-tire-offline-owner-scope");
        if (owner == null || !owner.matches("[0-9a-f]{64}")) throw new NativeFailure("OFFLINE_FALLBACK_AUTHORITY_INVALID");
        JSONObject directory = body(http.fallbackMetadata("/v1/sources", fence));
        return http.publish(fence, () -> {
            // Session checks precede Store locking; publication always uses HTTP -> Store lock order.
            boolean knownSessionChanged = previousNetwork != null && (previousNetwork.http != http || !previousNetwork.current());
            return store.observeFallbackAuthority(capture, settings, directory, owner, http.sessionBinding(fence),
                stillCurrent, http, fence, knownSessionChanged);
        });
    }
}
