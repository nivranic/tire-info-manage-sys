//! Host-owned coordinator. No JavaScript timers, arbitrary URLs or source queries.
use super::{conditions, wire, Store, SyncRun, SyncRunRequest, SyncTicket};
use crate::{
    bridge::{Bridge, SessionFence, SyncEndpoint},
    security::NativeResult,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};
use tokio_util::sync::CancellationToken;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Update {
    schema: String,
    state: String,
    mode: String,
    base_pack_id: String,
    base_semantic_digest: String,
    current_semantic_digest: String,
    base_pack: wire::Descriptor,
    plan: Option<Value>,
    source_refresh_performed: bool,
}

pub struct Coordinator {
    pub store: Arc<Store>,
    bridge: Arc<Bridge>,
    active: Mutex<Option<(String, CancellationToken)>>,
}
async fn blocking<T: Send + 'static>(
    f: impl FnOnce() -> NativeResult<T> + Send + 'static,
) -> NativeResult<T> {
    tokio::task::spawn_blocking(f)
        .await
        .map_err(|_| "OFFLINE_SYNC_WORKER_FAILED")?
}
fn encoded(value: &impl Serialize) -> NativeResult<Vec<u8>> {
    serde_json::to_vec(value).map_err(|_| "OFFLINE_SYNC_RESPONSE_INVALID")
}
fn same(a: &impl Serialize, b: &impl Serialize) -> bool {
    encoded(a).ok() == encoded(b).ok()
}

pub fn semantic_digest(bytes: &[u8]) -> NativeResult<String> {
    // Original producer fragments retain exact Python float spellings, nested
    // timestamps and array order. Do not reformat numeric values through f64.
    let mut fields: BTreeMap<String, Box<serde_json::value::RawValue>> =
        serde_json::from_slice(bytes).map_err(|_| "OFFLINE_PACK_INVALID")?;
    for nonce in [
        "package_id",
        "created_at",
        "plan_fingerprint",
        "base_pack_id",
    ] {
        fields.remove(nonce);
    }
    #[derive(Serialize)]
    struct Projection {
        envelope: BTreeMap<String, Box<serde_json::value::RawValue>>,
        namespace: &'static str,
    }
    Ok(super::crypto::hash(&encoded(&Projection {
        envelope: fields,
        namespace: "offline-semantic@1",
    })?))
}

impl Coordinator {
    pub fn new(store: Arc<Store>, bridge: Arc<Bridge>) -> Self {
        Self {
            store,
            bridge,
            active: Mutex::new(None),
        }
    }
    pub fn cancel(&self, policy: Option<&str>) {
        if let Ok(active) = self.active.lock() {
            if let Some((id, token)) = &*active {
                if policy.is_none() || policy == Some(id.as_str()) {
                    token.cancel();
                }
            }
        }
    }
    pub fn start(self: &Arc<Self>) {
        let coordinator = self.clone();
        tauri::async_runtime::spawn(async move {
            let mut timer = tokio::time::interval(std::time::Duration::from_secs(30));
            timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
            loop {
                timer.tick().await;
                let store = coordinator.store.clone();
                let Ok(status) = blocking(move || store.sync_status()).await else {
                    continue;
                };
                if status.capabilities.scheduler != "native_app_open" {
                    continue;
                }
                for policy in status.policies.into_iter().filter(|p| p.state == "enabled") {
                    let due = policy
                        .next_due_at
                        .as_deref()
                        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
                        .is_some_and(|t| t <= chrono::Utc::now());
                    if due {
                        let _ = coordinator
                            .run(SyncRunRequest {
                                policy_id: policy.policy_id,
                                expected_policy_revision: policy.policy_revision,
                                trigger: "timer".into(),
                            })
                            .await;
                    }
                }
            }
        });
    }
    pub async fn run(&self, request: SyncRunRequest) -> NativeResult<SyncRun> {
        let store = self.store.clone();
        let requested_policy = request.policy_id.clone();
        let begun = blocking(move || store.sync_begin(request, conditions::sample())).await;
        let ticket = match begun {
            Ok(ticket) => Arc::new(ticket),
            Err("OFFLINE_SYNC_DEFERRED") => return self.latest_run(&requested_policy, None).await,
            Err(error) => return Err(error),
        };
        let token = CancellationToken::new();
        {
            let mut active = self.active.lock().map_err(|_| "OFFLINE_SYNC_BUSY")?;
            if active.is_some() {
                return Err("OFFLINE_SYNC_BUSY");
            }
            *active = Some((ticket.policy.policy_id.clone(), token.clone()));
        }
        let result = tokio::select! { biased; _ = token.cancelled() => Err("REQUEST_CANCELLED"), result = self.perform(ticket.clone(), token.clone()) => result };
        if let Ok(mut active) = self.active.lock() {
            *active = None;
        }
        match result {
            Ok(run) => Ok(run),
            Err(error) => {
                let previous = self
                    .latest_run(&ticket.policy.policy_id, Some(&ticket.run_id))
                    .await?;
                if previous.state != "running" {
                    return Ok(previous);
                }
                let uncertain = matches!(previous.stage.as_str(), "preparing" | "confirming")
                    || matches!(
                        error,
                        "SESSION_CHANGED"
                            | "OFFLINE_SYNC_SESSION_REQUIRED"
                            | "OFFLINE_SYNC_RESPONSE_INVALID"
                    );
                let state = if uncertain {
                    "interrupted"
                } else if error == "REQUEST_CANCELLED" {
                    "cancelled"
                } else if error == "OFFLINE_SYNC_CONDITIONS_UNMET" {
                    "deferred"
                } else {
                    "failed"
                };
                let store = self.store.clone();
                let captured = ticket.clone();
                match blocking(move || {
                    store.sync_finish(&captured, state, Some(error), conditions::sample())
                })
                .await
                {
                    Ok(run) => Ok(run),
                    Err(_) => {
                        self.latest_run(&ticket.policy.policy_id, Some(&ticket.run_id))
                            .await
                    }
                }
            }
        }
    }
    async fn latest_run(&self, policy: &str, run_id: Option<&str>) -> NativeResult<SyncRun> {
        let store = self.store.clone();
        let policy = policy.to_owned();
        let run_id = run_id.map(str::to_owned);
        blocking(move || {
            store
                .sync_status()?
                .runs
                .into_iter()
                .rev()
                .find(|r| {
                    r.policy_id == policy && run_id.as_deref().is_none_or(|id| id == r.run_id)
                })
                .ok_or("OFFLINE_SYNC_RUN_NOT_FOUND")
        })
        .await
    }
    async fn stage(
        &self,
        ticket: Arc<SyncTicket>,
        stage: &'static str,
        plan: Option<(String, String, String)>,
        package: Option<String>,
    ) -> NativeResult<()> {
        let store = self.store.clone();
        blocking(move || {
            store.sync_stage(
                &ticket,
                stage,
                plan.as_ref()
                    .map(|(a, b, c)| (a.as_str(), b.as_str(), c.as_str())),
                package.as_deref(),
            )
        })
        .await
    }
    async fn perform(
        &self,
        ticket: Arc<SyncTicket>,
        token: CancellationToken,
    ) -> NativeResult<SyncRun> {
        let fence = Arc::new(self.bridge.sync_fence().await?);
        let version = wire::PackVersion::from_descriptor(&ticket.descriptor.schema)?;
        self.stage(ticket.clone(), "preparing", None, None).await?;
        let body = encoded(
            &json!({"mode":"history", "base_pack_id":ticket.descriptor.id,
            "expected_base_sha256":ticket.descriptor.sha256, "scope":ticket.policy.scope,
            "supported_pack_schemas":[version.pack_schema()]}),
        )?;
        let raw = self
            .bridge
            .sync_request(
                &fence,
                &ticket.policy.owner_scope_id,
                SyncEndpoint::Prepare,
                body,
                None,
            )
            .await?;
        let result: Update = serde_json::from_value(wire::strict_json(&raw)?)
            .map_err(|_| "OFFLINE_SYNC_RESPONSE_INVALID")?;
        if result.schema != version.update_schema()
            || result.mode != "history"
            || result.source_refresh_performed
            || result.base_pack_id != ticket.descriptor.id
            || !same(&result.base_pack, &ticket.descriptor)
            || !wire::hex(&result.base_semantic_digest)
            || !wire::hex(&result.current_semantic_digest)
            || result.base_semantic_digest != semantic_digest(&ticket.bytes)?
        {
            return Err("OFFLINE_SYNC_RESPONSE_INVALID");
        }
        if result.state == "no_change" {
            if result.plan.is_some()
                || result.base_semantic_digest != result.current_semantic_digest
            {
                return Err("OFFLINE_SYNC_RESPONSE_INVALID");
            }
            return self.finish_no_change(ticket, fence, token).await;
        }
        if result.state != "planned"
            || result.base_semantic_digest == result.current_semantic_digest
        {
            return Err("OFFLINE_SYNC_RESPONSE_INVALID");
        }
        let plan = result.plan.ok_or("OFFLINE_SYNC_RESPONSE_INVALID")?;
        let (plan_id, fingerprint, package_id, expected_sha, expected_bytes) =
            validate_plan(&plan, &ticket)?;
        let confirmation_key = uuid::Uuid::new_v4().to_string();
        self.stage(
            ticket.clone(),
            "confirming",
            Some((
                plan_id.clone(),
                fingerprint.clone(),
                confirmation_key.clone(),
            )),
            Some(package_id.clone()),
        )
        .await?;
        let body = encoded(
            &json!({"plan_id":plan_id,"expected_fingerprint":fingerprint,"allow_device_storage":true}),
        )?;
        let response = self
            .bridge
            .sync_request(
                &fence,
                &ticket.policy.owner_scope_id,
                SyncEndpoint::Confirm,
                body,
                Some(&confirmation_key),
            )
            .await?;
        let request = wire::InstallRequest {
            package_id: package_id.clone(),
            expected_sha256: expected_sha,
            expected_byte_count: expected_bytes,
            approved_plan_fingerprint: fingerprint,
            slot_id: ticket.policy.slot_id.clone(),
            expected_generation: ticket.policy.binding.generation,
            allow_device_storage: true,
        };
        let descriptor = wire::descriptor(&response, &request)?;
        if descriptor.plan_id != plan_id
            || descriptor.owner_scope_id != ticket.policy.owner_scope_id
            || descriptor.base_pack_id.as_deref() != Some(ticket.descriptor.id.as_str())
        {
            return Err("OFFLINE_SYNC_RESPONSE_INVALID");
        }
        self.stage(
            ticket.clone(),
            "downloading",
            None,
            Some(package_id.clone()),
        )
        .await?;
        let response = self
            .bridge
            .sync_request(
                &fence,
                &ticket.policy.owner_scope_id,
                SyncEndpoint::Descriptor(package_id.clone()),
                Vec::new(),
                None,
            )
            .await?;
        let owned_descriptor = wire::descriptor(&response, &request)?;
        if !same(&owned_descriptor, &descriptor)
            || wire::PackVersion::from_descriptor(&descriptor.schema)? != version
        {
            return Err("OFFLINE_SYNC_RESPONSE_INVALID");
        }
        let bytes = self
            .bridge
            .sync_request(
                &fence,
                &ticket.policy.owner_scope_id,
                SyncEndpoint::Download(package_id),
                Vec::new(),
                None,
            )
            .await?;
        wire::verify_bytes(&bytes, &descriptor)?;
        if semantic_digest(&bytes)? != result.current_semantic_digest {
            return Err("OFFLINE_SYNC_RESPONSE_INVALID");
        }
        let envelope = wire::package(&bytes, &descriptor)?;
        if !same(&envelope.scope, &ticket.policy.scope) {
            return Err("OFFLINE_SYNC_SCOPE_CHANGED");
        }
        self.stage(ticket.clone(), "committing", None, None).await?;
        let store = self.store.clone();
        let staged = blocking(move || {
            let install_ticket = store.begin_install(&request)?;
            store.stage_install(&request, descriptor, bytes, install_ticket)
        })
        .await?;
        let store = self.store.clone();
        self.bridge
            .sync_publish(fence, move || {
                if token.is_cancelled() {
                    return Err("REQUEST_CANCELLED");
                }
                store.sync_commit_observed(&ticket, staged, conditions::sample)
            })
            .await
    }
    async fn finish_no_change(
        &self,
        ticket: Arc<SyncTicket>,
        fence: Arc<SessionFence>,
        token: CancellationToken,
    ) -> NativeResult<SyncRun> {
        self.stage(ticket.clone(), "committing", None, None).await?;
        let store = self.store.clone();
        self.bridge
            .sync_publish(fence, move || {
                if token.is_cancelled() {
                    return Err("REQUEST_CANCELLED");
                }
                store.sync_finish_observed(&ticket, "no_change", None, conditions::sample)
            })
            .await
    }
}

fn validate_plan(
    plan: &Value,
    ticket: &SyncTicket,
) -> NativeResult<(String, String, String, String, u64)> {
    if plan["can_confirm"] != true || plan["state"] != "ready" {
        return Err("OFFLINE_SYNC_PLAN_BLOCKED");
    }
    let text = |key: &str| plan[key].as_str().ok_or("OFFLINE_SYNC_RESPONSE_INVALID");
    let id = text("id")?;
    let fingerprint = text("fingerprint")?;
    let package = text("package_id")?;
    let sha = text("content_sha256")?;
    let bytes = plan["measured_bytes"]
        .as_u64()
        .ok_or("OFFLINE_SYNC_RESPONSE_INVALID")?;
    let scope: wire::Scope = serde_json::from_value(plan["requested_scope"].clone())
        .map_err(|_| "OFFLINE_SYNC_RESPONSE_INVALID")?;
    let capacity: super::SyncCapacity = serde_json::from_value(plan["capacity"].clone())
        .map_err(|_| "OFFLINE_SYNC_RESPONSE_INVALID")?;
    let counts: wire::Counts = serde_json::from_value(plan["counts"].clone())
        .map_err(|_| "OFFLINE_SYNC_RESPONSE_INVALID")?;
    if plan["schema"]
        != wire::PackVersion::from_descriptor(&ticket.descriptor.schema)?.plan_schema()
        || !wire::uuid(id)
        || !wire::uuid(package)
        || !wire::hex(fingerprint)
        || !wire::hex(sha)
        || bytes == 0
        || bytes > capacity.max_package_bytes
        || plan["owner_scope_id"] != ticket.policy.owner_scope_id
        || plan["base_pack_id"] != ticket.descriptor.id
        || !same(&scope, &ticket.policy.scope)
        || capacity != ticket.policy.capacity
        || counts.distinct_evidence > capacity.max_distinct_evidence
        || counts.garage_profiles > capacity.max_garage_profiles
        || counts.watch_items > capacity.max_watch_items
        || counts.recent_queries > capacity.max_recent_query_candidates
        || counts.searchable_documents > capacity.max_searchable_documents
        || plan["resolved"].as_array().map(Vec::len) != Some(counts.distinct_evidence as usize)
        || plan["documents"].as_array().map(Vec::len) != Some(counts.searchable_documents as usize)
        || plan["contexts"].as_array().map(Vec::len)
            != Some((counts.garage_profiles + counts.watch_items) as usize)
        || plan["omissions"]
            .as_array()
            .is_none_or(|rows| rows.iter().any(|r| r["blocking"] != false))
        || text("expires_at")
            .ok()
            .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
            .is_none_or(|t| t <= chrono::Utc::now())
    {
        return Err("OFFLINE_SYNC_RESPONSE_INVALID");
    }
    Ok((
        id.into(),
        fingerprint.into(),
        package.into(),
        sha.into(),
        bytes,
    ))
}
