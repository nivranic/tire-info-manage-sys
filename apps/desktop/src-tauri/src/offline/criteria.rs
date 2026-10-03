//! Pure historical selection over original member material. No I/O, FTS or authority.
//! RawValue entry points preserve Python integer tokens until the @2 adapter is frozen.
use crate::security::NativeResult;
use serde::{de::MapAccess, de::Visitor, Deserialize, Deserializer};
use serde_json::value::RawValue;
use std::{cmp::Ordering, collections::BTreeMap, fmt, sync::OnceLock};
use unicode_normalization::UnicodeNormalization;

mod numeric;
use numeric::Numeric;

const INVALID: &str = "OFFLINE_FALLBACK_CRITERIA_INVALID";
pub(crate) const MAX_CONDITIONS: usize = 16;
pub(crate) fn exact_number_equal(left: &str, right: &str) -> bool {
    match (Numeric::parse(left), Numeric::parse(right)) {
        (Some(left), Some(right)) => left.cmp(&right) == Ordering::Equal,
        _ => false,
    }
}
pub(crate) const TIRE_FIELDS: [&str; 28] = [
    "brand",
    "family",
    "model",
    "variant_id",
    "region",
    "manufacturer_product_code",
    "gtin",
    "eprel_id",
    "size",
    "construction",
    "load_index",
    "speed_rating",
    "oe_mark",
    "acoustic_technology",
    "technology_features",
    "xl",
    "hl",
    "run_flat",
    "acoustic_foam",
    "ev_marketing_mark",
    "season",
    "utqg_treadwear",
    "utqg_traction",
    "utqg_temperature",
    "eu_fuel_class",
    "eu_wet_grip",
    "eu_external_noise_db",
    "eu_noise_class",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Truth {
    True,
    False,
    Unknown,
}
impl Truth {
    pub(crate) fn and(self, other: Self) -> Self {
        match (self, other) {
            (Self::False, _) | (_, Self::False) => Self::False,
            (Self::Unknown, _) | (_, Self::Unknown) => Self::Unknown,
            _ => Self::True,
        }
    }
    fn boolean(value: bool) -> Self {
        if value {
            Self::True
        } else {
            Self::False
        }
    }
}

#[derive(Deserialize)]
struct UnicodeTables {
    schema: String,
    unicode_version: String,
    casefold_map: BTreeMap<String, String>,
    category_c_ranges: Vec<[u32; 2]>,
    whitespace_codepoints: Vec<u32>,
    decimal_digit_map: BTreeMap<String, u8>,
}
fn unicode() -> &'static UnicodeTables {
    static TABLE: OnceLock<UnicodeTables> = OnceLock::new();
    TABLE.get_or_init(|| {
        let table: UnicodeTables = serde_json::from_str(include_str!(
            "../../../../../packages/domain-types/src/query-filter-unicode.json"
        ))
        .expect("checked shared Unicode table");
        assert_eq!(table.schema, "tire-query-unicode@1");
        assert!(!table.unicode_version.is_empty());
        table
    })
}
fn whitespace(character: char) -> bool {
    unicode()
        .whitespace_codepoints
        .contains(&(character as u32))
}
fn category_c(character: char) -> bool {
    let cp = character as u32;
    unicode()
        .category_c_ranges
        .iter()
        .any(|[start, end]| *start <= cp && cp <= *end)
}
fn collapsed(value: &str) -> String {
    value
        .split(whitespace)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
pub(crate) fn normalize_text(value: &str) -> NativeResult<String> {
    if value.chars().count() > 512 || value.chars().any(category_c) {
        return Err(INVALID);
    }
    let normalized: String = value.nfkc().collect();
    let mut folded = String::new();
    for character in collapsed(&normalized).chars() {
        if let Some(mapped) = unicode().casefold_map.get(&(character as u32).to_string()) {
            folded.push_str(mapped);
        } else {
            folded.push(character);
        }
    }
    if folded.is_empty() || folded.chars().count() > 512 {
        return Err(INVALID);
    }
    Ok(folded)
}
fn digit(character: char) -> Option<u8> {
    unicode()
        .decimal_digit_map
        .get(&(character as u32).to_string())
        .copied()
}
fn parse_decimal(characters: &[char]) -> Option<u32> {
    characters.iter().try_fold(0u32, |value, character| {
        value
            .checked_mul(10)?
            .checked_add(u32::from(digit(*character)?))
    })
}
pub(crate) fn normalize_size(value: &str) -> NativeResult<String> {
    // Python parse_size uses Unicode \d, while load_index deliberately uses [0-9].
    let chars: Vec<char> = value
        .chars()
        .filter(|c| !whitespace(*c))
        .flat_map(char::to_uppercase)
        .collect();
    if chars.len() < 9 || chars.get(3) != Some(&'/') {
        return Err(INVALID);
    }
    let width = parse_decimal(&chars[..3]).ok_or(INVALID)?;
    let aspect = parse_decimal(&chars[4..6]).ok_or(INVALID)?;
    let (construction, rim_start) = match chars.get(6..) {
        Some(['R', ..]) => ("R", 7),
        Some(['Z', 'R', ..]) => ("ZR", 8),
        _ => return Err(INVALID),
    };
    let rim = &chars[rim_start..];
    if !(rim.len() == 2 || (rim.len() == 4 && rim[2] == '.' && rim[3] == '5')) {
        return Err(INVALID);
    }
    let rim_number = parse_decimal(&rim[..2]).ok_or(INVALID)?;
    let rim_half = rim.len() == 4;
    if !(100..=455).contains(&width)
        || !(20..=95).contains(&aspect)
        || !(10..=30).contains(&rim_number)
        || (rim_number == 30 && rim_half)
    {
        return Err(INVALID);
    }
    Ok(format!(
        "{width}/{aspect}{construction}{}",
        rim.iter().collect::<String>()
    ))
}

#[derive(Default)]
struct Object(BTreeMap<String, Box<RawValue>>);
impl<'de> Deserialize<'de> for Object {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ObjectVisitor;
        impl<'de> Visitor<'de> for ObjectVisitor {
            type Value = Object;
            fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
                formatter.write_str("unique-key object")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Object, A::Error> {
                let mut result = BTreeMap::new();
                while let Some((key, value)) = map.next_entry::<String, Box<RawValue>>()? {
                    if result.insert(key, value).is_some() {
                        return Err(serde::de::Error::custom("duplicate key"));
                    }
                }
                Ok(Object(result))
            }
        }
        deserializer.deserialize_map(ObjectVisitor)
    }
}
fn object(json: &str) -> NativeResult<Object> {
    serde_json::from_str(json).map_err(|_| INVALID)
}
fn array(json: &str) -> NativeResult<Vec<Box<RawValue>>> {
    serde_json::from_str(json).map_err(|_| INVALID)
}
fn text(raw: &RawValue) -> NativeResult<String> {
    serde_json::from_str(raw.get()).map_err(|_| INVALID)
}
fn member<'a>(object: &'a Object, key: &str) -> Option<&'a RawValue> {
    object.0.get(key).map(Box::as_ref)
}
fn string_at(object: &Object, key: &str) -> Option<String> {
    member(object, key).and_then(|raw| text(raw).ok())
}

#[derive(Clone, Copy, Debug)]
enum Kind {
    Text,
    Boolean,
    Number,
}
fn kind(field: &str) -> Kind {
    match field {
        "xl" | "hl" | "run_flat" | "acoustic_foam" | "ev_marketing_mark" => Kind::Boolean,
        "utqg_treadwear" | "eu_external_noise_db" => Kind::Number,
        _ => Kind::Text,
    }
}
fn identity(field: &str) -> bool {
    matches!(
        field,
        "brand"
            | "model"
            | "region"
            | "manufacturer_product_code"
            | "size"
            | "load_index"
            | "speed_rating"
            | "oe_mark"
            | "acoustic_technology"
            | "xl"
            | "hl"
            | "run_flat"
    )
}
fn technical(field: &str) -> bool {
    matches!(
        field,
        "family"
            | "construction"
            | "load_index"
            | "speed_rating"
            | "oe_mark"
            | "acoustic_technology"
            | "season"
            | "utqg_traction"
            | "utqg_temperature"
            | "eu_fuel_class"
            | "eu_wet_grip"
            | "eu_noise_class"
    )
}
#[derive(Clone, Debug)]
enum Scalar {
    Text(String),
    Boolean(bool),
    Number(Numeric),
    TextList(Vec<String>),
}
fn scalar(field: &str, raw: &RawValue) -> NativeResult<Scalar> {
    match kind(field) {
        Kind::Boolean => serde_json::from_str::<bool>(raw.get())
            .map(Scalar::Boolean)
            .map_err(|_| INVALID),
        Kind::Number => Numeric::parse(raw.get()).map(Scalar::Number).ok_or(INVALID),
        Kind::Text => {
            let mut value = normalize_text(&text(raw)?)?;
            match field {
                "size" => value = normalize_size(&value)?,
                "load_index" => {
                    let parts: Vec<_> = value.split('/').collect();
                    if !(1..=2).contains(&parts.len())
                        || parts.iter().any(|part| {
                            !(2..=3).contains(&part.len())
                                || !part.bytes().all(|b| b.is_ascii_digit())
                        })
                    {
                        return Err(INVALID);
                    }
                }
                "speed_rating" => {
                    if !matches!(
                        value.as_str(),
                        "a1" | "a2"
                            | "a3"
                            | "a4"
                            | "a5"
                            | "a6"
                            | "a7"
                            | "a8"
                            | "b"
                            | "c"
                            | "d"
                            | "e"
                            | "f"
                            | "g"
                            | "j"
                            | "k"
                            | "l"
                            | "m"
                            | "n"
                            | "p"
                            | "q"
                            | "r"
                            | "s"
                            | "t"
                            | "u"
                            | "h"
                            | "v"
                            | "w"
                            | "y"
                            | "(y)"
                            | "zr"
                    ) {
                        return Err(INVALID);
                    }
                }
                _ => {}
            }
            Ok(Scalar::Text(value))
        }
    }
}
#[derive(Clone, Copy, Debug)]
enum Operator {
    Eq,
    Gte,
    Lte,
    IsKnown,
    IsUnknown,
}
#[derive(Clone, Debug)]
pub(crate) struct Condition {
    field: String,
    operator: Operator,
    expected: Option<Scalar>,
}
impl Condition {
    pub(crate) fn from_json(json: &str) -> NativeResult<Self> {
        let row = object(json)?;
        if row
            .0
            .keys()
            .any(|key| !matches!(key.as_str(), "field" | "op" | "value"))
        {
            return Err(INVALID);
        }
        let field = string_at(&row, "field").ok_or(INVALID)?;
        if !TIRE_FIELDS.contains(&field.as_str()) {
            return Err(INVALID);
        }
        let operator = match string_at(&row, "op").as_deref() {
            Some("eq") => Operator::Eq,
            Some("gte") if matches!(kind(&field), Kind::Number) => Operator::Gte,
            Some("lte") if matches!(kind(&field), Kind::Number) => Operator::Lte,
            Some("is_known") => Operator::IsKnown,
            Some("is_unknown") => Operator::IsUnknown,
            _ => return Err(INVALID),
        };
        let expected = match operator {
            Operator::IsKnown | Operator::IsUnknown => {
                if member(&row, "value").is_some() {
                    return Err(INVALID);
                }
                None
            }
            _ => Some(scalar(&field, member(&row, "value").ok_or(INVALID)?)?),
        };
        Ok(Self {
            field,
            operator,
            expected,
        })
    }
}
pub(crate) fn conditions_json(json: &str) -> NativeResult<Vec<Condition>> {
    let raw = array(json)?;
    if raw.len() > MAX_CONDITIONS {
        return Err(INVALID);
    }
    raw.iter()
        .map(|raw| Condition::from_json(raw.get()))
        .collect()
}

enum Read {
    Known(Scalar),
    Unknown,
    Invalid,
    Conflict,
}
struct Row {
    row: Object,
    facts: Object,
    conflicts: Vec<Box<RawValue>>,
    valid: bool,
}
impl Row {
    fn parse(json: &str) -> NativeResult<Self> {
        let row = object(json)?;
        let facts = match member(&row, "facts") {
            Some(raw) => object(raw.get()),
            None => Ok(Object::default()),
        };
        let (facts, mut valid) = match facts {
            Ok(facts) => (facts, true),
            Err(_) => (Object::default(), false),
        };
        let conflicts = match member(&facts, "source_field_conflicts") {
            Some(raw) => match array(raw.get()) {
                Ok(values) => values,
                Err(_) => {
                    valid = false;
                    Vec::new()
                }
            },
            None => Vec::new(),
        };
        Ok(Self {
            row,
            facts,
            conflicts,
            valid,
        })
    }
    fn read(&self, field: &str) -> Read {
        if !self.valid {
            return Read::Invalid;
        }
        if self.conflicts.iter().any(|raw| {
            object(raw.get())
                .ok()
                .and_then(|entry| string_at(&entry, "field"))
                .is_some_and(|name| {
                    name == field
                        || name == format!("facts.{field}")
                        || name == format!("identity.{field}")
                })
        }) {
            return Read::Conflict;
        }
        let raw = if field == "variant_id" {
            member(&self.row, "id")
        } else if identity(field) {
            member(&self.row, field)
        } else {
            member(&self.facts, field)
        };
        let Some(raw) = raw else {
            return Read::Unknown;
        };
        if raw.get() == "null" {
            return Read::Unknown;
        }
        let as_text = text(raw).ok();
        if as_text
            .as_deref()
            .is_some_and(|value| value.trim_matches(whitespace).is_empty())
        {
            return Read::Unknown;
        }
        if technical(field)
            && as_text.as_deref().is_some_and(|value| {
                normalize_text(value).is_ok_and(|v| matches!(v.as_str(), "unknown" | "unspecified"))
            })
        {
            return Read::Unknown;
        }
        if field == "technology_features" {
            let Ok(values) = array(raw.get()) else {
                return Read::Invalid;
            };
            if values.is_empty() {
                return Read::Unknown;
            }
            let values: NativeResult<Vec<String>> = values
                .iter()
                .map(|raw| normalize_text(&text(raw)?))
                .collect();
            return match values {
                Ok(values) => Read::Known(Scalar::TextList(values)),
                Err(_) => Read::Invalid,
            };
        }
        match scalar(field, raw) {
            Ok(value) => Read::Known(value),
            Err(_) => Read::Invalid,
        }
    }
    fn evaluate(&self, condition: &Condition) -> Truth {
        let actual = self.read(&condition.field);
        if matches!(actual, Read::Invalid | Read::Conflict) {
            return Truth::Unknown;
        }
        match condition.operator {
            Operator::IsKnown => return Truth::boolean(matches!(actual, Read::Known(_))),
            Operator::IsUnknown => return Truth::boolean(matches!(actual, Read::Unknown)),
            _ => {}
        }
        let Read::Known(actual) = actual else {
            return Truth::Unknown;
        };
        let Some(expected) = &condition.expected else {
            return Truth::Unknown;
        };
        let matched = match (&actual, expected, condition.operator) {
            (Scalar::Text(a), Scalar::Text(b), Operator::Eq) => a == b,
            (Scalar::Boolean(a), Scalar::Boolean(b), Operator::Eq) => a == b,
            (Scalar::TextList(a), Scalar::Text(b), Operator::Eq) => a.contains(b),
            (Scalar::Number(a), Scalar::Number(b), Operator::Eq) => a.cmp(b) == Ordering::Equal,
            (Scalar::Number(a), Scalar::Number(b), Operator::Gte) => a.cmp(b) != Ordering::Less,
            (Scalar::Number(a), Scalar::Number(b), Operator::Lte) => a.cmp(b) != Ordering::Greater,
            _ => return Truth::Unknown,
        };
        Truth::boolean(matched)
    }
}
pub(crate) fn evaluate_variant_json(json: &str, conditions: &[Condition]) -> NativeResult<Truth> {
    if conditions.len() > MAX_CONDITIONS {
        return Err(INVALID);
    }
    let row = Row::parse(json)?;
    Ok(conditions.iter().fold(Truth::True, |state, condition| {
        state.and(row.evaluate(condition))
    }))
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Selection {
    pub source_count: Option<usize>,
    pub matched_count: Option<usize>,
    pub excluded_count: Option<usize>,
    pub undetermined_count: Option<usize>,
    pub matched_row_indexes: Vec<usize>,
}
pub(crate) fn select_variants_json(
    rows_json: &str,
    filters_json: Option<&str>,
) -> NativeResult<Selection> {
    // Legacy SQL NULL is unfiltered selection; this does not relax intent/condition validation.
    let conditions = match filters_json {
        None | Some("null") => Vec::new(),
        Some(json) => conditions_json(json)?,
    };
    if rows_json == "null" {
        return Ok(Selection {
            source_count: None,
            matched_count: None,
            excluded_count: None,
            undetermined_count: None,
            matched_row_indexes: Vec::new(),
        });
    }
    let rows = array(rows_json)?;
    let mut result = Selection {
        source_count: Some(rows.len()),
        matched_count: Some(0),
        excluded_count: Some(0),
        undetermined_count: Some(0),
        matched_row_indexes: Vec::new(),
    };
    for (index, row) in rows.iter().enumerate() {
        match evaluate_variant_json(row.get(), &conditions)? {
            Truth::True => {
                *result.matched_count.as_mut().unwrap() += 1;
                result.matched_row_indexes.push(index);
            }
            Truth::False => *result.excluded_count.as_mut().unwrap() += 1,
            Truth::Unknown => *result.undetermined_count.as_mut().unwrap() += 1,
        }
    }
    Ok(result)
}

#[derive(Clone, Debug)]
pub(crate) struct TireCriteria {
    model: Option<String>,
    size: Option<String>,
    conditions: Vec<Condition>,
}
impl TireCriteria {
    pub(crate) fn canonical_query(&self) -> serde_json::Value {
        let mut query = serde_json::Map::new();
        if let Some(model) = &self.model {
            query.insert("model".into(), serde_json::Value::String(model.clone()));
        }
        if let Some(size) = &self.size {
            query.insert("size".into(), serde_json::Value::String(size.clone()));
        }
        serde_json::Value::Object(query)
    }
    pub(crate) fn new(
        model: Option<&str>,
        size: Option<&str>,
        filters_json: &str,
    ) -> NativeResult<Self> {
        let model = model.map(|value| value.trim_matches(whitespace));
        if model.is_some_and(|value| value.chars().count() > 120) {
            return Err(INVALID);
        }
        let model = model.map(collapsed).filter(|value| !value.is_empty());
        let model = model.map(|value| {
            let lower = value
                .chars()
                .map(|character| {
                    unicode()
                        .casefold_map
                        .get(&(character as u32).to_string())
                        .cloned()
                        .unwrap_or_else(|| character.to_string())
                })
                .collect::<String>();
            let alias = lower.strip_prefix("michelin ").unwrap_or(&lower);
            match alias {
                "psev" | "pilot sport ev" => "Pilot Sport EV".into(),
                "ps4s" | "pilot sport 4 s" => "Pilot Sport 4 S".into(),
                _ => value,
            }
        });
        let size = size.map(|value| value.trim_matches(whitespace));
        if size.is_some_and(|value| value.chars().count() > 24) {
            return Err(INVALID);
        }
        let size = size
            .filter(|value| !value.is_empty())
            .map(normalize_size)
            .transpose()?;
        if model.is_none() && size.is_none() {
            return Err(INVALID);
        }
        Ok(Self {
            model,
            size,
            conditions: conditions_json(filters_json)?,
        })
    }
    fn matches_variant(&self, raw: &str) -> NativeResult<Truth> {
        let row = Row::parse(raw)?;
        let mut state = Truth::True;
        for (field, expected) in [
            ("model", self.model.as_deref()),
            ("size", self.size.as_deref()),
        ] {
            if let Some(expected) = expected {
                // Identity query predicates also read the original row, never field_resolution.
                let actual = row.read(field);
                let expected = if field == "size" {
                    Ok(expected.to_owned())
                } else {
                    normalize_text(expected)
                };
                state = state.and(match (actual, expected) {
                    (Read::Known(Scalar::Text(actual)), Ok(expected)) => {
                        Truth::boolean(actual == expected)
                    }
                    _ => Truth::Unknown,
                });
            }
        }
        Ok(self
            .conditions
            .iter()
            .fold(state, |state, condition| state.and(row.evaluate(condition))))
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum MemberKind {
    Tire,
    Vehicle,
    Recall,
    RecallSearch,
    TestEvent,
}
#[derive(Clone, Debug)]
pub(crate) enum Query {
    Tire(TireCriteria),
    VehicleFitments { vehicle_id: String },
    RecallCampaign { campaign_number: String },
    RecallSearch { search: String, offset: u32 },
}
#[derive(Clone, Debug)]
pub(crate) struct Criteria {
    source_id: String,
    query: Query,
}
impl Criteria {
    pub(crate) fn new(source_id: &str, query: Query) -> NativeResult<Self> {
        if source_id.is_empty()
            || source_id.len() > 80
            || !source_id
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        {
            return Err(INVALID);
        }
        match &query {
            Query::Tire(_) => {}
            Query::VehicleFitments { vehicle_id } => {
                if vehicle_id.is_empty()
                    || vehicle_id.chars().count() > 100
                    || vehicle_id.chars().any(category_c)
                    || vehicle_id.trim_matches(whitespace) != vehicle_id
                {
                    return Err(INVALID);
                }
            }
            Query::RecallCampaign { campaign_number } => {
                if campaign_number.len() != 9
                    || campaign_number.as_bytes()[2] != b'T'
                    || !campaign_number
                        .bytes()
                        .enumerate()
                        .all(|(index, byte)| index == 2 || byte.is_ascii_digit())
                {
                    return Err(INVALID);
                }
            }
            Query::RecallSearch { search, offset } => {
                if search.is_empty()
                    || search.chars().count() > 120
                    || collapsed(search) != *search
                    || search.chars().any(|c| (c as u32) < 32)
                    || *offset > 10000
                    || offset % 10 != 0
                {
                    return Err(INVALID);
                }
            }
        }
        Ok(Self {
            source_id: source_id.into(),
            query,
        })
    }
    fn source_matches(&self, source_id: Option<&str>) -> Truth {
        match source_id {
            Some(source) => Truth::boolean(source == self.source_id),
            None => Truth::Unknown,
        }
    }
    pub(crate) fn matches_payload_json(
        &self,
        kind: MemberKind,
        source_id: Option<&str>,
        payload_json: &str,
    ) -> NativeResult<Truth> {
        let source = self.source_matches(source_id);
        if source != Truth::True {
            return Ok(source);
        }
        let payload = object(payload_json)?;
        let result = match (&self.query, kind) {
            (Query::Tire(criteria), MemberKind::Tire) => match member(&payload, "variant") {
                Some(raw) => criteria.matches_variant(raw.get())?,
                None => Truth::Unknown,
            },
            (Query::VehicleFitments { vehicle_id }, MemberKind::Vehicle) => {
                exact_nested(&payload, "vehicle", "id", vehicle_id)
            }
            (Query::RecallCampaign { campaign_number }, MemberKind::Recall) => {
                exact_nested(&payload, "evidence", "campaign_number", campaign_number)
            }
            (Query::RecallSearch { .. }, MemberKind::RecallSearch) => {
                // No guessed @2 payload layout: the frozen page adapter must pass both raw pieces.
                return Err("OFFLINE_FALLBACK_SEARCH_PAGE_ADAPTER_REQUIRED");
            }
            _ => Truth::False,
        };
        Ok(result)
    }
    pub(crate) fn matches_frozen_search_page_json(
        &self,
        source_id: Option<&str>,
        query_json: &str,
        discovery_json: &str,
    ) -> NativeResult<Truth> {
        let source = self.source_matches(source_id);
        if source != Truth::True {
            return Ok(source);
        }
        let Query::RecallSearch { search, offset } = &self.query else {
            return Ok(Truth::False);
        };
        let query = object(query_json)?;
        if query.0.len() != 2 {
            return Err(INVALID);
        }
        let Some(page_search) = string_at(&query, "search") else {
            return Ok(Truth::Unknown);
        };
        let Some(page_offset) = string_at(&query, "offset") else {
            return Ok(Truth::Unknown);
        };
        if page_search != *search || page_offset != offset.to_string() {
            return Ok(Truth::False);
        }
        let discovery = object(discovery_json)?;
        let Some(pagination) =
            member(&discovery, "pagination").and_then(|raw| object(raw.get()).ok())
        else {
            return Ok(Truth::Unknown);
        };
        let page_offset = member(&pagination, "offset")
            .and_then(|raw| serde_json::from_str::<u32>(raw.get()).ok());
        Ok(page_offset.map_or(Truth::Unknown, |page| Truth::boolean(page == *offset)))
    }
}
fn exact_nested(payload: &Object, key: &str, field: &str, expected: &str) -> Truth {
    match member(payload, key)
        .and_then(|raw| object(raw.get()).ok())
        .and_then(|nested| string_at(&nested, field))
    {
        Some(actual) => Truth::boolean(actual == expected),
        None => Truth::Unknown,
    }
}

#[cfg(test)]
mod tests;
