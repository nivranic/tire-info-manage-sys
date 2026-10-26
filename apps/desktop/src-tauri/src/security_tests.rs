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
fn inventory_hint_is_limited_to_canonical_get_routes_and_ascii_account_ids() {
    for path in ["/v1/api-keys/active", "/v1/api-key-history?mode=history&limit=20&cursor=opaque_-0"] {
        for account in ["a".to_owned(), "Account_01-safe".to_owned(), "_".to_owned(), "-".to_owned(), "a".repeat(64)] {
            let mut input = request(path);
            input.headers.insert("X-Tire-Expected-Account".to_owned(), account.clone());
            let validated = validate_request(input).unwrap();
            assert_eq!(validated.headers["x-tire-expected-account"], account.as_str());
            assert_eq!(validated.path, path);
        }
    }
    for account in ["", "a b", " leading", "trailing ", "a\t", "a\n", "a\r", "a.b", "a/b", "a,b", "a%20", "é", "账户", "😀"] {
        let mut input = request("/v1/api-keys/active?mode=history");
        input.headers.insert("x-tire-expected-account".to_owned(), account.to_owned());
        assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"), "accepted {account:?}");
    }
    let mut overlong = request("/v1/api-key-history?mode=history");
    overlong.headers.insert("x-tire-expected-account".to_owned(), "a".repeat(65));
    assert_eq!(validate_request(overlong).err(), Some("INVALID_API_HEADER"));
}

#[test]
fn inventory_hint_does_not_expand_other_routes_methods_or_credential_headers() {
    for path in ["/health", "/v1/api-keys", "/v1/api-keys/active/", "/v1/api-key-history/older", "/v1/api-key-history-extra", "/v1/api-keys/%61ctive", "/v1/%61pi-key-history", "/v1/api-keys?next=/v1/api-keys/active"] {
        let mut input = request(path);
        input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
        assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"), "accepted {path}");
    }
    for method in ["POST", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS"] {
        let mut input = request("/v1/api-key-history?mode=history");
        input.method = method.to_owned();
        input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
        assert!(validate_request(input).is_err(), "accepted {method}");
    }
    for name in ["Authorization", "Cookie", "Origin", "Host", "X-Unapproved", "X-Tire-Expected-Account"] {
        let mut input = request("/v1/api-keys/active?mode=history");
        input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
        input.headers.insert(name.to_owned(), "account".to_owned());
        assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"), "accepted {name}");
    }
}

#[test]
fn inventory_hint_preserves_header_budget_and_get_body_rejection() {
    let mut input = request("/v1/api-keys/active?mode=history");
    input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
    input.headers.insert("content-type".to_owned(), "application/json".to_owned());
    input.headers.insert("idempotency-key".to_owned(), uuid::Uuid::new_v4().to_string());
    let mut accepted = request(&input.path);
    accepted.headers = input.headers.clone();
    assert!(validate_request(accepted).is_ok());
    let mut with_body = request(&input.path);
    with_body.headers = input.headers.clone();
    with_body.body_base64 = Some(STANDARD.encode(b"{}"));
    assert_eq!(validate_request(with_body).err(), Some("INVALID_API_BODY"));
    input.headers.insert("x-evidence-metadata".to_owned(), STANDARD.encode(b"{}"));
    assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"));
}

#[test]
fn quarantine_review_hint_accepts_exact_post_and_preserves_json_bytes() {
    let body = r#"{"action":"approve","expected_revision":0,"operator":"复核员","reason":"证据已核对","confirmed_loss":true,"expected_binding_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#;
    for id in ["q".to_owned(), "Quarantine_01-safe".to_owned(), "_".to_owned(), "-".to_owned(), "q".repeat(64)] {
        let path = format!("/v1/quarantines/{id}/reviews?mode=history&format=raw-evidence-v2");
        for account in ["a".to_owned(), "Account_01-safe".to_owned(), "_".to_owned(), "-".to_owned(), "a".repeat(64)] {
            let mut input = request(&path);
            input.method = "POST".to_owned();
            input.headers.insert("X-Tire-Expected-Account".to_owned(), account.clone());
            input.headers.insert("Content-Type".to_owned(), "application/json".to_owned());
            input.headers.insert("Idempotency-Key".to_owned(), "123e4567-e89b-42d3-a456-426614174000".to_owned());
            input.body_base64 = Some(STANDARD.encode(body.as_bytes()));
            let validated = validate_request(input).unwrap();
            assert_eq!(validated.method, reqwest::Method::POST);
            assert_eq!(validated.path, path);
            assert_eq!(validated.headers.len(), 3);
            assert_eq!(validated.headers["x-tire-expected-account"], account.as_str());
            assert_eq!(validated.headers["content-type"], "application/json");
            assert_eq!(validated.headers["idempotency-key"], "123e4567-e89b-42d3-a456-426614174000");
            assert_eq!(validated.body, body.as_bytes());
        }
    }
}

#[test]
fn quarantine_review_hint_rejects_raw_path_and_query_aliases() {
    let overlong = format!("/v1/quarantines/{}/reviews?mode=history&format=raw-evidence-v2", "q".repeat(65));
    for path in [
        "/v1/quarantines/q/reviews",
        "/v1/quarantines/q/review?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/q/reviews/?mode=history&format=raw-evidence-v2",
        "/v1/quarantines//reviews?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/q.extra/reviews?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/账户/reviews?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/q/other/reviews?mode=history&format=raw-evidence-v2",
        "/v1/%71uarantines/q/reviews?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/%71/reviews?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/q/%72eviews?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/q%2Fother/reviews?mode=history&format=raw-evidence-v2",
        "/v1/quarantines/q/reviews?format=raw-evidence-v2&mode=history",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&extra=1",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&mode=history",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&format=raw-evidence-v2",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2&",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2?",
        "/v1/quarantines/q/reviews?mode=%68istory&format=raw-evidence-v2",
        "/v1/quarantines/q/reviews?%6dode=history&format=raw-evidence-v2",
        "/v1/quarantines/q/reviews?mode=history&format=raw%2Devidence-v2",
        "/v1/quarantines/q/reviews?mode=history%26format%3Draw-evidence-v2",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2\n",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2#fragment",
        "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v1",
        overlong.as_str(),
    ] {
        let mut input = request(path);
        input.method = "POST".to_owned();
        input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
        assert!(validate_request(input).is_err(), "accepted {path:?}");
    }
    for method in ["GET", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS", "post"] {
        let mut input = request("/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2");
        input.method = method.to_owned();
        input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
        assert!(validate_request(input).is_err(), "accepted {method}");
    }
}

#[test]
fn quarantine_review_hint_rejects_bad_ids_duplicates_credentials_and_fourth_header() {
    let path = "/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2";
    for account in ["".to_owned(), "a".repeat(65), "a b".to_owned(), " leading".to_owned(), "trailing ".to_owned(), "a\t".to_owned(), "a\n".to_owned(), "a\r".to_owned(), "a.b".to_owned(), "a/b".to_owned(), "a,b".to_owned(), "a%20".to_owned(), "é".to_owned(), "账户".to_owned(), "😀".to_owned()] {
        let mut input = request(path);
        input.method = "POST".to_owned();
        input.headers.insert("x-tire-expected-account".to_owned(), account.clone());
        assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"), "accepted {account:?}");
    }
    for name in ["X-Tire-Expected-Account", "Authorization", "Cookie", "Origin", "Host", "X-Unapproved"] {
        let mut input = request(path);
        input.method = "POST".to_owned();
        input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
        input.headers.insert(name.to_owned(), "account".to_owned());
        assert_eq!(validate_request(input).err(), Some("INVALID_API_HEADER"), "accepted {name}");
    }
    let mut fourth = request(path);
    fourth.method = "POST".to_owned();
    fourth.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
    fourth.headers.insert("content-type".to_owned(), "application/json".to_owned());
    fourth.headers.insert("idempotency-key".to_owned(), "123e4567-e89b-42d3-a456-426614174000".to_owned());
    fourth.headers.insert("x-evidence-metadata".to_owned(), STANDARD.encode(b"{}"));
    assert_eq!(validate_request(fourth).err(), Some("INVALID_API_HEADER"));
}

#[test]
fn quarantine_review_hint_preserves_missing_header_and_existing_body_rules() {
    for path in ["/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2", "/v1/quarantines/q/reviews", "/v1/quarantines/q/reviews?mode=history"] {
        let mut input = request(path);
        input.method = "POST".to_owned();
        input.headers.insert("content-type".to_owned(), "application/json".to_owned());
        input.body_base64 = Some(STANDARD.encode(b"{}"));
        let validated = validate_request(input).unwrap();
        assert!(!validated.headers.contains_key("x-tire-expected-account"));
        assert_eq!(validated.body, b"{}");
    }
    let mut input = request("/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2");
    input.method = "POST".to_owned();
    input.headers.insert("x-tire-expected-account".to_owned(), "account".to_owned());
    input.body_base64 = Some(STANDARD.encode(b"{}"));
    assert_eq!(validate_request(input).err(), Some("INVALID_API_BODY"));
    let mut input = request("/v1/quarantines/q/reviews?mode=history&format=raw-evidence-v2");
    input.headers.insert("content-type".to_owned(), "application/json".to_owned());
    input.body_base64 = Some(STANDARD.encode(b"{}"));
    assert_eq!(validate_request(input).err(), Some("INVALID_API_BODY"));
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
