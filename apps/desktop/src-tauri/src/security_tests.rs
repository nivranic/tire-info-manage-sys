use crate::security::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use std::collections::BTreeMap;

fn request(path: &str) -> ApiRequest {
    ApiRequest {
        id: uuid::Uuid::new_v4().to_string(),
        path: path.to_owned(),
        method: "GET".to_owned(),
        headers: BTreeMap::new(),
        body_base64: None,
    }
}

#[test]
fn launch_config_accepts_only_a_port_and_isolated_slug() {
    let default = LaunchConfig::parse(None, None).unwrap();
    assert_eq!(default.base_url(), "http://127.0.0.1:8000");
    for port in [
        "0",
        "80",
        "1023",
        "65536",
        "-1",
        " 8000",
        "8000/evil",
        "8000@evil",
        "http://evil",
        "",
    ] {
        assert!(
            LaunchConfig::parse(Some(port), None).is_err(),
            "accepted {port}"
        );
    }
    for port in ["1024", "65535"] {
        assert!(LaunchConfig::parse(Some(port), None).is_ok());
    }
    for slug in [
        "",
        "../other",
        "a:b",
        "a/b",
        "QA",
        " leading",
        "-leading",
        "trailing-",
        "a_b",
    ] {
        assert!(LaunchConfig::parse(None, Some(slug)).is_err());
    }
    let a = LaunchConfig::parse(Some("8000"), Some("qa-a")).unwrap();
    let b = LaunchConfig::parse(Some("8001"), Some("qa-a")).unwrap();
    let c = LaunchConfig::parse(Some("8000"), Some("qa-b")).unwrap();
    assert_ne!(a.store_account(), b.store_account());
    assert_ne!(a.store_account(), c.store_account());
}

#[test]
fn path_rejects_url_normalization_and_encoded_bypasses() {
    for path in [
        "http://evil/v1/a",
        "//evil/v1/a",
        "/v1//evil",
        "/health/",
        "/v10/a",
        "/admin",
        "/v1/../admin",
        "/v1/./a",
        "/v1/%2e%2E/admin",
        "/v1/%252e%252e/admin",
        "/v1/a%2fb",
        "/v1/a%2Fb",
        "/v1/a%5Cb",
        "/v1/\\evil",
        "/v1/a#fragment",
        "/v1/a%23fragment",
        "/v1/a%3Fquery",
        "/v1/%",
        "/v1/%xy",
        "/v1/a\r\nCookie:x",
        "/v1/a%00",
        "/v1/a?q=%0d%0aCookie:x",
        "/v1/%ff",
    ] {
        assert!(validate_path(path).is_err(), "accepted {path:?}");
    }
    for path in [
        "/health",
        "/v1/sources",
        "/v1/documents/2ef12db3-dc29-47ab-bde4-45764df84847/content?mode=history",
        "/v1/recalls/search-history?search=%E8%83%8E%E8%BF%B9%2F%25&offset=0",
    ] {
        assert!(validate_path(path).is_ok(), "rejected {path}");
    }
    assert!(validate_path(&format!("/v1/{}", "a".repeat(4096))).is_err());
}

#[test]
fn headers_do_not_allow_credentials_authority_or_arbitrary_controls() {
    for name in [
        "Cookie",
        "cookie",
        "Authorization",
        "Origin",
        "Host",
        "Connection",
        "X-Forwarded-For",
        "Sec-Fetch-Site",
        "Accept",
        "Set-Cookie",
    ] {
        let mut input = request("/v1/sources");
        input.headers.insert(name.to_owned(), "secret".to_owned());
        assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"));
    }
    for value in [
        "text/html",
        "application/json; charset=utf-8",
        "application/json\r\nCookie:secret",
    ] {
        let mut input = request("/v1/sources");
        input
            .headers
            .insert("Content-Type".to_owned(), value.to_owned());
        assert!(validate_request(input).is_err());
    }
    let mut duplicate = request("/v1/sources");
    duplicate
        .headers
        .insert("Content-Type".to_owned(), "application/json".to_owned());
    duplicate
        .headers
        .insert("content-type".to_owned(), "application/pdf".to_owned());
    assert!(validate_request(duplicate).is_err());
    let mut input = request("/v1/documents");
    input.headers.insert(
        "Idempotency-Key".to_owned(),
        uuid::Uuid::new_v4().to_string(),
    );
    input.headers.insert(
        "X-Evidence-Metadata".to_owned(),
        STANDARD.encode(br#"{"title":"QA"}"#),
    );
    assert!(validate_request(input).is_ok());
}

#[test]
fn metadata_is_bounded_json_and_request_body_has_real_byte_limit() {
    for value in [
        "garbage".to_owned(),
        STANDARD.encode(b"[]"),
        STANDARD.encode(b"not-json"),
        STANDARD.encode(vec![b'x'; 12 * 1024 + 1]),
    ] {
        let mut input = request("/v1/documents");
        input
            .headers
            .insert("X-Evidence-Metadata".to_owned(), value);
        assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"));
    }
    let payload = vec![0xff; MAX_REQUEST_BYTES];
    let mut input = request("/v1/documents");
    input.method = "POST".to_owned();
    input
        .headers
        .insert("Content-Type".to_owned(), "application/pdf".to_owned());
    input.body_base64 = Some(STANDARD.encode(&payload));
    assert_eq!(validate_request(input).unwrap().body, payload);
    assert_eq!(
        decode_bounded(
            &STANDARD.encode(vec![1; MAX_REQUEST_BYTES + 1]),
            MAX_REQUEST_BYTES,
            "REQUEST_TOO_LARGE"
        )
        .unwrap_err(),
        "REQUEST_TOO_LARGE"
    );
    assert_eq!(
        decode_bounded("broken=", 20, "TOO_BIG").unwrap_err(),
        "INVALID_BASE64"
    );
    let mut get_body = request("/v1/sources");
    get_body.body_base64 = Some(String::new());
    assert!(validate_request(get_body).is_err());
    let mut method = request("/health");
    method.method = "CONNECT".to_owned();
    assert!(validate_request(method).is_err());
}

#[test]
fn native_download_and_external_link_validation() {
    for filename in [
        "../a.pdf",
        "a/b.pdf",
        "a\\b.pdf",
        "C:a.pdf",
        "a.pdf:stream",
        "a.exe",
        ".hidden.pdf",
        "CON.pdf",
        "LPT1.pdf",
        "a.pdf ",
        "a.pdf\n",
    ] {
        assert!(
            download_extension(filename, "application/pdf").is_err(),
            "accepted {filename}"
        );
    }
    assert_eq!(
        download_extension("胎迹报告.pdf", "application/pdf").unwrap(),
        "pdf"
    );
    assert_eq!(
        download_extension("报告.md", "text/markdown;charset=utf-8").unwrap(),
        "md"
    );
    assert_eq!(
        download_extension("报告.html", "text/html").unwrap(),
        "html"
    );
    assert!(download_extension("a.pdf", "text/html").is_err());
    assert!(decode_bounded(
        &STANDARD.encode(vec![0; MAX_RESPONSE_BYTES + 1]),
        MAX_RESPONSE_BYTES,
        "DOWNLOAD_TOO_LARGE"
    )
    .is_err());
    for url in [
        "javascript:alert(1)",
        "file:///C:/a.pdf",
        "data:text/html,x",
        "shell:calc.exe",
        "https://user:pass@example.org",
        "https://user@example.org",
        "https://example.org\\@evil.org",
        "https://example.org\n",
        "//example.org",
    ] {
        assert!(external_url(url).is_err(), "accepted {url}");
    }
    assert!(external_url("https://example.org/evidence?q=abc#source").is_ok());
}

#[test]
fn privileged_webview_navigation_remains_local() {
    for url in [
        "https://evil.example",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://tauri.localhost:8000",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://evil@tauri.localhost",
    ] {
        assert!(!allowed_navigation(&url::Url::parse(url).unwrap(), true));
    }
    assert!(allowed_navigation(
        &url::Url::parse("tauri://localhost/index.html").unwrap(),
        false
    ));
    assert!(allowed_navigation(
        &url::Url::parse("http://tauri.localhost/").unwrap(),
        false
    ));
    let development = url::Url::parse("http://127.0.0.1:1420/").unwrap();
    assert!(allowed_navigation(&development, true));
    assert!(!allowed_navigation(&development, false));
}

#[test]
fn ipc_shapes_reject_extra_authority_and_status_never_serializes_a_cookie() {
    let id = uuid::Uuid::new_v4().to_string();
    let input =
        serde_json::json!({"id":id,"path":"/health","method":"GET","headers":{},"host":"evil"});
    assert!(serde_json::from_value::<ApiRequest>(input).is_err());
    let status = crate::DesktopStatus {
        api_base_url: "http://127.0.0.1:8000".to_owned(),
        session_persistent: true,
        session_store: "os_secure_store",
        version: "0.1.0",
        error: None,
    };
    let json = serde_json::to_value(status).unwrap();
    assert_eq!(json.as_object().unwrap().len(), 4);
    assert!(json.get("cookie").is_none());
}
