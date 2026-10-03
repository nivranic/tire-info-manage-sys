use super::*;

#[test]
fn authenticated_encryption_binds_owner_slot_generation_and_rejects_corruption() {
    let key = crypto::random_key().unwrap();
    let clear = b"SYNTHETIC PRIVATE GARAGE CANARY";
    let aad = b"offline-payload@1|profile-a|slot-a|generation-1";
    let first = crypto::seal(&key, aad, clear).unwrap();
    let second = crypto::seal(&key, aad, clear).unwrap();
    assert_ne!(first, second, "each write must have a fresh nonce");
    assert!(!first.windows(clear.len()).any(|bytes| bytes == clear));
    assert_eq!(
        &**crypto::open(&key, aad, &first, MAX_PACKAGE_BYTES).unwrap(),
        clear
    );
    assert_eq!(
        crypto::open(
            &key,
            b"wrong-owner-or-generation",
            &first,
            MAX_PACKAGE_BYTES
        )
        .err(),
        Some("OFFLINE_PACK_CORRUPT")
    );
    let mut damaged = first.clone();
    *damaged.last_mut().unwrap() ^= 1;
    assert_eq!(
        crypto::open(&key, aad, &damaged, MAX_PACKAGE_BYTES).err(),
        Some("OFFLINE_PACK_CORRUPT")
    );
    let other = crypto::random_key().unwrap();
    assert_eq!(
        crypto::open(&other, aad, &first, MAX_PACKAGE_BYTES).err(),
        Some("OFFLINE_PACK_CORRUPT")
    );
    assert!(crypto::open(&key, aad, &first, 1).is_err());
}
use super::{wire, MAX_SLOTS, MAX_STORE_BYTES};
use crate::security::NativeResult;
use serde_json::{json, Value};
use std::{fs, path::PathBuf, sync::Mutex};
use zeroize::Zeroizing;

#[derive(Default)]
struct FakeKeys(Mutex<Option<[u8; 32]>>);
impl super::crypto::KeyStore for FakeKeys {
    fn load(&self) -> NativeResult<Option<Zeroizing<[u8; 32]>>> {
        Ok(self.0.lock().unwrap().map(Zeroizing::new))
    }
    fn save(&self, key: &[u8; 32]) -> NativeResult<()> {
        *self.0.lock().unwrap() = Some(*key);
        Ok(())
    }
}
struct TestRoot(PathBuf);
impl TestRoot {
    fn new() -> Self {
        let path =
            std::env::temp_dir().join(format!("ti-offline-rust-qa-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for TestRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

pub(crate) fn sample() -> (wire::InstallRequest, wire::Descriptor, Vec<u8>) {
    let package_id = uuid::Uuid::new_v4().to_string();
    let context_id = format!("garage:{}", uuid::Uuid::new_v4());
    let date = "2026-10-01T00:00:00Z";
    let counts = json!({"garage_profiles":1,"watch_items":0,"recent_queries":0,"distinct_evidence":0,"searchable_documents":1});
    let raw = json!({"schema":"offline-pack@1","package_id":package_id,"created_at":date,"plan_fingerprint":"a".repeat(64),"owner_scope_id":"b".repeat(64),"privacy_class":"private","data_state":"local_snapshot","source_refresh_performed":false,"base_pack_id":null,
        "scope":{"garage":{"include":true,"vehicle_ids":null},"watchlist":{"include":false,"item_ids":null},"recent":{"include":false,"limit":0},"references":[]},
        "contracts":{"offline_policy":"offline-policy@1","field_policy":{},"recall_policy":{}},
        "contexts":[{"id":context_id,"kind":"garage","scope":"local_workspace","privacy_class":"private","payload":{"vehicle_id":context_id.strip_prefix("garage:").unwrap(),"revision":1,"basis":"custom","profile":{},"fitment_reference":null,"created_at":date},"evidence_keys":[]}],"members":[],
        "documents":[{"id":format!("context:{context_id}"),"category":"garage","kind":"garage","member_key":null,"context_id":context_id,"record_index":null,"title":"独立离线轮胎证据","text":"OFFLINE_PRIVATE_CANARY Michelin 205/55R16 召回 上海","facets":{"brand":"Michelin","model":null,"size":"205/55R16","source_id":null,"campaign_number":null},"membership":["garage"],"privacy_class":"private","observed_at":null,"verified_at":null}],"omissions":[]});
    let bytes = serde_json::to_vec(&raw).unwrap();
    let request = wire::InstallRequest {
        package_id: package_id.clone(),
        expected_sha256: super::crypto::hash(&bytes),
        expected_byte_count: bytes.len() as u64,
        approved_plan_fingerprint: "a".repeat(64),
        slot_id: uuid::Uuid::new_v4().to_string(),
        expected_generation: 0,
        allow_device_storage: true,
    };
    let descriptor=serde_json::from_value(json!({"schema":"offline-pack-descriptor@1","id":package_id,"plan_id":uuid::Uuid::new_v4().to_string(),"created_at":date,"content_created_at":date,"plan_fingerprint":request.approved_plan_fingerprint,"owner_scope_id":"b".repeat(64),"privacy_class":"private","sha256":request.expected_sha256,"byte_count":bytes.len(),"base_pack_id":null,"counts":counts,"download_path":format!("/v1/offline-packs/{package_id}/download?mode=history"),"data_state":"local_snapshot","source_refresh_performed":false})).unwrap();
    (request, descriptor, bytes)
}
fn install_sample(
    store: &Store,
    request: &wire::InstallRequest,
    descriptor: &wire::Descriptor,
    bytes: &[u8],
) -> Slot {
    let ticket = store.begin_install(request).unwrap();
    store
        .install(
            request,
            descriptor.clone(),
            Zeroizing::new(bytes.to_vec()),
            ticket,
        )
        .unwrap()
}
fn search(store: &Store, slot: &Slot, query: &str) -> NativeResult<SearchResult> {
    store.search(SearchRequest {
        slot_id: slot.slot_id.clone(),
        expected_generation: slot.generation,
        query: query.into(),
        kind: None,
        limit: 10,
        offset: 0,
    })
}
fn rehash(raw: Value, descriptor: &wire::Descriptor) -> (Vec<u8>, wire::Descriptor) {
    let bytes = serde_json::to_vec(&raw).unwrap();
    let mut descriptor = descriptor.clone();
    descriptor.sha256 = super::crypto::hash(&bytes);
    descriptor.byte_count = bytes.len() as u64;
    (bytes, descriptor)
}

#[test]
fn encrypted_store_reopens_searches_han_and_retains_tombstones() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (mut request, descriptor, bytes) = sample();
    let first = install_sample(&store, &request, &descriptor, &bytes);
    for query in ["轮", "召回", "michelin", "205/55R16"] {
        assert_eq!(search(&store, &first, query).unwrap().total, 1, "{query}");
    }
    assert_eq!(search(&store, &first, "\" OR *").unwrap().total, 0);
    assert_eq!(search(&store, &first, "").unwrap().total, 1);
    assert_eq!(search(&store, &first, "NOT michelin").unwrap().total, 0);
    assert_eq!(search(&store, &first, "回召").unwrap().total, 0);
    let page = search(&store, &first, "").unwrap();
    let read = store
        .read(ReadRequest {
            slot_id: first.slot_id.clone(),
            expected_generation: first.generation,
            document_id: page.items[0].id.clone(),
        })
        .unwrap();
    assert!(read.member.is_none());
    assert!(read.context.is_some());
    for entry in fs::read_dir(&root.0).unwrap() {
        let bytes = fs::read(entry.unwrap().path()).unwrap();
        assert!(!bytes
            .windows(b"OFFLINE_PRIVATE_CANARY".len())
            .any(|window| window == b"OFFLINE_PRIVATE_CANARY"));
        assert!(!bytes
            .windows(b"Michelin".len())
            .any(|window| window == b"Michelin"));
    }
    let profile = store.list().unwrap().profile_id;
    drop(store);
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    assert_eq!(store.list().unwrap().profile_id, profile);
    assert_eq!(search(&store, &first, "上海").unwrap().total, 1);
    assert_eq!(
        store.begin_install(&request).err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
    request.expected_generation = first.generation;
    let second = install_sample(&store, &request, &descriptor, &bytes);
    assert_eq!(second.generation, 2);
    assert_eq!(
        search(&store, &first, "").err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
    let removal = store
        .remove(SlotRequest {
            slot_id: second.slot_id.clone(),
            expected_generation: second.generation,
        })
        .unwrap();
    assert_eq!(removal.generation, 3);
    request.expected_generation = 0;
    assert_eq!(
        store.begin_install(&request).err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
    request.expected_generation = removal.generation;
    let fourth = install_sample(&store, &request, &descriptor, &bytes);
    assert_eq!(fourth.generation, 4);
    assert_eq!(
        search(&store, &first, "").err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
}

#[test]
fn owner_reset_is_durable_and_explicit_generation_unlock_preserves_label() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (request, descriptor, bytes) = sample();
    let slot = install_sample(&store, &request, &descriptor, &bytes);
    let mut replacement = request.clone();
    replacement.expected_generation = slot.generation;
    let ticket = store.begin_install(&replacement).unwrap();
    store.reset_owner().unwrap();
    assert_eq!(
        store
            .install(&replacement, descriptor, Zeroizing::new(bytes), ticket)
            .err(),
        Some("OFFLINE_OWNER_CHANGED")
    );
    assert_eq!(
        search(&store, &slot, "").err(),
        Some("OFFLINE_PREVIOUS_OWNER_LOCKED")
    );
    drop(store);
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let list = store.list().unwrap();
    assert_eq!(list.owner_epoch, 2);
    assert!(list.items[0].locked && list.items[0].previous_owner);
    assert_eq!(
        store
            .unlock(UnlockRequest {
                slot_id: slot.slot_id.clone(),
                expected_generation: slot.generation,
                allow_previous_owner: false
            })
            .err(),
        Some("OFFLINE_PREVIOUS_OWNER_CONSENT_REQUIRED")
    );
    assert_eq!(
        store
            .unlock(UnlockRequest {
                slot_id: slot.slot_id.clone(),
                expected_generation: slot.generation + 1,
                allow_previous_owner: true
            })
            .err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
    let unlocked = store
        .unlock(UnlockRequest {
            slot_id: slot.slot_id.clone(),
            expected_generation: slot.generation,
            allow_previous_owner: true,
        })
        .unwrap();
    assert!(!unlocked.locked && unlocked.previous_owner);
    assert_eq!(search(&store, &slot, "轮胎").unwrap().total, 1);
    store.reset_owner().unwrap();
    assert_eq!(
        search(&store, &slot, "").err(),
        Some("OFFLINE_PREVIOUS_OWNER_LOCKED")
    );
}

#[test]
fn missing_wrong_key_and_corrupt_ciphertext_fail_without_regeneration() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (request, descriptor, bytes) = sample();
    let slot = install_sample(&store, &request, &descriptor, &bytes);
    drop(store);
    assert_eq!(
        Store::with_keys(root.0.clone(), "qa-only".into(), &FakeKeys::default()).err(),
        Some("OFFLINE_KEY_UNAVAILABLE")
    );
    let wrong = FakeKeys(Mutex::new(Some([9; 32])));
    assert_eq!(
        Store::with_keys(root.0.clone(), "qa-only".into(), &wrong).err(),
        Some("OFFLINE_PACK_CORRUPT")
    );
    let path = fs::read_dir(&root.0)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .find(|path| {
            path.extension()
                .is_some_and(|extension| extension == "pack")
        })
        .unwrap();
    let mut encrypted = fs::read(&path).unwrap();
    *encrypted.last_mut().unwrap() ^= 1;
    fs::write(&path, &encrypted).unwrap();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    assert_eq!(
        search(&store, &slot, "").err(),
        Some("OFFLINE_RELEASE_VALIDATION_REQUIRED")
    );
    let release = store.sync_status().unwrap().release_checks.remove(0);
    assert_eq!(release.state, "failed");
    assert_eq!(release.sha256.as_deref(), Some(slot.sha256.as_str()));
    assert_eq!(release.reason.as_deref(), Some("OFFLINE_PACK_CORRUPT"));
    assert_eq!(fs::read(path).unwrap(), encrypted);
    assert_eq!(store.list().unwrap().items[0].generation, 1);
}

#[test]
fn missing_catalog_owner_state_does_not_recreate_epoch_zero() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (request, descriptor, bytes) = sample();
    install_sample(&store, &request, &descriptor, &bytes);
    store.reset_owner().unwrap();
    drop(store);
    let catalog = rusqlite::Connection::open(root.0.join("catalog.sqlite3")).unwrap();
    catalog.execute("DELETE FROM vault", []).unwrap();
    drop(catalog);
    assert_eq!(
        Store::with_keys(root.0.clone(), "qa-only".into(), &keys).err(),
        Some("OFFLINE_PACK_CORRUPT")
    );
}

#[test]
fn lost_catalog_after_removal_does_not_discard_tombstone_history() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (request, descriptor, bytes) = sample();
    let slot = install_sample(&store, &request, &descriptor, &bytes);
    store
        .remove(SlotRequest {
            slot_id: slot.slot_id,
            expected_generation: slot.generation,
        })
        .unwrap();
    drop(store);
    fs::remove_file(root.0.join("catalog.sqlite3")).unwrap();
    assert_eq!(
        Store::with_keys(root.0.clone(), "qa-only".into(), &keys).err(),
        Some("OFFLINE_PACK_CORRUPT")
    );
}

#[test]
fn removed_slot_reuse_requires_exact_tombstone_generation() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (mut request, descriptor, bytes) = sample();
    let first = install_sample(&store, &request, &descriptor, &bytes);
    let removed = store
        .remove(SlotRequest {
            slot_id: first.slot_id.clone(),
            expected_generation: first.generation,
        })
        .unwrap();
    assert_eq!(removed.generation, 2);
    assert_eq!(
        search(&store, &first, "").err(),
        Some("OFFLINE_SLOT_NOT_FOUND")
    );
    assert_eq!(
        store.begin_install(&request).err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
    request.expected_generation = removed.generation;
    let third = install_sample(&store, &request, &descriptor, &bytes);
    assert_eq!(third.generation, 3);
    assert_eq!(
        search(&store, &first, "").err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
}

#[test]
fn failed_replacement_and_concurrent_stage_preserve_active_generation() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (mut request, descriptor, bytes) = sample();
    let slot = install_sample(&store, &request, &descriptor, &bytes);
    request.expected_generation = slot.generation;
    let second = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let ticket = store.begin_install(&request).unwrap();
    assert_eq!(
        second.begin_install(&request).err(),
        Some("OFFLINE_INSTALL_BUSY")
    );
    let mut bad = bytes.clone();
    bad[0] ^= 1;
    assert_eq!(
        store
            .install(&request, descriptor.clone(), Zeroizing::new(bad), ticket)
            .err(),
        Some("OFFLINE_HASH_MISMATCH")
    );
    assert_eq!(search(&store, &slot, "轮胎").unwrap().total, 1);
    let ticket = store.begin_install(&request).unwrap();
    store
        .remove(SlotRequest {
            slot_id: slot.slot_id.clone(),
            expected_generation: slot.generation,
        })
        .unwrap();
    assert_eq!(
        store
            .install(&request, descriptor, Zeroizing::new(bytes), ticket)
            .err(),
        Some("OFFLINE_GENERATION_CONFLICT")
    );
}

#[test]
fn catalog_publish_failure_after_fsync_preserves_previous_ciphertext() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (mut request, descriptor, bytes) = sample();
    let slot = install_sample(&store, &request, &descriptor, &bytes);
    request.expected_generation = slot.generation;
    let fault = rusqlite::Connection::open(root.0.join("catalog.sqlite3")).unwrap();
    fault.execute_batch("CREATE TRIGGER qa_fail_publish BEFORE UPDATE ON slots BEGIN SELECT RAISE(ABORT,'independent QA publish failure'); END;").unwrap();
    let ticket = store.begin_install(&request).unwrap();
    assert_eq!(
        store
            .install(&request, descriptor, Zeroizing::new(bytes), ticket)
            .err(),
        Some("OFFLINE_STORE_FAILED")
    );
    fault
        .execute_batch("DROP TRIGGER qa_fail_publish;")
        .unwrap();
    drop(fault);
    drop(store);
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    assert_eq!(search(&store, &slot, "轮胎").unwrap().total, 1);
    assert_eq!(store.list().unwrap().items[0].generation, 1);
    assert_eq!(
        fs::read_dir(&root.0)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| entry
                .path()
                .extension()
                .is_some_and(|extension| extension == "pack"))
            .count(),
        1
    );
}

#[test]
fn committed_original_byte_budget_subtracts_replacement_and_rejects_excess() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (mut request, descriptor, bytes) = sample();
    let mut raw: Value = serde_json::from_slice(&bytes).unwrap();
    // Private structured profile data stays within the JSON per-string budget;
    // search documents remain small. The package is exactly the 8 MiB limit.
    for number in 0..8 {
        raw["contexts"][0]["payload"]["profile"][format!("qa_padding_{number}")] = json!("");
    }
    let base = serde_json::to_vec(&raw).unwrap().len();
    let mut remaining = super::MAX_PACKAGE_BYTES - base;
    for number in 0..8 {
        let count = remaining.min(1024 * 1024);
        raw["contexts"][0]["payload"]["profile"][format!("qa_padding_{number}")] =
            json!("x".repeat(count));
        remaining -= count;
    }
    assert_eq!(remaining, 0);
    let (bytes, descriptor) = rehash(raw, &descriptor);
    assert_eq!(bytes.len(), super::MAX_PACKAGE_BYTES);
    request.expected_byte_count = bytes.len() as u64;
    request.expected_sha256 = descriptor.sha256.clone();
    let mut first = None;
    for _ in 0..4 {
        let mut input = request.clone();
        input.slot_id = uuid::Uuid::new_v4().to_string();
        let slot = install_sample(&store, &input, &descriptor, &bytes);
        if first.is_none() {
            first = Some(slot);
        }
    }
    assert_eq!(store.status().total_bytes, MAX_STORE_BYTES);
    assert_eq!(
        store.begin_install(&request).err(),
        Some("OFFLINE_STORE_FULL")
    );
    let first = first.unwrap();
    request.slot_id = first.slot_id;
    request.expected_generation = first.generation;
    let replacement = install_sample(&store, &request, &descriptor, &bytes);
    assert_eq!(replacement.generation, 2);
    assert_eq!(store.status().total_bytes, MAX_STORE_BYTES);
    request.expected_byte_count = super::MAX_PACKAGE_BYTES as u64 + 1;
    assert_eq!(
        store.begin_install(&request).err(),
        Some("OFFLINE_INVALID_ARGUMENT")
    );
}

#[test]
fn closed_wire_rejects_missing_nullable_duplicate_and_bad_document_binding() {
    let (request, descriptor, bytes) = sample();
    assert!(wire::descriptor(&serde_json::to_vec(&descriptor).unwrap(), &request).is_ok());
    assert!(wire::package(&bytes, &descriptor).is_ok());
    let raw: Value = serde_json::from_slice(&bytes).unwrap();
    let mut missing = raw.clone();
    missing["documents"][0]
        .as_object_mut()
        .unwrap()
        .remove("record_index");
    let (bytes, descriptor2) = rehash(missing, &descriptor);
    assert_eq!(
        wire::package(&bytes, &descriptor2).err().map(|error| error),
        Some("OFFLINE_PACK_INVALID")
    );
    let mut binding = raw.clone();
    binding["documents"][0]["context_id"] = json!("garage:00000000-0000-0000-0000-000000000000");
    let (bytes, descriptor2) = rehash(binding, &descriptor);
    assert!(wire::package(&bytes, &descriptor2).is_err());
    assert!(wire::strict_json(br#"{"key":1,"key":2}"#).is_err());
    assert!(wire::strict_json(br#"{"key":"\u0000"}"#).is_err());
    assert!(wire::strict_json(b"{} trailing").is_err());
    let mut extra = raw;
    extra["arbitrary_sql"] = json!("SELECT 1");
    let (bytes, descriptor2) = rehash(extra, &descriptor);
    assert!(wire::package(&bytes, &descriptor2).is_err());
}

#[test]
fn active_slot_limit_and_replacement_capacity_are_enforced() {
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-only".into(), &keys).unwrap();
    let (request, descriptor, bytes) = sample();
    let mut first = None;
    for _ in 0..MAX_SLOTS {
        let mut request = request.clone();
        request.slot_id = uuid::Uuid::new_v4().to_string();
        let slot = install_sample(&store, &request, &descriptor, &bytes);
        if first.is_none() {
            first = Some(slot);
        }
    }
    assert_eq!(
        store.begin_install(&request).err(),
        Some("OFFLINE_STORE_FULL")
    );
    let first = first.unwrap();
    let mut replacement = request;
    replacement.slot_id = first.slot_id;
    replacement.expected_generation = first.generation;
    assert!(store.begin_install(&replacement).is_ok());
    let status = store.status();
    assert_eq!(status.total_bytes, bytes.len() as u64 * MAX_SLOTS as u64);
    assert_eq!(status.max_store_bytes, MAX_STORE_BYTES);
    assert_eq!(status.max_slots, 16);
}

#[test]
fn requested_scope_vectors_are_bounded_separately_from_resolved_contexts() {
    let (_, descriptor, bytes) = sample();
    let mut raw: Value = serde_json::from_slice(&bytes).unwrap();
    let garage_id = raw["contexts"][0]["payload"]["vehicle_id"]
        .as_str()
        .unwrap()
        .to_owned();
    raw["scope"]["garage"]["vehicle_ids"] = json!(vec![garage_id; 1000]);
    // Disabled selectors are preserved by the producer without resolving them.
    raw["scope"]["watchlist"]["item_ids"] = json!(vec!["未选中的opaque-ID"; 1000]);
    let (bytes, descriptor) = rehash(raw.clone(), &descriptor);
    assert!(wire::package(&bytes, &descriptor).is_ok());
    raw["scope"]["garage"]["vehicle_ids"]
        .as_array_mut()
        .unwrap()
        .push(json!("overflow"));
    let (bytes, descriptor) = rehash(raw, &descriptor);
    assert_eq!(
        wire::package(&bytes, &descriptor).err(),
        Some("OFFLINE_PACK_INVALID")
    );
}

#[test]
#[ignore = "requires actual producer duplicate-scope package from isolated PG46 acceptance"]
fn producer_duplicate_requested_scope_preserves_small_resolved_package() {
    let directory = PathBuf::from(
        std::env::var("TI_OFFLINE_WIRE_FIXTURE_DIR").expect("explicit QA fixture directory"),
    );
    let bytes = fs::read(directory.join("duplicate-scope-envelope.json")).unwrap();
    let encoded = fs::read(directory.join("duplicate-scope-descriptor.json")).unwrap();
    let descriptor: wire::Descriptor = serde_json::from_slice(&encoded).unwrap();
    let request = wire::InstallRequest {
        package_id: descriptor.id.clone(),
        expected_sha256: descriptor.sha256.clone(),
        expected_byte_count: descriptor.byte_count,
        approved_plan_fingerprint: descriptor.plan_fingerprint.clone(),
        slot_id: uuid::Uuid::new_v4().to_string(),
        expected_generation: 0,
        allow_device_storage: true,
    };
    let descriptor = wire::descriptor(&encoded, &request).unwrap();
    let envelope = wire::package(&bytes, &descriptor).unwrap();
    assert_eq!(envelope.scope.references.len(), 201);
    assert_eq!(
        envelope.scope.garage.vehicle_ids.as_ref().unwrap().len(),
        51
    );
    assert_eq!(
        envelope.scope.watchlist.item_ids.as_ref().unwrap().len(),
        101
    );
    assert_eq!(envelope.members.len(), 1);
    assert_eq!(envelope.contexts.len(), 2);
    assert_eq!(envelope.documents.len(), 3);
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-duplicate-scope".into(), &keys).unwrap();
    let slot = install_sample(&store, &request, &descriptor, &bytes);
    assert_eq!(search(&store, &slot, "").unwrap().total, 3);
}

#[test]
#[ignore = "requires independently generated backend QA fixture directory"]
fn producer_four_domain_original_bytes_round_trip() {
    let directory =
        std::env::var("TI_OFFLINE_WIRE_FIXTURE_DIR").expect("explicit QA fixture directory");
    let directory = PathBuf::from(directory);
    let bytes = fs::read(directory.join("valid-envelope.json")).unwrap();
    let encoded_descriptor = fs::read(directory.join("valid-descriptor.json")).unwrap();
    let descriptor: wire::Descriptor = serde_json::from_slice(&encoded_descriptor).unwrap();
    let request = wire::InstallRequest {
        package_id: descriptor.id.clone(),
        expected_sha256: descriptor.sha256.clone(),
        expected_byte_count: descriptor.byte_count,
        approved_plan_fingerprint: descriptor.plan_fingerprint.clone(),
        slot_id: uuid::Uuid::new_v4().to_string(),
        expected_generation: 0,
        allow_device_storage: true,
    };
    let descriptor = wire::descriptor(&encoded_descriptor, &request).unwrap();
    let envelope = wire::package(&bytes, &descriptor).unwrap();
    assert_eq!(envelope.members.len(), 5);
    assert_eq!(envelope.documents.len(), 9);
    let root = TestRoot::new();
    let keys = FakeKeys::default();
    let store = Store::with_keys(root.0.clone(), "qa-producer-wire".into(), &keys).unwrap();
    let slot = install_sample(&store, &request, &descriptor, &bytes);
    drop(store);
    let store = Store::with_keys(root.0.clone(), "qa-producer-wire".into(), &keys).unwrap();
    let result = search(&store, &slot, "").unwrap();
    assert_eq!(result.total, 9);
    let recall = |query: &str| {
        store
            .search(SearchRequest {
                slot_id: slot.slot_id.clone(),
                expected_generation: slot.generation,
                query: query.into(),
                kind: Some("recall".into()),
                limit: 50,
                offset: 0,
            })
            .unwrap()
    };
    assert_eq!(recall("Brand A Model A").total, 1);
    assert_eq!(recall("Brand A Model B").total, 0);
    assert_eq!(recall("23T001000").total, 3);
    let test = store
        .search(SearchRequest {
            slot_id: slot.slot_id.clone(),
            expected_generation: slot.generation,
            query: "Fixture A Fixture B".into(),
            kind: Some("test_event".into()),
            limit: 50,
            offset: 0,
        })
        .unwrap();
    assert_eq!(test.total, 0);
    for document in result.items {
        let read = store
            .read(ReadRequest {
                slot_id: slot.slot_id.clone(),
                expected_generation: slot.generation,
                document_id: document.id,
            })
            .unwrap();
        assert!(read.member.is_some() || read.context.is_some());
    }
}
