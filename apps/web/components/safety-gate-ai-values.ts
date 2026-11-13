import type { AIEvidence, AIPrepareRequest, SafetyGateAnalysisTarget, SafetyGateEvidence, SafetyGateResult } from "@tire/domain-types";

export const safetyGateAnalysisNotice = "仅整理所选 Safety Gate 官方告警的原始事实；具体轮胎、批次及实物适用性尚未评估，不提供安全或购买建议。历史空缺、告警缺席和未知字段不表示无风险或解除措施。";

export function isSafetyGateEvidence(evidence: AIEvidence): boolean {
  return evidence.evidence_type === "safety_gate" || evidence.source_id === "eu-safety-gate";
}

export function safetyGateTarget(result: SafetyGateResult, alertId: string): SafetyGateAnalysisTarget | null {
  const report = result.document?.report;
  const provenance = result.provenance[0];
  if (!["live", "live_verified_304", "local_snapshot"].includes(result.data_state)
    || result.query.operation !== "report" || !report || !provenance?.snapshot_id
    || result.source_id !== "eu-safety-gate" || provenance.source_id !== "eu-safety-gate"
    || report.report_id !== result.query.report_id || report.reference !== result.query.reference
    || !/^-?[1-9][0-9]{0,11}$/.test(alertId) || !result.document?.alerts.some(alert => alert.alert_id === alertId)) return null;
  return { query: { ...result.query }, reference: { kind: "safety_gate", snapshot_id: provenance.snapshot_id, alert_id: alertId } };
}

export function safetyGateCurrentRequest(target: SafetyGateAnalysisTarget): AIPrepareRequest {
  return { mode: "current", query_kind: "safety_gate_report", source_id: "eu-safety-gate", query: { ...target.query }, alert_ids: [target.reference.alert_id] };
}

export async function verifySafetyGateOriginal(evidence: AIEvidence, original: SafetyGateEvidence): Promise<string> {
  const invalid = () => new Error("原件与所选周报／告警或哈希不一致，未展示为已核对引用。冻结字段仍保留。");
  if (!isSafetyGateEvidence(evidence) || !evidence.snapshot_id || !evidence.alert_id || !evidence.case_number
    || original.id !== evidence.snapshot_id || original.snapshot_id !== evidence.snapshot_id
    || original.source_id !== "eu-safety-gate" || original.content_type !== "application/xml"
    || original.query.operation !== "report" || original.query.report_id !== evidence.report_id
    || original.query.reference !== evidence.report_reference || original.source_url !== evidence.source_url
    || original.raw_hash !== evidence.raw_hash || !/^[a-f0-9]{64}$/.test(original.raw_hash)
    || typeof original.body !== "string") throw invalid();
  const bytes = new TextEncoder().encode(original.body);
  if (bytes.length > 8 * 1024 * 1024) throw invalid();
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), byte => byte.toString(16).padStart(2, "0")).join("");
  if (hash !== evidence.raw_hash || /<!DOCTYPE|<!ENTITY/i.test(original.body)) throw invalid();
  const document = new DOMParser().parseFromString(original.body, "application/xml");
  if (document.querySelector("parsererror") || document.documentElement.tagName !== "Safety-Gate") throw invalid();
  const alertUrl = `https://ec.europa.eu/safety-gate-alerts/screen/webReport/alertDetail/${evidence.alert_id}`;
  if (evidence.alert_source_url !== alertUrl) throw invalid();
  const matches = Array.from(document.documentElement.children).filter(node => node.tagName === "notifications"
    && Array.from(node.children).filter(child => child.tagName === "reference" && child.textContent?.trim() === alertUrl).length === 1);
  if (matches.length !== 1) throw invalid();
  const cases = Array.from(matches[0].children).filter(node => node.tagName === "caseNumber");
  if (cases.length !== 1 || cases[0].textContent?.trim() !== evidence.case_number) throw invalid();
  return new XMLSerializer().serializeToString(matches[0]);
}
