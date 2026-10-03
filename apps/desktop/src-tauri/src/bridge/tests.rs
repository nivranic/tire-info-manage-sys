use super::*;
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::Notify,
    task::JoinHandle,
};

const TEST_COOKIE: &str = "acd95df4-f31d-4275-8b9e-098a90cbb223";

#[test]
fn denial_metadata_requires_fixed_closed_request_and_actual_201_matching_denial() {
    let query = Uuid::new_v4().to_string();
    let make = |method: Method, path: &str, body: serde_json::Value| ValidatedRequest {
        method,
        path: path.into(),
        headers: HeaderMap::new(),
        body: serde_json::to_vec(&body).unwrap(),
    };
    let body = serde_json::json!({"query_id":query,"decision":"deny","scope":"once"});
    assert_eq!(
        consent_denial_request(&make(Method::POST, "/v1/fallback-consents", body.clone())),
        Some(query.clone())
    );
    for request in [
        make(Method::GET, "/v1/fallback-consents", body.clone()),
        make(Method::POST, "/v1/fallback-consents?x=1", body.clone()),
        make(
            Method::POST,
            "/v1/fallback-consents",
            serde_json::json!({"query_id":query,"decision":"allow","scope":"once"}),
        ),
        make(
            Method::POST,
            "/v1/fallback-consents",
            serde_json::json!({"query_id":query,"decision":"deny","scope":"once","claim":true}),
        ),
    ] {
        assert!(consent_denial_request(&request).is_none());
    }
    let mut response = ApiResponse {
        status: 201,
        headers: BTreeMap::new(),
        body_base64: STANDARD.encode(
            serde_json::json!({"id":Uuid::new_v4().to_string(),"decision":"deny","scope":"once"})
                .to_string(),
        ),
    };
    assert!(consent_denial_response(&response, &query));
    response.status = 200;
    assert!(!consent_denial_response(&response, &query));
    response.status = 201;
    for body in [
        serde_json::json!({"id":Uuid::new_v4().to_string(),"decision":"allow","scope":"once"}),
        serde_json::json!({"id":"bad","decision":"deny","scope":"once"}),
        serde_json::json!({"id":Uuid::new_v4().to_string(),"decision":"deny","scope":"session"}),
    ] {
        response.body_base64 = STANDARD.encode(body.to_string());
        assert!(!consent_denial_response(&response, &query));
    }
}

fn authority_reply(settings: bool) -> Reply {
    let mut headers = vec![("Content-Type".into(), "application/json".into())];
    if settings {
        headers.push(("X-Tire-Offline-Owner-Scope".into(), "b".repeat(64)));
    }
    Reply::Body {
        status: 200,
        headers,
        body: if settings {
            br#"{"items":[]}"#.to_vec()
        } else {
            br#"{"sources":[]}"#.to_vec()
        },
        chunked: false,
        length: None,
    }
}
#[tokio::test]
async fn fallback_authority_uses_only_two_fixed_metadata_gets_and_no_health_bootstrap() {
    let server = Server::start(|request| match request.target.as_str() {
        "/v1/source-settings" => authority_reply(true),
        "/v1/sources" => authority_reply(false),
        _ => panic!("unexpected metadata endpoint"),
    })
    .await;
    let memory = Arc::new(MemoryStore::default());
    *memory.value.lock().unwrap() = Some(TEST_COOKIE.into());
    let bridge = server.bridge(memory);
    let fence = bridge.sync_fence().await.unwrap();
    let (owner, settings, directory) = bridge.fallback_authority_metadata(&fence).await.unwrap();
    assert_eq!(owner, "b".repeat(64));
    assert_eq!(settings, serde_json::json!({"items":[]}));
    assert_eq!(directory, serde_json::json!({"sources":[]}));
    let received = server.received.lock().unwrap();
    assert_eq!(
        received
            .iter()
            .map(|r| r.target.as_str())
            .collect::<Vec<_>>(),
        vec!["/v1/source-settings", "/v1/sources"]
    );
    assert!(received.iter().all(|r| r.body.is_empty()));
}
#[tokio::test]
async fn fallback_authority_cold_session_does_not_bootstrap_or_issue_metadata_request() {
    let server = Server::start(|_| panic!("cold metadata must not send any request")).await;
    let bridge = server.bridge(Arc::new(MemoryStore::default()));
    assert!(bridge.sync_fence().await.is_err());
    assert!(server.received.lock().unwrap().is_empty());
}
#[tokio::test]
async fn fallback_authority_cookie_rotation_between_fixed_reads_fails_before_second_get() {
    let server=Server::start(|_|{
        let Reply::Body{status,mut headers,body,chunked,length}=authority_reply(true)else{unreachable!()};
        headers.push(("Set-Cookie".into(),format!("{COOKIE_NAME}=ed03021d-664b-4305-9745-adf5870112b2; HttpOnly; Path=/; SameSite=strict; Max-Age=1209600")));
        Reply::Body{status,headers,body,chunked,length}
    }).await;
    let memory = Arc::new(MemoryStore::default());
    *memory.value.lock().unwrap() = Some(TEST_COOKIE.into());
    let bridge = server.bridge(memory);
    let fence = bridge.sync_fence().await.unwrap();
    assert_eq!(
        bridge
            .fallback_authority_metadata(&fence)
            .await
            .unwrap_err(),
        "SESSION_CHANGED"
    );
    assert_eq!(server.received.lock().unwrap().len(), 1);
}
#[tokio::test]
async fn fallback_authority_reset_during_second_metadata_get_never_publishes_mixed_session() {
    let started = Arc::new(Notify::new());
    let closed = Arc::new(Notify::new());
    let signal = started.clone();
    let closing = closed.clone();
    let server = Server::start(move |request| {
        if request.target == "/v1/source-settings" {
            authority_reply(true)
        } else {
            Reply::BeforeHeaders {
                started: signal.clone(),
                closed: closing.clone(),
            }
        }
    })
    .await;
    let memory = Arc::new(MemoryStore::default());
    *memory.value.lock().unwrap() = Some(TEST_COOKIE.into());
    let bridge = Arc::new(server.bridge(memory));
    let worker = bridge.clone();
    let fence = Arc::new(bridge.sync_fence().await.unwrap());
    let task = tokio::spawn(async move { worker.fallback_authority_metadata(&fence).await });
    started.notified().await;
    bridge.reset_session().await.unwrap();
    assert!(task.await.unwrap().is_err());
    assert_eq!(server.received.lock().unwrap().len(), 2);
}

#[derive(Default)]
struct MemoryStore {
    value: Mutex<Option<String>>,
    fail_read: AtomicBool,
    fail_write: AtomicBool,
    fail_delete: AtomicBool,
}

impl SessionStore for MemoryStore {
    fn load(&self) -> NativeResult<Option<String>> {
        if self.fail_read.load(Ordering::SeqCst) {
            return Err("SESSION_STORE_READ_FAILED");
        }
        Ok(self.value.lock().unwrap().clone())
    }
    fn save(&self, value: Option<&str>) -> NativeResult<()> {
        if self.fail_write.load(Ordering::SeqCst) {
            return Err("SESSION_STORE_WRITE_FAILED");
        }
        *self.value.lock().unwrap() = value.map(str::to_owned);
        Ok(())
    }
    fn delete(&self) -> NativeResult<()> {
        if self.fail_delete.load(Ordering::SeqCst) {
            return Err("SESSION_STORE_DELETE_FAILED");
        }
        *self.value.lock().unwrap() = None;
        Ok(())
    }
}

#[derive(Clone)]
struct Incoming {
    target: String,
    headers: BTreeMap<String, String>,
    body: Vec<u8>,
}

enum Reply {
    Body {
        status: u16,
        headers: Vec<(String, String)>,
        body: Vec<u8>,
        chunked: bool,
        length: Option<usize>,
    },
    Hang {
        started: Arc<Notify>,
        closed: Arc<Notify>,
    },
    BeforeHeaders {
        started: Arc<Notify>,
        closed: Arc<Notify>,
    },
}

fn body_reply(body: &[u8]) -> Reply {
    Reply::Body {
        status: 200,
        headers: Vec::new(),
        body: body.to_vec(),
        chunked: false,
        length: None,
    }
}

fn health_reply() -> Reply {
    Reply::Body {
        status: 200,
        headers: vec![(
            "Set-Cookie".into(),
            format!(
                "{COOKIE_NAME}={TEST_COOKIE}; HttpOnly; Path=/; SameSite=strict; Max-Age=1209600"
            ),
        )],
        body: b"{}".to_vec(),
        chunked: false,
        length: None,
    }
}

struct Server {
    port: u16,
    received: Arc<Mutex<Vec<Incoming>>>,
    task: JoinHandle<()>,
}

impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

impl Server {
    async fn start(handler: impl Fn(&Incoming) -> Reply + Send + Sync + 'static) -> Self {
        // Tests bind only their own ephemeral loopback listener; no real API/store is used.
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let received = Arc::new(Mutex::new(Vec::new()));
        let received_clone = received.clone();
        let handler = Arc::new(handler);
        let task = tokio::spawn(async move {
            while let Ok((stream, _)) = listener.accept().await {
                let received = received_clone.clone();
                let handler = handler.clone();
                tokio::spawn(async move {
                    let _ = serve(stream, received, handler).await;
                });
            }
        });
        Self {
            port,
            received,
            task,
        }
    }

    fn bridge(&self, store: Arc<dyn SessionStore>) -> Bridge {
        Bridge::new(
            LaunchConfig {
                port: self.port,
                namespace: "test-memory".into(),
            },
            store,
        )
        .unwrap()
    }
}

async fn serve(
    mut stream: TcpStream,
    received: Arc<Mutex<Vec<Incoming>>>,
    handler: Arc<impl Fn(&Incoming) -> Reply>,
) -> std::io::Result<()> {
    let mut data = Vec::new();
    let end = loop {
        let mut chunk = [0_u8; 8192];
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            return Ok(());
        }
        data.extend_from_slice(&chunk[..count]);
        if let Some(index) = data.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            break index + 4;
        }
        assert!(data.len() < 65536, "test request header exceeded limit");
    };
    let text = String::from_utf8_lossy(&data[..end]);
    let mut lines = text.split("\r\n");
    let target = lines
        .next()
        .unwrap()
        .split_whitespace()
        .nth(1)
        .unwrap()
        .to_owned();
    let headers: BTreeMap<String, String> = lines
        .filter_map(|line| {
            line.split_once(':')
                .map(|(key, value)| (key.to_ascii_lowercase(), value.trim().to_owned()))
        })
        .collect();
    let length = headers
        .get("content-length")
        .map(|value| value.parse::<usize>().unwrap())
        .unwrap_or(0);
    while data.len() - end < length {
        let mut chunk = [0_u8; 8192];
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            return Ok(());
        }
        data.extend_from_slice(&chunk[..count]);
    }
    let incoming = Incoming {
        target,
        headers,
        body: data[end..end + length].to_vec(),
    };
    received.lock().unwrap().push(incoming.clone());
    match handler(&incoming) {
        Reply::BeforeHeaders { started, closed } => {
            started.notify_one();
            let mut byte = [0_u8];
            let count = stream.read(&mut byte).await?;
            assert_eq!(
                count, 0,
                "cancellation must close the raw socket before any response headers"
            );
            closed.notify_one();
        }
        Reply::Hang { started, closed } => {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\n")
                .await?;
            started.notify_one();
            let mut byte = [0_u8];
            let _ = stream.read(&mut byte).await;
            closed.notify_one();
        }
        Reply::Body {
            status,
            headers,
            body,
            chunked,
            length,
        } => {
            let mut response = format!("HTTP/1.1 {status} Test\r\nConnection: close\r\n");
            for (key, value) in headers {
                response.push_str(&format!("{key}: {value}\r\n"));
            }
            if chunked {
                response.push_str("Transfer-Encoding: chunked\r\n\r\n");
                stream.write_all(response.as_bytes()).await?;
                for chunk in body.chunks(if body.len() > 1024 * 1024 { 8192 } else { 17 }) {
                    stream
                        .write_all(format!("{:x}\r\n", chunk.len()).as_bytes())
                        .await?;
                    stream.write_all(chunk).await?;
                    stream.write_all(b"\r\n").await?;
                }
                stream.write_all(b"0\r\n\r\n").await?;
            } else {
                response.push_str(&format!(
                    "Content-Length: {}\r\n\r\n",
                    length.unwrap_or(body.len())
                ));
                stream.write_all(response.as_bytes()).await?;
                stream.write_all(&body).await?;
            }
        }
    }
    Ok(())
}

fn offline_headers(sha256: &str) -> Vec<(String, String)> {
    vec![
        ("Content-Type".into(), "application/json".into()),
        ("ETag".into(), format!("\"{sha256}\"")),
        ("X-Content-SHA256".into(), sha256.into()),
        ("Cache-Control".into(), "no-store".into()),
        ("X-Content-Type-Options".into(), "nosniff".into()),
        (
            "Content-Disposition".into(),
            "attachment; filename=offline.json".into(),
        ),
    ]
}

fn sync_reply(owner: &str, extra: Vec<(String, String)>) -> Reply {
    let mut headers = vec![
        ("Content-Type".into(), "application/json".into()),
        ("Cache-Control".into(), "no-store".into()),
        ("X-Tire-Offline-Owner-Scope".into(), owner.into()),
    ];
    headers.extend(extra);
    Reply::Body {
        status: 200,
        headers,
        body: b"{}".to_vec(),
        chunked: false,
        length: None,
    }
}
fn retained_store() -> Arc<MemoryStore> {
    let store = Arc::new(MemoryStore::default());
    *store.value.lock().unwrap() = Some(TEST_COOKIE.into());
    store
}

#[tokio::test]
async fn sync_missing_cookie_never_bootstraps_or_calls_any_endpoint() {
    let server = Server::start(|_| panic!("No-cookie sync must never issue even /health")).await;
    let bridge = server.bridge(Arc::new(MemoryStore::default()));
    assert_eq!(
        bridge.sync_fence().await.err(),
        Some("OFFLINE_SYNC_SESSION_REQUIRED")
    );
    assert!(server.received.lock().unwrap().is_empty());
}

#[tokio::test]
async fn sync_fixes_cookie_generation_and_owner_headers_without_health_or_cookie_ipc() {
    let owner = "b".repeat(64);
    let reply_owner = owner.clone();
    let server = Server::start(move |request| {
        assert_eq!(request.target, "/v1/offline-pack-updates:prepare");
        sync_reply(&reply_owner, Vec::new())
    })
    .await;
    let bridge = server.bridge(retained_store());
    let fence = bridge.sync_fence().await.unwrap();
    assert_eq!(
        &**bridge
            .sync_request(&fence, &owner, SyncEndpoint::Prepare, b"{}".to_vec(), None)
            .await
            .unwrap(),
        b"{}"
    );
    let requests = server.received.lock().unwrap();
    assert_eq!(requests.len(), 1);
    assert_eq!(
        requests[0]
            .headers
            .get("x-tire-offline-sync")
            .map(String::as_str),
        Some("1")
    );
    assert_eq!(
        requests[0].headers.get("x-tire-offline-expected-owner"),
        Some(&owner)
    );
    assert!(requests[0].headers.contains_key("cookie"));
}

#[tokio::test]
async fn sync_cookie_aba_and_transport_reset_invalidate_old_fence() {
    let server = Server::start(|_| panic!("ABA must fail before a request")).await;
    let bridge = server.bridge(retained_store());
    let fence = bridge.sync_fence().await.unwrap();
    bridge.session.reset().await.unwrap();
    {
        let mut data = bridge.session.data.lock().await;
        bridge
            .session
            .persist(&mut data, Some(TEST_COOKIE.into()))
            .unwrap();
    }
    assert_eq!(
        bridge.check_sync_fence(&fence).await,
        Err("SESSION_CHANGED")
    );
    let fence = bridge.sync_fence().await.unwrap();
    bridge.reset_session().await.unwrap();
    assert_eq!(
        bridge.check_sync_fence(&fence).await,
        Err("SESSION_CHANGED")
    );
    assert!(server.received.lock().unwrap().is_empty());
}

#[tokio::test]
async fn cancelled_publish_awaiter_keeps_cookie_authority_locked_until_worker_commit_ends() {
    let server = Server::start(|_| panic!("Publication must not make an HTTP request")).await;
    let bridge = Arc::new(server.bridge(retained_store()));
    let fence = Arc::new(bridge.sync_fence().await.unwrap());
    let (started_tx, started_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let (finished_tx, finished_rx) = tokio::sync::oneshot::channel();
    let publishing = bridge.clone();
    let task = tokio::spawn(async move {
        publishing
            .sync_publish(fence, move || {
                started_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(2)).unwrap();
                finished_tx.send(()).unwrap();
                Ok(())
            })
            .await
    });
    started_rx.await.unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    // The detached blocking worker still owns this guard. A cookie rotation
    // cannot overtake its publication after the awaiting task is cancelled.
    assert!(
        tokio::time::timeout(Duration::from_millis(30), bridge.session.data.lock())
            .await
            .is_err()
    );
    release_tx.send(()).unwrap();
    finished_rx.await.unwrap();
    let mut data = tokio::time::timeout(Duration::from_secs(2), bridge.session.data.lock())
        .await
        .unwrap();
    bridge.session.persist(&mut data, None).unwrap();
    assert!(server.received.lock().unwrap().is_empty());
}

#[tokio::test]
async fn sync_response_cookie_rotation_stops_the_run_and_is_not_silently_replayed() {
    let owner = "b".repeat(64);
    let reply_owner = owner.clone();
    let replacement = Uuid::new_v4().to_string();
    let server=Server::start(move |_|sync_reply(&reply_owner,vec![("Set-Cookie".into(),format!("{COOKIE_NAME}={replacement}; HttpOnly; Path=/; SameSite=strict; Max-Age=1209600"))])).await;
    let bridge = server.bridge(retained_store());
    let fence = bridge.sync_fence().await.unwrap();
    assert_eq!(
        bridge
            .sync_request(&fence, &owner, SyncEndpoint::Prepare, b"{}".to_vec(), None)
            .await
            .err(),
        Some("SESSION_CHANGED")
    );
    assert_eq!(server.received.lock().unwrap().len(), 1);
    assert_eq!(
        bridge.check_sync_fence(&fence).await,
        Err("SESSION_CHANGED")
    );
}

#[tokio::test]
async fn sync_missing_wrong_or_duplicate_authority_never_accepts_response_bytes() {
    for fault in 0..3 {
        let owner = "b".repeat(64);
        let reply_owner = owner.clone();
        let server = Server::start(move |_| {
            let mut headers = vec![
                ("Content-Type".into(), "application/json".into()),
                ("Cache-Control".into(), "no-store".into()),
            ];
            if fault == 1 {
                headers.push(("X-Tire-Offline-Owner-Scope".into(), "c".repeat(64)));
            }
            if fault == 2 {
                headers.push(("X-Tire-Offline-Owner-Scope".into(), reply_owner.clone()));
                headers.push(("X-Tire-Offline-Owner-Scope".into(), reply_owner.clone()));
            }
            Reply::Body {
                status: 200,
                headers,
                body: b"{}".to_vec(),
                chunked: false,
                length: None,
            }
        })
        .await;
        let bridge = server.bridge(retained_store());
        let fence = bridge.sync_fence().await.unwrap();
        assert_eq!(
            bridge
                .sync_request(&fence, &owner, SyncEndpoint::Prepare, b"{}".to_vec(), None)
                .await
                .err(),
            Some("OFFLINE_SYNC_RESPONSE_INVALID")
        );
    }
}

#[tokio::test]
async fn reset_does_not_wait_for_a_sync_request_with_unknown_prepare_response() {
    let started = Arc::new(Notify::new());
    let closed = Arc::new(Notify::new());
    let a = started.clone();
    let b = closed.clone();
    let server = Server::start(move |_| Reply::BeforeHeaders {
        started: a.clone(),
        closed: b.clone(),
    })
    .await;
    let bridge = Arc::new(server.bridge(retained_store()));
    let fence = bridge.sync_fence().await.unwrap();
    let running = bridge.clone();
    let task = tokio::spawn(async move {
        running
            .sync_request(
                &fence,
                &"b".repeat(64),
                SyncEndpoint::Prepare,
                b"{}".to_vec(),
                None,
            )
            .await
    });
    started.notified().await;
    tokio::time::timeout(Duration::from_secs(2), bridge.reset_session())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(task.await.unwrap().err(), Some("REQUEST_CANCELLED"));
    tokio::time::timeout(Duration::from_secs(2), closed.notified())
        .await
        .unwrap();
}

#[tokio::test]
async fn offline_owned_download_uses_fixed_paths_and_exact_bytes_without_base64() {
    let (request, descriptor, bytes) = crate::offline::tests::sample();
    let expected_bytes = bytes.clone();
    let package_id = request.package_id.clone();
    let hash = descriptor.sha256.clone();
    let metadata = serde_json::to_vec(&descriptor).unwrap();
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        assert_eq!(
            incoming.headers.get("cookie"),
            Some(&format!("{COOKIE_NAME}={TEST_COOKIE}"))
        );
        if incoming.target.ends_with("/download?mode=history") {
            assert_eq!(
                incoming.target,
                format!("/v1/offline-packs/{package_id}/download?mode=history")
            );
            Reply::Body {
                status: 200,
                headers: offline_headers(&hash),
                body: bytes.clone(),
                chunked: false,
                length: None,
            }
        } else {
            assert_eq!(
                incoming.target,
                format!("/v1/offline-packs/{package_id}?mode=history")
            );
            Reply::Body {
                status: 200,
                headers: vec![("Content-Type".into(), "application/json".into())],
                body: metadata.clone(),
                chunked: false,
                length: None,
            }
        }
    })
    .await;
    let bridge = server.bridge(Arc::new(MemoryStore::default()));
    let (actual, body) = bridge.owned_pack(&request).await.unwrap();
    assert_eq!(actual.id, request.package_id);
    assert_eq!(&*body, &expected_bytes);
    assert_eq!(server.received.lock().unwrap().len(), 3);
    assert!(bridge.registry.lock().unwrap().active.is_empty());
}

#[tokio::test]
async fn offline_owned_download_rejects_binding_header_hash_and_redirect_errors() {
    for failure in [
        "descriptor",
        "etag",
        "hash",
        "redirect",
        "status",
        "encoding",
        "mime",
        "length",
    ] {
        let (request, mut descriptor, mut bytes) = crate::offline::tests::sample();
        let hash = descriptor.sha256.clone();
        if failure == "descriptor" {
            descriptor.owner_scope_id = "bad-owner".into();
        }
        if failure == "hash" {
            bytes[0] ^= 1;
        }
        let metadata = serde_json::to_vec(&descriptor).unwrap();
        let server = Server::start(move |incoming| {
            if incoming.target == "/health" {
                return health_reply();
            }
            if !incoming.target.ends_with("/download?mode=history") {
                return Reply::Body {
                    status: 200,
                    headers: vec![("Content-Type".into(), "application/json".into())],
                    body: metadata.clone(),
                    chunked: false,
                    length: None,
                };
            }
            let mut headers = offline_headers(&hash);
            if failure == "etag" {
                headers.retain(|(key, _)| key != "ETag");
            }
            if failure == "encoding" {
                headers.push(("Content-Encoding".into(), "gzip".into()));
            }
            if failure == "mime" {
                headers[0].1 = "text/html".into();
            }
            Reply::Body {
                status: if failure == "redirect" {
                    302
                } else if failure == "status" {
                    404
                } else {
                    200
                },
                headers,
                body: bytes.clone(),
                chunked: false,
                length: if failure == "length" {
                    Some(bytes.len() + 1)
                } else {
                    None
                },
            }
        })
        .await;
        let bridge = server.bridge(Arc::new(MemoryStore::default()));
        let error = bridge.owned_pack(&request).await.err().unwrap();
        let expected = match failure {
            "descriptor" => "OFFLINE_PACK_INVALID",
            "hash" => "OFFLINE_HASH_MISMATCH",
            "redirect" => "API_REDIRECT_BLOCKED",
            "status" => "OFFLINE_DOWNLOAD_FAILED",
            _ => "OFFLINE_RESPONSE_INVALID",
        };
        assert_eq!(error, expected, "{failure}");
        assert!(bridge.registry.lock().unwrap().active.is_empty());
    }
}

#[tokio::test]
async fn offline_owned_download_bounds_actual_chunked_bytes() {
    let (request, descriptor, _) = crate::offline::tests::sample();
    let hash = descriptor.sha256.clone();
    let metadata = serde_json::to_vec(&descriptor).unwrap();
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        if incoming.target.ends_with("/download?mode=history") {
            Reply::Body {
                status: 200,
                headers: offline_headers(&hash),
                body: vec![b' '; crate::offline::MAX_PACKAGE_BYTES + 1],
                chunked: true,
                length: None,
            }
        } else {
            Reply::Body {
                status: 200,
                headers: vec![("Content-Type".into(), "application/json".into())],
                body: metadata.clone(),
                chunked: false,
                length: None,
            }
        }
    })
    .await;
    let bridge = server.bridge(Arc::new(MemoryStore::default()));
    assert_eq!(
        bridge.owned_pack(&request).await.err(),
        Some("OFFLINE_PACK_TOO_LARGE")
    );
    assert!(bridge.registry.lock().unwrap().active.is_empty());
}

#[tokio::test]
async fn reset_cancels_owned_package_download_socket_and_preserves_registration_lifecycle() {
    let (request, descriptor, _) = crate::offline::tests::sample();
    let metadata = serde_json::to_vec(&descriptor).unwrap();
    let started = Arc::new(Notify::new());
    let closed = Arc::new(Notify::new());
    let (a, b) = (started.clone(), closed.clone());
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        if incoming.target.ends_with("/download?mode=history") {
            Reply::BeforeHeaders {
                started: a.clone(),
                closed: b.clone(),
            }
        } else {
            Reply::Body {
                status: 200,
                headers: vec![("Content-Type".into(), "application/json".into())],
                body: metadata.clone(),
                chunked: false,
                length: None,
            }
        }
    })
    .await;
    let bridge = Arc::new(server.bridge(Arc::new(MemoryStore::default())));
    let running = bridge.clone();
    let task = tokio::spawn(async move { running.owned_pack(&request).await });
    tokio::time::timeout(Duration::from_secs(3), started.notified())
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(3), bridge.reset_session())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(task.await.unwrap().err(), Some("REQUEST_CANCELLED"));
    tokio::time::timeout(Duration::from_secs(3), closed.notified())
        .await
        .unwrap();
    assert!(bridge.registry.lock().unwrap().active.is_empty());
}

#[tokio::test]
async fn offline_install_arguments_reject_url_path_and_false_consent_before_network() {
    let server = Server::start(|_| panic!("invalid typed arguments must not reach network")).await;
    let bridge = server.bridge(Arc::new(MemoryStore::default()));
    let (mut request, _, _) = crate::offline::tests::sample();
    request.package_id = "http://127.0.0.1:8000/health".into();
    assert_eq!(
        bridge.owned_pack(&request).await.err(),
        Some("OFFLINE_INVALID_ARGUMENT")
    );
    request.allow_device_storage = false;
    assert_eq!(
        bridge.owned_pack(&request).await.err(),
        Some("OFFLINE_CONSENT_REQUIRED")
    );
    assert!(server.received.lock().unwrap().is_empty());
}

#[tokio::test]
async fn cancellation_before_response_headers_closes_the_actual_socket() {
    let started = Arc::new(Notify::new());
    let closed = Arc::new(Notify::new());
    let (a, b) = (started.clone(), closed.clone());
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            health_reply()
        } else {
            Reply::BeforeHeaders {
                started: a.clone(),
                closed: b.clone(),
            }
        }
    })
    .await;
    let bridge = Arc::new(server.bridge(Arc::new(MemoryStore::default())));
    let input = request("/v1/slow-before-headers");
    let id = input.id.clone();
    let running = bridge.clone();
    let task = tokio::spawn(async move { running.request(input).await });
    tokio::time::timeout(Duration::from_secs(3), started.notified())
        .await
        .unwrap();
    bridge.cancel(&id).unwrap();
    assert_eq!(task.await.unwrap().unwrap_err(), "REQUEST_CANCELLED");
    tokio::time::timeout(Duration::from_secs(3), closed.notified())
        .await
        .expect("the server must see EOF without sending response headers");
    assert!(bridge.registry.lock().unwrap().active.is_empty());
}

#[tokio::test]
async fn cancellation_before_headers_also_closes_a_reused_keep_alive_socket() {
    async fn read_head(stream: &mut TcpStream) -> String {
        let mut head = Vec::new();
        loop {
            let mut byte = [0_u8];
            assert_eq!(stream.read(&mut byte).await.unwrap(), 1);
            head.push(byte[0]);
            if head.ends_with(b"\r\n\r\n") {
                return String::from_utf8(head).unwrap();
            }
            assert!(head.len() < 65536);
        }
    }
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let started = Arc::new(Notify::new());
    let observed = started.clone();
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        assert!(read_head(&mut socket)
            .await
            .starts_with("GET /health HTTP/1.1\r\n"));
        socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\nSet-Cookie: {COOKIE_NAME}={TEST_COOKIE}; HttpOnly; Path=/; SameSite=strict\r\n\r\n{{}}").as_bytes()).await.unwrap();
        // A second request on this same socket proves connection-pool reuse.
        assert!(read_head(&mut socket)
            .await
            .starts_with("GET /v1/slow-before-headers HTTP/1.1\r\n"));
        observed.notify_one();
        let mut byte = [0_u8];
        assert_eq!(socket.read(&mut byte).await.unwrap(), 0);
    });
    let bridge = Arc::new(
        Bridge::new(
            LaunchConfig {
                port,
                namespace: "test-memory".into(),
            },
            Arc::new(MemoryStore::default()),
        )
        .unwrap(),
    );
    let input = request("/v1/slow-before-headers");
    let id = input.id.clone();
    let running = bridge.clone();
    let task = tokio::spawn(async move { running.request(input).await });
    tokio::time::timeout(Duration::from_secs(3), started.notified())
        .await
        .unwrap();
    bridge.cancel(&id).unwrap();
    assert_eq!(task.await.unwrap().unwrap_err(), "REQUEST_CANCELLED");
    tokio::time::timeout(Duration::from_secs(3), server)
        .await
        .expect("reused socket must close before response headers")
        .unwrap();
    assert!(bridge.registry.lock().unwrap().active.is_empty());
}

fn request(path: &str) -> ApiRequest {
    ApiRequest {
        id: Uuid::new_v4().to_string(),
        path: path.into(),
        method: "GET".into(),
        headers: BTreeMap::new(),
        body_base64: None,
    }
}

#[tokio::test]
async fn binary_round_trip_cookie_reuse_and_no_response_credential_exposure() {
    let server = Server::start(|incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        Reply::Body {
            status: 200,
            headers: vec![
                ("Content-Type".into(), "application/pdf".into()),
                (
                    "Content-Disposition".into(),
                    "attachment; filename=report.pdf".into(),
                ),
                (
                    "Set-Cookie".into(),
                    "foreign_session=do-not-store; Path=/".into(),
                ),
                ("Authorization".into(), "never-forward-this".into()),
            ],
            body: incoming.body.clone(),
            chunked: false,
            length: None,
        }
    })
    .await;
    let store = Arc::new(MemoryStore::default());
    let bridge = server.bridge(store.clone());
    let bytes = vec![0, 1, 0xff, 0xfe, b'%', b'P', b'D', b'F', b'\r', b'\n'];
    let mut input = request("/v1/documents");
    input.method = "POST".into();
    input
        .headers
        .insert("Content-Type".into(), "application/pdf".into());
    input.body_base64 = Some(STANDARD.encode(&bytes));
    let response = bridge.request(input).await.unwrap();
    assert_eq!(response.status, 200);
    assert_eq!(STANDARD.decode(&response.body_base64).unwrap(), bytes);
    assert_eq!(response.headers.len(), 2);
    assert!(response.headers.get("set-cookie").is_none());
    assert!(!serde_json::to_string(&response)
        .unwrap()
        .contains(TEST_COOKIE));
    assert_eq!(store.load().unwrap().as_deref(), Some(TEST_COOKIE));
    let incoming = server.received.lock().unwrap();
    assert_eq!(incoming.len(), 2);
    assert!(!incoming[0].headers.contains_key("cookie"));
    assert_eq!(
        incoming[1].headers.get("cookie").unwrap(),
        &format!("{COOKIE_NAME}={TEST_COOKIE}")
    );
    assert_eq!(
        incoming[1].headers.get("host").unwrap(),
        &format!("127.0.0.1:{}", server.port)
    );
    assert!(!incoming[1].headers.contains_key("origin"));
}

#[tokio::test]
async fn persisted_session_survives_bridge_restart_and_stores_are_isolated() {
    let server = Server::start(|_| health_reply()).await;
    let store = Arc::new(MemoryStore::default());
    server
        .bridge(store.clone())
        .request(request("/health"))
        .await
        .unwrap();
    server
        .bridge(store.clone())
        .request(request("/health"))
        .await
        .unwrap();
    assert_eq!(
        server.received.lock().unwrap()[2]
            .headers
            .get("cookie")
            .unwrap(),
        &format!("{COOKIE_NAME}={TEST_COOKIE}")
    );
    let independent = Arc::new(MemoryStore::default());
    server
        .bridge(independent)
        .request(request("/health"))
        .await
        .unwrap();
    assert!(!server.received.lock().unwrap()[4]
        .headers
        .contains_key("cookie"));
}

#[tokio::test]
async fn persistence_errors_fail_closed_and_reset_clears_only_own_session() {
    let server = Server::start(|_| health_reply()).await;
    let store = Arc::new(MemoryStore::default());
    let bridge = server.bridge(store.clone());
    store.fail_write.store(true, Ordering::SeqCst);
    assert_eq!(
        bridge.request(request("/health")).await.unwrap_err(),
        "SESSION_STORE_WRITE_FAILED"
    );
    assert_eq!(bridge.session.error(), Some("SESSION_STORE_WRITE_FAILED"));
    assert_eq!(
        bridge.request(request("/v1/sources")).await.unwrap_err(),
        "SESSION_STORE_WRITE_FAILED"
    );
    assert_eq!(server.received.lock().unwrap().len(), 1);
    assert!(store.load().unwrap().is_none());
    store.fail_write.store(false, Ordering::SeqCst);
    bridge.reset_session().await.unwrap();
    bridge.request(request("/health")).await.unwrap();
    store.fail_delete.store(true, Ordering::SeqCst);
    assert_eq!(
        bridge.reset_session().await.unwrap_err(),
        "SESSION_STORE_DELETE_FAILED"
    );
    assert_eq!(bridge.session.error(), Some("SESSION_STORE_DELETE_FAILED"));
    store.fail_delete.store(false, Ordering::SeqCst);
    bridge.reset_session().await.unwrap();
    assert!(store.load().unwrap().is_none());
    assert!(bridge.session.data.lock().await.cookie.is_none());
    assert!(bridge.session.error().is_none());
}

#[tokio::test]
async fn store_read_failure_and_invalid_cookie_never_reach_http() {
    let server = Server::start(|_| health_reply()).await;
    let store = Arc::new(MemoryStore::default());
    store.fail_read.store(true, Ordering::SeqCst);
    let bridge = server.bridge(store);
    assert_eq!(
        bridge.request(request("/health")).await.unwrap_err(),
        "SESSION_STORE_READ_FAILED"
    );
    let invalid = Arc::new(MemoryStore::default());
    *invalid.value.lock().unwrap() = Some("not-a-session; injected=1".into());
    assert_eq!(
        server
            .bridge(invalid)
            .request(request("/health"))
            .await
            .unwrap_err(),
        "SESSION_STORE_INVALID"
    );
    assert!(server.received.lock().unwrap().is_empty());
}

#[tokio::test]
async fn malformed_session_cookie_is_rejected_without_persistence() {
    for cookie in [
        format!("{COOKIE_NAME}={TEST_COOKIE}; Path=/; SameSite=strict"),
        format!("{COOKIE_NAME}={TEST_COOKIE}; HttpOnly; Path=/; SameSite=lax"),
        format!("{COOKIE_NAME}={TEST_COOKIE}; HttpOnly; Path=/; SameSite=strict; Domain=127.0.0.1"),
        format!("{COOKIE_NAME}=malformed; HttpOnly; Path=/; SameSite=strict"),
    ] {
        let server = Server::start(move |_| Reply::Body {
            status: 200,
            headers: vec![("Set-Cookie".into(), cookie.clone())],
            body: b"{}".to_vec(),
            chunked: false,
            length: None,
        })
        .await;
        let store = Arc::new(MemoryStore::default());
        assert_eq!(
            server
                .bridge(store.clone())
                .request(request("/health"))
                .await
                .unwrap_err(),
            "INVALID_SESSION_COOKIE"
        );
        assert!(store.load().unwrap().is_none());
    }
}

#[tokio::test]
async fn cancellation_drops_the_actual_response_socket_and_registration() {
    let started = Arc::new(Notify::new());
    let closed = Arc::new(Notify::new());
    let (a, b) = (started.clone(), closed.clone());
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            health_reply()
        } else {
            Reply::Hang {
                started: a.clone(),
                closed: b.clone(),
            }
        }
    })
    .await;
    let bridge = Arc::new(server.bridge(Arc::new(MemoryStore::default())));
    let input = request("/v1/slow");
    let id = input.id.clone();
    let running = bridge.clone();
    let task = tokio::spawn(async move { running.request(input).await });
    tokio::time::timeout(Duration::from_secs(3), started.notified())
        .await
        .unwrap();
    bridge.cancel(&id).unwrap();
    assert_eq!(task.await.unwrap().unwrap_err(), "REQUEST_CANCELLED");
    tokio::time::timeout(Duration::from_secs(3), closed.notified())
        .await
        .unwrap();
    assert!(bridge.registry.lock().unwrap().active.is_empty());
    bridge.cancel(&id).unwrap();
    assert!(bridge.registry.lock().unwrap().pre_cancelled.is_empty());
}

#[tokio::test]
async fn pre_cancellation_does_not_send_a_request_and_queue_is_bounded() {
    let server = Server::start(|_| health_reply()).await;
    let bridge = server.bridge(Arc::new(MemoryStore::default()));
    let input = request("/v1/sources");
    bridge.cancel(&input.id).unwrap();
    assert_eq!(
        bridge.request(input).await.unwrap_err(),
        "REQUEST_CANCELLED"
    );
    assert!(server.received.lock().unwrap().is_empty());
    for _ in 0..MAX_CANCEL_TOMBSTONES {
        bridge.cancel(&Uuid::new_v4().to_string()).unwrap();
    }
    assert_eq!(
        bridge.cancel(&Uuid::new_v4().to_string()).unwrap_err(),
        "CANCEL_QUEUE_FULL"
    );
}

#[tokio::test]
async fn timeout_is_bounded_and_closes_the_response_socket() {
    let started = Arc::new(Notify::new());
    let closed = Arc::new(Notify::new());
    let (a, b) = (started, closed.clone());
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            health_reply()
        } else {
            Reply::Hang {
                started: a.clone(),
                closed: b.clone(),
            }
        }
    })
    .await;
    let bridge = Bridge::with_limits(
        LaunchConfig {
            port: server.port,
            namespace: "test-memory".into(),
        },
        Arc::new(MemoryStore::default()),
        Duration::from_millis(120),
        MAX_RESPONSE_BYTES,
    )
    .unwrap();
    assert_eq!(
        bridge.request(request("/v1/slow")).await.unwrap_err(),
        "API_TIMEOUT"
    );
    tokio::time::timeout(Duration::from_secs(3), closed.notified())
        .await
        .unwrap();
    assert!(bridge.registry.lock().unwrap().active.is_empty());
}

#[tokio::test]
async fn redirect_is_not_followed_even_to_another_loopback_endpoint() {
    let destination = Server::start(|_| body_reply(b"should never reach here")).await;
    let port = destination.port;
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        Reply::Body {
            status: 302,
            headers: vec![(
                "Location".into(),
                format!("http://127.0.0.1:{port}/credential-leak"),
            )],
            body: vec![],
            chunked: false,
            length: None,
        }
    })
    .await;
    assert_eq!(
        server
            .bridge(Arc::new(MemoryStore::default()))
            .request(request("/v1/redirect"))
            .await
            .unwrap_err(),
        "API_REDIRECT_BLOCKED"
    );
    assert!(destination.received.lock().unwrap().is_empty());
}

#[tokio::test]
async fn response_size_is_bounded_with_or_without_content_length() {
    for chunked in [false, true] {
        let server = Server::start(move |incoming| {
            if incoming.target == "/health" {
                return health_reply();
            }
            Reply::Body {
                status: 200,
                headers: vec![],
                body: vec![0xff; 129],
                chunked,
                length: None,
            }
        })
        .await;
        let bridge = Bridge::with_limits(
            LaunchConfig {
                port: server.port,
                namespace: "test-memory".into(),
            },
            Arc::new(MemoryStore::default()),
            REQUEST_TIMEOUT,
            128,
        )
        .unwrap();
        assert_eq!(
            bridge.request(request("/v1/large")).await.unwrap_err(),
            "RESPONSE_TOO_LARGE"
        );
        assert!(bridge.registry.lock().unwrap().active.is_empty());
    }
    let server = Server::start(|incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        Reply::Body {
            status: 200,
            headers: vec![],
            body: vec![],
            chunked: false,
            length: Some(MAX_RESPONSE_BYTES + 1),
        }
    })
    .await;
    assert_eq!(
        server
            .bridge(Arc::new(MemoryStore::default()))
            .request(request("/v1/large"))
            .await
            .unwrap_err(),
        "RESPONSE_TOO_LARGE"
    );
}

#[tokio::test]
async fn request_concurrency_is_limited_and_reset_cancels_inflight_work() {
    let started = Arc::new(Notify::new());
    let closed = Arc::new(Notify::new());
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            health_reply()
        } else {
            Reply::Hang {
                started: started.clone(),
                closed: closed.clone(),
            }
        }
    })
    .await;
    let bridge = Arc::new(server.bridge(Arc::new(MemoryStore::default())));
    let mut tasks = Vec::new();
    for _ in 0..MAX_IN_FLIGHT {
        let cloned = bridge.clone();
        tasks.push(tokio::spawn(async move {
            cloned.request(request("/v1/slow")).await
        }));
    }
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if bridge.registry.lock().unwrap().active.len() == MAX_IN_FLIGHT {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        bridge.request(request("/v1/ninth")).await.unwrap_err(),
        "TOO_MANY_REQUESTS"
    );
    bridge.reset_session().await.unwrap();
    for task in tasks {
        assert_eq!(task.await.unwrap().unwrap_err(), "REQUEST_CANCELLED");
    }
    assert!(bridge.registry.lock().unwrap().active.is_empty());
    assert!(bridge.session.data.lock().await.cookie.is_none());
}

#[test]
#[ignore = "Opt in only: creates and removes one fresh application-owned OS credential"]
fn os_secure_store_round_trip_own_temporary_entry() {
    assert_eq!(
        std::env::var("TI_DESKTOP_TEST_OS_STORE").as_deref(),
        Ok("1"),
        "explicit OS-store test opt-in is required"
    );
    let config = LaunchConfig {
        port: 65534,
        namespace: format!("test-{}", Uuid::new_v4()),
    };
    let store = crate::session::OsSessionStore::open(&config).unwrap();
    struct Cleanup(Arc<dyn SessionStore>);
    impl Drop for Cleanup {
        fn drop(&mut self) {
            let _ = self.0.delete();
        }
    }
    let _cleanup = Cleanup(store.clone());
    assert!(store.load().unwrap().is_none());
    store.save(Some(TEST_COOKIE)).unwrap();
    assert_eq!(store.load().unwrap().as_deref(), Some(TEST_COOKIE));
    store.delete().unwrap();
    assert!(store.load().unwrap().is_none());
}

#[tokio::test]
async fn unlock_retry_recovers_the_durable_cookie_without_deleting_it() {
    let server = Server::start(|_| health_reply()).await;
    let store = Arc::new(MemoryStore::default());
    *store.value.lock().unwrap() = Some(TEST_COOKIE.to_owned());
    store.fail_read.store(true, Ordering::SeqCst);
    let bridge = server.bridge(store.clone());
    assert_eq!(bridge.session.error(), Some("SESSION_STORE_READ_FAILED"));
    assert_eq!(
        bridge.recover_session().await.unwrap_err(),
        "SESSION_STORE_READ_FAILED"
    );
    assert_eq!(store.value.lock().unwrap().as_deref(), Some(TEST_COOKIE));
    store.fail_read.store(false, Ordering::SeqCst);
    store.fail_write.store(true, Ordering::SeqCst);
    assert_eq!(
        bridge.recover_session().await.unwrap_err(),
        "SESSION_STORE_WRITE_FAILED"
    );
    assert_eq!(store.value.lock().unwrap().as_deref(), Some(TEST_COOKIE));
    store.fail_write.store(false, Ordering::SeqCst);
    bridge.recover_session().await.unwrap();
    assert!(bridge.session.error().is_none());
    assert_eq!(store.load().unwrap().as_deref(), Some(TEST_COOKIE));
    bridge.request(request("/health")).await.unwrap();
    assert_eq!(
        server.received.lock().unwrap()[0]
            .headers
            .get("cookie")
            .unwrap(),
        &format!("{COOKIE_NAME}={TEST_COOKIE}")
    );
}

#[tokio::test]
async fn reset_epoch_rejects_new_registration_while_canceling_queued_old_payloads() {
    let server = Server::start(|_| health_reply()).await;
    let bridge = Arc::new(server.bridge(Arc::new(MemoryStore::default())));
    // Force the old request and reset to queue, exposing the previously racy gap.
    let gate = bridge.lifecycle.write().await;
    let old_bridge = bridge.clone();
    let mut old_payload = request("/v1/watchlists");
    old_payload.method = "POST".into();
    old_payload
        .headers
        .insert("Content-Type".into(), "application/json".into());
    old_payload.body_base64 = Some(STANDARD.encode(br#"{"old_session_only":true}"#));
    let old = tokio::spawn(async move { old_bridge.request(old_payload).await });
    tokio::time::timeout(Duration::from_secs(3), async {
        while bridge.registry.lock().unwrap().active.is_empty() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let reset_bridge = bridge.clone();
    let reset = tokio::spawn(async move { reset_bridge.reset_session().await });
    tokio::time::timeout(Duration::from_secs(3), async {
        while !bridge.registry.lock().unwrap().resetting {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        bridge
            .request(request("/v1/new-during-reset"))
            .await
            .unwrap_err(),
        "SESSION_RESET_IN_PROGRESS"
    );
    assert_eq!(old.await.unwrap().unwrap_err(), "REQUEST_CANCELLED");
    assert_eq!(bridge.registry.lock().unwrap().generation, 1);
    assert!(server.received.lock().unwrap().is_empty());
    drop(gate);
    reset.await.unwrap().unwrap();
    assert!(!bridge.registry.lock().unwrap().resetting);
    bridge.request(request("/health")).await.unwrap();
    assert!(server
        .received
        .lock()
        .unwrap()
        .iter()
        .all(|request| request.target == "/health"));
}
