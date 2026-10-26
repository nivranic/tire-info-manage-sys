import type { BinaryQuarantineReviewStateV2, QuarantineEvidenceV2, RawCaptureEvidenceV2, VehicleQuarantineEvidenceV2 } from "@tire/domain-types";
import { assertRawEvidenceDisplay, freezeRawEvidenceDisplay, rawEvidenceCanonical, RawEvidenceDisplayChanged,
  RawEvidenceViewChanged, type RawEvidenceOwner } from "./raw-evidence-v2-context";

export type BinaryQuarantineDetail = VehicleQuarantineEvidenceV2 & { body_encoding: "binary" };
export interface BinaryReviewBasis {
  detail: BinaryQuarantineDetail;
  review: BinaryQuarantineReviewStateV2;
  capture: RawCaptureEvidenceV2;
}
export interface BinaryReviewSelection { id: string; sourceId: string; query: { vehicle_id: string } }
export type BinaryReviewDisplay = ReturnType<typeof freezeRawEvidenceDisplay<BinaryReviewBasis>>;

/** Parent event handlers revoke in the same stack, before React commits/unmounts. */
export function createBinaryReviewRevocation() {
  let generation = 0;
  const listeners = new Set<() => void>(), uncertain = new Set<string>();
  return {
    generation: () => generation,
    revoke() { generation++; for (const listener of [...listeners]) listener(); },
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    markUncertain(id: string) { uncertain.add(id); },
    isUncertain(id: string) { return uncertain.has(id); },
  };
}
export type BinaryReviewRevocation = ReturnType<typeof createBinaryReviewRevocation>;

/** Kept beyond a read operation: idle confirmations also check live owner/transport. */
export function captureBinaryReviewOwner(current: () => RawEvidenceOwner): { assertCurrent(): void } {
  const owner = current();
  return { assertCurrent() {
    const now = current();
    if (!owner.ready || !now.ready || owner.ownerSignal.aborted || now.ownerSignal.aborted
      || !now.isCurrentOwner(owner.ownerEpoch) || now.ownerEpoch !== owner.ownerEpoch
      || now.ownerSignal !== owner.ownerSignal || now.transportEpoch !== owner.transportEpoch
      || now.selection !== owner.selection) throw new RawEvidenceViewChanged();
  } };
}

/** User events clear stale UI immediately; render-time basis checks remain side-effect free. */
export function binaryReviewEventBasis<T extends { owner: { assertCurrent(): void } }>(value: T | null, revoke: () => void): T | null {
  try { if (value) { value.owner.assertCurrent(); return value; } } catch { /* Fail closed and clear the old display. */ }
  revoke(); return null;
}

export function isBinaryQuarantineDetail(detail: QuarantineEvidenceV2): detail is BinaryQuarantineDetail {
  return detail.body_encoding === "binary" && detail.target_kind === "vehicle" && detail.kind === "field_loss";
}
const requireBasis = (value: unknown) => { if (!value) throw new RawEvidenceDisplayChanged(); };
const same = (left: unknown, right: unknown) => rawEvidenceCanonical(left) === rawEvidenceCanonical(right);
const exactKeys = (value: object, keys: string[]) => same(Object.keys(value).sort(), [...keys].sort());
export function assertBinaryReviewBasis(basis: BinaryReviewBasis, selection: BinaryReviewSelection): void {
  const { detail, review, capture } = basis;
  requireBasis(isBinaryQuarantineDetail(detail) && detail.id === selection.id && review.quarantine_id === detail.id
    && detail.source_id === selection.sourceId && review.baseline_snapshot_id === detail.previous_snapshot_id
    && detail.vehicle_id === selection.query.vehicle_id && capture.target_kind === "vehicle"
    && capture.id === detail.raw_capture_id && capture.raw_capture_id === detail.raw_capture_id
    && capture.query_id === detail.query_id && capture.source_id === detail.source_id && same(capture.query, selection.query));
  // All eight common raw fields, including real null, are compared across all three responses.
  for (const field of ["body_encoding", "body", "raw_capture_id", "raw_hash", "byte_count", "content_type", "source_url", "parser_version"] as const) {
    requireBasis(same(detail[field], review.raw_evidence[field]) && same(detail[field], capture[field]));
  }
  requireBasis(capture.body_encoding === "binary" && capture.parse_method === null && capture.mapping_id === null
    && detail.parse_method === "sha256_bound_reviewed_mapping" && detail.mapping_id !== null);
  requireBasis(capture.parser_identity && exactKeys(capture.parser_identity, ["bundle_id", "parser_digest", "deployment_revision"])
    && same(capture.parser_identity, review.raw_evidence.parser_identity));
  const candidate = review.comparison.candidate, provenance = candidate?.parse_provenance;
  requireBasis(candidate && review.comparison.before && Array.isArray(candidate.fitments) && candidate.fitments.length > 0
    && Array.isArray(review.comparison.before.fitments) && review.comparison.before.fitments.length > 0
    && same(candidate, detail.vehicle_payload) && same(detail.candidates, candidate.fitments));
  requireBasis(provenance && exactKeys(provenance, ["contract", "method", "mapping_id", "source_raw_hash", "bundle_id", "mapping_file_sha256"])
    && provenance.contract === "vehicle-pdf-parse@1" && provenance.method === detail.parse_method
    && candidate.parse_method === detail.parse_method && candidate.mapping_id === detail.mapping_id
    && provenance.mapping_id === detail.mapping_id && provenance.source_raw_hash === detail.raw_hash
    && provenance.bundle_id === review.raw_evidence.parser_identity.bundle_id
    && same(provenance, review.raw_evidence.parse_provenance));
}
export function freezeBinaryReviewBasis(basis: BinaryReviewBasis, selection: BinaryReviewSelection): BinaryReviewDisplay {
  assertBinaryReviewBasis(basis, selection);
  return freezeRawEvidenceDisplay("quarantine", basis);
}
export function assertFrozenBinaryReviewBasis(display: BinaryReviewDisplay, basis: BinaryReviewBasis, selection: BinaryReviewSelection): void {
  assertBinaryReviewBasis(basis, selection);
  assertRawEvidenceDisplay(display, "quarantine", basis);
}

function legalDescription(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const point = value.charCodeAt(i);
    if (point >= 0xd800 && point <= 0xdbff) { const next = value.charCodeAt(++i); if (!(next >= 0xdc00 && next <= 0xdfff)) return false; }
    else if (point >= 0xdc00 && point <= 0xdfff) return false;
  }
  return !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value);
}
/** UI-only trim policy; historical descriptions are never trimmed or normalized. */
export function binaryReviewInput(operator: string, reason: string): { operator: string; reason: string } | null {
  const result = { operator: operator.trim(), reason: reason.trim() };
  const operatorLength = Array.from(result.operator).length, reasonLength = Array.from(result.reason).length;
  return operatorLength >= 1 && operatorLength <= 80 && reasonLength >= 5 && reasonLength <= 2000
    && legalDescription(result.operator) && legalDescription(result.reason) ? result : null;
}

export interface BinaryLossRow { path: string; before: string; candidate: string; kind: "record" | "field" }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
/** Mirrors quality.is_known, including Python str.strip whitespace; false and 0 remain known. */
export function binaryReviewKnown(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return /[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/.test(value);
  if (Array.isArray(value)) return value.some(binaryReviewKnown);
  if (object(value)) return Object.values(value).some(binaryReviewKnown);
  return true;
}
export function binaryLossValue(value: unknown, present = true): string {
  if (!present || value === undefined) return "字段缺失（未提供）";
  if (value === null) return "字段缺失（null）";
  if (value === "") return "字段缺失（空字符串）";
  if (typeof value === "string" && !binaryReviewKnown(value)) return "字段缺失（空白字符串）";
  if (Array.isArray(value) && !binaryReviewKnown(value)) return value.length ? "字段缺失（全未知数组）" : "字段缺失（空数组）";
  if (object(value) && !binaryReviewKnown(value)) return "字段缺失（无已知值）";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
/** Match records by stable IDs. A missing row never borrows or dereferences a baseline row. */
export function binaryReviewLossRows(before: unknown, candidate: unknown): BinaryLossRow[] {
  if (!object(before) || !object(candidate) || !Array.isArray(candidate.fitments) || !candidate.fitments.length) throw new RawEvidenceDisplayChanged();
  const rows: BinaryLossRow[] = [];
  const fields = (old: Record<string, unknown>, next: Record<string, unknown>, path: string) => {
    for (const key of Object.keys(old)) {
      const prior = old[key], present = Object.hasOwn(next, key), value = next[key], name = `${path}.${key}`;
      if (!binaryReviewKnown(prior)) continue;
      if (object(prior) && object(value)) fields(prior, value, name);
      else if (!present || !binaryReviewKnown(value)) rows.push({ path: name, before: binaryLossValue(prior), candidate: binaryLossValue(value, present), kind: "field" });
    }
  };
  if (object(before.vehicle) && object(candidate.vehicle)) fields(before.vehicle, candidate.vehicle, "vehicle");
  for (const group of ["trims", "fitments"] as const) {
    if (!Array.isArray(before[group]) || !Array.isArray(candidate[group])) throw new RawEvidenceDisplayChanged();
    const oldRows = before[group] as unknown[], nextRows = candidate[group] as unknown[];
    const index = new Map<string, Record<string, unknown>>();
    for (const row of nextRows) {
      if (!object(row) || typeof row.id !== "string" || index.has(row.id)) throw new RawEvidenceDisplayChanged();
      index.set(row.id, row);
    }
    const seen = new Set<string>();
    for (const row of oldRows) {
      if (!object(row) || typeof row.id !== "string" || seen.has(row.id)) throw new RawEvidenceDisplayChanged();
      seen.add(row.id);
      const next = index.get(row.id), path = `${group}[id=${row.id}]`;
      if (!next) rows.push({ path, before: JSON.stringify(row), candidate: "记录缺失", kind: "record" });
      else fields(row, next, path);
    }
  }
  return rows;
}
