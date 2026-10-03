import unicode from "../../domain-types/src/query-filter-unicode.json";
import type { TireFilter, TireQuerySelection, DeviceFallbackQueryKind } from "@tire/domain-types";
import { ExactJsonNumber, stringifyExactJson } from "./exact-json";

const invalid = (): never => { throw Object.assign(new Error("设备查询条件无效。"), { code: "OFFLINE_FALLBACK_INVALID" }); };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value) && !(value instanceof ExactJsonNumber);
const textFields = ["brand", "family", "model", "variant_id", "region", "manufacturer_product_code", "gtin", "eprel_id", "size", "construction", "load_index", "speed_rating", "oe_mark", "acoustic_technology", "technology_features", "season", "utqg_traction", "utqg_temperature", "eu_fuel_class", "eu_wet_grip", "eu_noise_class"];
const boolFields = ["xl", "hl", "run_flat", "acoustic_foam", "ev_marketing_mark"];
const numberFields = ["utqg_treadwear", "eu_external_noise_db"];
const identity = new Set(["brand", "model", "region", "manufacturer_product_code", "size", "load_index", "speed_rating", "oe_mark", "acoustic_technology", "xl", "hl", "run_flat"]);
const technical = new Set(["family", "construction", "load_index", "speed_rating", "oe_mark", "acoustic_technology", "season", "utqg_traction", "utqg_temperature", "eu_fuel_class", "eu_wet_grip", "eu_noise_class"]);
const speedRatings = new Set("A1 A2 A3 A4 A5 A6 A7 A8 B C D E F G J K L M N P Q R S T U H V W Y (Y) ZR".split(" "));
const whitespace = new Set(unicode.whitespace_codepoints);
const casefoldMap = unicode.casefold_map as Record<string, string>;
const decimalMap = unicode.decimal_digit_map as Record<string, number>;
export function pythonWhitespace(value: string): string { return Array.from(value, char => whitespace.has(char.codePointAt(0)!) ? " " : char).join(""); }
export function pythonSplit(value: string): string { return pythonWhitespace(value).split(" ").filter(Boolean).join(" "); }
export function pythonCasefold(value: string): string { return Array.from(value, char => casefoldMap[String(char.codePointAt(0))] ?? char).join(""); }
export function isCategoryC(point: number): boolean {
  let lo = 0, hi = unicode.category_c_ranges.length - 1;
  while (lo <= hi) { const mid = (lo + hi) >>> 1, [start, end] = unicode.category_c_ranges[mid]; if (point < start) hi = mid - 1; else if (point > end) lo = mid + 1; else return true; }
  return false;
}
export function normalizeFilterText(value: unknown): string {
  if (typeof value !== "string" || Array.from(value).length > 512 || Array.from(value).some(char => isCategoryC(char.codePointAt(0)!))) return invalid();
  const result = pythonCasefold(pythonSplit(value.normalize("NFKC")));
  if (!result || Array.from(result).length > 512) return invalid(); return result;
}
export function canonicalDeviceSize(value: unknown): string {
  if (typeof value !== "string") return invalid();
  const compact = pythonWhitespace(value.toUpperCase()).replaceAll(" ", ""), chars = Array.from(compact);
  const digit = (char: string | undefined) => char === undefined ? undefined : decimalMap[String(char.codePointAt(0))];
  if (chars.length < 9 || chars[3] !== "/" || [0, 1, 2, 4, 5].some(i => digit(chars[i]) === undefined)) return invalid();
  let rimStart = 7, construction = "R"; if (chars[6] === "Z" && chars[7] === "R") { construction = "ZR"; rimStart = 8; } else if (chars[6] !== "R") return invalid();
  if (digit(chars[rimStart]) === undefined || digit(chars[rimStart + 1]) === undefined || !(chars.length === rimStart + 2 || chars.length === rimStart + 4 && chars[rimStart + 2] === "." && chars[rimStart + 3] === "5")) return invalid();
  const width = digit(chars[0])! * 100 + digit(chars[1])! * 10 + digit(chars[2])!, aspect = digit(chars[4])! * 10 + digit(chars[5])!;
  const rim = digit(chars[rimStart])! * 10 + digit(chars[rimStart + 1])! + (chars.length === rimStart + 4 ? .5 : 0);
  if (width < 100 || width > 455 || aspect < 20 || aspect > 95 || rim < 10 || rim > 30) return invalid();
  return `${width}/${aspect}${construction}${chars.slice(rimStart).join("")}`;
}
export function normalizeFilterNumber(value: unknown): ExactJsonNumber {
  if (typeof value === "number") { if (!Number.isFinite(value)) return invalid(); value = new ExactJsonNumber(String(value)); }
  if (!(value instanceof ExactJsonNumber)) return invalid();
  if (value.integer !== null) return new ExactJsonNumber(value.integer.toString());
  const float = value.float!; return Number.isInteger(float) ? new ExactJsonNumber(BigInt(float).toString()) : new ExactJsonNumber(pythonFloatText(float));
}
function pythonFloatText(value: number): string {
  const text = String(value), absolute = Math.abs(value); if (absolute >= .0001 && absolute < 1e16) return text;
  const [mantissa, exponent] = value.toExponential().split("e");
  return mantissa + "e" + (Number(exponent) < 0 ? "-" : "+") + String(Math.abs(Number(exponent))).padStart(2, "0");
}
function normalizedValue(field: string, value: unknown): unknown {
  if (boolFields.includes(field)) { if (typeof value !== "boolean") return invalid(); return value; }
  if (numberFields.includes(field)) return normalizeFilterNumber(value);
  const text = normalizeFilterText(value);
  if (field === "size") return canonicalDeviceSize(text);
  if (field === "load_index" && !/^[0-9]{2,3}(?:\/[0-9]{2,3})?$/.test(text) || field === "speed_rating" && !speedRatings.has(text.toUpperCase())) return invalid();
  return text;
}
export function compareCodepoints(a: string, b: string): number {
  const first = Array.from(a, c => c.codePointAt(0)!), second = Array.from(b, c => c.codePointAt(0)!);
  for (let i = 0; i < Math.min(first.length, second.length); i++) if (first[i] !== second[i]) return first[i] - second[i]; return first.length - second.length;
}
/** Python default JSON separators are used only for canonical filter ordering, never server query hashes. */
export function pythonCanonicalJson(value: unknown): string {
  if (value instanceof ExactJsonNumber) return value.token;
  if (typeof value === "number") return Number.isInteger(value) ? BigInt(value).toString() : pythonFloatText(value);
  if (Array.isArray(value)) return "[" + value.map(pythonCanonicalJson).join(", ") + "]";
  if (record(value)) return "{" + Object.keys(value).sort(compareCodepoints).map(key => JSON.stringify(key) + ": " + pythonCanonicalJson(value[key])).join(", ") + "}";
  return stringifyExactJson(value);
}
export function canonicalDeviceFilters(input: unknown): TireFilter[] {
  if (!Array.isArray(input) || input.length > 16) return invalid();
  const unique = new Map<string, TireFilter>();
  for (const value of input) {
    if (!record(value) || typeof value.field !== "string" || typeof value.op !== "string" || !Object.hasOwn(value, "field") || !Object.hasOwn(value, "op") || Object.keys(value).some(key => !["field", "op", "value"].includes(key))) return invalid();
    const { field, op } = value, kind = textFields.includes(field) ? "text" : boolFields.includes(field) ? "boolean" : numberFields.includes(field) ? "number" : invalid();
    if (!["eq", "is_known", "is_unknown", ...(kind === "number" ? ["gte", "lte"] : [])].includes(op)) return invalid();
    const presence = op === "is_known" || op === "is_unknown";
    if (presence && Object.hasOwn(value, "value")) return invalid();
    const condition = { field, op, ...(presence ? {} : { value: normalizedValue(field, value.value) }) } as TireFilter;
    unique.set(pythonCanonicalJson(condition), condition);
  }
  return [...unique.keys()].sort(compareCodepoints).map(key => unique.get(key)!);
}
export type DeviceFilterStatus = "known" | "unknown" | "invalid" | "conflict";
export function readDeviceTireField(row: unknown, field: string): { status: DeviceFilterStatus; value: unknown } {
  if (!record(row) || ![...textFields, ...boolFields, ...numberFields].includes(field)) return { status: "invalid", value: null };
  const facts = row.facts === undefined ? {} : row.facts;
  if (!record(facts) || facts.source_field_conflicts !== undefined && !Array.isArray(facts.source_field_conflicts)) return { status: "invalid", value: null };
  if ((facts.source_field_conflicts as unknown[] | undefined)?.some(item => record(item) && [field, "facts." + field, "identity." + field].includes(String(item.field)))) return { status: "conflict", value: null };
  const value = field === "variant_id" ? row.id : identity.has(field) ? row[field] : facts[field];
  if (value === undefined || value === null || typeof value === "string" && !pythonSplit(value)) return { status: "unknown", value: null };
  try {
    if (technical.has(field) && typeof value === "string" && ["unknown", "unspecified"].includes(normalizeFilterText(value))) return { status: "unknown", value: null };
    if (field === "technology_features") {
      if (!Array.isArray(value)) return { status: "invalid", value: null };
      if (!value.length) return { status: "unknown", value: null };
      return { status: "known", value: value.map(normalizeFilterText) };
    }
    return { status: "known", value: normalizedValue(field, value) };
  } catch { return { status: "invalid", value: null }; }
}
function rational(value: ExactJsonNumber): [bigint, bigint] {
  if (value.integer !== null) return [value.integer, 1n];
  const buffer = new ArrayBuffer(8), view = new DataView(buffer); view.setFloat64(0, value.float!);
  const bits = view.getBigUint64(0), sign = bits >> 63n ? -1n : 1n, exponent = Number(bits >> 52n & 2047n);
  const mantissa = (bits & ((1n << 52n) - 1n)) + (exponent ? 1n << 52n : 0n), shift = exponent ? exponent - 1075 : -1074;
  return shift >= 0 ? [sign * (mantissa << BigInt(shift)), 1n] : [sign * mantissa, 1n << BigInt(-shift)];
}
function compareNumbers(a: ExactJsonNumber, b: ExactJsonNumber): number { const [an, ad] = rational(a), [bn, bd] = rational(b), delta = an * bd - bn * ad; return delta < 0n ? -1 : delta > 0n ? 1 : 0; }
export function deviceConditionMatches(row: unknown, condition: TireFilter): boolean | null {
  const { status, value } = readDeviceTireField(row, condition.field); if (status === "invalid" || status === "conflict") return null;
  if (condition.op === "is_known") return status === "known"; if (condition.op === "is_unknown") return status === "unknown"; if (status !== "known") return null;
  if (condition.field === "technology_features") return (value as string[]).includes(condition.value as string);
  if (value instanceof ExactJsonNumber) { const cmp = compareNumbers(value, normalizeFilterNumber(condition.value)); return condition.op === "eq" ? cmp === 0 : condition.op === "gte" ? cmp >= 0 : cmp <= 0; }
  return value === condition.value;
}
export function selectDeviceTires<T>(rows: T[] | null, filters: TireFilter[], basic: Record<string, string> = {}): { selected: T[]; selection: TireQuerySelection; matches: (boolean | null)[] } {
  const selection: TireQuerySelection = { filters, source_count: rows?.length ?? null, matched_count: rows ? 0 : null, excluded_count: rows ? 0 : null, undetermined_count: rows ? 0 : null }, selected: T[] = [], matches: (boolean | null)[] = [];
  if (!rows) return { selected, selection, matches };
  // TireQuery keeps raw canonical rim digits; only advanced TireFilter values use NFKC.
  const conditions = [...Object.entries(basic).map(([field, value]) => ({ field, op: "eq", value: field === "size" ? value : normalizedValue(field, value) }) as TireFilter), ...filters];
  for (const row of rows) { const values = conditions.map(condition => deviceConditionMatches(row, condition)), matched = values.includes(false) ? false : values.includes(null) ? null : true; matches.push(matched); if (matched === false) selection.excluded_count!++; else if (matched === null) selection.undetermined_count!++; else { selection.matched_count!++; selected.push(row); } }
  return { selected, selection, matches };
}
export function canonicalDeviceQuery(kind: DeviceFallbackQueryKind, input: unknown): Record<string, string> {
  if (!record(input)) return invalid();
  if (kind === "tire") {
    if (Object.keys(input).some(key => !["model", "size"].includes(key))) return invalid(); const query: Record<string, string> = {};
    for (const key of ["model", "size"]) {
      const value = input[key]; if (value === undefined || value === null || value === "") continue;
      if (typeof value !== "string" || Array.from(value).length > (key === "model" ? 120 : 24)) return invalid();
      const normalized = pythonSplit(value); if (!normalized) continue;
      if (key === "size") query.size = canonicalDeviceSize(normalized);
      else { const alias = pythonCasefold(normalized).replace(/^michelin +/, ""); query.model = ({ psev: "Pilot Sport EV", "pilot sport ev": "Pilot Sport EV", ps4s: "Pilot Sport 4 S", "pilot sport 4 s": "Pilot Sport 4 S" } as Record<string, string>)[alias] ?? normalized; }
    }
    if (!Object.keys(query).length) return invalid(); return query;
  }
  const keys = kind === "vehicle_fitments" ? ["vehicle_id"] : kind === "recall_campaign" ? ["campaign_number"] : kind === "recall_search" ? ["search", "offset"] : invalid();
  if (Object.keys(input).length !== keys.length || keys.some(key => !Object.hasOwn(input, key) || typeof input[key] !== "string")) return invalid();
  if (kind === "vehicle_fitments") { if (!(input.vehicle_id as string) || (input.vehicle_id as string).length > 200 || /[\r\n\0]/.test(input.vehicle_id as string)) return invalid(); return { vehicle_id: input.vehicle_id as string }; }
  if (kind === "recall_campaign") { const value = pythonSplit(input.campaign_number as string).toUpperCase(); if (!/^[0-9]{2}T[0-9]{6}$/.test(value)) return invalid(); return { campaign_number: value }; }
  const search = pythonSplit(input.search as string), offset = input.offset as string;
  if (!search || Array.from(search).length > 120 || /[\x00-\x1f]/.test(search) || !/^(?:0|[1-9][0-9]*)$/.test(offset) || BigInt(offset) > 10000n || BigInt(offset) % 10n !== 0n) return invalid();
  return { search, offset };
}
/** This hashes approved history scope only; it is separate from all Python receipt digests. */
export async function approvedDeviceScopeFingerprint(scope: unknown): Promise<string> {
  const stable = (value: unknown): unknown => Array.isArray(value) ? value.map(stable) : record(value) ? Object.fromEntries(Object.keys(value).sort(compareCodepoints).map(key => [key, stable(value[key])])) : value;
  const bytes = new TextEncoder().encode("device-fallback-approved-scope@1\0" + stringifyExactJson(stable(scope))), digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}
