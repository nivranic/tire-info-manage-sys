//! Caller-observed failure consent, not proof that a native upstream request failed.
//! Only this path projects device history; ordinary history reads stay independent.
use super::*;
use chrono::{DateTime, Utc};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::atomic::Ordering;
use std::time::Instant;

const TTL_SECONDS: i64 = 300;
const MAX_PENDING: usize = 16;
const MAX_ATTEMPTS: usize = 1024;
const MAX_AUDIT: i64 = 64;

fn nullable<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::deserialize(deserializer)
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FallbackQuery {
    pub model: String,
    #[serde(deserialize_with = "nullable")]
    pub size: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FallbackFailure {
    pub scope: String,
    pub reason: String,
    #[serde(deserialize_with = "nullable")]
    pub query_id: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FallbackIntent {
    pub schema: String,
    pub attempt_id: String,
    pub query_fingerprint: String,
    pub source_id: String,
    pub source_access_generation: u64,
    pub query: FallbackQuery,
    pub filters: Vec<Value>,
    pub failure: FallbackFailure,
}
fn hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
fn text(value: &str, maximum: usize) -> bool {
    !value.trim().is_empty()
        && value.chars().count() <= maximum
        && !value.chars().any(char::is_control)
}
impl FallbackIntent {
    pub fn validate(&self) -> NativeResult<()> {
        if self.schema != "device-fallback-intent@1"
            || !wire::uuid(&self.attempt_id)
            || !hash(&self.query_fingerprint)
            || self.source_access_generation > SAFE_INTEGER
            || self.source_id.is_empty()
            || self.source_id.len() > 80
            || !self
                .source_id
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
            || !text(&self.query.model, 200)
            || self
                .query
                .size
                .as_deref()
                .is_some_and(|size| !text(size, 80))
        {
            return Err("OFFLINE_FALLBACK_INVALID");
        }
        if !self.filters.is_empty() {
            return Err("OFFLINE_FALLBACK_UNSUPPORTED");
        }
        let valid_failure = match self.failure.scope.as_str() {
            "api_transport" => {
                self.failure.query_id.is_none()
                    && matches!(
                        self.failure.reason.as_str(),
                        "api_network_unavailable" | "api_timeout"
                    )
            }
            "source_response" => {
                self.failure.query_id.as_deref().is_some_and(wire::uuid)
                    && matches!(
                        self.failure.reason.as_str(),
                        "upstream_timeout" | "upstream_network_error"
                    )
            }
            _ => false,
        };
        if !valid_failure {
            return Err("OFFLINE_FALLBACK_INVALID");
        }
        Ok(())
    }
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FallbackDecideRequest {
    pub intent: FallbackIntent,
    pub slot_id: String,
    pub expected_generation: u64,
    pub expected_sha256: String,
    pub expected_profile_id: String,
    pub expected_owner_epoch: u64,
    pub decision: String,
}
impl FallbackDecideRequest {
    fn validate(&self) -> NativeResult<()> {
        self.intent.validate()?;
        if !wire::uuid(&self.slot_id)
            || !(1..=SAFE_INTEGER).contains(&self.expected_generation)
            || !hash(&self.expected_sha256)
            || !text(&self.expected_profile_id, 80)
            || self.expected_owner_epoch > SAFE_INTEGER
            || !matches!(self.decision.as_str(), "allow" | "deny")
        {
            return Err("OFFLINE_FALLBACK_INVALID");
        }
        Ok(())
    }
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FallbackConsumeRequest {
    pub grant_id: String,
    pub intent: FallbackIntent,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FallbackRevokeRequest {
    pub grant_id: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FallbackGrant {
    pub schema: String,
    pub id: String,
    pub scope: String,
    pub state: String,
    pub intent: FallbackIntent,
    pub profile_id: String,
    pub owner_epoch: u64,
    pub slot_id: String,
    pub generation: u64,
    pub package_sha256: String,
    pub decided_at: String,
    pub expires_at: String,
    pub consumed_at: Option<String>,
}
#[derive(Serialize)]
pub struct FallbackResult {
    pub schema: &'static str,
    pub data_state: &'static str,
    pub fallback_consent: &'static str,
    pub grant: FallbackGrant,
    pub slot: Slot,
    pub members: Vec<Member>,
    pub complete_query_result: bool,
    pub notice: &'static str,
}
#[derive(Serialize)]
pub struct FallbackRevokeResult {
    pub revoked: bool,
    pub grant_id: String,
}
pub(super) struct Pending {
    receipt: FallbackGrant,
    issued: Instant,
    wall: DateTime<Utc>,
    page: u64,
}
impl Pending {
    fn expired(&self) -> bool {
        let now = Utc::now();
        now < self.wall
            || now >= self.wall + chrono::Duration::seconds(TTL_SECONDS)
            || self.issued.elapsed() >= Duration::from_secs(TTL_SECONDS as u64)
    }
}
#[derive(Default)]
pub(super) struct Memory {
    pub(super) pending: HashMap<String, Pending>,
    attempts: HashSet<String>,
    pub(super) v2: v2::Memory,
}

impl Store {
    pub fn fallback_page_id(&self) -> u64 {
        self.fallback_page.load(Ordering::SeqCst)
    }
    pub fn invalidate_fallback_page(&self) {
        self.fallback_page.fetch_add(1, Ordering::SeqCst);
    }
    fn fallback_page_check(&self, page: u64) -> NativeResult<()> {
        if page != self.fallback_page_id() {
            Err("OFFLINE_FALLBACK_USED")
        } else {
            Ok(())
        }
    }
    fn fallback_binding(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        grant: &FallbackGrant,
    ) -> NativeResult<(Row, Metadata, Slot)> {
        let vault = self.vault(connection, key)?;
        if vault.profile_id != grant.profile_id || vault.owner_epoch != grant.owner_epoch {
            return Err("OFFLINE_FALLBACK_MISMATCH");
        }
        let row = Self::row(connection, &grant.slot_id)?
            .filter(|row| row.file_id.is_some())
            .ok_or("OFFLINE_STALE_GENERATION")?;
        if row.generation != grant.generation {
            return Err("OFFLINE_STALE_GENERATION");
        }
        let metadata = self.metadata(&row, key)?;
        let slot = Self::public_slot(&metadata, vault.owner_epoch);
        if slot.locked || slot.previous_owner {
            return Err("OFFLINE_OWNER_LOCKED");
        }
        if slot.sha256 != grant.package_sha256 {
            return Err("OFFLINE_FALLBACK_MISMATCH");
        }
        Ok((row, metadata, slot))
    }
    fn fallback_audit(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        grant: &FallbackGrant,
    ) -> NativeResult<()> {
        let next: i64 = db(connection.query_row(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM fallback_audit",
            [],
            |row| row.get(0),
        ))?;
        if next <= 0 {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let clear =
            Zeroizing::new(serde_json::to_vec(grant).map_err(|_| "OFFLINE_FALLBACK_INVALID")?);
        if clear.len() > MAX_METADATA_BYTES {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let encrypted = crypto::seal(
            key,
            format!("offline-v1:{}:fallback-audit:{next}", self.namespace).as_bytes(),
            &clear,
        )?;
        db(connection.execute(
            "INSERT INTO fallback_audit(sequence,value) VALUES(?1,?2)",
            params![next, encrypted],
        ))?;
        db(connection.execute("DELETE FROM fallback_audit WHERE sequence NOT IN (SELECT sequence FROM fallback_audit ORDER BY sequence DESC LIMIT ?1)", [MAX_AUDIT]))?;
        Ok(())
    }
    pub fn decide_fallback(
        &self,
        request: FallbackDecideRequest,
        page: u64,
    ) -> NativeResult<FallbackGrant> {
        request.validate()?;
        let _profile_lock = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        self.fallback_page_check(page)?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        if fallback.attempts.contains(&request.intent.attempt_id) {
            return Err("OFFLINE_FALLBACK_USED");
        }
        if let Err(error) = Self::legacy_formal_query_gate(&fallback.v2, &request.intent) {
            if fallback.attempts.len() < MAX_ATTEMPTS {
                fallback.attempts.insert(request.intent.attempt_id.clone());
            }
            return Err(error);
        }
        fallback
            .pending
            .retain(|_, pending| pending.page == page && !pending.expired());
        let v2_pending = Self::v2_pending_count(fallback, page);
        if fallback.attempts.len() >= MAX_ATTEMPTS
            || (request.decision == "allow" && fallback.pending.len() + v2_pending >= MAX_PENDING)
        {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        let issued = Instant::now();
        let wall = Utc::now();
        let grant = FallbackGrant {
            schema: "device-fallback-grant@1".into(),
            id: uuid::Uuid::new_v4().to_string(),
            scope: "local_once".into(),
            state: if request.decision == "allow" {
                "allowed"
            } else {
                "denied"
            }
            .into(),
            intent: request.intent,
            profile_id: request.expected_profile_id,
            owner_epoch: request.expected_owner_epoch,
            slot_id: request.slot_id,
            generation: request.expected_generation,
            package_sha256: request.expected_sha256,
            decided_at: wall.to_rfc3339(),
            expires_at: (wall + chrono::Duration::seconds(TTL_SECONDS)).to_rfc3339(),
            consumed_at: None,
        };
        let transaction = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        if let Err(error) = self.legacy_never_gate(&transaction, key, &grant.intent) {
            fallback.attempts.insert(grant.intent.attempt_id.clone());
            return Err(error);
        }
        self.fallback_binding(&transaction, key, &grant)?;
        self.fallback_audit(&transaction, key, &grant)?;
        self.fallback_page_check(page)?;
        db(transaction.commit())?;
        fallback.attempts.insert(grant.intent.attempt_id.clone());
        if grant.state == "allowed" {
            fallback.pending.insert(
                grant.id.clone(),
                Pending {
                    receipt: grant.clone(),
                    issued,
                    wall,
                    page,
                },
            );
        }
        Ok(grant)
    }
    pub fn consume_fallback(
        &self,
        request: FallbackConsumeRequest,
        page: u64,
    ) -> NativeResult<FallbackResult> {
        if !wire::uuid(&request.grant_id) {
            return Err("OFFLINE_FALLBACK_INVALID");
        }
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        // Removal precedes intent/binding checks, SQLite access and package I/O.
        // Every subsequent failure leaves this grant terminal in this process.
        let pending = fallback
            .pending
            .remove(&request.grant_id)
            .ok_or("OFFLINE_FALLBACK_USED")?;
        let mut grant = pending.receipt.clone();
        let _profile_lock = self.fallback_profile_lock()?;
        let transaction = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let preflight = (|| {
            self.fallback_page_check(page)?;
            if page != pending.page {
                return Err("OFFLINE_FALLBACK_USED");
            }
            if pending.expired() {
                return Err("OFFLINE_FALLBACK_EXPIRED");
            }
            request.intent.validate()?;
            if request.intent != grant.intent {
                return Err("OFFLINE_FALLBACK_MISMATCH");
            }
            Self::legacy_formal_query_gate(&fallback.v2, &grant.intent)?;
            self.legacy_never_gate(&transaction, key, &grant.intent)?;
            self.fallback_binding(&transaction, key, &grant).map(|_| ())
        })();
        grant.state = if preflight.is_ok() {
            "consumed"
        } else {
            "revoked"
        }
        .into();
        if preflight.is_ok() {
            grant.consumed_at = Some(Utc::now().to_rfc3339());
        }
        self.fallback_audit(&transaction, key, &grant)?;
        db(transaction.commit())?;
        preflight?;
        // The durable consumed receipt precedes all package-body access. The
        // shared process/file locks continue across this commit; the new SQLite
        // transaction also holds the owner/slot version stable during the read.
        let transaction = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let outcome = (|| {
            self.fallback_page_check(page)?;
            if pending.expired() {
                return Err("OFFLINE_FALLBACK_EXPIRED");
            }
            let (row, metadata, slot) = self.fallback_binding(&transaction, key, &grant)?;
            Self::legacy_formal_query_gate(&fallback.v2, &grant.intent)?;
            self.legacy_never_gate(&transaction, key, &grant.intent)?;
            // @1 has no exact numeric carrier. This metadata gate runs after
            // the durable consumed audit and before all business-body reads.
            if metadata.descriptor.schema != "offline-pack-descriptor@1" {
                return Err("OFFLINE_FALLBACK_UNSUPPORTED");
            }
            self.release_gate(&transaction, key, &slot)?;
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
            let members = envelope
                .members
                .into_iter()
                .filter(|member| {
                    member.reference.kind() == "tire"
                        && member.source.source_id.as_deref()
                            == Some(grant.intent.source_id.as_str())
                        && member.payload.get("variant").is_some_and(|variant| {
                            variant.get("model").and_then(Value::as_str)
                                == Some(grant.intent.query.model.as_str())
                                && grant.intent.query.size.as_deref().is_none_or(|size| {
                                    variant.get("size").and_then(Value::as_str) == Some(size)
                                })
                        })
                })
                .collect();
            if pending.expired() {
                return Err("OFFLINE_FALLBACK_EXPIRED");
            }
            self.fallback_page_check(page)?;
            Self::legacy_formal_query_gate(&fallback.v2, &grant.intent)?;
            self.legacy_never_gate(&transaction, key, &grant.intent)?;
            Ok((slot, members))
        })();
        db(transaction.commit())?;
        let (slot, members) = outcome?;
        self.fallback_page_check(page)?;
        let result = FallbackResult { schema: "device-fallback-result@1", data_state: "local_snapshot", fallback_consent: "local_once",
            grant, slot, members, complete_query_result: false,
            notice: "所选设备包的历史快照；不是完整当前在线查询、当前身份或生命周期状态，也不构成 AI 授权。" };
        if serde_json::to_vec(&result)
            .map_err(|_| "OFFLINE_FALLBACK_INVALID")?
            .len()
            > MAX_PACKAGE_BYTES
        {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        self.fallback_page_check(page)?;
        if pending.expired() {
            return Err("OFFLINE_FALLBACK_EXPIRED");
        }
        Self::legacy_formal_query_gate(&fallback.v2, &result.grant.intent)?;
        Ok(result)
    }
    pub fn revoke_fallback(
        &self,
        request: FallbackRevokeRequest,
    ) -> NativeResult<FallbackRevokeResult> {
        if !wire::uuid(&request.grant_id) {
            return Err("OFFLINE_FALLBACK_INVALID");
        }
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            fallback,
            ..
        } = &mut *inner;
        if let Some(pending) = fallback.pending.remove(&request.grant_id) {
            let mut grant = pending.receipt;
            grant.state = "revoked".into();
            let transaction =
                db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
            self.fallback_audit(&transaction, key, &grant)?;
            db(transaction.commit())?;
        }
        Ok(FallbackRevokeResult {
            revoked: true,
            grant_id: request.grant_id,
        })
    }
}

#[cfg(test)]
mod tests;
mod v2;
pub use v2::*;
