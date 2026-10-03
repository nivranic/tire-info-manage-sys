//! Encrypted, additive sync state shares the slot catalog and its final transaction.
use super::*;
use crate::offline::conditions::{self, Capabilities, Conditions, Sample};
use chrono::{DateTime, Utc};
use std::{collections::HashMap, time::Instant};

const MAX_SYNC_BYTES: usize = MAX_STORE_BYTES as usize;
const MAX_RUNS: usize = 64;
const PREVIEW_SECONDS: i64 = 300;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct SyncCapacity {
    pub version: String,
    pub max_package_bytes: u64,
    pub max_distinct_evidence: u64,
    pub max_garage_profiles: u64,
    pub max_watch_items: u64,
    pub max_recent_query_candidates: u64,
    pub max_searchable_documents: u64,
    pub plan_ttl_seconds: u64,
    pub raw_policy: String,
}
impl Default for SyncCapacity {
    fn default() -> Self {
        Self {
            version: "offline-policy@1".into(),
            max_package_bytes: MAX_PACKAGE_BYTES as u64,
            max_distinct_evidence: 200,
            max_garage_profiles: 50,
            max_watch_items: 100,
            max_recent_query_candidates: 20,
            max_searchable_documents: 4000,
            plan_ttl_seconds: 600,
            raw_policy: "exclude".into(),
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncBinding {
    pub binding_revision: u64,
    pub generation: u64,
    pub package_id: String,
    pub sha256: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncPolicy {
    pub schema: String,
    pub policy_id: String,
    pub policy_revision: u64,
    pub state: String,
    pub profile_id: String,
    pub owner_epoch: u64,
    pub owner_scope_id: String,
    pub slot_id: String,
    pub scope: wire::Scope,
    pub capacity: SyncCapacity,
    pub interval_seconds: u64,
    pub conditions: Conditions,
    pub approved_at: String,
    pub updated_at: String,
    pub binding: SyncBinding,
    pub next_due_at: Option<String>,
    pub reason: Option<String>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncRun {
    pub schema: String,
    pub run_id: String,
    pub policy_id: String,
    pub policy_revision: u64,
    pub trigger: String,
    pub state: String,
    pub stage: String,
    pub reason: Option<String>,
    pub started_at: String,
    pub finished_at: Option<String>,
    pub before_generation: u64,
    pub after_generation: Option<u64>,
    pub plan_id: Option<String>,
    pub package_id: Option<String>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseCheck {
    pub slot_id: String,
    pub generation: u64,
    pub sha256: Option<String>,
    pub host_build: String,
    pub validator_version: String,
    pub checked_at: String,
    pub state: String,
    pub reason: Option<String>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncPreview {
    pub schema: String,
    pub preview_id: String,
    pub fingerprint: String,
    pub expires_at: String,
    pub expected_policy_revision: u64,
    pub profile_id: String,
    pub owner_epoch: u64,
    pub owner_scope_id: String,
    pub slot_id: String,
    pub generation: u64,
    pub package_sha256: String,
    pub scope: wire::Scope,
    pub capacity: SyncCapacity,
    pub interval_seconds: u64,
    pub conditions: Conditions,
    pub capabilities: Capabilities,
    pub counts: Counts,
    pub notice: String,
}
#[derive(Serialize)]
pub struct SyncStatus {
    pub schema: &'static str,
    pub capabilities: Capabilities,
    pub profile_id: String,
    pub owner_epoch: u64,
    pub policies: Vec<SyncPolicy>,
    pub runs: Vec<SyncRun>,
    pub release_checks: Vec<ReleaseCheck>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncPreviewRequest {
    pub slot_id: String,
    pub expected_generation: u64,
    pub expected_profile_id: String,
    pub expected_owner_epoch: u64,
    pub interval_seconds: u64,
    pub conditions: Conditions,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncApplyRequest {
    pub preview_id: String,
    pub expected_fingerprint: String,
    pub expected_policy_revision: u64,
    pub allow_continuous_history_updates: bool,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncPolicyRequest {
    pub policy_id: String,
    pub expected_policy_revision: u64,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SyncRunRequest {
    pub policy_id: String,
    pub expected_policy_revision: u64,
    pub trigger: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Journal {
    run_id: String,
    policy_id: String,
    plan_id: Option<String>,
    fingerprint: Option<String>,
    confirmation_key: Option<String>,
}
#[derive(Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct State {
    version: u8,
    policies: Vec<SyncPolicy>,
    runs: Vec<SyncRun>,
    release_checks: Vec<ReleaseCheck>,
    active: Option<Journal>,
    journals: Vec<Journal>,
}
struct Pending {
    preview: SyncPreview,
    wall: DateTime<Utc>,
    monotonic: Instant,
}
#[derive(Default)]
pub(super) struct Memory {
    previews: HashMap<String, Pending>,
}
impl Memory {
    pub(super) fn clear(&mut self) {
        self.previews.clear();
    }
}

pub struct SyncTicket {
    pub policy: SyncPolicy,
    pub run_id: String,
    pub descriptor: Descriptor,
    pub bytes: Zeroizing<Vec<u8>>,
    _lease: File,
}

fn now() -> String {
    Utc::now().to_rfc3339()
}
fn next_due(interval: u64) -> String {
    (Utc::now() + chrono::Duration::seconds(interval as i64)).to_rfc3339()
}
fn serialize(value: &impl Serialize) -> NativeResult<Vec<u8>> {
    serde_json::to_vec(value).map_err(|_| "OFFLINE_SYNC_STATE_CORRUPT")
}
fn same(a: &impl Serialize, b: &impl Serialize) -> bool {
    serialize(a).ok() == serialize(b).ok()
}

impl Store {
    fn sync_load(&self, connection: &Connection, key: &[u8; 32]) -> NativeResult<State> {
        let encoded: Option<Vec<u8>> = db(connection
            .query_row("SELECT value FROM sync_control WHERE id=1", [], |r| {
                r.get(0)
            })
            .optional())?;
        let Some(encoded) = encoded else {
            return Ok(State {
                version: 1,
                ..State::default()
            });
        };
        let clear = crypto::open(
            key,
            format!("offline-v1:{}:sync-control@1", self.namespace).as_bytes(),
            &encoded,
            MAX_SYNC_BYTES,
        )
        .map_err(|_| "OFFLINE_SYNC_STATE_CORRUPT")?;
        let state: State =
            serde_json::from_slice(&clear).map_err(|_| "OFFLINE_SYNC_STATE_CORRUPT")?;
        if state.version != 1
            || state.policies.len() > MAX_SLOTS
            || state.runs.len() > MAX_RUNS
            || state.journals.len() > MAX_RUNS
            || state.release_checks.len() > MAX_SLOTS
        {
            return Err("OFFLINE_SYNC_STATE_CORRUPT");
        }
        let mut ids = std::collections::HashSet::new();
        for policy in &state.policies {
            if policy.schema != "device-sync-policy@1"
                || !wire::uuid(&policy.policy_id)
                || !wire::uuid(&policy.slot_id)
                || !wire::uuid(&policy.profile_id)
                || !wire::hex(&policy.owner_scope_id)
                || !ids.insert(policy.slot_id.clone())
                || !(1..SAFE_INTEGER).contains(&policy.policy_revision)
                || !(900..=604800).contains(&policy.interval_seconds)
                || !matches!(policy.state.as_str(), "enabled" | "paused" | "revoked")
                || policy.capacity != SyncCapacity::default()
                || !wire::hex(&policy.binding.sha256)
                || !wire::uuid(&policy.binding.package_id)
                || policy.binding.generation == 0
            {
                return Err("OFFLINE_SYNC_STATE_CORRUPT");
            }
        }
        for check in &state.release_checks {
            if !wire::uuid(&check.slot_id)
                || check.generation == 0
                || !matches!(check.state.as_str(), "passed" | "failed")
                || check.sha256.as_deref().is_some_and(|sha| !wire::hex(sha))
                || (check.state == "passed" && check.sha256.is_none())
            {
                return Err("OFFLINE_SYNC_STATE_CORRUPT");
            }
        }
        let mut run_ids = std::collections::HashSet::new();
        for run in &state.runs {
            if run.schema != "device-sync-run@1"
                || !wire::uuid(&run.run_id)
                || !wire::uuid(&run.policy_id)
                || !run_ids.insert(run.run_id.clone())
                || !(1..SAFE_INTEGER).contains(&run.policy_revision)
                || !matches!(
                    run.state.as_str(),
                    "running"
                        | "succeeded"
                        | "no_change"
                        | "deferred"
                        | "blocked"
                        | "failed"
                        | "cancelled"
                        | "interrupted"
                )
                || !matches!(
                    run.stage.as_str(),
                    "checking"
                        | "preparing"
                        | "confirming"
                        | "downloading"
                        | "committing"
                        | "finished"
                )
                || run.plan_id.as_deref().is_some_and(|id| !wire::uuid(id))
                || run.package_id.as_deref().is_some_and(|id| !wire::uuid(id))
            {
                return Err("OFFLINE_SYNC_STATE_CORRUPT");
            }
        }
        if let Some(active) = &state.active {
            if !state.runs.iter().any(|r| {
                r.run_id == active.run_id && r.policy_id == active.policy_id && r.state == "running"
            }) || !state
                .policies
                .iter()
                .any(|p| p.policy_id == active.policy_id && p.state == "enabled")
                || active.plan_id.as_deref().is_some_and(|id| !wire::uuid(id))
                || active.fingerprint.as_deref().is_some_and(|v| !wire::hex(v))
                || active
                    .confirmation_key
                    .as_deref()
                    .is_some_and(|id| !wire::uuid(id))
            {
                return Err("OFFLINE_SYNC_STATE_CORRUPT");
            }
        }
        Ok(state)
    }
    fn sync_save(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        state: &State,
    ) -> NativeResult<()> {
        let clear = Zeroizing::new(serialize(state)?);
        if clear.len() > MAX_SYNC_BYTES {
            return Err("OFFLINE_SYNC_CAPACITY");
        }
        let encoded = crypto::seal(
            key,
            format!("offline-v1:{}:sync-control@1", self.namespace).as_bytes(),
            &clear,
        )?;
        db(connection.execute("INSERT INTO sync_control(id,value) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET value=excluded.value", [encoded]))?;
        Ok(())
    }
    fn sync_lock(&self) -> NativeResult<File> {
        let file = io(OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.root.join("sync.lock")))?;
        file.try_lock().map_err(|_| "OFFLINE_SYNC_BUSY")?;
        Ok(file)
    }
    pub(super) fn initialize_sync(&self) -> NativeResult<()> {
        {
            let inner = self.lock()?;
            db(inner.connection.execute_batch("CREATE TABLE IF NOT EXISTS sync_control(id INTEGER PRIMARY KEY CHECK(id=1),value BLOB NOT NULL);"))?;
        }
        // A live other-process lease is never mistaken for a crashed process.
        if let Ok(_lease) = self.sync_lock() {
            let _profile = self.fallback_profile_lock()?;
            let mut inner = self.lock()?;
            let Inner {
                connection, key, ..
            } = &mut *inner;
            let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
            let mut state = self.sync_load(&tx, key)?;
            if let Some(journal) = state.active.take() {
                for run in &mut state.runs {
                    if run.run_id == journal.run_id {
                        run.state = "interrupted".into();
                        run.stage = "finished".into();
                        run.reason = Some("OFFLINE_SYNC_PROCESS_RESTARTED".into());
                        run.finished_at = Some(now());
                    }
                }
                for policy in &mut state.policies {
                    if policy.policy_id == journal.policy_id && policy.state == "enabled" {
                        policy.state = "paused".into();
                        policy.policy_revision += 1;
                        policy.reason = Some("OFFLINE_SYNC_PROCESS_RESTARTED".into());
                        policy.next_due_at = None;
                        policy.updated_at = now();
                    }
                }
                state.journals.push(journal);
                state.journals.truncate(MAX_RUNS);
            }
            self.sync_save(&tx, key, &state)?;
            db(tx.commit())?;
        }
        self.sync_revalidate().map(|_| ())
    }
    pub fn sync_status(&self) -> NativeResult<SyncStatus> {
        let inner = self.lock()?;
        let vault = self.vault(&inner.connection, &inner.key)?;
        let state = self.sync_load(&inner.connection, &inner.key)?;
        Ok(SyncStatus {
            schema: "device-sync-status@1",
            capabilities: conditions::capabilities(),
            profile_id: vault.profile_id,
            owner_epoch: vault.owner_epoch,
            policies: state.policies,
            runs: state.runs,
            release_checks: state.release_checks,
        })
    }
    pub(super) fn release_gate(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        slot: &Slot,
    ) -> NativeResult<()> {
        let state = self.sync_load(connection, key)?;
        if state.release_checks.iter().any(|check| {
            check.slot_id == slot.slot_id
                && check.generation == slot.generation
                && check.sha256.as_deref() == Some(slot.sha256.as_str())
                && check.host_build == conditions::HOST_BUILD
                && check.validator_version == conditions::VALIDATOR_VERSION
                && check.state == "passed"
        }) {
            Ok(())
        } else {
            Err("OFFLINE_RELEASE_VALIDATION_REQUIRED")
        }
    }
    fn sync_original(
        &self,
        row: &Row,
        metadata: &Metadata,
        key: &[u8; 32],
    ) -> NativeResult<Zeroizing<Vec<u8>>> {
        let path = self.root.join(format!(
            "{}.pack",
            row.file_id.as_deref().ok_or("OFFLINE_PACK_CORRUPT")?
        ));
        let info = io(fs::symlink_metadata(&path))?;
        if !info.is_file()
            || info.file_type().is_symlink()
            || info.len() != metadata.slot.byte_count + crypto::OVERHEAD as u64
        {
            return Err("OFFLINE_PACK_CORRUPT");
        }
        let mut encrypted = Vec::new();
        io(File::open(path))?
            .take((MAX_PACKAGE_BYTES + crypto::OVERHEAD + 1) as u64)
            .read_to_end(&mut encrypted)
            .map_err(|_| "OFFLINE_STORE_FAILED")?;
        let bytes = crypto::open(
            key,
            self.package_aad(&row.id, row.generation, metadata.installed_epoch)
                .as_bytes(),
            &encrypted,
            MAX_PACKAGE_BYTES,
        )?;
        let request = InstallRequest {
            package_id: metadata.slot.package_id.clone(),
            expected_sha256: metadata.slot.sha256.clone(),
            expected_byte_count: metadata.slot.byte_count,
            approved_plan_fingerprint: metadata.descriptor.plan_fingerprint.clone(),
            slot_id: row.id.clone(),
            expected_generation: row.generation,
            allow_device_storage: true,
        };
        wire::descriptor(&serialize(&metadata.descriptor)?, &request)?;
        wire::package(&bytes, &metadata.descriptor)?;
        Ok(bytes)
    }
    fn sync_anchor(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        policy: &SyncPolicy,
    ) -> NativeResult<(Row, Metadata)> {
        let vault = self.vault(connection, key)?;
        if vault.profile_id != policy.profile_id || vault.owner_epoch != policy.owner_epoch {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        let row = Self::row(connection, &policy.slot_id)?
            .filter(|row| row.file_id.is_some())
            .ok_or("OFFLINE_SLOT_NOT_FOUND")?;
        let metadata = self.metadata(&row, key)?;
        if metadata.installed_epoch != vault.owner_epoch {
            return Err("OFFLINE_SYNC_PREVIOUS_OWNER");
        }
        if row.generation != policy.binding.generation
            || metadata.slot.sha256 != policy.binding.sha256
            || metadata.slot.package_id != policy.binding.package_id
            || metadata.slot.owner_scope_id != policy.owner_scope_id
            || metadata.descriptor.owner_scope_id != policy.owner_scope_id
        {
            return Err("OFFLINE_SYNC_BINDING_CHANGED");
        }
        self.release_gate(connection, key, &metadata.slot)?;
        Ok((row, metadata))
    }
    pub fn sync_preview(&self, request: SyncPreviewRequest) -> NativeResult<SyncPreview> {
        if !wire::uuid(&request.slot_id)
            || !wire::uuid(&request.expected_profile_id)
            || !(1..SAFE_INTEGER).contains(&request.expected_generation)
            || request.expected_owner_epoch >= SAFE_INTEGER
            || !(900..=604800).contains(&request.interval_seconds)
        {
            return Err("OFFLINE_SYNC_INVALID");
        }
        request.conditions.validate()?;
        if conditions::capabilities().scheduler == "unsupported" {
            return Err("OFFLINE_SYNC_UNSUPPORTED");
        }
        let mut inner = self.lock()?;
        let vault = self.vault(&inner.connection, &inner.key)?;
        if vault.profile_id != request.expected_profile_id
            || vault.owner_epoch != request.expected_owner_epoch
        {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        let row = Self::row(&inner.connection, &request.slot_id)?
            .filter(|r| r.file_id.is_some())
            .ok_or("OFFLINE_SLOT_NOT_FOUND")?;
        let metadata = self.metadata(&row, &inner.key)?;
        if row.generation != request.expected_generation {
            return Err("OFFLINE_GENERATION_CONFLICT");
        }
        if metadata.installed_epoch != vault.owner_epoch {
            return Err("OFFLINE_SYNC_PREVIOUS_OWNER");
        }
        self.release_gate(&inner.connection, &inner.key, &metadata.slot)?;
        let raw = self.sync_original(&row, &metadata, &inner.key)?;
        let envelope = wire::package(&raw, &metadata.descriptor)?;
        Index::new(
            row.id.clone(),
            row.generation,
            vault.owner_epoch,
            envelope.clone(),
        )?;
        let state = self.sync_load(&inner.connection, &inner.key)?;
        let revision = state
            .policies
            .iter()
            .find(|p| p.slot_id == row.id)
            .map(|p| p.policy_revision)
            .unwrap_or(0);
        let scope = derive_scope(&envelope)?;
        let wall = Utc::now();
        let mut preview = SyncPreview { schema: "device-sync-preview@1".into(), preview_id: uuid::Uuid::new_v4().to_string(),
            fingerprint: String::new(), expires_at: (wall + chrono::Duration::seconds(PREVIEW_SECONDS)).to_rfc3339(),
            expected_policy_revision: revision, profile_id: vault.profile_id, owner_epoch: vault.owner_epoch,
            owner_scope_id: metadata.slot.owner_scope_id, slot_id: row.id, generation: row.generation,
            package_sha256: metadata.slot.sha256, scope, capacity: SyncCapacity::default(), interval_seconds: request.interval_seconds,
            conditions: request.conditions, capabilities: conditions::capabilities(), counts: metadata.slot.counts,
            notice: "仅重新整理已有历史；Garage/关注项范围可包含未来新增或删除，最近N查询保持动态，显式证据固定验证回执；容量不裁剪。持续许可直到暂停/撤销。Windows仅应用打开时运行，关闭后不保证执行。".into() };
        preview.fingerprint = crypto::hash(&serialize(&preview)?);
        inner
            .sync
            .previews
            .retain(|_, p| p.monotonic.elapsed().as_secs() < PREVIEW_SECONDS as u64);
        if inner.sync.previews.len() >= MAX_SLOTS {
            return Err("OFFLINE_SYNC_CAPACITY");
        }
        inner.sync.previews.insert(
            preview.preview_id.clone(),
            Pending {
                preview: preview.clone(),
                wall,
                monotonic: Instant::now(),
            },
        );
        Ok(preview)
    }
    pub fn sync_apply(&self, request: SyncApplyRequest) -> NativeResult<SyncPolicy> {
        if !request.allow_continuous_history_updates {
            return Err("OFFLINE_SYNC_CONSENT_REQUIRED");
        }
        if !wire::uuid(&request.preview_id) || !wire::hex(&request.expected_fingerprint) {
            return Err("OFFLINE_SYNC_INVALID");
        }
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let pending = inner
            .sync
            .previews
            .remove(&request.preview_id)
            .ok_or("OFFLINE_SYNC_PREVIEW_USED")?;
        let preview = pending.preview;
        if Utc::now() < pending.wall
            || Utc::now() >= pending.wall + chrono::Duration::seconds(PREVIEW_SECONDS)
            || pending.monotonic.elapsed().as_secs() >= PREVIEW_SECONDS as u64
        {
            return Err("OFFLINE_SYNC_PREVIEW_EXPIRED");
        }
        if preview.fingerprint != request.expected_fingerprint
            || preview.expected_policy_revision != request.expected_policy_revision
        {
            return Err("OFFLINE_SYNC_PREVIEW_MISMATCH");
        }
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let vault = self.vault(&tx, key)?;
        let mut state = self.sync_load(&tx, key)?;
        if vault.profile_id != preview.profile_id || vault.owner_epoch != preview.owner_epoch {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        let existing = state
            .policies
            .iter()
            .position(|p| p.slot_id == preview.slot_id);
        let revision = existing
            .map(|i| state.policies[i].policy_revision)
            .unwrap_or(0);
        if revision != preview.expected_policy_revision {
            return Err("OFFLINE_SYNC_REVISION_CONFLICT");
        }
        let package_id = Self::row(&tx, &preview.slot_id)?
            .and_then(|r| self.metadata(&r, key).ok())
            .ok_or("OFFLINE_PACK_CORRUPT")?
            .slot
            .package_id;
        let binding_revision = existing
            .map(|i| state.policies[i].binding.binding_revision + 1)
            .unwrap_or(1);
        let policy = SyncPolicy {
            schema: "device-sync-policy@1".into(),
            policy_id: existing
                .map(|i| state.policies[i].policy_id.clone())
                .unwrap_or_else(|| uuid::Uuid::new_v4().to_string()),
            policy_revision: revision
                .checked_add(1)
                .filter(|r| *r < SAFE_INTEGER)
                .ok_or("OFFLINE_SYNC_REVISION_EXHAUSTED")?,
            state: "enabled".into(),
            profile_id: preview.profile_id,
            owner_epoch: preview.owner_epoch,
            owner_scope_id: preview.owner_scope_id,
            slot_id: preview.slot_id,
            scope: preview.scope,
            capacity: preview.capacity,
            interval_seconds: preview.interval_seconds,
            conditions: preview.conditions,
            approved_at: now(),
            updated_at: now(),
            binding: SyncBinding {
                binding_revision,
                generation: preview.generation,
                package_id,
                sha256: preview.package_sha256,
            },
            next_due_at: Some(now()),
            reason: None,
        };
        self.sync_anchor(&tx, key, &policy)?;
        if let Some(i) = existing {
            state.policies[i] = policy.clone();
        } else {
            if state.policies.len() >= MAX_SLOTS {
                return Err("OFFLINE_SYNC_CAPACITY");
            }
            state.policies.push(policy.clone());
        }
        self.sync_cancel_matching(
            &mut state,
            Some(&policy.policy_id),
            "OFFLINE_SYNC_POLICY_CHANGED",
        );
        self.sync_save(&tx, key, &state)?;
        db(tx.commit())?;
        Ok(policy)
    }
    fn sync_cancel_matching(&self, state: &mut State, policy_id: Option<&str>, reason: &str) {
        if state
            .active
            .as_ref()
            .is_some_and(|j| policy_id.is_none() || policy_id == Some(j.policy_id.as_str()))
        {
            let journal = state.active.take().unwrap();
            for run in &mut state.runs {
                if run.run_id == journal.run_id {
                    run.state = "cancelled".into();
                    run.stage = "finished".into();
                    run.reason = Some(reason.into());
                    run.finished_at = Some(now());
                }
            }
            state.journals.push(journal);
            if state.journals.len() > MAX_RUNS {
                state.journals.remove(0);
            }
        }
    }
    pub fn sync_change_policy(
        &self,
        request: SyncPolicyRequest,
        revoke: bool,
    ) -> NativeResult<SyncPolicy> {
        if !wire::uuid(&request.policy_id) || request.expected_policy_revision == 0 {
            return Err("OFFLINE_SYNC_INVALID");
        }
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.sync_load(&tx, key)?;
        let policy = state
            .policies
            .iter_mut()
            .find(|p| p.policy_id == request.policy_id)
            .ok_or("OFFLINE_SYNC_POLICY_NOT_FOUND")?;
        if policy.policy_revision != request.expected_policy_revision {
            return Err("OFFLINE_SYNC_REVISION_CONFLICT");
        }
        policy.policy_revision = policy
            .policy_revision
            .checked_add(1)
            .filter(|r| *r < SAFE_INTEGER)
            .ok_or("OFFLINE_SYNC_REVISION_EXHAUSTED")?;
        policy.state = if revoke { "revoked" } else { "paused" }.into();
        policy.updated_at = now();
        policy.next_due_at = None;
        policy.reason = Some(
            if revoke {
                "OFFLINE_SYNC_REVOKED"
            } else {
                "OFFLINE_SYNC_PAUSED"
            }
            .into(),
        );
        let result = policy.clone();
        self.sync_cancel_matching(
            &mut state,
            Some(&request.policy_id),
            "OFFLINE_SYNC_CANCELLED",
        );
        self.sync_save(&tx, key, &state)?;
        db(tx.commit())?;
        Ok(result)
    }
    pub fn sync_begin(&self, request: SyncRunRequest, sample: Sample) -> NativeResult<SyncTicket> {
        if !wire::uuid(&request.policy_id)
            || !matches!(
                request.trigger.as_str(),
                "manual" | "timer" | "resume" | "online"
            )
        {
            return Err("OFFLINE_SYNC_INVALID");
        }
        let lease = self.sync_lock()?;
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.sync_load(&tx, key)?;
        if state.active.is_some() {
            return Err("OFFLINE_SYNC_BUSY");
        }
        let policy = state
            .policies
            .iter()
            .find(|p| p.policy_id == request.policy_id)
            .ok_or("OFFLINE_SYNC_POLICY_NOT_FOUND")?
            .clone();
        if policy.policy_revision != request.expected_policy_revision {
            return Err("OFFLINE_SYNC_REVISION_CONFLICT");
        }
        if policy.state != "enabled" {
            return Err("OFFLINE_SYNC_NOT_ENABLED");
        }
        let (row, metadata) = self.sync_anchor(&tx, key, &policy)?;
        let bytes = self.sync_original(&row, &metadata, key)?;
        let run_id = uuid::Uuid::new_v4().to_string();
        let due = request.trigger == "manual"
            || policy
                .next_due_at
                .as_deref()
                .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
                .is_some_and(|due| due <= Utc::now());
        let allowed = due && policy.conditions.met(sample);
        let run = SyncRun {
            schema: "device-sync-run@1".into(),
            run_id: run_id.clone(),
            policy_id: policy.policy_id.clone(),
            policy_revision: policy.policy_revision,
            trigger: request.trigger,
            state: if allowed { "running" } else { "deferred" }.into(),
            stage: if allowed { "checking" } else { "finished" }.into(),
            reason: if allowed {
                None
            } else {
                Some(
                    if due {
                        "OFFLINE_SYNC_CONDITIONS_UNMET"
                    } else {
                        "OFFLINE_SYNC_NOT_DUE"
                    }
                    .into(),
                )
            },
            started_at: now(),
            finished_at: if allowed { None } else { Some(now()) },
            before_generation: row.generation,
            after_generation: None,
            plan_id: None,
            package_id: None,
        };
        state.runs.push(run);
        if state.runs.len() > MAX_RUNS {
            state.runs.remove(0);
        }
        if allowed {
            state.active = Some(Journal {
                run_id: run_id.clone(),
                policy_id: policy.policy_id.clone(),
                plan_id: None,
                fingerprint: None,
                confirmation_key: None,
            });
        } else if due {
            if let Some(p) = state
                .policies
                .iter_mut()
                .find(|p| p.policy_id == policy.policy_id)
            {
                p.next_due_at = Some(next_due(p.interval_seconds));
            }
        }
        self.sync_save(&tx, key, &state)?;
        db(tx.commit())?;
        if !allowed {
            return Err("OFFLINE_SYNC_DEFERRED");
        }
        Ok(SyncTicket {
            policy,
            run_id,
            descriptor: metadata.descriptor,
            bytes,
            _lease: lease,
        })
    }
    fn sync_ticket_check(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        state: &State,
        ticket: &SyncTicket,
    ) -> NativeResult<()> {
        if state.active.as_ref().map(|j| j.run_id.as_str()) != Some(ticket.run_id.as_str()) {
            return Err("OFFLINE_SYNC_LEASE_CHANGED");
        }
        let policy = state
            .policies
            .iter()
            .find(|p| p.policy_id == ticket.policy.policy_id)
            .ok_or("OFFLINE_SYNC_POLICY_NOT_FOUND")?;
        if policy.state != "enabled" || policy.policy_revision != ticket.policy.policy_revision {
            return Err("OFFLINE_SYNC_POLICY_CHANGED");
        }
        self.sync_anchor(connection, key, policy)?;
        Ok(())
    }
    pub fn sync_stage(
        &self,
        ticket: &SyncTicket,
        stage: &str,
        plan: Option<(&str, &str, &str)>,
        package: Option<&str>,
    ) -> NativeResult<()> {
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.sync_load(&tx, key)?;
        self.sync_ticket_check(&tx, key, &state, ticket)?;
        let run = state
            .runs
            .iter_mut()
            .find(|r| r.run_id == ticket.run_id)
            .ok_or("OFFLINE_SYNC_STATE_CORRUPT")?;
        run.stage = stage.into();
        if let Some((id, fingerprint, confirmation_key)) = plan {
            run.plan_id = Some(id.into());
            let journal = state.active.as_mut().unwrap();
            journal.plan_id = Some(id.into());
            journal.fingerprint = Some(fingerprint.into());
            journal.confirmation_key = Some(confirmation_key.into());
        }
        if let Some(id) = package {
            run.package_id = Some(id.into());
        }
        self.sync_save(&tx, key, &state)?;
        db(tx.commit())?;
        Ok(())
    }
    pub fn sync_finish(
        &self,
        ticket: &SyncTicket,
        result: &str,
        reason: Option<&str>,
        sample: Sample,
    ) -> NativeResult<SyncRun> {
        self.sync_finish_observed(ticket, result, reason, || sample)
    }
    pub fn sync_finish_observed(
        &self,
        ticket: &SyncTicket,
        result: &str,
        reason: Option<&str>,
        mut observe: impl FnMut() -> Sample,
    ) -> NativeResult<SyncRun> {
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.sync_load(&tx, key)?;
        self.sync_ticket_check(&tx, key, &state, ticket)?;
        if result == "no_change" && !ticket.policy.conditions.met(observe()) {
            return Err("OFFLINE_SYNC_CONDITIONS_UNMET");
        }
        let policy = state
            .policies
            .iter_mut()
            .find(|p| p.policy_id == ticket.policy.policy_id)
            .unwrap();
        if result == "interrupted" {
            policy.state = "paused".into();
            policy.policy_revision += 1;
            policy.next_due_at = None;
        } else {
            policy.next_due_at = Some(next_due(policy.interval_seconds));
        }
        policy.updated_at = now();
        policy.reason = reason.map(str::to_owned);
        let run = state
            .runs
            .iter_mut()
            .find(|r| r.run_id == ticket.run_id)
            .unwrap();
        run.state = result.into();
        run.stage = "finished".into();
        run.finished_at = Some(now());
        run.reason = reason.map(str::to_owned);
        run.after_generation = (result == "no_change").then_some(ticket.policy.binding.generation);
        let result = run.clone();
        let journal = state.active.take().unwrap();
        state.journals.push(journal);
        if state.journals.len() > MAX_RUNS {
            state.journals.remove(0);
        }
        self.sync_save(&tx, key, &state)?;
        // Observe again after preparing all durable writes, immediately before
        // COMMIT. The profile/SQLite/session authority guards remain held.
        if result.state == "no_change" && !ticket.policy.conditions.met(observe()) {
            return Err("OFFLINE_SYNC_CONDITIONS_UNMET");
        }
        db(tx.commit())?;
        Ok(result)
    }
    #[cfg(test)]
    pub fn sync_commit(
        &self,
        ticket: &SyncTicket,
        staged: StagedInstall,
        sample: Sample,
    ) -> NativeResult<SyncRun> {
        self.sync_commit_observed(ticket, staged, || sample)
    }
    pub fn sync_commit_observed(
        &self,
        ticket: &SyncTicket,
        mut staged: StagedInstall,
        mut observe: impl FnMut() -> Sample,
    ) -> NativeResult<SyncRun> {
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            index,
            fallback,
            ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.sync_load(&tx, key)?;
        self.sync_ticket_check(&tx, key, &state, ticket)?;
        if !ticket.policy.conditions.met(observe()) {
            return Err("OFFLINE_SYNC_CONDITIONS_UNMET");
        }
        if staged.slot.slot_id != ticket.policy.slot_id
            || staged.request.expected_generation != ticket.policy.binding.generation
            || staged.slot.owner_scope_id != ticket.policy.owner_scope_id
        {
            return Err("OFFLINE_SYNC_BINDING_CHANGED");
        }
        let journal = state.active.as_ref().unwrap();
        if journal.plan_id.is_none()
            || journal.fingerprint.as_deref()
                != Some(staged.request.approved_plan_fingerprint.as_str())
            || journal
                .confirmation_key
                .as_deref()
                .is_none_or(|key| !wire::uuid(key))
        {
            return Err("OFFLINE_SYNC_JOURNAL_MISMATCH");
        }
        self.write_staged(&tx, key, &staged)?;
        let next_metadata = self.metadata(
            &Self::row(&tx, &staged.slot.slot_id)?.ok_or("OFFLINE_PACK_CORRUPT")?,
            key,
        )?;
        self.fallback_invalidate_slot(
            &tx,
            key,
            Some(&staged.slot.slot_id),
            next_metadata.fallback_binding.as_ref(),
        )?;
        let policy = state
            .policies
            .iter_mut()
            .find(|p| p.policy_id == ticket.policy.policy_id)
            .unwrap();
        policy.binding = SyncBinding {
            binding_revision: policy
                .binding
                .binding_revision
                .checked_add(1)
                .filter(|v| *v < SAFE_INTEGER)
                .ok_or("OFFLINE_SYNC_REVISION_EXHAUSTED")?,
            generation: staged.slot.generation,
            package_id: staged.slot.package_id.clone(),
            sha256: staged.slot.sha256.clone(),
        };
        policy.updated_at = now();
        policy.reason = None;
        policy.next_due_at = Some(next_due(policy.interval_seconds));
        let run = state
            .runs
            .iter_mut()
            .find(|r| r.run_id == ticket.run_id)
            .unwrap();
        run.state = "succeeded".into();
        run.stage = "finished".into();
        run.finished_at = Some(now());
        run.after_generation = Some(staged.slot.generation);
        run.package_id = Some(staged.slot.package_id.clone());
        let result = run.clone();
        state.journals.push(state.active.take().unwrap());
        if state.journals.len() > MAX_RUNS {
            state.journals.remove(0);
        }
        state
            .release_checks
            .retain(|check| check.slot_id != staged.slot.slot_id);
        state.release_checks.push(ReleaseCheck {
            slot_id: staged.slot.slot_id.clone(),
            generation: staged.slot.generation,
            sha256: Some(staged.slot.sha256.clone()),
            host_build: conditions::HOST_BUILD.into(),
            validator_version: conditions::VALIDATOR_VERSION.into(),
            checked_at: now(),
            state: "passed".into(),
            reason: None,
        });
        self.sync_save(&tx, key, &state)?;
        if !ticket.policy.conditions.met(observe()) {
            return Err("OFFLINE_SYNC_CONDITIONS_UNMET");
        }
        db(tx.commit())?;
        Self::fallback_cancel_pending(fallback);
        staged.published = true;
        *index = staged.index.take();
        Ok(result)
    }
    pub(super) fn sync_invalidate_slot(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        slot_id: Option<&str>,
    ) -> NativeResult<()> {
        let mut state = match self.sync_load(connection, key) {
            Ok(state) => state,
            // Corruption already disables every sync operation. Exact explicit
            // removal/reset must remain available without recreating consent.
            Err("OFFLINE_SYNC_STATE_CORRUPT") => return Ok(()),
            Err(error) => return Err(error),
        };
        let ids: Vec<String> = state
            .policies
            .iter_mut()
            .filter(|p| slot_id.is_none() || slot_id == Some(p.slot_id.as_str()))
            .map(|p| {
                p.state = "revoked".into();
                p.policy_revision += 1;
                p.updated_at = now();
                p.next_due_at = None;
                p.reason = Some("OFFLINE_SYNC_ANCHOR_INVALIDATED".into());
                p.policy_id.clone()
            })
            .collect();
        for id in ids {
            self.sync_cancel_matching(&mut state, Some(&id), "OFFLINE_SYNC_ANCHOR_INVALIDATED");
        }
        self.sync_save(connection, key, &state)
    }
    pub(super) fn sync_record_install(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        slot: &Slot,
    ) -> NativeResult<()> {
        let mut state = self.sync_load(connection, key)?;
        state.release_checks.retain(|c| c.slot_id != slot.slot_id);
        state.release_checks.push(ReleaseCheck {
            slot_id: slot.slot_id.clone(),
            generation: slot.generation,
            sha256: Some(slot.sha256.clone()),
            host_build: conditions::HOST_BUILD.into(),
            validator_version: conditions::VALIDATOR_VERSION.into(),
            checked_at: now(),
            state: "passed".into(),
            reason: None,
        });
        self.sync_save(connection, key, &state)
    }
    pub fn sync_revalidate(&self) -> NativeResult<SyncStatus> {
        let (rows, key, epoch) = {
            let inner = self.lock()?;
            let mut statement = db(inner.connection.prepare("SELECT id,generation,file_id,metadata FROM slots WHERE file_id IS NOT NULL ORDER BY id"))?;
            let rows = db(statement.query_map([], |r| {
                Ok(Row {
                    id: r.get(0)?,
                    generation: r.get::<_, i64>(1)? as u64,
                    file_id: r.get(2)?,
                    metadata: r.get(3)?,
                })
            }))?;
            let rows = rows.map(db).collect::<NativeResult<Vec<_>>>()?;
            if rows.len() > MAX_SLOTS {
                return Err("OFFLINE_PACK_CORRUPT");
            }
            (
                rows,
                Zeroizing::new(*inner.key),
                self.vault(&inner.connection, &inner.key)?.owner_epoch,
            )
        };
        let mut checks = Vec::new();
        let mut fallback_backfills = Vec::new();
        for row in &rows {
            let metadata = self.metadata(row, &key);
            let sha = metadata.as_ref().ok().map(|m| m.slot.sha256.clone());
            let result = metadata.and_then(|mut m| {
                let bytes = self.sync_original(row, &m, &key)?;
                let envelope = wire::package(&bytes, &m.descriptor)?;
                if m.fallback_binding.is_none() {
                    m.fallback_binding =
                        Some(Self::approved_fallback_binding(&m.slot, &envelope, &bytes)?);
                    fallback_backfills.push((
                        row.id.clone(),
                        row.generation,
                        row.file_id.clone(),
                        m,
                    ));
                }
                Index::new(row.id.clone(), row.generation, epoch, envelope).map(|_| ())
            });
            checks.push(ReleaseCheck {
                slot_id: row.id.clone(),
                generation: row.generation,
                sha256: sha,
                host_build: conditions::HOST_BUILD.into(),
                validator_version: conditions::VALIDATOR_VERSION.into(),
                checked_at: now(),
                state: if result.is_ok() { "passed" } else { "failed" }.into(),
                reason: result.err().map(str::to_owned),
            });
        }
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            index,
            ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.sync_load(&tx, key)?;
        for (id, generation, file_id, metadata) in fallback_backfills {
            if Self::row(&tx, &id)?
                .is_some_and(|row| row.generation == generation && row.file_id == file_id)
            {
                let clear = Zeroizing::new(serialize(&metadata)?);
                let encoded =
                    crypto::seal(key, self.metadata_aad(&id, generation).as_bytes(), &clear)?;
                db(tx.execute(
                    "UPDATE slots SET metadata=?1 WHERE id=?2 AND generation=?3",
                    params![encoded, id, generation as i64],
                ))?;
            }
        }
        for check in checks {
            if Self::row(&tx, &check.slot_id)?
                .is_some_and(|r| r.generation == check.generation && r.file_id.is_some())
            {
                state.release_checks.retain(|c| c.slot_id != check.slot_id);
                state.release_checks.push(check);
            }
        }
        state.release_checks.retain(|c| {
            Self::row(&tx, &c.slot_id)
                .ok()
                .flatten()
                .is_some_and(|r| r.file_id.is_some())
        });
        self.sync_save(&tx, key, &state)?;
        db(tx.commit())?;
        *index = None;
        drop(inner);
        self.sync_status()
    }
}

fn derive_scope(envelope: &wire::Envelope) -> NativeResult<wire::Scope> {
    let mut scope = envelope.scope.clone();
    scope.references.clear();
    for requested in &envelope.scope.references {
        let mut requested =
            serde_json::to_value(requested).map_err(|_| "OFFLINE_SYNC_SCOPE_UNRESOLVED")?;
        let fields = requested
            .as_object_mut()
            .ok_or("OFFLINE_SYNC_SCOPE_UNRESOLVED")?;
        if fields
            .get("verification_id")
            .is_some_and(serde_json::Value::is_null)
        {
            fields.remove("verification_id");
        }
        let mut resolved = false;
        for member in envelope
            .members
            .iter()
            .filter(|m| m.member_reasons.iter().any(|r| r.selector == "explicit"))
        {
            let reference = serde_json::to_value(&member.reference)
                .map_err(|_| "OFFLINE_SYNC_SCOPE_UNRESOLVED")?;
            if fields
                .iter()
                .all(|(key, value)| reference.get(key) == Some(value))
            {
                resolved = true;
                if !scope.references.iter().any(|r| same(r, &member.reference)) {
                    scope.references.push(member.reference.clone());
                }
            }
        }
        if !resolved {
            return Err("OFFLINE_SYNC_SCOPE_UNRESOLVED");
        }
    }
    if envelope.omissions.iter().any(|o| o.selector == "explicit") {
        return Err("OFFLINE_SYNC_SCOPE_UNRESOLVED");
    }
    Ok(scope)
}

#[cfg(all(test, target_os = "windows"))]
mod tests;
