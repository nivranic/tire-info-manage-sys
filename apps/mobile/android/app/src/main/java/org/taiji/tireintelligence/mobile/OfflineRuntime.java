package org.taiji.tireintelligence.mobile;

import android.content.Context;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/** One application authority shared by Activity IPC and OS jobs, never Activity-owned. */
final class OfflineRuntime {
    private static final Map<String, OfflineRuntime> INSTANCES = new HashMap<>();
    private final Context context;
    private final String namespace;
    final ExecutorService offlineTasks;
    final ExecutorService syncTasks;
    final AtomicBoolean resetting = new AtomicBoolean();
    final AtomicLong documentGeneration = new AtomicLong();
    final NativeHttpBridge http;
    final String httpError;
    private OfflinePackStore store;
    private String storeError;
    private long storeDocumentGeneration;

    static synchronized OfflineRuntime get(Context context) {
        Context app = context.getApplicationContext();
        String key = app.getPackageName() + ":" + BuildConfig.SESSION_NAMESPACE + ":" + BuildConfig.API_PORT;
        return INSTANCES.computeIfAbsent(key, ignored -> new OfflineRuntime(app));
    }

    private static ExecutorService executor(String name, int capacity) {
        return new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(capacity), action -> {
            Thread worker = new Thread(action, name); worker.setDaemon(true); return worker;
        });
    }

    private OfflineRuntime(Context context) {
        this.context = context;
        namespace = BuildConfig.SESSION_NAMESPACE;
        offlineTasks = executor("tire-offline-store", 16);
        // A long owned history download does not hold the Store executor or its lock.
        syncTasks = executor("tire-offline-sync", 1);
        NativeHttpBridge initialized = null;
        String error = null;
        if (!BuildConfig.DEBUG) error = "RELEASE_API_NOT_CONFIGURED";
        else {
            try {
                initialized = new NativeHttpBridge("http://127.0.0.1:" + BuildConfig.API_PORT,
                    new EncryptedSessionStore(context, namespace + ":127.0.0.1:" + BuildConfig.API_PORT));
            } catch (NativeFailure failure) { error = failure.code; }
        }
        http = initialized;
        httpError = error;
    }

    synchronized OfflinePackStore store() throws NativeFailure {
        if (storeError != null) throw new NativeFailure(storeError);
        if (store == null) {
            try { store = new OfflinePackStore(context, namespace); store.attachFallbackHttp(http); }
            catch (NativeFailure failure) { storeError = failure.code; throw failure; }
        }
        long current = documentGeneration.get();
        if (storeDocumentGeneration != current) {
            store.invalidateFallbackGrants();
            storeDocumentGeneration = current;
        }
        return store;
    }

    NativeHttpBridge http() throws NativeFailure {
        if (httpError != null || http == null) throw new NativeFailure(httpError == null ? "API_CLIENT_UNAVAILABLE" : httpError);
        return http;
    }

    // Activity destroy invalidates only ephemeral one-shot grants. The shared HTTP,
    // package catalog and future WorkManager tasks remain application-owned.
    void documentEnded() { documentGeneration.incrementAndGet(); }
    void reconcile() throws Exception {OfflineSyncWorker.reconcile(context,store().syncSchedulingStatus());}
    org.json.JSONObject run(org.json.JSONObject request,java.util.function.Supplier<OfflineSyncConditions.Sample> conditions) throws Exception {
        OfflineSyncCoordinator.Remote remote;
        try{remote=OfflineSyncCoordinator.bridge(http());}
        catch(NativeFailure failure){return store().syncBlocked(request,failure.code);}
        return new OfflineSyncCoordinator(store(),remote,conditions).run(request);
    }
}
