import type { FieldCandidate, FieldDecision, FieldPolicy, FieldResolution } from "@tire/domain-types";
import { fieldDefaultText, fieldStateLabels, fieldValueText } from "./field-authority-values";

export type FieldContext = "current" | "search" | "prepared" | "saved";
const contextLabels: Record<FieldContext, string> = { current: "本次字段依据", search: "检索时字段依据", prepared: "证据准备时字段依据", saved: "保存时字段依据" };
const stamp = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const safeUrl = (value: string) => { try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; } catch { return undefined; } };
const isConflict = (field: FieldDecision) => field.state === "conflict_preferred" || field.state === "conflict_tied";
const evidenceReasons: Record<string, string> = { field_locator: "字段原文位置", snapshot_member_missing_or_ambiguous: "快照成员缺失或不唯一",
  snapshot_member_value_mismatch: "快照成员取值不一致", snapshot_member_invalid: "快照成员结构无效", accepted_verification_missing: "缺少正式核验",
  variant_revoked: "版本已撤销", identity_contract_review_required: "身份合同待核对", identity_snapshot_mismatch: "快照身份不一致",
  identity_snapshot_key_mismatch: "快照身份键不一致", legacy_identity_snapshot_mismatch: "旧快照身份不一致", identity_contract_version_unknown: "身份合同版本未知",
  variant_input_invalid: "规格结构未通过校验", equivalence_event_missing: "缺少有效合并记录", compatible_fact_version_missing: "缺少对应事实版本",
  raw_hash_missing: "缺少原文校验值", raw_integrity_failed: "原文完整性未通过", source_provenance_missing: "缺少来源出处" };
const matchLabels: Record<string, string> = { exact: "精确一致", reviewed_merge: "本次明确采用的有效合并", unverified: "尚未核对", mismatch: "不匹配" };

export function FieldPolicyStamp({ policy, context = "current" }: { policy?: FieldPolicy; context?: FieldContext }) {
  return <div className="field-policy-stamp"><p>{contextLabels[context]} · {policy ? <>规则 <code>{policy.version}</code></> : "此记录未保存字段权威规则，不使用当前规则回填。"}</p>{policy ? <details><summary>规则校验值</summary><code>{policy.digest}</code></details> : null}</div>;
}

function Candidate({ candidate, unit, preferred, onEvidence, onReview, onIdentity }: {
  candidate: FieldCandidate; unit?: string | null; preferred: boolean; onEvidence?: (candidate: FieldCandidate) => void;
  onReview?: (candidate: FieldCandidate) => void; onIdentity?: (id: string) => void;
}) {
  const { dimensions } = candidate;
  return <article className={`field-candidate${preferred ? " preferred" : ""}`} data-source-id={candidate.source_id} data-candidate-id={candidate.id}>
    <div className="field-candidate-heading"><strong>{candidate.source_name || candidate.source_id}</strong><span className={`tag ${preferred ? "success" : "quiet"}`}>{preferred ? "支持默认值" : candidate.eligible ? "参与核对" : "不参与默认值"}</span></div>
    <p className="field-candidate-value">{candidate.present ? fieldValueText(candidate.value, unit) : "来源未列出此字段"}</p>
    <p>{candidate.source_region || "地区未记录"} · {candidate.source_field}{candidate.source_conflicted ? " · 来源内部有矛盾" : ""}</p>
    <dl className="field-evaluation">
      <div><dt>字段权威</dt><dd>{candidate.authority.tier === null ? "无适用等级" : `等级 ${candidate.authority.tier}`} · {candidate.authority.explanation}</dd></div>
      <div><dt>精确身份</dt><dd>{matchLabels[dimensions.identity.match] || dimensions.identity.match} · {dimensions.identity.explanation}</dd></div>
      <div><dt>地区依据</dt><dd>{matchLabels[dimensions.region.match] || dimensions.region.match} · {dimensions.region.source_region || "来源地区未记录"}。{dimensions.region.explanation}</dd></div>
      <div><dt>内容时间</dt><dd>{dimensions.time.basis === "published_at" ? "可靠发布时间" : dimensions.time.basis === "observed_at" ? "原文观察时间" : "没有可排序的内容时间"} · {stamp(dimensions.time.ranked_at)}</dd></div>
      <div><dt>证据完整度</dt><dd>{dimensions.evidence.valid ? "正式证据校验通过" : "正式证据校验未通过"}。{dimensions.evidence.explanation}{dimensions.evidence.missing.length ? <p>仍需核对：{dimensions.evidence.missing.map(reason => evidenceReasons[reason] || reason).join("；")}</p> : null}</dd></div>
    </dl>
    <p className="field-candidate-time">观察 {stamp(candidate.observed_at)} · 核验 {stamp(candidate.verified_at)}。核验时间不作为内容新旧的排序依据。</p>
    {candidate.exclusion_reasons.length ? <ul className="field-exclusions">{candidate.exclusion_reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul> : null}
    {candidate.evidence_locator ? <details><summary>字段原文位置</summary><pre>{typeof candidate.evidence_locator === "string" ? candidate.evidence_locator : JSON.stringify(candidate.evidence_locator, null, 2)}</pre></details> : null}
    <div className="variant-actions">
      {onEvidence && candidate.snapshot_id ? <button type="button" className="text-button" onClick={() => onEvidence(candidate)}>核对此来源原文</button> : safeUrl(candidate.source_url) ? <a href={safeUrl(candidate.source_url)} target="_blank" rel="noopener noreferrer">打开原始来源</a> : null}
      {onReview && candidate.curation_field ? <button type="button" className="text-button" onClick={() => onReview(candidate)}>对此来源纠错</button> : null}
      {onIdentity ? <button type="button" className="text-button" onClick={() => onIdentity(candidate.variant_id)}>核对原始身份</button> : null}
    </div>
    <details className="field-reference"><summary>精确版本与证据引用</summary><p>原 SKU <code>{candidate.variant_id}</code></p><p>快照 <code>{candidate.snapshot_id || "未记录"}</code></p><p>事实版本 <code>{candidate.fact_version_id || "未记录"}</code></p><p>原文 SHA-256 <code>{candidate.raw_hash || "未记录"}</code></p><p>解析器 {candidate.parser_version || "未记录"}</p>{candidate.equivalence_event_id ? <p>本次明确采用的合并记录 <code>{candidate.equivalence_event_id}</code></p> : null}</details>
  </article>;
}

export function FieldResolutionView({ resolution, context = "current", onEvidence, onReview, onIdentity, initialField }: {
  resolution?: FieldResolution; context?: FieldContext; initialField?: string;
  onEvidence?: (candidate: FieldCandidate) => void; onReview?: (candidate: FieldCandidate) => void; onIdentity?: (id: string) => void;
}) {
  if (!resolution) return <p className="field-resolution-missing">{contextLabels[context]}未记录；原保存内容继续保留，不按当前规则补出默认值。</p>;
  const conflicts = resolution.fields.filter(isConflict);
  return <section className="field-resolution" aria-label={contextLabels[context]}>
    <FieldPolicyStamp policy={resolution.policy} context={context} />
    <p className="review-boundary">{resolution.notice}</p>
    {conflicts.length ? <p className="review-warning">{conflicts.length} 项来源冲突。默认展示值仅表示规则取舍，冲突和其他来源记录仍保留。</p> : null}
    <div className="field-decisions">{resolution.fields.map(field => <details className={`field-decision ${isConflict(field) ? "has-conflict" : ""}`} data-field={field.field} data-state={field.state} key={field.field} open={initialField === field.field || undefined}>
      <summary><span><strong>{field.label}</strong><small>{fieldStateLabels[field.state]}</small></span><b>{fieldDefaultText(field)}</b></summary>
      <div className="field-decision-body">{field.identity_bound ? <p className="review-boundary">这是身份字段的来源核对结果，不替代 v2 身份合同，也不修改 SKU。</p> : null}<ul className="field-reasons">{field.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
        <p>保留全部 {field.candidates.length} 条来源记录，包括未参与默认值的记录。</p>
        <div className="field-candidates">{field.candidates.map(candidate => <Candidate key={candidate.id} candidate={candidate} unit={field.unit} preferred={field.has_default && field.default_candidate_ids.includes(candidate.id)} onEvidence={onEvidence} onReview={field.identity_bound ? undefined : onReview} onIdentity={onIdentity} />)}</div>
      </div>
    </details>)}</div>
    {!resolution.fields.length ? <p>此范围没有可展示的字段判定。</p> : null}
    <details className="field-reference"><summary>本次范围与指纹</summary><p>精确版本 <code>{resolution.variant_id}</code></p><p>范围 <code>{resolution.scope}</code> · 数据状态 <code>{resolution.data_state}</code></p><code>{resolution.fingerprint}</code></details>
  </section>;
}

export function FrozenFieldResolutions({ resolutions, policy, context }: { resolutions?: FieldResolution[]; policy?: FieldPolicy; context: "prepared" | "saved" }) {
  return <section className="frozen-field-resolutions"><h3>{contextLabels[context]}</h3><FieldPolicyStamp policy={policy} context={context} />
    {resolutions?.length ? resolutions.map(resolution => <details key={resolution.variant_id}><summary>精确版本 <code>{resolution.variant_id}</code> · {resolution.fields.length} 项字段</summary><FieldResolutionView resolution={resolution} context={context} /></details>) : <p>{resolutions ? "本次证据范围没有轮胎字段权威判定。" : "此记录未保存字段权威判定；保留原事实与冲突，不回填当前结果。"}</p>}
  </section>;
}
