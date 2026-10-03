fn main() {
    use sha2::{Digest, Sha256};
    fn sources(path: &std::path::Path, files: &mut Vec<std::path::PathBuf>) {
        for entry in std::fs::read_dir(path).expect("host source directory unavailable") {
            let path = entry.expect("host source entry unavailable").path();
            if path.is_dir() {
                sources(&path, files);
            } else {
                files.push(path);
            }
        }
    }
    let mut files = vec![
        "Cargo.toml".into(),
        "Cargo.lock".into(),
        "build.rs".into(),
        "tauri.conf.json".into(),
        "../../../packages/domain-types/src/query-filter-unicode.json".into(),
    ];
    sources(std::path::Path::new("src"), &mut files);
    sources(std::path::Path::new("capabilities"), &mut files);
    files.sort();
    let mut hash = Sha256::new();
    hash.update(b"offline-host-build@1\0");
    for path in files {
        println!("cargo:rerun-if-changed={}", path.display());
        let name = path.to_string_lossy().replace('\\', "/");
        let bytes = std::fs::read(&path).expect("host source unavailable");
        hash.update((name.len() as u64).to_be_bytes());
        hash.update(name.as_bytes());
        hash.update((bytes.len() as u64).to_be_bytes());
        hash.update(bytes);
    }
    println!("cargo:rustc-env=OFFLINE_HOST_BUILD={:x}", hash.finalize());
    // Application commands are not ACL-gated unless they are in AppManifest.
    // Only the local main WebView receives their generated allow permissions.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "desktop_status",
            "api_request",
            "api_cancel",
            "reset_session",
            "save_download",
            "open_external",
            "offline_status",
            "offline_list",
            "offline_install",
            "offline_search",
            "offline_read",
            "offline_remove",
            "offline_unlock_previous_owner",
            "offline_fallback_decide",
            "offline_fallback_consume",
            "offline_fallback_revoke",
            "offline_fallback_status",
            "offline_fallback_authority_refresh",
            "offline_fallback_policy_preview",
            "offline_fallback_policy_apply",
            "offline_fallback_policy_pause",
            "offline_fallback_policy_revoke",
            "offline_fallback_authorize",
            "offline_sync_status",
            "offline_sync_preview",
            "offline_sync_apply",
            "offline_sync_pause",
            "offline_sync_revoke",
            "offline_sync_run",
            "offline_sync_revalidate",
            "device_ai_prepare",
            "device_ai_submit_stream",
            "device_ai_lookup_attempt",
            "device_ai_read_journal",
            "device_ai_journal_append",
            "device_ai_resolve_unknown",
        ]),
    ))
    .expect("desktop build configuration is invalid");
}
