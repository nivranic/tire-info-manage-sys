//! Frozen discovery pages remain candidates, including an exact empty-page observation.
use super::*;

const NOTICES: [&str; 3] = [
    "本页为美国 NHTSA 轮胎产品目录检索候选，未采纳为召回公告版本。",
    "名称和尺寸匹配不确认具体 SKU 或实物适用；须核对 DOT/TIN、生产批次及官方措施。",
    "仅显示当前页；本页没有召回不表示其他页、其他地区或具体轮胎无召回风险。",
];
fn exact(value: &Value, fields: &[&str]) -> bool {
    value.as_object().is_some_and(|value| {
        value.len() == fields.len() && fields.iter().all(|field| value.contains_key(*field))
    })
}
fn bounded(value: &Value, maximum: usize, nullable: bool) -> bool {
    (nullable && value.is_null())
        || value
            .as_str()
            .is_some_and(|value| value.chars().count() <= maximum && !value.contains('\0'))
}
fn positive(value: &Value) -> bool {
    value.as_u64().is_some_and(|value| value > 0)
}
fn campaign(value: &Value) -> bool {
    value.as_str().is_some_and(|value| {
        value.len() == 9
            && value.as_bytes()[2] == b'T'
            && value
                .bytes()
                .enumerate()
                .all(|(index, byte)| index == 2 || byte.is_ascii_digit())
    })
}
fn document(value: &Value) -> bool {
    if !exact(value, &["url", "title"]) || !bounded(&value["title"], 60_000, true) {
        return false;
    }
    let Some(raw) = value["url"].as_str().filter(|value| value.len() <= 8192) else {
        return false;
    };
    let Some(path) = raw.strip_prefix("https://static.nhtsa.gov/odi/rcl/") else {
        return false;
    };
    let Some((year, file)) = path.split_once('/') else {
        return false;
    };
    let Some(stem) = file
        .strip_suffix(".pdf")
        .or_else(|| file.strip_suffix(".PDF"))
    else {
        return false;
    };
    year.len() == 4
        && year.bytes().all(|byte| byte.is_ascii_digit())
        && !stem.is_empty()
        && stem
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
}
fn campaign_record(value: &Value) -> bool {
    if !exact(
        value,
        &[
            "campaign_number",
            "subject",
            "report_received_at",
            "summary",
            "consequence",
            "remedy",
            "manufacturer",
            "notes",
            "documents",
            "associated_products",
        ],
    ) || !campaign(&value["campaign_number"])
        || !["summary", "consequence", "remedy", "manufacturer"]
            .iter()
            .all(|key| bounded(&value[*key], 60_000, false))
        || !["subject", "notes"]
            .iter()
            .all(|key| bounded(&value[*key], 60_000, true))
        || !value["report_received_at"]
            .as_str()
            .is_some_and(|value| value.ends_with('Z') && timestamp(value))
    {
        return false;
    }
    value["documents"]
        .as_array()
        .is_some_and(|items| items.len() <= 1000 && items.iter().all(document))
        && value["associated_products"]
            .as_array()
            .is_some_and(|items| items.len() <= 1000 && items.iter().all(Value::is_object))
}
fn product(value: &Value) -> bool {
    if !exact(
        value,
        &[
            "id",
            "artemis_id",
            "brand",
            "tireline",
            "size",
            "recalls_count",
            "campaigns",
            "applicability",
        ],
    ) || !positive(&value["id"])
        || !positive(&value["artemis_id"])
        || !["brand", "tireline"].iter().all(|key| {
            bounded(&value[*key], 60_000, false)
                && value[*key]
                    .as_str()
                    .is_some_and(|value| !value.trim().is_empty())
        })
        || !bounded(&value["size"], 60_000, true)
        || value["applicability"] != "not_assessed"
    {
        return false;
    }
    let Some(campaigns) = value["campaigns"]
        .as_array()
        .filter(|items| items.len() <= 1000)
    else {
        return false;
    };
    value["recalls_count"].as_u64() == Some(campaigns.len() as u64)
        && campaigns.iter().all(campaign_record)
        && campaigns
            .iter()
            .map(|campaign| campaign["campaign_number"].as_str())
            .collect::<HashSet<_>>()
            .len()
            == campaigns.len()
}
pub(super) fn validate(member: &Member) -> NativeResult<()> {
    let Reference::RecallSearch {
        snapshot_id,
        verification_id,
    } = &member.reference
    else {
        return Err("OFFLINE_PACK_INVALID");
    };
    let payload = &member.payload;
    let query = &payload["query"];
    let discovery = &payload["discovery"];
    let evidence = &payload["evidence"];
    let boundary = &payload["boundary"];
    if !exact(query, &["search", "offset"])
        || !exact(discovery, &["products", "pagination"])
        || !exact(
            evidence,
            &[
                "snapshot_id",
                "query_id",
                "verification_id",
                "data_state",
                "observed_at",
                "verified_at",
            ],
        )
        || !exact(
            boundary,
            &[
                "kind",
                "formal_campaign_revision",
                "applicability",
                "complete_query_result",
            ],
        )
        || payload["discovery_hash"]
            .as_str()
            .is_none_or(|hash| !hex(hash))
        || evidence["snapshot_id"].as_str() != Some(snapshot_id)
        || evidence["verification_id"].as_str() != Some(verification_id)
        || evidence["query_id"].as_str().is_none_or(|id| !uuid(id))
        || evidence["data_state"] != "local_snapshot"
        || evidence["observed_at"].as_str() != Some(member.source.observed_at.as_str())
        || evidence["verified_at"].as_str() != member.source.verified_at.as_deref()
        || member.source.verified_at.is_none()
        || member.source.source_id.as_deref() != Some("nhtsa-us-recalls")
        || member
            .source
            .raw_hash
            .as_deref()
            .is_none_or(|hash| !hex(hash))
        || boundary["kind"] != "recall_search_candidate_page"
        || boundary["formal_campaign_revision"] != false
        || boundary["applicability"] != "not_assessed"
        || boundary["complete_query_result"] != false
        || payload["notices"].as_array().is_none_or(|items| {
            items.len() != 3
                || items
                    .iter()
                    .zip(NOTICES)
                    .any(|(actual, expected)| actual.as_str() != Some(expected))
        })
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    let search = query["search"].as_str().ok_or("OFFLINE_PACK_INVALID")?;
    let offset_text = query["offset"].as_str().ok_or("OFFLINE_PACK_INVALID")?;
    let offset: u32 = offset_text.parse().map_err(|_| "OFFLINE_PACK_INVALID")?;
    let criteria = super::super::criteria::Criteria::new(
        "nhtsa-us-recalls",
        super::super::criteria::Query::RecallSearch {
            search: search.into(),
            offset,
        },
    )?;
    if offset_text != offset.to_string()
        || criteria.matches_frozen_search_page_json(
            Some("nhtsa-us-recalls"),
            &query.to_string(),
            &discovery.to_string(),
        )? != super::super::criteria::Truth::True
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    let products = discovery["products"]
        .as_array()
        .ok_or("OFFLINE_PACK_INVALID")?;
    let page = &discovery["pagination"];
    if products.len() > 10
        || !products.iter().all(product)
        || products
            .iter()
            .map(|product| product["id"].as_u64())
            .collect::<HashSet<_>>()
            .len()
            != products.len()
        || !exact(
            page,
            &[
                "offset",
                "max",
                "count",
                "total",
                "has_next",
                "has_previous",
            ],
        )
        || page["max"].as_u64() != Some(10)
        || page["count"].as_u64() != Some(products.len() as u64)
        || page["offset"].as_u64() != Some(u64::from(offset))
        || payload["empty_observation"].as_bool() != Some(products.is_empty())
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    let total = page["total"]
        .as_u64()
        .filter(|total| *total <= 10_000_000)
        .ok_or("OFFLINE_PACK_INVALID")?;
    if products.len() as u64 != total.saturating_sub(u64::from(offset)).min(10)
        || page["has_next"].as_bool() != Some(u64::from(offset) + (products.len() as u64) < total)
        || page["has_previous"].as_bool() != Some(offset > 0)
    {
        return Err("OFFLINE_PACK_INVALID");
    }
    // discovery_hash is an opaque producer receipt bound by the approved original
    // package SHA. Never validate it by re-encoding Python numeric/source material.
    Ok(())
}
