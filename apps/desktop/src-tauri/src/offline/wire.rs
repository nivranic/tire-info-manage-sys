//! Closed, explicitly dispatched offline-pack@1/@2; the hash binds original bytes.
use super::{crypto, MAX_PACKAGE_BYTES};
use crate::security::NativeResult;
use serde::{
    de::{DeserializeSeed, MapAccess, SeqAccess, Visitor},
    Deserialize, Serialize,
};
use serde_json::{Map, Value};
use std::{
    collections::{HashMap, HashSet},
    fmt,
};
mod search;
#[cfg(test)]
mod v2_tests;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PackVersion {
    V1,
    V2,
}
impl PackVersion {
    pub(crate) fn from_pack(schema: &str) -> NativeResult<Self> {
        match schema {
            "offline-pack@1" => Ok(Self::V1),
            "offline-pack@2" => Ok(Self::V2),
            _ => Err("OFFLINE_PACK_INVALID"),
        }
    }
    pub(crate) fn from_descriptor(schema: &str) -> NativeResult<Self> {
        match schema {
            "offline-pack-descriptor@1" => Ok(Self::V1),
            "offline-pack-descriptor@2" => Ok(Self::V2),
            _ => Err("OFFLINE_PACK_INVALID"),
        }
    }
    pub(crate) fn pack_schema(self) -> &'static str {
        match self {
            Self::V1 => "offline-pack@1",
            Self::V2 => "offline-pack@2",
        }
    }
    pub(crate) fn plan_schema(self) -> &'static str {
        match self {
            Self::V1 => "offline-pack-plan@1",
            Self::V2 => "offline-pack-plan@2",
        }
    }
    pub(crate) fn update_schema(self) -> &'static str {
        match self {
            Self::V1 => "offline-pack-update@1",
            Self::V2 => "offline-pack-update@2",
        }
    }
}

#[derive(Clone, Deserialize, Serialize, Debug, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Counts {
    pub garage_profiles: u64,
    pub watch_items: u64,
    pub recent_queries: u64,
    pub distinct_evidence: u64,
    pub searchable_documents: u64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Descriptor {
    pub schema: String,
    pub id: String,
    pub plan_id: String,
    pub created_at: String,
    pub content_created_at: String,
    pub plan_fingerprint: String,
    pub owner_scope_id: String,
    pub privacy_class: String,
    pub sha256: String,
    pub byte_count: u64,
    pub base_pack_id: Option<String>,
    pub counts: Counts,
    pub download_path: String,
    pub data_state: String,
    pub source_refresh_performed: bool,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InstallRequest {
    pub package_id: String,
    pub expected_sha256: String,
    pub expected_byte_count: u64,
    pub approved_plan_fingerprint: String,
    pub slot_id: String,
    pub expected_generation: u64,
    pub allow_device_storage: bool,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum Reference {
    #[serde(rename = "tire")]
    Tire {
        snapshot_id: String,
        variant_id: String,
        verification_id: Option<String>,
    },
    #[serde(rename = "vehicle")]
    Vehicle {
        snapshot_id: String,
        verification_id: Option<String>,
    },
    #[serde(rename = "test_event")]
    TestEvent {
        event_id: String,
        event_revision: u64,
    },
    #[serde(rename = "recall")]
    Recall {
        snapshot_id: String,
        recall_revision_id: Option<String>,
        verification_id: Option<String>,
    },
    #[serde(rename = "recall_search")]
    RecallSearch {
        snapshot_id: String,
        verification_id: String,
    },
}

impl Reference {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Tire { .. } => "tire",
            Self::Vehicle { .. } => "vehicle",
            Self::TestEvent { .. } => "test_event",
            Self::Recall { .. } => "recall",
            Self::RecallSearch { .. } => "recall_search",
        }
    }
    fn validate(&self, resolved: bool) -> bool {
        let id = identifier;
        let verification = |value: &Option<String>| value.as_deref().map(id).unwrap_or(!resolved);
        match self {
            Self::Tire {
                snapshot_id,
                variant_id,
                verification_id,
            } => id(snapshot_id) && id(variant_id) && verification(verification_id),
            Self::Vehicle {
                snapshot_id,
                verification_id,
            } => id(snapshot_id) && verification(verification_id),
            Self::TestEvent {
                event_id,
                event_revision,
            } => id(event_id) && *event_revision > 0 && *event_revision <= i32::MAX as u64,
            Self::Recall {
                snapshot_id,
                recall_revision_id,
                verification_id,
            } => {
                id(snapshot_id)
                    && recall_revision_id.as_deref().map(id).unwrap_or(true)
                    && verification(verification_id)
            }
            Self::RecallSearch {
                snapshot_id,
                verification_id,
            } => id(snapshot_id) && id(verification_id),
        }
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GarageScope {
    pub include: bool,
    pub vehicle_ids: Option<Vec<String>>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WatchScope {
    pub include: bool,
    pub item_ids: Option<Vec<String>>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecentScope {
    pub include: bool,
    pub limit: u64,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    pub garage: GarageScope,
    pub watchlist: WatchScope,
    pub recent: RecentScope,
    pub references: Vec<Reference>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Contracts {
    pub offline_policy: String,
    pub field_policy: Map<String, Value>,
    pub recall_policy: Map<String, Value>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Reason {
    pub selector: String,
    pub scope: String,
    pub object_id: Option<String>,
    pub revision: Option<u64>,
    pub axle: Option<String>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub id: String,
    pub kind: String,
    pub scope: String,
    pub privacy_class: String,
    pub payload: Map<String, Value>,
    pub evidence_keys: Vec<String>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Source {
    pub source_id: Option<String>,
    pub source_url: Option<String>,
    pub raw_hash: Option<String>,
    pub parser_version: Option<String>,
    pub parser_identity: Option<Map<String, Value>>,
    pub observed_at: String,
    pub verified_at: Option<String>,
    pub verification_id: Option<String>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Member {
    pub key: String,
    pub reference: Reference,
    pub member_reasons: Vec<Reason>,
    pub privacy_class: String,
    pub raw_included: bool,
    pub source: Source,
    pub payload: Map<String, Value>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Facets {
    pub brand: Option<String>,
    pub model: Option<String>,
    pub size: Option<String>,
    pub source_id: Option<String>,
    pub campaign_number: Option<String>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Document {
    pub id: String,
    pub category: String,
    pub kind: String,
    pub member_key: Option<String>,
    pub context_id: Option<String>,
    pub record_index: Option<u64>,
    pub title: String,
    pub text: String,
    pub facets: Facets,
    pub membership: Vec<String>,
    pub privacy_class: String,
    pub observed_at: Option<String>,
    pub verified_at: Option<String>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Omission {
    pub selector: String,
    pub object_id: Option<String>,
    pub reason: String,
    pub blocking: bool,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    pub schema: String,
    pub package_id: String,
    pub created_at: String,
    pub plan_fingerprint: String,
    pub owner_scope_id: String,
    pub privacy_class: String,
    pub data_state: String,
    pub source_refresh_performed: bool,
    pub base_pack_id: Option<String>,
    pub scope: Scope,
    pub contracts: Contracts,
    pub contexts: Vec<Context>,
    pub members: Vec<Member>,
    pub documents: Vec<Document>,
    pub omissions: Vec<Omission>,
}

pub fn uuid(value: &str) -> bool {
    value.len() == 36 && uuid::Uuid::parse_str(value).is_ok_and(|id| id.to_string() == value)
}
fn identifier(value: &str) -> bool {
    !value.is_empty() && value.chars().count() <= 64 && !value.contains('\0')
}
pub fn hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn privacy(value: &str) -> bool {
    matches!(value, "public" | "private" | "restricted")
}
fn timestamp(value: &str) -> bool {
    chrono::DateTime::parse_from_rfc3339(value).is_ok()
}

impl InstallRequest {
    pub fn validate(&self) -> NativeResult<()> {
        if !self.allow_device_storage {
            return Err("OFFLINE_CONSENT_REQUIRED");
        }
        if !uuid(&self.package_id)
            || !uuid(&self.slot_id)
            || !hex(&self.expected_sha256)
            || !hex(&self.approved_plan_fingerprint)
            || self.expected_byte_count == 0
            || self.expected_byte_count > MAX_PACKAGE_BYTES as u64
            || self.expected_generation >= 9_007_199_254_740_990
        {
            return Err("OFFLINE_INVALID_ARGUMENT");
        }
        Ok(())
    }
}

pub fn descriptor(bytes: &[u8], request: &InstallRequest) -> NativeResult<Descriptor> {
    request.validate()?;
    if bytes.len() > 64 * 1024 {
        return Err("OFFLINE_PACK_INVALID");
    }
    let raw = strict_json(bytes)?;
    required(&raw, &["base_pack_id"])?;
    let value: Descriptor = serde_json::from_value(raw).map_err(|_| "OFFLINE_PACK_INVALID")?;
    PackVersion::from_descriptor(&value.schema)?;
    if value.id != request.package_id
        || !uuid(&value.plan_id)
        || value.sha256 != request.expected_sha256
        || value.byte_count != request.expected_byte_count
        || value.plan_fingerprint != request.approved_plan_fingerprint
        || !hex(&value.owner_scope_id)
        || !matches!(value.privacy_class.as_str(), "private" | "restricted")
        || value.download_path != format!("/v1/offline-packs/{}/download?mode=history", value.id)
        || value.data_state != "local_snapshot"
        || value.source_refresh_performed
        || !timestamp(&value.created_at)
        || !timestamp(&value.content_created_at)
        || value.base_pack_id.as_deref().is_some_and(|id| !uuid(id))
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    Ok(value)
}

pub fn verify_bytes(bytes: &[u8], descriptor: &Descriptor) -> NativeResult<()> {
    if bytes.len() != descriptor.byte_count as usize
        || bytes.len() > MAX_PACKAGE_BYTES
        || crypto::hash(bytes) != descriptor.sha256
    {
        return Err("OFFLINE_HASH_MISMATCH");
    }
    Ok(())
}
pub fn package(bytes: &[u8], descriptor: &Descriptor) -> NativeResult<Envelope> {
    verify_bytes(bytes, descriptor)?;
    let raw = match PackVersion::from_descriptor(&descriptor.schema)? {
        PackVersion::V1 => strict_json(bytes)?,
        PackVersion::V2 => super::raw::Exact::parse(
            std::str::from_utf8(bytes).map_err(|_| "OFFLINE_PACK_INVALID")?,
        )
        .map_err(|_| "OFFLINE_PACK_INVALID")?
        .package_mirror(),
    };
    required_nullable_fields(&raw)?;
    let value: Envelope = serde_json::from_value(raw).map_err(|_| "OFFLINE_PACK_INVALID")?;
    let c = &descriptor.counts;
    let version = PackVersion::from_pack(&value.schema)?;
    if version != PackVersion::from_descriptor(&descriptor.schema)?
        || (version == PackVersion::V1
            && (value
                .members
                .iter()
                .any(|member| member.reference.kind() == "recall_search")
                || value
                    .scope
                    .references
                    .iter()
                    .any(|reference| reference.kind() == "recall_search")))
        || value.package_id != descriptor.id
        || value.plan_fingerprint != descriptor.plan_fingerprint
        || value.owner_scope_id != descriptor.owner_scope_id
        || value.privacy_class != descriptor.privacy_class
        || value.base_pack_id != descriptor.base_pack_id
        || value.created_at != descriptor.content_created_at
        || value.data_state != "local_snapshot"
        || value.source_refresh_performed
        || value.contracts.offline_policy != "offline-policy@1"
        || c.garage_profiles > 50
        || c.watch_items > 100
        || c.recent_queries > 20
        || c.distinct_evidence > 200
        || value.members.len() != c.distinct_evidence as usize
        || value.documents.len() != c.searchable_documents as usize
        || value.contexts.len() != (c.garage_profiles + c.watch_items) as usize
        || value.documents.len() > 4_000
        || value.scope.recent.limit > 20
        || value.scope.references.len() > 1000
        || !value
            .scope
            .references
            .iter()
            .all(|reference| reference.validate(false))
        || value
            .scope
            .garage
            .vehicle_ids
            .as_ref()
            .is_some_and(|ids| ids.len() > 1000 || ids.iter().any(|id| !identifier(id)))
        || value
            .scope
            .watchlist
            .item_ids
            .as_ref()
            .is_some_and(|ids| ids.len() > 1000 || ids.iter().any(|id| !identifier(id)))
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    let mut members = HashMap::new();
    for member in &value.members {
        if !hex(&member.key)
            || members.insert(member.key.as_str(), member).is_some()
            || !member.reference.validate(true)
            || member.raw_included
            || !privacy(&member.privacy_class)
            || !timestamp(&member.source.observed_at)
            || member
                .source
                .verified_at
                .as_deref()
                .is_some_and(|at| !timestamp(at))
            || member
                .source
                .raw_hash
                .as_deref()
                .is_some_and(|hash| !hex(hash))
            || member.member_reasons.is_empty()
            || member.member_reasons.len() > 500
        {
            return Err("OFFLINE_PACK_INVALID");
        }
        for reason in &member.member_reasons {
            if !matches!(
                reason.selector.as_str(),
                "garage" | "watchlist" | "recent" | "explicit"
            ) || !matches!(
                reason.scope.as_str(),
                "local_workspace" | "current_session" | "explicit"
            ) || reason
                .axle
                .as_deref()
                .is_some_and(|axle| !matches!(axle, "front" | "rear"))
            {
                return Err("OFFLINE_PACK_INVALID");
            }
        }
        validate_payload(member)?;
    }
    let mut contexts = HashMap::new();
    for context in &value.contexts {
        if contexts.insert(context.id.as_str(), context).is_some()
            || context.privacy_class != "private"
            || !matches!(
                (context.kind.as_str(), context.scope.as_str()),
                ("garage", "local_workspace") | ("watchlist", "current_session")
            )
            || context
                .id
                .strip_prefix(&format!("{}:", context.kind))
                .is_none_or(|id| !uuid(id))
            || context
                .evidence_keys
                .iter()
                .any(|key| !members.contains_key(key.as_str()))
        {
            return Err("OFFLINE_PACK_INVALID");
        }
        let object_id = context.id.split_once(':').ok_or("OFFLINE_PACK_INVALID")?.1;
        let keys: &[&str] = if context.kind == "garage" {
            &[
                "vehicle_id",
                "revision",
                "basis",
                "profile",
                "fitment_reference",
                "created_at",
            ]
        } else {
            &["item_id", "variant_id", "created_at"]
        };
        if context.payload.len() != keys.len()
            || keys.iter().any(|key| !context.payload.contains_key(*key))
            || !context.payload["created_at"]
                .as_str()
                .is_some_and(timestamp)
            || context.evidence_keys.iter().collect::<HashSet<_>>().len()
                != context.evidence_keys.len()
        {
            return Err("OFFLINE_PACK_INVALID");
        }
        if context.kind == "garage" {
            if context.payload["vehicle_id"].as_str() != Some(object_id)
                || !context.payload["profile"].is_object()
                || context.payload["revision"]
                    .as_u64()
                    .is_none_or(|revision| revision == 0)
                || !context.payload["basis"].is_string()
                || !(context.payload["fitment_reference"].is_null()
                    || context.payload["fitment_reference"].is_object())
            {
                return Err("OFFLINE_PACK_INVALID");
            }
        } else if context.payload["item_id"].as_str() != Some(object_id)
            || !context.payload["variant_id"].is_string()
        {
            return Err("OFFLINE_PACK_INVALID");
        }
        for key in &context.evidence_keys {
            let member = members.get(key.as_str()).ok_or("OFFLINE_PACK_INVALID")?;
            if !member.member_reasons.iter().any(|reason| {
                reason.selector == context.kind
                    && reason.scope == context.scope
                    && reason.object_id.as_deref() == Some(object_id)
            }) {
                return Err("OFFLINE_PACK_INVALID");
            }
        }
    }
    if contexts.values().filter(|ctx| ctx.kind == "garage").count() != c.garage_profiles as usize
        || contexts
            .values()
            .filter(|ctx| ctx.kind == "watchlist")
            .count()
            != c.watch_items as usize
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    for member in &value.members {
        for reason in &member.member_reasons {
            let valid = match reason.selector.as_str() {
                "garage" | "watchlist" => reason
                    .object_id
                    .as_ref()
                    .and_then(|id| contexts.get(format!("{}:{id}", reason.selector).as_str()))
                    .is_some_and(|context| {
                        context.scope == reason.scope && context.evidence_keys.contains(&member.key)
                    }),
                "recent" => {
                    reason.scope == "current_session"
                        && reason.object_id.as_deref().is_some_and(uuid)
                }
                "explicit" => reason.scope == "explicit" && reason.object_id.is_none(),
                _ => false,
            };
            if !valid {
                return Err("OFFLINE_PACK_INVALID");
            }
        }
    }
    let mut ids = HashSet::new();
    for doc in &value.documents {
        if !ids.insert(doc.id.as_str())
            || doc.title.is_empty()
            || doc.title.len() > 16_384
            || doc.text.len() > 1024 * 1024
            || !privacy(&doc.privacy_class)
            || doc.observed_at.as_deref().is_some_and(|at| !timestamp(at))
            || doc.verified_at.as_deref().is_some_and(|at| !timestamp(at))
            || doc.membership.iter().any(|item| {
                !matches!(
                    item.as_str(),
                    "garage" | "watchlist" | "recent" | "explicit"
                )
            })
        {
            return Err("OFFLINE_PACK_INVALID");
        }
        if doc.category == "evidence" {
            let member = doc
                .member_key
                .as_deref()
                .and_then(|key| members.get(key))
                .ok_or("OFFLINE_PACK_INVALID")?;
            let mut expected = format!("member:{}", member.key);
            if let Some(index) = doc.record_index {
                if !matches!(doc.kind.as_str(), "recall" | "recall_search" | "test_event")
                    || index >= 20_000
                {
                    return Err("OFFLINE_PACK_INVALID");
                }
                expected.push_str(&format!(":record:{index}"));
            }
            if doc.id != expected
                || doc.context_id.is_some()
                || doc.kind != member.reference.kind()
                || doc.privacy_class != member.privacy_class
                || doc.facets.source_id != member.source.source_id
                || doc.observed_at.as_deref() != Some(member.source.observed_at.as_str())
                || doc.verified_at != member.source.verified_at
                || doc.membership.iter().collect::<HashSet<_>>()
                    != member
                        .member_reasons
                        .iter()
                        .map(|reason| &reason.selector)
                        .collect::<HashSet<_>>()
            {
                return Err("OFFLINE_PACK_INVALID");
            }
            let records = record_count(member)?;
            if (records > 0 && doc.record_index.is_none_or(|index| index >= records as u64))
                || (records == 0 && doc.record_index.is_some())
            {
                return Err("OFFLINE_PACK_INVALID");
            }
        } else {
            let context = doc
                .context_id
                .as_deref()
                .and_then(|id| contexts.get(id))
                .ok_or("OFFLINE_PACK_INVALID")?;
            if doc.id != format!("context:{}", context.id)
                || doc.member_key.is_some()
                || doc.record_index.is_some()
                || doc.category != context.kind
                || doc.kind != context.kind
                || doc.privacy_class != "private"
                || doc.observed_at.is_some()
                || doc.verified_at.is_some()
                || doc.facets.source_id.is_some()
                || doc.membership != [context.kind.clone()]
            {
                return Err("OFFLINE_PACK_INVALID");
            }
        }
    }
    // No missing or extra per-record documents: this prevents a package from
    // silently collapsing separate recall products/test participants together.
    let expected_documents = value.contexts.len()
        + value
            .members
            .iter()
            .map(|member| record_count(member).map(|count| count.max(1)))
            .collect::<NativeResult<Vec<_>>>()?
            .iter()
            .sum::<usize>();
    if value.documents.len() != expected_documents {
        return Err("OFFLINE_PACK_INVALID");
    }
    Ok(value)
}

fn required(value: &Value, keys: &[&str]) -> NativeResult<()> {
    if !value
        .as_object()
        .is_some_and(|map| keys.iter().all(|key| map.contains_key(*key)))
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    Ok(())
}
fn required_nullable_fields(raw: &Value) -> NativeResult<()> {
    required(raw, &["base_pack_id"])?;
    required(&raw["scope"]["garage"], &["vehicle_ids"])?;
    required(&raw["scope"]["watchlist"], &["item_ids"])?;
    for reference in raw["scope"]["references"]
        .as_array()
        .ok_or("OFFLINE_PACK_INVALID")?
    {
        if reference["kind"] == "recall" {
            required(reference, &["recall_revision_id"])?;
        }
    }
    for member in raw["members"].as_array().ok_or("OFFLINE_PACK_INVALID")? {
        required(
            &member["source"],
            &[
                "source_id",
                "source_url",
                "raw_hash",
                "parser_version",
                "parser_identity",
                "verified_at",
                "verification_id",
            ],
        )?;
        if member["reference"]["kind"] != "test_event" {
            required(&member["reference"], &["verification_id"])?;
        }
        if member["reference"]["kind"] == "recall" {
            required(&member["reference"], &["recall_revision_id"])?;
        }
        for reason in member["member_reasons"]
            .as_array()
            .ok_or("OFFLINE_PACK_INVALID")?
        {
            required(reason, &["object_id", "revision", "axle"])?;
        }
    }
    for document in raw["documents"].as_array().ok_or("OFFLINE_PACK_INVALID")? {
        required(
            document,
            &[
                "member_key",
                "context_id",
                "record_index",
                "observed_at",
                "verified_at",
            ],
        )?;
        required(
            &document["facets"],
            &["brand", "model", "size", "source_id", "campaign_number"],
        )?;
    }
    for omission in raw["omissions"].as_array().ok_or("OFFLINE_PACK_INVALID")? {
        required(omission, &["object_id"])?;
    }
    Ok(())
}
fn record_count(member: &Member) -> NativeResult<usize> {
    match member.reference.kind() {
        "recall" => member
            .payload
            .get("records")
            .and_then(Value::as_array)
            .map(Vec::len)
            .ok_or("OFFLINE_PACK_INVALID"),
        "test_event" => member
            .payload
            .get("event")
            .and_then(|event| event.get("participants"))
            .and_then(Value::as_array)
            .map(Vec::len)
            .ok_or("OFFLINE_PACK_INVALID"),
        "recall_search" => member
            .payload
            .get("discovery")
            .and_then(|discovery| discovery.get("products"))
            .and_then(Value::as_array)
            .map(Vec::len)
            .ok_or("OFFLINE_PACK_INVALID"),
        _ => Ok(0),
    }
}
fn validate_payload(member: &Member) -> NativeResult<()> {
    let (keys, verification): (&[&str], Option<&str>) = match &member.reference {
        Reference::Tire {
            verification_id, ..
        } => (
            &[
                "variant",
                "identity_contract",
                "snapshot_identity_contract",
                "field_resolution",
                "lifecycle",
            ],
            verification_id.as_deref(),
        ),
        Reference::Vehicle {
            verification_id, ..
        } => (
            &[
                "vehicle",
                "trims",
                "fitments",
                "footnotes",
                "fact_hash",
                "fact_version",
                "excluded_document_count",
            ],
            verification_id.as_deref(),
        ),
        Reference::Recall {
            verification_id, ..
        } => (
            &["evidence", "records", "facts", "policy", "boundary"],
            verification_id.as_deref(),
        ),
        Reference::TestEvent { .. } => (&["metadata", "event"], None),
        Reference::RecallSearch {
            verification_id, ..
        } => (
            &[
                "query",
                "discovery",
                "discovery_hash",
                "evidence",
                "empty_observation",
                "notices",
                "boundary",
            ],
            Some(verification_id.as_str()),
        ),
    };
    if member.payload.len() != keys.len()
        || keys.iter().any(|key| !member.payload.contains_key(*key))
        || member.source.verification_id.as_deref() != verification
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    let object = |key: &str| member.payload.get(key).is_some_and(Value::is_object);
    let array = |key: &str| member.payload.get(key).is_some_and(Value::is_array);
    let valid = match member.reference.kind() {
        "tire" => {
            object("variant")
                && object("identity_contract")
                && object("field_resolution")
                && member.payload["lifecycle"].is_string()
        }
        "vehicle" => {
            object("vehicle")
                && array("trims")
                && array("fitments")
                && array("footnotes")
                && member.payload["fact_hash"].as_str().is_some_and(hex)
                && member.payload["fact_version"].as_u64().is_some()
                && member.payload["excluded_document_count"].as_u64().is_some()
        }
        "recall" => {
            object("evidence")
                && array("records")
                && array("facts")
                && object("policy")
                && object("boundary")
        }
        "test_event" => object("metadata") && object("event") && record_count(member)? > 0,
        "recall_search" => search::validate(member).is_ok(),
        _ => false,
    };
    if !valid {
        return Err("OFFLINE_PACK_INVALID");
    }
    Ok(())
}

struct Budget {
    nodes: usize,
}
struct Seed<'a> {
    budget: &'a mut Budget,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = Value;
    fn deserialize<D: serde::Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        if self.depth > 64 || self.budget.nodes >= 250_000 {
            return Err(serde::de::Error::custom("bounded JSON"));
        }
        self.budget.nodes += 1;
        deserializer.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = Value;
    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("bounded JSON value")
    }
    fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Value, E> {
        Ok(Value::Bool(v))
    }
    fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Value, E> {
        Ok(v.into())
    }
    fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Value, E> {
        Ok(v.into())
    }
    fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Value, E> {
        serde_json::Number::from_f64(v)
            .map(Value::Number)
            .ok_or_else(|| E::custom("finite JSON"))
    }
    fn visit_unit<E: serde::de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Value, E> {
        if v.len() > 1024 * 1024 || v.contains('\0') {
            return Err(E::custom("bounded string"));
        }
        Ok(Value::String(v.to_owned()))
    }
    fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Value, E> {
        self.visit_str(&v)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = seq.next_element_seed(Seed {
            budget: self.budget,
            depth: self.depth + 1,
        })? {
            if values.len() >= 20_000 {
                return Err(serde::de::Error::custom("bounded array"));
            }
            values.push(value);
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if key.len() > 4096
                || key.contains('\0')
                || values.len() >= 4096
                || values.contains_key(&key)
            {
                return Err(serde::de::Error::custom("unique bounded fields"));
            }
            let value = map.next_value_seed(Seed {
                budget: self.budget,
                depth: self.depth + 1,
            })?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

pub fn strict_json(bytes: &[u8]) -> NativeResult<Value> {
    if bytes.is_empty() || bytes.len() > MAX_PACKAGE_BYTES || bytes.starts_with(&[0xef, 0xbb, 0xbf])
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    let mut parser = serde_json::Deserializer::from_slice(bytes);
    let value = Seed {
        budget: &mut Budget { nodes: 0 },
        depth: 0,
    }
    .deserialize(&mut parser)
    .map_err(|_| "OFFLINE_PACK_INVALID")?;
    parser.end().map_err(|_| "OFFLINE_PACK_INVALID")?;
    Ok(value)
}
