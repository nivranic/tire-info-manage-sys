use crate::security::{
    request_id, validate_request, ApiRequest, ApiResponse, LaunchConfig, NativeResult,
    ValidatedRequest, MAX_RESPONSE_BYTES,
};
use crate::session::{Session, SessionData, SessionStore, COOKIE_NAME};
use base64::{engine::general_purpose::STANDARD, Engine};
use cookie::{Cookie, SameSite};
use reqwest::{
    header::{HeaderMap, SET_COOKIE},
    Client, Method, Response,
};
use std::{
    collections::{BTreeMap, HashMap, VecDeque},
    sync::{Arc, Mutex, Weak},
    time::{Duration, Instant},
};
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(75);
const MAX_IN_FLIGHT: usize = 8;
const MAX_CANCEL_TOMBSTONES: usize = 256;

fn consent_denial_request(request: &ValidatedRequest) -> Option<String> {
    if request.method != Method::POST || request.path != "/v1/fallback-consents" {
        return None;
    }
    let raw = crate::offline::raw::Exact::parse(std::str::from_utf8(&request.body).ok()?).ok()?;
    let body = raw.package_mirror();
    let object = body.as_object()?;
    if object.len() != 3 || body["decision"] != "deny" || body["scope"] != "once" {
        return None;
    }
    body["query_id"]
        .as_str()
        .filter(|id| crate::offline::wire::uuid(id))
        .map(str::to_owned)
}
fn consent_denial_response(response: &ApiResponse, _query: &str) -> bool {
    if response.status != 201 {
        return false;
    }
    let Ok(bytes) = STANDARD.decode(&response.body_base64) else {
        return false;
    };
    let Ok(text) = std::str::from_utf8(&bytes) else {
        return false;
    };
    let Ok(raw) = crate::offline::raw::Exact::parse(text) else {
        return false;
    };
    let body = raw.package_mirror();
    body["decision"] == "deny"
        && body["scope"] == "once"
        && body["id"].as_str().is_some_and(crate::offline::wire::uuid)
}

#[derive(Default)]
struct Registry {
    active: HashMap<Uuid, CancellationToken>,
    pre_cancelled: HashMap<Uuid, Instant>,
    completed: VecDeque<(Uuid, Instant)>,
    resetting: bool,
    generation: u64,
}

impl Registry {
    fn prune(&mut self) {
        self.pre_cancelled
            .retain(|_, at| at.elapsed() < REQUEST_TIMEOUT);
        while self
            .completed
            .front()
            .is_some_and(|(_, at)| at.elapsed() >= REQUEST_TIMEOUT)
        {
            self.completed.pop_front();
        }
    }
}

struct Registration<'a> {
    registry: &'a Mutex<Registry>,
    id: Uuid,
    token: CancellationToken,
    generation: u64,
}

struct ResetRegistration<'a>(&'a Mutex<Registry>);

impl Drop for ResetRegistration<'_> {
    fn drop(&mut self) {
        if let Ok(mut registry) = self.0.lock() {
            registry.resetting = false;
        }
    }
}

impl Drop for Registration<'_> {
    fn drop(&mut self) {
        self.token.cancel();
        if let Ok(mut registry) = self.registry.lock() {
            registry.active.remove(&self.id);
            registry.completed.push_back((self.id, Instant::now()));
            if registry.completed.len() > MAX_CANCEL_TOMBSTONES {
                registry.completed.pop_front();
            }
        }
    }
}

pub struct Bridge {
    pub config: LaunchConfig,
    pub session: Session,
    client: Client,
    registry: Mutex<Registry>,
    lifecycle: RwLock<()>,
    timeout: Duration,
    response_limit: usize,
    fallback_store: Mutex<Option<Weak<crate::offline::Store>>>,
}

// Never Serialize/Debug this authority: cookie material remains host-private.
pub struct SessionFence {
    cookie: zeroize::Zeroizing<String>,
    generation: u64,
    transport_generation: u64,
}
impl SessionFence {
    pub(crate) fn same_session(&self, other: &Self) -> bool {
        self.generation == other.generation
            && self.transport_generation == other.transport_generation
            && self.cookie == other.cookie
    }
}
pub enum SyncEndpoint {
    Prepare,
    Confirm,
    Descriptor(String),
    Download(String),
}

impl Bridge {
    pub fn bind_fallback_store(&self, store: &Arc<crate::offline::Store>) -> NativeResult<()> {
        *self
            .fallback_store
            .lock()
            .map_err(|_| "API_CLIENT_UNAVAILABLE")? = Some(Arc::downgrade(store));
        Ok(())
    }
    pub async fn sync_fence(&self) -> NativeResult<SessionFence> {
        self.session.check()?;
        let data = self.session.data.lock().await;
        let cookie = data
            .cookie
            .as_ref()
            .ok_or("OFFLINE_SYNC_SESSION_REQUIRED")?;
        let registry = self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?;
        if registry.resetting {
            return Err("SESSION_RESET_IN_PROGRESS");
        }
        Ok(SessionFence {
            cookie: zeroize::Zeroizing::new(cookie.clone()),
            generation: data.generation,
            transport_generation: registry.generation,
        })
    }
    pub fn sync_fence_matches(&self, fence: &SessionFence, data: &SessionData) -> NativeResult<()> {
        self.session.check()?;
        let registry = self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?;
        if registry.resetting
            || registry.generation != fence.transport_generation
            || data.generation != fence.generation
            || data.cookie.as_deref() != Some(fence.cookie.as_str())
        {
            Err("SESSION_CHANGED")
        } else {
            Ok(())
        }
    }
    pub async fn check_sync_fence(&self, fence: &SessionFence) -> NativeResult<()> {
        let data = self.session.data.lock().await;
        self.sync_fence_matches(fence, &data)
    }
    /// Fixed metadata only, with one private cookie/session fence across both
    /// GETs. No URL/request/source arguments or /health bootstrap are accepted.
    pub async fn fallback_authority_metadata(
        &self,
        fence: &SessionFence,
    ) -> NativeResult<(String, serde_json::Value, serde_json::Value)> {
        let registration = self.register(Uuid::new_v4())?;
        let reads = async {
            let mut result = Vec::new();
            let mut owner = None;
            for path in ["/v1/source-settings", "/v1/sources"] {
                self.check_sync_fence(fence).await?;
                let response = self
                    .send(
                        Method::GET,
                        path,
                        HeaderMap::new(),
                        Vec::new(),
                        Some(fence.cookie.as_str()),
                    )
                    .await?;
                {
                    let mut data = self.session.data.lock().await;
                    self.sync_fence_matches(fence, &data)?;
                    self.update_cookie(response.headers(), &mut data)?;
                    self.sync_fence_matches(fence, &data)?;
                }
                if response.status().as_u16() != 200 {
                    return Err("OFFLINE_FALLBACK_AUTHORITY_HTTP_REJECTED");
                }
                let headers = response.headers();
                if !headers
                    .get("content-type")
                    .and_then(|v| v.to_str().ok())
                    .is_some_and(|v| {
                        v.split(';')
                            .next()
                            .is_some_and(|v| v.trim() == "application/json")
                    })
                    || headers.contains_key("content-encoding")
                {
                    return Err("OFFLINE_FALLBACK_AUTHORITY_RESPONSE_INVALID");
                }
                if path == "/v1/source-settings" {
                    if headers.get_all("x-tire-offline-owner-scope").iter().count() != 1 {
                        return Err("OFFLINE_FALLBACK_AUTHORITY_RESPONSE_INVALID");
                    }
                    let scope = headers
                        .get("x-tire-offline-owner-scope")
                        .and_then(|v| v.to_str().ok())
                        .filter(|v| crate::offline::wire::hex(v))
                        .ok_or("OFFLINE_FALLBACK_AUTHORITY_RESPONSE_INVALID")?;
                    owner = Some(scope.to_owned());
                }
                let bytes = Self::read_owned_bytes(response, MAX_RESPONSE_BYTES).await?;
                result.push(
                    crate::offline::wire::strict_json(&bytes)
                        .map_err(|_| "OFFLINE_FALLBACK_AUTHORITY_RESPONSE_INVALID")?,
                );
                self.check_sync_fence(fence).await?;
            }
            Ok((
                owner.ok_or("OFFLINE_FALLBACK_AUTHORITY_RESPONSE_INVALID")?,
                result.remove(0),
                result.remove(0),
            ))
        };
        tokio::select! {biased; _=registration.token.cancelled()=>Err("REQUEST_CANCELLED"), result=tokio::time::timeout(self.timeout,reads)=>result.map_err(|_|"API_REQUEST_TIMEOUT")?}
    }
    // Caller holds session.data for this short synchronous publication only.
    pub fn sync_transport_commit<T>(
        &self,
        fence: &SessionFence,
        publish: impl FnOnce() -> NativeResult<T>,
    ) -> NativeResult<T> {
        self.session.check()?;
        let registry = self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?;
        if registry.resetting || registry.generation != fence.transport_generation {
            return Err("SESSION_CHANGED");
        }
        publish()
    }
    pub async fn sync_publish<T: Send + 'static>(
        self: &Arc<Self>,
        fence: Arc<SessionFence>,
        publish: impl FnOnce() -> NativeResult<T> + Send + 'static,
    ) -> NativeResult<T> {
        // A spawned blocking worker is not cancelled when its awaiting task
        // is dropped. Move the owned session guard into that worker so cookie
        // changes remain serialized with publication even in that case.
        let data = self.session.data.clone().lock_owned().await;
        let bridge = self.clone();
        tokio::task::spawn_blocking(move || {
            bridge.sync_fence_matches(&fence, &data)?;
            bridge.sync_transport_commit(&fence, publish)
        })
        .await
        .map_err(|_| "OFFLINE_SYNC_WORKER_FAILED")?
    }
    pub async fn sync_request(
        &self,
        fence: &SessionFence,
        owner: &str,
        endpoint: SyncEndpoint,
        body: Vec<u8>,
        key: Option<&str>,
    ) -> NativeResult<zeroize::Zeroizing<Vec<u8>>> {
        if !crate::offline::wire::hex(owner) {
            return Err("OFFLINE_SYNC_OWNER_INVALID");
        }
        let is_download = matches!(&endpoint, SyncEndpoint::Download(_));
        let (method, path, limit, status) = match endpoint {
            SyncEndpoint::Prepare => (
                Method::POST,
                "/v1/offline-pack-updates:prepare".into(),
                MAX_RESPONSE_BYTES,
                200,
            ),
            SyncEndpoint::Confirm => {
                if key.is_none_or(|key| request_id(key).is_err()) {
                    return Err("OFFLINE_SYNC_CONFIRMATION_KEY_INVALID");
                }
                (Method::POST, "/v1/offline-packs".into(), 64 * 1024, 201)
            }
            SyncEndpoint::Descriptor(id) | SyncEndpoint::Download(id)
                if !crate::offline::wire::uuid(&id) =>
            {
                return Err("OFFLINE_SYNC_PACKAGE_INVALID")
            }
            SyncEndpoint::Descriptor(id) => (
                Method::GET,
                format!("/v1/offline-packs/{id}?mode=history"),
                64 * 1024,
                200,
            ),
            SyncEndpoint::Download(id) => (
                Method::GET,
                format!("/v1/offline-packs/{id}/download?mode=history"),
                crate::offline::MAX_PACKAGE_BYTES,
                200,
            ),
        };
        self.check_sync_fence(fence).await?;
        let registration = self.register(Uuid::new_v4())?;
        tokio::select! {
            biased;
            _ = registration.token.cancelled() => Err("REQUEST_CANCELLED"),
            result = tokio::time::timeout(self.timeout, async {
                let mut headers = HeaderMap::new();
                headers.insert("x-tire-offline-sync", reqwest::header::HeaderValue::from_static("1"));
                headers.insert("x-tire-offline-expected-owner", reqwest::header::HeaderValue::from_str(owner).map_err(|_| "OFFLINE_SYNC_OWNER_INVALID")?);
                if method == Method::POST { headers.insert("content-type", reqwest::header::HeaderValue::from_static("application/json")); }
                if let Some(key) = key { headers.insert("idempotency-key", reqwest::header::HeaderValue::from_str(key).map_err(|_| "OFFLINE_SYNC_CONFIRMATION_KEY_INVALID")?); }
                let response = self.send(method, &path, headers, body, Some(fence.cookie.as_str())).await?;
                { let mut data = self.session.data.lock().await; self.sync_fence_matches(fence, &data)?;
                    self.update_cookie(response.headers(), &mut data)?; self.sync_fence_matches(fence, &data)?; }
                if response.status().as_u16() == 401 { return Err("OFFLINE_SYNC_SESSION_REQUIRED"); }
                if response.status().as_u16() != status { return Err("OFFLINE_SYNC_HTTP_REJECTED"); }
                let headers = response.headers();
                if headers.get_all("x-tire-offline-owner-scope").iter().count() != 1
                    || headers.get("x-tire-offline-owner-scope").and_then(|v| v.to_str().ok()) != Some(owner)
                    || headers.get("cache-control").and_then(|v| v.to_str().ok()) != Some("no-store")
                    || !headers.get("content-type").and_then(|v| v.to_str().ok()).is_some_and(|v| v.split(';').next().is_some_and(|v| v.trim() == "application/json"))
                    || headers.contains_key("content-encoding") { return Err("OFFLINE_SYNC_RESPONSE_INVALID"); }
                if is_download {
                    let etag = headers.get("etag").and_then(|v| v.to_str().ok()).and_then(|v| v.strip_prefix('"')).and_then(|v| v.strip_suffix('"'));
                    if etag.is_none_or(|v| !crate::offline::wire::hex(v))
                        || headers.get("x-content-sha256").and_then(|v| v.to_str().ok()) != etag
                        || headers.get("x-content-type-options").and_then(|v| v.to_str().ok()) != Some("nosniff")
                        || !headers.get("content-disposition").and_then(|v| v.to_str().ok()).is_some_and(|v| v.starts_with("attachment;")) {
                        return Err("OFFLINE_SYNC_RESPONSE_INVALID");
                    }
                }
                let bytes = Self::read_owned_bytes(response, limit).await?;
                self.check_sync_fence(fence).await?; Ok(bytes)
            }) => result.unwrap_or(Err("API_TIMEOUT")),
        }
    }
}

impl Bridge {
    /// A dedicated byte path for one owned package. IPC supplies neither a URL
    /// nor bytes; ordinary API request/response limits remain unchanged.
    pub async fn owned_pack(
        &self,
        request: &crate::offline::wire::InstallRequest,
    ) -> NativeResult<(
        crate::offline::wire::Descriptor,
        zeroize::Zeroizing<Vec<u8>>,
    )> {
        request.validate()?;
        let registration = self.register(Uuid::new_v4())?;
        tokio::select! {
            biased;
            _ = registration.token.cancelled() => Err("REQUEST_CANCELLED"),
            result = tokio::time::timeout(self.timeout, async {
                let _lifecycle = self.lifecycle.read().await;
                if self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?.generation != registration.generation { return Err("REQUEST_CANCELLED"); }
                self.bootstrap().await?;
                let cookie = self.session.data.lock().await.cookie.clone();
                let path = format!("/v1/offline-packs/{}?mode=history", request.package_id);
                let response = self.owned_response(&path, cookie.as_deref()).await?;
                let metadata = Self::read_owned_bytes(response, 64 * 1024).await?;
                let descriptor = crate::offline::wire::descriptor(&metadata, request)?;
                let path = format!("/v1/offline-packs/{}/download?mode=history", request.package_id);
                let response = self.owned_response(&path, cookie.as_deref()).await?;
                let headers = response.headers();
                let header = |name: &str| headers.get(name).and_then(|value| value.to_str().ok());
                let quoted = format!("\"{}\"", descriptor.sha256);
                if response.content_length().is_some_and(|length| length != descriptor.byte_count)
                    || header("etag") != Some(quoted.as_str()) || header("x-content-sha256") != Some(descriptor.sha256.as_str())
                    || header("cache-control") != Some("no-store") || header("x-content-type-options") != Some("nosniff")
                    || !header("content-disposition").is_some_and(|value| value.starts_with("attachment;")) {
                    return Err("OFFLINE_RESPONSE_INVALID");
                }
                let bytes = Self::read_owned_bytes(response, crate::offline::MAX_PACKAGE_BYTES).await?;
                crate::offline::wire::verify_bytes(&bytes, &descriptor)?;
                Ok((descriptor, bytes))
            }) => result.unwrap_or(Err("API_TIMEOUT")),
        }
    }

    async fn owned_response(&self, path: &str, cookie: Option<&str>) -> NativeResult<Response> {
        self.session.check()?;
        let response = self
            .send(Method::GET, path, HeaderMap::new(), Vec::new(), cookie)
            .await?;
        {
            let mut session = self.session.data.lock().await;
            self.session.check()?;
            if session.cookie.as_deref() != cookie {
                return Err("SESSION_CHANGED");
            }
            self.update_cookie(response.headers(), &mut session)?;
            if session.cookie.as_deref() != cookie {
                return Err("SESSION_CHANGED");
            }
        }
        if response.status().as_u16() != 200 {
            return Err("OFFLINE_DOWNLOAD_FAILED");
        }
        if !response
            .headers()
            .get("content-type")
            .and_then(|value| value.to_str().ok())
            .is_some_and(|value| {
                value
                    .split(';')
                    .next()
                    .is_some_and(|mime| mime.trim() == "application/json")
            })
            || response.headers().contains_key("content-encoding")
        {
            return Err("OFFLINE_RESPONSE_INVALID");
        }
        Ok(response)
    }

    async fn read_owned_bytes(
        mut response: Response,
        limit: usize,
    ) -> NativeResult<zeroize::Zeroizing<Vec<u8>>> {
        if response
            .content_length()
            .is_some_and(|length| length > limit as u64)
        {
            return Err("OFFLINE_PACK_TOO_LARGE");
        }
        let mut bytes = zeroize::Zeroizing::new(Vec::new());
        while let Some(chunk) = response.chunk().await.map_err(network_error)? {
            if chunk.len() > limit.saturating_sub(bytes.len()) {
                return Err("OFFLINE_PACK_TOO_LARGE");
            }
            bytes.extend_from_slice(&chunk);
        }
        Ok(bytes)
    }

    pub fn new(config: LaunchConfig, store: Arc<dyn SessionStore>) -> NativeResult<Self> {
        Self::with_limits(config, store, REQUEST_TIMEOUT, MAX_RESPONSE_BYTES)
    }

    fn with_limits(
        config: LaunchConfig,
        store: Arc<dyn SessionStore>,
        timeout: Duration,
        response_limit: usize,
    ) -> NativeResult<Self> {
        let client = Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(3))
            .timeout(timeout)
            .pool_idle_timeout(Duration::from_secs(30))
            .pool_max_idle_per_host(4)
            .http1_only()
            .build()
            .map_err(|_| "API_CLIENT_UNAVAILABLE")?;
        Ok(Self {
            config,
            session: Session::new(store),
            client,
            registry: Mutex::default(),
            lifecycle: RwLock::new(()),
            timeout,
            response_limit,
            fallback_store: Mutex::new(None),
        })
    }

    fn register(&self, id: Uuid) -> NativeResult<Registration<'_>> {
        let mut registry = self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?;
        registry.prune();
        if registry.resetting {
            return Err("SESSION_RESET_IN_PROGRESS");
        }
        if registry.pre_cancelled.remove(&id).is_some() {
            return Err("REQUEST_CANCELLED");
        }
        if registry.active.contains_key(&id)
            || registry.completed.iter().any(|(value, _)| *value == id)
        {
            return Err("DUPLICATE_REQUEST_ID");
        }
        if registry.active.len() >= MAX_IN_FLIGHT {
            return Err("TOO_MANY_REQUESTS");
        }
        let token = CancellationToken::new();
        registry.active.insert(id, token.clone());
        Ok(Registration {
            registry: &self.registry,
            id,
            token,
            generation: registry.generation,
        })
    }

    pub fn cancel(&self, id: &str) -> NativeResult<()> {
        let id = request_id(id)?;
        let mut registry = self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?;
        registry.prune();
        if let Some(token) = registry.active.get(&id) {
            token.cancel();
        } else if !registry.completed.iter().any(|(value, _)| *value == id) {
            if registry.pre_cancelled.len() >= MAX_CANCEL_TOMBSTONES
                && !registry.pre_cancelled.contains_key(&id)
            {
                return Err("CANCEL_QUEUE_FULL");
            }
            registry.pre_cancelled.insert(id, Instant::now());
        }
        Ok(())
    }

    pub async fn request(&self, request: ApiRequest) -> NativeResult<ApiResponse> {
        let registration = self.register(request_id(&request.id)?)?;
        let request = validate_request(request)?;
        // Dropping the losing future cancels reqwest's actual connection/body read.
        // Cancellation never claims that a server-side mutation was rolled back.
        tokio::select! {
            biased;
            _ = registration.token.cancelled() => Err("REQUEST_CANCELLED"),
            result = tokio::time::timeout(self.timeout, async {
                let _lifecycle = self.lifecycle.read().await;
                if self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?.generation != registration.generation {
                    return Err("REQUEST_CANCELLED");
                }
                self.bootstrap().await?;
                self.perform(request).await
            }) => result.unwrap_or(Err("API_TIMEOUT")),
        }
    }

    pub async fn reset_session(&self) -> NativeResult<()> {
        {
            let mut registry = self.registry.lock().map_err(|_| "API_CLIENT_UNAVAILABLE")?;
            if registry.resetting {
                return Err("SESSION_RESET_IN_PROGRESS");
            }
            registry.resetting = true;
            registry.generation = registry.generation.wrapping_add(1);
            for token in registry.active.values() {
                token.cancel();
            }
        }
        let _reset = ResetRegistration(&self.registry);
        let _lifecycle = self.lifecycle.write().await;
        self.session.reset().await
    }

    pub async fn recover_session(&self) -> NativeResult<()> {
        if self.session.error().is_none() {
            return Ok(());
        }
        let _lifecycle = self.lifecycle.write().await;
        self.session.recover().await
    }

    async fn bootstrap(&self) -> NativeResult<()> {
        self.session.check()?;
        let mut session = self.session.data.lock().await;
        self.session.check()?;
        if session.bootstrapped {
            return Ok(());
        }
        let response = self
            .send(
                Method::GET,
                "/health",
                HeaderMap::new(),
                Vec::new(),
                session.cookie.as_deref(),
            )
            .await?;
        self.update_cookie(response.headers(), &mut session)?;
        let response = self.read_response(response).await?;
        if response.status != 200 {
            return Err("API_HEALTH_FAILED");
        }
        if session.cookie.is_none() {
            return Err("SESSION_COOKIE_MISSING");
        }
        session.bootstrapped = true;
        Ok(())
    }

    async fn perform(&self, request: ValidatedRequest) -> NativeResult<ApiResponse> {
        self.session.check()?;
        let denial = consent_denial_request(&request);
        let fence = if denial.is_some() {
            Some(Arc::new(self.sync_fence().await?))
        } else {
            None
        };
        let cookie = self.session.data.lock().await.cookie.clone();
        let response = self
            .send(
                request.method,
                &request.path,
                request.headers,
                request.body,
                cookie.as_deref(),
            )
            .await?;
        {
            let mut session = self.session.data.lock().await;
            self.session.check()?;
            if session.cookie != cookie {
                return Err("SESSION_CHANGED");
            }
            self.update_cookie(response.headers(), &mut session)?;
        }
        let result = self.read_response(response).await?;
        if let (Some(query), Some(fence)) = (denial, fence) {
            if consent_denial_response(&result, &query) {
                // Body parsing is complete. Observation and fallback publication
                // both retain this private session guard and transport gate.
                let data = self.session.data.lock().await;
                self.sync_fence_matches(&fence, &data)?;
                let store = self
                    .fallback_store
                    .lock()
                    .map_err(|_| "API_CLIENT_UNAVAILABLE")?
                    .as_ref()
                    .and_then(Weak::upgrade);
                if let Some(store) = store {
                    self.sync_transport_commit(&fence, || {
                        store.fallback_observe_query_denial(&query, fence.clone())
                    })?;
                }
            }
        }
        Ok(result)
    }

    async fn send(
        &self,
        method: Method,
        path: &str,
        headers: HeaderMap,
        body: Vec<u8>,
        cookie: Option<&str>,
    ) -> NativeResult<Response> {
        // path was validated before concatenation; JS never supplies this authority.
        let mut request = self
            .client
            .request(method, format!("{}{}", self.config.base_url(), path))
            .headers(headers)
            .header(
                "Accept",
                "application/json, application/pdf, text/plain, text/html",
            )
            .header("Cache-Control", "no-store");
        if let Some(cookie) = cookie {
            request = request.header("Cookie", format!("{COOKIE_NAME}={cookie}"));
        }
        let response = request.body(body).send().await.map_err(network_error)?;
        if response.status().is_redirection() {
            return Err("API_REDIRECT_BLOCKED");
        }
        Ok(response)
    }

    fn update_cookie(&self, headers: &HeaderMap, session: &mut SessionData) -> NativeResult<()> {
        let mut replacement = None;
        for header in headers.get_all(SET_COOKIE) {
            let raw = header.to_str().map_err(|_| "INVALID_SESSION_COOKIE")?;
            if raw.len() > 4096 {
                return Err("INVALID_SESSION_COOKIE");
            }
            let parsed = Cookie::parse(raw).map_err(|_| "INVALID_SESSION_COOKIE")?;
            // Other cookies are deliberately neither persisted nor replayed.
            if parsed.name() != COOKIE_NAME {
                continue;
            }
            if replacement.is_some()
                || parsed.http_only() != Some(true)
                || parsed.same_site() != Some(SameSite::Strict)
                || parsed.path() != Some("/")
                || parsed.domain().is_some()
                || parsed.secure() == Some(true)
            {
                return Err("INVALID_SESSION_COOKIE");
            }
            let value = if parsed.max_age().is_some_and(|age| age.whole_seconds() <= 0) {
                None
            } else {
                request_id(parsed.value()).map_err(|_| "INVALID_SESSION_COOKIE")?;
                Some(parsed.value().to_owned())
            };
            replacement = Some(value);
        }
        if let Some(value) = replacement {
            if value.is_none() {
                session.bootstrapped = false;
            }
            self.session.persist(session, value)?;
        }
        Ok(())
    }

    async fn read_response(&self, mut response: Response) -> NativeResult<ApiResponse> {
        if response
            .content_length()
            .is_some_and(|len| len > self.response_limit as u64)
        {
            return Err("RESPONSE_TOO_LARGE");
        }
        let mut headers = BTreeMap::new();
        for name in [
            "content-type",
            "content-disposition",
            "cache-control",
            "x-content-type-options",
            "retry-after",
        ] {
            if let Some(value) = response.headers().get(name) {
                let value = value.to_str().map_err(|_| "INVALID_RESPONSE_HEADER")?;
                if value.len() > 4096 || value.chars().any(char::is_control) {
                    return Err("INVALID_RESPONSE_HEADER");
                }
                headers.insert(name.to_owned(), value.to_owned());
            }
        }
        let status = response.status().as_u16();
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(network_error)? {
            if chunk.len() > self.response_limit.saturating_sub(bytes.len()) {
                return Err("RESPONSE_TOO_LARGE");
            }
            bytes.extend_from_slice(&chunk);
        }
        Ok(ApiResponse {
            status,
            headers,
            body_base64: STANDARD.encode(bytes),
        })
    }
}

fn network_error(error: reqwest::Error) -> &'static str {
    if error.is_timeout() {
        "API_TIMEOUT"
    } else if error.is_connect() {
        "API_UNAVAILABLE"
    } else {
        "API_REQUEST_FAILED"
    }
}

#[cfg(test)]
mod tests;
