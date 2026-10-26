import type { ExternalTireFactRequest, ExternalTireFactResult } from "@tire/domain-types";

export const EXTERNAL_TIRE_FACT_MAX_BYTES = 65_792;
const MAX_DEPTH = 5, MAX_NODES = 272;
type Obj = Record<string, unknown>;
const identityKeys = ["brand", "model", "region", "manufacturer_product_code", "product_code_type", "size",
  "load_index", "speed_rating", "xl", "hl", "run_flat", "oe_mark", "acoustic_technology", "gtin", "technology_features", "eprel_id"];
const factKeys = ["utqg_treadwear", "utqg_traction", "utqg_temperature", "eu_fuel_class", "eu_wet_grip",
  "eu_external_noise_db", "eu_noise_class", "weight_kg", "tread_depth"];
const speeds = new Set(["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "B", "C", "D", "E", "F", "G",
  "J", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "U", "H", "V", "W", "Y", "(Y)", "ZR"]);
const enums: Record<string, string[]> = { utqg_traction: ["AA", "A", "B", "C"], utqg_temperature: ["A", "B", "C"],
  eu_fuel_class: ["A", "B", "C", "D", "E", "F", "G"], eu_wet_grip: ["A", "B", "C", "D", "E", "F", "G"], eu_noise_class: ["A", "B", "C"] };
function ensure(value: unknown): asserts value { if (!value) throw new Error("external_tire_fact_contract_invalid"); }
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
function closed(v: unknown, fields: string[]): asserts v is Obj {
  ensure(object(v) && Object.keys(v).length === fields.length && fields.every(key => Object.hasOwn(v, key)));
}
const full = (pattern: RegExp, value: unknown): value is string => typeof value === "string" && pattern.exec(value)?.[0] === value;
const identifier = (v: unknown, maximum = 64): v is string => full(new RegExp(`^[A-Za-z0-9_-]{1,${maximum}}$`), v);
function unicode(v: string) { return ![...v].some(c => { const cp = c.codePointAt(0)!; return cp >= 0xd800 && cp <= 0xdfff; }); }
function text(v: unknown, maximum: number, empty = false): v is string {
  // Python str.isprintable rejects every C/Z category except U+0020.
  return typeof v === "string" && [...v].length >= (empty ? 0 : 1) && [...v].length <= maximum
    && unicode(v) && ![...v].some(c => c !== " " && /[\p{C}\p{Z}]/u.test(c)) && !v.startsWith(" ") && !v.endsWith(" ");
}
function codePointOrder(a: string, b: string) {
  const aa = [...a], bb = [...b];
  for (let i = 0; i < Math.min(aa.length, bb.length); i++) {
    const difference = aa[i].codePointAt(0)! - bb[i].codePointAt(0)!;
    if (difference) return difference;
  }
  return aa.length - bb.length;
}
/** Check the detached JSON shape before semantics, without invoking getters/toJSON. */
function bounded(input: unknown): unknown {
  let nodes = 0;
  const ancestors = new Set<object>();
  function visit(v: unknown, depth: number): unknown {
    ensure(depth <= MAX_DEPTH && ++nodes <= MAX_NODES);
    if (typeof v === "string") { ensure(v.length <= EXTERNAL_TIRE_FACT_MAX_BYTES && unicode(v)); return v; }
    if (v === null || typeof v === "boolean") return v;
    if (typeof v === "number") { ensure(Number.isFinite(v)); return v; }
    ensure(typeof v === "object" && v !== null);
    const array = Array.isArray(v), prototype = Object.getPrototypeOf(v);
    ensure(array ? prototype === Array.prototype : prototype === Object.prototype || prototype === null);
    ensure(!ancestors.has(v)); ancestors.add(v);
    const descriptors = Object.getOwnPropertyDescriptors(v), keys = Object.keys(v);
    ensure(keys.length <= MAX_NODES && Object.getOwnPropertySymbols(v).length === 0
      && Object.getOwnPropertyNames(v).length === keys.length + (array ? 1 : 0));
    let result: unknown;
    if (array) {
      ensure(keys.length === v.length && keys.every((key, index) => key === String(index)));
      result = keys.map(key => { ensure("value" in descriptors[key]); return visit(descriptors[key].value, depth + 1); });
    } else {
      const copy = Object.create(null) as Obj;
      for (const key of keys) {
        ensure(unicode(key) && "value" in descriptors[key]);
        copy[key] = visit(descriptors[key].value, depth + 1);
      }
      result = copy;
    }
    ancestors.delete(v);
    return result;
  }
  const result = visit(input, 0);
  ensure(new TextEncoder().encode(JSON.stringify(result)).byteLength <= EXTERNAL_TIRE_FACT_MAX_BYTES);
  return result;
}
function identity(input: unknown) {
  closed(input, ["variant_id", "contract_version", "status", "values"]);
  ensure(identifier(input.variant_id) && input.contract_version === "variant-identity@2"
    && (input.status === "complete" || input.status === "source_scoped"));
  const v = input.values; closed(v, identityKeys);
  ensure(text(v.brand, 120) && text(v.model, 200) && text(v.region, 40));
  for (const key of ["manufacturer_product_code", "product_code_type"]) ensure(v[key] === null || text(v[key], 100));
  ensure(typeof v.size === "string");
  const size = /^([0-9]{3})\/([0-9]{2})(?:ZR|R)([0-9]{2}(?:\.5)?)$/.exec(v.size);
  ensure(size && size[0] === v.size && Number(size[1]) >= 100 && Number(size[1]) <= 455 && Number(size[2]) >= 20 && Number(size[2]) <= 95
    && Number(size[3]) >= 10 && Number(size[3]) <= 30);
  ensure(v.load_index === null || full(/^[0-9]{2,3}(?:\/[0-9]{2,3})?$/, v.load_index));
  ensure(v.speed_rating === null || (typeof v.speed_rating === "string" && speeds.has(v.speed_rating)));
  for (const key of ["xl", "hl", "run_flat"]) ensure(v[key] === null || typeof v[key] === "boolean");
  for (const key of ["oe_mark", "acoustic_technology"]) ensure(v[key] === null || text(v[key], 100, true));
  if (v.gtin !== null) {
    ensure(full(/^(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})$/, v.gtin));
    const digits = [...v.gtin.slice(0, -1)].reverse();
    const sum = digits.reduce((total, digit, index) => total + Number(digit) * (index % 2 === 0 ? 3 : 1), 0);
    ensure((10 - sum % 10) % 10 === Number(v.gtin.at(-1)));
  }
  if (v.technology_features !== null) {
    ensure(Array.isArray(v.technology_features) && v.technology_features.length <= 32);
    const features = v.technology_features;
    ensure(features.every((feature): feature is string => text(feature, 100)) && new Set(features).size === features.length);
    ensure(features.every((feature, index) => index === 0 || codePointOrder(features[index - 1], feature) < 0));
  }
  ensure(v.eprel_id === null || full(/^[1-9][0-9]{0,19}$/, v.eprel_id));
  if (input.status === "complete") ensure(identityKeys.slice(0, 13).every(key => v[key] !== null));
}
function number(v: unknown, maximum: number, places: number, positive = false) {
  ensure(typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= maximum && (!positive || v > 0));
  // Expand the decimal exponent rather than multiplying a binary float.
  const [mantissa, exponent = "0"] = String(v).toLowerCase().split("e");
  const decimals = Math.max(0, (mantissa.split(".")[1]?.length ?? 0) - Number(exponent));
  ensure(decimals <= places);
}
function facts(input: unknown, conflicts: unknown) {
  ensure(object(input) && Object.keys(input).every(key => factKeys.includes(key)));
  ensure(Array.isArray(conflicts) && conflicts.length <= 9 && conflicts.every(key => typeof key === "string" && factKeys.includes(key))
    && new Set(conflicts).size === conflicts.length && conflicts.every((key, index) => index === 0 || conflicts[index - 1] < key)
    && conflicts.every(key => !Object.hasOwn(input, key)) && Object.keys(input).length + conflicts.length > 0);
  for (const [key, value] of Object.entries(input)) {
    if (value === null) continue;
    if (Object.hasOwn(enums, key)) ensure(typeof value === "string" && enums[key].includes(value));
    else if (key === "utqg_treadwear" || key === "eu_external_noise_db")
      ensure(typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= (key === "utqg_treadwear" ? 5000 : 200));
    else if (key === "weight_kg") number(value, 200, 3, true);
    else {
      closed(value, ["value", "unit"]);
      ensure(value.unit === "mm" || value.unit === "1/32 in" || value.unit === "in");
      const [maximum, places] = value.unit === "mm" ? [100, 3] : value.unit === "1/32 in" ? [128, 3] : [4, 4];
      number(value.value, maximum, places);
    }
  }
}
export function isExternalTireFactResult(value: unknown): value is ExternalTireFactResult {
  try {
    const v = bounded(value); closed(v, ["status", "reason", "item"]);
    ensure(v.status === "projected" && v.reason === "projected");
    const item = v.item; closed(item, ["schema", "data_state", "source_refresh_performed", "observation", "identity", "facts", "conflicted_fields"]);
    ensure(item.schema === "external-tire-fact-projection@1" && item.data_state === "local_snapshot" && item.source_refresh_performed === false);
    const observation = item.observation; closed(observation, ["source_id", "snapshot_id", "raw_hash", "parser_version"]);
    ensure(identifier(observation.source_id, 80) && identifier(observation.snapshot_id)
      && full(/^[a-f0-9]{64}$/, observation.raw_hash) && text(observation.parser_version, 100));
    identity(item.identity); facts(item.facts, item.conflicted_fields);
    return true;
  } catch { return false; }
}
export function isExternalTireFactRequest(value: unknown): value is ExternalTireFactRequest {
  try {
    ensure(object(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null));
    const required = ["source_id", "query_id", "verification_id", "variant_id"], keys = Object.keys(value);
    ensure(required.every(key => Object.hasOwn(value, key)) && keys.every(key => required.includes(key) || key === "signal")
      && Object.getOwnPropertySymbols(value).length === 0 && Object.getOwnPropertyNames(value).length === keys.length
      && keys.every(key => "value" in Object.getOwnPropertyDescriptor(value, key)!));
    ensure(identifier(value.source_id, 80) && identifier(value.query_id) && identifier(value.verification_id) && identifier(value.variant_id));
    ensure(value.signal === undefined || (typeof AbortSignal !== "undefined" && value.signal instanceof AbortSignal));
    return true;
  } catch { return false; }
}
