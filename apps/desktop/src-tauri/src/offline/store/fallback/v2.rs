//! Exact @2 criteria, host observed authority and encrypted continuous consent.
//! Metadata authorization never opens package bodies or a search index.
use super::*;
use crate::bridge::SessionFence;
use crate::offline::{
    criteria::{Criteria, MemberKind, Query, TireCriteria, Truth},
    raw::{self, Exact},
};
use serde_json::json;
use std::{collections::BTreeSet, sync::Arc};

const INVALID: &str = "OFFLINE_FALLBACK_INVALID";
const AUTHORITY: &str = "OFFLINE_FALLBACK_AUTHORITY_REQUIRED";
const MAX_POLICY_RECORDS: usize = 64;
const MAX_NONREVOKED_POLICIES: usize = 16;
const MAX_POLICY_CONTROL_BYTES: usize = 2 * 1024 * 1024;
const KINDS: [&str; 4] = [
    "tire",
    "vehicle_fitments",
    "recall_campaign",
    "recall_search",
];

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FallbackPackageBinding {
    pub binding_revision: u64,
    pub slot_id: String,
    pub generation: u64,
    pub package_id: String,
    pub sha256: String,
    pub history_scope_fingerprint: String,
    pub source_ids: Vec<String>,
}
#[derive(Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyState {
    version: u8,
    policies: Vec<Value>,
    #[serde(default)]
    permission_observations: HashMap<String, Vec<Value>>,
}
impl PolicyState {
    fn nonrevoked(&self) -> usize {
        self.policies
            .iter()
            .filter(|p| p["state"] != "revoked")
            .count()
    }
    fn compact(&mut self) -> NativeResult<()> {
        while self.policies.len() > MAX_POLICY_RECORDS {
            let index = self
                .policies
                .iter()
                .enumerate()
                .filter(|(_, p)| p["state"] == "revoked")
                .min_by(|(_, a), (_, b)| {
                    a["updated_at"]
                        .as_str()
                        .cmp(&b["updated_at"].as_str())
                        .then_with(|| a["policy_id"].as_str().cmp(&b["policy_id"].as_str()))
                })
                .map(|(index, _)| index)
                .ok_or("OFFLINE_FALLBACK_CAPACITY")?;
            self.policies.remove(index);
        }
        self.permission_observations
            .retain(|id, _| self.policies.iter().any(|p| p["policy_id"] == *id));
        Ok(())
    }
}
struct Preview {
    response: Value,
    request: Value,
    issued: Instant,
    wall: DateTime<Utc>,
    page: u64,
}
struct PendingV2 {
    receipt: Exact,
    intent: Intent,
    issued: Instant,
    wall: DateTime<Utc>,
    page: u64,
}
impl PendingV2 {
    fn expired(&self) -> bool {
        Utc::now() < self.wall
            || Utc::now() >= self.wall + chrono::Duration::seconds(TTL_SECONDS)
            || self.issued.elapsed() >= Duration::from_secs(TTL_SECONDS as u64)
    }
}
pub(in crate::offline::store) struct Memory {
    runtime: String,
    revision: u64,
    observed: Option<Value>,
    fence: Option<Arc<SessionFence>>,
    denial_fence: Option<Arc<SessionFence>>,
    denied_queries: HashSet<String>,
    denial_overflow: bool,
    previews: HashMap<String, Preview>,
    pending: HashMap<String, PendingV2>,
    last_wall: DateTime<Utc>,
}
impl Default for Memory {
    fn default() -> Self {
        Self {
            runtime: uuid::Uuid::new_v4().to_string(),
            revision: 1,
            observed: None,
            fence: None,
            denial_fence: None,
            denied_queries: HashSet::new(),
            denial_overflow: false,
            previews: HashMap::new(),
            pending: HashMap::new(),
            last_wall: Utc::now(),
        }
    }
}

fn keys(value: &Value, expected: &[&str]) -> NativeResult<()> {
    let object = value.as_object().ok_or(INVALID)?;
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err(INVALID);
    }
    Ok(())
}
fn string<'a>(value: &'a Value, key: &str) -> NativeResult<&'a str> {
    value.get(key).and_then(Value::as_str).ok_or(INVALID)
}
fn uint(value: &Value, key: &str) -> NativeResult<u64> {
    value
        .get(key)
        .and_then(Value::as_u64)
        .filter(|v| *v < SAFE_INTEGER)
        .ok_or(INVALID)
}
fn exact(value: &Value) -> NativeResult<Exact> {
    Exact::parse(&serde_json::to_string(value).map_err(|_| INVALID)?)
}
fn get<'a>(value: &'a Exact, key: &str) -> NativeResult<&'a Exact> {
    value.get(key).ok_or(INVALID)
}
fn set(value: &mut Exact, key: &str, replacement: Exact) -> NativeResult<()> {
    if let Exact::Object(object) = value {
        object.insert(key.into(), replacement);
        Ok(())
    } else {
        Err(INVALID)
    }
}
fn source_valid(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && id
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}
fn utc(value: &str) -> NativeResult<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value)
        .map(|v| v.with_timezone(&Utc))
        .map_err(|_| INVALID)
}
fn enabled(policy: &Value) -> bool {
    policy["state"] == "enabled"
        && string(policy, "expires_at")
            .ok()
            .and_then(|s| utc(s).ok())
            .is_some_and(|t| t > Utc::now())
}
fn policy_sources(scope: &Value) -> Vec<Value> {
    match scope["kind"].as_str() {
        Some("source") => vec![scope.clone()],
        _ => scope["sources"].as_array().cloned().unwrap_or_default(),
    }
}
fn matches(policy: &Value, source: &str, generation: u64, kind: &str, legacy: bool) -> bool {
    let scope = &policy["scope"];
    if scope["kind"] == "query" && scope["query_kind"] != kind {
        return false;
    }
    policy_sources(scope).iter().any(|pin| {
        pin["source_id"] == source
            && (legacy || pin["access_generation"].as_u64() == Some(generation))
            && (scope["kind"] == "query"
                || pin["query_kinds"]
                    .as_array()
                    .is_some_and(|kinds| kinds.iter().any(|k| k == kind)))
    })
}

#[derive(Clone)]
struct Intent {
    raw: Exact,
    value: Value,
    criteria: Criteria,
}
impl Intent {
    fn parse(raw: Exact) -> NativeResult<Self> {
        let value = raw.package_mirror();
        keys(
            &value,
            &[
                "schema",
                "attempt_id",
                "query_fingerprint",
                "source_id",
                "source_access_generation",
                "authority",
                "fallback_policy",
                "failure",
                "query_kind",
                "query",
                "filters",
            ],
        )?;
        if value["schema"] != "device-fallback-intent@2"
            || !wire::uuid(string(&value, "attempt_id")?)
            || !wire::hex(string(&value, "query_fingerprint")?)
            || !source_valid(string(&value, "source_id")?)
            || !matches!(string(&value, "fallback_policy")?, "ask" | "never")
        {
            return Err(INVALID);
        }
        uint(&value, "source_access_generation")?;
        keys(
            &value["authority"],
            &["runtime_session_id", "authority_revision"],
        )?;
        if !wire::uuid(string(&value["authority"], "runtime_session_id")?)
            || uint(&value["authority"], "authority_revision")? == 0
        {
            return Err(INVALID);
        }
        keys(&value["failure"], &["scope", "reason", "query_id"])?;
        let f = &value["failure"];
        let failure_ok = match string(f, "scope")? {
            "api_transport" => {
                f["query_id"].is_null()
                    && matches!(
                        string(f, "reason")?,
                        "api_network_unavailable" | "api_timeout"
                    )
            }
            "source_response" => {
                string(f, "query_id").is_ok_and(wire::uuid)
                    && matches!(
                        string(f, "reason")?,
                        "upstream_network_error" | "upstream_timeout"
                    )
            }
            _ => false,
        };
        if !failure_ok {
            return Err(INVALID);
        }
        let query = &value["query"];
        let filters = get(&raw, "filters")?;
        let q = match string(&value, "query_kind")? {
            "tire" => {
                let object = query.as_object().ok_or(INVALID)?;
                if object.is_empty()
                    || object.len() > 2
                    || object
                        .keys()
                        .any(|k| !matches!(k.as_str(), "model" | "size"))
                    || object.values().any(|v| !v.is_string())
                {
                    return Err(INVALID);
                }
                let tire = TireCriteria::new(
                    query["model"].as_str(),
                    query["size"].as_str(),
                    &filters.json(),
                )?;
                if tire.canonical_query() != *query {
                    return Err(INVALID);
                }
                Query::Tire(tire)
            }
            "vehicle_fitments" => {
                keys(query, &["vehicle_id"])?;
                Query::VehicleFitments {
                    vehicle_id: string(query, "vehicle_id")?.into(),
                }
            }
            "recall_campaign" => {
                keys(query, &["campaign_number"])?;
                Query::RecallCampaign {
                    campaign_number: string(query, "campaign_number")?.into(),
                }
            }
            "recall_search" => {
                keys(query, &["search", "offset"])?;
                let spelling = string(query, "offset")?;
                let offset: u32 = spelling.parse().map_err(|_| INVALID)?;
                if offset.to_string() != spelling {
                    return Err(INVALID);
                }
                Query::RecallSearch {
                    search: string(query, "search")?.into(),
                    offset,
                }
            }
            _ => return Err(INVALID),
        };
        if value["query_kind"] != "tire" && !filters.array()?.is_empty() {
            return Err(INVALID);
        }
        let criteria = Criteria::new(string(&value, "source_id")?, q)?;
        Ok(Self {
            raw,
            value,
            criteria,
        })
    }
    fn id(&self) -> &str {
        self.value["attempt_id"].as_str().unwrap()
    }
    fn source(&self) -> &str {
        self.value["source_id"].as_str().unwrap()
    }
    fn generation(&self) -> u64 {
        self.value["source_access_generation"].as_u64().unwrap()
    }
    fn kind(&self) -> &str {
        self.value["query_kind"].as_str().unwrap()
    }
}

impl Store {
    /// Called only while the private bridge owns its session publication guard.
    pub fn fallback_bind_denial_session(&self, fence: Arc<SessionFence>) -> NativeResult<()> {
        let mut inner = self.lock()?;
        Self::bind_denial_session(&mut inner.fallback.v2, fence);
        Ok(())
    }
    fn bind_denial_session(memory: &mut Memory, fence: Arc<SessionFence>) {
        if memory
            .denial_fence
            .as_ref()
            .is_some_and(|old| !old.same_session(&fence))
        {
            memory.denied_queries.clear();
            memory.denial_overflow = false;
        }
        memory.denial_fence = Some(fence);
    }
    /// Actual owned 201 deny response metadata only; no IPC decision claim.
    pub fn fallback_observe_query_denial(
        &self,
        query_id: &str,
        fence: Arc<SessionFence>,
    ) -> NativeResult<()> {
        if !wire::uuid(query_id) {
            return Err(INVALID);
        }
        let mut inner = self.lock()?;
        let memory = &mut inner.fallback.v2;
        Self::bind_denial_session(memory, fence);
        if !memory.denied_queries.contains(query_id) {
            if memory.denied_queries.len() >= MAX_ATTEMPTS {
                memory.denial_overflow = true;
            } else {
                memory.denied_queries.insert(query_id.to_owned());
            }
        }
        Ok(())
    }
    pub(super) fn formal_query_gate(memory: &Memory, failure: &Value) -> NativeResult<()> {
        if failure["scope"] == "source_response" {
            if memory.denial_overflow {
                return Err("OFFLINE_FALLBACK_CAPACITY");
            }
            if failure["query_id"]
                .as_str()
                .is_some_and(|id| memory.denied_queries.contains(id))
            {
                return Err("OFFLINE_FALLBACK_NEVER");
            }
        }
        Ok(())
    }
    pub(super) fn legacy_formal_query_gate(
        memory: &Memory,
        intent: &FallbackIntent,
    ) -> NativeResult<()> {
        Self::formal_query_gate(
            memory,
            &json!({"scope":intent.failure.scope,"query_id":intent.failure.query_id}),
        )
    }
    pub(in crate::offline::store) fn fallback_reset_owner_control(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        profile: &str,
        new_epoch: u64,
    ) -> NativeResult<()> {
        let mut state = self.fallback_policy_load(connection, key)?;
        for policy in &mut state.policies {
            if policy["state"] != "revoked"
                && policy["profile_id"] == profile
                && policy["owner_epoch"]
                    .as_u64()
                    .is_some_and(|epoch| epoch < new_epoch)
            {
                Self::pause_policy(policy, "OFFLINE_FALLBACK_OWNER_CHANGED")?;
                policy["state"] = json!("revoked");
            }
        }
        state.compact()?;
        self.fallback_policy_save(connection, key, &state)
    }
    pub(in crate::offline::store) fn fallback_reset_runtime(fallback: &mut super::Memory) {
        fallback.v2 = Memory::default();
        fallback.pending.clear();
        fallback.attempts.clear();
    }
    pub(in crate::offline::store) fn initialize_fallback_runtime(&self) -> NativeResult<()> {
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.fallback_policy_load(&tx, key)?;
        for policy in &mut state.policies {
            if policy["state"] == "enabled"
                && policy["scope"]["kind"] == "session"
                && policy["runtime_session_id"] != fallback.v2.runtime
            {
                Self::pause_policy(policy, "OFFLINE_FALLBACK_RUNTIME_CHANGED")?;
            }
        }
        self.fallback_policy_save(&tx, key, &state)?;
        db(tx.commit())?;
        Ok(())
    }
    pub(in crate::offline::store) fn fallback_cancel_pending(fallback: &mut super::Memory) {
        fallback.v2.pending.clear();
        fallback.v2.previews.clear();
    }
    pub(super) fn v2_pending_count(fallback: &mut super::Memory, page: u64) -> usize {
        fallback
            .v2
            .pending
            .retain(|_, pending| pending.page == page && !pending.expired());
        fallback.v2.pending.len()
    }
    pub(in crate::offline::store) fn approved_fallback_binding(
        slot: &Slot,
        envelope: &wire::Envelope,
        bytes: &[u8],
    ) -> NativeResult<FallbackPackageBinding> {
        // Preserve the actual approved scope, including omitted optional keys.
        let original = Exact::parse(std::str::from_utf8(bytes).map_err(|_| INVALID)?)?;
        let scope = get(&original, "scope")?;
        let material = format!("device-fallback-approved-scope@1\0{}", scope.json());
        let source_ids = envelope
            .members
            .iter()
            .filter_map(|m| m.source.source_id.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        Ok(FallbackPackageBinding {
            binding_revision: slot.generation,
            slot_id: slot.slot_id.clone(),
            generation: slot.generation,
            package_id: slot.package_id.clone(),
            sha256: slot.sha256.clone(),
            history_scope_fingerprint: crypto::hash(material.as_bytes()),
            source_ids,
        })
    }
    fn fallback_policy_load(
        &self,
        connection: &Connection,
        key: &[u8; 32],
    ) -> NativeResult<PolicyState> {
        let bytes: Option<Vec<u8>> = db(connection
            .query_row(
                "SELECT value FROM fallback_policy_control WHERE id=1",
                [],
                |r| r.get(0),
            )
            .optional())?;
        let Some(bytes) = bytes else {
            return Ok(PolicyState {
                version: 1,
                policies: Vec::new(),
                permission_observations: HashMap::new(),
            });
        };
        let clear = crypto::open(
            key,
            format!("offline-v1:{}:fallback-policy@1", self.namespace).as_bytes(),
            &bytes,
            MAX_POLICY_CONTROL_BYTES,
        )?;
        let state: PolicyState =
            serde_json::from_slice(&clear).map_err(|_| "OFFLINE_FALLBACK_POLICY_CORRUPT")?;
        if state.version != 1
            || state.policies.len() > MAX_POLICY_RECORDS
            || state.nonrevoked() > MAX_NONREVOKED_POLICIES
            || state.permission_observations.len() > MAX_POLICY_RECORDS
        {
            return Err("OFFLINE_FALLBACK_POLICY_CORRUPT");
        }
        let mut ids = HashSet::new();
        for p in &state.policies {
            keys(
                p,
                &[
                    "schema",
                    "policy_id",
                    "policy_revision",
                    "state",
                    "profile_id",
                    "owner_epoch",
                    "owner_scope_id",
                    "runtime_session_id",
                    "approved_at",
                    "updated_at",
                    "expires_at",
                    "fingerprint",
                    "reason",
                    "mode",
                    "scope",
                    "binding",
                    "allow_same_scope_sync_binding_advance",
                ],
            )?;
            if p["schema"] != "device-fallback-policy@1"
                || !wire::uuid(string(p, "policy_id")?)
                || !ids.insert(string(p, "policy_id")?)
                || uint(p, "policy_revision")? == 0
                || !matches!(string(p, "state")?, "enabled" | "paused" | "revoked")
                || !wire::uuid(string(p, "profile_id")?)
                || !wire::hex(string(p, "owner_scope_id")?)
                || !wire::hex(string(p, "fingerprint")?)
            {
                return Err("OFFLINE_FALLBACK_POLICY_CORRUPT");
            }
            self.validate_choice(p, None)?;
            for k in ["approved_at", "updated_at", "expires_at"] {
                utc(string(p, k)?)?;
            }
        }
        for (id, observations) in &state.permission_observations {
            if !state.policies.iter().any(|p| p["policy_id"] == *id) || observations.len() > 10 {
                return Err("OFFLINE_FALLBACK_POLICY_CORRUPT");
            }
            let mut ids = HashSet::new();
            for row in observations {
                keys(
                    row,
                    &[
                        "source_id",
                        "access_generation",
                        "query_kinds",
                        "can_query",
                        "can_fetch",
                    ],
                )?;
                if !source_valid(string(row, "source_id")?)
                    || !ids.insert(string(row, "source_id")?)
                    || row["can_query"].as_bool().is_none()
                    || row["can_fetch"].as_bool().is_none()
                {
                    return Err("OFFLINE_FALLBACK_POLICY_CORRUPT");
                }
                uint(row, "access_generation")?;
                let kinds = row["query_kinds"]
                    .as_array()
                    .ok_or("OFFLINE_FALLBACK_POLICY_CORRUPT")?;
                if kinds.is_empty()
                    || kinds.len() > 4
                    || kinds
                        .iter()
                        .any(|k| k.as_str().is_none_or(|k| !KINDS.contains(&k)))
                {
                    return Err("OFFLINE_FALLBACK_POLICY_CORRUPT");
                }
            }
        }
        Ok(state)
    }
    fn fallback_policy_save(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        state: &PolicyState,
    ) -> NativeResult<()> {
        let clear = Zeroizing::new(serde_json::to_vec(state).map_err(|_| INVALID)?);
        if clear.len() > MAX_POLICY_CONTROL_BYTES {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let bytes = crypto::seal(
            key,
            format!("offline-v1:{}:fallback-policy@1", self.namespace).as_bytes(),
            &clear,
        )?;
        db(connection.execute("INSERT INTO fallback_policy_control(id,value) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET value=excluded.value",[bytes]))?;
        Ok(())
    }
    fn authority_locked(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        memory: &Memory,
    ) -> NativeResult<Value> {
        let vault = self.vault(connection, key)?;
        let observed = memory.observed.as_ref().filter(|a| {
            a["profile_id"] == vault.profile_id
                && a["owner_epoch"].as_u64() == Some(vault.owner_epoch)
        });
        Ok(observed.cloned().unwrap_or_else(||json!({"schema":"device-fallback-source-authority@1","runtime_session_id":memory.runtime,"authority_revision":memory.revision,"state":"unknown","observed_at":null,"profile_id":vault.profile_id,"owner_epoch":vault.owner_epoch,"owner_scope_id":null,"sources":[]})))
    }
    pub fn fallback_authority_capture(&self) -> NativeResult<Value> {
        let inner = self.lock()?;
        self.authority_locked(&inner.connection, &inner.key, &inner.fallback.v2)
    }
    pub fn fallback_authority_fence(&self) -> NativeResult<Arc<SessionFence>> {
        let inner = self.lock()?;
        let authority = self.authority_locked(&inner.connection, &inner.key, &inner.fallback.v2)?;
        if authority["state"] != "last_observed" {
            return Err(AUTHORITY);
        }
        inner.fallback.v2.fence.clone().ok_or(AUTHORITY)
    }
    pub fn fallback_authority_unknown(&self) -> NativeResult<()> {
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        inner.fallback.v2.observed = None;
        // Keep the old private fence solely to detect a changed session on the
        // next successful refresh. Unknown authority cannot retrieve/use it.
        inner.fallback.v2.revision = inner
            .fallback
            .v2
            .revision
            .checked_add(1)
            .filter(|v| *v < SAFE_INTEGER)
            .ok_or(INVALID)?;
        inner.fallback.v2.pending.clear();
        inner.fallback.v2.previews.clear();
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.fallback_policy_load(&tx, key)?;
        for policy in &mut state.policies {
            if policy["state"] == "enabled" && policy["scope"]["kind"] == "session" {
                Self::pause_policy(policy, "OFFLINE_FALLBACK_RUNTIME_CHANGED")?;
            }
        }
        self.fallback_policy_save(&tx, key, &state)?;
        db(tx.commit())?;
        Ok(())
    }
    pub fn fallback_authority_commit(
        &self,
        captured: Value,
        owner: String,
        settings: Value,
        directory: Value,
        fence: Arc<SessionFence>,
    ) -> NativeResult<Value> {
        if !wire::hex(&owner) {
            return Err(AUTHORITY);
        }
        let items = settings["items"].as_array().ok_or(AUTHORITY)?;
        let registered = directory["sources"].as_array().ok_or(AUTHORITY)?;
        if items.len() > 200 || registered.len() > 200 {
            return Err(AUTHORITY);
        }
        let mut sources = Vec::new();
        let mut ids = HashSet::new();
        for item in items {
            let id = string(item, "source_id")?;
            if !source_valid(id) || !ids.insert(id) {
                return Err(AUTHORITY);
            }
            let target = string(item, "target_kind")?;
            // Source settings is itself the registered metadata directory for
            // vehicle sources; tire/recall must also appear in /sources.
            if target != "vehicle" && !registered.iter().any(|s| s["id"] == id) {
                continue;
            }
            let kinds = match target {
                "tire" => vec!["tire"],
                "vehicle" => vec!["vehicle_fitments"],
                "recall" if id == "nhtsa-us-recalls" => vec!["recall_campaign", "recall_search"],
                _ => continue,
            };
            let generation = uint(&item["management"], "access_generation")?;
            let can_fetch = item["can_fetch"].as_bool().ok_or(AUTHORITY)?;
            let can_query = can_fetch
                && item["management"]["state"] == "enabled"
                && item["effective_status"] == "ready";
            sources.push(json!({"source_id":id,"access_generation":generation,"query_kinds":kinds,"can_query":can_query,"can_fetch":can_fetch}));
        }
        sources.sort_by(|a, b| a["source_id"].as_str().cmp(&b["source_id"].as_str()));
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        let current = self.authority_locked(connection, key, &fallback.v2)?;
        if current != captured {
            return Err("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
        }
        let session_changed = fallback
            .v2
            .fence
            .as_ref()
            .is_some_and(|old| !old.same_session(&fence));
        let changed = session_changed
            || current["state"] != "last_observed"
            || current["owner_scope_id"] != owner
            || current["sources"] != Value::Array(sources.clone());
        let mut revision = fallback.v2.revision;
        if changed {
            revision = revision
                .checked_add(1)
                .filter(|v| *v < SAFE_INTEGER)
                .ok_or(INVALID)?;
        }
        let authority = json!({"schema":"device-fallback-source-authority@1","runtime_session_id":fallback.v2.runtime,"authority_revision":revision,"state":"last_observed","observed_at":Utc::now().to_rfc3339(),"profile_id":current["profile_id"],"owner_epoch":current["owner_epoch"],"owner_scope_id":owner,"sources":sources});
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.fallback_policy_load(&tx, key)?;
        let vault = self.vault(&tx, key)?;
        for policy in &mut state.policies {
            if policy["state"] != "enabled" {
                continue;
            }
            let reason = if session_changed {
                Some("OFFLINE_FALLBACK_SESSION_CHANGED")
            } else if policy["profile_id"] != vault.profile_id
                || policy["owner_epoch"].as_u64() != Some(vault.owner_epoch)
                || policy["owner_scope_id"] != owner
            {
                Some("OFFLINE_OWNER_CHANGED")
            } else if policy["scope"]["kind"] == "session"
                && policy["runtime_session_id"] != fallback.v2.runtime
            {
                Some("OFFLINE_FALLBACK_RUNTIME_CHANGED")
            } else if !self.scope_authorized(
                &policy["scope"],
                &authority,
                !matches!(policy["mode"].as_str(), Some("ask" | "never")),
            ) || state
                .permission_observations
                .get(string(policy, "policy_id")?)
                .is_none_or(|saved| {
                    *saved != Self::permission_snapshot(&policy["scope"], &authority)
                })
            {
                Some("OFFLINE_FALLBACK_SOURCE_CHANGED")
            } else {
                None
            };
            if let Some(reason) = reason {
                Self::pause_policy(policy, reason)?;
            }
        }
        self.fallback_policy_save(&tx, key, &state)?;
        db(tx.commit())?;
        fallback.v2.revision = revision;
        fallback.v2.observed = Some(authority.clone());
        Self::bind_denial_session(&mut fallback.v2, fence.clone());
        fallback.v2.fence = Some(fence);
        if changed {
            fallback.v2.pending.clear();
            fallback.v2.previews.clear();
        }
        Ok(authority)
    }
    fn permission_snapshot(scope: &Value, authority: &Value) -> Vec<Value> {
        authority["sources"]
            .as_array()
            .map(|sources| {
                sources
                    .iter()
                    .filter(|source| {
                        policy_sources(scope)
                            .iter()
                            .any(|pin| pin["source_id"] == source["source_id"])
                    })
                    .cloned()
                    .collect()
            })
            .unwrap_or_default()
    }
    fn scope_authorized(&self, scope: &Value, authority: &Value, require_query: bool) -> bool {
        policy_sources(scope).iter().all(|pin| {
            authority["sources"].as_array().is_some_and(|sources| {
                sources.iter().any(|source| {
                    source["source_id"] == pin["source_id"]
                        && source["access_generation"] == pin["access_generation"]
                        && (!require_query || source["can_query"] == true)
                        && if scope["kind"] == "query" {
                            source["query_kinds"]
                                .as_array()
                                .is_some_and(|kinds| kinds.contains(&scope["query_kind"]))
                        } else {
                            pin["query_kinds"].as_array().is_some_and(|kinds| {
                                kinds.iter().all(|k| {
                                    source["query_kinds"]
                                        .as_array()
                                        .is_some_and(|registered| registered.contains(k))
                                })
                            })
                        }
                })
            })
        })
    }
    fn validate_choice(&self, value: &Value, authority: Option<&Value>) -> NativeResult<()> {
        let mode = string(value, "mode")?;
        let scope = &value["scope"];
        if !matches!(
            mode,
            "ask" | "never" | "session_allow" | "source_allow" | "query_allow"
        ) {
            return Err(INVALID);
        }
        match string(scope, "kind")? {
            "source" => keys(
                scope,
                &["kind", "source_id", "access_generation", "query_kinds"],
            )?,
            "session" => keys(scope, &["kind", "sources"])?,
            "query" => {
                keys(scope, &["kind", "query_kind", "sources"])?;
                if !KINDS.contains(&string(scope, "query_kind")?) {
                    return Err(INVALID);
                }
            }
            _ => return Err(INVALID),
        }
        let pins = policy_sources(scope);
        if pins.is_empty() || pins.len() > 10 {
            return Err(INVALID);
        }
        let mut ids = HashSet::new();
        for pin in &pins {
            if scope["kind"] == "query" {
                keys(pin, &["source_id", "access_generation"])?;
            } else if scope["kind"] == "session" {
                keys(pin, &["source_id", "access_generation", "query_kinds"])?;
            }
            let id = string(pin, "source_id")?;
            if !source_valid(id) || !ids.insert(id) {
                return Err(INVALID);
            }
            uint(pin, "access_generation")?;
            if scope["kind"] != "query" {
                let kinds = pin["query_kinds"].as_array().ok_or(INVALID)?;
                let mut unique = HashSet::new();
                if kinds.is_empty()
                    || kinds.len() > 4
                    || kinds.iter().any(|k| {
                        k.as_str()
                            .is_none_or(|k| !KINDS.contains(&k) || !unique.insert(k))
                    })
                {
                    return Err(INVALID);
                }
            }
        }
        if matches!(mode, "ask" | "never") {
            if !value["binding"].is_null()
                || value["allow_same_scope_sync_binding_advance"] != false
            {
                return Err(INVALID);
            }
        } else {
            if (mode == "session_allow" && scope["kind"] != "session")
                || (mode == "source_allow" && scope["kind"] != "source")
                || (mode == "query_allow" && scope["kind"] != "query")
            {
                return Err(INVALID);
            }
            let binding: FallbackPackageBinding =
                serde_json::from_value(value["binding"].clone()).map_err(|_| INVALID)?;
            if binding.binding_revision == 0
                || binding.binding_revision >= SAFE_INTEGER
                || binding.generation == 0
                || binding.generation >= SAFE_INTEGER
                || !wire::uuid(&binding.slot_id)
                || !wire::uuid(&binding.package_id)
                || !wire::hex(&binding.sha256)
                || !wire::hex(&binding.history_scope_fingerprint)
                || binding.source_ids.len() > 1000
                || binding.source_ids.iter().any(|s| !source_valid(s))
            {
                return Err(INVALID);
            }
            value["allow_same_scope_sync_binding_advance"]
                .as_bool()
                .ok_or(INVALID)?;
            if value["allow_same_scope_sync_binding_advance"] == true
                && binding
                    .source_ids
                    .iter()
                    .any(|source| !pins.iter().any(|pin| pin["source_id"] == *source))
            {
                return Err("OFFLINE_FALLBACK_SYNC_ADVANCE_SCOPE_UNAVAILABLE");
            }
        }
        if authority.is_some_and(|a| {
            a["state"] != "last_observed"
                || !self.scope_authorized(scope, a, !matches!(mode, "ask" | "never"))
        }) {
            return Err(AUTHORITY);
        }
        Ok(())
    }
    fn pause_policy(policy: &mut Value, reason: &str) -> NativeResult<()> {
        policy["state"] = json!("paused");
        policy["reason"] = json!(reason);
        policy["updated_at"] = json!(Utc::now().to_rfc3339());
        policy["policy_revision"] = json!(uint(policy, "policy_revision")?
            .checked_add(1)
            .filter(|v| *v < SAFE_INTEGER)
            .ok_or(INVALID)?);
        Ok(())
    }
    pub(in crate::offline::store) fn fallback_invalidate_slot(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        slot: Option<&str>,
        advance: Option<&FallbackPackageBinding>,
    ) -> NativeResult<()> {
        let mut state = match self.fallback_policy_load(connection, key) {
            Ok(state) => state,
            Err("OFFLINE_FALLBACK_POLICY_CORRUPT" | "OFFLINE_PACK_CORRUPT") => return Ok(()),
            Err(error) => return Err(error),
        };
        for p in &mut state.policies {
            if p["state"] != "enabled"
                || p["binding"].is_null()
                || slot.is_some_and(|slot| p["binding"]["slot_id"] != slot)
            {
                continue;
            }
            let can_advance = advance.is_some_and(|next| {
                p["allow_same_scope_sync_binding_advance"] == true
                    && p["binding"]["history_scope_fingerprint"] == next.history_scope_fingerprint
                    && next.source_ids.iter().all(|source| {
                        policy_sources(&p["scope"])
                            .iter()
                            .any(|pin| pin["source_id"] == *source)
                    })
            });
            if can_advance {
                p["binding"] = serde_json::to_value(advance.unwrap()).map_err(|_| INVALID)?;
                p["updated_at"] = json!(Utc::now().to_rfc3339());
            } else {
                Self::pause_policy(p, "OFFLINE_FALLBACK_PACKAGE_CHANGED")?;
            }
        }
        self.fallback_policy_save(connection, key, &state)
    }
    fn binding_metadata(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        binding: &Value,
        profile: &str,
        epoch: u64,
    ) -> NativeResult<(Row, Metadata, Slot)> {
        let vault = self.vault(connection, key)?;
        if vault.profile_id != profile || vault.owner_epoch != epoch {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        let row = Self::row(connection, string(binding, "slot_id")?)?
            .filter(|r| r.file_id.is_some())
            .ok_or("OFFLINE_STALE_GENERATION")?;
        if row.generation != uint(binding, "generation")? {
            return Err("OFFLINE_STALE_GENERATION");
        }
        let metadata = self.metadata(&row, key)?;
        let slot = Self::public_slot(&metadata, epoch);
        if slot.locked || slot.previous_owner || slot.sha256 != string(binding, "sha256")? {
            return Err("OFFLINE_FALLBACK_MISMATCH");
        }
        Ok((row, metadata, slot))
    }
    fn intent_authorized(
        &self,
        intent: &Intent,
        authority: &Value,
        require_query: bool,
    ) -> NativeResult<()> {
        if authority["state"] != "last_observed"
            || intent.value["authority"]["runtime_session_id"] != authority["runtime_session_id"]
            || intent.value["authority"]["authority_revision"] != authority["authority_revision"]
            || !authority["sources"].as_array().is_some_and(|sources| {
                sources.iter().any(|s| {
                    s["source_id"] == intent.source()
                        && s["access_generation"].as_u64() == Some(intent.generation())
                        && (!require_query || s["can_query"] == true)
                        && s["query_kinds"]
                            .as_array()
                            .is_some_and(|ks| ks.iter().any(|k| k == intent.kind()))
                })
            })
        {
            return Err(AUTHORITY);
        }
        Ok(())
    }
    pub(super) fn legacy_never_gate(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        intent: &FallbackIntent,
    ) -> NativeResult<()> {
        let vault = self.vault(connection, key)?;
        let state = self.fallback_policy_load(connection, key)?;
        // Generation is intentionally ignored for legacy callers. Only a
        // successful native refresh may invalidate a saved deny preference.
        if state.policies.iter().any(|p| {
            enabled(p)
                && p["profile_id"] == vault.profile_id
                && p["owner_epoch"].as_u64() == Some(vault.owner_epoch)
                && p["mode"] == "never"
                && matches(
                    p,
                    &intent.source_id,
                    intent.source_access_generation,
                    "tire",
                    true,
                )
        }) {
            return Err("OFFLINE_FALLBACK_NEVER");
        }
        Ok(())
    }
    pub fn fallback_status_v2(&self) -> NativeResult<Value> {
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        self.fallback_clock_gate(&mut inner)?;
        let authority = self.authority_locked(&inner.connection, &inner.key, &inner.fallback.v2)?;
        let state = self.fallback_policy_load(&inner.connection, &inner.key)?;
        let vault = self.vault(&inner.connection, &inner.key)?;
        let mut bindings = Vec::new();
        let mut missing = Vec::new();
        for (_, m) in self.active(&inner.connection, &inner.key)? {
            let slot = Self::public_slot(&m, vault.owner_epoch);
            if slot.locked || slot.previous_owner {
                continue;
            }
            if let Some(binding) = m.fallback_binding {
                bindings.push(serde_json::to_value(binding).map_err(|_| INVALID)?);
            } else {
                missing.push(json!({"slot_id":slot.slot_id,"generation":slot.generation,"reason":"scope_metadata_missing"}));
            }
        }
        Ok(
            json!({"schema":"device-fallback-status@1","profile_id":vault.profile_id,"owner_epoch":vault.owner_epoch,"authority":authority,"capabilities":{"schema":"device-fallback-capabilities@1","intent_schemas":["device-fallback-intent@1","device-fallback-intent@2"],"supported_pack_schemas":["offline-pack@1","offline-pack@2"],"query_kinds":KINDS,"filter_contract":"tire-query-filters@1","unicode_contract":"tire-query-unicode@1","continuous_policies":true,"max_filters":16,"max_policies":16,"max_sources":10,"max_pending_grants":16,"max_attempts_per_runtime":1024,"max_audit_receipts":64,"grant_ttl_seconds":300},"policies":state.policies.into_iter().filter(|p|p["profile_id"]==vault.profile_id&&p["owner_epoch"].as_u64()==Some(vault.owner_epoch)).collect::<Vec<_>>(),"package_bindings":bindings,"missing_package_bindings":missing}),
        )
    }
    fn fallback_clock_gate(&self, inner: &mut Inner) -> NativeResult<()> {
        let wall = Utc::now();
        let rollback = wall < inner.fallback.v2.last_wall;
        let mut state = self.fallback_policy_load(&inner.connection, &inner.key)?;
        let mut changed = false;
        for p in &mut state.policies {
            if p["state"] == "enabled"
                && (rollback
                    || utc(string(p, "expires_at")?)? <= wall
                    || utc(string(p, "updated_at")?)? > wall)
            {
                Self::pause_policy(
                    p,
                    if rollback {
                        "OFFLINE_FALLBACK_CLOCK_ROLLBACK"
                    } else {
                        "OFFLINE_FALLBACK_POLICY_EXPIRED"
                    },
                )?;
                changed = true;
            }
        }
        if changed {
            let tx = db(inner
                .connection
                .transaction_with_behavior(TransactionBehavior::Immediate))?;
            self.fallback_policy_save(&tx, &inner.key, &state)?;
            db(tx.commit())?;
            inner.fallback.v2.pending.clear();
            inner.fallback.v2.previews.clear();
        }
        inner.fallback.v2.last_wall = wall;
        Ok(())
    }
    pub fn fallback_policy_preview_v2(&self, request: Value, page: u64) -> NativeResult<Value> {
        keys(
            &request,
            &[
                "mode",
                "scope",
                "binding",
                "allow_same_scope_sync_binding_advance",
                "expected_profile_id",
                "expected_owner_epoch",
                "authority",
                "policy_id",
                "expected_policy_revision",
                "expires_in_seconds",
            ],
        )?;
        keys(
            &request["authority"],
            &["runtime_session_id", "authority_revision"],
        )?;
        let expiry = uint(&request, "expires_in_seconds")?;
        if !(900..=604800).contains(&expiry) {
            return Err(INVALID);
        }
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        self.fallback_clock_gate(&mut inner)?;
        self.fallback_page_check(page)?;
        let authority = self.authority_locked(&inner.connection, &inner.key, &inner.fallback.v2)?;
        if request["expected_profile_id"] != authority["profile_id"]
            || request["expected_owner_epoch"] != authority["owner_epoch"]
        {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        if request["authority"]["runtime_session_id"] != authority["runtime_session_id"]
            || request["authority"]["authority_revision"] != authority["authority_revision"]
        {
            return Err(AUTHORITY);
        }
        self.validate_choice(&request, Some(&authority))?;
        if !request["binding"].is_null() {
            let (_, metadata, slot) = self.binding_metadata(
                &inner.connection,
                &inner.key,
                &request["binding"],
                string(&authority, "profile_id")?,
                uint(&authority, "owner_epoch")?,
            )?;
            if slot.owner_scope_id != string(&authority, "owner_scope_id")?
                || serde_json::to_value(
                    metadata
                        .fallback_binding
                        .ok_or("OFFLINE_FALLBACK_SCOPE_METADATA_MISSING")?,
                )
                .map_err(|_| INVALID)?
                    != request["binding"]
            {
                return Err("OFFLINE_FALLBACK_BINDING_CHANGED");
            }
        }
        let state = self.fallback_policy_load(&inner.connection, &inner.key)?;
        let expected = uint(&request, "expected_policy_revision")?;
        if request["policy_id"].is_null() {
            if expected != 0
                || state
                    .policies
                    .iter()
                    .filter(|p| p["state"] != "revoked")
                    .count()
                    >= 16
            {
                return Err("OFFLINE_FALLBACK_CAPACITY");
            }
        } else {
            let id = string(&request, "policy_id")?;
            if !wire::uuid(id)
                || !state.policies.iter().any(|p| {
                    p["policy_id"] == id
                        && p["policy_revision"].as_u64() == Some(expected)
                        && p["profile_id"] == authority["profile_id"]
                        && p["owner_epoch"] == authority["owner_epoch"]
                })
            {
                return Err("OFFLINE_FALLBACK_POLICY_CHANGED");
            }
            if state
                .policies
                .iter()
                .any(|p| p["policy_id"] == id && p["state"] == "revoked")
                && state.nonrevoked() >= MAX_NONREVOKED_POLICIES
            {
                return Err("OFFLINE_FALLBACK_CAPACITY");
            }
        }
        inner.fallback.v2.previews.retain(|_, p| {
            p.page == page
                && p.issued.elapsed() < Duration::from_secs(300)
                && Utc::now() >= p.wall
                && Utc::now() < p.wall + chrono::Duration::seconds(300)
        });
        if inner.fallback.v2.previews.len() >= 16 {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let wall = Utc::now();
        let id = uuid::Uuid::new_v4().to_string();
        let proposed = json!({"mode":request["mode"],"scope":request["scope"],"binding":request["binding"],"allow_same_scope_sync_binding_advance":request["allow_same_scope_sync_binding_advance"]});
        let policy_expires = (wall + chrono::Duration::seconds(expiry as i64)).to_rfc3339();
        let fingerprint=crypto::hash(exact(&json!({"namespace":"device-fallback-policy-preview@1","request":request,"authority":authority,"policy_expires_at":policy_expires}))?.json().as_bytes());
        let response = json!({"schema":"device-fallback-policy-preview@1","preview_id":id,"fingerprint":fingerprint,"expires_at":(wall+chrono::Duration::seconds(300)).to_rfc3339(),"policy_expires_at":policy_expires,"expected_policy_revision":expected,"profile_id":authority["profile_id"],"owner_epoch":authority["owner_epoch"],"authority":authority,"proposed_policy":proposed,"notice":"仅授权所选设备包历史子集；未读取包业务内容，不证明当前官网权限、完整查询或 AI 授权。"});
        inner.fallback.v2.previews.insert(
            id,
            Preview {
                response: response.clone(),
                request,
                issued: Instant::now(),
                wall,
                page,
            },
        );
        Ok(response)
    }
    pub fn fallback_policy_apply_v2(&self, request: Value, page: u64) -> NativeResult<Value> {
        keys(
            &request,
            &[
                "preview_id",
                "expected_fingerprint",
                "expected_policy_revision",
                "allow_continuous_history_fallback",
            ],
        )?;
        if request["allow_continuous_history_fallback"] != true {
            return Err("OFFLINE_FALLBACK_CONSENT_REQUIRED");
        }
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        self.fallback_clock_gate(&mut inner)?;
        let preview = inner
            .fallback
            .v2
            .previews
            .remove(string(&request, "preview_id")?)
            .ok_or("OFFLINE_FALLBACK_PREVIEW_USED")?;
        self.fallback_page_check(page)?;
        if preview.page != page
            || preview.issued.elapsed() >= Duration::from_secs(300)
            || Utc::now() < preview.wall
            || Utc::now() >= preview.wall + chrono::Duration::seconds(300)
            || preview.response["fingerprint"] != request["expected_fingerprint"]
            || preview.response["expected_policy_revision"] != request["expected_policy_revision"]
        {
            return Err("OFFLINE_FALLBACK_PREVIEW_CHANGED");
        }
        let authority = self.authority_locked(&inner.connection, &inner.key, &inner.fallback.v2)?;
        let prior = &preview.response["authority"];
        if authority["profile_id"] != prior["profile_id"]
            || authority["owner_epoch"] != prior["owner_epoch"]
            || authority["runtime_session_id"] != prior["runtime_session_id"]
            || authority["authority_revision"] != prior["authority_revision"]
            || authority["owner_scope_id"] != prior["owner_scope_id"]
        {
            return Err(AUTHORITY);
        }
        self.validate_choice(&preview.request, Some(&authority))?;
        if !preview.request["binding"].is_null() {
            let (_, m, _) = self.binding_metadata(
                &inner.connection,
                &inner.key,
                &preview.request["binding"],
                string(&authority, "profile_id")?,
                uint(&authority, "owner_epoch")?,
            )?;
            if serde_json::to_value(
                m.fallback_binding
                    .ok_or("OFFLINE_FALLBACK_SCOPE_METADATA_MISSING")?,
            )
            .map_err(|_| INVALID)?
                != preview.request["binding"]
            {
                return Err("OFFLINE_FALLBACK_BINDING_CHANGED");
            }
        }
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut state = self.fallback_policy_load(&tx, key)?;
        let expected = uint(&request, "expected_policy_revision")?;
        let requested_id = preview.request["policy_id"].as_str();
        let next_revision = expected
            .checked_add(1)
            .filter(|v| *v < SAFE_INTEGER)
            .ok_or(INVALID)?;
        let index = if let Some(id) = requested_id {
            Some(
                state
                    .policies
                    .iter()
                    .position(|p| {
                        p["policy_id"] == id
                            && p["policy_revision"].as_u64() == Some(expected)
                            && p["profile_id"] == authority["profile_id"]
                            && p["owner_epoch"] == authority["owner_epoch"]
                    })
                    .ok_or("OFFLINE_FALLBACK_POLICY_CHANGED")?,
            )
        } else {
            if expected != 0
                || state
                    .policies
                    .iter()
                    .filter(|p| p["state"] != "revoked")
                    .count()
                    >= 16
            {
                return Err("OFFLINE_FALLBACK_CAPACITY");
            }
            None
        };
        if index.is_some_and(|index| state.policies[index]["state"] == "revoked")
            && state.nonrevoked() >= MAX_NONREVOKED_POLICIES
        {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let id = requested_id
            .map(str::to_owned)
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        let mut policy = preview.response["proposed_policy"].clone();
        let p = policy.as_object_mut().ok_or(INVALID)?;
        for (key,value) in json!({"schema":"device-fallback-policy@1","policy_id":id,"policy_revision":next_revision,"state":"enabled","profile_id":authority["profile_id"],"owner_epoch":authority["owner_epoch"],"owner_scope_id":authority["owner_scope_id"],"runtime_session_id":if preview.request["scope"]["kind"]=="session" {authority["runtime_session_id"].clone()}else{Value::Null},"approved_at":Utc::now().to_rfc3339(),"updated_at":Utc::now().to_rfc3339(),"expires_at":preview.response["policy_expires_at"],"fingerprint":preview.response["fingerprint"],"reason":null}).as_object().unwrap() {p.insert(key.clone(),value.clone());}
        if let Some(index) = index {
            state.policies[index] = policy.clone();
        } else {
            state.policies.push(policy.clone());
        }
        state
            .permission_observations
            .insert(id, Self::permission_snapshot(&policy["scope"], &authority));
        state.compact()?;
        self.fallback_policy_save(&tx, key, &state)?;
        self.fallback_page_check(page)?;
        db(tx.commit())?;
        // Changed consent removes all pending versions conservatively. Attempt
        // tombstones remain, so a revoked receipt cannot be downgraded/reissued.
        if policy["mode"] == "never" {
            fallback.pending.retain(|_, p| {
                !matches(
                    &policy,
                    &p.receipt.intent.source_id,
                    p.receipt.intent.source_access_generation,
                    "tire",
                    true,
                )
            });
        }
        fallback.v2.pending.clear();
        Ok(policy)
    }
    pub fn fallback_policy_change_v2(&self, request: Value, revoke: bool) -> NativeResult<Value> {
        keys(&request, &["policy_id", "expected_policy_revision"])?;
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let vault = self.vault(&tx, key)?;
        let mut state = self.fallback_policy_load(&tx, key)?;
        let p = state
            .policies
            .iter_mut()
            .find(|p| {
                p["policy_id"] == request["policy_id"]
                    && p["policy_revision"] == request["expected_policy_revision"]
                    && p["profile_id"] == vault.profile_id
                    && p["owner_epoch"].as_u64() == Some(vault.owner_epoch)
                    && p["state"] != "revoked"
            })
            .ok_or("OFFLINE_FALLBACK_POLICY_CHANGED")?;
        Self::pause_policy(
            p,
            if revoke {
                "OFFLINE_FALLBACK_POLICY_REVOKED"
            } else {
                "OFFLINE_FALLBACK_POLICY_PAUSED"
            },
        )?;
        if revoke {
            p["state"] = json!("revoked");
        }
        let result = p.clone();
        self.fallback_policy_save(&tx, key, &state)?;
        db(tx.commit())?;
        fallback.v2.pending.clear();
        Ok(result)
    }
    fn v2_audit(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        receipt: &Exact,
    ) -> NativeResult<()> {
        let next: i64 = db(connection.query_row(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM fallback_audit",
            [],
            |r| r.get(0),
        ))?;
        if next <= 0 {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let clear = Zeroizing::new(receipt.json().into_bytes());
        if clear.len() > MAX_METADATA_BYTES {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let encoded = crypto::seal(
            key,
            format!("offline-v1:{}:fallback-audit:{next}", self.namespace).as_bytes(),
            &clear,
        )?;
        db(connection.execute(
            "INSERT INTO fallback_audit(sequence,value) VALUES(?1,?2)",
            params![next, encoded],
        ))?;
        db(connection.execute("DELETE FROM fallback_audit WHERE sequence NOT IN (SELECT sequence FROM fallback_audit ORDER BY sequence DESC LIMIT ?1)",[MAX_AUDIT]))?;
        Ok(())
    }
    fn v2_grant_binding(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        receipt: &Exact,
        intent: &Intent,
        memory: &Memory,
    ) -> NativeResult<(Row, Metadata, Slot)> {
        Self::formal_query_gate(memory, &intent.value["failure"])?;
        let grant = receipt.package_mirror();
        let authority = self.authority_locked(connection, key, memory)?;
        self.intent_authorized(intent, &authority, true)?;
        if intent.value["fallback_policy"] == "never" {
            return Err("OFFLINE_FALLBACK_NEVER");
        }
        let state = self.fallback_policy_load(connection, key)?;
        if state.policies.iter().any(|p| {
            enabled(p)
                && p["profile_id"] == authority["profile_id"]
                && p["owner_epoch"] == authority["owner_epoch"]
                && p["mode"] == "never"
                && matches(
                    p,
                    intent.source(),
                    intent.generation(),
                    intent.kind(),
                    false,
                )
        }) {
            return Err("OFFLINE_FALLBACK_NEVER");
        }
        let binding = json!({"slot_id":grant["slot_id"],"generation":grant["generation"],"sha256":grant["package_sha256"]});
        let found = self.binding_metadata(
            connection,
            key,
            &binding,
            string(&grant, "profile_id")?,
            uint(&grant, "owner_epoch")?,
        )?;
        if found.2.owner_scope_id != string(&authority, "owner_scope_id")? {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        let authorization = &grant["fallback_authorization"];
        if authorization["type"] == "policy_once" {
            let policy = state
                .policies
                .iter()
                .find(|p| {
                    p["policy_id"] == authorization["policy_id"]
                        && p["policy_revision"] == authorization["policy_revision"]
                        && enabled(p)
                })
                .ok_or("OFFLINE_FALLBACK_POLICY_CHANGED")?;
            if !matches!(
                string(policy, "mode")?,
                "session_allow" | "source_allow" | "query_allow"
            ) || policy["profile_id"] != authority["profile_id"]
                || policy["owner_epoch"] != authority["owner_epoch"]
                || policy["owner_scope_id"] != authority["owner_scope_id"]
                || (policy["mode"] == "session_allow"
                    && policy["runtime_session_id"] != authority["runtime_session_id"])
                || !matches(
                    policy,
                    intent.source(),
                    intent.generation(),
                    intent.kind(),
                    false,
                )
                || serde_json::to_value(
                    found
                        .1
                        .fallback_binding
                        .as_ref()
                        .ok_or("OFFLINE_FALLBACK_SCOPE_METADATA_MISSING")?,
                )
                .map_err(|_| INVALID)?
                    != policy["binding"]
            {
                return Err("OFFLINE_FALLBACK_POLICY_CHANGED");
            }
            if state.policies.iter().any(|p| {
                enabled(p)
                    && p["profile_id"] == authority["profile_id"]
                    && p["owner_epoch"] == authority["owner_epoch"]
                    && p["mode"] == "ask"
                    && matches(
                        p,
                        intent.source(),
                        intent.generation(),
                        intent.kind(),
                        false,
                    )
            }) {
                return Err("OFFLINE_FALLBACK_ASK");
            }
        }
        Ok(found)
    }
    fn v2_issue(&self, core: Exact, page: u64, authorize: bool) -> NativeResult<Value> {
        let request = core.package_mirror();
        let mut expected = vec![
            "intent",
            "slot_id",
            "expected_generation",
            "expected_sha256",
            "expected_profile_id",
            "expected_owner_epoch",
        ];
        if !authorize {
            expected.push("decision");
        }
        keys(&request, &expected)?;
        let intent = Intent::parse(get(&core, "intent")?.clone())?;
        if !wire::uuid(string(&request, "slot_id")?)
            || !wire::hex(string(&request, "expected_sha256")?)
            || !wire::uuid(string(&request, "expected_profile_id")?)
            || uint(&request, "expected_generation")? == 0
        {
            return Err(INVALID);
        }
        uint(&request, "expected_owner_epoch")?;
        let decision = if authorize {
            "allow"
        } else {
            string(&request, "decision")?
        };
        if !matches!(decision, "allow" | "deny") {
            return Err(INVALID);
        }
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        self.fallback_clock_gate(&mut inner)?;
        self.fallback_page_check(page)?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        if fallback.attempts.contains(intent.id()) {
            return Err("OFFLINE_FALLBACK_USED");
        }
        if fallback.attempts.len() >= MAX_ATTEMPTS {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        if let Err(error) = Self::formal_query_gate(&fallback.v2, &intent.value["failure"]) {
            fallback.attempts.insert(intent.id().into());
            return if authorize {
                raw::encode_transport(&exact(
                    &json!({"schema":"device-fallback-authorization@1","state":"blocked","reason":error,"grant":null}),
                )?)
            } else {
                Err(error)
            };
        }
        if intent.value["fallback_policy"] == "never" {
            fallback.attempts.insert(intent.id().into());
            return if authorize {
                raw::encode_transport(&exact(
                    &json!({"schema":"device-fallback-authorization@1","state":"blocked","reason":"OFFLINE_FALLBACK_NEVER","grant":null}),
                )?)
            } else {
                Err("OFFLINE_FALLBACK_NEVER")
            };
        }
        let authority = self.authority_locked(connection, key, &fallback.v2)?;
        self.intent_authorized(&intent, &authority, false)?;
        if request["expected_profile_id"] != authority["profile_id"]
            || request["expected_owner_epoch"] != authority["owner_epoch"]
        {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        let state = self.fallback_policy_load(connection, key)?;
        let policies = state
            .policies
            .iter()
            .filter(|p| {
                enabled(p)
                    && p["profile_id"] == authority["profile_id"]
                    && p["owner_epoch"] == authority["owner_epoch"]
                    && p["owner_scope_id"] == authority["owner_scope_id"]
                    && matches(
                        p,
                        intent.source(),
                        intent.generation(),
                        intent.kind(),
                        false,
                    )
            })
            .collect::<Vec<_>>();
        let never = intent.value["fallback_policy"] == "never"
            || policies.iter().any(|p| p["mode"] == "never");
        if never {
            fallback.attempts.insert(intent.id().into());
            return if authorize {
                raw::encode_transport(&exact(
                    &json!({"schema":"device-fallback-authorization@1","state":"blocked","reason":"OFFLINE_FALLBACK_NEVER","grant":null}),
                )?)
            } else {
                Err("OFFLINE_FALLBACK_NEVER")
            };
        }
        self.intent_authorized(&intent, &authority, true)?;
        let mut authorization = json!({"type":"explicit_once"});
        if authorize {
            if policies.iter().any(|p| p["mode"] == "ask") {
                return raw::encode_transport(&exact(
                    &json!({"schema":"device-fallback-authorization@1","state":"ask","reason":"OFFLINE_FALLBACK_EXPLICIT_ONCE_REQUIRED","grant":null}),
                )?);
            }
            let mut allowed = policies
                .into_iter()
                .filter(|p| {
                    matches!(
                        p["mode"].as_str(),
                        Some("query_allow" | "source_allow" | "session_allow")
                    ) && (p["mode"] != "session_allow"
                        || p["runtime_session_id"] == authority["runtime_session_id"])
                        && p["binding"]["slot_id"] == request["slot_id"]
                        && p["binding"]["generation"] == request["expected_generation"]
                        && p["binding"]["sha256"] == request["expected_sha256"]
                })
                .collect::<Vec<_>>();
            allowed.sort_by(|a, b| {
                let priority = |p: &Value| match p["mode"].as_str() {
                    Some("query_allow") => 3,
                    Some("source_allow") => 2,
                    _ => 1,
                };
                priority(b)
                    .cmp(&priority(a))
                    .then_with(|| b["approved_at"].as_str().cmp(&a["approved_at"].as_str()))
                    .then_with(|| a["policy_id"].as_str().cmp(&b["policy_id"].as_str()))
            });
            let Some(policy) = allowed.first() else {
                return raw::encode_transport(&exact(
                    &json!({"schema":"device-fallback-authorization@1","state":"ask","reason":"OFFLINE_FALLBACK_EXPLICIT_ONCE_REQUIRED","grant":null}),
                )?);
            };
            authorization = json!({"type":"policy_once","policy_id":policy["policy_id"],"policy_revision":policy["policy_revision"]});
        }
        fallback
            .v2
            .pending
            .retain(|_, p| p.page == page && !p.expired());
        fallback
            .pending
            .retain(|_, p| p.page == page && !p.expired());
        if decision == "allow" && fallback.v2.pending.len() + fallback.pending.len() >= MAX_PENDING
        {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let wall = Utc::now();
        let id = uuid::Uuid::new_v4().to_string();
        let mut receipt = exact(
            &json!({"schema":"device-fallback-grant@2","id":id,"scope":"local_once","state":if decision=="allow"{"allowed"}else{"denied"},"fallback_authorization":authorization,"intent":null,"profile_id":request["expected_profile_id"],"owner_epoch":request["expected_owner_epoch"],"slot_id":request["slot_id"],"generation":request["expected_generation"],"package_sha256":request["expected_sha256"],"decided_at":wall.to_rfc3339(),"expires_at":(wall+chrono::Duration::seconds(300)).to_rfc3339(),"consumed_at":null}),
        )?;
        set(&mut receipt, "intent", intent.raw.clone())?;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        self.v2_grant_binding(&tx, key, &receipt, &intent, &fallback.v2)?;
        self.v2_audit(&tx, key, &receipt)?;
        self.fallback_page_check(page)?;
        db(tx.commit())?;
        fallback.attempts.insert(intent.id().into());
        if decision == "allow" {
            fallback.v2.pending.insert(
                id,
                PendingV2 {
                    receipt: receipt.clone(),
                    intent,
                    issued: Instant::now(),
                    wall,
                    page,
                },
            );
        }
        if authorize {
            let mut output = exact(
                &json!({"schema":"device-fallback-authorization@1","state":"allowed","reason":null,"grant":null}),
            )?;
            set(&mut output, "grant", receipt)?;
            raw::encode_transport(&output)
        } else {
            raw::encode_transport(&receipt)
        }
    }
    pub fn decide_fallback_v2(&self, outer: Value, page: u64) -> NativeResult<Value> {
        self.v2_issue(raw::decode_transport(outer)?, page, false)
    }
    pub fn authorize_fallback_v2(&self, outer: Value, page: u64) -> NativeResult<Value> {
        self.v2_issue(raw::decode_transport(outer)?, page, true)
    }
    pub fn consume_fallback_v2(&self, outer: Value, page: u64) -> NativeResult<Value> {
        let core = raw::decode_transport(outer)?;
        let request = core.package_mirror();
        keys(&request, &["grant_id", "intent"])?;
        let id = string(&request, "grant_id")?;
        if !wire::uuid(id) {
            return Err(INVALID);
        }
        let mut inner = self.lock()?;
        // Claim precedes semantic checks and any package validation/read. A
        // malformed or mismatched intent still leaves this receipt terminal.
        let pending = inner
            .fallback
            .v2
            .pending
            .remove(id)
            .ok_or("OFFLINE_FALLBACK_USED")?;
        let _profile = self.fallback_profile_lock()?;
        self.fallback_clock_gate(&mut inner)?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        let mut receipt = pending.receipt.clone();
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let preflight = (|| {
            self.fallback_page_check(page)?;
            if page != pending.page {
                return Err("OFFLINE_FALLBACK_USED");
            }
            if pending.expired() {
                return Err("OFFLINE_FALLBACK_EXPIRED");
            }
            let supplied = Intent::parse(get(&core, "intent")?.clone())?;
            if supplied.raw != pending.intent.raw {
                return Err("OFFLINE_FALLBACK_MISMATCH");
            }
            self.v2_grant_binding(&tx, key, &receipt, &pending.intent, &fallback.v2)
                .map(|_| ())
        })();
        set(
            &mut receipt,
            "state",
            Exact::Text(
                if preflight.is_ok() {
                    "consumed"
                } else {
                    "revoked"
                }
                .into(),
            ),
        )?;
        if preflight.is_ok() {
            set(
                &mut receipt,
                "consumed_at",
                Exact::Text(Utc::now().to_rfc3339()),
            )?;
        }
        self.v2_audit(&tx, key, &receipt)?;
        db(tx.commit())?;
        preflight?;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let (row, metadata, slot) =
            self.v2_grant_binding(&tx, key, &receipt, &pending.intent, &fallback.v2)?;
        self.release_gate(&tx, key, &slot)?;
        let path = self.root.join(format!(
            "{}.pack",
            row.file_id.as_deref().ok_or("OFFLINE_CORRUPT")?
        ));
        let facts = io(fs::symlink_metadata(&path))?;
        if !facts.is_file()
            || facts.file_type().is_symlink()
            || facts.len() > (MAX_PACKAGE_BYTES + crypto::OVERHEAD) as u64
        {
            return Err("OFFLINE_CORRUPT");
        }
        let mut sealed = Vec::new();
        io(File::open(path))?
            .take((MAX_PACKAGE_BYTES + crypto::OVERHEAD + 1) as u64)
            .read_to_end(&mut sealed)
            .map_err(|_| "OFFLINE_STORE_FAILED")?;
        let clear = crypto::open(
            key,
            self.package_aad(&row.id, row.generation, metadata.installed_epoch)
                .as_bytes(),
            &sealed,
            MAX_PACKAGE_BYTES,
        )
        .map_err(|_| "OFFLINE_CORRUPT")?;
        let envelope =
            wire::package(&clear, &metadata.descriptor).map_err(|_| "OFFLINE_CORRUPT")?;
        let package = Exact::parse(std::str::from_utf8(&clear).map_err(|_| "OFFLINE_CORRUPT")?)?;
        let originals = get(&package, "members")?.array()?;
        let mut members = Vec::new();
        let mut citations = Vec::new();
        let mut source_count = 0u64;
        let mut matched = 0u64;
        let mut excluded = 0u64;
        let mut undetermined = 0u64;
        for (member, original) in envelope.members.iter().zip(originals) {
            if member.source.source_id.as_deref() != Some(pending.intent.source()) {
                continue;
            }
            let kind = match member.reference.kind() {
                "tire" => MemberKind::Tire,
                "vehicle" => MemberKind::Vehicle,
                "recall" => MemberKind::Recall,
                "recall_search" => MemberKind::RecallSearch,
                _ => continue,
            };
            if (pending.intent.kind() == "tire" && kind != MemberKind::Tire)
                || (pending.intent.kind() == "vehicle_fitments" && kind != MemberKind::Vehicle)
                || (pending.intent.kind() == "recall_campaign" && kind != MemberKind::Recall)
                || (pending.intent.kind() == "recall_search" && kind != MemberKind::RecallSearch)
            {
                continue;
            }
            let payload = get(original, "payload")?;
            let truth = if kind == MemberKind::RecallSearch {
                pending.intent.criteria.matches_frozen_search_page_json(
                    member.source.source_id.as_deref(),
                    &get(payload, "query")?.json(),
                    &get(payload, "discovery")?.json(),
                )?
            } else {
                pending.intent.criteria.matches_payload_json(
                    kind,
                    member.source.source_id.as_deref(),
                    &payload.json(),
                )?
            };
            if pending.intent.kind() == "tire" {
                source_count += 1;
                match truth {
                    Truth::True => matched += 1,
                    Truth::False => excluded += 1,
                    Truth::Unknown => undetermined += 1,
                };
            }
            if truth != Truth::True {
                continue;
            }
            members.push(original.clone());
            let documents = envelope
                .documents
                .iter()
                .filter(|d| d.member_key.as_deref() == Some(&member.key))
                .collect::<Vec<_>>();
            let verification = match &member.reference {
                wire::Reference::Tire {
                    verification_id, ..
                }
                | wire::Reference::Vehicle {
                    verification_id, ..
                }
                | wire::Reference::Recall {
                    verification_id, ..
                } => verification_id.clone(),
                wire::Reference::RecallSearch {
                    verification_id, ..
                } => Some(verification_id.clone()),
                _ => None,
            };
            let docs = if documents.is_empty() {
                vec![None]
            } else {
                documents.into_iter().map(Some).collect()
            };
            for document in docs {
                let doc_id = document.map(|d| d.id.clone());
                let record = document.and_then(|d| d.record_index);
                let citation_id = crypto::hash(
                    format!(
                        "device-citation@1\0{}\0{}\0{}\0{}\0{}\0{}\0{}",
                        receipt.package_mirror()["profile_id"],
                        receipt.package_mirror()["owner_epoch"],
                        slot.slot_id,
                        slot.generation,
                        slot.sha256,
                        member.key,
                        doc_id.as_deref().unwrap_or("")
                    )
                    .as_bytes(),
                );
                citations.push(json!({"schema":"device-citation@1","id":format!("device:{citation_id}"),"profile_id":request_profile(&receipt)?,"owner_epoch":receipt.package_mirror()["owner_epoch"],"slot_id":slot.slot_id,"generation":slot.generation,"package_sha256":slot.sha256,"member_key":member.key,"document_id":doc_id,"record_index":record,"observed_at":member.source.observed_at,"verified_at":member.source.verified_at,"verification_id":verification}));
            }
        }
        let mut result = exact(
            &json!({"schema":"device-fallback-result@2","data_state":"local_snapshot","fallback_consent":"local_once","fallback_authorization":receipt.package_mirror()["fallback_authorization"],"grant":null,"slot":slot,"package_schema":envelope.schema,"citations":citations,"complete_query_result":false,"notice":"所选设备包历史观察子集；不是官网完整当前查询或唯一 SKU 计数，空页不证明无召回，也不构成 AI 授权。","query_kind":pending.intent.kind(),"query":pending.intent.value["query"],"selection":if pending.intent.kind()=="tire" {json!({"filters":[],"source_count":source_count,"matched_count":matched,"excluded_count":excluded,"undetermined_count":undetermined})}else{Value::Null},"members":[]}),
        )?;
        set(&mut result, "grant", receipt.clone())?;
        set(&mut result, "members", Exact::Array(members))?;
        if pending.intent.kind() == "tire" {
            let mut selection = get(&result, "selection")?.clone();
            set(
                &mut selection,
                "filters",
                get(&pending.intent.raw, "filters")?.clone(),
            )?;
            set(&mut result, "selection", selection)?;
        }
        if pending.expired() {
            return Err("OFFLINE_FALLBACK_EXPIRED");
        }
        self.fallback_page_check(page)?;
        self.v2_grant_binding(&tx, key, &receipt, &pending.intent, &fallback.v2)?;
        let output = raw::encode_transport(&result)?;
        db(tx.commit())?;
        self.fallback_page_check(page)?;
        if pending.expired() {
            return Err("OFFLINE_FALLBACK_EXPIRED");
        }
        Ok(output)
    }
    pub fn revoke_fallback_v2_if_known(
        &self,
        request: &FallbackRevokeRequest,
    ) -> NativeResult<bool> {
        let mut inner = self.lock()?;
        let Some(pending) = inner.fallback.v2.pending.remove(&request.grant_id) else {
            return Ok(false);
        };
        let _profile = self.fallback_profile_lock()?;
        let mut receipt = pending.receipt;
        set(&mut receipt, "state", Exact::Text("revoked".into()))?;
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        self.v2_audit(&tx, key, &receipt)?;
        db(tx.commit())?;
        Ok(true)
    }
}
fn request_profile(receipt: &Exact) -> NativeResult<String> {
    Ok(get(receipt, "profile_id")?.text()?.into())
}
#[cfg(test)]
mod tests;
