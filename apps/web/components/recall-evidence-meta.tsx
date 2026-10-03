import type { AIEvidence, AIPack, KnowledgeSearchItem, RecallBoundary } from "@tire/domain-types";

const stamp = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
export const recallAnalysisNotice = "仅整理所选官方公告事实，不评估具体轮胎适用性（not_assessed），不提供安全或购买建议。DOT/TIN、生产批次及实物仍需另行核对；空响应不表示旧公告解除，首次观察不表示新发布。";

export function RecallAnalysisBoundary({ boundary, pending = false }: { boundary?: RecallBoundary; pending?: boolean }) {
  if (!boundary && !pending) return null;
  return <aside className="review-boundary recall-analysis-boundary" aria-label="召回公告分析边界"><strong>仅公告事实 · 具体轮胎适用性尚未评估 · not_assessed</strong><p>{boundary?.notice || recallAnalysisNotice}</p></aside>;
}

export function RecallKnowledgeMeta({ item }: { item: KnowledgeSearchItem }) {
  const recall = item.recall;
  if (item.kind !== "recall" || !recall) return null;
  const laterEmpty = recall.observation_kind !== "empty" && recall.latest_observation.observation_kind === "empty";
  return <div className="recall-knowledge-meta">
    <p><strong>{recall.observation_kind === "empty" ? "官方空观察 · 0 条产品记录" : `正式历史公告 · 此份响应共 ${recall.record_count} 条产品记录`}</strong> · {recall.campaign_number}</p>
    <p>{recall.observation_kind === "empty" ? "仅分析本次官方空响应及其局限；不补入旧公告内容。" : "选择此产品命中将分析此公告全部记录；相同公告证据自动合并。"}</p>
    <p>具体轮胎适用性尚未评估 · not_assessed</p>
    {laterEmpty ? <aside className="review-warning"><strong>之后有官方空观察，不表示公告解除</strong><p>空观察时间 {stamp(recall.latest_observation.observed_at)} · 空响应核验 {stamp(recall.latest_observation.verified_at)}</p><p>上方公告内容与时间仍属于所选历史非空响应。</p></aside> : null}
  </div>;
}

export function RecallEvidenceMeta({ evidence }: { evidence: AIEvidence }) {
  if (evidence.evidence_type !== "recall") return null;
  return <div className="recall-ai-meta">
    <p><strong>{evidence.observation_kind === "empty" ? "官方空观察" : "正式公告全部记录"}</strong> · {evidence.campaign_number} · {evidence.record_count ?? "未记录"} 条产品记录</p>
    <p>具体轮胎适用性尚未评估 · not_assessed</p>
    {evidence.observation_kind === "empty" ? <p className="review-warning">本次响应为 0 条，不继承旧公告的概要或措施，也不表示召回解除。</p> : null}
    <dl className="recall-meta"><div><dt>分析所用原文快照</dt><dd><code>{evidence.snapshot_id}</code><br />观察 {stamp(evidence.observed_at)}<br />核验 {stamp(evidence.verified_at)}</dd></div>
      <div><dt>语义公告修订</dt><dd>{evidence.recall_revision_id ? <>#{evidence.recall_revision} · <code>{evidence.recall_revision_id}</code><br />修订观察 {stamp(evidence.revision_observed_at)}<br />修订原始快照 <code>{evidence.revision_snapshot_id}</code></> : "本次为空观察，不绑定历史公告修订"}</dd></div></dl>
    {evidence.recall_revision_id && evidence.snapshot_id !== evidence.revision_snapshot_id ? <p className="recall-help">所用原文是另一份已采纳快照，公告内容沿用上述语义修订；两者时间分别保留。</p> : null}
  </div>;
}

export function RecallFactScope({ fact, evidence }: { fact: AIPack["facts"][number]; evidence: AIEvidence }) {
  if (fact.domain !== "recall") return null;
  const record = evidence.record_scopes?.find(value => value.record_key === fact.record_key);
  return <small className="recall-fact-scope">{fact.scope === "observation" ? "整份官方响应的观察事实" : record ? `产品记录 ${record.index + 1} 的原始字段` : "所引用产品记录的原始字段"}</small>;
}
