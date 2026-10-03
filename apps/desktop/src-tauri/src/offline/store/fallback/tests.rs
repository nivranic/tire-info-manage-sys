use super::*;
use serde_json::json;
use std::sync::{Arc, Barrier};

#[derive(Default)]
struct FakeKeys(Mutex<Option<[u8; 32]>>);
impl KeyStore for FakeKeys {
    fn load(&self) -> NativeResult<Option<Zeroizing<[u8; 32]>>> {
        Ok(self.0.lock().unwrap().map(Zeroizing::new))
    }
    fn save(&self, key: &[u8; 32]) -> NativeResult<()> {
        *self.0.lock().unwrap() = Some(*key);
        Ok(())
    }
}
struct Fixture {
    root: PathBuf,
    keys: FakeKeys,
    store: Arc<Store>,
    install: InstallRequest,
    descriptor: Descriptor,
    bytes: Vec<u8>,
    slot: Slot,
}
impl Fixture {
    fn new() -> Self {
        let root =
            std::env::temp_dir().join(format!("ti-localonce-rust-qa-{}", uuid::Uuid::new_v4()));
        let keys = FakeKeys::default();
        let store =
            Arc::new(Store::with_keys(root.clone(), "qa-local-once".into(), &keys).unwrap());
        let (mut install, mut descriptor, bytes) = crate::offline::tests::sample();
        let mut envelope: Value = serde_json::from_slice(&bytes).unwrap();
        let variant_id = uuid::Uuid::new_v4().to_string();
        let snapshot_id = uuid::Uuid::new_v4().to_string();
        for (index, (source, model, size)) in [
            ("synthetic-source", "EXACT_PRIVATE_MODEL", "205/55R16"),
            ("synthetic-source", "EXACT_PRIVATE_MODEL", "205/55R16"),
            ("other-source", "EXACT_PRIVATE_MODEL", "205/55R16"),
            ("synthetic-source", "EXACT_PRIVATE_MODEL Plus", "205/55R16"),
            ("synthetic-source", "EXACT_PRIVATE_MODEL", "205/55ZR16"),
        ]
        .into_iter()
        .enumerate()
        {
            let key = format!("{index:064x}");
            let receipt = uuid::Uuid::new_v4().to_string();
            envelope["members"].as_array_mut().unwrap().push(json!({
                "key":key,"reference":{"kind":"tire","snapshot_id":snapshot_id,"variant_id":variant_id,"verification_id":receipt},
                "member_reasons":[{"selector":"explicit","scope":"explicit","object_id":null,"revision":null,"axle":null}],
                "privacy_class":"private","raw_included":false,
                "source":{"source_id":source,"source_url":"https://fixture.example/tire","raw_hash":"c".repeat(64),
                    "parser_version":"synthetic@1","parser_identity":null,"observed_at":"2026-10-01T00:00:00Z","verified_at":"2026-10-01T00:01:00Z","verification_id":receipt},
                "payload":{"variant":{"id":variant_id,"model":model,"size":size,"facts":{"preserved":"PRIVATE_LOCAL_CANARY"}},
                    "identity_contract":{},"snapshot_identity_contract":null,"field_resolution":{"complete_package_history":true},"lifecycle":"unreviewed"}
            }));
            envelope["documents"].as_array_mut().unwrap().push(json!({
                "id":format!("member:{key}"),"category":"evidence","kind":"tire","member_key":key,"context_id":null,"record_index":null,
                "title":model,"text":"synthetic tire","facets":{"brand":null,"model":model,"size":size,"source_id":source,"campaign_number":null},
                "membership":["explicit"],"privacy_class":"private","observed_at":"2026-10-01T00:00:00Z","verified_at":"2026-10-01T00:01:00Z"
            }));
        }
        let bytes = serde_json::to_vec(&envelope).unwrap();
        descriptor.counts.distinct_evidence = 5;
        descriptor.counts.searchable_documents = 6;
        descriptor.sha256 = crypto::hash(&bytes);
        descriptor.byte_count = bytes.len() as u64;
        install.expected_sha256 = descriptor.sha256.clone();
        install.expected_byte_count = descriptor.byte_count;
        let ticket = store.begin_install(&install).unwrap();
        let slot = store
            .install(
                &install,
                descriptor.clone(),
                Zeroizing::new(bytes.clone()),
                ticket,
            )
            .unwrap();
        Self {
            root,
            keys,
            store,
            install,
            descriptor,
            bytes,
            slot,
        }
    }
    fn decide_request(&self, decision: &str) -> FallbackDecideRequest {
        let status = self.store.status();
        FallbackDecideRequest {
            intent: FallbackIntent {
                schema: "device-fallback-intent@1".into(),
                attempt_id: uuid::Uuid::new_v4().to_string(),
                query_fingerprint: "a".repeat(64),
                source_id: "synthetic-source".into(),
                source_access_generation: 7,
                query: FallbackQuery {
                    model: "EXACT_PRIVATE_MODEL".into(),
                    size: Some("205/55R16".into()),
                },
                filters: vec![],
                failure: FallbackFailure {
                    scope: "api_transport".into(),
                    reason: "api_timeout".into(),
                    query_id: None,
                },
            },
            slot_id: self.slot.slot_id.clone(),
            expected_generation: self.slot.generation,
            expected_sha256: self.slot.sha256.clone(),
            expected_profile_id: status.profile_id.unwrap(),
            expected_owner_epoch: status.owner_epoch,
            decision: decision.into(),
        }
    }
    fn grant(&self) -> FallbackGrant {
        self.store
            .decide_fallback(self.decide_request("allow"), self.store.fallback_page_id())
            .unwrap()
    }
    fn consume(&self, grant: &FallbackGrant) -> NativeResult<FallbackResult> {
        self.store.consume_fallback(
            FallbackConsumeRequest {
                grant_id: grant.id.clone(),
                intent: grant.intent.clone(),
            },
            self.store.fallback_page_id(),
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        // Close the file-backed connection before deleting this UUID-owned root.
        let inner = Arc::get_mut(&mut self.store)
            .unwrap()
            .inner
            .get_mut()
            .unwrap();
        let connection =
            std::mem::replace(&mut inner.connection, Connection::open_in_memory().unwrap());
        connection.close().unwrap();
        assert!(self
            .root
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("ti-localonce-rust-qa-"));
        fs::remove_dir_all(&self.root).unwrap();
    }
}

#[test]
fn fallback_exact_subset_preserves_receipts_and_terminal_decision() {
    let fixture = Fixture::new();
    assert_eq!(fixture.store.status().owner_epoch, 1);
    let request = fixture.decide_request("allow");
    let grant = fixture.store.decide_fallback(request.clone(), 0).unwrap();
    assert_eq!(
        fixture.store.decide_fallback(request.clone(), 0).err(),
        Some("OFFLINE_FALLBACK_USED")
    );
    let result = fixture.consume(&grant).unwrap();
    assert_eq!(result.members.len(), 2);
    assert_ne!(
        result.members[0].source.verification_id,
        result.members[1].source.verification_id
    );
    assert_eq!(
        result.members[0].payload["field_resolution"]["complete_package_history"],
        true
    );
    assert_eq!(result.grant.state, "consumed");
    assert!(result.grant.consumed_at.is_some());
    assert!(!result.complete_query_result);
    assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_FALLBACK_USED"));
    assert_eq!(
        fixture.store.decide_fallback(request, 0).err(),
        Some("OFFLINE_FALLBACK_USED")
    );
    let mut unmatched = fixture.decide_request("allow");
    unmatched.intent.query.model = "EXACT_PRIVATE_MODEL missing".into();
    let grant = fixture.store.decide_fallback(unmatched, 0).unwrap();
    assert!(fixture.consume(&grant).unwrap().members.is_empty());
}

#[test]
fn fallback_decisions_do_not_read_body_and_audit_is_encrypted() {
    let fixture = Fixture::new();
    for entry in fs::read_dir(&fixture.root).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().is_some_and(|ext| ext == "pack") {
            fs::write(path, b"corrupt").unwrap();
        }
    }
    // A release sweep has already rejected the corrupt original. Decisions
    // remain metadata-only; consumption must durably burn its receipt before
    // the failed release/body gate rejects access.
    assert_eq!(
        fixture.store.sync_revalidate().unwrap().release_checks[0].state,
        "failed"
    );
    let denied_request = fixture.decide_request("deny");
    let denied = fixture
        .store
        .decide_fallback(denied_request.clone(), 0)
        .unwrap();
    assert_eq!(denied.state, "denied");
    assert_eq!(
        fixture.consume(&denied).err(),
        Some("OFFLINE_FALLBACK_USED")
    );
    assert_eq!(
        fixture.store.decide_fallback(denied_request, 0).err(),
        Some("OFFLINE_FALLBACK_USED")
    );
    let allowed = fixture.grant();
    assert_eq!(
        fixture.consume(&allowed).err(),
        Some("OFFLINE_RELEASE_VALIDATION_REQUIRED")
    );
    assert_eq!(
        fixture.consume(&allowed).err(),
        Some("OFFLINE_FALLBACK_USED")
    );
    let inner = fixture.store.lock().unwrap();
    let (sequence, encoded): (i64, Vec<u8>) = inner
        .connection
        .query_row(
            "SELECT sequence,value FROM fallback_audit ORDER BY sequence DESC LIMIT 1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    let clear = crypto::open(
        &inner.key,
        format!("offline-v1:qa-local-once:fallback-audit:{sequence}").as_bytes(),
        &encoded,
        MAX_METADATA_BYTES,
    )
    .unwrap();
    let receipt: FallbackGrant = serde_json::from_slice(&clear).unwrap();
    assert_eq!(receipt.state, "consumed");
    drop(inner);
    let catalog = fs::read(fixture.root.join("catalog.sqlite3")).unwrap();
    for canary in [
        b"EXACT_PRIVATE_MODEL".as_slice(),
        b"synthetic-source",
        allowed.id.as_bytes(),
    ] {
        assert!(!catalog.windows(canary.len()).any(|window| window == canary));
    }
}

#[test]
fn fallback_compares_actual_intent_fields_and_consumes_on_mismatch() {
    let fixture = Fixture::new();
    for field in 0..8 {
        let grant = fixture.grant();
        let mut intent = grant.intent.clone();
        match field {
            0 => intent.attempt_id = uuid::Uuid::new_v4().to_string(),
            1 => intent.source_id = "other-source".into(),
            2 => intent.source_access_generation += 1,
            3 => intent.query.model.push_str(" Plus"),
            4 => intent.query.size = None,
            5 => intent.query_fingerprint = "b".repeat(64),
            6 => intent.failure.reason = "api_network_unavailable".into(),
            _ => {
                intent.failure = FallbackFailure {
                    scope: "source_response".into(),
                    reason: "upstream_timeout".into(),
                    query_id: Some(uuid::Uuid::new_v4().to_string()),
                }
            }
        }
        assert_eq!(
            fixture
                .store
                .consume_fallback(
                    FallbackConsumeRequest {
                        grant_id: grant.id.clone(),
                        intent
                    },
                    0
                )
                .err(),
            Some("OFFLINE_FALLBACK_MISMATCH")
        );
        assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_FALLBACK_USED"));
    }
    let mut invalid = serde_json::to_value(&fixture.decide_request("allow").intent).unwrap();
    invalid["query"].as_object_mut().unwrap().remove("size");
    assert!(serde_json::from_value::<FallbackIntent>(invalid).is_err());
    let mut unsupported = fixture.decide_request("allow");
    unsupported
        .intent
        .filters
        .push(json!({"field":"xl","op":"eq","value":true}));
    assert_eq!(
        fixture.store.decide_fallback(unsupported, 0).err(),
        Some("OFFLINE_FALLBACK_UNSUPPORTED")
    );
}

#[test]
fn fallback_monotonic_wall_rollback_page_and_revoke_are_terminal() {
    let fixture = Fixture::new();
    for mode in 0..3 {
        let grant = fixture.grant();
        {
            let mut inner = fixture.store.lock().unwrap();
            let pending = inner.fallback.pending.get_mut(&grant.id).unwrap();
            match mode {
                0 => pending.issued = Instant::now() - Duration::from_secs(301),
                1 => pending.wall = Utc::now() - chrono::Duration::seconds(301),
                _ => pending.wall = Utc::now() + chrono::Duration::seconds(60),
            }
        }
        assert_eq!(
            fixture.consume(&grant).err(),
            Some("OFFLINE_FALLBACK_EXPIRED")
        );
        assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_FALLBACK_USED"));
    }
    let grant = fixture.grant();
    fixture.store.invalidate_fallback_page();
    assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_FALLBACK_USED"));
    let request = fixture.decide_request("allow");
    let grant = fixture.store.decide_fallback(request.clone(), 1).unwrap();
    fixture
        .store
        .revoke_fallback(FallbackRevokeRequest {
            grant_id: grant.id.clone(),
        })
        .unwrap();
    assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_FALLBACK_USED"));
    assert_eq!(
        fixture.store.decide_fallback(request, 1).err(),
        Some("OFFLINE_FALLBACK_USED")
    );
}

#[test]
fn fallback_pending_capacity_audit_ring_and_attempt_memory_are_bounded() {
    let fixture = Fixture::new();
    let grants: Vec<_> = (0..16).map(|_| fixture.grant()).collect();
    assert_eq!(
        fixture
            .store
            .decide_fallback(fixture.decide_request("allow"), 0)
            .err(),
        Some("OFFLINE_FALLBACK_CAPACITY")
    );
    for grant in grants {
        fixture
            .store
            .revoke_fallback(FallbackRevokeRequest { grant_id: grant.id })
            .unwrap();
    }
    for _ in 16..1024 {
        fixture
            .store
            .decide_fallback(fixture.decide_request("deny"), 0)
            .unwrap();
    }
    let inner = fixture.store.lock().unwrap();
    assert_eq!(
        inner
            .connection
            .query_row("SELECT count(*) FROM fallback_audit", [], |row| row
                .get::<_, i64>(0))
            .unwrap(),
        64
    );
    assert!(inner.fallback.pending.is_empty());
    assert_eq!(inner.fallback.attempts.len(), 1024);
    drop(inner);
    assert_eq!(
        fixture
            .store
            .decide_fallback(fixture.decide_request("deny"), 0)
            .err(),
        Some("OFFLINE_FALLBACK_CAPACITY")
    );
}

#[test]
fn fallback_owner_reset_unlock_replacement_restart_and_audit_failure_reject() {
    let fixture = Fixture::new();
    let grant = fixture.grant();
    let second =
        Store::with_keys(fixture.root.clone(), "qa-local-once".into(), &fixture.keys).unwrap();
    assert_eq!(
        second
            .consume_fallback(
                FallbackConsumeRequest {
                    grant_id: grant.id.clone(),
                    intent: grant.intent.clone()
                },
                0
            )
            .err(),
        Some("OFFLINE_FALLBACK_USED")
    );
    second.reset_owner().unwrap();
    assert_eq!(
        fixture.consume(&grant).err(),
        Some("OFFLINE_FALLBACK_MISMATCH")
    );
    fixture
        .store
        .unlock(UnlockRequest {
            slot_id: fixture.slot.slot_id.clone(),
            expected_generation: fixture.slot.generation,
            allow_previous_owner: true,
        })
        .unwrap();
    assert_eq!(
        fixture
            .store
            .decide_fallback(fixture.decide_request("allow"), 0)
            .err(),
        Some("OFFLINE_OWNER_LOCKED")
    );
    drop(second);
    let fixture = Fixture::new();
    let grant = fixture.grant();
    let mut request = fixture.install.clone();
    request.expected_generation = fixture.slot.generation;
    let ticket = fixture.store.begin_install(&request).unwrap();
    fixture
        .store
        .install(
            &request,
            fixture.descriptor.clone(),
            Zeroizing::new(fixture.bytes.clone()),
            ticket,
        )
        .unwrap();
    assert_eq!(
        fixture.consume(&grant).err(),
        Some("OFFLINE_STALE_GENERATION")
    );
    let fixture = Fixture::new();
    let grant = fixture.grant();
    for entry in fs::read_dir(&fixture.root).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().is_some_and(|ext| ext == "pack") {
            fs::write(path, b"corrupt").unwrap();
        }
    }
    fixture.store.lock().unwrap().connection.execute_batch("CREATE TRIGGER reject_fallback_audit BEFORE INSERT ON fallback_audit BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END;").unwrap();
    assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_STORE_FAILED"));
    assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_FALLBACK_USED"));
}

#[test]
fn fallback_profile_lock_covers_other_store_mutations_but_not_download_ticket() {
    let fixture = Fixture::new();
    let second =
        Store::with_keys(fixture.root.clone(), "qa-local-once".into(), &fixture.keys).unwrap();
    let lock = fixture.store.fallback_profile_lock().unwrap();
    assert_eq!(second.reset_owner().err(), Some("OFFLINE_INSTALL_BUSY"));
    assert_eq!(
        second
            .remove(SlotRequest {
                slot_id: fixture.slot.slot_id.clone(),
                expected_generation: 1
            })
            .err(),
        Some("OFFLINE_INSTALL_BUSY")
    );
    assert_eq!(
        second
            .unlock(UnlockRequest {
                slot_id: fixture.slot.slot_id.clone(),
                expected_generation: 1,
                allow_previous_owner: true
            })
            .err(),
        Some("OFFLINE_INSTALL_BUSY")
    );
    let mut request = fixture.install.clone();
    request.expected_generation = 1;
    let ticket = second.begin_install(&request).unwrap();
    assert_eq!(
        second
            .install(
                &request,
                fixture.descriptor.clone(),
                Zeroizing::new(fixture.bytes.clone()),
                ticket
            )
            .err(),
        Some("OFFLINE_INSTALL_BUSY")
    );
    drop(lock);
    let ticket = second.begin_install(&request).unwrap();
    second.reset_owner().unwrap();
    assert_eq!(
        second
            .install(
                &request,
                fixture.descriptor.clone(),
                Zeroizing::new(fixture.bytes.clone()),
                ticket
            )
            .err(),
        Some("OFFLINE_OWNER_CHANGED")
    );
}

#[test]
fn fallback_complete_response_limit_burns_without_truncating_matching_member() {
    let mut fixture = Fixture::new();
    let mut envelope: Value = serde_json::from_slice(&fixture.bytes).unwrap();
    let member = envelope["members"][0].clone();
    let document = envelope["documents"][1].clone();
    envelope["members"] = json!([member]);
    envelope["documents"] = json!([document]);
    envelope["contexts"] = json!([]);
    envelope["members"][0]["payload"]["variant"]["facts"]["padding"] =
        json!(["", "", "", "", "", "", "", "", ""]);
    let baseline = serde_json::to_vec(&envelope).unwrap().len();
    let mut remaining = MAX_PACKAGE_BYTES - baseline;
    for value in envelope["members"][0]["payload"]["variant"]["facts"]["padding"]
        .as_array_mut()
        .unwrap()
    {
        let count = remaining.min(1_000_000);
        *value = "x".repeat(count).into();
        remaining -= count;
    }
    assert_eq!(remaining, 0);
    let bytes = serde_json::to_vec(&envelope).unwrap();
    assert_eq!(bytes.len(), MAX_PACKAGE_BYTES);
    let mut descriptor = fixture.descriptor.clone();
    descriptor.counts.distinct_evidence = 1;
    descriptor.counts.searchable_documents = 1;
    descriptor.counts.garage_profiles = 0;
    descriptor.sha256 = crypto::hash(&bytes);
    descriptor.byte_count = bytes.len() as u64;
    let mut request = fixture.install.clone();
    request.expected_generation = 1;
    request.expected_sha256 = descriptor.sha256.clone();
    request.expected_byte_count = descriptor.byte_count;
    let ticket = fixture.store.begin_install(&request).unwrap();
    fixture.slot = fixture
        .store
        .install(&request, descriptor, Zeroizing::new(bytes), ticket)
        .unwrap();
    let grant = fixture.grant();
    assert_eq!(
        fixture.consume(&grant).err(),
        Some("OFFLINE_FALLBACK_CAPACITY")
    );
    assert_eq!(fixture.consume(&grant).err(), Some("OFFLINE_FALLBACK_USED"));
}

#[test]
fn fallback_concurrent_consumers_return_parameters_exactly_once() {
    let fixture = Fixture::new();
    let grant = fixture.grant();
    let barrier = Arc::new(Barrier::new(3));
    let mut handles = Vec::new();
    for _ in 0..2 {
        let store = fixture.store.clone();
        let barrier = barrier.clone();
        let grant = grant.clone();
        handles.push(std::thread::spawn(move || {
            barrier.wait();
            store
                .consume_fallback(
                    FallbackConsumeRequest {
                        grant_id: grant.id,
                        intent: grant.intent,
                    },
                    0,
                )
                .map(|result| result.members.len())
        }));
    }
    barrier.wait();
    let results: Vec<_> = handles
        .into_iter()
        .map(|handle| handle.join().unwrap())
        .collect();
    assert_eq!(results.iter().filter(|result| **result == Ok(2)).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| **result == Err("OFFLINE_FALLBACK_USED"))
            .count(),
        1
    );
}
