use super::*;
use crate::{bridge::Bridge, security::LaunchConfig, session::SessionStore};
use std::sync::Barrier;

#[test]
fn actual_private_loopback_201_deny_observes_request_query_and_session_rotation_ends_ledger() {
    use crate::security::ApiRequest;
    use base64::{engine::general_purpose::STANDARD, Engine};
    use std::io::{Read, Write};
    let f = Fixture::new("legacy");
    let store =
        Arc::new(Store::with_keys(f.root.clone(), "qa-fallback-v2".into(), &f.keys).unwrap());
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let query = uuid::Uuid::new_v4().to_string();
    let expected = query.clone();
    let server = std::thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let count = socket.read(&mut chunk).unwrap();
            assert!(count > 0);
            bytes.extend_from_slice(&chunk[..count]);
            if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                let headers = std::str::from_utf8(&bytes[..end]).unwrap();
                let length = headers
                    .lines()
                    .find_map(|v| {
                        v.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .map(|v| v.trim().parse::<usize>().unwrap())
                    })
                    .unwrap();
                if bytes.len() >= end + 4 + length {
                    assert!(headers.starts_with("POST /v1/fallback-consents "));
                    let body: Value =
                        serde_json::from_slice(&bytes[end + 4..end + 4 + length]).unwrap();
                    assert_eq!(body["query_id"], expected);
                    break;
                }
            }
        }
        // This is the actual API response shape: it intentionally has no query_id.
        let body=json!({"id":uuid::Uuid::new_v4().to_string(),"decision":"deny","scope":"once","expires_at":"2026-10-01T10:00:00Z"}).to_string();
        socket.write_all(format!("HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).as_bytes()).unwrap();
    });
    let bridge = Arc::new(
        Bridge::new(
            LaunchConfig {
                port,
                namespace: "qa-denial-http".into(),
            },
            Arc::new(SessionMemory),
        )
        .unwrap(),
    );
    bridge.bind_fallback_store(&store).unwrap();
    let runtime = tokio::runtime::Runtime::new().unwrap();
    runtime.block_on(async {
        bridge.session.data.lock().await.bootstrapped = true;
        let response = bridge
            .request(ApiRequest {
                id: uuid::Uuid::new_v4().to_string(),
                path: "/v1/fallback-consents".into(),
                method: "POST".into(),
                headers: std::collections::BTreeMap::from([(
                    "content-type".into(),
                    "application/json".into(),
                )]),
                body_base64: Some(STANDARD.encode(
                    json!({"query_id":query,"decision":"deny","scope":"once"}).to_string(),
                )),
            })
            .await
            .unwrap();
        assert_eq!(response.status, 201);
    });
    server.join().unwrap();
    let mut request = f.legacy();
    request.intent.failure = FallbackFailure {
        scope: "source_response".into(),
        reason: "upstream_timeout".into(),
        query_id: Some(query.clone()),
    };
    assert_eq!(
        store.decide_fallback(request.clone(), 0).unwrap_err(),
        "OFFLINE_FALLBACK_NEVER"
    );
    runtime.block_on(async {
        {
            let mut data = bridge.session.data.lock().await;
            data.cookie = Some(uuid::Uuid::new_v4().to_string());
            data.generation += 1;
        }
        let fence = Arc::new(bridge.sync_fence().await.unwrap());
        let bind = fence.clone();
        let store = store.clone();
        bridge
            .sync_publish(fence, move || store.fallback_bind_denial_session(bind))
            .await
            .unwrap();
    });
    request.intent.attempt_id = uuid::Uuid::new_v4().to_string();
    assert!(store.decide_fallback(request, 0).is_ok());
    drop(bridge);
    drop(store);
}

fn reapprove(f: &Fixture, policy: &Value) -> NativeResult<Value> {
    let mut choice = f.choice("ask");
    choice["policy_id"] = policy["policy_id"].clone();
    choice["expected_policy_revision"] = policy["policy_revision"].clone();
    let p = f.store.fallback_policy_preview_v2(choice, 0)?;
    f.store.fallback_policy_apply_v2(json!({"preview_id":p["preview_id"],"expected_fingerprint":p["fingerprint"],"expected_policy_revision":p["expected_policy_revision"],"allow_continuous_history_fallback":true}),0)
}

#[test]
fn retention_nonrevoked_sixteen_archives_sixtyfour_and_reapproves_retained_revoked() {
    let f = Fixture::new("nonempty");
    let mut first = None;
    for index in 0..66 {
        let p = f.policy("ask");
        let revoked = f
            .store
            .fallback_policy_change_v2(
                json!({"policy_id":p["policy_id"],"expected_policy_revision":p["policy_revision"]}),
                true,
            )
            .unwrap();
        if index == 0 {
            first = Some(revoked);
        }
    }
    let status = f.store.fallback_status_v2().unwrap();
    assert_eq!(status["policies"].as_array().unwrap().len(), 64);
    assert_eq!(
        reapprove(&f, first.as_ref().unwrap()).unwrap_err(),
        "OFFLINE_FALLBACK_POLICY_CHANGED"
    );
    let retained = status["policies"][63].clone();
    let revived = reapprove(&f, &retained).unwrap();
    assert_eq!(
        revived["policy_revision"].as_u64().unwrap(),
        retained["policy_revision"].as_u64().unwrap() + 1
    );
    for _ in 0..15 {
        f.policy("ask");
    }
    assert_eq!(
        f.store
            .fallback_policy_preview_v2(f.choice("ask"), 0)
            .unwrap_err(),
        "OFFLINE_FALLBACK_CAPACITY"
    );
    let status = f.store.fallback_status_v2().unwrap();
    let other = status["policies"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["state"] == "revoked")
        .unwrap();
    assert_eq!(
        reapprove(&f, other).unwrap_err(),
        "OFFLINE_FALLBACK_CAPACITY"
    );
    let paused=f.store.fallback_policy_change_v2(json!({"policy_id":revived["policy_id"],"expected_policy_revision":revived["policy_revision"]}),false).unwrap();
    assert_eq!(
        f.store
            .fallback_policy_preview_v2(f.choice("ask"), 0)
            .unwrap_err(),
        "OFFLINE_FALLBACK_CAPACITY"
    );
    assert_eq!(reapprove(&f, &paused).unwrap()["state"], "enabled");
    let inner = f.store.lock().unwrap();
    let state = f
        .store
        .fallback_policy_load(&inner.connection, &inner.key)
        .unwrap();
    assert_eq!(state.policies.len(), 64);
    assert_eq!(state.nonrevoked(), 16);
    assert_eq!(state.permission_observations.len(), 64);
}

#[test]
fn retention_compacts_only_oldest_revoked_timestamp_then_id_and_private_sidecar_exceeds_old_bound()
{
    let f = Fixture::new("nonempty");
    let template = f.policy("source_allow");
    let authority = f.authority();
    let inner = f.store.lock().unwrap();
    let mut state = f
        .store
        .fallback_policy_load(&inner.connection, &inner.key)
        .unwrap();
    state.policies.clear();
    state.permission_observations.clear();
    for index in 0..65 {
        let mut p = template.clone();
        let id = format!("00000000-0000-4000-8000-{index:012}");
        p["policy_id"] = json!(id);
        p["state"] = json!(if index == 0 { "paused" } else { "revoked" });
        p["updated_at"] = json!("2026-10-01T00:00:00Z");
        state
            .permission_observations
            .insert(id, Store::permission_snapshot(&p["scope"], &authority));
        state.policies.push(p);
    }
    state.compact().unwrap();
    assert_eq!(state.policies.len(), 64);
    assert!(state
        .policies
        .iter()
        .any(|p| p["policy_id"] == "00000000-0000-4000-8000-000000000000"));
    assert!(!state
        .policies
        .iter()
        .any(|p| p["policy_id"] == "00000000-0000-4000-8000-000000000001"));
    assert!(serde_json::to_vec(&state).unwrap().len() > MAX_METADATA_BYTES);
    f.store
        .fallback_policy_save(&inner.connection, &inner.key, &state)
        .unwrap();
    assert_eq!(
        f.store
            .fallback_policy_load(&inner.connection, &inner.key)
            .unwrap()
            .policies
            .len(),
        64
    );
}

#[test]
fn owner_reset_revokes_all_old_epoch_modes_atomically_releases_quota_and_keeps_archive() {
    let f = Fixture::new("nonempty");
    for mode in [
        "ask",
        "never",
        "source_allow",
        "session_allow",
        "query_allow",
    ] {
        f.policy(mode);
    }
    let old_runtime = f.authority()["runtime_session_id"].clone();
    let old_epoch = f.authority()["owner_epoch"].as_u64().unwrap();
    f.store.reset_owner().unwrap();
    let status = f.store.fallback_status_v2().unwrap();
    assert_eq!(status["authority"]["state"], "unknown");
    assert_ne!(status["authority"]["runtime_session_id"], old_runtime);
    assert!(status["policies"].as_array().unwrap().is_empty());
    let inner = f.store.lock().unwrap();
    let state = f
        .store
        .fallback_policy_load(&inner.connection, &inner.key)
        .unwrap();
    assert_eq!(state.policies.len(), 5);
    assert_eq!(state.nonrevoked(), 0);
    for p in state.policies {
        assert_eq!(p["state"], "revoked");
        assert_eq!(p["reason"], "OFFLINE_FALLBACK_OWNER_CHANGED");
        assert_eq!(p["policy_revision"], 2);
        assert_eq!(p["owner_epoch"], old_epoch);
    }
}

#[test]
fn formal_query_denial_blocks_new_attempts_all_schemas_and_terminal_consume_before_body() {
    let f = Fixture::new("legacy");
    let query = uuid::Uuid::new_v4().to_string();
    let mut intent = f.intent("tire");
    intent["failure"] =
        json!({"scope":"source_response","reason":"upstream_timeout","query_id":query});
    let grant = f.once(intent.clone());
    let mut legacy = f.legacy();
    legacy.intent.failure = FallbackFailure {
        scope: "source_response".into(),
        reason: "upstream_timeout".into(),
        query_id: Some(query.clone()),
    };
    let old = f.store.decide_fallback(legacy.clone(), 0).unwrap();
    f.store
        .fallback_observe_query_denial(&query, fence())
        .unwrap();
    fs::remove_file(f.pack_path()).unwrap();
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_FALLBACK_NEVER");
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_FALLBACK_USED");
    assert_eq!(
        f.store
            .consume_fallback(
                FallbackConsumeRequest {
                    grant_id: old.id.clone(),
                    intent: old.intent.clone()
                },
                0
            )
            .err(),
        Some("OFFLINE_FALLBACK_NEVER")
    );
    assert_eq!(
        f.store
            .consume_fallback(
                FallbackConsumeRequest {
                    grant_id: old.id,
                    intent: old.intent
                },
                0
            )
            .err(),
        Some("OFFLINE_FALLBACK_USED")
    );
    intent["attempt_id"] = json!(uuid::Uuid::new_v4().to_string());
    let blocked = decode(
        f.store
            .authorize_fallback_v2(transport(&f.request(intent.clone())), 0)
            .unwrap(),
    )
    .package_mirror();
    assert_eq!(blocked["state"], "blocked");
    assert_eq!(blocked["reason"], "OFFLINE_FALLBACK_NEVER");
    intent["attempt_id"] = json!(uuid::Uuid::new_v4().to_string());
    let mut request = f.request(intent);
    request["decision"] = json!("allow");
    assert_eq!(
        f.store
            .decide_fallback_v2(transport(&request), 0)
            .unwrap_err(),
        "OFFLINE_FALLBACK_NEVER"
    );
    legacy.intent.attempt_id = uuid::Uuid::new_v4().to_string();
    assert_eq!(
        f.store.decide_fallback(legacy, 0).unwrap_err(),
        "OFFLINE_FALLBACK_NEVER"
    );
}

#[test]
fn formal_query_denial_ledger_overflow_never_evicts_and_owner_reset_ends_runtime() {
    let f = Fixture::new("nonempty");
    let first = uuid::Uuid::new_v4().to_string();
    let owned = fence();
    f.store
        .fallback_observe_query_denial(&first, owned.clone())
        .unwrap();
    for _ in 1..1025 {
        f.store
            .fallback_observe_query_denial(&uuid::Uuid::new_v4().to_string(), owned.clone())
            .unwrap();
    }
    let inner = f.store.lock().unwrap();
    assert_eq!(inner.fallback.v2.denied_queries.len(), 1024);
    assert!(inner.fallback.v2.denied_queries.contains(&first));
    assert!(inner.fallback.v2.denial_overflow);
    drop(inner);
    let mut intent = f.intent("tire");
    intent["failure"] = json!({"scope":"source_response","reason":"upstream_timeout","query_id":uuid::Uuid::new_v4().to_string()});
    assert_eq!(
        decode(
            f.store
                .authorize_fallback_v2(transport(&f.request(intent)), 0)
                .unwrap()
        )
        .package_mirror()["reason"],
        "OFFLINE_FALLBACK_CAPACITY"
    );
    f.store.reset_owner().unwrap();
    let inner = f.store.lock().unwrap();
    assert!(inner.fallback.v2.denied_queries.is_empty());
    assert!(!inner.fallback.v2.denial_overflow);
}

#[test]
fn every_session_scope_mode_pauses_immediately_on_restart_while_source_never_keeps_cold_deny() {
    for mode in ["ask", "never", "session_allow"] {
        let f = Fixture::new("nonempty");
        let mut choice = f.choice(mode);
        choice["scope"] = json!({"kind":"session","sources":[{"source_id":"fixture","access_generation":0,"query_kinds":["tire"]}]});
        let p = f.store.fallback_policy_preview_v2(choice, 0).unwrap();
        let policy=f.store.fallback_policy_apply_v2(json!({"preview_id":p["preview_id"],"expected_fingerprint":p["fingerprint"],"expected_policy_revision":0,"allow_continuous_history_fallback":true}),0).unwrap();
        assert_eq!(
            policy["runtime_session_id"],
            f.authority()["runtime_session_id"]
        );
        let reopened = Store::with_keys(f.root.clone(), "qa-fallback-v2".into(), &f.keys).unwrap();
        let status = reopened.fallback_status_v2().unwrap();
        assert_eq!(status["authority"]["state"], "unknown");
        assert_eq!(status["policies"][0]["state"], "paused");
        assert_eq!(
            status["policies"][0]["reason"],
            "OFFLINE_FALLBACK_RUNTIME_CHANGED"
        );
        assert_eq!(status["policies"][0]["policy_revision"], 2);
        assert!(reopened.decide_fallback(f.legacy(), 0).is_ok());
        drop(reopened);
    }
    let f = Fixture::new("nonempty");
    let p = f.policy("never");
    assert!(p["runtime_session_id"].is_null());
    let reopened = Store::with_keys(f.root.clone(), "qa-fallback-v2".into(), &f.keys).unwrap();
    let status = reopened.fallback_status_v2().unwrap();
    assert_eq!(status["authority"]["state"], "unknown");
    assert_eq!(status["policies"][0]["state"], "enabled");
    assert_eq!(
        reopened.decide_fallback(f.legacy(), 0).unwrap_err(),
        "OFFLINE_FALLBACK_NEVER"
    );
    drop(reopened);
}

#[test]
fn legacy_v2_audit_failure_burns_without_release_validation_or_body() {
    let f = Fixture::new("nonempty");
    let grant = f.store.decide_fallback(f.legacy(), 0).unwrap();
    fs::remove_file(f.pack_path()).unwrap();
    {
        let inner = f.store.lock().unwrap();
        inner.connection.execute_batch("CREATE TRIGGER qa_fail_legacy_audit BEFORE INSERT ON fallback_audit BEGIN SELECT RAISE(ABORT,'qa'); END;").unwrap();
    }
    assert_eq!(
        f.store
            .consume_fallback(
                FallbackConsumeRequest {
                    grant_id: grant.id.clone(),
                    intent: grant.intent.clone()
                },
                0
            )
            .err(),
        Some("OFFLINE_STORE_FAILED")
    );
    assert_eq!(
        f.store
            .consume_fallback(
                FallbackConsumeRequest {
                    grant_id: grant.id,
                    intent: grant.intent
                },
                0
            )
            .err(),
        Some("OFFLINE_FALLBACK_USED")
    );
}

#[test]
fn equal_priority_uses_latest_approval_then_ascending_policy_id() {
    let f = Fixture::new("nonempty");
    let first = f.policy("source_allow");
    let second = f.policy("source_allow");
    {
        let mut inner = f.store.lock().unwrap();
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = connection.transaction().unwrap();
        let mut state = f.store.fallback_policy_load(&tx, key).unwrap();
        let stamp = Utc::now().to_rfc3339();
        for policy in &mut state.policies {
            policy["approved_at"] = json!(stamp);
        }
        f.store.fallback_policy_save(&tx, key, &state).unwrap();
        tx.commit().unwrap();
    }
    let response = decode(
        f.store
            .authorize_fallback_v2(transport(&f.request(f.intent("tire"))), 0)
            .unwrap(),
    )
    .package_mirror();
    let expected = std::cmp::min(
        first["policy_id"].as_str().unwrap(),
        second["policy_id"].as_str().unwrap(),
    );
    assert_eq!(
        response["grant"]["fallback_authorization"]["policy_id"],
        expected
    );
}
#[test]
fn same_scope_sync_advances_only_explicit_whitelist_binding_atomically_and_old_grant_stays_terminal(
) {
    use crate::offline::conditions::{Conditions, Sample};
    for advance in [false, true] {
        let mut f = Fixture::new("nonempty");
        let mut choice = f.choice("session_allow");
        choice["allow_same_scope_sync_binding_advance"] = json!(advance);
        choice["scope"]["sources"] = json!([{"source_id":"fixture","access_generation":0,"query_kinds":["tire"]},{"source_id":"synthetic-oem","access_generation":0,"query_kinds":["vehicle_fitments"]},{"source_id":"nhtsa-us-recalls","access_generation":0,"query_kinds":["recall_campaign","recall_search"]}]);
        let p = f.store.fallback_policy_preview_v2(choice, 0).unwrap();
        let fallback=f.store.fallback_policy_apply_v2(json!({"preview_id":p["preview_id"],"expected_fingerprint":p["fingerprint"],"expected_policy_revision":0,"allow_continuous_history_fallback":true}),0).unwrap();
        let old = f.once(f.intent("tire"));
        let status = f.store.status();
        let p = f
            .store
            .sync_preview(SyncPreviewRequest {
                slot_id: f.slot.slot_id.clone(),
                expected_generation: f.slot.generation,
                expected_profile_id: status.profile_id.unwrap(),
                expected_owner_epoch: status.owner_epoch,
                interval_seconds: 900,
                conditions: Conditions {
                    network: "any".into(),
                    power: "any".into(),
                },
            })
            .unwrap();
        let sync = f
            .store
            .sync_apply(SyncApplyRequest {
                preview_id: p.preview_id,
                expected_fingerprint: p.fingerprint,
                expected_policy_revision: p.expected_policy_revision,
                allow_continuous_history_updates: true,
            })
            .unwrap();
        let ticket = f
            .store
            .sync_begin(
                SyncRunRequest {
                    policy_id: sync.policy_id,
                    expected_policy_revision: sync.policy_revision,
                    trigger: "manual".into(),
                },
                Sample::default(),
            )
            .unwrap();
        let mut package = Exact::parse(std::str::from_utf8(&f.bytes).unwrap()).unwrap();
        let package_id = uuid::Uuid::new_v4().to_string();
        set(&mut package, "package_id", Exact::Text(package_id.clone())).unwrap();
        set(
            &mut package,
            "base_pack_id",
            Exact::Text(f.descriptor.id.clone()),
        )
        .unwrap();
        set(
            &mut package,
            "scope",
            exact(&serde_json::to_value(&ticket.policy.scope).unwrap()).unwrap(),
        )
        .unwrap();
        let bytes = package.json().into_bytes();
        let mut descriptor = f.descriptor.clone();
        descriptor.id = package_id.clone();
        descriptor.base_pack_id = Some(f.descriptor.id.clone());
        descriptor.plan_id = uuid::Uuid::new_v4().to_string();
        descriptor.sha256 = crypto::hash(&bytes);
        descriptor.byte_count = bytes.len() as u64;
        descriptor.download_path = format!("/v1/offline-packs/{package_id}/download?mode=history");
        let request = InstallRequest {
            package_id,
            expected_sha256: descriptor.sha256.clone(),
            expected_byte_count: descriptor.byte_count,
            approved_plan_fingerprint: descriptor.plan_fingerprint.clone(),
            slot_id: f.slot.slot_id.clone(),
            expected_generation: f.slot.generation,
            allow_device_storage: true,
        };
        f.store
            .sync_stage(
                &ticket,
                "confirming",
                Some((
                    &descriptor.plan_id,
                    &descriptor.plan_fingerprint,
                    &uuid::Uuid::new_v4().to_string(),
                )),
                Some(&descriptor.id),
            )
            .unwrap();
        let install = f.store.begin_install(&request).unwrap();
        let staged = f
            .store
            .stage_install(
                &request,
                descriptor.clone(),
                Zeroizing::new(bytes.clone()),
                install,
            )
            .unwrap();
        let run = f
            .store
            .sync_commit(&ticket, staged, Sample::default())
            .unwrap();
        assert_eq!(run.state, "succeeded");
        f.slot = f.store.list().unwrap().items[0].clone();
        f.bytes = bytes;
        f.descriptor = descriptor;
        let state = f.store.fallback_status_v2().unwrap();
        let p = state["policies"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["policy_id"] == fallback["policy_id"])
            .unwrap();
        assert_eq!(p["state"], if advance { "enabled" } else { "paused" });
        if advance {
            assert_eq!(p["binding"], state["package_bindings"][0]);
            assert_eq!(p["policy_revision"], 1);
            let r = decode(
                f.store
                    .authorize_fallback_v2(transport(&f.request(f.intent("tire"))), 0)
                    .unwrap(),
            )
            .package_mirror();
            assert_eq!(r["state"], "allowed");
        }
        assert_eq!(f.consume(&old).unwrap_err(), "OFFLINE_FALLBACK_USED");
    }
}

#[test]
fn legacy_consume_v2_burns_durably_before_metadata_rejection_and_v2_reads_legacy() {
    let f = Fixture::new("nonempty");
    let grant = f.store.decide_fallback(f.legacy(), 0).unwrap();
    fs::remove_file(f.pack_path()).unwrap();
    let req = FallbackConsumeRequest {
        grant_id: grant.id.clone(),
        intent: grant.intent.clone(),
    };
    assert_eq!(
        f.store.consume_fallback(req, 0).err(),
        Some("OFFLINE_FALLBACK_UNSUPPORTED")
    );
    let inner = f.store.lock().unwrap();
    let (seq, encoded): (i64, Vec<u8>) = inner
        .connection
        .query_row(
            "SELECT sequence,value FROM fallback_audit ORDER BY sequence DESC LIMIT 1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    let clear = crypto::open(
        &inner.key,
        format!("offline-v1:{}:fallback-audit:{seq}", f.store.namespace).as_bytes(),
        &encoded,
        MAX_METADATA_BYTES,
    )
    .unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&clear).unwrap()["state"],
        "consumed"
    );
    drop(inner);
    let legacy = Fixture::new("legacy");
    for kind in ["tire", "vehicle_fitments", "recall_campaign"] {
        let result =
            decode(legacy.consume(&legacy.once(legacy.intent(kind))).unwrap()).package_mirror();
        assert_eq!(result["package_schema"], "offline-pack@1");
        assert_eq!(result["grant"]["schema"], "device-fallback-grant@2");
        assert!(!result["members"].as_array().unwrap().is_empty());
    }
}

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
struct SessionMemory;
impl SessionStore for SessionMemory {
    fn load(&self) -> NativeResult<Option<String>> {
        Ok(Some("acd95df4-f31d-4275-8b9e-098a90cbb223".into()))
    }
    fn save(&self, _: Option<&str>) -> NativeResult<()> {
        Ok(())
    }
    fn delete(&self) -> NativeResult<()> {
        Ok(())
    }
}
fn fence() -> Arc<SessionFence> {
    let bridge = Bridge::new(
        LaunchConfig {
            port: 48793,
            namespace: "fallback-v2-no-http-test".into(),
        },
        Arc::new(SessionMemory),
    )
    .unwrap();
    Arc::new(
        tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(bridge.sync_fence())
            .unwrap(),
    )
}
fn fixture_bytes(name: &str) -> Vec<u8> {
    fs::read(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("src/offline/test-fixtures/query-fallback49")
            .join(name),
    )
    .unwrap()
}
fn transport(value: &Value) -> Value {
    raw::encode_transport(&exact(value).unwrap()).unwrap()
}
fn decode(value: Value) -> Exact {
    raw::decode_transport(value).unwrap()
}

struct Fixture {
    store: Store,
    root: PathBuf,
    keys: FakeKeys,
    slot: Slot,
    descriptor: Descriptor,
    bytes: Vec<u8>,
}
impl Fixture {
    fn new(name: &str) -> Self {
        let root =
            std::env::temp_dir().join(format!("ti-fallback-v2-rust-qa-{}", uuid::Uuid::new_v4()));
        let keys = FakeKeys::default();
        let store = Store::with_keys(root.clone(), "qa-fallback-v2".into(), &keys).unwrap();
        let bytes = fixture_bytes(&format!("{name}-pack.json"));
        let descriptor: Descriptor =
            serde_json::from_slice(&fixture_bytes(&format!("{name}-descriptor.json"))).unwrap();
        let request = InstallRequest {
            package_id: descriptor.id.clone(),
            expected_sha256: descriptor.sha256.clone(),
            expected_byte_count: descriptor.byte_count,
            approved_plan_fingerprint: descriptor.plan_fingerprint.clone(),
            slot_id: uuid::Uuid::new_v4().to_string(),
            expected_generation: 0,
            allow_device_storage: true,
        };
        let ticket = store.begin_install(&request).unwrap();
        let slot = store
            .install(
                &request,
                descriptor.clone(),
                Zeroizing::new(bytes.clone()),
                ticket,
            )
            .unwrap();
        let fixture = Self {
            store,
            root,
            keys,
            slot,
            descriptor,
            bytes,
        };
        fixture.observe();
        fixture
    }
    fn settings() -> Value {
        json!({"items":[
            {"source_id":"fixture","target_kind":"tire","management":{"access_generation":0,"state":"enabled"},"effective_status":"ready","can_fetch":true},
            {"source_id":"synthetic-oem","target_kind":"vehicle","management":{"access_generation":0,"state":"enabled"},"effective_status":"ready","can_fetch":true},
            {"source_id":"nhtsa-us-recalls","target_kind":"recall","management":{"access_generation":0,"state":"enabled"},"effective_status":"ready","can_fetch":true}
        ]})
    }
    fn directory() -> Value {
        json!({"sources":[{"id":"fixture"},{"id":"nhtsa-us-recalls"}]})
    }
    fn observe(&self) -> Value {
        self.store
            .fallback_authority_commit(
                self.store.fallback_authority_capture().unwrap(),
                self.slot.owner_scope_id.clone(),
                Self::settings(),
                Self::directory(),
                fence(),
            )
            .unwrap()
    }
    fn authority(&self) -> Value {
        self.store.fallback_authority_capture().unwrap()
    }
    fn intent(&self, kind: &str) -> Value {
        let authority = self.authority();
        let pack = Exact::parse(std::str::from_utf8(&self.bytes).unwrap())
            .unwrap()
            .package_mirror();
        let (source, query) = match kind {
            "tire" => (
                "fixture",
                json!({"model":"Fixture Tire","size":"265/40ZR20"}),
            ),
            "vehicle_fitments" => (
                "synthetic-oem",
                json!({"vehicle_id":pack["members"].as_array().unwrap().iter().find(|m|m["reference"]["kind"]=="vehicle").unwrap()["payload"]["vehicle"]["id"]}),
            ),
            "recall_campaign" => ("nhtsa-us-recalls", json!({"campaign_number":"23T001000"})),
            "recall_search" => (
                "nhtsa-us-recalls",
                pack["members"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|m| m["reference"]["kind"] == "recall_search")
                    .unwrap()["payload"]["query"]
                    .clone(),
            ),
            _ => panic!("kind"),
        };
        json!({"schema":"device-fallback-intent@2","attempt_id":uuid::Uuid::new_v4().to_string(),"query_fingerprint":"a".repeat(64),"source_id":source,"source_access_generation":0,"authority":{"runtime_session_id":authority["runtime_session_id"],"authority_revision":authority["authority_revision"]},"fallback_policy":"ask","failure":{"scope":"api_transport","reason":"api_timeout","query_id":null},"query_kind":kind,"query":query,"filters":[]})
    }
    fn request(&self, intent: Value) -> Value {
        let a = self.authority();
        json!({"intent":intent,"slot_id":self.slot.slot_id,"expected_generation":self.slot.generation,"expected_sha256":self.slot.sha256,"expected_profile_id":a["profile_id"],"expected_owner_epoch":a["owner_epoch"]})
    }
    fn once(&self, intent: Value) -> Exact {
        let mut req = self.request(intent);
        req["decision"] = json!("allow");
        decode(
            self.store
                .decide_fallback_v2(transport(&req), self.store.fallback_page_id())
                .unwrap(),
        )
    }
    fn consume(&self, grant: &Exact) -> NativeResult<Value> {
        let mut req = exact(&json!({"grant_id":get(grant,"id")?.text()?,"intent":null}))?;
        set(&mut req, "intent", get(grant, "intent")?.clone())?;
        self.store
            .consume_fallback_v2(raw::encode_transport(&req)?, self.store.fallback_page_id())
    }
    fn choice(&self, mode: &str) -> Value {
        let status = self.store.fallback_status_v2().unwrap();
        let a = &status["authority"];
        let scope = match mode {
            "session_allow" => {
                json!({"kind":"session","sources":[{"source_id":"fixture","access_generation":0,"query_kinds":["tire"]}]})
            }
            "query_allow" => {
                json!({"kind":"query","query_kind":"tire","sources":[{"source_id":"fixture","access_generation":0}]})
            }
            _ => {
                json!({"kind":"source","source_id":"fixture","access_generation":0,"query_kinds":["tire"]})
            }
        };
        json!({"mode":mode,"scope":scope,"binding":if matches!(mode,"ask"|"never"){Value::Null}else{status["package_bindings"][0].clone()},"allow_same_scope_sync_binding_advance":false,"expected_profile_id":status["profile_id"],"expected_owner_epoch":status["owner_epoch"],"authority":{"runtime_session_id":a["runtime_session_id"],"authority_revision":a["authority_revision"]},"policy_id":null,"expected_policy_revision":0,"expires_in_seconds":86400})
    }
    fn policy(&self, mode: &str) -> Value {
        let p = self
            .store
            .fallback_policy_preview_v2(self.choice(mode), self.store.fallback_page_id())
            .unwrap();
        self.store.fallback_policy_apply_v2(json!({"preview_id":p["preview_id"],"expected_fingerprint":p["fingerprint"],"expected_policy_revision":p["expected_policy_revision"],"allow_continuous_history_fallback":true}),self.store.fallback_page_id()).unwrap()
    }
    fn pack_path(&self) -> PathBuf {
        let inner = self.store.lock().unwrap();
        let row = Store::row(&inner.connection, &self.slot.slot_id)
            .unwrap()
            .unwrap();
        self.root.join(format!("{}.pack", row.file_id.unwrap()))
    }
    fn legacy(&self) -> FallbackDecideRequest {
        let a = self.authority();
        FallbackDecideRequest {
            intent: FallbackIntent {
                schema: "device-fallback-intent@1".into(),
                attempt_id: uuid::Uuid::new_v4().to_string(),
                query_fingerprint: "a".repeat(64),
                source_id: "fixture".into(),
                source_access_generation: 999,
                query: FallbackQuery {
                    model: "Fixture Tire".into(),
                    size: Some("265/40ZR20".into()),
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
            expected_profile_id: a["profile_id"].as_str().unwrap().into(),
            expected_owner_epoch: a["owner_epoch"].as_u64().unwrap(),
            decision: "allow".into(),
        }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let inner = self
            .store
            .inner
            .get_mut()
            .unwrap_or_else(|poison| poison.into_inner());
        let connection =
            std::mem::replace(&mut inner.connection, Connection::open_in_memory().unwrap());
        connection.close().unwrap();
        assert!(self
            .root
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("ti-fallback-v2-rust-qa-"));
        fs::remove_dir_all(&self.root).unwrap();
    }
}

#[test]
fn four_domains_original_receipts_and_empty_page_are_exact_and_once() {
    for name in ["nonempty", "empty"] {
        let f = Fixture::new(name);
        for kind in KINDS {
            let grant = f.once(f.intent(kind));
            let response = f.consume(&grant).unwrap();
            let result = decode(response).package_mirror();
            assert_eq!(result["query_kind"], kind);
            assert_eq!(result["package_schema"], "offline-pack@2");
            assert_eq!(result["grant"]["state"], "consumed");
            assert!(!result["complete_query_result"].as_bool().unwrap());
            assert!(
                !result["members"].as_array().unwrap().is_empty(),
                "name={name} kind={kind} result={result}"
            );
            assert!(!result["citations"].as_array().unwrap().is_empty());
            if kind == "tire" {
                assert_eq!(result["selection"]["source_count"], 1);
                assert_eq!(result["selection"]["matched_count"], 1);
            } else {
                assert!(result["selection"].is_null());
            }
            if kind == "recall_search" {
                let member = &result["members"][0];
                assert_eq!(member["payload"]["query"]["offset"], "0");
                assert_eq!(member["payload"]["empty_observation"], name == "empty");
                assert!(member["payload"]["boundary"]["complete_query_result"] == false);
            }
            assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_FALLBACK_USED");
        }
    }
}
#[test]
fn result_and_manual_read_preserve_original_unsafe_integer_and_float_tokens() {
    let f = Fixture::new("nonempty");
    let grant = f.once(f.intent("tire"));
    let result = decode(f.consume(&grant).unwrap());
    let member = &get(&result, "members").unwrap().array().unwrap()[0];
    let facts = get(
        get(get(member, "payload").unwrap(), "variant").unwrap(),
        "facts",
    )
    .unwrap();
    assert_eq!(
        get(facts, "reference_int").unwrap(),
        &Exact::Number("9007199254740993".into())
    );
    assert_eq!(
        get(facts, "reference_float").unwrap(),
        &Exact::Number("1.0".into())
    );
    assert_eq!(
        get(facts, "reference_tiny").unwrap(),
        &Exact::Number("5e-324".into())
    );
    let doc = facts;
    assert!(doc.object().is_ok());
    let p: Value = serde_json::from_slice(&f.bytes).unwrap();
    let id = p["documents"]
        .as_array()
        .unwrap()
        .iter()
        .find(|d| d["kind"] == "tire")
        .unwrap()["id"]
        .as_str()
        .unwrap();
    let read = decode(
        f.store
            .read_wire(ReadRequest {
                slot_id: f.slot.slot_id.clone(),
                expected_generation: f.slot.generation,
                document_id: id.into(),
            })
            .unwrap(),
    );
    assert_eq!(
        get(&read, "schema").unwrap().text().unwrap(),
        "offline-read-result@2"
    );
    assert_eq!(get(&read, "member").unwrap(), member);
}
#[test]
fn source_count_keeps_all_basic_filter_true_false_unknown_observations() {
    let mut f = Fixture::new("nonempty");
    let mut pack: Value = serde_json::from_slice(&f.bytes).unwrap();
    let original = pack["members"]
        .as_array()
        .unwrap()
        .iter()
        .find(|m| m["reference"]["kind"] == "tire")
        .unwrap()
        .clone();
    for (index, mode) in ["false", "unknown"].into_iter().enumerate() {
        let mut m = original.clone();
        m["key"] = json!(format!("{:064x}", index + 100));
        if mode == "false" {
            m["payload"]["variant"]["model"] = json!("Other Tire");
        } else {
            m["payload"]["variant"]["facts"]["source_field_conflicts"] = json!([{"field":"model"}]);
        }
        let mut document = pack["documents"]
            .as_array()
            .unwrap()
            .iter()
            .find(|d| d["kind"] == "tire")
            .unwrap()
            .clone();
        document["id"] = json!(format!("member:{}", m["key"].as_str().unwrap()));
        document["member_key"] = m["key"].clone();
        pack["documents"].as_array_mut().unwrap().push(document);
        pack["members"].as_array_mut().unwrap().push(m);
    }
    f.descriptor.counts.distinct_evidence += 2;
    f.descriptor.counts.searchable_documents += 2;
    let bytes = serde_json::to_vec(&pack).unwrap();
    f.descriptor.sha256 = crypto::hash(&bytes);
    f.descriptor.byte_count = bytes.len() as u64;
    let request = InstallRequest {
        package_id: f.descriptor.id.clone(),
        expected_sha256: f.descriptor.sha256.clone(),
        expected_byte_count: f.descriptor.byte_count,
        approved_plan_fingerprint: f.descriptor.plan_fingerprint.clone(),
        slot_id: f.slot.slot_id.clone(),
        expected_generation: f.slot.generation,
        allow_device_storage: true,
    };
    let ticket = f.store.begin_install(&request).unwrap();
    f.slot = f
        .store
        .install(
            &request,
            f.descriptor.clone(),
            Zeroizing::new(bytes.clone()),
            ticket,
        )
        .unwrap();
    f.bytes = bytes;
    let result = decode(f.consume(&f.once(f.intent("tire"))).unwrap()).package_mirror();
    assert_eq!(result["selection"]["source_count"], 3);
    assert_eq!(result["selection"]["matched_count"], 1);
    assert_eq!(result["selection"]["excluded_count"], 1);
    assert_eq!(result["selection"]["undetermined_count"], 1);
    assert_eq!(result["members"].as_array().unwrap().len(), 1);
}
#[test]
fn authorize_ask_does_not_burn_attempt_then_explicit_once_succeeds() {
    let f = Fixture::new("nonempty");
    let intent = f.intent("tire");
    let request = f.request(intent.clone());
    let response = decode(
        f.store
            .authorize_fallback_v2(transport(&request), 0)
            .unwrap(),
    )
    .package_mirror();
    assert_eq!(response["state"], "ask");
    assert!(response["grant"].is_null());
    let grant = f.once(intent);
    assert!(f.consume(&grant).is_ok());
}
#[test]
fn allow_priority_and_ask_require_explicit_once_then_never_terminates_shared_attempt() {
    let f = Fixture::new("nonempty");
    f.policy("session_allow");
    f.policy("source_allow");
    let query = f.policy("query_allow");
    let response = decode(
        f.store
            .authorize_fallback_v2(transport(&f.request(f.intent("tire"))), 0)
            .unwrap(),
    );
    let grant = get(&response, "grant").unwrap();
    assert_eq!(
        get(grant, "fallback_authorization")
            .unwrap()
            .package_mirror()["policy_id"],
        query["policy_id"]
    );
    assert!(f.consume(grant).is_ok());
    f.policy("ask");
    let response = decode(
        f.store
            .authorize_fallback_v2(transport(&f.request(f.intent("tire"))), 0)
            .unwrap(),
    )
    .package_mirror();
    assert_eq!(response["state"], "ask");
    f.policy("never");
    let intent = f.intent("tire");
    let response = decode(
        f.store
            .authorize_fallback_v2(transport(&f.request(intent.clone())), 0)
            .unwrap(),
    )
    .package_mirror();
    assert_eq!(response["state"], "blocked");
    let mut req = f.request(intent);
    req["decision"] = json!("allow");
    assert_eq!(
        f.store.decide_fallback_v2(transport(&req), 0).unwrap_err(),
        "OFFLINE_FALLBACK_USED"
    );
}
#[test]
fn never_blocks_existing_legacy_once_and_forged_generation_even_cold_unknown() {
    let f = Fixture::new("nonempty");
    let old = f.store.decide_fallback(f.legacy(), 0).unwrap();
    f.policy("never");
    assert!(f
        .store
        .consume_fallback(
            FallbackConsumeRequest {
                grant_id: old.id,
                intent: old.intent
            },
            0
        )
        .is_err());
    assert_eq!(
        f.store.decide_fallback(f.legacy(), 0).unwrap_err(),
        "OFFLINE_FALLBACK_NEVER"
    );
    f.store.fallback_authority_unknown().unwrap();
    assert_eq!(
        f.store.decide_fallback(f.legacy(), 0).unwrap_err(),
        "OFFLINE_FALLBACK_NEVER"
    );
}
#[test]
fn metadata_status_and_policy_preview_work_with_missing_body_and_reject_forged_scope() {
    let f = Fixture::new("nonempty");
    let path = f.pack_path();
    let saved = path.with_extension("qa-saved");
    fs::rename(&path, &saved).unwrap();
    let status = f.store.fallback_status_v2().unwrap();
    assert_eq!(status["package_bindings"].as_array().unwrap().len(), 1);
    let preview = f
        .store
        .fallback_policy_preview_v2(f.choice("source_allow"), 0)
        .unwrap();
    assert!(preview.get("matched_count").is_none());
    let mut forged = f.choice("source_allow");
    forged["binding"]["history_scope_fingerprint"] = json!("f".repeat(64));
    assert!(f.store.fallback_policy_preview_v2(forged, 0).is_err());
    fs::rename(saved, path).unwrap();
}
#[test]
fn bad_body_still_has_durable_consumed_receipt_and_audit_failure_precedes_file_read() {
    let f = Fixture::new("nonempty");
    let grant = f.once(f.intent("tire"));
    let path = f.pack_path();
    let bytes = fs::read(&path).unwrap();
    let mut bad = bytes.clone();
    bad[0] ^= 1;
    fs::write(&path, &bad).unwrap();
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_CORRUPT");
    let inner = f.store.lock().unwrap();
    let (seq, encoded): (i64, Vec<u8>) = inner
        .connection
        .query_row(
            "SELECT sequence,value FROM fallback_audit ORDER BY sequence DESC LIMIT 1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    let clear = crypto::open(
        &inner.key,
        format!("offline-v1:{}:fallback-audit:{seq}", f.store.namespace).as_bytes(),
        &encoded,
        MAX_METADATA_BYTES,
    )
    .unwrap();
    assert_eq!(
        Exact::parse(std::str::from_utf8(&clear).unwrap())
            .unwrap()
            .package_mirror()["state"],
        "consumed"
    );
    assert!(!encoded.windows(12).any(|w| w == b"Fixture Tire"));
    drop(inner);
    fs::write(&path, &bytes).unwrap();
    let grant = f.once(f.intent("tire"));
    fs::remove_file(&path).unwrap();
    let inner = f.store.lock().unwrap();
    inner.connection.execute_batch("CREATE TRIGGER qa_fail_audit BEFORE INSERT ON fallback_audit BEGIN SELECT RAISE(ABORT,'qa'); END;").unwrap();
    drop(inner);
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_STORE_FAILED");
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_FALLBACK_USED");
}
#[test]
fn complete_intent_mismatch_closes_receipt_without_using_same_fingerprint() {
    let f = Fixture::new("nonempty");
    let grant = f.once(f.intent("tire"));
    let mut intent = get(&grant, "intent").unwrap().clone();
    set(
        &mut intent,
        "query",
        exact(&json!({"model":"Other Tire"})).unwrap(),
    )
    .unwrap();
    let mut req =
        exact(&json!({"grant_id":get(&grant,"id").unwrap().text().unwrap(),"intent":null}))
            .unwrap();
    set(&mut req, "intent", intent).unwrap();
    assert_eq!(
        f.store
            .consume_fallback_v2(raw::encode_transport(&req).unwrap(), 0)
            .unwrap_err(),
        "OFFLINE_FALLBACK_MISMATCH"
    );
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_FALLBACK_USED");
}
#[test]
fn restart_retains_source_policy_but_unknown_requires_successful_current_observation() {
    let f = Fixture::new("nonempty");
    let policy = f.policy("source_allow");
    let old = f.once(f.intent("tire"));
    let reopened = Store::with_keys(f.root.clone(), "qa-fallback-v2".into(), &f.keys).unwrap();
    let status = reopened.fallback_status_v2().unwrap();
    assert_eq!(status["authority"]["state"], "unknown");
    assert_eq!(status["policies"][0]["policy_id"], policy["policy_id"]);
    let req = f.request(f.intent("tire"));
    assert_eq!(
        reopened
            .authorize_fallback_v2(transport(&req), 0)
            .unwrap_err(),
        AUTHORITY
    );
    reopened
        .fallback_authority_commit(
            reopened.fallback_authority_capture().unwrap(),
            f.slot.owner_scope_id.clone(),
            Fixture::settings(),
            Fixture::directory(),
            fence(),
        )
        .unwrap();
    let mut req = req;
    let a = reopened.fallback_authority_capture().unwrap();
    req["intent"]["authority"] = json!({"runtime_session_id":a["runtime_session_id"],"authority_revision":a["authority_revision"]});
    let response =
        decode(reopened.authorize_fallback_v2(transport(&req), 0).unwrap()).package_mirror();
    assert_eq!(response["state"], "allowed");
    let oldreq = transport(
        &json!({"grant_id":get(&old,"id").unwrap().text().unwrap(),"intent":get(&old,"intent").unwrap().package_mirror()}),
    );
    assert_eq!(
        reopened.consume_fallback_v2(oldreq, 0).unwrap_err(),
        "OFFLINE_FALLBACK_USED"
    );
    drop(reopened);
}
#[test]
fn changed_generation_pauses_policy_and_old_receipt_and_stale_capture_is_rejected() {
    let f = Fixture::new("nonempty");
    f.policy("source_allow");
    let old = f.once(f.intent("tire"));
    let capture = f.authority();
    let mut settings = Fixture::settings();
    settings["items"][0]["management"]["access_generation"] = json!(1);
    f.store
        .fallback_authority_commit(
            capture.clone(),
            f.slot.owner_scope_id.clone(),
            settings.clone(),
            Fixture::directory(),
            fence(),
        )
        .unwrap();
    assert_eq!(
        f.store.fallback_status_v2().unwrap()["policies"][0]["state"],
        "paused"
    );
    assert_eq!(f.consume(&old).unwrap_err(), "OFFLINE_FALLBACK_USED");
    assert_eq!(
        f.store
            .fallback_authority_commit(
                capture,
                f.slot.owner_scope_id.clone(),
                settings,
                Fixture::directory(),
                fence()
            )
            .unwrap_err(),
        "OFFLINE_FALLBACK_AUTHORITY_CHANGED"
    );
}
#[test]
fn original_api_metadata_catalog_keeps_11_sources_and_vehicle_kind_pin_zero() {
    let f = Fixture::new("nonempty");
    let settings: Value = serde_json::from_slice(&fixture_bytes("source-settings.json")).unwrap();
    let directory: Value = serde_json::from_slice(&fixture_bytes("sources.json")).unwrap();
    let a = f
        .store
        .fallback_authority_commit(
            f.authority(),
            f.slot.owner_scope_id.clone(),
            settings,
            directory,
            fence(),
        )
        .unwrap();
    assert_eq!(a["sources"].as_array().unwrap().len(), 11);
    let vehicle = a["sources"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["source_id"] == "xiaomi-cn-vehicles")
        .unwrap();
    assert_eq!(vehicle["access_generation"], 0);
    assert_eq!(vehicle["query_kinds"], json!(["vehicle_fitments"]));
    assert_eq!(vehicle["can_query"], true);
}
#[test]
fn simultaneous_consumers_return_business_material_once() {
    let f = Arc::new(Fixture::new("nonempty"));
    let grant = f.once(f.intent("tire"));
    let barrier = Arc::new(Barrier::new(3));
    let mut workers = Vec::new();
    for _ in 0..2 {
        let f = f.clone();
        let grant = grant.clone();
        let barrier = barrier.clone();
        workers.push(std::thread::spawn(move || {
            barrier.wait();
            f.consume(&grant)
        }));
    }
    barrier.wait();
    let results = workers
        .into_iter()
        .map(|w| w.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(results.iter().filter(|r| r.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|r| r.as_ref().err() == Some(&"OFFLINE_FALLBACK_USED"))
            .count(),
        1
    );
}
#[test]
fn preview_is_one_shot_and_clock_page_expiry_pause_policy() {
    let f = Fixture::new("nonempty");
    let preview = f
        .store
        .fallback_policy_preview_v2(f.choice("source_allow"), 0)
        .unwrap();
    let apply = json!({"preview_id":preview["preview_id"],"expected_fingerprint":preview["fingerprint"],"expected_policy_revision":0,"allow_continuous_history_fallback":true});
    assert!(f.store.fallback_policy_apply_v2(apply.clone(), 0).is_ok());
    assert!(f.store.fallback_policy_apply_v2(apply, 0).is_err());
    let grant = f.once(f.intent("tire"));
    f.store.inner.lock().unwrap().fallback.v2.last_wall =
        Utc::now() + chrono::Duration::seconds(60);
    let status = f.store.fallback_status_v2().unwrap();
    assert_eq!(status["policies"][0]["state"], "paused");
    assert_eq!(
        status["policies"][0]["reason"],
        "OFFLINE_FALLBACK_CLOCK_ROLLBACK"
    );
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_FALLBACK_USED");
    let grant = f.once(f.intent("tire"));
    f.store.invalidate_fallback_page();
    assert_eq!(f.consume(&grant).unwrap_err(), "OFFLINE_FALLBACK_USED");
}
#[test]
fn saved_scope_fingerprint_uses_only_actual_approved_scope_and_stable_keys() {
    let f = Fixture::new("nonempty");
    let original = Exact::parse(std::str::from_utf8(&f.bytes).unwrap()).unwrap();
    let scope = get(&original, "scope").unwrap();
    let expected =
        crypto::hash(format!("device-fallback-approved-scope@1\0{}", scope.json()).as_bytes());
    let status = f.store.fallback_status_v2().unwrap();
    assert_eq!(
        status["package_bindings"][0]["history_scope_fingerprint"],
        expected
    );
    assert_eq!(
        status["package_bindings"][0]["source_ids"],
        json!(["fixture", "nhtsa-us-recalls", "synthetic-oem"])
    );
}
#[test]
fn advanced_unsafe_and_arbitrary_integer_filter_tokens_survive_native_route_exactly() {
    let f = Fixture::new("nonempty");
    for token in ["9007199254740993".into(), "9".repeat(500)] {
        let mut intent = exact(&f.intent("tire")).unwrap();
        set(
            &mut intent,
            "filters",
            Exact::parse(&format!(
                r#"[{{"field":"utqg_treadwear","op":"gte","value":{token}}}]"#
            ))
            .unwrap(),
        )
        .unwrap();
        let mut req = exact(&f.request(Value::Null)).unwrap();
        set(&mut req, "intent", intent.clone()).unwrap();
        set(&mut req, "decision", Exact::Text("allow".into())).unwrap();
        let grant = decode(
            f.store
                .decide_fallback_v2(raw::encode_transport(&req).unwrap(), 0)
                .unwrap(),
        );
        let result = decode(f.consume(&grant).unwrap());
        assert_eq!(
            get(get(&result, "selection").unwrap(), "filters").unwrap(),
            get(&intent, "filters").unwrap()
        );
        assert_eq!(result.package_mirror()["selection"]["excluded_count"], 1);
        assert!(get(&result, "members").unwrap().array().unwrap().is_empty());
    }
}
#[test]
fn missing_scope_metadata_stays_missing_without_body_until_independently_authorized_release() {
    let f = Fixture::new("nonempty");
    let path = f.pack_path();
    let saved = path.with_extension("qa-saved");
    {
        let mut inner = f.store.lock().unwrap();
        let Inner {
            connection, key, ..
        } = &mut *inner;
        let tx = connection.transaction().unwrap();
        let row = Store::row(&tx, &f.slot.slot_id).unwrap().unwrap();
        let mut m = f.store.metadata(&row, key).unwrap();
        m.fallback_binding = None;
        let clear = serde_json::to_vec(&m).unwrap();
        let bytes = crypto::seal(
            key,
            f.store.metadata_aad(&row.id, row.generation).as_bytes(),
            &clear,
        )
        .unwrap();
        tx.execute(
            "UPDATE slots SET metadata=?1 WHERE id=?2",
            params![bytes, row.id],
        )
        .unwrap();
        tx.commit().unwrap();
    }
    fs::rename(&path, &saved).unwrap();
    let status = f.store.fallback_status_v2().unwrap();
    assert!(status["package_bindings"].as_array().unwrap().is_empty());
    assert_eq!(
        status["missing_package_bindings"][0]["reason"],
        "scope_metadata_missing"
    );
    let mut choice = f.choice("never");
    choice["mode"] = json!("source_allow");
    choice["binding"] = json!({"binding_revision":1,"slot_id":f.slot.slot_id,"generation":f.slot.generation,"package_id":f.slot.package_id,"sha256":f.slot.sha256,"history_scope_fingerprint":"f".repeat(64),"source_ids":["fixture"]});
    assert_eq!(
        f.store.fallback_policy_preview_v2(choice, 0).unwrap_err(),
        "OFFLINE_FALLBACK_SCOPE_METADATA_MISSING"
    );
    fs::rename(saved, path).unwrap();
    f.store.sync_revalidate().unwrap();
    assert_eq!(
        f.store.fallback_status_v2().unwrap()["package_bindings"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
}
#[test]
fn mult_source_binding_cannot_request_sync_advance_with_one_source_whitelist() {
    let f = Fixture::new("nonempty");
    let mut choice = f.choice("source_allow");
    choice["allow_same_scope_sync_binding_advance"] = json!(true);
    assert_eq!(
        f.store.fallback_policy_preview_v2(choice, 0).unwrap_err(),
        "OFFLINE_FALLBACK_SYNC_ADVANCE_SCOPE_UNAVAILABLE"
    );
    let mut choice = f.choice("session_allow");
    choice["allow_same_scope_sync_binding_advance"] = json!(true);
    choice["scope"]["sources"] = json!([{"source_id":"fixture","access_generation":0,"query_kinds":["tire"]},{"source_id":"synthetic-oem","access_generation":0,"query_kinds":["vehicle_fitments"]},{"source_id":"nhtsa-us-recalls","access_generation":0,"query_kinds":["recall_campaign","recall_search"]}]);
    assert!(f.store.fallback_policy_preview_v2(choice, 0).is_ok());
}
#[test]
fn legacy_and_v2_share_the_sixteen_pending_and_lifetime_attempt_registry() {
    let f = Fixture::new("nonempty");
    let mut used_attempt = None;
    for _ in 0..8 {
        let grant = f.once(f.intent("tire"));
        used_attempt = Some(
            get(get(&grant, "intent").unwrap(), "attempt_id")
                .unwrap()
                .text()
                .unwrap()
                .to_owned(),
        );
    }
    for _ in 0..8 {
        f.store.decide_fallback(f.legacy(), 0).unwrap();
    }
    let mut req = f.request(f.intent("tire"));
    req["decision"] = json!("allow");
    assert_eq!(
        f.store.decide_fallback_v2(transport(&req), 0).unwrap_err(),
        "OFFLINE_FALLBACK_CAPACITY"
    );
    assert_eq!(
        f.store.decide_fallback(f.legacy(), 0).unwrap_err(),
        "OFFLINE_FALLBACK_CAPACITY"
    );
    let mut legacy = f.legacy();
    legacy.intent.attempt_id = used_attempt.unwrap();
    assert_eq!(
        f.store.decide_fallback(legacy, 0).unwrap_err(),
        "OFFLINE_FALLBACK_USED"
    );
}
#[test]
fn registered_disabled_source_can_save_new_never_without_read_rights_and_unchanged_refresh_keeps_it(
) {
    let f = Fixture::new("nonempty");
    let old = f.policy("source_allow");
    let mut disabled = Fixture::settings();
    disabled["items"][0]["effective_status"] = json!("disabled");
    disabled["items"][0]["can_fetch"] = json!(false);
    f.store
        .fallback_authority_commit(
            f.authority(),
            f.slot.owner_scope_id.clone(),
            disabled.clone(),
            Fixture::directory(),
            fence(),
        )
        .unwrap();
    assert_eq!(
        f.store.fallback_status_v2().unwrap()["policies"][0]["state"],
        "paused"
    );
    assert_eq!(
        f.store
            .fallback_policy_preview_v2(f.choice("source_allow"), 0)
            .unwrap_err(),
        AUTHORITY
    );
    let new = f.policy("never");
    assert_ne!(new["policy_id"], old["policy_id"]);
    let result = decode(
        f.store
            .authorize_fallback_v2(transport(&f.request(f.intent("tire"))), 0)
            .unwrap(),
    )
    .package_mirror();
    assert_eq!(result["state"], "blocked");
    assert_eq!(result["reason"], "OFFLINE_FALLBACK_NEVER");
    assert_eq!(
        f.store.decide_fallback(f.legacy(), 0).unwrap_err(),
        "OFFLINE_FALLBACK_NEVER"
    );
    f.store
        .fallback_authority_commit(
            f.authority(),
            f.slot.owner_scope_id.clone(),
            disabled,
            Fixture::directory(),
            fence(),
        )
        .unwrap();
    let status = f.store.fallback_status_v2().unwrap();
    let new = status["policies"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["policy_id"] == new["policy_id"])
        .unwrap();
    assert_eq!(new["state"], "enabled");
    assert_eq!(new["policy_revision"], 1);
    f.observe();
    let status = f.store.fallback_status_v2().unwrap();
    assert!(status["policies"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|p| p["mode"] == "never")
        .all(|p| p["state"] == "paused"));
}
