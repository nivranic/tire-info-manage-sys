use super::*;

fn fixture(name: &str) -> Vec<u8> {
    std::fs::read(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("src/offline/test-fixtures/query-fallback49")
            .join(name),
    )
    .unwrap()
}
fn load(name: &str) -> (Vec<u8>, Descriptor) {
    let bytes = fixture(&format!("{name}-pack.json"));
    let descriptor: Descriptor =
        serde_json::from_slice(&fixture(&format!("{name}-descriptor.json"))).unwrap();
    (bytes, descriptor)
}
#[test]
fn actual_producer_v2_nonempty_and_empty_pages_validate_original_bytes() {
    for name in ["nonempty", "empty"] {
        let (bytes, descriptor) = load(name);
        let pack = package(&bytes, &descriptor).unwrap();
        assert_eq!(pack.schema, "offline-pack@2");
        assert!(pack
            .members
            .iter()
            .any(|m| m.reference.kind() == "recall_search"));
    }
}
#[test]
fn actual_legacy_producer_preserves_explicit_schema_and_rejects_downgrade() {
    let (bytes, descriptor) = load("legacy");
    assert_eq!(
        package(&bytes, &descriptor).unwrap().schema,
        "offline-pack@1"
    );
    let (bytes, mut descriptor) = load("nonempty");
    descriptor.schema = "offline-pack-descriptor@1".into();
    assert!(package(&bytes, &descriptor).is_err());
}
