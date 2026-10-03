package org.taiji.tireintelligence.mobile;

import android.app.Activity;
import android.content.Intent;
import android.content.ContentResolver;
import android.database.Cursor;
import android.net.Uri;
import android.os.SystemClock;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.OutputStream;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import org.json.JSONObject;
import org.json.JSONTokener;

@CapacitorPlugin(name = "TireNative")
public final class TireNativePlugin extends Plugin {
    private final ExecutorService requests = Executors.newFixedThreadPool(8);
    private final ExecutorService controls = new ThreadPoolExecutor(1,1,0,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(16));
    private final ExecutorService downloads = new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(1), action -> {
        Thread worker = new Thread(action, "tire-saf-download"); worker.setDaemon(true); return worker;
    });
    private final AtomicBoolean downloadBusy = new AtomicBoolean();
    private ExecutorService offlineTasks;
    private AtomicBoolean offlineResetting;
    private OfflineRuntime runtime;
    private final Set<RequestRegistry.Ticket> ownedRequests = java.util.concurrent.ConcurrentHashMap.newKeySet();
    private final AtomicLong offlineLifecycle = new AtomicLong();
    private String offlineInitializationError;
    private NativeHttpBridge http;
    private String initializationError;
    private DownloadJob downloadJob;
    private String downloadCallbackId;
    private volatile boolean destroyed;
    private String pendingBack;
    private long backDeadline;
    @Override public void load() {
        runtime = OfflineRuntime.get(getContext());
        offlineTasks = runtime.offlineTasks;
        offlineResetting = runtime.resetting;
        http = runtime.http;
        initializationError = runtime.httpError;
        offlineTasks.execute(() -> {
            try { requireOffline(); runtime.reconcile(); } catch (NativeFailure failure) { offlineInitializationError = failure.code; }
            catch(Exception ignored) { /* Storage remains usable when OS scheduling is unavailable. */ }
        });
    }
    private String baseUrl() { return BuildConfig.DEBUG ? "http://127.0.0.1:" + BuildConfig.API_PORT : ""; }
    private void guard() throws NativeFailure {
        if (destroyed) throw new NativeFailure("API_CLIENT_UNAVAILABLE");
        if (!(getActivity() instanceof MainActivity) || !((MainActivity) getActivity()).isTrustedDocument()) throw new NativeFailure("IPC_ORIGIN_DENIED");
    }
    private NativeHttpBridge requireHttp() throws NativeFailure {
        if (initializationError != null || http == null) throw new NativeFailure(initializationError == null ? "API_CLIENT_UNAVAILABLE" : initializationError);
        return http;
    }
    private OfflinePackStore requireOffline() throws NativeFailure {
        if (destroyed) throw new NativeFailure("API_CLIENT_UNAVAILABLE");
        if (offlineInitializationError != null) throw new NativeFailure(offlineInitializationError);
        return runtime.store();
    }
    /** Every main-frame document invalidates queued work and prior-page one-shot grants. */
    void documentStarted() { offlineLifecycle.incrementAndGet(); if (runtime != null) runtime.documentEnded(); }
    private interface OfflineAction { JSONObject run(OfflinePackStore store) throws Exception; }
    private void offline(PluginCall call, OfflineAction action) {
        try {
            guard();
            if (offlineResetting.get()) throw new NativeFailure("SESSION_RESET_IN_PROGRESS");
            final long admitted = offlineLifecycle.get();
            offlineTasks.execute(() -> {
                try {
                    guard();
                    if (offlineResetting.get() || offlineLifecycle.get() != admitted) throw new NativeFailure("REQUEST_CANCELLED");
                    JSONObject result = action.run(requireOffline());
                    if (destroyed || offlineLifecycle.get() != admitted) throw new NativeFailure("REQUEST_CANCELLED");
                    call.resolve(JSObject.fromJSONObject(result));
                } catch (NativeFailure failure) { reject(call, failure); }
                catch (Exception ignored) { call.reject("OFFLINE_STORAGE_FAILED", "OFFLINE_STORAGE_FAILED"); }
            });
        } catch (NativeFailure failure) { reject(call, failure); }
        catch (RejectedExecutionException ignored) { call.reject("OFFLINE_BUSY", "OFFLINE_BUSY"); }
    }
    private static JSONObject offlineRequest(PluginCall call) throws NativeFailure {
        fields(call.getData(), "request");
        JSONObject request = call.getData().optJSONObject("request");
        if (request == null) throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        return request;
    }
    private static JSONObject fallbackRequest(PluginCall call, boolean authorize) throws NativeFailure {
        JSONObject submitted = offlineRequest(call);
        if (submitted.has("raw_json")) {
            JSONObject core = OfflineFallbackWire.decode(submitted), intent = core.optJSONObject("intent");
            if (intent == null || !"device-fallback-intent@2".equals(intent.optString("schema")))
                throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
            return core;
        }
        JSONObject intent = submitted.optJSONObject("intent");
        if (authorize || (intent != null && "device-fallback-intent@2".equals(intent.optString("schema"))))
            throw new NativeFailure("OFFLINE_FALLBACK_INVALID");
        return submitted;
    }
    private static JSONObject fallbackResponse(JSONObject core) throws NativeFailure {
        String schema = core.optString("schema");
        if (schema.equals("device-fallback-grant@2") || schema.equals("device-fallback-result@2")
            || (schema.equals("device-fallback-authorization@1") && core.optString("state").equals("allowed")))
            return OfflineFallbackWire.encode(core);
        return core;
    }
    @PluginMethod public void offlineStatus(PluginCall call) {
        try { fields(call.getData()); offline(call, OfflinePackStore::status); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineList(PluginCall call) {
        try { fields(call.getData()); offline(call, OfflinePackStore::list); } catch (NativeFailure failure) { reject(call, failure); }
    }
    private interface SyncAction { JSONObject run() throws Exception; }
    private void syncControl(PluginCall call,SyncAction action){
        try{guard();final long admitted=offlineLifecycle.get();controls.execute(()->{
            try{guard();if(offlineResetting.get()||offlineLifecycle.get()!=admitted)throw new NativeFailure("REQUEST_CANCELLED");
                JSONObject value=action.run();runtime.reconcile();if(destroyed||offlineLifecycle.get()!=admitted)throw new NativeFailure("REQUEST_CANCELLED");call.resolve(JSObject.fromJSONObject(value));
            }catch(NativeFailure failure){reject(call,failure);}catch(Exception ignored){call.reject("OFFLINE_SYNC_FAILED","OFFLINE_SYNC_FAILED");}
        });}catch(NativeFailure failure){reject(call,failure);}catch(RejectedExecutionException ignored){call.reject("OFFLINE_BUSY","OFFLINE_BUSY");}
    }
    @PluginMethod public void offlineSyncStatus(PluginCall call){try{fields(call.getData());syncControl(call,()->requireOffline().syncStatus(false));}catch(NativeFailure failure){reject(call,failure);}}
    @PluginMethod public void offlineSyncRevalidate(PluginCall call){try{fields(call.getData());syncControl(call,()->requireOffline().syncStatus(true));}catch(NativeFailure failure){reject(call,failure);}}
    @PluginMethod public void offlineSyncPreview(PluginCall call){try{JSONObject request=offlineRequest(call);syncControl(call,()->{
        NativeHttpBridge bridge=requireHttp();NativeHttpBridge.SessionFence fence=bridge.freezeSession();return requireOffline().syncPreview(request,bridge.sessionBinding(fence));
    });}catch(NativeFailure failure){reject(call,failure);}}
    @PluginMethod public void offlineSyncApply(PluginCall call){try{JSONObject request=offlineRequest(call);syncControl(call,()->{
        NativeHttpBridge bridge=requireHttp();NativeHttpBridge.SessionFence fence=bridge.freezeSession();return requireOffline().syncApply(request,bridge.sessionBinding(fence));
    });}catch(NativeFailure failure){reject(call,failure);}}
    @PluginMethod public void offlineSyncPause(PluginCall call){try{JSONObject request=offlineRequest(call);syncControl(call,()->requireOffline().syncChange(request,false));}catch(NativeFailure failure){reject(call,failure);}}
    @PluginMethod public void offlineSyncRevoke(PluginCall call){try{JSONObject request=offlineRequest(call);syncControl(call,()->requireOffline().syncChange(request,true));}catch(NativeFailure failure){reject(call,failure);}}
    @PluginMethod public void offlineSyncRun(PluginCall call){
        try{guard();JSONObject request=offlineRequest(call);if(offlineResetting.get())throw new NativeFailure("SESSION_RESET_IN_PROGRESS");
            final android.content.Context appContext=getContext().getApplicationContext();
            final long admittedDocument=offlineLifecycle.get();
            runtime.syncTasks.execute(()->{try{
                // Once accepted, a history update belongs to the native host; navigation
                // only detaches delivery and does not fabricate cancellation of consent.
                JSONObject run=runtime.run(request,()->OfflineSyncConditions.sample(appContext));runtime.reconcile();if(!destroyed&&offlineLifecycle.get()==admittedDocument)call.resolve(JSObject.fromJSONObject(run));
            }catch(NativeFailure failure){if(!destroyed&&offlineLifecycle.get()==admittedDocument)reject(call,failure);}catch(Exception ignored){if(!destroyed&&offlineLifecycle.get()==admittedDocument)call.reject("OFFLINE_SYNC_FAILED","OFFLINE_SYNC_FAILED");}});
        }catch(NativeFailure failure){reject(call,failure);}catch(RejectedExecutionException ignored){call.reject("OFFLINE_BUSY","OFFLINE_BUSY");}
    }
    @PluginMethod public void offlineInstall(PluginCall call) {
        try {
            JSONObject request = offlineRequest(call); OfflinePackageValidator.installRequest(request);
            offline(call, store -> {
                final long epoch = offlineLifecycle.get();
                NativeHttpBridge bridge = requireHttp();
                JSONObject descriptor = bridge.offlineDescriptor(OfflinePackageValidator.uuid(request, "package_id"));
                OfflinePackageValidator.descriptor(descriptor, request);
                byte[] original = bridge.downloadOffline(OfflinePackageValidator.uuid(request, "package_id"),
                    OfflinePackageValidator.hash(request, "expected_sha256"), (int) OfflinePackageValidator.number(request, "expected_byte_count", OfflinePackageValidator.MAX_BYTES));
                try {
                    return store.install(request, descriptor, original,
                        () -> !destroyed && !offlineResetting.get() && offlineLifecycle.get() == epoch);
                } finally { Arrays.fill(original, (byte) 0); }
            });
        } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineSearch(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.search(request)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineRead(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.read(request)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineRemove(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.remove(request)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineUnlockPreviousOwner(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.unlockPreviousOwner(request)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackDecide(PluginCall call) {
        try { JSONObject request = fallbackRequest(call, false); offline(call, store -> fallbackResponse(store.decideFallback(request))); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackConsume(PluginCall call) {
        try { JSONObject request = fallbackRequest(call, false); offline(call, store -> fallbackResponse(store.consumeFallback(request))); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackAuthorize(PluginCall call) {
        try { JSONObject request = fallbackRequest(call, true); offline(call, store -> fallbackResponse(store.authorizeFallback(request))); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackRevoke(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.revokeFallback(request)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackAuthorityRefresh(PluginCall call) {
        try {
            fields(call.getData());
            offline(call, store -> {
                final long admitted = offlineLifecycle.get();
                return OfflineFallbackAuthorityCoordinator.refresh(store, requireHttp(),
                    () -> !destroyed && !offlineResetting.get() && offlineLifecycle.get() == admitted);
            });
        } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackStatus(PluginCall call) {
        try { fields(call.getData()); offline(call, OfflinePackStore::fallbackStatus); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackPolicyPreview(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.fallbackPolicyPreview(request)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackPolicyApply(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.fallbackPolicyApply(request)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackPolicyPause(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.fallbackPolicyChange(request, false)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    @PluginMethod public void offlineFallbackPolicyRevoke(PluginCall call) {
        try { JSONObject request = offlineRequest(call); offline(call, store -> store.fallbackPolicyChange(request, true)); } catch (NativeFailure failure) { reject(call, failure); }
    }
    // device-ai host bridge (round 50 P1-3 + journal/N18 command completion):
    // dormant thin wrappers over DeviceAiHost. The wire is not frozen
    // (roundtable D15); no JS flow calls these until the TS SDK module is
    // imported by path, so no product authorization changes with them.
    private interface DeviceAiAction { JSONObject run(JSONObject request) throws Exception; }
    private void deviceAi(PluginCall call, DeviceAiAction action) {
        try {
            guard(); JSONObject request = offlineRequest(call);
            requests.execute(() -> {
                try {
                    guard();
                    call.resolve(JSObject.fromJSONObject(action.run(request)));
                } catch (DeviceAiHost.DeviceAiHostException error) {
                    call.reject(error.serverCode != null ? error.serverCode : error.code, error.code);
                } catch (NativeFailure failure) { reject(call, failure); }
                catch (Exception ignored) { call.reject("API_REQUEST_FAILED", "API_REQUEST_FAILED"); }
            });
        } catch (NativeFailure failure) { reject(call, failure); }
        catch (RejectedExecutionException ignored) { call.reject("API_CLIENT_UNAVAILABLE", "API_CLIENT_UNAVAILABLE"); }
    }
    @PluginMethod public void deviceAiPrepare(PluginCall call) {
        deviceAi(call, request -> DeviceAiHost.prepareCommand(DeviceAiHost.clientOver(requireHttp()), request));
    }
    @PluginMethod public void deviceAiSubmitStream(PluginCall call) {
        deviceAi(call, request -> DeviceAiHost.submitCommand(DeviceAiHost.clientOver(requireHttp()), request));
    }
    @PluginMethod public void deviceAiLookup(PluginCall call) {
        deviceAi(call, request -> DeviceAiHost.lookupCommand(DeviceAiHost.clientOver(requireHttp()), request));
    }
    @PluginMethod public void deviceAiJournalRead(PluginCall call) {
        deviceAi(call, request -> DeviceAiHost.journalReadCommand(getContext(), request));
    }
    @PluginMethod public void deviceAiJournalAppend(PluginCall call) {
        deviceAi(call, request -> DeviceAiHost.journalAppendCommand(getContext(), request));
    }
    @PluginMethod public void deviceAiResolveUnknown(PluginCall call) {
        deviceAi(call, request -> DeviceAiHost.resolveUnknownCommand(getContext(), requireHttp(), request));
    }
    private static void reject(PluginCall call, NativeFailure error) { call.reject(error.code, error.code); }
    private static String string(JSONObject object, String key) throws NativeFailure {
        Object value = object.opt(key); if (!(value instanceof String)) throw new NativeFailure("INVALID_NATIVE_ARGUMENT"); return (String) value;
    }
    private static void fields(JSONObject object, String... allowed) throws NativeFailure {
        Set<String> names = new HashSet<>(Arrays.asList(allowed)); Iterator<String> keys = object.keys();
        while (keys.hasNext()) if (!names.contains(keys.next())) throw new NativeFailure("INVALID_NATIVE_ARGUMENT");
    }
    private static boolean metadata(byte[] bytes) {
        try { JSONTokener parser = new JSONTokener(NativePolicy.utf8(bytes, "INVALID_API_HEADER")); Object value = parser.nextValue(); return value instanceof JSONObject && parser.nextClean() == 0; }
        catch (Exception ignored) { return false; }
    }
    private void control(PluginCall call, Runnable action, Runnable discarded) {
        try { controls.execute(() -> {
            if (destroyed) { if (discarded != null) discarded.run(); call.reject("API_CLIENT_UNAVAILABLE", "API_CLIENT_UNAVAILABLE"); return; }
            action.run();
        }); }
        catch (RejectedExecutionException ignored) { if (discarded != null) discarded.run(); call.reject("API_CLIENT_UNAVAILABLE", "API_CLIENT_UNAVAILABLE"); }
    }
    @PluginMethod public void status(PluginCall call) {
        try { guard(); fields(call.getData()); }
        catch (NativeFailure error) { reject(call, error); return; }
        control(call, () -> {
            String error = initializationError;
            if (http != null) { try { http.recover(); } catch (NativeFailure failure) { error = failure.code; } if (error == null) error = http.session.error(); }
            JSObject result = new JSObject(); result.put("api_base_url", baseUrl()); result.put("session_persistent", error == null); result.put("session_store", "android_keystore");
            result.put("version", BuildConfig.VERSION_NAME); result.put("platform", "android"); result.put("mode", BuildConfig.DEBUG ? "debug-local" : "release-unconfigured");
            if (error != null) result.put("error", error); call.resolve(result);
        }, null);
    }
    @PluginMethod public void apiRequest(PluginCall call) {
        RequestRegistry.Ticket registered = null;
        try {
            guard(); fields(call.getData(), "request"); NativeHttpBridge bridge = requireHttp();
            JSONObject value = call.getData().optJSONObject("request"); if (value == null) throw new NativeFailure("INVALID_NATIVE_ARGUMENT");
            fields(value, "id", "path", "method", "headers", "body_base64");
            registered = bridge.registry.register(string(value, "id"));
            ownedRequests.add(registered);
            Map<String,String> headers = new LinkedHashMap<>();
            if (value.has("headers")) {
                JSONObject supplied = value.optJSONObject("headers"); if (supplied == null) throw new NativeFailure("INVALID_API_HEADER");
                Iterator<String> keys = supplied.keys(); while (keys.hasNext()) { String key = keys.next(); headers.put(key, string(supplied, key)); }
            }
            String body = value.isNull("body_base64") ? null : string(value, "body_base64");
            NativePolicy.Request request = NativePolicy.request(string(value, "id"), string(value, "path"), string(value, "method"), headers, body, TireNativePlugin::metadata);
            RequestRegistry.Ticket ticket = registered;
            // Do not retain another full copy in PluginCall while the bounded native request runs.
            call.getData().remove("request");
            try { requests.execute(() -> { try { call.resolve(bridge.request(request, ticket)); } catch (NativeFailure error) { reject(call, error); } catch (RuntimeException ignored) { bridge.registry.complete(ticket); call.reject("API_REQUEST_FAILED", "API_REQUEST_FAILED"); } finally { ownedRequests.remove(ticket); Arrays.fill(request.body, (byte) 0); } }); }
            catch (RejectedExecutionException ignored) { Arrays.fill(request.body, (byte) 0); throw new NativeFailure("API_CLIENT_UNAVAILABLE"); }
        } catch (NativeFailure error) { if (registered != null && http != null) { ownedRequests.remove(registered); http.registry.complete(registered); } reject(call, error); }
    }
    @PluginMethod public void apiCancel(PluginCall call) {
        try { guard(); fields(call.getData(), "id"); requireHttp().registry.cancel(string(call.getData(), "id")); call.resolve(); }
        catch (NativeFailure error) { reject(call, error); }
    }
    @PluginMethod public void resetSession(PluginCall call) {
        try {
            guard(); fields(call.getData());
            if (!offlineResetting.compareAndSet(false, true)) throw new NativeFailure("SESSION_RESET_IN_PROGRESS");
            NativeHttpBridge bridge = http;
            // Publish durable owner/policy revocation before cancelling network work.
            // Controls do not queue behind a long manual download or sync request.
            offlineLifecycle.incrementAndGet();
            runtime.documentEnded();
            try { controls.execute(() -> {
                try {
                    requireOffline().resetOwnerEpoch();
                    if (bridge != null) bridge.registry.beginReset();
                    if (bridge != null) bridge.finishReset();
                    runtime.reconcile();
                    call.resolve();
                } catch (NativeFailure failure) {
                    if (bridge != null) bridge.registry.endReset();
                    reject(call, failure);
                } catch (Exception ignored) {
                    if (bridge != null) bridge.registry.endReset();
                    call.reject("OFFLINE_STORAGE_FAILED", "OFFLINE_STORAGE_FAILED");
                } finally { offlineResetting.set(false); }
            }); } catch (RejectedExecutionException ignored) {
                if (bridge != null) bridge.registry.endReset();
                offlineResetting.set(false); throw new NativeFailure("OFFLINE_BUSY");
            }
        }
        catch (NativeFailure error) { reject(call, error); }
    }
    @PluginMethod public void saveDownload(PluginCall call) {
        try {
            guard(); fields(call.getData(), "filename", "mime", "body_base64");
            String name = string(call.getData(), "filename"), mime = NativePolicy.download(name, string(call.getData(), "mime"));
            if (!downloadBusy.compareAndSet(false, true)) throw new NativeFailure("DOWNLOAD_DIALOG_BUSY");
            byte[] bytes;
            try { bytes = NativePolicy.decode(string(call.getData(), "body_base64"), NativePolicy.MAX_RESPONSE_BYTES, "DOWNLOAD_TOO_LARGE"); }
            catch (NativeFailure error) { downloadBusy.set(false); throw error; }
            DownloadJob job = new DownloadJob(mime, bytes, new DownloadJob.Completion() {
                @Override public void result(DownloadJob current, String error) {
                    if (error == null) call.resolve(new JSObject().put("saved", true));
                    else if (error.equals("DOWNLOAD_DIALOG_CANCELLED")) call.resolve(new JSObject().put("saved", false));
                    else call.reject(error, error);
                }
                @Override public void finished(DownloadJob current) { finishDownload(current); }
            });
            synchronized (this) {
                if (destroyed) { job.abort("API_CLIENT_UNAVAILABLE"); downloadBusy.set(false); return; }
                downloadJob = job; downloadCallbackId = call.getCallbackId();
            }
            call.getData().remove("body_base64");
            getActivity().runOnUiThread(() -> {
                if (destroyed) { job.cancel(); return; }
                Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(mime).putExtra(Intent.EXTRA_TITLE, name);
                try { startActivityForResult(call, intent, "downloadSelected"); }
                catch (Exception ignored) { job.abort("DOWNLOAD_DIALOG_FAILED"); }
            });
        } catch (NativeFailure error) { reject(call, error); }
    }
    @ActivityCallback private void downloadSelected(PluginCall call, ActivityResult result) {
        final DownloadJob job;
        synchronized (this) {
            job = downloadJob;
            if (call != null && !call.getCallbackId().equals(downloadCallbackId)) { call.reject("DOWNLOAD_WRITE_FAILED", "DOWNLOAD_WRITE_FAILED"); return; }
        }
        if (job == null) { if (call != null) call.reject("DOWNLOAD_WRITE_FAILED", "DOWNLOAD_WRITE_FAILED"); return; }
        if (destroyed || call == null) { job.cancel(); return; }
        if (result.getResultCode() != Activity.RESULT_OK || result.getData() == null) { job.abort("DOWNLOAD_DIALOG_CANCELLED"); return; }
        Uri uri = result.getData().getData();
        if (uri == null || !"content".equals(uri.getScheme())) { job.abort("DOWNLOAD_WRITE_FAILED"); return; }
        ContentResolver resolver = getContext().getContentResolver(); CancellationSignal signal = new CancellationSignal();
        try { downloads.execute(() -> job.run(new DownloadJob.Destination() {
                @Override public String displayName() {
                    try (Cursor cursor = resolver.query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null, signal)) {
                        return cursor != null && cursor.moveToFirst() ? cursor.getString(0) : null;
                    }
                }
                @Override public OutputStream open() throws Exception {
                    ParcelFileDescriptor descriptor = resolver.openFileDescriptor(uri, "wt", signal);
                    return descriptor == null ? null : new ParcelFileDescriptor.AutoCloseOutputStream(descriptor);
                }
                @Override public void cancel() { signal.cancel(); }
            })); }
        catch (RejectedExecutionException ignored) { job.abort("DOWNLOAD_WRITE_FAILED"); }
    }
    private synchronized void finishDownload(DownloadJob job) {
        if (downloadJob == job) { downloadJob = null; downloadCallbackId = null; downloadBusy.set(false); }
    }
    @PluginMethod public void openExternal(PluginCall call) {
        try { guard(); fields(call.getData(), "url"); Uri uri = Uri.parse(NativePolicy.externalUrl(string(call.getData(), "url")).toASCIIString());
            getActivity().runOnUiThread(() -> { try { getActivity().startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)); call.resolve(); } catch (Exception ignored) { call.reject("EXTERNAL_OPEN_FAILED", "EXTERNAL_OPEN_FAILED"); } });
        } catch (NativeFailure error) { reject(call, error); }
    }
    public synchronized void requestBack() {
        pendingBack = UUID.randomUUID().toString(); backDeadline = SystemClock.elapsedRealtime() + 3000;
        notifyListeners("backRequested", new JSObject().put("id", pendingBack));
    }
    @PluginMethod public void resolveBack(PluginCall call) {
        try {
            guard(); fields(call.getData(), "id", "handled"); String id = string(call.getData(), "id");
            Object handled = call.getData().opt("handled"); if (!(handled instanceof Boolean)) throw new NativeFailure("INVALID_NATIVE_ARGUMENT");
            synchronized (this) { if (!id.equals(pendingBack) || SystemClock.elapsedRealtime() > backDeadline) throw new NativeFailure("BACK_REQUEST_EXPIRED"); pendingBack = null; }
            if (!(Boolean) handled) getActivity().runOnUiThread(() -> getActivity().moveTaskToBack(true)); call.resolve();
        } catch (NativeFailure error) { reject(call, error); }
    }
    @PluginMethod public void setSystemTheme(PluginCall call) {
        try { guard(); fields(call.getData(), "theme"); String theme = string(call.getData(), "theme"); if (!theme.equals("light") && !theme.equals("dark")) throw new NativeFailure("INVALID_THEME");
            getActivity().runOnUiThread(() -> { ((MainActivity) getActivity()).setSystemTheme(theme.equals("dark")); call.resolve(); });
        } catch (NativeFailure error) { reject(call, error); }
    }
    // Initial launch has no listeners yet; every actual return to the foreground must notify.
    @Override protected void handleOnResume() { notifyListeners("resume", new JSObject()); }
    @Override protected synchronized void handleOnPause() { pendingBack = null; }
    @Override protected void handleOnDestroy() {
        destroyed = true;
        offlineLifecycle.incrementAndGet();
        if (runtime != null) runtime.documentEnded();
        DownloadJob job; synchronized (this) { job = downloadJob; }
        if (job != null) job.cancel();
        downloads.shutdownNow();
        for (RequestRegistry.Ticket ticket : ownedRequests) {
            ticket.cancel();
            if (http != null) http.registry.complete(ticket);
        }
        ownedRequests.clear(); requests.shutdownNow();
        // Already queued controls settle promptly without running their action after teardown.
        controls.shutdown();
        // Queued document calls settle through guard. Application-owned Store/HTTP
        // and scheduler executors remain available after this Activity disappears.
    }
}
