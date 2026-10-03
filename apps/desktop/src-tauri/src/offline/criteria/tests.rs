use super::*;
use serde_json::{json, Value};

fn conditions(value: Value) -> Vec<Condition> {
    conditions_json(&value.to_string()).unwrap()
}
fn evaluate(row: &Value, filters: Value) -> Truth {
    evaluate_variant_json(&row.to_string(), &conditions(filters)).unwrap()
}
fn sample(field: &str) -> Value {
    match field {
        "size" => json!("265/40ZR20"),
        "load_index" => json!("104/102"),
        "speed_rating" => json!("(Y)"),
        "technology_features" => json!("PNCS"),
        field if matches!(kind(field), Kind::Boolean) => json!(false),
        field if matches!(kind(field), Kind::Number) => json!(650),
        _ => json!("Original Value"),
    }
}
fn row_with(field: &str, value: Value) -> Value {
    let mut row = json!({"facts":{}});
    if field == "variant_id" {
        row["id"] = value;
    } else if identity(field) {
        row[field] = value;
    } else {
        row["facts"][field] = value;
    }
    row
}

#[test]
fn all_28_original_fields_keep_known_unknown_conflict_and_presence_semantics() {
    assert_eq!(TIRE_FIELDS.len(), 28);
    for field in TIRE_FIELDS {
        let expected = sample(field);
        let actual = if field == "technology_features" {
            json!([expected.clone()])
        } else {
            expected.clone()
        };
        let mut row = row_with(field, actual);
        let filter = json!([{"field":field,"op":"eq","value":expected}]);
        assert_eq!(evaluate(&row, filter.clone()), Truth::True, "{field}: eq");
        assert_eq!(
            evaluate(&row, json!([{"field":field,"op":"is_known"}])),
            Truth::True,
            "{field}: known"
        );
        assert_eq!(
            evaluate(&row, json!([{"field":field,"op":"is_unknown"}])),
            Truth::False,
            "{field}: unknown"
        );
        for prefix in ["", "facts.", "identity."] {
            row["facts"]["source_field_conflicts"] = json!([{"field":format!("{prefix}{field}")}]);
            for op in ["is_known", "is_unknown"] {
                assert_eq!(
                    evaluate(&row, json!([{"field":field,"op":op}])),
                    Truth::Unknown,
                    "{field}: conflict {prefix}"
                );
            }
            assert_eq!(evaluate(&row, filter.clone()), Truth::Unknown);
        }
        let unknown = row_with(field, Value::Null);
        assert_eq!(evaluate(&unknown, filter), Truth::Unknown);
        assert_eq!(
            evaluate(&unknown, json!([{"field":field,"op":"is_unknown"}])),
            Truth::True
        );
    }
}

#[test]
fn malformed_facts_or_conflict_container_invalidates_every_field() {
    for facts in [
        Value::Null,
        json!([]),
        json!("wrong"),
        json!({"source_field_conflicts":null}),
        json!({"source_field_conflicts":{}}),
    ] {
        let row = json!({"brand":"Actual", "id":"variant", "facts":facts});
        for field in TIRE_FIELDS {
            for op in ["is_known", "is_unknown"] {
                assert_eq!(
                    evaluate(&row, json!([{"field":field,"op":op}])),
                    Truth::Unknown,
                    "{field}"
                );
            }
        }
    }
    assert_eq!(
        evaluate(
            &json!({"brand":"Actual"}),
            json!([{"field":"brand","op":"eq","value":"actual"}])
        ),
        Truth::True
    );
}

#[test]
fn three_valued_and_has_false_precedence_and_16_input_limit() {
    let row = json!({"brand":"Actual", "facts":{}});
    let unknown = json!({"field":"season","op":"eq","value":"summer"});
    let excluded = json!({"field":"brand","op":"eq","value":"other"});
    for filters in [
        json!([unknown.clone(), excluded.clone()]),
        json!([excluded, unknown]),
    ] {
        assert_eq!(evaluate(&row, filters), Truth::False);
    }
    let known = json!({"field":"brand","op":"eq","value":"Actual"});
    assert_eq!(evaluate(&row, json!(vec![known.clone(); 16])), Truth::True);
    assert!(conditions_json(&json!(vec![known; 17]).to_string()).is_err());
    assert_eq!(evaluate(&row, json!([])), Truth::True);
}

#[test]
fn normalization_uses_shared_python_unicode_full_casefold_and_nfkc() {
    assert_eq!(
        normalize_text("  ＳＴＲＡＳＳＥ\u{00a0}Straße ﬃ ").unwrap(),
        "strasse strasse ffi"
    );
    assert_eq!(normalize_text("Σ σ ς İ ı").unwrap(), "σ σ σ i\u{0307} ı");
    assert_eq!(normalize_text("Ꭰ ꭰ").unwrap(), "Ꭰ Ꭰ");
    for text in [
        "x\u{200d}",
        "\u{e000}",
        "\u{0378}",
        "\u{001c}",
        "x\u{0085}",
        "\u{1e5d0}",
    ] {
        assert!(normalize_text(text).is_err(), "forbidden Python category C");
    }
    assert!(normalize_text(&"a".repeat(513)).is_err());
    assert!(normalize_text(&"ß".repeat(257)).is_err());
    assert!(normalize_text("   ").is_err());
}

#[test]
fn compiled_host_and_unicode_normalizer_identity_are_reported() {
    let table = unicode();
    assert_eq!(table.schema, "tire-query-unicode@1");
    assert_eq!(table.casefold_map.len(), 1530);
    assert_eq!(table.category_c_ranges.len(), 712);
    assert_eq!(table.decimal_digit_map.len(), 680);
    println!(
        "criteria_host_build={} shared_python_unicode_version={} normalizer_unicode_version={:?}",
        super::super::conditions::HOST_BUILD,
        table.unicode_version,
        unicode_normalization::UNICODE_VERSION
    );
}

#[test]
fn metric_sizes_keep_zr_half_rim_and_python_nd_semantics() {
    assert_eq!(normalize_size("265 / 40 zr 20").unwrap(), "265/40ZR20");
    assert_eq!(normalize_size("١٦٥/٤٠R١٥.5").unwrap(), "165/40R١٥.5");
    for size in [
        "99/40R20",
        "456/40R20",
        "265/19R20",
        "265/96R20",
        "265/40R09",
        "265/40R30.5",
        "265/40R20.0",
        "265/40X20",
    ] {
        assert!(normalize_size(size).is_err());
    }
    let row = json!({"size":"265/40ZR20","facts":{}});
    assert_eq!(
        evaluate(
            &row,
            json!([{"field":"size","op":"eq","value":"265/40R20"}])
        ),
        Truth::False
    );
    assert_eq!(
        evaluate(
            &row,
            json!([{"field":"size","op":"eq","value":"２６５／４０ＺＲ２０"}])
        ),
        Truth::True
    );
}

#[test]
fn strict_boolean_numeric_identifiers_and_technical_unknowns_do_not_infer() {
    for value in [json!(0), json!(1), json!("false"), json!({})] {
        assert_eq!(
            evaluate(
                &row_with("run_flat", value),
                json!([{"field":"run_flat","op":"is_unknown"}])
            ),
            Truth::Unknown
        );
    }
    assert_eq!(
        evaluate(
            &row_with("run_flat", json!(false)),
            json!([{"field":"run_flat","op":"eq","value":false}])
        ),
        Truth::True
    );
    for value in [json!("650"), json!(true), json!({"value":650,"unit":"dB"})] {
        assert_eq!(
            evaluate(
                &row_with("utqg_treadwear", value),
                json!([{"field":"utqg_treadwear","op":"is_known"}])
            ),
            Truth::Unknown
        );
    }
    for field in [
        "family",
        "season",
        "oe_mark",
        "utqg_traction",
        "eu_noise_class",
    ] {
        for value in [" unknown ", "UNSPECIFIED"] {
            assert_eq!(
                evaluate(
                    &row_with(field, json!(value)),
                    json!([{"field":field,"op":"is_unknown"}])
                ),
                Truth::True
            );
        }
    }
    for field in [
        "gtin",
        "eprel_id",
        "manufacturer_product_code",
        "brand",
        "model",
        "variant_id",
    ] {
        assert_eq!(
            evaluate(
                &row_with(field, json!("unknown")),
                json!([{"field":field,"op":"is_known"}])
            ),
            Truth::True
        );
    }
    assert_eq!(
        evaluate(
            &row_with("gtin", json!("00123")),
            json!([{"field":"gtin","op":"eq","value":"123"}])
        ),
        Truth::False
    );
    // _read checks Python strip before _text: an all-whitespace control value is unknown.
    assert_eq!(
        evaluate(
            &row_with("season", json!("\u{001c}")),
            json!([{"field":"season","op":"is_unknown"}])
        ),
        Truth::True
    );
}

#[test]
fn technology_features_match_complete_members_without_inference() {
    assert_eq!(
        evaluate(
            &row_with("technology_features", json!(["PNCS", "Foam"])),
            json!([{"field":"technology_features","op":"eq","value":"pncs"}])
        ),
        Truth::True
    );
    assert_eq!(
        evaluate(
            &row_with("technology_features", json!(["PNCS Foam"])),
            json!([{"field":"technology_features","op":"eq","value":"Foam"}])
        ),
        Truth::False
    );
    assert_eq!(
        evaluate(
            &row_with("technology_features", json!([])),
            json!([{"field":"technology_features","op":"is_unknown"}])
        ),
        Truth::True
    );
    for value in [
        json!(["PNCS", null]),
        json!(["PNCS", false]),
        json!([""]),
        json!("PNCS"),
    ] {
        assert_eq!(
            evaluate(
                &row_with("technology_features", value),
                json!([{"field":"technology_features","op":"is_unknown"}])
            ),
            Truth::Unknown
        );
    }
}

#[test]
fn condition_contract_is_closed_and_presence_rejects_even_null_value() {
    for condition in [
        json!({"field":"not_registered","op":"eq","value":"x"}),
        json!({"field":"brand","op":"gte","value":"x"}),
        json!({"field":"brand","op":"is_known","value":null}),
        json!({"field":"brand","op":"eq","value":"x","extra":true}),
        json!({"field":"run_flat","op":"eq","value":0}),
        json!({"field":"utqg_treadwear","op":"eq","value":"650"}),
        json!({"field":"load_index","op":"eq","value":"1"}),
        json!({"field":"speed_rating","op":"eq","value":"I"}),
    ] {
        assert!(Condition::from_json(&condition.to_string()).is_err());
    }
    assert!(
        Condition::from_json(r#"{"field":"brand","field":"family","op":"eq","value":"x"}"#)
            .is_err()
    );
    assert!(evaluate_variant_json(r#"{"brand":"x","brand":"y"}"#, &[]).is_err());
}

#[test]
fn raw_number_tokens_keep_arbitrary_int_float_and_type_boundaries() {
    for (row, filter, expected) in [
        (
            r#"{"facts":{"utqg_treadwear":9007199254740993}}"#,
            r#"[{"field":"utqg_treadwear","op":"eq","value":9007199254740993}]"#,
            Truth::True,
        ),
        (
            r#"{"facts":{"utqg_treadwear":9007199254740993}}"#,
            r#"[{"field":"utqg_treadwear","op":"eq","value":9007199254740992.0}]"#,
            Truth::False,
        ),
        (
            r#"{"facts":{"utqg_treadwear":18446744073709551617}}"#,
            r#"[{"field":"utqg_treadwear","op":"gte","value":18446744073709551616}]"#,
            Truth::True,
        ),
        (
            r#"{"facts":{"utqg_treadwear":650.0}}"#,
            r#"[{"field":"utqg_treadwear","op":"eq","value":650}]"#,
            Truth::True,
        ),
        (
            r#"{"facts":{"utqg_treadwear":1e309}}"#,
            r#"[{"field":"utqg_treadwear","op":"is_unknown"}]"#,
            Truth::Unknown,
        ),
    ] {
        assert_eq!(
            evaluate_variant_json(row, &conditions_json(filter).unwrap()).unwrap(),
            expected
        );
    }
    let huge = "9".repeat(500);
    let row = format!(r#"{{"facts":{{"utqg_treadwear":{huge}}}}}"#);
    let filter = format!(r#"[{{"field":"utqg_treadwear","op":"eq","value":{huge}}}]"#);
    assert_eq!(
        evaluate_variant_json(&row, &conditions_json(&filter).unwrap()).unwrap(),
        Truth::True
    );
}

#[test]
fn typed_tire_selection_uses_original_variant_and_source_only() {
    let criteria = Criteria::new(
        "tire-source",
        Query::Tire(
            TireCriteria::new(
                Some("Michelin PSEV"),
                Some("265/40ZR20"),
                r#"[{"field":"run_flat","op":"eq","value":false}]"#,
            )
            .unwrap(),
        ),
    )
    .unwrap();
    let payload = json!({"variant":{"model":"Pilot Sport EV","size":"265/40ZR20","run_flat":false,"facts":{}},"field_resolution":{"model":"other","run_flat":true},"text":"other FTS"});
    assert_eq!(
        criteria
            .matches_payload_json(MemberKind::Tire, Some("tire-source"), &payload.to_string())
            .unwrap(),
        Truth::True
    );
    assert_eq!(
        criteria
            .matches_payload_json(MemberKind::Tire, Some("other"), &payload.to_string())
            .unwrap(),
        Truth::False
    );
    assert_eq!(
        criteria
            .matches_payload_json(MemberKind::Tire, None, &payload.to_string())
            .unwrap(),
        Truth::Unknown
    );
    let wrong = json!({"variant":{"model":"other","size":"265/40ZR20","run_flat":false,"facts":{}},"field_resolution":{"model":"Pilot Sport EV"}});
    assert_eq!(
        criteria
            .matches_payload_json(MemberKind::Tire, Some("tire-source"), &wrong.to_string())
            .unwrap(),
        Truth::False
    );
}

#[test]
fn vehicle_and_campaign_identity_cannot_be_replaced_by_text_or_facts() {
    let vehicle = Criteria::new(
        "vehicle-source",
        Query::VehicleFitments {
            vehicle_id: "vehicle-original".into(),
        },
    )
    .unwrap();
    let campaign = Criteria::new(
        "recall-source",
        Query::RecallCampaign {
            campaign_number: "23T001000".into(),
        },
    )
    .unwrap();
    assert_eq!(vehicle.matches_payload_json(MemberKind::Vehicle,Some("vehicle-source"),r#"{"vehicle":{"id":"vehicle-original"},"fitments":[],"facts":{"vehicle_id":"other"}}"#).unwrap(),Truth::True);
    assert_eq!(
        vehicle
            .matches_payload_json(
                MemberKind::Vehicle,
                Some("vehicle-source"),
                r#"{"vehicle":{"id":"other"},"text":"vehicle-original"}"#
            )
            .unwrap(),
        Truth::False
    );
    assert_eq!(campaign.matches_payload_json(MemberKind::Recall,Some("recall-source"),r#"{"evidence":{"campaign_number":"23T001000","observation_kind":"empty"},"records":[]}"#).unwrap(),Truth::True);
    assert_eq!(campaign.matches_payload_json(MemberKind::Recall,Some("recall-source"),r#"{"evidence":{"campaign_number":"23T002000"},"facts":[{"campaign_number":"23T001000"}]}"#).unwrap(),Truth::False);
    assert_eq!(
        campaign
            .matches_payload_json(MemberKind::RecallSearch, Some("recall-source"), r#"{}"#)
            .unwrap(),
        Truth::False
    );
    assert_eq!(
        campaign
            .matches_payload_json(MemberKind::TestEvent, Some("recall-source"), r#"{}"#)
            .unwrap(),
        Truth::False
    );
}

#[test]
fn recall_search_matches_exact_canonical_query_and_only_the_frozen_page() {
    let criteria = Criteria::new(
        "recall-source",
        Query::RecallSearch {
            search: "Pilot Sport".into(),
            offset: 10,
        },
    )
    .unwrap();
    let page = r#"{"products":[],"pagination":{"offset":10,"max":10,"count":0,"total":10,"has_next":false,"has_previous":true}}"#;
    assert_eq!(
        criteria
            .matches_frozen_search_page_json(
                Some("recall-source"),
                r#"{"search":"Pilot Sport","offset":"10"}"#,
                page
            )
            .unwrap(),
        Truth::True
    );
    for query in [
        r#"{"search":"pilot sport","offset":"10"}"#,
        r#"{"search":"Pilot Sport","offset":"0"}"#,
        r#"{"search":"Pilot Sport ","offset":"10"}"#,
    ] {
        assert_eq!(
            criteria
                .matches_frozen_search_page_json(Some("recall-source"), query, page)
                .unwrap(),
            Truth::False
        );
    }
    assert_eq!(
        criteria
            .matches_frozen_search_page_json(
                Some("recall-source"),
                r#"{"search":"Pilot Sport","offset":10}"#,
                page
            )
            .unwrap(),
        Truth::Unknown
    );
    let wrong_page = r#"{"pagination":{"offset":0},"products":[]}"#;
    assert_eq!(
        criteria
            .matches_frozen_search_page_json(
                Some("recall-source"),
                r#"{"search":"Pilot Sport","offset":"10"}"#,
                wrong_page
            )
            .unwrap(),
        Truth::False
    );
    assert!(criteria
        .matches_payload_json(
            MemberKind::RecallSearch,
            Some("recall-source"),
            r#"{"evidence":{"campaign_number":"23T001000"}}"#
        )
        .is_err());
}

#[test]
fn original_python_oracle_all_cases_and_condition_statuses_match() {
    verify_python_fixture(
        include_str!("../../../../../../apps/api/tests/data/query-filters49.json"),
        242,
    );
}

#[test]
fn supplementary_python_unicode_filter_and_raw_query_size_boundaries_match() {
    let fixture_json =
        include_str!("../../../../../../apps/api/tests/data/query-filters49-extra.json");
    verify_python_fixture(fixture_json, 14);
    let fixture = object(fixture_json).unwrap();
    for raw in array(member(&fixture, "query_size_cases").unwrap().get()).unwrap() {
        let row = object(raw.get()).unwrap();
        let input = string_at(&row, "input_size").unwrap();
        let invalid: bool = serde_json::from_str(member(&row, "invalid").unwrap().get()).unwrap();
        let actual = TireCriteria::new(None, Some(&input), "[]");
        if invalid {
            assert!(actual.is_err(), "invalid raw query size accepted");
        } else {
            let expected = object(member(&row, "canonical_query").unwrap().get()).unwrap();
            assert_eq!(
                actual.unwrap().size,
                string_at(&expected, "size"),
                "raw query Nd/rim token retained"
            );
        }
    }
}

fn verify_python_fixture(fixture_json: &str, expected_cases: usize) {
    let fixture = object(fixture_json).unwrap();
    assert_eq!(
        string_at(&fixture, "schema").unwrap(),
        "tire-query-filter-reference@1"
    );
    let cases = array(member(&fixture, "cases").unwrap().get()).unwrap();
    assert_eq!(cases.len(), expected_cases);
    let mut checked_rows = 0;
    let mut checked_predicates = 0;
    for case in cases {
        let case = object(case.get()).unwrap();
        let id = string_at(&case, "id").unwrap();
        let input = string_at(&case, "input_filters_json").unwrap();
        if member(&case, "validation_error").unwrap().get() != "null" {
            assert!(
                conditions_json(&input).is_err(),
                "invalid Python input accepted: {id}"
            );
            continue;
        }
        let canonical = string_at(&case, "canonical_filters_json").unwrap();
        let rows_json = string_at(&case, "rows_json").unwrap();
        let expected = object(&string_at(&case, "expected_json").unwrap()).unwrap();
        let actual = select_variants_json(&rows_json, Some(&canonical)).unwrap();
        let selection = object(member(&expected, "selection").unwrap().get()).unwrap();
        for (key, value) in [
            ("source_count", actual.source_count),
            ("matched_count", actual.matched_count),
            ("excluded_count", actual.excluded_count),
            ("undetermined_count", actual.undetermined_count),
        ] {
            let expected: Option<usize> =
                serde_json::from_str(member(&selection, key).unwrap().get()).unwrap();
            assert_eq!(value, expected, "{id}: {key}");
        }
        let indexes: Vec<usize> =
            serde_json::from_str(member(&expected, "matched_row_indexes").unwrap().get()).unwrap();
        assert_eq!(
            actual.matched_row_indexes, indexes,
            "{id}: exact selected rows"
        );
        if rows_json == "null" {
            continue;
        }
        let rows = array(&rows_json).unwrap();
        let conditions = if canonical == "null" {
            Vec::new()
        } else {
            conditions_json(&canonical).unwrap()
        };
        let per_row = array(member(&expected, "per_row").unwrap().get()).unwrap();
        assert_eq!(rows.len(), per_row.len());
        for (raw, expected) in rows.into_iter().zip(per_row) {
            checked_rows += 1;
            let row = Row::parse(raw.get()).unwrap();
            let expected = object(expected.get()).unwrap();
            let results = array(member(&expected, "conditions").unwrap().get()).unwrap();
            assert_eq!(conditions.len(), results.len());
            for (condition, expected) in conditions.iter().zip(results) {
                checked_predicates += 1;
                let expected = object(expected.get()).unwrap();
                let expected_match: Option<bool> =
                    serde_json::from_str(member(&expected, "matched").unwrap().get()).unwrap();
                let truth = expected_match.map_or(Truth::Unknown, Truth::boolean);
                assert_eq!(
                    row.evaluate(condition),
                    truth,
                    "{id}: predicate {}",
                    condition.field
                );
                let status = match row.read(&condition.field) {
                    Read::Known(_) => "known",
                    Read::Unknown => "unknown",
                    Read::Invalid => "invalid",
                    Read::Conflict => "conflict",
                };
                assert_eq!(
                    Some(status),
                    string_at(&expected, "status").as_deref(),
                    "{id}: status {}",
                    condition.field
                );
            }
        }
    }
    println!("shared_python_oracle_cases={expected_cases} checked_rows={checked_rows} checked_predicates={checked_predicates}; original raw numeric tokens retained");
}
#[test]
fn original_basic_query_oracle_retains_raw_expected_size_and_advanced_row_projection() {
    let reference: serde_json::Value = serde_json::from_str(include_str!(
        "../test-fixtures/query-fallback49/basic-query-reference.json"
    ))
    .unwrap();
    let cases = reference["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 9);
    for (index, case) in cases.iter().enumerate() {
        let query = &case["draft_query"];
        let criteria =
            TireCriteria::new(query["model"].as_str(), query["size"].as_str(), "[]").unwrap();
        assert_eq!(
            criteria.canonical_query(),
            case["canonical_query"],
            "case {index}"
        );
        let row = case["row"].to_string();
        assert_eq!(
            criteria.matches_variant(&row).unwrap(),
            case["basic_match"]
                .as_bool()
                .map_or(Truth::Unknown, Truth::boolean),
            "case {index}"
        );
        let advanced = conditions_json(&format!("[{}]", case["advanced_filter"])).unwrap();
        assert_eq!(
            evaluate_variant_json(&row, &advanced).unwrap(),
            case["advanced_match"]
                .as_bool()
                .map_or(Truth::Unknown, Truth::boolean),
            "case {index}"
        );
        let false_model = TireCriteria::new(
            Some("Definitely Different Model"),
            query["size"].as_str(),
            "[]",
        )
        .unwrap();
        assert_eq!(
            false_model.matches_variant(&row).unwrap(),
            Truth::False,
            "case {index}"
        );
    }
}
