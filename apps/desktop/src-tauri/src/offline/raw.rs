//! Bounded exact JSON with deterministic JavaScript numeric mirrors for @2 only.
use crate::security::NativeResult;
use serde::{de::MapAccess, de::Visitor, Deserialize, Deserializer};
use serde_json::{value::RawValue, Value};
use std::{collections::BTreeMap, fmt};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Exact {
    Null,
    Bool(bool),
    Text(String),
    Number(String),
    Array(Vec<Exact>),
    Object(BTreeMap<String, Exact>),
}
#[derive(Default)]
struct Object(BTreeMap<String, Box<RawValue>>);
impl<'de> Deserialize<'de> for Object {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Object;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("unique object")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Object, A::Error> {
                let mut values = BTreeMap::new();
                while let Some((key, value)) = map.next_entry::<String, Box<RawValue>>()? {
                    if values.insert(key, value).is_some() {
                        return Err(serde::de::Error::custom("duplicate field"));
                    }
                }
                Ok(Object(values))
            }
        }
        deserializer.deserialize_map(V)
    }
}
impl Exact {
    pub(crate) fn parse(json: &str) -> NativeResult<Self> {
        if json.is_empty() || json.len() > super::MAX_PACKAGE_BYTES || json.starts_with('\u{feff}')
        {
            return Err("OFFLINE_FALLBACK_INVALID");
        }
        let mut nodes = 0;
        Self::read(json, 0, &mut nodes)
    }
    fn read(json: &str, depth: usize, nodes: &mut usize) -> NativeResult<Self> {
        if depth > 64 || *nodes >= 250_000 {
            return Err("OFFLINE_FALLBACK_CAPACITY");
        }
        *nodes += 1;
        let raw: Box<RawValue> =
            serde_json::from_str(json).map_err(|_| "OFFLINE_FALLBACK_INVALID")?;
        let json = raw.get();
        match json.as_bytes()[0] {
            b'n' => Ok(Self::Null),
            b't' => Ok(Self::Bool(true)),
            b'f' => Ok(Self::Bool(false)),
            b'"' => {
                let text: String =
                    serde_json::from_str(json).map_err(|_| "OFFLINE_FALLBACK_INVALID")?;
                if text.len() > 1024 * 1024 || text.contains('\0') {
                    return Err("OFFLINE_FALLBACK_INVALID");
                }
                Ok(Self::Text(text))
            }
            b'[' => {
                let values: Vec<Box<RawValue>> =
                    serde_json::from_str(json).map_err(|_| "OFFLINE_FALLBACK_INVALID")?;
                if values.len() > 20_000 {
                    return Err("OFFLINE_FALLBACK_CAPACITY");
                }
                Ok(Self::Array(
                    values
                        .iter()
                        .map(|value| Self::read(value.get(), depth + 1, nodes))
                        .collect::<NativeResult<_>>()?,
                ))
            }
            b'{' => {
                let values: Object =
                    serde_json::from_str(json).map_err(|_| "OFFLINE_FALLBACK_INVALID")?;
                if values.0.len() > 4096 {
                    return Err("OFFLINE_FALLBACK_CAPACITY");
                }
                Ok(Self::Object(
                    values
                        .0
                        .iter()
                        .map(|(key, value)| {
                            if key.len() > 4096 || key.contains('\0') {
                                return Err("OFFLINE_FALLBACK_INVALID");
                            }
                            Ok((key.clone(), Self::read(value.get(), depth + 1, nodes)?))
                        })
                        .collect::<NativeResult<_>>()?,
                ))
            }
            _ => {
                // JSON integer tokens stay arbitrary precision. JSON floating tokens
                // must follow finite Python binary64, including underflow to zero.
                if json.contains(['.', 'e', 'E'])
                    && json.parse::<f64>().ok().is_none_or(|v| !v.is_finite())
                {
                    return Err("OFFLINE_FALLBACK_INVALID");
                }
                Ok(Self::Number(json.into()))
            }
        }
    }
    pub(crate) fn get(&self, key: &str) -> Option<&Self> {
        if let Self::Object(values) = self {
            values.get(key)
        } else {
            None
        }
    }
    pub(crate) fn object(&self) -> NativeResult<&BTreeMap<String, Self>> {
        if let Self::Object(values) = self {
            Ok(values)
        } else {
            Err("OFFLINE_FALLBACK_INVALID")
        }
    }
    pub(crate) fn array(&self) -> NativeResult<&[Self]> {
        if let Self::Array(values) = self {
            Ok(values)
        } else {
            Err("OFFLINE_FALLBACK_INVALID")
        }
    }
    pub(crate) fn text(&self) -> NativeResult<&str> {
        if let Self::Text(value) = self {
            Ok(value)
        } else {
            Err("OFFLINE_FALLBACK_INVALID")
        }
    }
    pub(crate) fn json(&self) -> String {
        match self {
            Self::Null => "null".into(),
            Self::Bool(v) => v.to_string(),
            Self::Number(v) => v.clone(),
            Self::Text(v) => serde_json::to_string(v).expect("JSON string"),
            Self::Array(values) => format!(
                "[{}]",
                values.iter().map(Self::json).collect::<Vec<_>>().join(",")
            ),
            Self::Object(values) => format!(
                "{{{}}}",
                values
                    .iter()
                    .map(|(key, value)| format!(
                        "{}:{}",
                        serde_json::to_string(key).expect("JSON key"),
                        value.json()
                    ))
                    .collect::<Vec<_>>()
                    .join(",")
            ),
        }
    }
    pub(crate) fn mirror(&self) -> Value {
        match self {
            Self::Null => Value::Null,
            Self::Bool(v) => Value::Bool(*v),
            Self::Text(v) => Value::String(v.clone()),
            Self::Number(token) => token
                .parse::<f64>()
                .ok()
                .and_then(serde_json::Number::from_f64)
                .map(Value::Number)
                .unwrap_or(Value::Null),
            Self::Array(values) => Value::Array(values.iter().map(Self::mirror).collect()),
            Self::Object(values) => Value::Object(
                values
                    .iter()
                    .map(|(key, value)| (key.clone(), value.mirror()))
                    .collect(),
            ),
        }
    }
    pub(crate) fn package_mirror(&self) -> Value {
        // Integer fields that fit u64/i64 keep their exact Rust type for schema gates;
        // arbitrary package facts use raw fragments rather than this projection.
        match self {
            Self::Number(token) if !token.contains(['.', 'e', 'E']) => token
                .parse::<i64>()
                .map(Value::from)
                .or_else(|_| token.parse::<u64>().map(Value::from))
                .unwrap_or_else(|_| self.mirror()),
            Self::Array(values) => Value::Array(values.iter().map(Self::package_mirror).collect()),
            Self::Object(values) => Value::Object(
                values
                    .iter()
                    .map(|(key, value)| (key.clone(), value.package_mirror()))
                    .collect(),
            ),
            _ => self.mirror(),
        }
    }
}
fn mirror_equal(left: &Value, right: &Value) -> bool {
    match (left, right) {
        (Value::Number(left), Value::Number(right)) => {
            super::criteria::exact_number_equal(&left.to_string(), &right.to_string())
        }
        (Value::Array(left), Value::Array(right)) => {
            left.len() == right.len() && left.iter().zip(right).all(|(a, b)| mirror_equal(a, b))
        }
        (Value::Object(left), Value::Object(right)) => {
            left.len() == right.len()
                && left
                    .iter()
                    .all(|(key, a)| right.get(key).is_some_and(|b| mirror_equal(a, b)))
        }
        _ => left == right,
    }
}
pub(crate) fn decode_transport(mut outer: Value) -> NativeResult<Exact> {
    let object = outer.as_object_mut().ok_or("OFFLINE_FALLBACK_INVALID")?;
    let raw = object
        .remove("raw_json")
        .and_then(|value| value.as_str().map(str::to_owned))
        .ok_or("OFFLINE_FALLBACK_RAW_REQUIRED")?;
    let core = Exact::parse(&raw)?;
    if core.object()?.contains_key("raw_json") || !mirror_equal(&core.mirror(), &outer) {
        return Err("OFFLINE_FALLBACK_RAW_MISMATCH");
    }
    Ok(core)
}
pub(crate) fn encode_transport(core: &Exact) -> NativeResult<Value> {
    if core.object()?.contains_key("raw_json") {
        return Err("OFFLINE_FALLBACK_INVALID");
    }
    let raw = core.json();
    if raw.len() > super::MAX_PACKAGE_BYTES {
        return Err("OFFLINE_FALLBACK_CAPACITY");
    }
    let mut outer = core.mirror();
    outer
        .as_object_mut()
        .ok_or("OFFLINE_FALLBACK_INVALID")?
        .insert("raw_json".into(), Value::String(raw));
    if serde_json::to_vec(&outer)
        .map_err(|_| "OFFLINE_FALLBACK_INVALID")?
        .len()
        > 32 * 1024 * 1024
    {
        return Err("OFFLINE_FALLBACK_CAPACITY");
    }
    Ok(outer)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn raw_numeric_token_and_deterministic_mirror_round_trip() {
        let raw = format!(
            r#"{{"schema":"test","value":9007199254740993,"huge":{},"tiny":5e-324}}"#,
            "9".repeat(500)
        );
        let exact = Exact::parse(&raw).unwrap();
        let outer = encode_transport(&exact).unwrap();
        assert_eq!(outer["value"].as_f64(), Some(9007199254740992.0));
        assert!(outer["huge"].is_null());
        assert_eq!(decode_transport(outer).unwrap(), exact);
    }
    #[test]
    fn raw_rejects_float_overflow_duplicates_wrong_mirror_and_recursion() {
        assert!(Exact::parse(r#"{"number":1e309}"#).is_err());
        assert!(Exact::parse(r#"{"x":1,"x":2}"#).is_err());
        let exact = Exact::parse(r#"{"value":9007199254740993}"#).unwrap();
        let mut outer = encode_transport(&exact).unwrap();
        outer["value"] = Value::from(9007199254740993u64);
        assert!(decode_transport(outer).is_err());
        let mut outer = encode_transport(&exact).unwrap();
        outer["value"] = Value::from(9007199254740994u64);
        assert!(decode_transport(outer).is_err());
        assert!(
            decode_transport(serde_json::json!({"raw_json":"{\"raw_json\":\"x\"}","x":1})).is_err()
        );
    }
}
