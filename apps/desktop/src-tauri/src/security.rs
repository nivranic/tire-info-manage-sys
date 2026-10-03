//! Validates all untrusted IPC input before it reaches network or OS APIs.
use base64::{engine::general_purpose::STANDARD, Engine};
use percent_encoding::percent_decode_str;
use reqwest::{header::HeaderMap, Method};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use url::Url;
use uuid::Uuid;

pub type NativeResult<T> = Result<T, &'static str>;
pub const MAX_REQUEST_BYTES: usize = 10 * 1024 * 1024;
pub const MAX_RESPONSE_BYTES: usize = 32 * 1024 * 1024;

#[derive(Clone)]
pub struct LaunchConfig {
    pub port: u16,
    pub namespace: String,
}

impl LaunchConfig {
    pub fn from_env() -> NativeResult<Self> {
        let port = std::env::var("TI_DESKTOP_API_PORT").ok();
        let namespace = std::env::var("TI_DESKTOP_SESSION_NAMESPACE").ok();
        Self::parse(port.as_deref(), namespace.as_deref())
    }

    pub fn parse(port: Option<&str>, namespace: Option<&str>) -> NativeResult<Self> {
        let port = match port {
            None => 8000,
            Some(raw) if !raw.is_empty() && raw.bytes().all(|b| b.is_ascii_digit()) => {
                raw.parse::<u16>().map_err(|_| "INVALID_API_PORT")?
            }
            _ => return Err("INVALID_API_PORT"),
        };
        if port < 1024 {
            return Err("INVALID_API_PORT");
        }
        let namespace = namespace.unwrap_or("default");
        if namespace.is_empty()
            || namespace.len() > 48
            || !namespace
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
            || namespace.starts_with('-')
            || namespace.ends_with('-')
        {
            return Err("INVALID_SESSION_NAMESPACE");
        }
        Ok(Self {
            port,
            namespace: namespace.to_owned(),
        })
    }

    pub fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    pub fn store_account(&self) -> String {
        format!("{}:127.0.0.1:{}", self.namespace, self.port)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ApiRequest {
    pub id: String,
    pub path: String,
    pub method: String,
    #[serde(default)]
    pub headers: BTreeMap<String, String>,
    pub body_base64: Option<String>,
}

#[derive(Serialize, Debug)]
pub struct ApiResponse {
    pub status: u16,
    pub headers: BTreeMap<String, String>,
    pub body_base64: String,
}

pub struct ValidatedRequest {
    pub method: Method,
    pub path: String,
    pub headers: HeaderMap,
    pub body: Vec<u8>,
}

pub fn request_id(value: &str) -> NativeResult<Uuid> {
    if value.len() != 36 {
        return Err("INVALID_REQUEST_ID");
    }
    Uuid::parse_str(value).map_err(|_| "INVALID_REQUEST_ID")
}

fn decoded_component(value: &str) -> NativeResult<String> {
    let bytes = value.as_bytes();
    for (i, b) in bytes.iter().enumerate() {
        if *b == b'%'
            && (i + 2 >= bytes.len()
                || !bytes[i + 1].is_ascii_hexdigit()
                || !bytes[i + 2].is_ascii_hexdigit())
        {
            return Err("INVALID_API_PATH");
        }
    }
    percent_decode_str(value)
        .decode_utf8()
        .map(|s| s.into_owned())
        .map_err(|_| "INVALID_API_PATH")
}

pub fn validate_path(path: &str) -> NativeResult<()> {
    if path.len() > 4096 || path.contains(['\\', '#']) || path.chars().any(char::is_control) {
        return Err("INVALID_API_PATH");
    }
    let (route, query) = path.split_once('?').unwrap_or((path, ""));
    if !(route == "/health" || route.starts_with("/v1/")) || route.contains("//") {
        return Err("INVALID_API_PATH");
    }
    let decoded = decoded_component(route)?;
    // Reject nested escapes as well as separators/dot segments before Url can normalize them.
    if decoded.contains(['\\', '%', '#', '?'])
        || decoded.chars().any(char::is_control)
        || decoded.bytes().filter(|b| *b == b'/').count()
            != route.bytes().filter(|b| *b == b'/').count()
        || decoded.split('/').any(|part| part == "." || part == "..")
    {
        return Err("INVALID_API_PATH");
    }
    let decoded_query = decoded_component(query)?;
    if decoded_query.chars().any(char::is_control) {
        return Err("INVALID_API_PATH");
    }
    Ok(())
}

pub fn decode_bounded(value: &str, limit: usize, error: &'static str) -> NativeResult<Vec<u8>> {
    if value.len() > limit.div_ceil(3) * 4 {
        return Err(error);
    }
    let bytes = STANDARD.decode(value).map_err(|_| "INVALID_BASE64")?;
    if bytes.len() > limit {
        return Err(error);
    }
    Ok(bytes)
}

pub fn validate_request(request: ApiRequest) -> NativeResult<ValidatedRequest> {
    validate_path(&request.path)?;
    let method = match request.method.as_str() {
        "GET" => Method::GET,
        "POST" => Method::POST,
        "PUT" => Method::PUT,
        "DELETE" => Method::DELETE,
        _ => return Err("INVALID_API_METHOD"),
    };
    let mut seen = HashSet::new();
    let mut headers = HeaderMap::new();
    for (name, value) in request.headers {
        let name = name.to_ascii_lowercase();
        if !seen.insert(name.clone()) || value.chars().any(char::is_control) {
            return Err("INVALID_API_HEADER");
        }
        match name.as_str() {
            "content-type" if matches!(value.as_str(), "application/json" | "application/pdf") => {}
            "idempotency-key" if request_id(&value).is_ok() => {}
            "x-evidence-metadata" => {
                let bytes = decode_bounded(&value, 12 * 1024, "INVALID_API_HEADER")
                    .map_err(|_| "INVALID_API_HEADER")?;
                let parsed: serde_json::Value =
                    serde_json::from_slice(&bytes).map_err(|_| "INVALID_API_HEADER")?;
                if !parsed.is_object() {
                    return Err("INVALID_API_HEADER");
                }
            }
            _ => return Err("INVALID_API_HEADER"),
        }
        headers.insert(
            reqwest::header::HeaderName::from_bytes(name.as_bytes())
                .map_err(|_| "INVALID_API_HEADER")?,
            reqwest::header::HeaderValue::from_str(&value).map_err(|_| "INVALID_API_HEADER")?,
        );
    }
    if request.body_base64.is_some()
        && (method == Method::GET || !headers.contains_key("content-type"))
    {
        return Err("INVALID_API_BODY");
    }
    let body = match request.body_base64 {
        Some(value) => decode_bounded(&value, MAX_REQUEST_BYTES, "REQUEST_TOO_LARGE")?,
        None => Vec::new(),
    };
    Ok(ValidatedRequest {
        method,
        path: request.path,
        headers,
        body,
    })
}

pub fn external_url(value: &str) -> NativeResult<Url> {
    if value.len() > 8192 || value.chars().any(char::is_control) || value.contains('\\') {
        return Err("INVALID_EXTERNAL_URL");
    }
    let url = Url::parse(value).map_err(|_| "INVALID_EXTERNAL_URL")?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("INVALID_EXTERNAL_URL");
    }
    Ok(url)
}

pub fn download_extension(filename: &str, mime: &str) -> NativeResult<&'static str> {
    if filename.is_empty()
        || filename.len() > 180
        || filename.starts_with('.')
        || filename.ends_with(['.', ' '])
        || filename.contains(['/', '\\', ':', '<', '>', '"', '|', '?', '*'])
        || filename.chars().any(char::is_control)
    {
        return Err("INVALID_DOWNLOAD_NAME");
    }
    let stem = filename
        .split('.')
        .next()
        .unwrap_or_default()
        .to_ascii_uppercase();
    if matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || (stem.len() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && stem.as_bytes()[3].is_ascii_digit())
    {
        return Err("INVALID_DOWNLOAD_NAME");
    }
    match (
        filename.rsplit('.').next(),
        mime.split(';').next().map(str::trim),
    ) {
        (Some("md"), Some("text/markdown" | "text/plain")) => Ok("md"),
        (Some("html"), Some("text/html")) => Ok("html"),
        (Some("pdf"), Some("application/pdf")) => Ok("pdf"),
        _ => Err("INVALID_DOWNLOAD_TYPE"),
    }
}

pub fn allowed_navigation(url: &Url, development: bool) -> bool {
    if !url.username().is_empty() || url.password().is_some() {
        return false;
    }
    let local =
        (url.scheme() == "tauri" && url.host_str() == Some("localhost") && url.port().is_none())
            || (url.scheme() == "http"
                && url.host_str() == Some("tauri.localhost")
                && url.port().is_none());
    local
        || (development
            && url.scheme() == "http"
            && url.host_str() == Some("127.0.0.1")
            && url.port() == Some(1420))
}
