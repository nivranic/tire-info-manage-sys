mod bridge;
pub mod device_ai_exact;
pub mod device_ai_host;
mod offline;
mod security;
mod session;

use bridge::Bridge;
use security::{
    allowed_navigation, decode_bounded, download_extension, external_url, ApiRequest, ApiResponse,
    LaunchConfig, NativeResult, MAX_RESPONSE_BYTES,
};
use serde::Serialize;
use session::OsSessionStore;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use tauri::{Manager, State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
use tokio::sync::Semaphore;

struct NativeState {
    bridge: NativeResult<Arc<Bridge>>,
    offline: NativeResult<Arc<offline::Store>>,
    sync: NativeResult<Arc<offline::sync::Coordinator>>,
    offline_gate: tokio::sync::Mutex<()>,
    offline_cancel: Mutex<Option<tokio_util::sync::CancellationToken>>,
    offline_resetting: AtomicBool,
    api_base_url: String,
    download: Semaphore,
}

impl NativeState {
    fn from_environment(app_data: NativeResult<std::path::PathBuf>) -> Self {
        let config = LaunchConfig::from_env();
        let api_base_url = config
            .as_ref()
            .map(LaunchConfig::base_url)
            .unwrap_or_default();
        // Offline access is independent of session-key recovery and /health.
        let offline = config.as_ref().map_err(|error| *error).and_then(|config| {
            app_data
                .and_then(|path| offline::Store::open(&path, config))
                .map(Arc::new)
        });
        let bridge = config.and_then(|config| {
            let store = OsSessionStore::open(&config)?;
            Bridge::new(config, store).map(Arc::new)
        });
        if let (Ok(bridge), Ok(store)) = (&bridge, &offline) {
            let _ = bridge.bind_fallback_store(store);
        }
        let sync = offline.as_ref().map_err(|e| *e).and_then(|store| {
            bridge
                .as_ref()
                .map(|bridge| {
                    Arc::new(offline::sync::Coordinator::new(
                        store.clone(),
                        bridge.clone(),
                    ))
                })
                .map_err(|e| *e)
        });
        Self {
            bridge,
            offline,
            sync,
            offline_gate: tokio::sync::Mutex::new(()),
            offline_cancel: Mutex::new(None),
            offline_resetting: AtomicBool::new(false),
            api_base_url,
            download: Semaphore::new(1),
        }
    }

    fn bridge(&self) -> NativeResult<&Bridge> {
        self.bridge
            .as_ref()
            .map(Arc::as_ref)
            .map_err(|error| *error)
    }
    fn offline(&self) -> NativeResult<Arc<offline::Store>> {
        self.offline.as_ref().cloned().map_err(|error| *error)
    }
}

#[derive(Serialize)]
struct DesktopStatus {
    api_base_url: String,
    session_persistent: bool,
    session_store: &'static str,
    version: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<&'static str>,
}

fn require_main(window: &WebviewWindow) -> NativeResult<()> {
    if window.label() != "main"
        || !window
            .url()
            .is_ok_and(|url| allowed_navigation(&url, cfg!(debug_assertions)))
    {
        return Err("IPC_WINDOW_DENIED");
    }
    Ok(())
}

#[tauri::command(rename_all = "snake_case")]
async fn desktop_status(
    window: WebviewWindow,
    state: State<'_, NativeState>,
) -> NativeResult<DesktopStatus> {
    require_main(&window)?;
    let error = match state.bridge() {
        Ok(bridge) => bridge
            .recover_session()
            .await
            .err()
            .or_else(|| bridge.session.error()),
        Err(error) => Some(error),
    };
    Ok(DesktopStatus {
        api_base_url: state.api_base_url.clone(),
        session_persistent: error.is_none(),
        session_store: "os_secure_store",
        version: env!("CARGO_PKG_VERSION"),
        error,
    })
}

#[tauri::command(rename_all = "snake_case")]
async fn api_request(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: ApiRequest,
) -> NativeResult<ApiResponse> {
    require_main(&window)?;
    state.bridge()?.request(request).await
}

#[tauri::command(rename_all = "snake_case")]
fn api_cancel(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    id: String,
) -> NativeResult<()> {
    require_main(&window)?;
    state.bridge()?.cancel(&id)
}

#[tauri::command(rename_all = "snake_case")]
async fn reset_session(window: WebviewWindow, state: State<'_, NativeState>) -> NativeResult<()> {
    require_main(&window)?;
    if state.offline_resetting.swap(true, Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    struct ResetFlag<'a>(&'a AtomicBool);
    impl Drop for ResetFlag<'_> {
        fn drop(&mut self) {
            self.0.store(false, Ordering::SeqCst);
        }
    }
    let _reset = ResetFlag(&state.offline_resetting);
    if let Some(token) = state
        .offline_cancel
        .lock()
        .map_err(|_| "OFFLINE_STORE_FAILED")?
        .as_ref()
    {
        token.cancel();
    }
    let _gate = state.offline_gate.lock().await;
    let store = state.offline()?;
    // A failed durable epoch update leaves the original session intact.
    blocking(move || store.reset_owner()).await?;
    if let Ok(sync) = &state.sync {
        sync.cancel(None);
    }
    state.bridge()?.reset_session().await
}

async fn blocking<T: Send + 'static>(
    operation: impl FnOnce() -> NativeResult<T> + Send + 'static,
) -> NativeResult<T> {
    tokio::task::spawn_blocking(operation)
        .await
        .map_err(|_| "OFFLINE_STORE_FAILED")?
}

#[tauri::command(rename_all = "snake_case")]
async fn offline_status(
    window: WebviewWindow,
    state: State<'_, NativeState>,
) -> NativeResult<offline::Status> {
    require_main(&window)?;
    match state.offline() {
        Ok(store) => blocking(move || Ok(store.status())).await,
        Err(error) => Ok(offline::Status::unavailable(error)),
    }
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_list(
    window: WebviewWindow,
    state: State<'_, NativeState>,
) -> NativeResult<offline::List> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.list()).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_sync_status(
    window: WebviewWindow,
    state: State<'_, NativeState>,
) -> NativeResult<offline::SyncStatus> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.sync_status()).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_sync_preview(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::SyncPreviewRequest,
) -> NativeResult<offline::SyncPreview> {
    require_main(&window)?;
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    let store = state.offline()?;
    blocking(move || store.sync_preview(request)).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_sync_apply(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::SyncApplyRequest,
) -> NativeResult<offline::SyncPolicy> {
    require_main(&window)?;
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    let store = state.offline()?;
    let policy = blocking(move || store.sync_apply(request)).await?;
    if let Ok(sync) = &state.sync {
        sync.cancel(Some(&policy.policy_id));
    }
    Ok(policy)
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_sync_pause(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::SyncPolicyRequest,
) -> NativeResult<offline::SyncPolicy> {
    require_main(&window)?;
    let store = state.offline()?;
    let policy = blocking(move || store.sync_change_policy(request, false)).await?;
    if let Ok(sync) = &state.sync {
        sync.cancel(Some(&policy.policy_id));
    }
    Ok(policy)
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_sync_revoke(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::SyncPolicyRequest,
) -> NativeResult<offline::SyncPolicy> {
    require_main(&window)?;
    let store = state.offline()?;
    let policy = blocking(move || store.sync_change_policy(request, true)).await?;
    if let Ok(sync) = &state.sync {
        sync.cancel(Some(&policy.policy_id));
    }
    Ok(policy)
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_sync_run(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::SyncRunRequest,
) -> NativeResult<offline::SyncRun> {
    require_main(&window)?;
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    state.sync.as_ref().map_err(|e| *e)?.run(request).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_sync_revalidate(
    window: WebviewWindow,
    state: State<'_, NativeState>,
) -> NativeResult<offline::SyncStatus> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.sync_revalidate()).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_install(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::wire::InstallRequest,
) -> NativeResult<offline::Slot> {
    require_main(&window)?;
    request.validate()?;
    let _gate = state
        .offline_gate
        .try_lock()
        .map_err(|_| "OFFLINE_INSTALL_BUSY")?;
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    let cancellation = tokio_util::sync::CancellationToken::new();
    *state
        .offline_cancel
        .lock()
        .map_err(|_| "OFFLINE_STORE_FAILED")? = Some(cancellation.clone());
    // Recheck after publishing the cancellation handle to close the reset race.
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    let store = state.offline()?;
    let stage_store = store.clone();
    let stage_request = request.clone();
    let ticket = blocking(move || stage_store.begin_install(&stage_request)).await?;
    let (descriptor, bytes) = tokio::select! {
        biased;
        _=cancellation.cancelled()=>return Err("REQUEST_CANCELLED"),
        value=state.bridge()?.owned_pack(&request)=>value?,
    };
    if cancellation.is_cancelled() {
        return Err("REQUEST_CANCELLED");
    }
    blocking(move || store.install(&request, descriptor, bytes, ticket)).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_search(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::SearchRequest,
) -> NativeResult<offline::SearchResult> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.search(request)).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_read(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::ReadRequest,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.read_wire(request)).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_remove(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::SlotRequest,
) -> NativeResult<offline::RemoveResult> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.remove(request)).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_unlock_previous_owner(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::UnlockRequest,
) -> NativeResult<offline::Slot> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.unlock(request)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_decide(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: serde_json::Value,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    if request["intent"]["schema"] == "device-fallback-intent@2" {
        if request["intent"]["fallback_policy"] == "never" {
            let store = state.offline()?;
            let page = store.fallback_page_id();
            return blocking(move || store.decide_fallback_v2(request, page)).await;
        }
        return fallback_authority_action(&state, move |store, page| {
            store.decide_fallback_v2(request, page)
        })
        .await;
    }
    let request: offline::FallbackDecideRequest =
        serde_json::from_value(request).map_err(|_| "OFFLINE_FALLBACK_INVALID")?;
    if request.intent.failure.scope == "source_response" {
        return fallback_legacy_session_action(&state, move |store, page| {
            serde_json::to_value(store.decide_fallback(request, page)?)
                .map_err(|_| "OFFLINE_FALLBACK_INVALID")
        })
        .await;
    }
    let store = state.offline()?;
    let page = store.fallback_page_id();
    blocking(move || {
        serde_json::to_value(store.decide_fallback(request, page)?)
            .map_err(|_| "OFFLINE_FALLBACK_INVALID")
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_consume(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: serde_json::Value,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    if request["intent"]["schema"] == "device-fallback-intent@2" {
        return fallback_authority_action(&state, move |store, page| {
            store.consume_fallback_v2(request, page)
        })
        .await;
    }
    let request: offline::FallbackConsumeRequest =
        serde_json::from_value(request).map_err(|_| "OFFLINE_FALLBACK_INVALID")?;
    if request.intent.failure.scope == "source_response" {
        return fallback_legacy_session_action(&state, move |store, page| {
            serde_json::to_value(store.consume_fallback(request, page)?)
                .map_err(|_| "OFFLINE_FALLBACK_INVALID")
        })
        .await;
    }
    let store = state.offline()?;
    let page = store.fallback_page_id();
    blocking(move || {
        serde_json::to_value(store.consume_fallback(request, page)?)
            .map_err(|_| "OFFLINE_FALLBACK_INVALID")
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_revoke(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: offline::FallbackRevokeRequest,
) -> NativeResult<offline::FallbackRevokeResult> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || {
        if store.revoke_fallback_v2_if_known(&request)? {
            return Ok(offline::FallbackRevokeResult {
                revoked: true,
                grant_id: request.grant_id,
            });
        }
        store.revoke_fallback(request)
    })
    .await
}

async fn fallback_authority_action(
    state: &NativeState,
    action: impl FnOnce(Arc<offline::Store>, u64) -> NativeResult<serde_json::Value> + Send + 'static,
) -> NativeResult<serde_json::Value> {
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    let store = state.offline()?;
    let fence = store.fallback_authority_fence()?;
    let bridge = state.bridge.as_ref().cloned().map_err(|e| *e)?;
    let page = store.fallback_page_id();
    let authority_store = store.clone();
    let result = bridge
        .sync_publish(fence, move || action(store, page))
        .await;
    if matches!(
        result,
        Err("SESSION_CHANGED" | "SESSION_RESET_IN_PROGRESS" | "SESSION_KEY_UNAVAILABLE")
    ) {
        let _ = blocking(move || authority_store.fallback_authority_unknown()).await;
    }
    result
}
async fn fallback_legacy_session_action(
    state: &NativeState,
    action: impl FnOnce(Arc<offline::Store>, u64) -> NativeResult<serde_json::Value> + Send + 'static,
) -> NativeResult<serde_json::Value> {
    let store = state.offline()?;
    let page = store.fallback_page_id();
    let bridge = state.bridge.as_ref().cloned().map_err(|e| *e)?;
    let fence = Arc::new(bridge.sync_fence().await?);
    let bind = fence.clone();
    bridge
        .sync_publish(fence, move || {
            store.fallback_bind_denial_session(bind)?;
            action(store, page)
        })
        .await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_status(
    window: WebviewWindow,
    state: State<'_, NativeState>,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let store = state.offline()?;
    if let Ok(fence) = store.fallback_authority_fence() {
        if state.bridge()?.check_sync_fence(&fence).await.is_err() {
            let invalid = store.clone();
            blocking(move || invalid.fallback_authority_unknown()).await?;
        }
    }
    blocking(move || store.fallback_status_v2()).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_authority_refresh(
    window: WebviewWindow,
    state: State<'_, NativeState>,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    if state.offline_resetting.load(Ordering::SeqCst) {
        return Err("SESSION_RESET_IN_PROGRESS");
    }
    let store = state.offline()?;
    let capture_store = store.clone();
    let captured = blocking(move || capture_store.fallback_authority_capture()).await?;
    let bridge = state.bridge.as_ref().cloned().map_err(|e| *e)?;
    let fence = Arc::new(bridge.sync_fence().await?);
    let metadata = bridge.fallback_authority_metadata(&fence).await;
    let (owner, settings, directory) = match metadata {
        Ok(value) => value,
        Err(error) => {
            if matches!(error, "SESSION_CHANGED" | "SESSION_RESET_IN_PROGRESS") {
                let invalid = store.clone();
                let _ = blocking(move || invalid.fallback_authority_unknown()).await;
            }
            return Err(error);
        }
    };
    let publish_fence = fence.clone();
    bridge
        .sync_publish(fence, move || {
            store.fallback_authority_commit(captured, owner, settings, directory, publish_fence)
        })
        .await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_policy_preview(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: serde_json::Value,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    fallback_authority_action(&state, move |store, page| {
        store.fallback_policy_preview_v2(request, page)
    })
    .await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_policy_apply(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: serde_json::Value,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    fallback_authority_action(&state, move |store, page| {
        store.fallback_policy_apply_v2(request, page)
    })
    .await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_policy_pause(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: serde_json::Value,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.fallback_policy_change_v2(request, false)).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_policy_revoke(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: serde_json::Value,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let store = state.offline()?;
    blocking(move || store.fallback_policy_change_v2(request, true)).await
}
#[tauri::command(rename_all = "snake_case")]
async fn offline_fallback_authorize(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    request: serde_json::Value,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    if request["intent"]["fallback_policy"] == "never" {
        let store = state.offline()?;
        let page = store.fallback_page_id();
        return blocking(move || store.authorize_fallback_v2(request, page)).await;
    }
    fallback_authority_action(&state, move |store, page| {
        store.authorize_fallback_v2(request, page)
    })
    .await
}

// ---------------------------------------------------------------------------
// device-ai host commands (round 50 P1-3 host wiring). Thin wrappers over
// device_ai_host; permissions follow the existing IPC conventions
// (require_main window gate, closed static error codes). Server HTTP
// rejections are NOT IPC errors: they pass through as a `rejected` envelope
// (status + closed detail code), mirroring the TS ApiError passthrough the
// orchestration layer consumes (404 drives N18, 409 drives conflict UX).
// The envelope wire is an unfrozen draft (roundtable D15).
// ---------------------------------------------------------------------------

#[derive(Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
enum DeviceAiHttpOutcome {
    Accepted {
        http_status: u16,
        value: serde_json::Value,
    },
    Rejected {
        http_status: u16,
        code: Option<String>,
        message: Option<String>,
        run_id: Option<String>,
    },
}

fn device_ai_outcome(
    result: Result<
        device_ai_host::DeviceAiEndpointSuccess,
        device_ai_host::DeviceAiClientError,
    >,
) -> NativeResult<serde_json::Value> {
    match result {
        Ok(success) => serde_json::to_value(DeviceAiHttpOutcome::Accepted {
            http_status: success.status,
            value: success.value,
        })
        .map_err(|_| "DEVICE_AI_RESPONSE_INVALID"),
        Err(device_ai_host::DeviceAiClientError::Api(error)) => {
            serde_json::to_value(DeviceAiHttpOutcome::Rejected {
                http_status: error.status,
                code: error.code,
                message: error.message,
                run_id: error.run_id,
            })
            .map_err(|_| "DEVICE_AI_RESPONSE_INVALID")
        }
        Err(other) => Err(other
            .into_ipc_error()
            .unwrap_or("DEVICE_AI_RESPONSE_INVALID")),
    }
}

fn device_ai_bridge(state: &State<'_, NativeState>) -> NativeResult<Arc<Bridge>> {
    state
        .bridge
        .as_ref()
        .map(Arc::clone)
        .map_err(|error| *error)
}

#[tauri::command(rename_all = "snake_case")]
async fn device_ai_prepare(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    body: device_ai_host::DeviceAiPrepareBody,
    key: String,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let client = device_ai_host::DeviceAiHostClient::new(device_ai_bridge(&state)?);
    device_ai_outcome(client.prepare(&body, &key).await)
}

#[tauri::command(rename_all = "snake_case")]
async fn device_ai_submit_stream(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    body: device_ai_host::DeviceAiStreamSubmission,
    key: String,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let client = device_ai_host::DeviceAiHostClient::new(device_ai_bridge(&state)?);
    device_ai_outcome(client.submit_stream(&body, &key).await)
}

#[tauri::command(rename_all = "snake_case")]
async fn device_ai_lookup_attempt(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    key: String,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let client = device_ai_host::DeviceAiHostClient::new(device_ai_bridge(&state)?);
    device_ai_outcome(client.lookup_attempt(&key).await)
}

#[tauri::command(rename_all = "snake_case")]
async fn device_ai_read_journal(
    window: WebviewWindow,
    app: tauri::AppHandle,
    state: State<'_, NativeState>,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let bridge = device_ai_bridge(&state)?;
    let (app_data, account, session_id) = device_ai_journal_identity(&bridge, &app).await?;
    let owner = account.clone();
    blocking(move || {
        let journal = device_ai_host::open_native_journal(
            &app_data,
            &account,
            &owner,
            1,
            &session_id,
        )?;
        let journal_error = journal_error_code;
        let verification = journal
            .verify_integrity()
            .map_err(journal_error)?;
        let entries = journal.read_all().map_err(journal_error)?;
        Ok(serde_json::json!({
            "schema": device_ai_host::DEVICE_AI_JOURNAL_SCHEMA,
            "owner": owner,
            "generation": 1,
            "session_id": session_id,
            "length": entries.len(),
            "entries": entries,
            "verification": verification,
        }))
    })
    .await
}

/// Shared journal-open inputs for the three journal-touching commands: the
/// per-installation store account (owner), app-data directory, and the fence-5
/// session snapshot (cookie + generation at call time).
async fn device_ai_journal_identity(
    bridge: &Bridge,
    app: &tauri::AppHandle,
) -> NativeResult<(std::path::PathBuf, String, String)> {
    let account = bridge.config.store_account();
    let session_id = {
        let data = bridge.session.data.lock().await;
        match &data.cookie {
            Some(cookie) => format!("{cookie}#{}", data.generation),
            None => format!("anonymous#{}", data.generation),
        }
    };
    let app_data = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "OFFLINE_STORE_FAILED")?;
    Ok((app_data, account, session_id))
}

/// Journal failures map onto the same closed IPC codes as read_journal:
/// store/OS failures through their native code, fence violations through the
/// device_ai_host_* closed set.
fn journal_error_code(error: device_ai_host::DeviceAiJournalError) -> &'static str {
    match error {
        device_ai_host::DeviceAiJournalError::Store(code) => code,
        device_ai_host::DeviceAiJournalError::Fence(code) => code.as_str(),
    }
}

/// Append one journal event from the WebView orchestration. The event wire is
/// closed (serde tag + deny_unknown_fields) and value-validated
/// (assert_device_ai_journal_event) before anything is sealed; the journal is
/// opened through the same keyring/app-data conventions as read_journal, so
/// entries land in the same ledger, under the same five fences.
#[tauri::command(rename_all = "snake_case")]
async fn device_ai_journal_append(
    window: WebviewWindow,
    app: tauri::AppHandle,
    state: State<'_, NativeState>,
    event: device_ai_host::DeviceAiJournalEvent,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    device_ai_host::assert_device_ai_journal_event(&event).map_err(|code| code.as_str())?;
    let bridge = device_ai_bridge(&state)?;
    let (app_data, account, session_id) = device_ai_journal_identity(&bridge, &app).await?;
    let owner = account.clone();
    blocking(move || {
        let journal = device_ai_host::open_native_journal(
            &app_data,
            &account,
            &owner,
            1,
            &session_id,
        )?;
        let entry = journal.append(event).map_err(journal_error_code)?;
        serde_json::to_value(entry).map_err(|_| "DEVICE_AI_RESPONSE_INVALID")
    })
    .await
}

/// N18 unknown-outcome resolution over IPC: lookup-first with the SAME
/// idempotency key, never a resubmission. Returns the resolution through the
/// same accepted/rejected envelope convention as the HTTP commands (the
/// resolution value is `{kind, ...}` matching the TS
/// DeviceAiUnknownOutcomeResolution union); server rejections pass through as
/// `rejected` so the frontend maps them to ApiError like every other route.
#[tauri::command(rename_all = "snake_case")]
async fn device_ai_resolve_unknown(
    window: WebviewWindow,
    app: tauri::AppHandle,
    state: State<'_, NativeState>,
    analysis_key: String,
    intent_id: Option<String>,
) -> NativeResult<serde_json::Value> {
    require_main(&window)?;
    let bridge = device_ai_bridge(&state)?;
    let (app_data, account, session_id) = device_ai_journal_identity(&bridge, &app).await?;
    let owner = account.clone();
    let journal = blocking(move || {
        device_ai_host::open_native_journal(&app_data, &account, &owner, 1, &session_id)
    })
    .await?;
    let client = device_ai_host::DeviceAiHostClient::new(bridge);
    match device_ai_host::resolve_unknown_outcome(
        &client,
        Some(&journal),
        &analysis_key,
        intent_id.as_deref(),
    )
    .await
    {
        Ok(resolution) => {
            let value = serde_json::to_value(resolution)
                .map_err(|_| "DEVICE_AI_RESPONSE_INVALID")?;
            serde_json::to_value(DeviceAiHttpOutcome::Accepted {
                http_status: 200,
                value,
            })
            .map_err(|_| "DEVICE_AI_RESPONSE_INVALID")
        }
        Err(error) => device_ai_outcome(Err(error)),
    }
}

#[derive(Serialize)]
struct SaveResult {
    saved: bool,
}

#[tauri::command(rename_all = "snake_case")]
async fn save_download(
    window: WebviewWindow,
    state: State<'_, NativeState>,
    filename: String,
    mime: String,
    body_base64: String,
) -> NativeResult<SaveResult> {
    require_main(&window)?;
    let _permit = state
        .download
        .try_acquire()
        .map_err(|_| "DOWNLOAD_DIALOG_BUSY")?;
    let extension = download_extension(&filename, &mime)?;
    let body = decode_bounded(&body_base64, MAX_RESPONSE_BYTES, "DOWNLOAD_TOO_LARGE")?;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    window
        .dialog()
        .file()
        .set_parent(&window)
        .set_title("保存胎迹导出文件")
        .set_file_name(&filename)
        .add_filter("导出文件", &[extension])
        .save_file(move |path| {
            let _ = sender.send(path);
        });
    let Some(path) = receiver.await.map_err(|_| "DOWNLOAD_DIALOG_FAILED")? else {
        return Ok(SaveResult { saved: false });
    };
    let path = path.into_path().map_err(|_| "DOWNLOAD_WRITE_FAILED")?;
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
        != Some(extension)
    {
        return Err("INVALID_DOWNLOAD_TYPE");
    }
    // Only this user-selected native path is accepted. No path is supplied by IPC.
    tokio::fs::write(path, body)
        .await
        .map_err(|_| "DOWNLOAD_WRITE_FAILED")?;
    Ok(SaveResult { saved: true })
}

#[tauri::command(rename_all = "snake_case")]
fn open_external(window: WebviewWindow, url: String) -> NativeResult<()> {
    require_main(&window)?;
    let url = external_url(&url)?;
    window
        .opener()
        .open_url(url.as_str(), None::<&str>)
        .map_err(|_| "EXTERNAL_OPEN_FAILED")
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Plugin APIs are used only from Rust; no dialog/opener permissions are granted to JS.
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            desktop_status,
            api_request,
            api_cancel,
            reset_session,
            save_download,
            open_external,
            offline_status,
            offline_list,
            offline_install,
            offline_search,
            offline_read,
            offline_remove,
            offline_unlock_previous_owner,
            offline_fallback_decide,
            offline_fallback_consume,
            offline_fallback_revoke,
            offline_fallback_status,
            offline_fallback_authority_refresh,
            offline_fallback_policy_preview,
            offline_fallback_policy_apply,
            offline_fallback_policy_pause,
            offline_fallback_policy_revoke,
            offline_fallback_authorize,
            offline_sync_status,
            offline_sync_preview,
            offline_sync_apply,
            offline_sync_pause,
            offline_sync_revoke,
            offline_sync_run,
            offline_sync_revalidate,
            device_ai_prepare,
            device_ai_submit_stream,
            device_ai_lookup_attempt,
            device_ai_read_journal,
            device_ai_journal_append,
            device_ai_resolve_unknown
        ])
        .setup(|app| {
            app.manage(NativeState::from_environment(
                app.path()
                    .app_local_data_dir()
                    .map_err(|_| "OFFLINE_STORE_FAILED"),
            ));
            if let Ok(sync) = &app.state::<NativeState>().sync {
                sync.start();
            }
            let hidden = std::env::var("TI_DESKTOP_HEADLESS").as_deref() == Ok("1")
                || (cfg!(debug_assertions)
                    && std::env::var("TI_DESKTOP_QA_HIDDEN").as_deref() == Ok("1"));
            // QA may explicitly supply WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS in the
            // launch environment. The application never enables a debugging port itself.
            tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("胎迹 · 轮胎证据工作台")
            .inner_size(1200.0, 820.0)
            .min_inner_size(900.0, 640.0)
            .visible(!hidden)
            .on_navigation(|url| allowed_navigation(url, cfg!(debug_assertions)))
            .on_page_load(|window, payload| {
                if payload.event() == tauri::webview::PageLoadEvent::Started {
                    if let Some(state) = window.try_state::<NativeState>() {
                        if let Ok(store) = state.offline() {
                            store.invalidate_fallback_page();
                        }
                    }
                }
            })
            .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
            .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("desktop application startup failed");
}

#[cfg(test)]
mod security_tests;
