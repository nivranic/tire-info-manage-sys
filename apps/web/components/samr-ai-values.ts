import type { AIEvidence, AIPrepareRequest, SamrRecallAnalysisTarget, SamrRecallEvidence, SamrRecallResult } from "@tire/domain-types";

export const samrAnalysisNotice = "仅整理所选中国官方召回公告的冻结字段。具体 SKU、车辆、批次及实物适用性待核对。原显示发布日期、DeployTime、PubDate、系统观察和核验时间分别保留。开放再分发许可待核验，外发所选证据需逐包授权。";
const nativeReference = /^\/zhxx\/jdczh\/jdczh\/art\/20[0-9]{2}\/art_([a-f0-9]{32})\.html(?:\?type=nFZcuWzfh2c41ylKrWj7k)?$/;
const origin = "https://www.samrdprc.org.cn";

export function isSamrEvidence(evidence: AIEvidence): boolean {
  return evidence.evidence_type === "samr_recall" || evidence.source_id === "samr-cn-recalls";
}

export function samrTarget(result: SamrRecallResult): SamrRecallAnalysisTarget | null {
  const notice = result.document?.operation === "notice" ? result.document.notice : null;
  const provenance = result.provenance[0];
  if (!["live", "live_verified_304", "local_snapshot"].includes(result.data_state)
    || result.query.operation !== "notice" || !notice || !provenance?.snapshot_id
    || result.source_id !== "samr-cn-recalls" || provenance.source_id !== "samr-cn-recalls"
    || nativeReference.exec(result.query.reference)?.[1] !== notice.article_id
    || notice.reference !== result.query.reference || notice.source_url !== origin + notice.reference
    || provenance.source_url !== notice.source_url) return null;
  return { query: { ...result.query }, reference: { kind: "samr_recall", snapshot_id: provenance.snapshot_id, article_id: notice.article_id } };
}

export function samrCurrentRequest(target: SamrRecallAnalysisTarget): AIPrepareRequest {
  return { mode: "current", query_kind: "samr_recall_notice", source_id: "samr-cn-recalls", query: { ...target.query } };
}

export async function verifySamrOriginal(evidence: AIEvidence, original: SamrRecallEvidence): Promise<string> {
  const invalid = () => new Error("原件与所选中国公告、快照或哈希不一致。冻结字段仍可查看。");
  if (!isSamrEvidence(evidence) || !evidence.snapshot_id || !evidence.article_id || !evidence.reference
    || nativeReference.exec(evidence.reference)?.[1] !== evidence.article_id
    || evidence.source_url !== origin + evidence.reference
    || original.id !== evidence.snapshot_id || original.snapshot_id !== evidence.snapshot_id
    || original.source_id !== "samr-cn-recalls" || original.content_type !== "text/html"
    || original.query.operation !== "notice" || original.query.reference !== evidence.reference
    || original.source_url !== evidence.source_url || original.raw_hash !== evidence.raw_hash
    || !/^[a-f0-9]{64}$/.test(original.raw_hash) || typeof original.body !== "string") throw invalid();
  const bytes = new TextEncoder().encode(original.body);
  if (bytes.length > 8 * 1024 * 1024) throw invalid();
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), byte => byte.toString(16).padStart(2, "0")).join("");
  if (hash !== evidence.raw_hash) throw invalid();
  return original.body;
}
