"use client";

import { useEffect, useLayoutEffect, useId, useRef, useState, type MutableRefObject } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type {
  Evidence, FitmentRelationRevision, InterestCapabilities, InterestChangedField, InterestCondition, InterestCurationApplicabilityAffected, InterestCurationApplicabilityBasis, InterestCurationApplicabilityRecord, InterestDetail, InterestDomain, InterestEvidence,
  InterestEvent, InterestKind, InterestNotification, InterestOriginalEvidence, InterestPreview, InterestPreviewItem, InterestRecord,
  InterestSettings, QuarantineEvidence, TestEventDetail, VehicleCandidate,
} from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { RawEvidenceV2View, useRawEvidenceV2 } from "./raw-evidence-v2";

const kinds: [InterestKind, string][] = [["brand", "品牌"], ["model", "型号"], ["size", "尺寸"], ["oe", "OE 标识"], ["technology", "静音技术"], ["test_organization", "测试机构"], ["vehicle_fitment", "车型适配"]];
const domains: Record<InterestDomain, string> = {
  tire: "轮胎", test_event: "测试场次", vehicle: "车型", fitment: "人工适配关系",
  tire_curation: "手工参数纠错", tire_lifecycle: "SKU 本地状态", tire_identity: "身份映射决定", tire_catalog: "来源目录成员",
  tire_curation_validity: "人工处理适用性",
  tire_source_quality: "来源采集状态异常",
};
const domainNotices: Partial<Record<InterestDomain, string>> = {
  tire_curation: "人工纠错与来源原值分别保存。清除人工覆盖表示恢复当时来源值；来源事实更新使旧处理不再适用的变化，另列为人工处理适用性事件。",
  tire_lifecycle: "这里是本地对精确 SKU 的撤销或恢复决定，不表示官方召回、来源停售或参数发生变化。",
  tire_identity: "这里是本地身份更正、合并或撤回映射。历史事实与兴趣主体仍保持原版本，不自动改为目标 SKU。",
  tire_catalog: "加入或移出仅说明同一来源、同一查询范围的已采纳目录成员变化；移出不表示 SKU 被撤销或官方停售。",
  tire_curation_validity: "来源事实更新后，原人工处理绑定的基础事实已更替，需要复核。原人工决定仍保留；这不是新的人工修改，也不会自动将旧处理恢复到新来源版本。",
  tire_source_quality: "与你关注范围相关的查询，本次更新被隔离。相关性只来自当时采纳基线的同一成员；本次候选未采纳，不能据此确认候选参数、SKU 消失或停售。",
};
const actionLabels: Partial<Record<InterestDomain, Record<string, string>>> = {
  tire: { variant_observed: "首次本地观察", facts_changed: "来源参数变化" },
  test_event: { create: "录入场次", revise: "修订场次", revoke: "撤销场次", restore: "恢复场次" },
  vehicle: { vehicle_observed: "首次本地观察车型", vehicle_facts_changed: "车型资料变化" },
  fitment: { create: "建立关系", revise: "修订关系", review: "复核关系", revoke: "撤销关系", restore: "恢复关系" },
  tire_curation: { manual_override: "人工覆盖参数", revoke: "人工撤销字段", clear_override: "撤回人工覆盖" },
  tire_lifecycle: { revoke: "本地撤销 SKU", restore: "本地恢复 SKU" },
  tire_identity: { correct: "更正身份映射", merge: "建立合并映射", clear: "撤回身份映射" },
  tire_catalog: { added: "加入来源目录", removed: "移出来源目录" },
  tire_curation_validity: { invalidate: "来源事实更新后待复核" },
  tire_source_quality: { quarantined: "查询更新被质量隔离" },
};
const actionLabel = (domain: InterestDomain, action: string) => actionLabels[domain]?.[action] ? `${actionLabels[domain][action]}（${action}）` : action;
const stateLabels: Record<string, string> = { accepted: "已采纳", active: "有效", revoked: "已撤销", manual_override: "人工覆盖", cleared: "已撤回", redirected: "本地映射", present: "目录中存在", absent: "目录中缺席", applicable: "当时适用", needs_review: "需要复核", quarantined: "未采纳 · 质量隔离" };
const stateLabel = (event: InterestEvent) => stateLabels[event.state] ? `${stateLabels[event.state]}（${event.state}）` : event.state;
const limitationLabels: Record<string, string> = {
  accepted_source_facts_only: "只处理已采纳的来源参数", historical_snapshot_identity_only: "身份以当时原始快照为准",
  manual_transcription_unverified: "测试为未经独立核验的人工转录", participant_only_not_sku: "测试参测记录不代表精确 SKU", explicit_metric_keys_only: "指标只按明确的原始 key 匹配",
  accepted_fact_version_changes_only: "只处理已采纳的事实版本变化", no_inferred_tire_fitment: "不推断轮胎适配关系",
  manual_relation_not_official_oe: "人工适配关系不代表官方 OE 认证", mixed_conditions_require_reviewed_frozen_relation: "跨轮胎和车型的组合条件需要已复核的冻结关系",
  local_manual_decision_not_source_fact: "人工决定与来源原值分别保存", source_bound_overlay_only: "人工覆盖只适用于其绑定来源与基础事实",
  local_entity_state_not_official_recall: "本地 SKU 状态不代表官方召回或停售", source_contexts_not_pooled: "不同来源分别匹配，不拼接条件",
  local_mapping_no_fact_or_interest_retargeting: "本地身份映射不移动历史事实，也不改向兴趣主体", source_contexts_only_target_is_basis: "只用原主体的来源上下文匹配，目标仅作为决定依据",
  source_query_membership_only_not_entity_revocation: "目录成员仅限同一来源与查询范围，移出不等于撤销 SKU", accepted_adjacent_results_only: "只比较相邻的已采纳结果", no_304_membership_event: "304 核验不产生虚假的目录变化",
  source_bound_overlay_applicability_only: "只处理绑定同一来源基础事实的人工处理适用性",
  derived_transition_not_manual_decision: "这是派生适用状态变化，不是新的人工决定，也不自动恢复旧处理",
  actual_fact_replacement_including_304_reconciliation: "实际事实版本更替才会触发；合法跨查询 304 协调也可能产生新事实，单纯核验不会触发",
  explicit_subscription_required: "必须另行明确订阅采集状态异常提醒",
  verified_baseline_members_only: "只用经核对的当时采纳基线成员判断相关性",
  unaccepted_candidates_never_matched: "本次未采纳候选不参与匹配，也不据此确认参数变化",
  no_quality_history_preview: "质量提醒不提供历史预览，也不补发旧隔离",
  local_notifications_only: "仅发送本人站内通知，不外发 Webhook 等消息",
};
const unsupportedLabels: Record<string, string> = {
  source_quality_rejection: "来源拒绝或隔离结果", metadata_only_verification: "仅验证元数据更新", derived_manual_applicability: "来源刷新后人工覆盖的适用性变化",
};
const unsupportedReasonLabels: Record<string, string> = {
  rejected_or_quarantined_results_are_not_accepted_events: "拒绝或隔离结果不是已采纳事件",
  only_tire_quarantine_with_verified_baseline_supported: "仅支持有可核对基线的轮胎隔离，其他拒收或隔离暂未接入",
  unchanged_facts_are_not_new_publications: "事实不变的核验不是新发布",
  source_refresh_invalidation_not_a_new_manual_revision: "来源刷新使旧覆盖失效，但没有产生新的人工修订，尚不单独通知",
};
const evidenceLabels: Record<InterestEvidence["kind"], string> = {
  tire_change: "轮胎事实变化", test_revision: "测试历史修订", vehicle_snapshot: "车型原始快照", fitment_relation_revision: "适配关系历史修订",
  tire_curation_revision: "原始手工纠错修订", tire_lifecycle_event: "原始 SKU 本地状态决定", tire_identity_revision: "原始身份映射决定", tire_catalog_revision: "原始来源目录成员记录",
  tire_curation_applicability_event: "原始人工处理适用性记录",
  tire_source_quarantine: "本次隔离原文 · 未采纳", tire_source_quality_baseline: "当时采纳基线原文",
};
const fields: Record<InterestChangedField, string> = {
  "identity.brand": "品牌", "identity.model": "型号", "identity.size": "尺寸", "identity.oe_mark": "OE 标识",
  "identity.acoustic_technology": "静音技术", "identity.technology_features": "技术配置", facts: "轮胎参数",
  "facts.utqg_treadwear": "UTQG 耐磨", "facts.utqg_traction": "UTQG 牵引", "facts.utqg_temperature": "UTQG 耐热",
  "facts.tread_depth": "胎纹深度", "facts.tread_depths": "多处胎纹深度",
  "event.organization": "测试机构", "event.participants": "测试成员", "event.metrics": "指标定义", "event.measurements": "测试成绩",
  "event.metadata": "场次资料", state: "记录状态", vehicle: "车型资料", trims: "车辆配置", fitments: "轮毂与前后轴",
  footnotes: "适配注释", selection: "关系选定对象", review_state: "关系复核状态", vehicle_evidence: "关系中的车型证据",
  tire_evidence: "关系中的轮胎证据", binding: "证据绑定",
  curation: "人工参数处理", identity_resolution: "本地身份映射", catalog_membership: "来源目录成员状态", curation_applicability: "人工处理适用性",
};
const kindLabel = (kind: InterestKind) => kinds.find(([key]) => key === kind)![1];
const stamp = (value: string | null) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "未记录";
const errorText = (cause: unknown) => cause instanceof ApiError && cause.code === "source_quality_interest_filter_unsupported" ? "采集状态异常提醒仅支持品牌、型号、尺寸、OE 与技术条件，且变化字段和测试指标须留空。原条件已保留，请手动调整或取消此项订阅。" : cause instanceof ApiError && cause.code === "source_quality_interest_history_invalid" ? "这条质量提醒的历史证据绑定或原文校验未通过，未读取替代记录。" : cause instanceof Error ? cause.message : "操作未完成，请重试。";
const settingsOf = (record: InterestSettings): InterestSettings => ({ name: record.name, enabled: record.enabled, conditions: record.conditions, metric_keys: record.metric_keys, changed_fields: record.changed_fields, source_quality_notifications: record.source_quality_notifications === true });
const newCondition = (kind: InterestKind): InterestCondition => kind === "model"
  ? { kind, values: [{ brand: "", model: "" }] }
  : kind === "vehicle_fitment" ? { kind, values: [{ vehicle_id: "" }] } : { kind, values: [""] };
const blankSettings = (): InterestSettings => ({ name: "", enabled: false, conditions: [newCondition("brand")], metric_keys: [], changed_fields: [], source_quality_notifications: false });
const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const isId = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isRevision = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const isHash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

function applicabilityRecord(original: InterestOriginalEvidence): InterestCurationApplicabilityRecord {
  const row = original.record;
  if (!isId(row.source_id) || !isId(row.before_fact_id) || !isId(row.after_fact_id) || row.before_fact_id === row.after_fact_id
    || !isId(row.verification_id) || row.action !== "invalidate" || !isRevision(row.manual_revision_watermark)
    || !Array.isArray(row.affected) || row.affected.length === 0 || !isRecord(row.binding)
    || !isRecord(row.binding.before) || !isRecord(row.binding.after)) throw new Error("派生适用性记录的事实或人工修订绑定不完整，未使用当前状态补全。");
  const seen = new Set<string>();
  for (const affected of row.affected) {
    if (!isRecord(affected) || !isId(affected.manual_revision_id) || seen.has(affected.manual_revision_id)
      || !isRevision(affected.manual_revision) || affected.manual_revision > row.manual_revision_watermark || !isId(affected.field)
      || (affected.action !== "manual_override" && affected.action !== "revoke")
      || affected.before_status !== (affected.action === "manual_override" ? "manual_override" : "revoked")
      || affected.after_status !== "needs_review" || !isHash(affected.manual_fingerprint)
      || !original.evidence.some(ref => ref.kind === "tire_curation_revision" && ref.record_id === affected.manual_revision_id
        && ref.entity_id === original.entity_id && ref.source_id === row.source_id
        && ref.revision === affected.manual_revision && ref.fingerprint === affected.manual_fingerprint)) throw new Error("受影响的原人工修订与冻结 ID、修订或指纹不一致，未显示替代记录。");
    seen.add(affected.manual_revision_id);
  }
  for (const [side, factId] of [[row.binding.before, row.before_fact_id], [row.binding.after, row.after_fact_id]]) {
    if (!isRecord(side) || side.source_id !== row.source_id || side.fact_version_id !== factId
      || (side.fact_version !== null && !isRevision(side.fact_version)) || (side.facts_hash !== null && !isHash(side.facts_hash))
      || (side.snapshot_member_fact_version !== null && !isRevision(side.snapshot_member_fact_version))) throw new Error("派生记录的实际事实与快照成员依据不完整，未使用当前事实补全。");
  }
  if (row.binding.after.verification_id !== row.verification_id) throw new Error("派生记录未绑定触发本次事实采纳的核验，未展示该记录。");
  return row as InterestCurationApplicabilityRecord;
}

function completeApplicabilityBasis(basis: InterestCurationApplicabilityBasis) {
  return isId(basis.snapshot_id) && isHash(basis.raw_hash) && isId(basis.query_key)
    && isId(basis.verification_id) && isId(basis.verification_status) && isId(basis.verified_at)
    && basis.present === true && isHash(basis.parsed_variants_hash) && isHash(basis.member_hash) && isId(basis.structured_locator)
    && isRevision(basis.fact_version) && isHash(basis.facts_hash) && isRevision(basis.snapshot_member_fact_version);
}

function verifyOriginal(original: InterestOriginalEvidence, evidence: InterestEvidence) {
  if (!isRevision(evidence.revision) || !isHash(evidence.fingerprint)
    || original.schema !== "interest-original-evidence@1" || original.scope !== "local_workspace" || original.data_state !== "local_snapshot"
    || original.kind !== evidence.kind || original.record_id !== evidence.record_id || original.entity_id !== evidence.entity_id
    || original.revision !== evidence.revision || original.fingerprint !== evidence.fingerprint || !isRecord(original.record)
    || original.record.id !== evidence.record_id || original.record.variant_id !== evidence.entity_id
    || original.record.revision !== evidence.revision || !Array.isArray(original.evidence)) throw new Error("返回的原始记录与冻结 ID、实体、修订或指纹不一致，未展示当前记录或其他版本。");
}

function ApplicabilitySummary({ record, busy, onManual }: { record: InterestCurationApplicabilityRecord; busy: boolean; onManual: (affected: InterestCurationApplicabilityAffected) => void }) {
  return <section aria-label="派生适用性与原人工决定"><h4>派生适用性修订 #{record.revision}</h4><p>派生记录 {record.id} · 来源 {record.source_id}。这是来源事实更新后的适用状态记录，原人工决定仍保留。</p>
    {(["before", "after"] as const).map(side => <p key={side}>{side === "before" ? "变化前" : "变化后"}实际事实 #{record.binding[side].fact_version ?? "未能确认"}（{record.binding[side].fact_version_id}） · 快照成员版本 {record.binding[side].snapshot_member_fact_version ?? "未能确认"} · 查询范围 {record.binding[side].query_key ?? "未能确认"}</p>)}
    <p>实际事实版本与快照成员版本分别保留，合法 304 协调时可以不同；两侧查询范围也可以不同。</p>
    {record.affected.map(item => <article key={item.manual_revision_id}><h4>原人工修订 #{item.manual_revision} · {item.field}</h4><p>{item.action === "manual_override" ? "人工覆盖参数" : "人工撤销字段"}：当时适用 → 来源事实更新后待复核。未创建新的人工决定，也未自动恢复旧处理。</p><p>原人工记录 {item.manual_revision_id}</p><button type="button" className="text-button" disabled={busy} onClick={() => onManual(item)}>重开原人工决定 #{item.manual_revision}</button></article>)}
  </section>;
}
type FrozenInterestItem = InterestPreviewItem | InterestNotification;
const reasonLabels: Record<string, string> = {
  matches_before: "变化前的同一证据对象满足全部关注条件。",
  matches_after: "变化后的同一证据对象满足全部关注条件。",
  reviewed_relation_required: "缺少已复核的适配关系，无法确认全部条件属于同一条证据链。",
  missing_tire_identity: "缺少可核对的轮胎身份，无法确认轮胎身份相关条件。",
  missing_vehicle_scope: "缺少明确的车型、配置或车轴范围，无法确认车型适配条件。",
  missing_test_organization: "记录未声明测试机构，无法确认机构条件。",
  source_field_conflict: "来源字段存在冲突，无法据此确认匹配。",
  historical_evidence_unverifiable: "历史证据无法核验，无法确认匹配。",
  selected_changed_field_absent: "本次事件没有所选字段的变化。",
  selected_metric_change_absent: "本次事件没有所选原始指标 key 的变化。",
  condition_not_matched: "已录证据不满足全部关注条件。",
  missing_declared_technology: "记录未明确声明所需技术，无法确认技术条件。",
  missing_declared_brand: "记录未明确声明品牌，无法确认品牌条件。",
  missing_declared_size: "记录未明确声明尺寸，无法确认尺寸条件。",
  missing_declared_oe: "记录未明确声明 OE 标识，无法确认 OE 条件。",
  matches_baseline_member: "当时采纳基线中的同一成员满足全部关注条件；本次隔离候选未参与匹配。",
  source_quality_not_subscribed: "当时未明确订阅采集状态异常提醒。",
  baseline_evidence_unverifiable: "当时采纳基线的证据不足，无法确认完整匹配。",
};

function ReasonList({ reasons }: { reasons: string[] }) {
  return <ul>{reasons.map((reason, index) => <li key={index}>{Object.hasOwn(reasonLabels, reason) ? reasonLabels[reason] : "后端返回了尚未识别的判定原因，请核对原始原因码。"}<small>（{reason}）</small></li>)}</ul>;
}

function ConditionSummary({ conditions }: { conditions: InterestCondition[] }) {
  return <ol className="interest-condition-summary">{conditions.map((condition, index) => <li key={index}><strong>{index ? "且 · " : ""}{kindLabel(condition.kind)}</strong>：{condition.kind === "model"
    ? condition.values.map(value => `${value.brand} / ${value.model}`).join(" 或 ")
    : condition.kind === "vehicle_fitment" ? condition.values.map(value => [value.vehicle_id, value.trim_id && `配置 ${value.trim_id}`, value.wheel_option_id && `轮毂 ${value.wheel_option_id}`, value.axle && (value.axle === "front" ? "前轴" : "后轴")].filter(Boolean).join(" · ")).join(" 或 ")
      : condition.values.join(" 或 ")}</li>)}</ol>;
}

function Capabilities({ value }: { value: InterestCapabilities }) {
  return <details className="interest-capabilities"><summary>匹配能力与未覆盖的事件</summary><p>{value.notice}</p><p>仅处理已录本地事件，不启动联网抓取或定时任务。</p>{value.domains.map(domain => <div key={domain.domain}><strong>{domains[domain.domain] || domain.domain} · {domain.supported ? "已接入本地事件" : "未接入"}</strong><p>事件：{domain.event_kinds.map(action => actionLabel(domain.domain, action)).join("、") || "无"}</p>{domainNotices[domain.domain] ? <p>{domainNotices[domain.domain]}</p> : null}{domain.limitations.map((reason, index) => <p key={index}>{limitationLabels[reason] || "尚未识别的能力限制，请核对原始说明码。"}<small>（{reason}）</small></p>)}</div>)}{value.unsupported_events.length ? <ul>{value.unsupported_events.map((item, index) => <li key={index}>{unsupportedLabels[item.kind] || item.kind}：{unsupportedReasonLabels[item.reason] || "尚未接入的事件，请核对原始原因码。"}<small>（{item.kind} · {item.reason}）</small></li>)}</ul> : null}</details>;
}

type EvidenceAbortGroup = MutableRefObject<Set<() => void>>;
export function HistoricalEvidence({ evidence, abortGroup, qualityNotice }: { evidence: InterestEvidence; abortGroup?: EvidenceAbortGroup; qualityNotice?: InterestNotification }) {
  const auth = useWorkbenchAuth();
  const ownerEpoch = auth.ownerEpoch;
  const [open, setOpen] = useState(!!qualityNotice);
  const abortReader = useRef<() => void>(() => {});
  useLayoutEffect(() => {
    const cancel = () => abortReader.current(); abortGroup?.current.add(cancel);
    return () => { cancel(); abortGroup?.current.delete(cancel); };
  }, [abortGroup]);
  useLayoutEffect(() => {
    const cancel = () => { abortReader.current(); setOpen(false); };
    auth.ownerSignal.addEventListener("abort", cancel, { once: true });
    return () => { auth.ownerSignal.removeEventListener("abort", cancel); abortReader.current(); };
  }, [auth.ownerSignal]);
  return <details className="interest-evidence" open={open} onToggle={event => { if (!event.currentTarget.open) abortReader.current(); setOpen(event.currentTarget.open); }}><summary>冻结绑定 · {evidenceLabels[evidence.kind] || evidence.kind} · {evidence.record_id}</summary><dl>{Object.entries(evidence).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{Array.isArray(value) ? value.join("、") || "无" : value === null ? "未记录（null）" : String(value)}</dd></div>)}</dl>{open ? <HistoricalEvidenceReader evidence={evidence} ownerEpoch={ownerEpoch} abortReader={abortReader} qualityNotice={qualityNotice} /> : null}</details>;
}

function HistoricalEvidenceReader({ evidence, ownerEpoch, abortReader, qualityNotice }: { evidence: InterestEvidence; ownerEpoch: number; abortReader: MutableRefObject<() => void>; qualityNotice?: InterestNotification }) {
  const auth = useWorkbenchAuth();
  const request = useRef<AbortController | null>(null);
  type HistoricalRecord = { kind: "snapshot"; value: Evidence; side: "before" | "after" | "baseline" } | { kind: "quarantine"; value: QuarantineEvidence } | { kind: "test_revision"; value: TestEventDetail } | { kind: "fitment_revision"; value: FitmentRelationRevision } | { kind: "governance"; value: InterestOriginalEvidence };
  const [result, setResult] = useState<HistoricalRecord | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [applicability, setApplicability] = useState<InterestCurationApplicabilityRecord | null>(null);
  const [vehicleSelection, setVehicleSelection] = useState<{ id: string; previous: boolean; revision: number } | null>(null);
  const vehicleReadRevision = useRef(0);
  const vehicleReader = useRawEvidenceV2({ kind: "vehicle", id: vehicleSelection?.id || "",
    selectionKey: JSON.stringify([evidence, vehicleSelection?.previous, vehicleSelection?.revision]),
    validate(value) {
      if (!vehicleSelection || value.snapshot_id !== vehicleSelection.id || (evidence.source_id !== null && value.source_id !== evidence.source_id)
        || (!vehicleSelection.previous && evidence.fingerprint !== null && value.raw_hash !== evidence.fingerprint)) throw new Error("车型原件与冻结事件快照、来源或哈希不一致。");
    } });
  abortReader.current = () => { request.current?.abort(); vehicleReader.cancel(); setVehicleSelection(null); setLoading(false); setResult(null); setError(""); setApplicability(null); };
  useEffect(() => () => request.current?.abort(), []);
  async function read(previous = false, sourceSnapshot = false, manualRevision?: InterestCurationApplicabilityAffected) {
    if (!auth.ready || auth.ownerSignal.aborted || !auth.isCurrentOwner(ownerEpoch)) return;
    vehicleReader.cancel();
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    const current = () => auth.ready && !auth.ownerSignal.aborted && !controller.signal.aborted && request.current === controller && auth.isCurrentOwner(ownerEpoch);
    setResult(null); setError(""); setLoading(true);
    setVehicleSelection(null);
    try {
      let value: HistoricalRecord;
      let derivedRecord: InterestCurationApplicabilityRecord | null = null;
      if (evidence.kind === "tire_source_quarantine" || evidence.kind === "tire_source_quality_baseline") {
        if (!qualityNotice || qualityNotice.event.domain !== "tire_source_quality") throw new Error("缺少本人质量通知的冻结绑定，未读取共享原文。");
        // A prior list or detail response never authorizes a later evidence read.
        const latest = await tireApi.interestNotification(qualityNotice.id, controller.signal);
        if (!current()) return;
        if (latest.id !== qualityNotice.id || latest.interest_id !== qualityNotice.interest_id || latest.interest_revision !== qualityNotice.interest_revision
          || latest.event.domain !== "tire_source_quality" || latest.event.id !== qualityNotice.event.id || latest.event.event_hash !== qualityNotice.event.event_hash) throw new Error("重新核对的本人通知与当时事件或兴趣修订不一致，未读取替代原文。");
        const reference = latest.event.evidence.find(item => item.kind === evidence.kind);
        const key = (item: InterestEvidence) => JSON.stringify([item.kind, item.record_id, item.entity_id, item.revision, item.snapshot_id, item.previous_snapshot_id, item.source_id, item.source_url, item.verification_ids, item.fingerprint, item.contract_version]);
        if (!reference || key(reference) !== key(evidence)) throw new Error("质量原文引用与通知冻结绑定不一致，未使用当前记录补全。");
        const { quarantine: q, baseline: b } = latest.event.after;
        if (evidence.kind === "tire_source_quarantine") {
          const original = await tireApi.quarantineEvidence(q.id, controller.signal);
          if (!current()) return;
          if (original.id !== q.id || original.query_id !== q.query_id || original.source_id !== q.source_id || original.source_url !== q.source_url
            || original.raw_hash !== q.raw_hash || original.parser_version !== q.parser_version || Date.parse(original.observed_at) !== Date.parse(q.observed_at)
            || original.previous_snapshot_id !== b.snapshot_id || original.accepted !== false || original.data_state !== "local_snapshot"
            || original.status !== "quarantined" || typeof original.body !== "string") throw new Error("隔离原文的 ID、查询、来源、时间或哈希与通知绑定不一致，未展示其他记录。");
          if (!globalThis.crypto?.subtle) throw new Error("当前环境无法核验隔离原文 SHA-256，未展示未核验内容。");
          const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(original.body))), byte => byte.toString(16).padStart(2, "0")).join("");
          if (hash !== q.raw_hash) throw new Error("隔离原文内容与冻结 SHA-256 不一致，未展示该记录。");
          value = { kind: "quarantine", value: original };
        } else {
          const snapshot = await tireApi.evidence(b.snapshot_id, controller.signal);
          if (!current()) return;
          if (snapshot.id !== b.snapshot_id || snapshot.source_id !== b.source_id || snapshot.source_url !== b.source_url || snapshot.raw_hash !== b.raw_hash
            || snapshot.parser_version !== b.parser_version || Date.parse(snapshot.observed_at) !== Date.parse(b.observed_at) || typeof snapshot.body !== "string") throw new Error("当时采纳基线原文与冻结快照、来源、时间或哈希不一致，未展示当前快照。");
          if (!globalThis.crypto?.subtle) throw new Error("当前环境无法核验基线原文 SHA-256，未展示未核验内容。");
          const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(snapshot.body))), byte => byte.toString(16).padStart(2, "0")).join("");
          if (hash !== b.raw_hash) throw new Error("基线原文内容与冻结 SHA-256 不一致，未展示该记录。");
          value = { kind: "snapshot", value: snapshot, side: "baseline" };
        }
      } else if (evidence.kind === "test_revision") {
        if (evidence.revision === null) throw new Error("冻结绑定缺少场次修订，无法读取指定历史版本。");
        const event = await tireApi.testEvent(evidence.entity_id, controller.signal, evidence.revision);
        if (event.id !== evidence.entity_id || event.revision !== evidence.revision || event.revision_id !== evidence.record_id) throw new Error("返回的场次修订与冻结绑定不一致，未展示其他版本。");
        if (evidence.fingerprint !== null && event.fingerprint !== evidence.fingerprint) throw new Error("场次修订指纹与冻结绑定不一致，未展示该记录。");
        value = { kind: "test_revision", value: event };
      } else if (evidence.kind === "fitment_relation_revision") {
        if (evidence.revision === null) throw new Error("冻结绑定缺少适配修订，无法读取指定历史版本。");
        const revision = await tireApi.fitmentRelationRevision(evidence.entity_id, evidence.revision, controller.signal);
        if (revision.id !== evidence.record_id || revision.revision !== evidence.revision || revision.relation_id !== evidence.entity_id) throw new Error("返回适配修订与冻结绑定不一致，未展示当前关系或其他版本。");
        if (evidence.fingerprint !== null && revision.binding_hash !== evidence.fingerprint) throw new Error("适配修订的证据指纹与冻结绑定不一致，未展示该记录。");
        value = { kind: "fitment_revision", value: revision };
      } else if (evidence.kind === "tire_curation_revision" || evidence.kind === "tire_lifecycle_event" || evidence.kind === "tire_identity_revision" || evidence.kind === "tire_catalog_revision" || evidence.kind === "tire_curation_applicability_event") {
        if (evidence.revision === null || !evidence.fingerprint) throw new Error("冻结绑定缺少治理记录修订或指纹，无法核对原始记录。");
        const original = await tireApi.interestEvidence(evidence.kind, evidence.record_id, controller.signal);
        verifyOriginal(original, evidence);
        if (evidence.kind === "tire_curation_applicability_event") {
          derivedRecord = applicabilityRecord(original);
          if (derivedRecord.source_id !== evidence.source_id) throw new Error("派生适用性记录的来源与冻结绑定不一致。");
          if (manualRevision) {
            const affected = derivedRecord.affected.find(item => item.manual_revision_id === manualRevision.manual_revision_id);
            if (!affected || affected.manual_revision !== manualRevision.manual_revision || affected.manual_fingerprint !== manualRevision.manual_fingerprint) throw new Error("原人工决定与派生记录的受影响项不一致，未读取替代修订。");
            const reference = original.evidence.find(item => item.kind === "tire_curation_revision" && item.record_id === affected.manual_revision_id)!;
            const manual = await tireApi.interestEvidence("tire_curation_revision", affected.manual_revision_id, controller.signal);
            verifyOriginal(manual, reference);
            if (manual.record.source_id !== derivedRecord.source_id || manual.record.base_fact_id !== derivedRecord.before_fact_id
              || manual.record.field !== affected.field || manual.record.action !== affected.action) throw new Error("重新读取的人工决定不属于当时的来源、基础事实或字段，未显示该记录。");
            value = { kind: "governance", value: manual };
          } else if (sourceSnapshot) {
            const basis: InterestCurationApplicabilityBasis = previous ? derivedRecord.binding.before : derivedRecord.binding.after;
            const snapshotId = previous ? evidence.previous_snapshot_id : evidence.snapshot_id;
            if (!completeApplicabilityBasis(basis) || !isId(snapshotId) || basis.snapshot_id !== snapshotId || !isHash(basis.raw_hash)
              || !isId(basis.verification_id) || !evidence.verification_ids.includes(basis.verification_id)
              || basis.source_id !== derivedRecord.source_id) throw new Error("此侧来源原文的冻结快照、查询或核验依据不完整，未使用当前来源补全。");
            const snapshot = await tireApi.evidence(snapshotId, controller.signal);
            if (snapshot.id !== snapshotId || snapshot.source_id !== basis.source_id || snapshot.raw_hash !== basis.raw_hash) throw new Error("适用性来源原文与此侧冻结快照或哈希不一致，未显示该记录。");
            if (!globalThis.crypto?.subtle) throw new Error("当前环境无法核验来源原文的 SHA-256，未展示未核验内容。");
            const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(snapshot.body))), byte => byte.toString(16).padStart(2, "0")).join("");
            if (hash !== basis.raw_hash) throw new Error("来源原文内容与此侧冻结 SHA-256 不一致，未展示该记录。");
            value = { kind: "snapshot", value: snapshot, side: previous ? "before" : "after" };
          } else value = { kind: "governance", value: original };
        } else if (sourceSnapshot) {
          const binding = original.record.binding;
          const basis = isRecord(binding) ? (previous ? binding.before : binding.after) : null;
          const snapshotId = previous ? evidence.previous_snapshot_id : evidence.snapshot_id;
          if (evidence.kind !== "tire_catalog_revision" || !snapshotId || !isRecord(basis)
            || basis.snapshot_id !== snapshotId || typeof basis.raw_hash !== "string" || !/^[a-f0-9]{64}$/.test(basis.raw_hash)
            || typeof basis.source_id !== "string" || basis.source_id !== evidence.source_id
            || typeof basis.query_key !== "string" || basis.query_key !== original.record.query_key
            || basis.source_id !== original.record.source_id) throw new Error("目录快照的冻结范围或原文哈希不完整，未改读其他快照。");
          const snapshot = await tireApi.evidence(snapshotId, controller.signal);
          if (snapshot.id !== snapshotId || snapshot.source_id !== basis.source_id || snapshot.raw_hash !== basis.raw_hash) throw new Error("目录原文与冻结的快照 ID、来源或哈希不一致，未展示该记录。");
          if (!globalThis.crypto?.subtle) throw new Error("当前环境无法核验目录原文的 SHA-256，未展示未核验内容。");
          const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(snapshot.body))), byte => byte.toString(16).padStart(2, "0")).join("");
          if (hash !== basis.raw_hash) throw new Error("目录原文内容与冻结 SHA-256 不一致，未展示该记录。");
          value = { kind: "snapshot", value: snapshot, side: previous ? "before" : "after" };
        } else value = { kind: "governance", value: original };
      } else if (evidence.kind === "vehicle_snapshot") {
        const snapshotId = previous ? evidence.previous_snapshot_id : evidence.snapshot_id;
        if (!snapshotId) throw new Error("冻结绑定缺少快照 ID，无法读取原始记录。");
        if (current()) setVehicleSelection({ id: snapshotId, previous, revision: ++vehicleReadRevision.current });
        return;
      } else if (evidence.kind === "tire_change") {
        const snapshotId = previous ? evidence.previous_snapshot_id : evidence.snapshot_id;
        if (!snapshotId) throw new Error("冻结绑定缺少快照 ID，无法读取原始记录。");
        const snapshot = await tireApi.evidence(snapshotId, controller.signal);
        if (snapshot.id !== snapshotId || (evidence.source_id !== null && snapshot.source_id !== evidence.source_id)) throw new Error("返回快照与冻结绑定不一致，未展示其他快照。");
        if (!previous && evidence.fingerprint !== null && snapshot.raw_hash !== evidence.fingerprint) throw new Error("快照原文哈希与冻结绑定不一致，未展示该记录。");
        value = { kind: "snapshot", value: snapshot, side: previous ? "before" : "after" };
      } else throw new Error("尚不支持读取此证据类别，未改读其他记录。");
      if (current()) { setResult(value); if (derivedRecord) setApplicability(derivedRecord); }
    } catch (cause) { if (current()) setError(errorText(cause)); }
    finally { if (current()) setLoading(false); }
  }
  return <section className="interest-original-record">
    <p>从本地历史接口重新读取此绑定版本，以上冻结事件仍是当时匹配的依据。读取失败不会换用当前记录。</p>
    <div className="variant-actions">
      <button type="button" className="secondary-button" disabled={loading} onClick={() => void read()}>{evidence.kind === "tire_source_quarantine" ? "重开本次隔离原文（未采纳）" : evidence.kind === "tire_source_quality_baseline" ? "重开当时采纳基线原文" : "按绑定版本重开原始记录"}</button>
      {evidence.previous_snapshot_id && (evidence.kind === "tire_change" || evidence.kind === "vehicle_snapshot") ? <button type="button" className="text-button" disabled={loading} onClick={() => void read(true)}>重开变化前快照原文</button> : null}
      {evidence.kind === "tire_catalog_revision" ? <>
        {evidence.previous_snapshot_id ? <button type="button" className="text-button" disabled={loading} onClick={() => void read(true, true)}>重开目录变化前完整快照原文</button> : null}
        <button type="button" className="text-button" disabled={loading} onClick={() => void read(false, true)}>重开目录变化后完整快照原文</button>
      </> : null}
      {evidence.kind === "tire_curation_applicability_event" ? <>
        <button type="button" className="text-button" disabled={loading || !applicability || !completeApplicabilityBasis(applicability.binding.before)} onClick={() => void read(true, true)}>重开适用性变化前完整来源原文</button>
        <button type="button" className="text-button" disabled={loading || !applicability || !completeApplicabilityBasis(applicability.binding.after)} onClick={() => void read(false, true)}>重开适用性变化后完整来源原文</button>
      </> : null}
    </div>
    {evidence.kind === "tire_catalog_revision" ? <p>目录原文按冻结快照和原文 SHA-256 核对。缺席侧展示当时完整结果，不补造轮胎成员；若为首次本地目录结果，则没有变化前快照。</p> : null}
    {evidence.kind === "tire_curation_applicability_event" ? <p>先重开派生原行，可按每项原 ID 重开原人工决定。两侧来源原文分别核对，完整依据载入后才能重开原文；历史证明缺口明确保留。查询范围与实际事实／快照成员版本不要求相同，不以旧观察时间代替本次事实采纳时间。</p> : null}
    {applicability ? <ApplicabilitySummary record={applicability} busy={loading} onManual={item => void read(false, false, item)} /> : null}
    {loading ? <><p role="status">正在读取指定历史记录…</p><button type="button" className="text-button" onClick={() => { request.current?.abort(); setLoading(false); setResult(null); }}>取消读取历史记录</button></> : null}
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    {vehicleSelection ? <div><h4>{vehicleSelection.previous ? "变化前" : "变化后"}指定车型快照原件</h4><RawEvidenceV2View reader={vehicleReader} /></div> : null}
    {result !== null ? <div><h4>重新读取的原始历史记录</h4>{result.kind === "snapshot" ? <><details><summary>快照元数据</summary><pre>{JSON.stringify({ ...result.value, body: undefined }, null, 2)}</pre></details><h4>{result.side === "baseline" ? "当时采纳基线原文" : `${result.side === "before" ? "变化前" : "变化后"}指定快照原文`}</h4><pre>{result.value.body}</pre></> : result.kind === "quarantine" ? <><p>本次隔离原文 · 未采纳 · 本地历史。仅核对此次查询的原始观察，候选未成为参数事实。</p><p>隔离 {result.value.id} · 查询 {result.value.query_id} · SHA-256 {result.value.raw_hash}</p><pre>{result.value.body}</pre></> : <pre>{JSON.stringify(result.value, null, 2)}</pre>}</div> : null}
  </section>;
}

/** The event contains the facts that were matched. Opening this never substitutes current facts. */
export function FrozenEvent({ item, abortGroup }: { item: FrozenInterestItem; abortGroup?: EvidenceAbortGroup }) {
  const notification = "interest_revision" in item ? item : null;
  const criteria = item.match.criteria;
  const quality = item.event.domain === "tire_source_quality";
  const qualityNotice = quality && notification ? notification : undefined;
  return <div className="interest-frozen-event">
    <p>{domains[item.event.domain]} · {actionLabel(item.event.domain, item.event.action)} · 状态 {stateLabel(item.event)} · 修订 #{item.event.revision} · {stamp(item.event.observed_at)}</p>
    {domainNotices[item.event.domain] ? <p>{domainNotices[item.event.domain]}</p> : null}
    {item.event.domain === "tire_curation_validity" ? <p>两侧 facts 表示当时有效值，source_facts 表示来源原值。字段缺席、null 和零分别保留；有效值相同也可能仅产生适用状态变化。</p> : null}
    <p>事件 {item.event.id} · 对象 {item.event.subject_id}</p>
    <p>判定：{item.match.state === "matched" ? "匹配" : item.match.state === "indeterminate" ? "无法判定，不产生新通知" : "不匹配"} · {quality ? "匹配依据：当时采纳基线的同一成员，不是本次候选" : `命中侧：${item.match.matched_sides.map(side => side === "before" ? "变化前" : "变化后").join("、") || "无"}`}</p>
    <ReasonList reasons={item.match.reasons} />
    <section aria-label="当时冻结的匹配条件"><h4>{notification ? `通知采用的兴趣原修订 #${notification.interest_revision}` : "本次历史预览的匹配条件"}</h4>{notification ? <p>{notification.interest_name} · 兴趣 {notification.interest_id}。下列条件随当时的匹配结果保存，不随兴趣后续修订变化。</p> : <p>下列条件是本次历史预览的输入，不会生成或补发通知。</p>}{criteria ? <><ConditionSummary conditions={criteria.conditions} /><p>当时变化字段：{criteria.changed_fields.length ? criteria.changed_fields.map(field => `${fields[field]}（${field}）`).join("、") : "不限"}</p><p>当时原始 metric key：{criteria.metric_keys.join("、") || "不限"}</p></> : <p role="status">这条历史记录未保存当时的匹配条件，无法补全；未使用当前兴趣设置代替。</p>}</section>
    <p>变化路径：{item.event.changed_paths.join("、") || "未记录"}</p>
    {item.match.policy_version === "source-quality-interest@1" ? <section aria-label="质量提醒冻结的订阅和匹配成员"><p>当时明确订阅采集状态异常：是。变化字段与测试指标为空；质量提醒不提供历史预览。</p><h4>当时匹配的采纳基线成员</h4>{item.match.matched_baseline_members.map(member => <p className="interest-hash" key={`${member.variant_id}:${member.structured_locator}`}>{member.variant_id} · {member.structured_locator} · 成员 SHA-256 {member.member_hash}</p>)}</section> : null}
    <div className="interest-facts"><section><h4>{quality ? "查询采集状态 · 非参数变化" : "变化前 · 冻结原记录"}</h4>{quality ? <p>本次更新未采纳。此事件不比较前后 SKU 事实，也不推断参数变化或 SKU 消失。</p> : item.event.before === null ? <p>没有前记录；首次本地观察不代表新发布。</p> : <pre>{JSON.stringify(item.event.before, null, 2)}</pre>}</section><section><h4>{quality ? "隔离观察与当时采纳基线 · 冻结记录" : "变化后 · 冻结原记录"}</h4><pre>{JSON.stringify(item.event.after, null, 2)}</pre></section></div>
    <p>下列每条绑定均随事件冻结。字段是否存在、原始值与身份版本以以上原记录为准。</p>
    {item.event.evidence.map((evidence, index) => <HistoricalEvidence key={`${evidence.kind}:${evidence.record_id}:${index}`} evidence={evidence} abortGroup={abortGroup} qualityNotice={qualityNotice} />)}
    <p className="interest-hash">事件 SHA-256：{item.event.event_hash}<br />匹配策略：{item.match.policy_version}</p>
  </div>;
}

function SourceQualityFrozenRegion({ item, onClose }: { item: InterestNotification; onClose: () => void }) {
  const auth = useWorkbenchAuth();
  const panel = useRef<HTMLElement>(null);
  const abortGroup = useRef(new Set<() => void>());
  const cancelReads = () => { for (const cancel of abortGroup.current) cancel(); };
  const close = () => { cancelReads(); onClose(); };
  useEffect(() => { panel.current?.focus(); panel.current?.scrollIntoView({ block: "start" }); return cancelReads; }, []);
  useLayoutEffect(() => {
    auth.ownerSignal.addEventListener("abort", close, { once: true });
    return () => { auth.ownerSignal.removeEventListener("abort", close); cancelReads(); };
  }, [auth.ownerSignal]);
  return <section ref={panel} tabIndex={-1} className="quarantine-panel interest-frozen-event" aria-label="来源质量通知冻结证据"><div className="panel-title"><h3>来源质量通知冻结证据 · 未采纳／本地历史</h3><button type="button" className="text-button" onClick={close}>关闭质量冻结证据</button></div><FrozenEvent item={item} abortGroup={abortGroup} /></section>;
}

function FrozenDialog({ item, onClose }: { item: FrozenInterestItem; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const abortGroup = useRef(new Set<() => void>());
  const close = () => { for (const cancel of abortGroup.current) cancel(); onClose(); };
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  return <dialog ref={dialog} className="fact-review-dialog interest-dialog" aria-label="冻结的兴趣变化证据" onCancel={event => { event.preventDefault(); event.stopPropagation(); close(); }}><div className="fact-review-heading"><h2>{item.event.label}</h2><button type="button" className="text-button" onClick={close}>关闭冻结证据</button></div><div className="fact-review-content"><FrozenEvent item={item} abortGroup={abortGroup} /></div></dialog>;
}

function ConditionEditor({ condition, index, vehicles, onChange, onRemove }: { condition: InterestCondition; index: number; vehicles: VehicleCandidate[]; onChange: (value: InterestCondition) => void; onRemove: () => void }) {
  return <fieldset className="interest-condition"><legend>条件组 {index + 1} · 与其他组同时满足（AND）</legend><div className="interest-condition-heading"><label><span>关注类别</span><select value={condition.kind} onChange={event => onChange(newCondition(event.target.value as InterestKind))}>{kinds.map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select></label><button type="button" className="text-button" onClick={onRemove}>删除条件组 {index + 1}</button></div><p>本组任一备选满足即可（OR）。需要多项技术同时成立时，分别添加技术条件组。</p>
    {condition.kind === "model" ? condition.values.map((value, valueIndex) => <div className="interest-alternative" key={valueIndex}><label><span>型号备选 {valueIndex + 1} 的品牌</span><input required value={value.brand} onChange={event => onChange({ ...condition, values: condition.values.map((old, i) => i === valueIndex ? { ...old, brand: event.target.value } : old) })} /></label><label><span>型号备选 {valueIndex + 1}</span><input required value={value.model} onChange={event => onChange({ ...condition, values: condition.values.map((old, i) => i === valueIndex ? { ...old, model: event.target.value } : old) })} /></label><button type="button" className="text-button" disabled={condition.values.length === 1} onClick={() => onChange({ ...condition, values: condition.values.filter((_, i) => i !== valueIndex) })}>删除备选 {valueIndex + 1}</button></div>)
      : condition.kind === "vehicle_fitment" ? condition.values.map((value, valueIndex) => <div className="interest-alternative interest-vehicle-alternative" key={valueIndex}><label><span>车型备选 {valueIndex + 1}</span><select required value={value.vehicle_id} onChange={event => onChange({ ...condition, values: condition.values.map((old, i) => i === valueIndex ? { vehicle_id: event.target.value } : old) })}><option value="">选择本地稳定车型 ID</option>{value.vehicle_id && !vehicles.some(vehicle => vehicle.id === value.vehicle_id) ? <option value={value.vehicle_id}>{value.vehicle_id}（目录待核对）</option> : null}{vehicles.map(vehicle => <option key={vehicle.id} value={vehicle.id}>{vehicle.manufacturer} · {vehicle.model} · {vehicle.generation} · {vehicle.model_year ?? "年款未知"} · {vehicle.id}</option>)}</select></label>{(["trim_id", "wheel_option_id"] as const).map(key => <label key={key}><span>{key === "trim_id" ? "配置 ID（可选）" : "轮毂选项 ID（可选）"}</span><input value={value[key] || ""} onChange={event => { const next = { ...value }; if (event.target.value) next[key] = event.target.value; else delete next[key]; onChange({ ...condition, values: condition.values.map((old, i) => i === valueIndex ? next : old) }); }} /></label>)}<label><span>车轴（可选）</span><select value={value.axle || ""} onChange={event => { const next = { ...value }; if (event.target.value) next.axle = event.target.value as "front" | "rear"; else delete next.axle; onChange({ ...condition, values: condition.values.map((old, i) => i === valueIndex ? next : old) }); }}><option value="">不限</option><option value="front">前轴</option><option value="rear">后轴</option></select></label><button type="button" className="text-button" disabled={condition.values.length === 1} onClick={() => onChange({ ...condition, values: condition.values.filter((_, i) => i !== valueIndex) })}>删除备选 {valueIndex + 1}</button></div>)
        : condition.values.map((value, valueIndex) => <div className="interest-alternative" key={valueIndex}><label><span>{kindLabel(condition.kind)}备选 {valueIndex + 1}</span><input required value={value} placeholder={condition.kind === "size" ? "245/40R20（R 与 ZR 不同）" : undefined} onChange={event => onChange({ ...condition, values: condition.values.map((old, i) => i === valueIndex ? event.target.value : old) })} /></label><button type="button" className="text-button" disabled={condition.values.length === 1} onClick={() => onChange({ ...condition, values: condition.values.filter((_, i) => i !== valueIndex) })}>删除备选 {valueIndex + 1}</button></div>)}
    <button type="button" className="secondary-button" disabled={condition.values.length >= 20} onClick={() => onChange(condition.kind === "model" ? { ...condition, values: [...condition.values, { brand: "", model: "" }] } : condition.kind === "vehicle_fitment" ? { ...condition, values: [...condition.values, { vehicle_id: "" }] } : { ...condition, values: [...condition.values, ""] })}>添加本组备选（OR）</button>
  </fieldset>;
}

function InterestEditor({ id, ownerEpoch, capabilities, vehicles, onSaved, onClose }: { id: string | null; ownerEpoch: number; capabilities: InterestCapabilities | null; vehicles: VehicleCandidate[]; onSaved: (record: InterestRecord) => void; onClose: () => void }) {
  const auth = useWorkbenchAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [data, setData] = useState<InterestDetail | null>(null);
  const [settings, setSettings] = useState<InterestSettings>(blankSettings);
  const [metricText, setMetricText] = useState("");
  const [conditionKeys, setConditionKeys] = useState([0]);
  const nextKey = useRef(1);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(!!id);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<InterestPreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [frozen, setFrozen] = useState<FrozenInterestItem | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const detailRead = useRef<AbortController | null>(null);
  const previewRequest = useRef<AbortController | null>(null);
  const previewGeneration = useRef(0);
  const currentOwner = () => auth.ready && !auth.ownerSignal.aborted && auth.isCurrentOwner(ownerEpoch);
  const current = (controller: AbortController) => !controller.signal.aborted && currentOwner();
  const qualityUnsupported = settings.source_quality_notifications === true && (settings.conditions.some(condition => !["brand", "model", "size", "oe", "technology"].includes(condition.kind)) || settings.metric_keys.length > 0 || settings.changed_fields.length > 0);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => { element?.close(); mutation.current?.abort(); previewRequest.current?.abort(); }; }, []);
  useLayoutEffect(() => {
    const abort = () => { detailRead.current?.abort(); mutation.current?.abort(); previewRequest.current?.abort(); previewGeneration.current++; };
    const cancel = () => { abort(); setFrozen(null); setPreview(null); setPreviewBusy(false); };
    auth.ownerSignal.addEventListener("abort", cancel, { once: true });
    return () => { auth.ownerSignal.removeEventListener("abort", cancel); abort(); };
  }, [auth.ownerSignal]);
  useEffect(() => {
    if (!id || !currentOwner()) return;
    const controller = new AbortController(); detailRead.current = controller; setLoading(true); setError(""); setStale(false); setData(null); setPreview(null);
    void tireApi.interest(id, controller.signal).then(value => { if (current(controller)) { setData(value); setSettings(settingsOf(value)); setMetricText(value.metric_keys.join("\n")); setConditionKeys(value.conditions.map(() => nextKey.current++)); } })
      .catch(cause => { if (current(controller)) setError(errorText(cause)); }).finally(() => { if (current(controller)) setLoading(false); });
    return () => { controller.abort(); if (detailRead.current === controller) detailRead.current = null; };
  }, [id, attempt, ownerEpoch, auth.ownerSignal, auth.isCurrentOwner]);
  function edit(value: InterestSettings) { previewRequest.current?.abort(); previewGeneration.current++; setPreview(null); setPreviewBusy(false); setPreviewError(""); setFrozen(null); setSettings(value); }
  async function save() {
    if (mutation.current || stale || data?.archived || (id && !data) || !currentOwner()) return;
    if (qualityUnsupported) { setError("采集状态异常提醒仅支持品牌、型号、尺寸、OE 与技术条件，变化字段和测试指标须留空；原条件已保留，请手动调整或取消订阅。"); return; }
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError("");
    try { const value = id ? await tireApi.updateInterest(id, data!.revision, settings, controller.signal) : await tireApi.createInterest(settings, controller.signal); if (current(controller)) onSaved(value); }
    catch (cause) { if (current(controller)) { setError(errorText(cause)); if (cause instanceof ApiError && cause.status === 409) setStale(true); } }
    finally { if (mutation.current === controller) mutation.current = null; if (current(controller)) setBusy(false); }
  }
  async function runPreview(offset = 0) {
    if (previewBusy || !currentOwner()) return;
    previewRequest.current?.abort(); const controller = new AbortController(); previewRequest.current = controller;
    const generation = ++previewGeneration.current; setPreviewBusy(true); setPreviewError(""); if (!offset) setPreview(null);
    const isCurrent = () => current(controller) && previewGeneration.current === generation;
    try { const value = await tireApi.previewInterests({ conditions: settings.conditions, metric_keys: settings.metric_keys, changed_fields: settings.changed_fields }, controller.signal, offset); if (isCurrent()) setPreview(old => offset && old ? { ...value, items: [...new Map([...old.items, ...value.items].map(item => [item.event.id, item])).values()], scanned_count: old.scanned_count + value.scanned_count, matched_count: old.matched_count + value.matched_count, indeterminate_count: old.indeterminate_count + value.indeterminate_count } : value); }
    catch (cause) { if (isCurrent()) setPreviewError(errorText(cause)); }
    finally { if (isCurrent()) setPreviewBusy(false); }
  }
  const locked = !currentOwner() || busy || loading || stale || !!data?.archived;
  return <dialog ref={dialog} className="fact-review-dialog interest-dialog" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); event.stopPropagation(); if (!busy) onClose(); }}><div className="fact-review-heading"><h2 id={titleId}>{id ? "编辑兴趣与修订历史" : "新建兴趣关注"}</h2><button type="button" className="text-button" disabled={busy} onClick={onClose}>关闭兴趣编辑</button></div><div className="fact-review-content">
    <p className="review-boundary">本人私有。每组内备选为 OR，各组之间为 AND；所有条件须在同一证据对象上成立。精确文本不推断别名、后继型号或 OE 认证。尺寸 R / ZR 分别保存。</p>
    {error ? <p className="inline-error" role="alert">{error}{id ? <button type="button" className="text-button" disabled={busy} onClick={() => { previewRequest.current?.abort(); previewGeneration.current++; setAttempt(value => value + 1); }}>重新载入兴趣</button> : null}</p> : null}
    {loading ? <p role="status">正在读取兴趣…</p> : id && !data ? null : <form className="review-form interest-form" onSubmit={event => { event.preventDefault(); void save(); }}><fieldset disabled={locked} className="interest-settings">
      <label><span>兴趣名称</span><input required maxLength={120} value={settings.name} onChange={event => edit({ ...settings, name: event.target.value })} /></label>
      {settings.conditions.map((condition, index) => <ConditionEditor key={conditionKeys[index]} condition={condition} index={index} vehicles={vehicles} onChange={value => edit({ ...settings, conditions: settings.conditions.map((old, i) => i === index ? value : old) })} onRemove={() => { setConditionKeys(old => old.filter((_, i) => i !== index)); edit({ ...settings, conditions: settings.conditions.filter((_, i) => i !== index) }); }} />)}
      <button type="button" className="secondary-button" disabled={settings.conditions.length >= 8} onClick={() => { setConditionKeys(old => [...old, nextKey.current++]); edit({ ...settings, conditions: [...settings.conditions, newCondition("brand")] }); }}>添加条件组（AND）</button>
      {!settings.conditions.length ? <p role="alert">至少添加一个条件组。</p> : null}
      <details><summary>限制变化字段与原始测试指标</summary><p>留空表示不限。字段只筛实际变化路径；原始 metric key 每行一个，不根据“湿地”等显示标签推断。UTQG 耐磨、牵引、耐热须分别选择。</p><fieldset className="interest-field-filters"><legend>变化字段（可多选，OR）</legend>{(capabilities?.changed_fields || Object.keys(fields) as InterestChangedField[]).map(field => <label className="review-checkbox" key={field}><input type="checkbox" checked={settings.changed_fields.includes(field)} onChange={event => edit({ ...settings, changed_fields: event.target.checked ? [...settings.changed_fields, field] : settings.changed_fields.filter(old => old !== field) })} />{fields[field]} · <code>{field}</code></label>)}</fieldset><label><span>原始测试 metric key（每行一个，最多 24 个）</span><textarea value={metricText} onChange={event => { setMetricText(event.target.value); edit({ ...settings, metric_keys: event.target.value.split("\n").filter(value => value.length > 0) }); }} /></label></details>
      <label className="review-checkbox"><input type="checkbox" checked={settings.enabled} onChange={event => edit({ ...settings, enabled: event.target.checked })} />启用本人兴趣的新事件通知</label>
      <label className="review-checkbox"><input type="checkbox" checked={settings.source_quality_notifications === true} onChange={event => edit({ ...settings, source_quality_notifications: event.target.checked })} />相关查询的更新被质量隔离时也提醒</label>
      <p className="review-boundary">此项默认关闭。仅支持品牌、型号、尺寸、OE 与技术条件，且变化字段与测试指标须留空；相关性取自同一历史采纳基线成员，本次隔离候选未采纳。不提供质量历史预览或旧隔离补发，也不新增抓取任务。须同时启用本人兴趣才接收新的提醒。</p>
      {qualityUnsupported ? <p className="inline-error" role="alert">当前条件或筛选不支持质量提醒。原设置已保留，请手动调整，或取消“相关查询的更新被质量隔离时也提醒”。</p> : null}
    </fieldset><p className="review-boundary">启用后记录新采纳且明确匹配的本地事件；明确订阅质量提醒时，还可接收相关查询的新隔离状态。暂停期间不补发。历史预览不含质量隔离，也不会写入通知。保存兴趣不会启动抓取或创建监控任务。</p><div className="variant-actions"><button type="submit" className="primary-button" disabled={locked || qualityUnsupported || !settings.conditions.length}>{id ? "保存兴趣修订" : "保存兴趣"}</button><button type="button" className="secondary-button" disabled={locked || previewBusy || !settings.conditions.length} onClick={() => void runPreview()}>预览已录历史（不推送）</button></div></form>}
    {previewBusy ? <p role="status">正在扫描一页本地历史事件…</p> : null}{previewError ? <p role="alert" className="inline-error">{previewError}</p> : null}
    {preview ? <section className="interest-preview" aria-label="兴趣历史预览"><h3>历史预览 · 不产生通知</h3><p>已扫描 {preview.scanned_count} 条候选事件；匹配 {preview.matched_count} 条，无法判定 {preview.indeterminate_count} 条。本页不匹配项省略；分页按扫描事件推进，不代表已遍历全部历史。</p>{preview.items.length ? preview.items.map(item => <article className="interest-preview-item" key={item.event.id}><h4>{item.event.label} · {item.match.state === "matched" ? "匹配" : "无法判定"}</h4><p>{domains[item.event.domain]} · {stamp(item.event.observed_at)}</p><ReasonList reasons={item.match.reasons} /><button type="button" className="text-button" onClick={() => setFrozen(item)}>查看此条历史冻结证据</button></article>) : <p>本次扫描范围没有匹配或无法判定的事件。</p>}{preview.next_offset !== null ? <button type="button" className="secondary-button" disabled={previewBusy} onClick={() => void runPreview(preview.next_offset!)}>继续扫描历史事件</button> : <p>当前可扫描历史已结束。</p>}<Capabilities value={preview.capabilities} /></section> : null}
    {data ? <details className="interest-history"><summary>兴趣修订历史{data.history_truncated ? "（已截断）" : ""}</summary>{data.history.map(row => <article key={row.revision}><h4>#{row.revision} · {row.archived ? "已归档" : row.enabled ? "已启用" : "暂停"} · {stamp(row.created_at)}</h4><p>{row.name}</p><ConditionSummary conditions={row.conditions} /><p>字段：{row.changed_fields.join("、") || "不限"}；metric key：{row.metric_keys.join("、") || "不限"}</p><p>采集状态异常提醒：{row.source_quality_notifications === true ? "当时已明确订阅" : "当时未订阅"}</p><p className="interest-hash">{row.fingerprint}</p></article>)}</details> : null}
  </div>{frozen ? <FrozenDialog key={frozen.event.id} item={frozen} onClose={() => setFrozen(null)} /> : null}</dialog>;
}

export default function InterestCenter() {
  const auth = useWorkbenchAuth();
  if (!auth.ready || auth.ownerSignal.aborted || !auth.isCurrentOwner(auth.ownerEpoch)) return <section className="quarantine-panel interest-center"><div className="panel-title"><span>兴趣关注 · 本人私有</span></div><p className="quality-empty" role="status">正在确认当前账户归属，私人兴趣与通知暂不显示。</p><button type="button" className="text-button" onClick={() => void auth.refresh()}>重新确认账户归属</button></section>;
  return <PrivateInterestCenter key={auth.ownerEpoch} ownerEpoch={auth.ownerEpoch} />;
}

function PrivateInterestCenter({ ownerEpoch }: { ownerEpoch: number }) {
  const auth = useWorkbenchAuth();
  const [records, setRecords] = useState<InterestRecord[]>([]);
  const [notices, setNotices] = useState<InterestNotification[]>([]);
  const [vehicles, setVehicles] = useState<VehicleCandidate[]>([]);
  const [capabilities, setCapabilities] = useState<InterestCapabilities | null>(null);
  const [total, setTotal] = useState(0);
  const [noticeTotal, setNoticeTotal] = useState(0);
  const [archived, setArchived] = useState(false);
  const [unread, setUnread] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [editor, setEditor] = useState<string | null | undefined>(undefined);
  const [frozen, setFrozen] = useState<FrozenInterestItem | null>(null);
  const [error, setError] = useState("");
  const [noticeError, setNoticeError] = useState("");
  const [vehicleError, setVehicleError] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const paging = useRef(false);
  const currentOwner = () => auth.ready && !auth.ownerSignal.aborted && auth.isCurrentOwner(ownerEpoch);
  const current = (controller: AbortController) => !controller.signal.aborted && currentOwner();
  useEffect(() => () => mutation.current?.abort(), []);
  useLayoutEffect(() => {
    const abort = () => { request.current?.abort(); mutation.current?.abort(); };
    const cancel = () => { abort(); setFrozen(null); setStatus(""); };
    auth.ownerSignal.addEventListener("abort", cancel, { once: true });
    return () => { auth.ownerSignal.removeEventListener("abort", cancel); abort(); };
  }, [auth.ownerSignal]);
  useEffect(() => {
    if (!currentOwner()) return;
    const controller = new AbortController(); request.current = controller; setLoading(true); setError(""); setNoticeError(""); setVehicleError("");
    void Promise.allSettled([tireApi.interests(archived, controller.signal), tireApi.interestNotifications(unread, controller.signal), tireApi.vehicles(controller.signal)]).then(([interests, notifications, catalog]) => {
      if (!current(controller)) return;
      if (interests.status === "fulfilled") { setRecords(interests.value.items); setTotal(interests.value.total); setCapabilities(interests.value.capabilities); } else { setRecords([]); setError(errorText(interests.reason)); }
      if (notifications.status === "fulfilled") { setNotices(notifications.value.items); setNoticeTotal(notifications.value.total); } else { setNotices([]); setNoticeError(errorText(notifications.reason)); }
      if (catalog.status === "fulfilled") setVehicles(catalog.value.vehicles); else setVehicleError(errorText(catalog.reason));
      setLoading(false);
    });
    return () => controller.abort();
  }, [archived, unread, attempt, ownerEpoch, auth.ownerSignal, auth.isCurrentOwner]);
  async function more(kind: "interests" | "notices") {
    const controller = request.current; if (!controller || busy || loading || paging.current || !current(controller)) return;
    paging.current = true; setBusy(true);
    try { if (kind === "interests") { const result = await tireApi.interests(archived, controller.signal, records.length); if (current(controller)) { setRecords(old => [...new Map([...old, ...result.items].map(item => [item.id, item])).values()]); setTotal(result.total); } } else { const result = await tireApi.interestNotifications(unread, controller.signal, notices.length); if (current(controller)) { setNotices(old => [...new Map([...old, ...result.items].map(item => [item.id, item])).values()]); setNoticeTotal(result.total); } } }
    catch (cause) { if (current(controller)) (kind === "interests" ? setError : setNoticeError)(errorText(cause)); }
    finally { paging.current = false; if (current(controller)) setBusy(false); }
  }
  async function perform(action: (signal: AbortSignal) => Promise<unknown>, message: string) {
    if (mutation.current || busy || !currentOwner()) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError(""); setStatus("");
    try { await action(controller.signal); if (current(controller)) { setStatus(message); setAttempt(value => value + 1); } }
    catch (cause) { if (current(controller)) setError(errorText(cause)); }
    finally { if (mutation.current === controller) mutation.current = null; if (current(controller)) setBusy(false); }
  }
  async function reopen(notice: InterestNotification) {
    if (mutation.current || busy || !currentOwner()) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setNoticeError(""); setFrozen(null);
    try { const value = await tireApi.interestNotification(notice.id, controller.signal); if (!current(controller)) return; if (value.id !== notice.id) throw new Error("返回通知与指定本人记录不一致，未展示替代事件。"); setFrozen(value); }
    catch (cause) { if (current(controller)) setNoticeError(errorText(cause)); }
    finally { if (mutation.current === controller) mutation.current = null; if (current(controller)) setBusy(false); }
  }
  return <section className="quarantine-panel interest-center" aria-label="兴趣关注与私人通知"><div className="panel-title"><span>兴趣关注 · 本人私有</span><button type="button" className="text-button" disabled={loading || busy} onClick={() => setAttempt(value => value + 1)}>刷新兴趣与通知</button></div><div className="interest-intro"><p>关注品牌、型号、尺寸、OE、静音技术、测试机构与车型适配，也可组合条件。精确 SKU 继续在下方“关注规格”中管理。</p><p>默认匹配已采纳的本地事件；另行明确订阅后，可接收相关查询更新被质量隔离的状态提醒。相关性来自当时采纳基线，不确认本次候选。兴趣不创建监控任务，历史预览不补发通知。</p>{capabilities ? <Capabilities value={capabilities} /> : null}</div>
    {status ? <p className="quality-empty" role="status">{status}</p> : null}{error ? <p className="inline-error" role="alert">{error}</p> : null}{vehicleError ? <p className="inline-error" role="alert">车型目录读取失败：{vehicleError}；仍可管理其他类别。</p> : null}
    <div className="quarantine-filter"><label><span>兴趣范围</span><select disabled={busy} value={archived ? "archived" : "active"} onChange={event => setArchived(event.target.value === "archived")}><option value="active">使用中的兴趣</option><option value="archived">已归档兴趣</option></select></label><button type="button" className="secondary-button" disabled={busy} onClick={() => setEditor(null)}>新建兴趣关注</button></div>
    {loading ? <p className="quality-empty" role="status">正在读取本人的兴趣与通知…</p> : <>{records.length ? records.map(record => <article className="quarantine-item" key={record.id}><div className="quality-item-heading"><h3>{record.name}</h3><span className="tag quiet">{record.archived ? "已归档" : record.enabled ? "接收匹配的新事件" : "暂停"} · #{record.revision}</span></div><ConditionSummary conditions={record.conditions} /><p className="monitor-text">变化字段：{record.changed_fields.join("、") || "不限"} · 原始 metric key：{record.metric_keys.join("、") || "不限"}</p><p className="monitor-text">采集状态异常提醒：{record.source_quality_notifications === true ? "已明确订阅；相关性取自历史采纳基线，隔离候选未采纳" : "未订阅"}</p><div className="variant-actions"><button type="button" className="text-button" disabled={busy} onClick={() => setEditor(record.id)}>编辑、历史与预览</button>{!record.archived ? <button type="button" className="text-button" disabled={busy} onClick={() => void perform(signal => tireApi.updateInterest(record.id, record.revision, { ...settingsOf(record), enabled: !record.enabled }, signal), record.enabled ? "兴趣已暂停；暂停期间不补发。" : "兴趣已启用，等待新的明确匹配事件。")}>{record.enabled ? "暂停兴趣" : "启用兴趣"}</button> : null}<button type="button" className="text-button" disabled={busy} onClick={() => void perform(signal => tireApi.interestState(record.id, record.revision, record.archived ? "restore" : "archive", signal), record.archived ? "已恢复为暂停兴趣；需要另行启用。" : "兴趣已归档，已记录的私人通知保留。")}>{record.archived ? "恢复为暂停兴趣" : "归档兴趣"}</button></div></article>) : <p className="quality-empty">此范围暂无兴趣关注。</p>}{records.length < total ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void more("interests")}>加载更多兴趣</button> : null}
    <div className="panel-title"><span>私人兴趣通知 · {noticeTotal}</span><label className="review-checkbox"><input type="checkbox" checked={unread} disabled={busy} onChange={event => setUnread(event.target.checked)} />仅看未读兴趣通知</label></div><p className="quality-empty">下列是启用期间产生的新事件通知；通知保留当时兴趣修订与冻结证据。它们与历史预览、下方共享监控提醒分别保存。</p>{noticeError ? <p className="inline-error" role="alert">{noticeError}</p> : null}{notices.length ? notices.map(notice => <article className="quarantine-item" key={notice.id}><div className="quality-item-heading"><h3>{notice.interest_name} · {notice.event.label}</h3><span className="tag quiet">{notice.read_at ? "已读" : "未读"}</span></div><p className="monitor-text">{domains[notice.event.domain]} · 兴趣修订 #{notice.interest_revision} · 事件 {stamp(notice.event.observed_at)} · 通知 {stamp(notice.delivered_at)}</p><p className="review-boundary">{notice.event.domain === "tire_source_quality" ? "未采纳 · 本地历史。与你关注范围相关的查询，本次更新被隔离；相关性只来自当时采纳基线，不确认候选或 SKU 参数变化。" : null}</p><ReasonList reasons={notice.match.reasons} /><div className="variant-actions"><button type="button" className="text-button" disabled={busy} onClick={() => void reopen(notice)}>重开通知冻结证据</button><button type="button" className="text-button" disabled={busy} onClick={() => void perform(async signal => { const result = await tireApi.markInterestNotification(notice.id, !notice.read_at, signal); if (notice.event.domain === "tire_source_quality" && (result.id !== notice.id || (notice.read_at ? result.read_at !== null : !result.read_at || !Number.isFinite(Date.parse(result.read_at))))) throw new Error("已读状态返回与指定通知不一致，请刷新核对；未自动重写。"); }, notice.read_at ? "兴趣通知已标记为未读。" : "兴趣通知已标记为已读。")}>标记兴趣通知为{notice.read_at ? "未读" : "已读"}</button></div></article>) : <p className="quality-empty">暂无{unread ? "未读" : ""}私人兴趣通知。历史预览不会生成通知；质量隔离仅在明确订阅且同一采纳基线成员完整匹配时提醒，候选仍未采纳；无法判定时不推送。</p>}{notices.length < noticeTotal ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void more("notices")}>加载更多兴趣通知</button> : null}</>}
    {editor !== undefined ? <InterestEditor key={editor || "new-interest"} id={editor} ownerEpoch={ownerEpoch} capabilities={capabilities} vehicles={vehicles} onClose={() => setEditor(undefined)} onSaved={() => { setEditor(undefined); setStatus("兴趣已保存；历史预览不会补发通知。"); setAttempt(value => value + 1); }} /> : null}{frozen ? frozen.event.domain === "tire_source_quality" && "interest_revision" in frozen ? <SourceQualityFrozenRegion key={frozen.event.id} item={frozen} onClose={() => setFrozen(null)} /> : <FrozenDialog key={frozen.event.id} item={frozen} onClose={() => setFrozen(null)} /> : null}
  </section>;
}
