"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { ParserBundle, ParserDeployment, ParserEvaluation, ParserEvaluationCreate, ParserPage,
  ParserSignedAction, ParserTransition, RawCaptureEvidence, RawCaptureRecord, Source, GoldenSet, GoldenGate } from "@tire/domain-types";
import { DataTree, QualityMetrics, qualityLabels, qualityGroupLabels, queryScope, targetLabel } from "./reparse-review";

const stamp = (value?: string) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const short = (value: string) => `${value.slice(0, 12)}…`;
const stateLabels = { pending: "执行结果待确认", unknown: "执行结果未知", completed: "评估完成", failed: "评估失败" };
const actionLabels = { bootstrap: "初始化部署", activate: "激活已批准的包", pause: "暂停来源解析", resume: "恢复当前包", rollback: "回滚到历史包" };
const errorLabels: Record<string, string> = {
  golden_set_required: "本次未绑定人工审核冻结集，只能作为相对回归记录，不能用于新发布。",
  golden_assertions_failed: "Golden 精确断言存在差异，不能批准，也不能以署名豁免。",
  golden_coverage_inconclusive: "Golden 覆盖不足，不能证明零错误合并。",
  golden_distinct_cases_required: "至少需要两个不同 Golden SKU 才能检查独立性。",
  golden_set_stale: "冻结集已有新修订，当前评估不能用于新发布。",
  golden_set_revoked: "所绑定的冻结集已撤回，当前评估不能用于新发布。",
  golden_case_binding_changed: "集合中的预期或审核已变化，须重新冻结并评估。",
  golden_case_review_changed: "人工审核已变化或撤回，当前集合不能用于新发布。",
  golden_release_review_required: "此部署没有有效的 Golden 发布审批；首次信任初始化仍属未验证。",
  parser_deployment_revision_conflict: "部署修订已变化。重新读取当前部署后再次核对。",
  parser_review_revision_conflict: "审批修订已变化。重新读取评估与审批记录后再次核对。",
  parser_evaluation_stale: "评估所依据的部署已变化，不能继续用于新发布。",
  parser_evaluation_gate_failed: "评估存在阻断项，不能批准。",
  parser_release_approval_required: "没有匹配且仍有效的发布批准，未切换。",
  parser_reference_gap_acknowledgement_required: "缺少同原文正式参考，须明确核对这一缺口。",
  parser_bundle_not_registered: "代码包未登记，不能执行。",
  parser_bundle_missing: "封存包文件缺失，未使用其他代码替代。",
  parser_bundle_integrity_failed: "封存包完整性校验失败，未执行。",
  parser_bundle_environment_incompatible: "当前运行环境与封存包不兼容，未执行。",
  parser_bundle_policy_incompatible: "运行协议或资源策略不兼容，未执行。",
  parser_evaluation_integrity_failed: "评估完整性校验失败，未展示结果。",
  parser_deployment_bootstrap_required: "请先明确初始化此来源的活动部署。",
  parser_rollback_target_invalid: "回滚目标不是此来源可用的历史活动修订。",
  candidate_validation_failed: "候选结构、查询范围或身份未通过校验，不能批准发布。",
  capture_query_mismatch: "历史原文与冻结查询范围不一致，未执行。",
  capture_integrity_failed: "历史原文缺失或完整性校验失败，未使用其他正文替代。",
  parser_receipt_invalid: "执行回执不完整或无效，结果已拒收。",
  parser_receipt_mismatch: "执行回执与固定代码包或部署修订不匹配，结果已拒收。",
  parser_receipt_input_mismatch: "执行回执与冻结输入不匹配，结果已拒收。",
  idempotency_payload_mismatch: "请求标识已绑定其他操作，请保留标识并核对记录。",
};
const message = (error: unknown) => error instanceof ApiError && error.code
  ? errorLabels[error.code] || `操作未完成（${error.code}）。请核对记录。`
  : error instanceof Error ? error.message : "操作未完成，请核对记录。";
type Pending =
  { kind: "evaluation"; source: string; key: string; payload: ParserEvaluationCreate; id?: string } |
  { kind: "transition"; source: string; key: string; payload: ParserTransition } |
  { kind: "bootstrap"; source: string; key: string; payload: ParserSignedAction };
// Tab memory only. Closing a dialog cannot manufacture a new request identifier.
const attempts = new Map<string, Pending>();
let lastViewedSource = "";

function Pages({ label, offset, total, disabled, onChange }: {
  label: string; offset: number; total: number; disabled: boolean; onChange: (offset: number) => void;
}) {
  return <div className="reparse-pages"><button type="button" className="text-button" disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - 10))}>上一页{label}</button><span>共 {total} 条 · 第 {Math.floor(offset / 10) + 1} 页</span><button type="button" className="text-button" disabled={disabled || offset + 10 >= total} onClick={() => onChange(offset + 10)}>下一页{label}</button></div>;
}

const goldenStates: Record<GoldenGate["state"], string> = { unverified: "未验证", pending: "待完成", passed: "本冻结集通过", stale: "当前依据已失效", failed: "未通过", inconclusive: "覆盖不足，无法判定", not_applicable: "本轮不适用 · 召回相对回归" };
const recallRegression = (gate?: GoldenGate) => gate?.state === "not_applicable" && gate.applicable === false && gate.scope === "legacy_recall_regression";
const gateAllowsRelease = (gate?: GoldenGate) => gate?.state === "passed" || recallRegression(gate);
function GoldenEvidence({ gate }: { gate?: GoldenGate }) {
  const report = gate?.report;
  if (recallRegression(gate)) return <section className="review-boundary"><h4>Golden 不适用 · 召回相对回归</h4><p>本轮人工真值集只覆盖轮胎与车型。召回继续按既有质量门、参考缺口确认与发布审批核对，不宣称 Golden 通过或适用性已确认。</p></section>;
  return <section className="review-boundary"><h4>Golden 精确验收 · {gate ? goldenStates[gate.state] : "未绑定人工冻结集"}</h4>
    {gate?.set_id ? <p>集合 <code>{gate.set_id}</code> · 修订 #{gate.set_revision} · 指纹 <code>{gate.set_fingerprint}</code></p> : <p>此记录只有相对回归依据，不能替代人工真值，也不能批准新的部署变更。</p>}
    {report ? <><p>已完成 {report.completed_case_count}/{report.expected_case_count} 个样本 · {report.scope === "vehicle_structure" ? "车型、配置与轴位结构" : "精确轮胎 SKU 与字段"}</p>
      {report.scope !== "vehicle_structure" ? <p>独立 SKU 配对已检查 {report.checked_distinct_pairs}/{report.expected_distinct_pairs} · 错误合并 {report.wrong_merge_count === null ? "无法判定（不是 0 次）" : `${report.wrong_merge_count} 次`}</p> : <p>车型评估不提供轮胎零错合并结论。</p>}<DataTree label="集合精确比较与覆盖报告" value={report} /></> : null}
    {gate?.blockers?.length ? <ul>{gate.blockers.map(code => <li key={code}>{errorLabels[code] || code}</li>)}</ul> : null}
    <p>精确差异和缺失覆盖不能签署豁免。通过仅覆盖所列冻结样本；测试事件尚未支持，不代表完整生产真值集验收。</p>
  </section>;
}

function EvaluationEvidence({ value }: { value: ParserEvaluation }) {
  return <div className="parser-evaluation-evidence">
    <GoldenEvidence gate={value.golden_gate} />
    <dl className="quality-detail-meta"><div><dt>评估预留时间</dt><dd>{stamp(value.created_at)}</dd></div><div><dt>评估完成时间</dt><dd>{stamp(value.completion?.completed_at)}</dd></div><div><dt>依据的部署修订</dt><dd>#{value.deployment_revision}</dd></div><div><dt>历史候选</dt><dd>始终未采纳为事实</dd></div></dl>
    <details className="reparse-technical"><summary>完整代码包与评估指纹</summary><p>候选包 <code>{value.target_bundle_id}</code></p><p>对照包 <code>{value.control_bundle_id}</code></p><p>评估 <code>{value.id}</code></p><p>完成指纹 <code>{value.completion?.fingerprint || "尚未完成"}</code></p></details>
    {value.completion ? <>
      {value.completion.hard_blocks.length ? <div className="inline-error" role="status"><strong>发布质量门未通过，不能批准</strong><ul>{value.completion.hard_blocks.map((item, index) => <li key={`${item.capture_id}:${index}`}>{item.capture_id ? `收件 ${short(item.capture_id)}` : "集合检查"} · {qualityLabels[item.code] || errorLabels[item.code] || item.code} <code>{item.code}</code></li>)}</ul></div> : <p className="review-boundary">未触发相对质量阻断；{recallRegression(value.golden_gate) ? "召回发布仍须核对参考与独立审批。" : "发布还必须满足上方 Golden 精确验收与独立审批。"}</p>}
      {value.completion.reference_gaps.length ? <p className="inline-error">{value.completion.reference_gaps.length} 份样本缺少同原文正式参考。相对回归使用同原文的对照 Parser；对照失败时也会明确标记。此参考缺口与上方 Golden 断言分别核对。</p> : null}
      {(value.completion.results || []).map(sample => {
        const binding = value.bindings?.find(item => item.input.capture_id === sample.capture_id);
        return <section key={sample.capture_id} className="parser-sample-result"><h4>样本 {short(sample.capture_id)}</h4><p>原文观察 {stamp(binding?.input.observed_at)} · {binding?.input.byte_count.toLocaleString("zh-CN")} 字节</p>{binding ? <p>{targetLabel(binding.input.target_kind, binding.input.query)} · {queryScope(binding.input.query) || "查询范围见冻结原文信息"}</p> : null}{binding?.input.target_kind === "recall" ? <p className="review-boundary">这是未采纳的{targetLabel(binding.input.target_kind, binding.input.query)}解析结果，适用性未评估（not_assessed）。公告、关联产品、附件与安全字段分别核对；空响应不表示风险解除。</p> : null}<p>参考：{sample.reference_kind === "accepted_same_raw" ? "这份原文当时产生的已采纳快照" : sample.reference_kind === "control_same_raw" ? "同一原文的对照 Parser 输出（非正式真值）" : "无可用参考"}</p>
          {sample.candidate_error ? <p className="inline-error">候选失败：{errorLabels[sample.candidate_error] || sample.candidate_error}</p> : null}{sample.control_error ? <p className="inline-error">对照失败：{errorLabels[sample.control_error] || sample.control_error}</p> : null}
          {sample.quality ? <><QualityMetrics value={sample.quality} label="此样本质量分母" />{Object.entries(sample.quality.groups || {}).map(([name, metrics]) => <QualityMetrics key={name} value={metrics} label={`分组 ${qualityGroupLabels[name] || name}`} />)}</> : <p>没有质量比较结果，不能表示通过。</p>}
          {sample.diff ? <p>新增 {sample.diff.added_row_keys.length} · 移除 {sample.diff.removed_row_keys.length} · 变化字段 {sample.diff.total_changed_fields} · 身份变化 {sample.diff.identity_changed_row_keys.length}{sample.diff.truncated ? " · 差异已达展示上限，须分别核对完整候选和参考" : ""}</p> : null}
          {binding?.golden ? <><DataTree label="此样本冻结的人工预期、审核与原文绑定" value={binding.golden.case} />{sample.golden_report ? <><p>Golden 字段检查：{sample.golden_report.state === "passed" ? "本样本字段匹配（集合独立性结论见上方）" : "存在精确差异"} · 差异 {sample.golden_report.failure_count} 处{sample.golden_report.failures_truncated ? " · 差异明细达到上限，请对照完整预期与候选" : ""}</p><DataTree label="精确字段差异：预期 / 实际 / 缺失" value={sample.golden_report.failures} /><DataTree label="完整样本 Golden 检查报告" value={sample.golden_report} /></> : <p className="inline-error">此样本没有完成 Golden 检查，不能算作通过。</p>}</> : null}
          <DataTree label="冻结原文信息与正式参考" value={binding} /><DataTree label="未采纳的候选输出" value={sample.candidate} /><DataTree label="同原文的对照输出" value={sample.control} /><DataTree label="质量与字段差异" value={{ quality: sample.quality, diff: sample.diff }} /><DataTree label="候选与对照执行回执" value={{ candidate: sample.candidate_receipt, control: sample.control_receipt }} />
        </section>;
      })}
    </> : <p className="review-boundary">尚无完成回执。重新读取只跟踪此次任务，不会重新执行；未知结果不能批准或激活。</p>}
    <details className="report-history"><summary>审批历史（{value.reviews?.length || 0}{value.reviews_truncated ? "+，只显示最近100条" : "条"}）</summary>{value.reviews?.map(review => <article key={review.id}><h4>#{review.revision} · {review.action === "approve" ? "批准发布" : "不批准 / 撤回批准"}</h4><p>{stamp(review.created_at)} · {review.operator}（本地自报）</p><p className="draft-original">{review.reason}</p><p>{review.acknowledged_reference_gaps ? "已明确确认参考缺口" : "未确认参考缺口"}</p></article>)}</details>
  </div>;
}

function ReleaseDialog({ sources, onClose }: { sources: Source[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const focusTarget = useRef<HTMLHeadingElement>(null);
  const operation = useRef<AbortController | null>(null);
  // An installed source can be disabled independently of its Parser deployment;
  // keep its release history reachable while excluding unimplemented sources.
  const choices = [...sources.filter(item => !!item.parser_version && item.id !== "xiaomi-cn-vehicles"), { id: "xiaomi-cn-vehicles", name: "小米汽车 · 官方配置" }];
  const [source, setSource] = useState(() => choices.find(item => item.id === lastViewedSource)?.id || choices[0]?.id || "");
  const [refresh, setRefresh] = useState(0);
  const [head, setHead] = useState<ParserDeployment | null>(null);
  const [bundles, setBundles] = useState<ParserPage<ParserBundle> | null>(null);
  const [bundleOffset, setBundleOffset] = useState(0);
  const [bundle, setBundle] = useState<ParserBundle | null>(null);
  const [captures, setCaptures] = useState<ParserPage<RawCaptureRecord> | null>(null);
  const [captureOffset, setCaptureOffset] = useState(0);
  const [samples, setSamples] = useState<RawCaptureRecord[]>([]);
  const [evaluationMode, setEvaluationMode] = useState<"golden" | "relative">(() => sources.find(item => item.id === source)?.target_kind === "recall" ? "relative" : "golden");
  const [goldenSets, setGoldenSets] = useState<ParserPage<GoldenSet> | null>(null);
  const [goldenOffset, setGoldenOffset] = useState(0);
  const [goldenId, setGoldenId] = useState("");
  const [goldenSet, setGoldenSet] = useState<GoldenSet | null>(null);
  const [rawId, setRawId] = useState("");
  const [raw, setRaw] = useState<RawCaptureEvidence | null>(null);
  const [evaluations, setEvaluations] = useState<ParserPage<ParserEvaluation> | null>(null);
  const [evaluationOffset, setEvaluationOffset] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [detailRefresh, setDetailRefresh] = useState(0);
  const [evaluation, setEvaluation] = useState<ParserEvaluation | null>(null);
  const [readErrors, setReadErrors] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(attempts.get(source) || null);
  const pendingRef = useRef(pending);
  const [evaluateConfirmed, setEvaluateConfirmed] = useState(false);
  const [reviewStale, setReviewStale] = useState(false);
  const [deploymentStale, setDeploymentStale] = useState(false);
  const [reviewAction, setReviewAction] = useState<"approve" | "reject">("approve");
  const [reviewOperator, setReviewOperator] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [gapConfirmed, setGapConfirmed] = useState(false);
  const [action, setAction] = useState<ParserTransition["action"]>("pause");
  const [rollbackRevision, setRollbackRevision] = useState(0);
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [changeConfirmed, setChangeConfirmed] = useState(false);
  const locked = busy || !!pending;
  const descriptor = bundle?.parsers.find(item => item.source_id === source);
  const currentEvaluation = !!evaluation && !!head && evaluation.deployment_revision === head.revision && !evaluation.deployment_stale;
  const canApprove = !!evaluation?.can_approve && currentEvaluation && gateAllowsRelease(evaluation?.golden_gate);
  const canActivate = canApprove && evaluation?.latest_review?.action === "approve"
    && evaluation.latest_review.completion_fingerprint === evaluation.completion?.fingerprint;
  const rollback = head?.history.find(item => item.revision === rollbackRevision && item.state === "active" && item.revision < head.revision);
  const canTransition = !!head?.revision && !deploymentStale && (action === "activate" ? canActivate
    : action === "rollback" ? !!rollback && gateAllowsRelease(rollback.golden_gate)
    : action === "pause" ? head.state === "active" : head.state === "paused" && gateAllowsRelease(head.golden_gate));
  const recallSource = sources.find(item => item.id === source)?.target_kind === "recall";
  const evaluationCaptures = evaluationMode === "golden" ? goldenSet?.capture_ids || [] : samples.map(item => item.id);
  const readySamples = evaluationCaptures.length >= 1 && evaluationCaptures.length <= 3
    && (evaluationMode === "relative" || (!!goldenSet?.eligible && goldenSet.state === "frozen"));

  function loadError(key: string, value = "") { setReadErrors(current => ({ ...current, [key]: value })); }
  function remember(value: Pending | null) {
    pendingRef.current = value; setPending(value);
    if (value) attempts.set(value.source, value); else attempts.delete(source);
  }
  function reload() { setActionError(""); setRefresh(value => value + 1); setDetailRefresh(value => value + 1); setChangeConfirmed(false); setEvaluateConfirmed(false); }
  function acceptEvaluation(value: ParserEvaluation, expectedId?: string) {
    if (value.source_id !== source || value.accepted_as_facts !== false || (expectedId && value.id !== expectedId)) throw new Error("评估返回范围不匹配，未展示。");
    setEvaluation(value); setReviewStale(false); setReviewConfirmed(false); setGapConfirmed(false);
    const active = pendingRef.current;
    if (active?.kind === "evaluation" && active.id === value.id && ["completed", "failed"].includes(value.state)) remember(null);
  }
  useEffect(() => {
    const node = dialog.current; const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { operation.current?.abort(); node?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setHead(null); loadError("head");
    void tireApi.parserDeployment(source, controller.signal).then(value => {
      if (!controller.signal.aborted) { if (value.source_id !== source) throw new Error("部署来源不匹配，未展示。"); setHead(value); setDeploymentStale(false); }
    }).catch(error => { if (!controller.signal.aborted) loadError("head", message(error)); });
    return () => controller.abort();
  }, [source, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setBundles(null); loadError("bundles");
    void tireApi.parserBundles(controller.signal, bundleOffset).then(value => { if (!controller.signal.aborted) setBundles(value); })
      .catch(error => { if (!controller.signal.aborted) loadError("bundles", message(error)); });
    return () => controller.abort();
  }, [bundleOffset, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setCaptures(null); loadError("captures");
    void tireApi.parserCaptures(source, controller.signal, captureOffset).then(value => {
      if (!controller.signal.aborted) { if (value.items.some(item => item.source_id !== source)) throw new Error("原文来源不匹配，未展示。"); setCaptures(value); }
    }).catch(error => { if (!controller.signal.aborted) loadError("captures", message(error)); });
    return () => controller.abort();
  }, [source, captureOffset, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setEvaluations(null); loadError("list");
    void tireApi.parserEvaluations(source, controller.signal, evaluationOffset).then(value => {
      if (!controller.signal.aborted) { if (value.items.some(item => item.source_id !== source)) throw new Error("评估列表来源不匹配，未展示。"); setEvaluations(value); }
    }).catch(error => { if (!controller.signal.aborted) loadError("list", message(error)); });
    return () => controller.abort();
  }, [source, evaluationOffset, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setGoldenSets(null); loadError("goldenList");
    void tireApi.goldenSets(source, controller.signal, goldenOffset).then(value => {
      if (!controller.signal.aborted) { if (value.items.some(item => item.source_id !== source)) throw new Error("Golden 集合来源不匹配，未展示。"); setGoldenSets(value); }
    }).catch(error => { if (!controller.signal.aborted) loadError("goldenList", message(error)); });
    return () => controller.abort();
  }, [source, goldenOffset, refresh]);
  useEffect(() => {
    setGoldenSet(null); setEvaluateConfirmed(false); loadError("goldenDetail");
    if (!goldenId) return;
    const controller = new AbortController();
    void tireApi.goldenSet(goldenId, controller.signal).then(value => {
      if (!controller.signal.aborted) { if (value.source_id !== source || value.id !== goldenId) throw new Error("Golden 集合范围不匹配，未展示。"); setGoldenSet(value); }
    }).catch(error => { if (!controller.signal.aborted) loadError("goldenDetail", message(error)); });
    return () => controller.abort();
  }, [source, goldenId, refresh]);
  useEffect(() => {
    setEvaluation(null); loadError("detail"); setReviewConfirmed(false); setGapConfirmed(false);
    if (!selectedId) return;
    const controller = new AbortController();
    void tireApi.parserEvaluation(selectedId, controller.signal).then(value => {
      if (!controller.signal.aborted) { acceptEvaluation(value, selectedId); focusTarget.current?.focus({ preventScroll: true }); }
    }).catch(error => { if (!controller.signal.aborted) loadError("detail", message(error)); });
    return () => controller.abort();
    // Requests are bound to the source/ID current when this effect is created.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, selectedId, detailRefresh]);
  useEffect(() => {
    setRaw(null); loadError("raw");
    if (!rawId) return;
    const controller = new AbortController();
    void tireApi.captureEvidence(rawId, controller.signal).then(value => {
      if (!controller.signal.aborted) { if (value.id !== rawId || value.source_id !== source) throw new Error("原文范围不匹配，未展示。"); setRaw(value); }
    }).catch(error => { if (!controller.signal.aborted) loadError("raw", message(error)); });
    return () => controller.abort();
  }, [source, rawId]);
  useEffect(() => { setEvaluateConfirmed(false); setChangeConfirmed(false); }, [head?.revision, bundle?.id, samples, action, rollbackRevision, evaluation?.review_revision, evaluationMode, goldenSet?.fingerprint]);

  function chooseSource(value: string) {
    lastViewedSource = value;
    setSource(value); setHead(null); setBundle(null); setSamples([]); setRawId(""); setRaw(null);
    setGoldenId(""); setGoldenSet(null); setGoldenOffset(0); setEvaluationMode(sources.find(item => item.id === value)?.target_kind === "recall" ? "relative" : "golden");
    setCaptureOffset(0); setEvaluationOffset(0); setSelectedId(""); setEvaluation(null); setReviewStale(false); setDeploymentStale(false);
    setEvaluateConfirmed(false); setChangeConfirmed(false); setActionError(""); setNotice(""); setReason("");
    const active = attempts.get(value) || null; pendingRef.current = active; setPending(active);
    if (active?.kind === "evaluation" && active.id) setSelectedId(active.id);
  }
  async function perform(value: Pending) {
    if (operation.current || value.source !== source) return;
    remember(value); const controller = new AbortController(); operation.current = controller; setBusy(true); setActionError(""); setNotice("");
    try {
      if (value.kind === "evaluation") {
        const result = value.id ? await tireApi.parserEvaluation(value.id, controller.signal) : await tireApi.evaluateParser(value.payload, value.key, controller.signal);
        if (controller.signal.aborted) return;
        if (result.source_id !== source || result.target_bundle_id !== value.payload.target_bundle_id
          || result.deployment_revision !== value.payload.expected_deployment_revision
          || JSON.stringify(result.capture_ids) !== JSON.stringify(value.payload.capture_ids)
          || (value.payload.golden_set_id && (result.golden_gate?.set_id !== value.payload.golden_set_id
            || result.golden_gate.set_revision !== value.payload.expected_golden_set_revision
            || result.golden_gate.set_fingerprint !== value.payload.golden_set_fingerprint))) throw new Error("评估结果与固定请求不匹配，请保留请求标识并核对。");
        remember({ ...value, id: result.id }); acceptEvaluation(result, value.id); setSelectedId(result.id); setEvaluationOffset(0);
        setNotice("此次评估已记录；没有访问来源或采纳事实。");
      } else {
        const result = value.kind === "bootstrap" ? await tireApi.bootstrapParser(source, value.payload, controller.signal)
          : await tireApi.transitionParser(source, value.payload, value.key, controller.signal);
        if (controller.signal.aborted) return;
        if (result.source_id !== source || (value.kind === "transition" && (result.revision !== value.payload.expected_revision + 1 || result.action !== value.payload.action))) throw new Error("部署返回结果与固定操作不匹配，请保留请求标识并核对。");
        remember(null); setReason(""); setNotice(`已核对部署修订 #${result.revision}。正在重新读取当前状态；没有访问来源或采纳历史候选。`);
      }
      reload();
    } catch (error) {
      if (!controller.signal.aborted) {
        setActionError(message(error));
        // These responses are definite rejections, not transport uncertainty.
        if (error instanceof ApiError && ([404, 409, 422].includes(error.status) || error.code?.startsWith("parser_bundle_"))) {
          if (error.code !== "idempotency_payload_mismatch") remember(null);
          setChangeConfirmed(false); setEvaluateConfirmed(false);
          if (error.status === 409) { setDeploymentStale(true); setReviewStale(true); }
        }
      }
    } finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  async function review() {
    if (!evaluation?.completion || locked || operation.current || reviewStale || !reviewConfirmed || !reviewOperator.trim() || !reviewReason.trim()) return;
    if (reviewAction === "approve" && (!canApprove || (evaluation.completion.reference_gaps.length > 0 && !gapConfirmed))) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setActionError(""); setNotice("");
    try {
      const result = await tireApi.reviewParser(evaluation.id, { mode: "history", expected_revision: evaluation.review_revision,
        completion_fingerprint: evaluation.completion.fingerprint, action: reviewAction, acknowledged: true,
        acknowledge_reference_gaps: gapConfirmed, operator: reviewOperator.trim(), reason: reviewReason.trim() }, controller.signal);
      if (!controller.signal.aborted) { acceptEvaluation(result, evaluation.id); setReviewReason(""); setNotice("审批已追加，活动部署没有改变。激活仍需单独核对和确认。"); setRefresh(value => value + 1); }
    } catch (error) { if (!controller.signal.aborted) { setActionError(message(error)); setReviewStale(true); } }
    finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function createEvaluation() {
    if (!head?.revision || !bundle || !descriptor || !readySamples || !evaluateConfirmed || locked) return;
    void perform({ kind: "evaluation", source, key: crypto.randomUUID(), payload: { mode: "history", source_id: source,
      target_bundle_id: bundle.id, capture_ids: evaluationCaptures, expected_deployment_revision: head.revision,
      ...(evaluationMode === "golden" && goldenSet ? { golden_set_id: goldenSet.id, expected_golden_set_revision: goldenSet.revision, golden_set_fingerprint: goldenSet.fingerprint } : {}) } });
  }
  function changeDeployment() {
    if (!head || locked || !changeConfirmed || !operator.trim() || !reason.trim()) return;
    const signed = { operator: operator.trim(), reason: reason.trim() };
    if (head.revision === 0) { void perform({ kind: "bootstrap", source, key: crypto.randomUUID(), payload: signed }); return; }
    if (!canTransition) return;
    const base = { ...signed, expected_revision: head.revision };
    const payload: ParserTransition = action === "activate" ? { ...base, action, target_bundle_id: evaluation!.target_bundle_id,
      evaluation_id: evaluation!.id, expected_review_revision: evaluation!.review_revision }
      : action === "rollback" ? { ...base, action, target_revision: rollbackRevision } : { ...base, action };
    void perform({ kind: "transition", source, key: crypto.randomUUID(), payload });
  }

  return <dialog ref={dialog} className="fact-review-dialog reports-dialog parser-release-dialog" aria-labelledby="parser-release-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">LOCAL PARSER RELEASE</span><h2 id="parser-release-title">解析器发布与回滚</h2></div><button type="button" className="icon-button" aria-label="关闭解析器发布" onClick={onClose}>×</button></header>
    <div className="reports-content parser-release-content"><div className="snapshot-banner"><strong>本机工作区 · 受控发布</strong><span>评估只重放历史原文；审批、切换不访问来源，不采纳历史候选，也不刷新在线核验时间。署名为本地自报。</span></div>
      <div className="parser-release-toolbar"><label><span>管理来源</span><select value={source} disabled={busy} onChange={event => chooseSource(event.target.value)}>{choices.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><button type="button" className="secondary-button" disabled={busy} onClick={reload}>重新读取部署与记录</button></div>
      {Object.entries(readErrors).filter(([, value]) => value).map(([key, value]) => <p className="inline-error" role="alert" key={key}>{value}</p>)}
      {actionError ? <p className="inline-error" role="alert">{actionError}</p> : null}{notice ? <p className="review-saved" role="status">{notice}</p> : null}
      {pending ? <section className="review-boundary" aria-label="待核对的固定发布请求"><strong>已有请求待核对，不创建新的请求标识</strong><p>标识 <code>{pending.key}</code> · {pending.kind === "evaluation" ? "历史评估" : pending.kind === "bootstrap" ? "首次初始化" : actionLabels[pending.payload.action]}</p><DataTree label="此请求的固定范围" value={pending.payload} /><p>关闭窗口不会撤销服务端已受理操作。同一标签页重开仍保留此请求；刷新整个页面后请先核对历史记录。</p><button type="button" className="primary-button" disabled={busy} onClick={() => void perform(pending)}>{busy ? "正在核对…" : "继续 / 核对同一次请求"}</button></section> : null}
      <section className="parser-deployment-current"><div className="panel-title"><h3>1 · 当前部署</h3>{head ? <span className="metadata-pill">{head.state === "active" ? "活动" : head.state === "paused" ? "暂停" : "尚未初始化"} · 修订 #{head.revision}</span> : null}</div>
        {!head ? <p role="status">正在读取当前部署…</p> : <><p>{head.parser?.parser_version || "首次使用前固定当前受信安装代码"}</p>{head.bundle_id ? <p>活动指向包 <code>{head.bundle_id}</code></p> : <p>初始化会封存服务端当前受信代码并固定修订1；不会访问官网或采纳事实。后续源码更新仍须单独评估与发布。</p>}
          <GoldenEvidence gate={head.golden_gate} />
          <details className="report-history"><summary>部署历史（{head.history.length}{head.history_truncated ? "+，最近100条" : "条"}）</summary>{head.history.map(item => <article key={item.revision}><h4>#{item.revision} · {actionLabels[item.action]} · {item.state === "active" ? "活动" : "暂停"}</h4><p>{stamp(item.created_at)} · {item.operator}（本地自报）</p><p>{item.parser.parser_version} · 包 <code>{item.bundle_id}</code></p><p>当前 Golden 资格：{item.golden_gate ? goldenStates[item.golden_gate.state] : "未验证"}</p><p className="draft-original">{item.reason}</p>{item.rollback_revision ? <p>回滚目标是历史修订 #{item.rollback_revision}；本记录仍是新修订。</p> : null}</article>)}</details></>}
      </section>
      <section className="parser-evaluation-create"><h3>2 · 选择代码包与历史样本</h3><p>只选择已登记的受信包，不上传代码。登记不保证文件与环境仍可用，执行前会再次校验。</p>
        <div className="parser-bundle-options">{bundles?.items.filter(item => item.parsers.some(parser => parser.source_id === source)).map(item => <button type="button" key={item.id} className={`report-list-item${bundle?.id === item.id ? " selected" : ""}`} aria-pressed={bundle?.id === item.id} disabled={locked} onClick={() => setBundle(item)}><strong>包 {short(item.id)}</strong><span>{item.parsers.find(parser => parser.source_id === source)?.parser_version}</span><small>{stamp(item.created_at)} · {item.operator}</small></button>)}</div>
        {bundles && !bundles.items.length ? <p>本页没有已登记包。初始化可固定首次活动包；其他候选须由服务端运维入口完成封存登记。</p> : bundles && !bundles.items.some(item => item.parsers.some(parser => parser.source_id === source)) ? <p>本页没有包含当前来源的代码包。可翻页查找；历史包不会自动增加新来源，初始化仅固定当前安装代码。</p> : null}
        <Pages label="代码包" offset={bundleOffset} total={bundles?.total || 0} disabled={locked || !bundles} onChange={setBundleOffset} />
        {bundle ? <div className="review-boundary"><p>所选候选包 <code>{bundle.id}</code> · {descriptor?.parser_version}</p><p>Parser 指纹 <code>{descriptor?.parser_digest}</code></p><DataTree label="所选包的登记与兼容环境" value={bundle} /></div> : null}
        <label className="golden-field"><span>评估依据</span><select value={evaluationMode} disabled={locked} onChange={event => setEvaluationMode(event.target.value as "golden" | "relative")}><option value="golden" disabled={recallSource}>人工审核的完整冻结集</option><option value="relative">{recallSource ? "召回相对回归样本（既有发布流程）" : "相对回归样本（不能用于新发布）"}</option></select></label>
        {evaluationMode === "golden" ? <><h4>同来源 Golden 冻结集 · 全部成员参与评估</h4><p>先在“Golden 真值与冻结集”填写并人工审核预期；此处绑定集合的精确修订与指纹，不能只选部分成员。</p><div className="parser-bundle-options">{goldenSets?.items.map(item => <button type="button" key={item.id} className={`report-list-item${goldenId === item.id ? " selected" : ""}`} aria-pressed={goldenId === item.id} disabled={locked || !item.eligible || item.state !== "frozen"} onClick={() => setGoldenId(item.id)}><strong>{item.title} · #{item.revision}</strong><span>{item.capture_ids.length} 份原文 · {item.eligible ? "当前可评估" : item.state === "revoked" ? "已撤回" : "依据已失效"}</span><small>{stamp(item.created_at)}</small></button>)}</div>{goldenSets?.total === 0 ? <p className="review-boundary">该来源暂无冻结集。缺少人工真值不能批准新发布；召回与测试事件尚不支持 Golden 集合。</p> : null}<Pages label="冻结集" offset={goldenOffset} total={goldenSets?.total || 0} disabled={locked || !goldenSets} onChange={setGoldenOffset} />
          {goldenSet ? <div className="review-boundary"><p>{goldenSet.title} · 修订 #{goldenSet.revision}</p><p>冻结指纹 <code>{goldenSet.fingerprint}</code></p>{!goldenSet.eligible ? <p className="inline-error">集合当前不可评估：{goldenSet.blockers.join("、")}</p> : null}<DataTree label="所选集合的人工预期与审核证据" value={goldenSet.cases} />{goldenSet.capture_ids.map(id => <p key={id}>原文 <code>{id}</code> <button type="button" className="text-button" disabled={busy} onClick={() => setRawId(id)}>核对原文</button></p>)}</div> : goldenId ? <p role="status">正在读取冻结集合…</p> : null}
        </> : <><h4>同来源原文 · 选择1–3份</h4><p className="review-boundary">{recallSource ? "召回保留既有严格回归审批流程；Golden 不适用，不表示人工真值或适用性已确认。" : "此模式只生成相对回归记录，不绑定人工真值，不能据此批准、激活、恢复或回滚部署。"}</p><div className="parser-capture-options">{captures?.items.map(item => <article key={item.id}><label className="review-checkbox"><input type="checkbox" checked={samples.some(sample => sample.id === item.id)} disabled={locked || (samples.length >= 3 && !samples.some(sample => sample.id === item.id))} onChange={event => setSamples(current => event.target.checked ? [...current, item] : current.filter(sample => sample.id !== item.id))} /><span>{targetLabel(item.target_kind, item.query)} · {stamp(item.observed_at)} · {item.byte_count.toLocaleString("zh-CN")} 字节<br />{item.query && queryScope(item.query) ? <>{queryScope(item.query)}<br /></> : null}<code>{short(item.id)}</code> · {item.query_state}</span></label><button type="button" className="text-button" disabled={busy} onClick={() => setRawId(item.id)}>核对这份原文</button></article>)}</div>
        <Pages label="原文" offset={captureOffset} total={captures?.total || 0} disabled={locked || !captures} onChange={setCaptureOffset} />
        <p>已选择 {samples.length}/3 份</p>{samples.map(item => <p key={item.id}><code>{item.id}</code> · {stamp(item.observed_at)} <button type="button" className="text-button" disabled={locked} onClick={() => setSamples(current => current.filter(sample => sample.id !== item.id))}>移除样本</button></p>)}</>}
        {rawId ? <section className="parser-raw-preview"><div className="panel-title"><h4>原文核对</h4><button type="button" className="text-button" onClick={() => setRawId("")}>收起原文</button></div>{raw ? <><p>{raw.source_url}</p><p>收件 <code>{raw.id}</code> · SHA-256 <code>{raw.raw_hash}</code></p><DataTree label="历史原文（分页文本，不执行内容）" value={raw.body} /></> : <p role="status">正在读取这份历史原文…</p>}</section> : null}
        <p>本次评估 {evaluationCaptures.length} 份原文 · 依据部署修订 #{head?.revision ?? "未读取"}</p>
        <label className="review-checkbox"><input type="checkbox" checked={evaluateConfirmed} disabled={locked || !head?.revision || !descriptor || !readySamples} onChange={event => setEvaluateConfirmed(event.target.checked)} /><span>已核对具体包、{evaluationMode === "golden" ? "完整人工冻结集及指纹" : "相对回归原文"}和当前部署修订；仅生成评估，不访问来源或采纳事实。</span></label><button type="button" className="primary-button" disabled={locked || !head?.revision || !descriptor || !readySamples || !evaluateConfirmed} onClick={createEvaluation}>评估所选包与样本</button>
      </section>
      <div className="reports-layout"><section className="reports-list" aria-label="解析器评估历史"><h3>3 · 评估与审批</h3>{evaluations?.items.map(item => <button type="button" className={`report-list-item${selectedId === item.id ? " selected" : ""}`} aria-pressed={selectedId === item.id} key={item.id} disabled={busy} onClick={() => { setSelectedId(item.id); setDetailRefresh(value => value + 1); }}><strong>{stateLabels[item.state]}</strong><small>候选 {short(item.target_bundle_id)} · 依据 #{item.deployment_revision}</small><small>{stamp(item.created_at)}</small><small>{item.latest_review ? item.latest_review.action === "approve" ? "已批准（活动状态见部署）" : "不批准 / 已撤回" : "尚未审批"}{item.deployment_stale ? " · 依据已过时" : ""}</small></button>)}{evaluations?.total === 0 ? <p>暂无评估记录。</p> : null}<Pages label="评估" offset={evaluationOffset} total={evaluations?.total || 0} disabled={busy || !evaluations} onChange={setEvaluationOffset} /></section>
        <section className="report-detail" aria-label="解析器评估详情"><h3 ref={focusTarget} tabIndex={-1}>{evaluation ? stateLabels[evaluation.state] : selectedId ? "正在读取评估…" : "选择一份评估核对"}</h3>{evaluation ? <><button type="button" className="text-button" disabled={busy} onClick={() => { setActionError(""); setDetailRefresh(value => value + 1); }}>重新读取评估与审批</button><EvaluationEvidence value={evaluation} />
          {!currentEvaluation ? <p className="inline-error">评估依据与当前部署不同，不能据此批准或激活。可保留历史记录或追加不批准决定。</p> : null}
          {reviewStale ? <p className="inline-error" role="alert">审批状态发生冲突或结果未确认。重新读取后再核对；当前表单已锁定。</p> : null}
          {evaluation.completion ? <form className="review-form" onSubmit={event => { event.preventDefault(); void review(); }}><h4>追加发布审批（不自动切换）</h4><label><span>审批决定</span><select value={reviewAction} disabled={locked || reviewStale} onChange={event => { setReviewAction(event.target.value as "approve" | "reject"); setReviewConfirmed(false); }}><option value="approve">批准此冻结评估用于发布</option><option value="reject">不批准 / 撤回批准</option></select></label><label><span>审批署名（本地自报）</span><input value={reviewOperator} maxLength={100} required disabled={locked || reviewStale} onChange={event => setReviewOperator(event.target.value)} /></label><label><span>审批理由</span><textarea value={reviewReason} maxLength={2000} rows={3} required disabled={locked || reviewStale} onChange={event => setReviewReason(event.target.value)} /></label>
            {evaluation.completion.reference_gaps.length ? <label className="review-checkbox"><input type="checkbox" checked={gapConfirmed} disabled={locked || reviewStale} onChange={event => setGapConfirmed(event.target.checked)} /><span>确认相对回归缺少同原文正式参考；已核对对照结果或其失败。此确认不能豁免 Golden 精确差异或覆盖缺口。</span></label> : null}
            <label className="review-checkbox"><input type="checkbox" checked={reviewConfirmed} disabled={locked || reviewStale} onChange={event => setReviewConfirmed(event.target.checked)} /><span>已核对{recallRegression(evaluation.golden_gate) ? "召回候选、参考、质量与回执" : "人工冻结集、精确差异、候选及回执"}；批准只绑定当前完成指纹，仍须单独激活。</span></label><button type="submit" className="primary-button" disabled={locked || reviewStale || !reviewConfirmed || !reviewOperator.trim() || !reviewReason.trim() || (reviewAction === "approve" && (!canApprove || (!!evaluation.completion.reference_gaps.length && !gapConfirmed)))}>追加审批修订</button></form> : null}
          {canActivate ? <button type="button" className="secondary-button" disabled={locked} onClick={() => { setAction("activate"); setChangeConfirmed(false); document.getElementById("parser-transition-title")?.scrollIntoView({ block: "start" }); }}>准备激活此已批准评估</button> : null}
        </> : null}</section></div>
      <section className="parser-transition"><h3 id="parser-transition-title">4 · 明确变更部署</h3><p>所有动作只改变本机后续请求的 Parser 选择，不回退数据库或重写旧事实。暂停后已在途的旧修订结果也不能采纳。</p>{deploymentStale ? <p className="inline-error">部署修订已发生冲突，先重新读取当前部署再确认。</p> : null}
        {head ? <form className="review-form" onSubmit={event => { event.preventDefault(); changeDeployment(); }}>{head.revision ? <label><span>部署操作</span><select value={action} disabled={locked || deploymentStale} onChange={event => { setAction(event.target.value as ParserTransition["action"]); setChangeConfirmed(false); }}><option value="pause">暂停来源解析</option><option value="resume">恢复当前包</option><option value="activate">激活所选已批准评估</option><option value="rollback">回滚到曾活动的历史包</option></select></label> : <p>首次本机信任初始化：封存当前安装代码，固定来源修订1；Golden 仍为未验证，不代表精确真值已通过。</p>}
          {head.revision > 0 && action === "rollback" ? <label><span>历史活动修订</span><select value={rollbackRevision} disabled={locked || deploymentStale} onChange={event => setRollbackRevision(Number(event.target.value))}><option value={0}>请选择明确的历史修订</option>{head.history.filter(item => item.state === "active" && item.revision < head.revision).map(item => <option value={item.revision} key={item.revision}>#{item.revision} · {item.parser.parser_version} · {short(item.bundle_id)}</option>)}</select></label> : null}
          <div className="review-boundary"><p>当前修订 #{head.revision}{head.revision ? ` → 新修订 #${head.revision + 1}` : " → 首次修订 #1"}</p><p>{head.revision === 0 ? "目标：当前受信安装代码，在服务端封存时确定包身份。" : action === "activate" ? <>目标候选 <code>{evaluation?.target_bundle_id || "未选择"}</code> · 审批修订 #{evaluation?.review_revision || 0}</> : action === "rollback" ? <>回滚目标 #{rollback?.revision || "未选择"} · <code>{rollback?.bundle_id || "未选择历史包"}</code></> : <>保持包 <code>{head.bundle_id}</code>，{action === "pause" ? "停止后续解析" : "恢复后续解析"}。</>}</p></div>
          {head.revision > 0 && !canTransition ? <p className="review-boundary">当前状态或审批不满足所选操作，请核对部署状态、评估依据和目标修订。</p> : null}
          <label><span>部署署名（本地自报）</span><input required maxLength={100} value={operator} disabled={locked || deploymentStale} onChange={event => setOperator(event.target.value)} /></label><label><span>部署理由</span><textarea required maxLength={2000} rows={3} value={reason} disabled={locked || deploymentStale} onChange={event => setReason(event.target.value)} /></label><label className="review-checkbox"><input type="checkbox" checked={changeConfirmed} disabled={locked || deploymentStale} onChange={event => setChangeConfirmed(event.target.checked)} /><span>确认上述当前修订、目标包与操作；理解不会重新访问来源或自动采纳历史候选。</span></label><button type="submit" className="primary-button" disabled={locked || deploymentStale || !changeConfirmed || !operator.trim() || !reason.trim() || (head.revision > 0 && !canTransition)}>{head.revision === 0 ? "初始化并固定首次部署" : actionLabels[action]}</button>
        </form> : null}
      </section>
    </div>
  </dialog>;
}

export default function ParserReleases({ sources, sessionReady }: { sources: Source[]; sessionReady: boolean }) {
  const [opened, setOpened] = useState(false);
  return <section className="report-entry panel"><div><span className="eyebrow">PARSER RELEASE</span><h3>解析器发布与回滚</h3><p>核对封存代码、历史样本与审批，再明确切换本机部署。</p></div><button type="button" className="secondary-button" disabled={!sessionReady} onClick={() => setOpened(true)}>管理解析器发布</button>{opened ? <ReleaseDialog sources={sources} onClose={() => setOpened(false)} /> : null}</section>;
}
