"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { GoldenCase, GoldenCaseSummary, GoldenCaseCreate, GoldenCaseEdit, GoldenCaseRef,
  GoldenCaseReviewRequest, GoldenExpected, GoldenKind, GoldenSet, GoldenSetCreate, GoldenSetRevision,
  ParserPage, RawCaptureEvidence, RawCaptureRecord, ReparseSummary, Source } from "@tire/domain-types";
import { DataTree } from "./reparse-review";

const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const short = (value: string) => `${value.slice(0, 12)}…`;
const statuses = { pending: "待人工审核", approved: "已签署当前预期", rejected: "不认可", revoked: "审核已撤回" };
const errorText = (error: unknown) => error instanceof ApiError && error.code
  ? `操作未完成（${error.code}）。请重新读取并核对版本、原文与审核记录。`
  : error instanceof Error ? error.message : "操作未完成，请核对记录。";
const json = (value: unknown) => JSON.stringify(value, null, 2);
const tireTemplate = { records: [{ golden_sku_id: "", value: { brand: "", model: "", manufacturer_product_code: null,
  region: "", size: "", load_index: null, speed_rating: null, xl: null, hl: null, oe_mark: null,
  acoustic_technology: null, run_flat: null, source_variant_name: null, facts: {} } }] };
const axleTemplate = { size: "", load_index: null, speed_rating: null, oe_mark: null, manufacturer_product_code: null, matched_tire_variant_id: null };
const vehicleTemplate = { vehicle: { id: "", manufacturer: { id: "", name: "" }, model: "", generation: "", model_year: null,
  region: "", source_vehicle_id: "" }, trims: [{ id: "", name: "", source_trim_id: "", model_year: null, wheel_option_ids: [""] }],
  fitments: [{ id: "", trim_id: "", trim_name: "", wheel_option_name: "", wheel_diameter_inches: null, availability: "",
    front: axleTemplate, rear: axleTemplate, staggered: null, source_tire_description: null, constraints: [], source_description: "", evidence_locator: "" }] };
const template = (kind: GoldenKind) => json(kind === "vehicle" ? vehicleTemplate : tireTemplate);
type Attempt = { key: string } & (
  { kind: "create-case"; payload: GoldenCaseCreate } | { kind: "edit-case"; id: string; payload: GoldenCaseEdit } |
  { kind: "review-case"; id: string; payload: GoldenCaseReviewRequest } | { kind: "create-set"; payload: GoldenSetCreate } |
  { kind: "edit-set"; id: string; payload: GoldenSetRevision });
// Requests survive dialog closure in this tab; evidence is never written to browser storage.
const pendingBySource = new Map<string, Attempt>();
type SelectedCase = { ref: GoldenCaseRef; capture: string; title: string };

function Pages({ name, page, busy, change }: { name: string; page: { offset: number; total: number } | null; busy: boolean; change: (offset: number) => void }) {
  return <div className="reparse-pages"><button type="button" className="text-button" disabled={busy || !page || !page.offset} onClick={() => page && change(Math.max(0, page.offset - 10))}>上一页{name}</button><span>{page ? `共 ${page.total} 条 · 第 ${Math.floor(page.offset / 10) + 1} 页` : "正在读取…"}</span><button type="button" className="text-button" disabled={busy || !page || page.offset + 10 >= page.total} onClick={() => page && change(page.offset + 10)}>下一页{name}</button></div>;
}

function GoldenWorkspace({ source, kind }: { source: string; kind: GoldenKind }) {
  const operation = useRef<AbortController | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [captureOffset, setCaptureOffset] = useState(0);
  const [captures, setCaptures] = useState<ParserPage<RawCaptureRecord> | null>(null);
  const [captureId, setCaptureId] = useState("");
  const [raw, setRaw] = useState<RawCaptureEvidence | null>(null);
  const [caseOffset, setCaseOffset] = useState(0);
  const [cases, setCases] = useState<ParserPage<GoldenCaseSummary> | null>(null);
  const [caseId, setCaseId] = useState("");
  const [caseRead, setCaseRead] = useState(0);
  const [record, setRecord] = useState<GoldenCase | null>(null);
  const [title, setTitle] = useState("");
  const [evidenceNote, setEvidenceNote] = useState("");
  const [expected, setExpected] = useState(() => template(kind));
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [reviewAction, setReviewAction] = useState<GoldenCaseReviewRequest["action"]>("approve");
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [candidates, setCandidates] = useState<ParserPage<ReparseSummary> | null>(null);
  const [candidateOffset, setCandidateOffset] = useState(0);
  const [showCandidates, setShowCandidates] = useState(false);
  const [setOffset, setSetOffset] = useState(0);
  const [sets, setSets] = useState<ParserPage<GoldenSet> | null>(null);
  const [setId, setSetId] = useState("");
  const [setRead, setSetRead] = useState(0);
  const [frozen, setFrozen] = useState<GoldenSet | null>(null);
  const [collectionTitle, setCollectionTitle] = useState("");
  const [selected, setSelected] = useState<SelectedCase[]>([]);
  const [setAction, setSetAction] = useState<"freeze" | "revoke">("freeze");
  const [collectionOperator, setCollectionOperator] = useState("");
  const [collectionReason, setCollectionReason] = useState("");
  const [freezeConfirmed, setFreezeConfirmed] = useState(false);
  const [pending, setPending] = useState<Attempt | null>(() => pendingBySource.get(source) || null);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [historical, setHistorical] = useState<{ kind: "case" | "set"; value: GoldenCase | GoldenSet } | null>(null);
  const locked = busy || !!pending;
  const dirty = !!record && (title !== record.title || captureId !== record.capture_id || evidenceNote !== record.evidence_note || expected !== json(record.expected));
  const rawMatches = !!record && raw?.id === record.capture_id && raw.raw_hash === record.input.raw_hash;
  const signed = !!operator.trim() && !!reason.trim();

  function error(name: string, value = "") { setErrors(current => ({ ...current, [name]: value })); }
  function remember(value: Attempt | null) { setPending(value); if (value) pendingBySource.set(source, value); else pendingBySource.delete(source); }
  function acceptCase(value: GoldenCase, expectedId?: string) {
    if (value.source_id !== source || value.kind !== kind || (expectedId && value.id !== expectedId)) throw new Error("样本返回范围不匹配，未展示。");
    setRecord(value); setTitle(value.title); setCaptureId(value.capture_id); setEvidenceNote(value.evidence_note); setExpected(json(value.expected));
    setReviewConfirmed(false); setReason(""); setStale(!value.is_current); setHistorical(null);
  }
  function acceptSet(value: GoldenSet, expectedId?: string) {
    if (value.source_id !== source || value.kind !== kind || (expectedId && value.id !== expectedId)) throw new Error("冻结集返回范围不匹配，未展示。");
    setFrozen(value); setCollectionTitle(value.title); setSetAction("freeze"); setSelected([]); setFreezeConfirmed(false); setCollectionReason(""); setStale(false); setHistorical(null);
  }
  function reload() { setRefresh(value => value + 1); setCaseRead(value => value + 1); setSetRead(value => value + 1); setReviewConfirmed(false); setFreezeConfirmed(false); }
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); setCaptures(null); error("captures");
    void tireApi.parserCaptures(source, controller.signal, captureOffset).then(value => {
      if (!controller.signal.aborted) { if (value.items.some(item => item.source_id !== source || item.target_kind !== kind)) throw new Error("原文来源或类型不匹配。"); setCaptures(value); }
    }).catch(cause => { if (!controller.signal.aborted) error("captures", errorText(cause)); });
    return () => controller.abort();
  }, [source, kind, captureOffset, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setCases(null); error("cases");
    void tireApi.goldenCases(source, controller.signal, caseOffset).then(value => {
      if (!controller.signal.aborted) { if (value.items.some(item => item.source_id !== source || item.kind !== kind)) throw new Error("样本列表范围不匹配。"); setCases(value); }
    }).catch(cause => { if (!controller.signal.aborted) error("cases", errorText(cause)); });
    return () => controller.abort();
  }, [source, kind, caseOffset, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setSets(null); error("sets");
    void tireApi.goldenSets(source, controller.signal, setOffset).then(value => {
      if (!controller.signal.aborted) { if (value.items.some(item => item.source_id !== source || item.kind !== kind)) throw new Error("冻结集列表范围不匹配。"); setSets(value); }
    }).catch(cause => { if (!controller.signal.aborted) error("sets", errorText(cause)); });
    return () => controller.abort();
  }, [source, kind, setOffset, refresh]);
  useEffect(() => {
    setRecord(null); setReviewConfirmed(false); error("case");
    if (!caseId) return;
    const controller = new AbortController();
    void tireApi.goldenCase(caseId, controller.signal).then(value => { if (!controller.signal.aborted) acceptCase(value, caseId); })
      .catch(cause => { if (!controller.signal.aborted) error("case", errorText(cause)); });
    return () => controller.abort();
    // The keyed workspace binds these requests to one immutable source/kind.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, caseRead]);
  useEffect(() => {
    setFrozen(null); setFreezeConfirmed(false); error("set");
    if (!setId) return;
    const controller = new AbortController();
    void tireApi.goldenSet(setId, controller.signal).then(value => { if (!controller.signal.aborted) acceptSet(value, setId); })
      .catch(cause => { if (!controller.signal.aborted) error("set", errorText(cause)); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setId, setRead]);
  useEffect(() => {
    setRaw(null); setShowCandidates(false); setCandidateOffset(0); setCandidates(null); setReviewConfirmed(false); error("raw");
    if (!captureId) return;
    const controller = new AbortController();
    void tireApi.captureEvidence(captureId, controller.signal).then(value => {
      if (!controller.signal.aborted) { if (value.id !== captureId || value.source_id !== source || value.target_kind !== kind) throw new Error("原文范围不匹配，未展示。"); setRaw(value); }
    }).catch(cause => { if (!controller.signal.aborted) error("raw", errorText(cause)); });
    return () => controller.abort();
  }, [captureId, source, kind, refresh]);
  useEffect(() => {
    setCandidates(null); error("candidates");
    if (!showCandidates || !captureId) return;
    const controller = new AbortController();
    void tireApi.reparses(captureId, controller.signal, candidateOffset).then(value => { if (!controller.signal.aborted) setCandidates(value); })
      .catch(cause => { if (!controller.signal.aborted) error("candidates", errorText(cause)); });
    return () => controller.abort();
  }, [captureId, showCandidates, candidateOffset]);
  useEffect(() => { setReviewConfirmed(false); }, [title, evidenceNote, expected, operator, reason, reviewAction]);
  useEffect(() => { setFreezeConfirmed(false); }, [selected, setAction, collectionTitle, collectionOperator, collectionReason]);

  function newCase() {
    setCaseId(""); setRecord(null); setTitle(""); setCaptureId(""); setEvidenceNote(""); setExpected(template(kind));
    setReviewConfirmed(false); setReason(""); setStale(false); setHistorical(null); error("action"); setNotice("");
  }
  async function copyCandidate(id: string) {
    if (locked || operation.current || !raw) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); error("action");
    try {
      const value = await tireApi.reparse(id, controller.signal);
      if (controller.signal.aborted) return;
      if (value.input.capture_id !== captureId || value.input.source_id !== source || value.input.raw_hash !== raw.raw_hash
        || value.state !== "completed" || !value.completion?.candidate) throw new Error("候选与当前原文不匹配或没有完成，未复制。");
      const candidate = value.completion.candidate;
      if (kind === "tire") {
        if (!Array.isArray(candidate)) throw new Error("轮胎候选结构无效，未复制。");
        // Empty IDs force the reviewer to establish identity; array positions are not SKU truth.
        setExpected(json({ records: candidate.map(item => ({ golden_sku_id: "", value: item })) }));
      } else {
        if (!candidate || typeof candidate !== "object" || !("vehicle" in candidate) || !("trims" in candidate) || !("fitments" in candidate)) throw new Error("车型候选结构无效，未复制。");
        setExpected(json({ vehicle: candidate.vehicle, trims: candidate.trims, fitments: candidate.fitments }));
      }
      const provenance = `机器候选辅助：重解析 ${id}，完成指纹 ${value.completion.fingerprint}。尚未人工确认。`;
      setEvidenceNote(current => `${provenance}\n${current}`.trim().slice(0, 2000)); setReviewConfirmed(false);
      setNotice("候选已复制到未保存的待审稿。请逐字段核对原文、填写证据定位与 SKU 身份；这不是人工真值。");
    } catch (cause) { if (!controller.signal.aborted) error("action", errorText(cause)); }
    finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  async function readHistory(type: "case" | "set", id: string, revision: number) {
    if (locked || operation.current) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); error("action"); setHistorical(null);
    try {
      const value = type === "case" ? await tireApi.goldenCase(id, controller.signal, revision) : await tireApi.goldenSet(id, controller.signal, revision);
      if (controller.signal.aborted) return;
      if (value.id !== id || value.source_id !== source || value.kind !== kind || value.revision !== revision) throw new Error("历史内容与指定修订不匹配，未展示。");
      setHistorical({ kind: type, value });
    } catch (cause) { if (!controller.signal.aborted) error("action", errorText(cause)); }
    finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  async function perform(attempt: Attempt) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; remember(attempt); setBusy(true); error("action"); setNotice("");
    try {
      if (attempt.kind === "create-set" || attempt.kind === "edit-set") {
        const value = attempt.kind === "create-set" ? await tireApi.createGoldenSet(attempt.payload, attempt.key, controller.signal)
          : await tireApi.reviseGoldenSet(attempt.id, attempt.payload, attempt.key, controller.signal);
        if (controller.signal.aborted) return;
        if (value.revision !== attempt.payload.expected_revision + 1) throw new Error("冻结集响应修订不匹配，请保留请求标识核对。");
        acceptSet(value, attempt.kind === "edit-set" ? attempt.id : undefined); setSetId(value.id); setSetOffset(0);
        setNotice(value.state === "revoked" ? "已追加撤回修订；旧冻结内容与评估保留，不能再用于新发布。" : "已保存冻结修订。请在解析器发布中选择此集合进行离线评估；没有自动批准或激活。");
      } else {
        const value = attempt.kind === "create-case" ? await tireApi.createGoldenCase(attempt.payload, attempt.key, controller.signal)
          : attempt.kind === "edit-case" ? await tireApi.reviseGoldenCase(attempt.id, attempt.payload, attempt.key, controller.signal)
          : await tireApi.reviewGoldenCase(attempt.id, attempt.payload, attempt.key, controller.signal);
        if (controller.signal.aborted) return;
        if ((attempt.kind === "review-case" ? value.recorded_review?.revision : value.revision) !== attempt.payload.expected_revision + 1) throw new Error("样本响应修订不匹配，请保留请求标识核对。");
        if (attempt.kind === "review-case" && (value.recorded_review?.case_revision !== attempt.payload.case_revision
          || value.recorded_review.case_fingerprint !== attempt.payload.case_fingerprint || value.recorded_review.action !== attempt.payload.action)) throw new Error("审核原事件与固定请求不匹配，请保留请求标识核对。");
        acceptCase(value, attempt.kind === "create-case" ? undefined : attempt.id); setCaseId(value.id); setCaseOffset(0); setSelected([]);
        setNotice(attempt.kind === "review-case" ? "人工决定已追加，仅绑定这份预期修订；没有冻结集合或采纳事实。" : "待审稿已保存。新内容需要单独对照原文审核；不会沿用旧审核。");
      }
      remember(null); setRefresh(value => value + 1);
    } catch (cause) {
      if (!controller.signal.aborted) {
        error("action", errorText(cause)); setReviewConfirmed(false); setFreezeConfirmed(false);
        if (cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status) && cause.code !== "idempotency_payload_mismatch") {
          remember(null); if (cause.status === 409) setStale(true);
        }
      }
    } finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function saveCase() {
    if (locked || stale || !signed || !title.trim() || !evidenceNote.trim() || !raw || raw.id !== captureId || (caseId && (!record || !record.is_current))) return;
    try {
      const parsed: unknown = JSON.parse(expected);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || (kind === "tire" ? !("records" in parsed) : !("vehicle" in parsed) || !("trims" in parsed) || !("fitments" in parsed))) throw new Error("请按当前类型的结构填写完整预期 JSON。字段值与身份约束还会由服务端校验。");
      const payload: GoldenCaseEdit = { title: title.trim(), capture_id: captureId, evidence_note: evidenceNote.trim(), expected: parsed as GoldenExpected,
        expected_revision: record?.revision || 0, expected_fingerprint: record?.fingerprint || null, operator: operator.trim(), reason: reason.trim() };
      void perform(record ? { kind: "edit-case", id: record.id, payload, key: crypto.randomUUID() }
        : { kind: "create-case", payload: { ...payload, source_id: source, kind }, key: crypto.randomUUID() });
    } catch (cause) { error("action", cause instanceof SyntaxError ? "预期 JSON 格式无效，请检查引号、逗号和括号。" : errorText(cause)); }
  }
  function reviewCase() {
    if (locked || stale || !record || !record.is_current || dirty || !rawMatches || !signed || !reviewConfirmed) return;
    void perform({ kind: "review-case", id: record.id, key: crypto.randomUUID(), payload: { case_revision: record.revision,
      case_fingerprint: record.fingerprint, expected_revision: record.review_revision, expected_fingerprint: record.review_fingerprint,
      action: reviewAction, acknowledged: true, operator: operator.trim(), reason: reason.trim() } });
  }
  function toggleCase(value: GoldenCaseSummary) {
    if (locked || value.status !== "approved" || !value.review_fingerprint) return;
    setSelected(current => current.some(item => item.ref.case_id === value.id) ? current.filter(item => item.ref.case_id !== value.id)
      : current.length < 3 && !current.some(item => item.capture === value.capture_id) ? [...current, { title: value.title, capture: value.capture_id,
        ref: { case_id: value.id, case_revision: value.revision, case_fingerprint: value.fingerprint, review_revision: value.review_revision, review_fingerprint: value.review_fingerprint! } }] : current);
  }
  function freezeSet() {
    if (locked || stale || !freezeConfirmed || !collectionTitle.trim() || !collectionOperator.trim() || !collectionReason.trim() || (setId && !frozen)
      || (setAction === "freeze" && !selected.length)) return;
    const payload: GoldenSetCreate = { title: collectionTitle.trim(), source_id: source, case_refs: setAction === "revoke" ? [] : selected.map(item => item.ref),
      expected_revision: frozen?.revision || 0, expected_fingerprint: frozen?.fingerprint || null, acknowledged: true, operator: collectionOperator.trim(), reason: collectionReason.trim() };
    void perform(frozen ? { kind: "edit-set", id: frozen.id, key: crypto.randomUUID(), payload: { ...payload, action: setAction } }
      : { kind: "create-set", key: crypto.randomUUID(), payload });
  }

  return <div className="parser-release-content golden-workspace">
    <div className="parser-release-toolbar"><span>{kind === "tire" ? "轮胎精确 SKU" : "车型、配置与轴位"} · 历史原文</span><button type="button" className="secondary-button" disabled={locked} onClick={reload}>重新读取最新记录</button></div>
    {Object.entries(errors).filter(([, value]) => value).map(([key, value]) => <p key={key} className="inline-error" role="alert">{value}</p>)}
    {notice ? <p className="review-saved" role="status">{notice}</p> : null}
    {stale ? <p className="inline-error">修订已变化，当前提交已锁定。重新读取所选样本或集合后核对；新建草稿可点击“新建待审样本”。</p> : null}
    {pending ? <section className="review-boundary"><strong>上一次写入结果待核对</strong><p>固定请求 <code>{pending.key}</code>。关闭窗口不撤销已受理的操作；同标签页重开保留相同请求，整页刷新前请先核对记录。</p><DataTree label="待核对请求的固定内容" value={pending.payload} /><button type="button" className="primary-button" disabled={busy} onClick={() => void perform(pending)}>继续核对同一次请求</button></section> : null}
    <section><div className="panel-title"><h3>1 · 样本与待审预期</h3><button type="button" className="secondary-button" disabled={locked} onClick={newCase}>新建待审样本</button></div>
      <div className="parser-bundle-options">{cases?.items.map(item => <article key={item.id} className="golden-case-option"><button type="button" className={`report-list-item${caseId === item.id ? " selected" : ""}`} aria-pressed={caseId === item.id} disabled={locked} onClick={() => { setCaseId(item.id); setCaseRead(value => value + 1); }}><strong>{item.title}</strong><span>预期 #{item.revision} · {statuses[item.status]}</span><small>{stamp(item.created_at)} · {short(item.capture_id)}</small></button><label className="review-checkbox"><input type="checkbox" checked={selected.some(value => value.ref.case_id === item.id)} disabled={locked || item.status !== "approved" || (!selected.some(value => value.ref.case_id === item.id) && (selected.length >= 3 || selected.some(value => value.capture === item.capture_id)))} onChange={() => toggleCase(item)} /><span>将此已审核修订加入冻结选择</span></label></article>)}</div>
      {cases?.total === 0 ? <p>暂无 Golden 样本。下面可从已接收原文建立第一份待审稿。</p> : null}<Pages name="样本" page={cases} busy={locked} change={setCaseOffset} />
      {caseId && !record ? <p role="status">正在读取所选样本内容…</p> : <>
        <h4>{record ? `编辑 ${record.title} · 预期 #${record.revision}` : "新建待审稿"}</h4><p>保存只生成待审修订。修改任何预期、原文或证据说明后都需要重新审核。</p>
        <h4>选择原文收件</h4><div className="parser-capture-options">{captures?.items.map(item => <article key={item.id}><label className="review-checkbox"><input type="radio" name="golden-capture" checked={captureId === item.id} disabled={locked} onChange={() => setCaptureId(item.id)} /><span>{stamp(item.observed_at)} · {item.byte_count.toLocaleString("zh-CN")} 字节 · <code>{short(item.id)}</code><br />{JSON.stringify(item.query || {})}</span></label></article>)}</div><Pages name="原文" page={captures} busy={locked} change={setCaptureOffset} />
        {captureId ? <div className="review-boundary"><p>选定收件 <code>{captureId}</code></p>{raw ? <><p>原文 SHA-256 <code>{raw.raw_hash}</code> · {raw.content_type}</p><p>{raw.source_url}</p><DataTree label="接收原文（纯文本，不执行内容）" value={raw.body} /><DataTree label="原文查询范围" value={raw.query} /></> : <p role="status">正在读取原文；原文可用后才能保存或审核。</p>}</div> : null}
        <form className="review-form" onSubmit={event => { event.preventDefault(); saveCase(); }}>
          <label><span>样本标题</span><input maxLength={200} value={title} disabled={locked} onChange={event => setTitle(event.target.value)} /></label>
          <label><span>原文定位与核对说明</span><textarea rows={3} maxLength={2000} value={evidenceNote} disabled={locked} placeholder="记录行、表、段落、字段及身份判定依据；解释未知值。" onChange={event => setEvidenceNote(event.target.value)} /></label>
          <details className="review-boundary"><summary>预期字段与身份约定</summary><p>{kind === "tire" ? "records 每项包含 golden_sku_id 和完整 value；value 使用 brand、model、manufacturer_product_code、region、size、load_index、speed_rating、xl、hl、oe_mark、acoustic_technology、run_flat、source_variant_name、facts。未知可空字段写 null，不能用 false 或空字符串代替未知。" : "顶层仅填写 vehicle、trims、fitments 三组。vehicle 使用 model 与 manufacturer（id、name），各组内字段完整核对；Parser 的 coverage、documents、footnotes 留作原始证据，不放入预期。车型、配置、轮毂项 ID 及 wheel_option_ids 必须对应；前后轴规格、异宽标记和轮毂直径必须一致。未知可空字段写 null；availability 填 standard、optional 或 unavailable。"}</p>{kind === "tire" ? <p>同一冻结集内，相同 golden_sku_id 表示同一 SKU；不同 ID 必须保持独立。不能把行序号直接当作已确认的 SKU 身份。至少两个不同 SKU 才能评估独立性；单 SKU 不能证明零错误合并。</p> : null}<p>空白模板只说明结构，不能直接作为真值保存。必填字段需根据原文补齐；服务端会校验完整结构、查询范围和身份。</p></details>
          {kind === "tire" ? <p className="review-boundary">来源编码类型仍写在 facts.product_code_type 中，按原文保留 CAI、MSPN、EAN 等声明；不能用当前迁移结论自动补改旧人工预期。身份规则变化后，应新建待审修订并重新核对、冻结。</p> : null}
          <label><span>人工预期 JSON</span><textarea className="golden-json-editor" spellCheck={false} rows={18} value={expected} disabled={locked} onChange={event => setExpected(event.target.value)} /></label>
          <button type="button" className="text-button" disabled={locked || !raw} onClick={() => setShowCandidates(value => !value)}>{showCandidates ? "收起既有解析候选" : "查看可显式复制的既有解析候选"}</button>
          {showCandidates ? <div className="review-boundary"><p>只读取已有重解析。点击复制才填入草稿；不会执行 Parser、自动审核或生成 SKU 真值。</p>{candidates?.items.map(item => <div key={item.id}><p>{stamp(item.created_at)} · {item.state} · {item.parser.version}</p><button type="button" className="secondary-button" disabled={locked || item.state !== "completed" || !!item.completion?.error_code} onClick={() => void copyCandidate(item.id)}>复制此解析候选为待审稿</button></div>)}{candidates?.total === 0 ? <p>这份原文没有历史重解析，可手工填写预期。</p> : null}<Pages name="候选" page={candidates} busy={locked} change={setCandidateOffset} /></div> : null}
          <label><span>本次操作署名（本地自报）</span><input maxLength={100} value={operator} disabled={locked} onChange={event => setOperator(event.target.value)} /></label><label><span>保存或审核理由</span><textarea maxLength={2000} rows={3} value={reason} disabled={locked} onChange={event => setReason(event.target.value)} /></label>
          <button type="submit" className="primary-button" disabled={locked || stale || !raw || !title.trim() || !evidenceNote.trim() || !signed || (!!record && (!dirty || !record.is_current))}>{record ? "保存为新的待审修订" : "保存待审样本"}</button>
        </form>
        {record ? <section className="golden-review"><h4>2 · 审核已保存的精确内容</h4><p>预期 #{record.revision} · 审核 #{record.review_revision} · {statuses[record.status]}</p><p>内容指纹 <code>{record.fingerprint}</code></p><DataTree label="已保存的预期值（本次审核对象）" value={record.expected} /><DataTree label="冻结原文绑定" value={record.input} /><p className="draft-original">{record.evidence_note}</p>
          {dirty ? <p className="inline-error">有未保存的修改。先保存为待审修订并重新核对，再签署该修订。</p> : null}{!rawMatches ? <p className="inline-error">尚未读取与审核对象 hash 一致的原文，不能签署。</p> : null}
          <label className="golden-field"><span>人工决定</span><select value={reviewAction} disabled={locked} onChange={event => setReviewAction(event.target.value as GoldenCaseReviewRequest["action"])}><option value="approve">确认预期与原文一致</option><option value="reject">不认可这份预期</option><option value="revoke">撤回人工审核</option></select></label>
          <label className="review-checkbox"><input type="checkbox" checked={reviewConfirmed} disabled={locked || stale || dirty || !rawMatches} onChange={event => setReviewConfirmed(event.target.checked)} /><span>我已亲自对照上述原文、字段与身份判定，确认对此预期修订作出所选决定。机器生成的候选或合成测试不能冒充真实数据的人工审核。</span></label>
          <button type="button" className="primary-button" disabled={locked || stale || !record.is_current || dirty || !rawMatches || !signed || !reviewConfirmed} onClick={reviewCase}>签署当前预期修订</button>
          <DataTree label={`预期修订历史${record.history_truncated ? "（最近100条）" : ""}`} value={record.history} /><DataTree label={`审核历史${record.reviews_truncated ? "（最近100条）" : ""}`} value={record.reviews} />
          <details><summary>读取指定历史预期（只读）</summary>{record.history?.map(item => <p key={item.revision}>#{item.revision} · {stamp(item.created_at)} · {item.operator} <button type="button" className="text-button" disabled={locked} onClick={() => void readHistory("case", record.id, item.revision)}>读取预期历史 #{item.revision}</button></p>)}</details>
        </section> : null}
      </>}
    </section>
    <section><div className="panel-title"><h3>3 · 冻结同来源集合</h3><button type="button" className="secondary-button" disabled={locked} onClick={() => { setSetId(""); setFrozen(null); setCollectionTitle(""); setSetAction("freeze"); setFreezeConfirmed(false); setCollectionReason(""); setStale(false); }}>新建冻结集合</button></div>
      <p>选择上方 1–3 个已签署样本，每份原文只能出现一次。冻结后内容不可改写；撤回或新审核会使旧集合失去新发布资格，历史内容仍保留。</p>
      <div className="parser-bundle-options">{sets?.items.map(item => <button type="button" className={`report-list-item${setId === item.id ? " selected" : ""}`} key={item.id} disabled={locked} aria-pressed={setId === item.id} onClick={() => { setSetId(item.id); setSetRead(value => value + 1); }}><strong>{item.title} · #{item.revision}</strong><span>{item.state === "revoked" ? "已撤回" : item.eligible ? "已冻结 · 当前可用于评估" : "历史冻结 · 当前不可发布"}</span><small>{item.capture_ids.length} 份原文 · {stamp(item.created_at)}</small></button>)}</div><Pages name="集合" page={sets} busy={locked} change={setSetOffset} />
      {frozen ? <div className="review-boundary"><p>集合 <code>{frozen.id}</code> · #{frozen.revision}</p><p>指纹 <code>{frozen.fingerprint}</code></p>{frozen.blockers.length ? <p className="inline-error">当前阻断：{frozen.blockers.join("、")}</p> : null}<DataTree label="集合冻结的原文与人工预期" value={frozen.cases} /><DataTree label={`集合修订历史${frozen.history_truncated ? "（最近100条）" : ""}`} value={frozen.history} /></div> : null}
      {frozen ? <details><summary>读取指定冻结历史（只读）</summary>{frozen.history?.map(item => <p key={item.revision}>#{item.revision} · {item.action === "freeze" ? "冻结" : "撤回"} · {stamp(item.created_at)} <button type="button" className="text-button" disabled={locked} onClick={() => void readHistory("set", frozen.id, item.revision)}>读取冻结历史 #{item.revision}</button></p>)}</details> : null}
      <form className="review-form" onSubmit={event => { event.preventDefault(); freezeSet(); }}><h4>{frozen ? "追加集合修订" : "创建冻结集合"}</h4><label><span>集合标题</span><input value={collectionTitle} maxLength={200} disabled={locked || (!!setId && !frozen)} onChange={event => setCollectionTitle(event.target.value)} /></label>
        {frozen ? <label><span>集合操作</span><select value={setAction} disabled={locked} onChange={event => setSetAction(event.target.value as "freeze" | "revoke")}><option value="freeze">用重新选择的审核修订冻结新版本</option><option value="revoke">撤回当前集合</option></select></label> : null}
        {setAction === "freeze" ? <div className="review-boundary"><p>当前选择 {selected.length}/3 个样本。核对原文范围与 SKU 身份后冻结。</p>{selected.map(item => <p key={item.ref.case_id}>{item.title} · 预期 #{item.ref.case_revision} · 审核 #{item.ref.review_revision} <button type="button" className="text-button" disabled={locked} onClick={() => setSelected(current => current.filter(value => value.ref.case_id !== item.ref.case_id))}>移除</button></p>)}<DataTree label="将冻结的精确样本与审核指纹" value={selected.map(item => item.ref)} /></div> : <p className="review-boundary">撤回将阻止引用此集合的新批准、激活、恢复和回滚；不会删除历史评估或自动暂停现有部署。</p>}
        <label><span>集合操作署名（本地自报）</span><input maxLength={100} value={collectionOperator} disabled={locked} onChange={event => setCollectionOperator(event.target.value)} /></label><label><span>冻结或撤回理由</span><textarea maxLength={2000} rows={3} value={collectionReason} disabled={locked} onChange={event => setCollectionReason(event.target.value)} /></label>
        <label className="review-checkbox"><input type="checkbox" checked={freezeConfirmed} disabled={locked || stale} onChange={event => setFreezeConfirmed(event.target.checked)} /><span>已核对本次集合操作、具体样本与审核指纹。冻结不等于评估通过，精确差异不能通过署名豁免。</span></label><button type="submit" className="primary-button" disabled={locked || stale || (!!setId && !frozen) || !collectionTitle.trim() || !collectionOperator.trim() || !collectionReason.trim() || !freezeConfirmed || (setAction === "freeze" && !selected.length)}>{setAction === "freeze" ? "冻结所选人工审核修订" : "追加集合撤回修订"}</button>
      </form>
    </section>
    {historical ? <section className="review-boundary"><div className="panel-title"><h3>历史{historical.kind === "case" ? "预期" : "集合"} · #{historical.value.revision} · 只读</h3><button type="button" className="text-button" onClick={() => setHistorical(null)}>收起历史内容</button></div><p>历史内容保留原修订，不替换当前编辑表单，也不恢复其发布资格。</p><DataTree label="指定历史修订完整内容" value={historical.value} /></section> : null}
  </div>;
}

function GoldenDialog({ sources, onClose }: { sources: Source[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const choices = sources.filter(item => !!item.parser_version && item.target_kind !== "recall" && item.id !== "xiaomi-cn-vehicles");
  const sourceChoices = [...choices, { id: "xiaomi-cn-vehicles", name: "小米汽车 · 官方配置", target_kind: "vehicle" as const }];
  const [source, setSource] = useState(sourceChoices[0]?.id || "");
  const kind: GoldenKind = sourceChoices.find(item => item.id === source)?.target_kind === "vehicle" ? "vehicle" : "tire";
  useEffect(() => {
    const node = dialog.current; const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal(); return () => { node?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={dialog} className="fact-review-dialog reports-dialog golden-dialog" aria-labelledby="golden-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">GOLDEN EVIDENCE</span><h2 id="golden-title">Golden 真值与冻结集</h2></div><button type="button" className="icon-button" aria-label="关闭 Golden 工作区" onClick={onClose}>×</button></header>
    <div className="reports-content"><div className="snapshot-banner"><strong>人工预期 · 本机工作区</strong><span>支持轮胎与车型原文。测试事件尚无 Parser，不在本轮范围。此处不会访问官网、采纳事实或证明完整生产 Golden 覆盖。</span></div><p className="review-boundary">署名是本地自报，不是身份认证。Agent 与 Parser 只能辅助准备待审稿；真实真值必须由人工对照证据签署，合成测试应明确标注。</p>
      <label className="golden-field"><span>Golden 来源</span><select value={source} onChange={event => setSource(event.target.value)}>{sourceChoices.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {source ? <GoldenWorkspace key={source} source={source} kind={kind} /> : <p>没有支持的来源。</p>}
    </div>
  </dialog>;
}

export default function GoldenSets({ sources, sessionReady }: { sources: Source[]; sessionReady: boolean }) {
  const [opened, setOpened] = useState(false);
  return <section className="report-entry panel"><div><span className="eyebrow">GOLDEN EVIDENCE</span><h3>Golden 真值与冻结集</h3><p>对照历史原文填写预期、人工签署，再冻结同来源集合供解析器评估。</p></div><button type="button" className="secondary-button" disabled={!sessionReady} onClick={() => setOpened(true)}>管理 Golden 样本</button>{opened ? <GoldenDialog sources={sources} onClose={() => setOpened(false)} /> : null}</section>;
}
