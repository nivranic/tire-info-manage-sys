use super::*;
use crate::offline::crypto::KeyStore;
use serde_json::{json, Value};

#[derive(Default)]
struct Keys(Mutex<Option<[u8; 32]>>);
impl KeyStore for Keys {
    fn load(&self) -> NativeResult<Option<Zeroizing<[u8; 32]>>> {
        Ok(self.0.lock().unwrap().map(Zeroizing::new))
    }
    fn save(&self, key: &[u8; 32]) -> NativeResult<()> {
        *self.0.lock().unwrap() = Some(*key);
        Ok(())
    }
}
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!("ti-rust48-sync-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn install(store: &Store) -> Slot {
    let (request, descriptor, bytes) = crate::offline::tests::sample();
    let ticket = store.begin_install(&request).unwrap();
    store
        .install(&request, descriptor, Zeroizing::new(bytes), ticket)
        .unwrap()
}
fn preview(store: &Store, slot: &Slot) -> SyncPreview {
    let status = store.status();
    store
        .sync_preview(SyncPreviewRequest {
            slot_id: slot.slot_id.clone(),
            expected_generation: slot.generation,
            expected_profile_id: status.profile_id.unwrap(),
            expected_owner_epoch: status.owner_epoch,
            interval_seconds: 900,
            conditions: Conditions {
                network: "any".into(),
                power: "any".into(),
            },
        })
        .unwrap()
}
fn apply(store: &Store, preview: SyncPreview) -> SyncPolicy {
    store
        .sync_apply(SyncApplyRequest {
            preview_id: preview.preview_id,
            expected_fingerprint: preview.fingerprint,
            expected_policy_revision: preview.expected_policy_revision,
            allow_continuous_history_updates: true,
        })
        .unwrap()
}
fn begin(store: &Store, policy: &SyncPolicy) -> SyncTicket {
    store
        .sync_begin(
            SyncRunRequest {
                policy_id: policy.policy_id.clone(),
                expected_policy_revision: policy.policy_revision,
                trigger: "manual".into(),
            },
            Sample::default(),
        )
        .unwrap()
}
fn staged(store: &Store, ticket: &SyncTicket) -> StagedInstall {
    let (mut request, mut descriptor, bytes) = crate::offline::tests::sample();
    let mut raw: Value = serde_json::from_slice(&bytes).unwrap();
    raw["base_pack_id"] = json!(ticket.descriptor.id);
    let bytes = serde_json::to_vec(&raw).unwrap();
    descriptor.base_pack_id = Some(ticket.descriptor.id.clone());
    descriptor.sha256 = crypto::hash(&bytes);
    descriptor.byte_count = bytes.len() as u64;
    request.slot_id = ticket.policy.slot_id.clone();
    request.expected_generation = ticket.policy.binding.generation;
    request.expected_sha256 = descriptor.sha256.clone();
    request.expected_byte_count = descriptor.byte_count;
    store
        .sync_stage(
            ticket,
            "confirming",
            Some((
                &descriptor.plan_id,
                &descriptor.plan_fingerprint,
                &uuid::Uuid::new_v4().to_string(),
            )),
            Some(&descriptor.id),
        )
        .unwrap();
    let install = store.begin_install(&request).unwrap();
    store
        .stage_install(&request, descriptor, Zeroizing::new(bytes), install)
        .unwrap()
}

#[test]
fn preview_is_separate_one_shot_consent_and_stale_revision_is_rejected() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    assert!(store.sync_status().unwrap().policies.is_empty());
    let first = preview(&store, &slot);
    let second = preview(&store, &slot);
    assert_eq!(
        store
            .sync_apply(SyncApplyRequest {
                preview_id: first.preview_id.clone(),
                expected_fingerprint: first.fingerprint.clone(),
                expected_policy_revision: 0,
                allow_continuous_history_updates: false
            })
            .err(),
        Some("OFFLINE_SYNC_CONSENT_REQUIRED")
    );
    let policy = apply(&store, first.clone());
    assert_eq!(policy.policy_revision, 1);
    assert_eq!(
        store
            .sync_apply(SyncApplyRequest {
                preview_id: first.preview_id,
                expected_fingerprint: first.fingerprint,
                expected_policy_revision: 0,
                allow_continuous_history_updates: true
            })
            .err(),
        Some("OFFLINE_SYNC_PREVIEW_USED")
    );
    assert_eq!(
        store
            .sync_apply(SyncApplyRequest {
                preview_id: second.preview_id,
                expected_fingerprint: second.fingerprint,
                expected_policy_revision: 0,
                allow_continuous_history_updates: true
            })
            .err(),
        Some("OFFLINE_SYNC_REVISION_CONFLICT")
    );
}

#[test]
fn original_previous_owner_cannot_authorize_or_run_even_after_explicit_unlock() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    let policy = apply(&store, preview(&store, &slot));
    store.reset_owner().unwrap();
    let unlocked = store
        .unlock(UnlockRequest {
            slot_id: slot.slot_id.clone(),
            expected_generation: slot.generation,
            allow_previous_owner: true,
        })
        .unwrap();
    assert!(!unlocked.locked && unlocked.previous_owner);
    let status = store.status();
    assert_eq!(
        store
            .sync_preview(SyncPreviewRequest {
                slot_id: slot.slot_id,
                expected_generation: slot.generation,
                expected_profile_id: status.profile_id.unwrap(),
                expected_owner_epoch: status.owner_epoch,
                interval_seconds: 900,
                conditions: Conditions {
                    network: "any".into(),
                    power: "any".into()
                }
            })
            .err(),
        Some("OFFLINE_SYNC_PREVIOUS_OWNER")
    );
    assert_eq!(store.sync_status().unwrap().policies[0].state, "revoked");
    assert!(store
        .sync_begin(
            SyncRunRequest {
                policy_id: policy.policy_id,
                expected_policy_revision: policy.policy_revision,
                trigger: "manual".into()
            },
            Sample::default()
        )
        .is_err());
}

#[test]
fn pause_and_revoke_are_short_and_staged_run_cannot_publish() {
    for revoke in [false, true] {
        let root = Root::new();
        let keys = Keys::default();
        let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
        let slot = install(&store);
        let policy = apply(&store, preview(&store, &slot));
        let ticket = begin(&store, &policy);
        let staged = staged(&store, &ticket);
        let started = Instant::now();
        store
            .sync_change_policy(
                SyncPolicyRequest {
                    policy_id: policy.policy_id,
                    expected_policy_revision: 1,
                },
                revoke,
            )
            .unwrap();
        assert!(started.elapsed() < Duration::from_secs(2));
        assert_eq!(
            store.sync_commit(&ticket, staged, Sample::default()).err(),
            Some("OFFLINE_SYNC_LEASE_CHANGED")
        );
        assert_eq!(store.list().unwrap().items[0].generation, slot.generation);
        assert_eq!(store.sync_status().unwrap().runs[0].state, "cancelled");
    }
}

#[test]
fn final_publish_checks_conditions_and_preserves_previous_slot() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    let mut p = preview(&store, &slot);
    let mut inner = store.lock().unwrap();
    let pending = inner.sync.previews.get_mut(&p.preview_id).unwrap();
    pending.preview.conditions.network = "wifi".into();
    pending.preview.fingerprint.clear();
    pending.preview.fingerprint = crypto::hash(&serialize(&pending.preview).unwrap());
    p = pending.preview.clone();
    drop(inner);
    let policy = apply(&store, p);
    let ticket = store
        .sync_begin(
            SyncRunRequest {
                policy_id: policy.policy_id,
                expected_policy_revision: 1,
                trigger: "manual".into(),
            },
            Sample {
                wifi: Some(true),
                ..Sample::default()
            },
        )
        .unwrap();
    let staged = staged(&store, &ticket);
    assert_eq!(
        store
            .sync_commit(
                &ticket,
                staged,
                Sample {
                    wifi: None,
                    ..Sample::default()
                }
            )
            .err(),
        Some("OFFLINE_SYNC_CONDITIONS_UNMET")
    );
    assert_eq!(store.list().unwrap().items[0].sha256, slot.sha256);
}

#[test]
fn changing_native_conditions_immediately_before_commit_rolls_back_publish_and_no_change() {
    for no_change in [false, true] {
        let root = Root::new();
        let keys = Keys::default();
        let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
        let slot = install(&store);
        let mut p = preview(&store, &slot);
        let mut inner = store.lock().unwrap();
        let pending = inner.sync.previews.get_mut(&p.preview_id).unwrap();
        pending.preview.conditions.network = "wifi".into();
        pending.preview.fingerprint.clear();
        pending.preview.fingerprint = crypto::hash(&serialize(&pending.preview).unwrap());
        p = pending.preview.clone();
        drop(inner);
        let policy = apply(&store, p);
        let ticket = store
            .sync_begin(
                SyncRunRequest {
                    policy_id: policy.policy_id,
                    expected_policy_revision: 1,
                    trigger: "manual".into(),
                },
                Sample {
                    wifi: Some(true),
                    ..Sample::default()
                },
            )
            .unwrap();
        let staged = (!no_change).then(|| staged(&store, &ticket));
        let before = store.sync_status().unwrap();
        let mut observed = 0;
        let observe = || {
            observed += 1;
            Sample {
                wifi: (observed == 1).then_some(true),
                ..Sample::default()
            }
        };
        let result = match staged {
            Some(staged) => store.sync_commit_observed(&ticket, staged, observe),
            None => store.sync_finish_observed(&ticket, "no_change", None, observe),
        };
        assert_eq!(result.err(), Some("OFFLINE_SYNC_CONDITIONS_UNMET"));
        assert_eq!(observed, 2);
        let after = store.sync_status().unwrap();
        assert!(same(&before.policies, &after.policies));
        assert!(same(&before.runs, &after.runs));
        assert!(same(&before.release_checks, &after.release_checks));
        assert_eq!(store.list().unwrap().items[0].sha256, slot.sha256);
    }
}

#[test]
fn slot_binding_release_audit_and_run_success_commit_atomically_without_new_consent_revision() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    let policy = apply(&store, preview(&store, &slot));
    let ticket = begin(&store, &policy);
    let staged = staged(&store, &ticket);
    let expected_sha = staged.slot.sha256.clone();
    let result = store
        .sync_commit(&ticket, staged, Sample::default())
        .unwrap();
    assert_eq!(result.state, "succeeded");
    assert_eq!(result.after_generation, Some(slot.generation + 1));
    let status = store.sync_status().unwrap();
    assert_eq!(status.policies[0].policy_revision, 1);
    assert_eq!(status.policies[0].binding.binding_revision, 2);
    assert_eq!(status.policies[0].binding.sha256, expected_sha);
    assert_eq!(
        status.release_checks[0].sha256.as_deref(),
        Some(expected_sha.as_str())
    );
    assert_eq!(
        store.list().unwrap().items[0].generation,
        status.policies[0].binding.generation
    );
}

#[test]
fn catalog_failure_after_ciphertext_fsync_rolls_back_slot_binding_and_run_together() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    let policy = apply(&store, preview(&store, &slot));
    let ticket = begin(&store, &policy);
    let staged = staged(&store, &ticket);
    let before = store.sync_status().unwrap();
    store.lock().unwrap().connection.execute_batch("CREATE TRIGGER rust48_fail_publish BEFORE UPDATE ON slots BEGIN SELECT RAISE(ABORT,'synthetic publication fault'); END;").unwrap();
    assert!(store
        .sync_commit(&ticket, staged, Sample::default())
        .is_err());
    let after = store.sync_status().unwrap();
    assert_eq!(store.list().unwrap().items[0].sha256, slot.sha256);
    assert!(same(&before.policies, &after.policies));
    assert!(same(&before.runs, &after.runs));
    assert!(same(&before.release_checks, &after.release_checks));
}

#[test]
fn process_restart_interrupts_journal_and_pauses_without_replay_or_slot_change() {
    for stage in ["preparing", "confirming"] {
        let root = Root::new();
        let keys = Keys::default();
        let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
        let slot = install(&store);
        let policy = apply(&store, preview(&store, &slot));
        let ticket = begin(&store, &policy);
        let plan = uuid::Uuid::new_v4().to_string();
        let key = uuid::Uuid::new_v4().to_string();
        store
            .sync_stage(
                &ticket,
                stage,
                (stage == "confirming").then_some((
                    plan.as_str(),
                    "a".repeat(64).as_str(),
                    key.as_str(),
                )),
                None,
            )
            .unwrap();
        drop(ticket);
        drop(store);
        let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
        let status = store.sync_status().unwrap();
        assert_eq!(status.runs[0].state, "interrupted");
        assert_eq!(status.policies[0].state, "paused");
        assert_eq!(status.policies[0].policy_revision, 2);
        assert_eq!(store.list().unwrap().items[0].sha256, slot.sha256);
    }
}

#[test]
fn release_sweep_checks_locked_owner_and_every_good_slot_when_metadata_is_corrupt() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let first = install(&store);
    let second = install(&store);
    store.reset_owner().unwrap();
    store
        .lock()
        .unwrap()
        .connection
        .execute(
            "UPDATE slots SET metadata=?1 WHERE id=?2",
            params![vec![0u8; 48], first.slot_id],
        )
        .unwrap();
    let status = store.sync_revalidate().unwrap();
    assert_eq!(status.release_checks.len(), 2);
    let bad = status
        .release_checks
        .iter()
        .find(|c| c.slot_id == first.slot_id)
        .unwrap();
    assert_eq!(bad.state, "failed");
    assert_eq!(bad.sha256, None);
    let good = status
        .release_checks
        .iter()
        .find(|c| c.slot_id == second.slot_id)
        .unwrap();
    assert_eq!(good.state, "passed");
    let inner = store.lock().unwrap();
    let row = Store::row(&inner.connection, &second.slot_id)
        .unwrap()
        .unwrap();
    let metadata = store.metadata(&row, &inner.key).unwrap();
    assert_eq!(metadata.unlocked_epoch, None);
    drop(inner);
    store
        .remove(SlotRequest {
            slot_id: first.slot_id,
            expected_generation: first.generation,
        })
        .unwrap();
}

#[test]
fn release_failure_blocks_cached_read_and_corrupt_sidecar_still_allows_exact_removal() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    let request = SearchRequest {
        slot_id: slot.slot_id.clone(),
        expected_generation: slot.generation,
        query: String::new(),
        kind: None,
        limit: 10,
        offset: 0,
    };
    assert_eq!(store.search(request).unwrap().total, 1);
    let inner = store.lock().unwrap();
    let row = Store::row(&inner.connection, &slot.slot_id)
        .unwrap()
        .unwrap();
    let path = store.root.join(format!("{}.pack", row.file_id.unwrap()));
    drop(inner);
    fs::write(&path, b"synthetic corrupt ciphertext").unwrap();
    assert_eq!(
        store.sync_revalidate().unwrap().release_checks[0].state,
        "failed"
    );
    assert!(store
        .search(SearchRequest {
            slot_id: slot.slot_id.clone(),
            expected_generation: slot.generation,
            query: String::new(),
            kind: None,
            limit: 10,
            offset: 0
        })
        .is_err());
    store
        .lock()
        .unwrap()
        .connection
        .execute(
            "UPDATE sync_control SET value=?1 WHERE id=1",
            [vec![0u8; 48]],
        )
        .unwrap();
    assert_eq!(
        store.sync_status().err(),
        Some("OFFLINE_SYNC_STATE_CORRUPT")
    );
    store
        .remove(SlotRequest {
            slot_id: slot.slot_id,
            expected_generation: slot.generation,
        })
        .unwrap();
    assert!(!path.exists());
}

#[test]
fn release_build_change_closes_cached_reads_until_full_original_revalidation() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    let inner = store.lock().unwrap();
    let mut state = store.sync_load(&inner.connection, &inner.key).unwrap();
    state.release_checks[0].host_build = "older-host".into();
    store
        .sync_save(&inner.connection, &inner.key, &state)
        .unwrap();
    drop(inner);
    assert_eq!(
        store
            .sync_preview(SyncPreviewRequest {
                slot_id: slot.slot_id.clone(),
                expected_generation: slot.generation,
                expected_profile_id: store.status().profile_id.unwrap(),
                expected_owner_epoch: 1,
                interval_seconds: 900,
                conditions: Conditions {
                    network: "any".into(),
                    power: "any".into()
                }
            })
            .err(),
        Some("OFFLINE_RELEASE_VALIDATION_REQUIRED")
    );
    store.sync_revalidate().unwrap();
    assert_eq!(preview(&store, &slot).generation, slot.generation);
}

#[test]
fn one_persistent_profile_lease_and_bounded_run_history_are_enforced() {
    let root = Root::new();
    let keys = Keys::default();
    let store = Store::with_keys(root.0.clone(), "rust48".into(), &keys).unwrap();
    let slot = install(&store);
    let policy = apply(&store, preview(&store, &slot));
    let ticket = begin(&store, &policy);
    assert_eq!(
        store
            .sync_begin(
                SyncRunRequest {
                    policy_id: policy.policy_id.clone(),
                    expected_policy_revision: 1,
                    trigger: "manual".into()
                },
                Sample::default()
            )
            .err()
            .map(|e| e),
        Some("OFFLINE_SYNC_BUSY")
    );
    store
        .sync_finish(&ticket, "no_change", None, Sample::default())
        .unwrap();
    drop(ticket);
    for _ in 0..70 {
        let ticket = begin(&store, &policy);
        store
            .sync_finish(&ticket, "no_change", None, Sample::default())
            .unwrap();
    }
    assert_eq!(store.sync_status().unwrap().runs.len(), 64);
}

#[test]
fn full_four_domain_original_api_fixture_has_fixed_explicit_receipts_and_exact_semantic_digest() {
    let bytes = include_bytes!("../../test-fixtures/round48-base-pack.json");
    let descriptor: Descriptor = serde_json::from_slice(include_bytes!(
        "../../test-fixtures/round48-base-descriptor.json"
    ))
    .unwrap();
    let envelope = wire::package(bytes, &descriptor).unwrap();
    let kinds: std::collections::HashSet<_> = envelope
        .members
        .iter()
        .map(|m| m.reference.kind())
        .collect();
    assert_eq!(kinds.len(), 4);
    let scope = derive_scope(&envelope).unwrap();
    assert_eq!(scope.references.len(), envelope.scope.references.len());
    let result: Value = serde_json::from_slice(include_bytes!(
        "../../test-fixtures/round48-planned-update.json"
    ))
    .unwrap();
    assert_eq!(
        crate::offline::sync::semantic_digest(bytes).unwrap(),
        result["base_semantic_digest"]
    );
    let candidate = include_bytes!("../../test-fixtures/round48-candidate-pack.json");
    let descriptor: Descriptor = serde_json::from_slice(include_bytes!(
        "../../test-fixtures/round48-candidate-descriptor.json"
    ))
    .unwrap();
    wire::package(candidate, &descriptor).unwrap();
    assert_eq!(
        crate::offline::sync::semantic_digest(candidate).unwrap(),
        result["current_semantic_digest"]
    );
}
