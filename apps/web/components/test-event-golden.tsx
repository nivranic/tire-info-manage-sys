"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { BridgeMaterialChoice, TestEventDetail, TestEventGoldenCase, TestEventGoldenCaseRef,
  TestEventGoldenCaseSummary, TestEventGoldenContent, TestEventGoldenEvaluation, TestEventGoldenExpected,
  TestEventGoldenLinkRef, TestEventGoldenMaterial, TestEventGoldenReviewRequest, TestEventGoldenSet,
  TestEventGoldenSetSummary, TestEventGoldenSetWrite, TestSkuLinkView } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { useWorkbenchPlatform } from "./workbench-platform";

type Attempt = { key: string; eventId: string } & (
  { action: "create-case"; payload: TestEventGoldenContent } |
  { action: "revise-case"; id: string; payload: TestEventGoldenContent } |
  { action: "review-case"; id: string; payload: TestEventGoldenReviewRequest } |
  { action: "create-set"; payload: TestEventGoldenSetWrite } |
  { action: "revise-set"; id: string; payload: TestEventGoldenSetWrite });

// A response can be lost after a write is accepted. Keep the original UUID and body in this tab.
const unresolved = new Map<string, Attempt>();
const scopeKey = (userId: string, eventId: string) => JSON.stringify([userId, eventId]);
const json = (value: unknown) => JSON.stringify(value, null, 2);
const short = (value: string) => value.length > 24 ? `${value.slice(0, 20)}…` : value;
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const errorText = (cause: unknown) => cause instanceof ApiError && cause.code
  ? `操作未完成（${cause.code}）。请重新读取对应记录与修订。`
  : cause instanceof Error ? cause.message : "操作未完成，请重新核对。";
const blankLocator = () => ({ page: 1, region: "", quote: "" });
const blankExpected = () => json({ event: { title: "", organization: "", relationship: "unknown", publication_date: null,
  source_url: "", rights_basis: "", tested_size: "", vehicle: null, surface: null, conditions: "",
  coverage: "selected_results", reported_participants: null, participants: [], metrics: [], measurements: [] },
  identity_assertions: [], distinct_pairs: [] });

function Pages({ label, offset, total, step, busy, onChange }: { label: string; offset: number; total: number; step: number;
  busy: boolean; onChange: (value: number) => void }) {
  return <div className="reparse-pages"><button type="button" className="text-button" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - step))}>上一页{label}</button>
    <span>{total} 条 · 第 {Math.floor(offset / step) + 1} 页</span><button type="button" className="text-button" disabled={busy || offset + step >= total} onClick={() => onChange(offset + step)}>下一页{label}</button></div>;
}

function JsonDetails({ label, value }: { label: string; value: unknown }) {
  return <details className="quality-technical"><summary>{label}</summary><pre className="golden-json-editor">{json(value)}</pre></details>;
}

function EvaluationView({ value }: { value: TestEventGoldenEvaluation }) {
  const state = { passed: "工程差异检查通过", failed: "工程差异检查失败", inconclusive: "证据不足，工程结果未定" }[value.state];
  return <section className="review-boundary" aria-label="测试事件 Golden 差异结果">
    <h4>{value.target === "current_head" ? "当前版本差异" : "冻结版本差异"} · {state}</h4>
    <p>集合 #{value.set_revision} · {short(value.set_fingerprint)}；已检查不同身份对 {value.checked_distinct_pair_count}，观察到的错误合并 {value.observed_wrong_merge_count ?? "未能判定"}。</p>
    <p>真人 Golden 资格：待外部人工审核。正式零错合并计数未认证；本机通过不代表发布通过，也不生成跨测试排名。</p>
    {value.case_results.map(item => <article key={item.case_id} className="quarantine-item"><h5>样本 {short(item.case_id)} · {item.state === "passed" ? "工程检查通过" : item.state === "failed" ? "工程检查失败" : "未定"}</h5>
      <p>事件修订 {short(item.expected_event_revision_id)} → {item.actual_event_revision_id ? short(item.actual_event_revision_id) : "缺失"}；审核 {item.review_status}；{item.eligible ? "当前有效" : "当前不可用"}</p>
      {item.blockers.length ? <p className="inline-error">阻断：{item.blockers.join("、")}</p> : null}
      <div className="comparison-table-wrap" tabIndex={0} aria-label="测试事件 Golden 逐字段差异，可横向滚动"><table className="comparison-table"><thead><tr><th>字段</th><th>原因</th><th>独立预期</th><th>真实当前值</th></tr></thead><tbody>
        {item.differences.map((difference, index) => <tr key={`${difference.path}:${index}`}><th scope="row">{difference.path}</th><td>{difference.code}</td><td><pre>{json(difference.expected)}</pre></td><td><pre>{json(difference.actual)}</pre></td></tr>)}
        {!item.differences.length ? <tr><td colSpan={4}>本目标下没有报告逐字段差异；仍须查看阻断与真人审核状态。</td></tr> : null}
      </tbody></table></div>{item.differences_truncated ? <p>差异已截断，请缩小并重新核对；不能据此判定全部一致。</p> : null}
      <JsonDetails label="同场比较、身份与不同 SKU 核对细节" value={{ comparison: item.comparison, identity_results: item.identity_results, distinct_results: item.distinct_results }} />
    </article>)}
  </section>;
}

export default function TestEventGolden({ event, readOnly = false }: { event: TestEventDetail; readOnly?: boolean }) {
  const auth = useWorkbenchAuth();
  if (!auth.ready) return <section className="test-event-golden"><h4>测试真值与复核</h4><p role="status">正在重新确认账户，旧内容和写入暂不显示。</p></section>;
  return <Workspace key={`${auth.ownerEpoch}:${event.revision_id}:${event.state}`} event={event} readOnly={readOnly} ownerEpoch={auth.ownerEpoch} />;
}

function Workspace({ event, readOnly, ownerEpoch }: { event: TestEventDetail; readOnly: boolean; ownerEpoch: number }) {
  const auth = useWorkbenchAuth(), platform = useWorkbenchPlatform();
  const userId = auth.state.user?.id || "", scope = scopeKey(userId, event.id);
  const [pending, setPending] = useState<Attempt | null>(() => unresolved.get(scope) || null);
  const [cases, setCases] = useState<TestEventGoldenCaseSummary[]>([]), [caseTotal, setCaseTotal] = useState(0), [caseOffset, setCaseOffset] = useState(0);
  const [allCases, setAllCases] = useState<TestEventGoldenCaseSummary[]>([]), [allTotal, setAllTotal] = useState(0), [allOffset, setAllOffset] = useState(0);
  const [sets, setSets] = useState<TestEventGoldenSetSummary[]>([]), [setTotal, setSetTotal] = useState(0), [setOffset, setSetOffset] = useState(0);
  const [materialsPage, setMaterialsPage] = useState<BridgeMaterialChoice[]>([]), [materialTotal, setMaterialTotal] = useState(0), [materialOffset, setMaterialOffset] = useState(0);
  const [linksPage, setLinksPage] = useState<TestSkuLinkView[]>([]), [linkTotal, setLinkTotal] = useState(0), [linkOffset, setLinkOffset] = useState(0);
  const [refresh, setRefresh] = useState(0), [caseId, setCaseId] = useState(""), [record, setRecord] = useState<TestEventGoldenCase | null>(null);
  const [setId, setSetId] = useState(""), [frozen, setFrozen] = useState<TestEventGoldenSet | null>(null);
  const [history, setHistory] = useState<{ kind: "case" | "set"; value: TestEventGoldenCase | TestEventGoldenSet } | null>(null);
  const [title, setTitle] = useState(""), [evidenceNote, setEvidenceNote] = useState(""), [expectedText, setExpectedText] = useState(blankExpected);
  const [materials, setMaterials] = useState<TestEventGoldenMaterial[]>([]), [linkRefs, setLinkRefs] = useState<TestEventGoldenLinkRef[]>([]);
  const [rightsAccepted, setRightsAccepted] = useState<Record<string, boolean>>({}), [downloaded, setDownloaded] = useState<Record<string, string>>({});
  const [opened, setOpened] = useState<Record<string, boolean>>({}), [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [operator, setOperator] = useState(""), [reason, setReason] = useState(""), [reviewAction, setReviewAction] = useState<TestEventGoldenReviewRequest["action"]>("approve");
  const [selected, setSelected] = useState<TestEventGoldenCaseRef[]>([]), [collectionTitle, setCollectionTitle] = useState("");
  const [collectionOperator, setCollectionOperator] = useState(""), [collectionReason, setCollectionReason] = useState("");
  const [setAction, setSetAction] = useState<"freeze" | "revoke">("freeze"), [freezeConfirmed, setFreezeConfirmed] = useState(false);
  const [evaluation, setEvaluation] = useState<TestEventGoldenEvaluation | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const requests = useRef(new Set<AbortController>()), writing = useRef(false);
  const administrator = !!auth.state.user?.is_admin;
  const current = (request: AbortController) => !request.signal.aborted && auth.isCurrentOwner(ownerEpoch);
  const controller = () => { const value = new AbortController(); requests.current.add(value); return value; };
  const locked = busy || !!pending;
  const currentView = !readOnly && !!auth.state.user;
  const eventCurrent = currentView && event.state === "active";
  const reviewSignatureEditable = currentView && administrator && !!record;
  const draftDirty = !!record && (title !== record.title || evidenceNote !== record.evidence_note || expectedText !== json(record.expected)
    || json(materials) !== json(record.materials) || json(linkRefs) !== json(record.link_refs));
  const eventBindingChanged = !!record && record.event_ref.event_revision_id !== event.revision_id;
  const caseDirty = draftDirty || eventBindingChanged;
  const materialChoice = (item: TestEventGoldenMaterial) => materialsPage.find(row => row.id === item.document_id
    && row.raw_hash === item.expected_raw_hash && row.metadata_hash === item.expected_metadata_hash);
  const materialOpened = (item: TestEventGoldenMaterial) => downloaded[item.document_id] === `${item.expected_raw_hash}:${item.expected_metadata_hash}` && opened[item.document_id];
  const canReview = !!record && record.is_current && !draftDirty && administrator && currentView && record.actor_user_id !== userId
    && !locked && !!operator.trim() && !!reason.trim() && reviewConfirmed
    && (reviewAction !== "approve" || (eventCurrent && !eventBindingChanged && !record.blockers.length && record.materials.every(materialOpened)));
  const canSetWrite = administrator && currentView && (setAction === "revoke" ? frozen?.state === "frozen" : eventCurrent);

  useEffect(() => () => { requests.current.forEach(request => request.abort()); requests.current.clear(); }, []);
  useEffect(() => {
    const request = controller(); setError("");
    void tireApi.testEventGoldenCases(event.id, request.signal, caseOffset).then(value => { if (current(request)) {
      if (value.items.some(item => item.event_id !== event.id)) throw new Error("Golden 样本列表事件范围不符。");
      setCases(value.items); setCaseTotal(value.total);
    } }).catch(cause => { if (current(request)) setError(errorText(cause)); }).finally(() => requests.current.delete(request));
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event.id, caseOffset, refresh, ownerEpoch]);
  useEffect(() => {
    const request = controller();
    void tireApi.testEventGoldenCases(undefined, request.signal, allOffset).then(value => { if (current(request)) { setAllCases(value.items); setAllTotal(value.total); } })
      .catch(cause => { if (current(request)) setError(errorText(cause)); }).finally(() => requests.current.delete(request));
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allOffset, refresh, ownerEpoch]);
  useEffect(() => {
    const request = controller();
    void tireApi.testEventGoldenSets(request.signal, setOffset).then(value => { if (current(request)) { setSets(value.items); setSetTotal(value.total); } })
      .catch(cause => { if (current(request)) setError(errorText(cause)); }).finally(() => requests.current.delete(request));
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setOffset, refresh, ownerEpoch]);
  useEffect(() => {
    const request = controller();
    void tireApi.testSkuLinkMaterials(materialOffset, request.signal).then(value => { if (current(request)) { setMaterialsPage(value.items); setMaterialTotal(value.total); } })
      .catch(cause => { if (current(request)) setError(errorText(cause)); }).finally(() => requests.current.delete(request));
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialOffset, refresh, ownerEpoch]);
  useEffect(() => {
    const request = controller();
    void tireApi.testSkuLinks(event.id, linkOffset, request.signal).then(value => { if (current(request)) {
      if (value.items.some(item => item.selection.event_id !== event.id)) throw new Error("身份关系列表事件范围不符。");
      setLinksPage(value.items); setLinkTotal(value.total);
    } }).catch(cause => { if (current(request)) setError(errorText(cause)); }).finally(() => requests.current.delete(request));
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event.id, linkOffset, refresh, ownerEpoch]);
  useEffect(() => {
    setRecord(null); setDownloaded({}); setOpened({}); setReviewConfirmed(false); setHistory(null);
    if (!caseId) return;
    const request = controller();
    void tireApi.testEventGoldenCase(caseId, request.signal).then(value => { if (current(request)) {
      if (value.id !== caseId || value.event_id !== event.id) throw new Error("样本详情与当前场次不匹配。");
      acceptCase(value);
    } }).catch(cause => { if (current(request)) setError(errorText(cause)); }).finally(() => requests.current.delete(request));
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, refresh, ownerEpoch]);
  useEffect(() => {
    setFrozen(null); setEvaluation(null);
    if (!setId) return;
    const request = controller();
    void tireApi.testEventGoldenSet(setId, request.signal).then(value => { if (current(request)) {
      if (value.id !== setId) throw new Error("冻结集详情与选择不匹配。");
      setFrozen(value); setCollectionTitle(value.title); setSetAction("freeze"); setSelected([]); setFreezeConfirmed(false);
    } }).catch(cause => { if (current(request)) setError(errorText(cause)); }).finally(() => requests.current.delete(request));
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setId, refresh, ownerEpoch]);

  function acceptCase(value: TestEventGoldenCase) {
    setRecord(value); setCaseId(value.id); setTitle(value.title); setEvidenceNote(value.evidence_note);
    setExpectedText(json(value.expected)); setMaterials(value.materials); setLinkRefs(value.link_refs);
    setRightsAccepted({}); setDownloaded({}); setOpened({}); setReviewConfirmed(false); setReason("");
  }
  function newCase() {
    setCaseId(""); setRecord(null); setTitle(""); setEvidenceNote(""); setExpectedText(blankExpected()); setMaterials([]); setLinkRefs([]);
    setRightsAccepted({}); setDownloaded({}); setOpened({}); setReviewConfirmed(false); setHistory(null); setError(""); setNotice("");
  }
  function remember(value: Attempt | null) { if (value) unresolved.set(scope, value); else unresolved.delete(scope); setPending(value); }
  async function perform(attempt: Attempt) {
    if (writing.current) return;
    const request = controller(); writing.current = true; remember(attempt); setBusy(true); setError(""); setNotice(""); setEvaluation(null);
    try {
      if (attempt.action === "create-case" || attempt.action === "revise-case" || attempt.action === "review-case") {
        const value = attempt.action === "create-case" ? await tireApi.testEventGoldenCreateCase(attempt.payload, attempt.key, request.signal)
          : attempt.action === "revise-case" ? await tireApi.testEventGoldenReviseCase(attempt.id, attempt.payload, attempt.key, request.signal)
          : await tireApi.testEventGoldenReviewCase(attempt.id, attempt.payload, attempt.key, request.signal);
        if (!current(request)) return;
      if (value.event_id !== attempt.eventId || (attempt.action !== "create-case" && value.id !== attempt.id)
        || (attempt.action === "review-case" ? (value.recorded_review?.revision ?? value.review_revision) : value.revision) !== attempt.payload.expected_revision + 1)
        throw new Error("返回的样本范围或修订不符，请保留 UUID 核对。");
        acceptCase(value); setCaseOffset(0); setAllOffset(0); setNotice(attempt.action === "review-case" ? "人工决定已追加并绑定精确内容；真人资格仍待外部审核。" : "已保存待审修订；旧审核不会自动转移。");
      } else {
        const value = attempt.action === "create-set" ? await tireApi.testEventGoldenCreateSet(attempt.payload, attempt.key, request.signal)
          : await tireApi.testEventGoldenReviseSet(attempt.id, attempt.payload, attempt.key, request.signal);
        if (!current(request)) return;
        if ((attempt.action === "revise-set" && value.id !== attempt.id) || value.revision !== attempt.payload.expected_revision + 1)
          throw new Error("返回的集合范围或修订不符，请保留 UUID 核对。");
        setSetId(value.id); setFrozen(value); setSelected([]); setFreezeConfirmed(false); setSetOffset(0);
        setNotice(value.state === "revoked" ? "已追加撤回修订，历史记录仍可读取。" : "已冻结精确样本与审核指纹；请分别核对冻结版本和当前版本。");
      }
      remember(null); setRefresh(value => value + 1);
    } catch (cause) {
      if (current(request)) { setError(errorText(cause)); setReviewConfirmed(false); setFreezeConfirmed(false);
        if (cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status)
          && cause.code !== "test_event_golden_idempotency_payload_mismatch") remember(null);
      }
    } finally { writing.current = false; requests.current.delete(request); if (current(request)) setBusy(false); }
  }
  async function readHistory(kind: "case" | "set", id: string, revision: number) {
    if (locked) return;
    const request = controller(); setBusy(true); setError(""); setHistory(null);
    try {
      const value = kind === "case" ? await tireApi.testEventGoldenCase(id, request.signal, revision) : await tireApi.testEventGoldenSet(id, request.signal, revision);
      if (current(request)) { if (value.id !== id || value.revision !== revision
        || (kind === "case" && (!("event_id" in value) || value.event_id !== event.id)))
        throw new Error("历史修订范围不符，未展示。"); setHistory({ kind, value }); }
    } catch (cause) { if (current(request)) setError(errorText(cause)); }
    finally { requests.current.delete(request); if (current(request)) setBusy(false); }
  }
  async function downloadMaterial(item: TestEventGoldenMaterial) {
    const choice = materialChoice(item);
    if (!choice || locked) return;
    const request = controller(); setBusy(true); setError("");
    try {
      const blob = await tireApi.documentContent(choice.id, request.signal);
      if (!current(request)) return;
      if (blob.type.split(";")[0].trim().toLowerCase() !== "application/pdf" || blob.size !== choice.byte_count) throw new Error("PDF 类型或字节数与材料目录不符。");
      const rawHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())), byte => byte.toString(16).padStart(2, "0")).join("");
      if (!current(request)) return;
      if (rawHash !== item.expected_raw_hash || choice.metadata_hash !== item.expected_metadata_hash) throw new Error("材料 SHA 或元数据指纹变化，不能作为本次审核原件。");
      const result = await platform.saveDownload({ blob, filename: `test-golden-material-${rawHash}.pdf`, signal: request.signal,
        assertCurrent: () => { if (!current(request)) throw new Error("账户或场次已变化。"); } });
      if (!current(request)) return;
      if (result.saved) { setDownloaded(previous => ({ ...previous, [item.document_id]: `${rawHash}:${choice.metadata_hash}` }));
        setNotice("完整 PDF 校验后已交付保存。请自行打开核读，再单独勾选人工核对；下载不证明阅读。"); }
    } catch (cause) { if (current(request)) setError(errorText(cause)); }
    finally { requests.current.delete(request); if (current(request)) setBusy(false); }
  }
  function addMaterial(choice: BridgeMaterialChoice) {
    if (locked || materials.length >= 3 || materials.some(item => item.document_id === choice.id)) return;
    setMaterials(current => [...current, { document_id: choice.id, expected_raw_hash: choice.raw_hash, expected_metadata_hash: choice.metadata_hash,
      event_locator: blankLocator(), participant_locator: blankLocator(), rights: { rights_holder: "", basis: "", store_original: true,
        workspace_reopen: true, quote_identifiers: true, quote_test_results: true } }]);
    setRightsAccepted(current => ({ ...current, [choice.id]: false })); setReviewConfirmed(false);
  }
  function updateMaterial(index: number, value: TestEventGoldenMaterial) {
    setMaterials(current => current.map((item, at) => at === index ? value : item));
    setRightsAccepted(current => ({ ...current, [value.document_id]: false })); setDownloaded({}); setOpened({}); setReviewConfirmed(false);
  }
  function saveCase() {
    if (locked || !eventCurrent || !title.trim() || !evidenceNote.trim() || !operator.trim() || !reason.trim() || !materials.length
      || materials.some(item => !rightsAccepted[item.document_id] || !item.rights.rights_holder.trim() || !item.rights.basis.trim()
        || !item.event_locator.region.trim() || !item.event_locator.quote.trim() || !item.participant_locator.region.trim() || !item.participant_locator.quote.trim())
      || (record && (!record.is_current || !caseDirty))) return;
    try {
      const parsed = JSON.parse(expectedText) as TestEventGoldenExpected;
      if (!parsed || typeof parsed !== "object" || !parsed.event || !Array.isArray(parsed.identity_assertions) || !Array.isArray(parsed.distinct_pairs)) throw new Error("请填写完整的独立预期 JSON。");
      const payload: TestEventGoldenContent = { title: title.trim(), event_ref: { event_id: event.id, event_revision_id: event.revision_id,
        event_fingerprint: event.fingerprint }, materials: structuredClone(materials), link_refs: structuredClone(linkRefs), expected: parsed,
        evidence_note: evidenceNote.trim(), operator: operator.trim(), reason: reason.trim(), expected_revision: record?.revision || 0,
        expected_fingerprint: record?.fingerprint || null };
      void perform(record ? { action: "revise-case", eventId: event.id, id: record.id, payload, key: crypto.randomUUID() }
        : { action: "create-case", eventId: event.id, payload, key: crypto.randomUUID() });
    } catch (cause) { setError(cause instanceof SyntaxError ? "预期 JSON 格式无效。" : errorText(cause)); }
  }
  function reviewCase() {
    if (!record || !canReview) return;
    const payload: TestEventGoldenReviewRequest = { case_revision: record.revision, case_fingerprint: record.fingerprint,
      action: reviewAction, acknowledged: true, opened_materials: reviewAction === "approve" ? record.materials.map(item => ({ document_id: item.document_id,
        raw_hash: item.expected_raw_hash, metadata_hash: item.expected_metadata_hash })) : [], operator: operator.trim(), reason: reason.trim(),
      expected_revision: record.review_revision, expected_fingerprint: record.review_fingerprint };
    void perform({ action: "review-case", eventId: event.id, id: record.id, payload, key: crypto.randomUUID() });
  }
  function toggleCase(item: TestEventGoldenCaseSummary) {
    if (item.review_status !== "approved" || !item.review_fingerprint || item.blockers.length || locked) return;
    setSelected(current => current.some(row => row.case_id === item.id) ? current.filter(row => row.case_id !== item.id)
      : current.length < 3 ? [...current, { case_id: item.id, case_revision: item.revision, case_fingerprint: item.fingerprint,
        review_revision: item.review_revision, review_fingerprint: item.review_fingerprint! }] : current);
    setFreezeConfirmed(false);
  }
  function writeSet() {
    if (locked || !canSetWrite || !freezeConfirmed || !collectionTitle.trim() || !collectionOperator.trim()
      || !collectionReason.trim() || (setAction === "freeze" && !selected.length) || (setId && !frozen)) return;
    const payload: TestEventGoldenSetWrite = { title: collectionTitle.trim(), action: setAction, case_refs: setAction === "freeze" ? structuredClone(selected) : [],
      acknowledged: true, operator: collectionOperator.trim(), reason: collectionReason.trim(), expected_revision: frozen?.revision || 0,
      expected_fingerprint: frozen?.fingerprint || null };
    void perform(frozen ? { action: "revise-set", eventId: event.id, id: frozen.id, payload, key: crypto.randomUUID() }
      : { action: "create-set", eventId: event.id, payload, key: crypto.randomUUID() });
  }
  async function evaluate(target: "frozen_revision" | "current_head") {
    if (!frozen || locked) return;
    const request = controller(); setBusy(true); setError(""); setEvaluation(null);
    try {
      const value = await tireApi.testEventGoldenEvaluateSet(frozen.id, { expected_set_revision: frozen.revision,
        expected_set_fingerprint: frozen.fingerprint, target }, request.signal);
      if (current(request)) { if (value.set_id !== frozen.id || value.set_revision !== frozen.revision
        || value.set_fingerprint !== frozen.fingerprint || value.target !== target
        || value.human_truth_status !== "pending_external_review" || value.wrong_merge_count !== null) throw new Error("差异结果范围或人工资格合同不符。"); setEvaluation(value); }
    } catch (cause) { if (current(request)) setError(errorText(cause)); }
    finally { requests.current.delete(request); if (current(request)) setBusy(false); }
  }

  return <section className="test-event-golden golden-workspace quarantine-panel" aria-label="测试真值与复核">
    <div className="panel-title"><span>测试真值与复核 · 本机场次 Golden</span><button type="button" className="secondary-button" disabled={locked} onClick={() => { setRefresh(value => value + 1); setHistory(null); setEvaluation(null); }}>重新读取</button></div>
    <p className="quality-intro">独立预期、人工审核和冻结集只用于本机核对。事件是人工转录、来源未在线核验；署名是本地自报，真人 Golden 资格仍待外部审核。</p>
    <p className="review-boundary">场次 {event.title} · 修订 #{event.revision} · {short(event.revision_id)} · {event.state === "revoked" ? "已撤销" : "当前读取"}。不同场次成绩不直接排名。</p>
    {!administrator ? <p className="review-boundary">当前可读取与保存待审稿；审核及冻结/撤回须管理员账户，且内容作者不能以同一账户自审。</p> : null}
    {readOnly ? <p className="review-boundary">当前打开的是指定历史事件修订，仅可读取样本、历史与已有冻结集的差异。</p> : event.state === "revoked" ? <p className="review-boundary">事件已撤销：不能新建、批准或冻结；仍可撤回既有审核或集合。</p> : null}
    {[...unresolved.entries()].filter(([key, item]) => key === scopeKey(userId, item.eventId) && item.eventId !== event.id).map(([, item]) => <p key={item.key} className="review-boundary">此账户的事件 {short(item.eventId)} 还有固定请求 {item.key} 待核对；请返回对应场次。</p>)}
    {pending ? <div className="review-boundary"><strong>上一次写入待核对</strong><p>固定 UUID {pending.key}。关闭场次不撤销已受理请求；只能用同一正文和 UUID 重试。</p>
      <JsonDetails label="固定请求内容" value={pending.payload} /><button type="button" className="secondary-button" disabled={busy} onClick={() => void perform(pending)}>重放并核对同一次请求</button></div> : null}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p role="status" className="review-saved">{notice}</p> : null}

    <section className="review-boundary"><div className="panel-title"><h4>1 · 独立预期与待审样本</h4><button type="button" className="secondary-button" disabled={locked || !eventCurrent} onClick={newCase}>新建待审样本</button></div>
      {cases.map(item => <button type="button" className="report-list-item" key={item.id} aria-pressed={caseId === item.id} disabled={locked} onClick={() => setCaseId(item.id)}>
        <strong>{item.title} · #{item.revision}</strong><span>{item.review_status} · {item.blockers.length ? `阻断 ${item.blockers.join("、")}` : "无当前阻断"}</span><small>{stamp(item.created_at)} · {short(item.id)}</small></button>)}
      {!caseTotal ? <p>本场尚无 Golden 待审样本。</p> : null}<Pages label="本场样本" offset={caseOffset} total={caseTotal} step={10} busy={locked} onChange={setCaseOffset} />
      {caseId && !record ? <p role="status">正在读取所选样本…</p> : null}
      {(!caseId || record) ? <form className="review-form" onSubmit={submit => { submit.preventDefault(); saveCase(); }}>
        <h5>{record ? `编辑待审修订 #${record.revision}` : "新建独立预期"}</h5>
        <label><span>样本标题</span><input maxLength={200} value={title} disabled={locked || !eventCurrent} onChange={change => setTitle(change.target.value)} /></label>
        <label><span>原文定位与人工核对说明</span><textarea rows={3} maxLength={2000} value={evidenceNote} disabled={locked || !eventCurrent} onChange={change => setEvidenceNote(change.target.value)} /></label>
        <p>预期必须独立核对来源原件；空模板和本场转录都不是人工真值。`raw_value`、尾零、来源名次、单位及测试条件请按原文保留。</p>
        <label><span>独立预期 JSON</span><textarea className="golden-json-editor" rows={18} spellCheck={false} value={expectedText} disabled={locked || !eventCurrent} onChange={change => setExpectedText(change.target.value)} /></label>
        <button type="button" className="text-button" disabled={locked || !eventCurrent} onClick={() => { setExpectedText(json({ event: structuredClone(event.event), identity_assertions: [], distinct_pairs: [] })); setNotice("当前人工转录仅复制到未保存草稿；还须逐项对照 PDF 原件，补足身份断言并另行审核。"); }}>显式复制当前人工转录为待审草稿</button>
        <h5>供审 PDF 材料 · 最多 3 份</h5><div className="parser-bundle-options">{materialsPage.map(choice => <article key={choice.id}><p>{choice.title} · {choice.byte_count.toLocaleString()} 字节 · {short(choice.raw_hash)}</p><button type="button" className="secondary-button" disabled={locked || !eventCurrent || materials.length >= 3 || materials.some(item => item.document_id === choice.id)} onClick={() => addMaterial(choice)}>选择此 PDF 原件</button></article>)}</div>
        <Pages label="PDF 材料" offset={materialOffset} total={materialTotal} step={50} busy={locked} onChange={setMaterialOffset} />
        {materials.map((item, index) => <fieldset className="review-boundary" key={item.document_id}><legend>材料 {index + 1} · {short(item.document_id)}</legend>
          <p>完整 SHA {item.expected_raw_hash}；元数据指纹 {item.expected_metadata_hash}</p>
          <button type="button" className="text-button" disabled={locked || !eventCurrent} onClick={() => { setMaterials(value => value.filter(row => row.document_id !== item.document_id)); setReviewConfirmed(false); }}>移除此材料</button>
          <label><span>权利人声明</span><input value={item.rights.rights_holder} disabled={locked || !eventCurrent} onChange={change => updateMaterial(index, { ...item, rights: { ...item.rights, rights_holder: change.target.value } })} /></label>
          <label><span>留存、重开及短引文依据</span><textarea value={item.rights.basis} disabled={locked || !eventCurrent} onChange={change => updateMaterial(index, { ...item, rights: { ...item.rights, basis: change.target.value } })} /></label>
          {(["event_locator", "participant_locator"] as const).map(field => <div key={field}><strong>{field === "event_locator" ? "场次定位" : "参测对象定位"}</strong>
            <label><span>页码</span><input type="number" min={1} value={item[field].page} disabled={locked || !eventCurrent} onChange={change => updateMaterial(index, { ...item, [field]: { ...item[field], page: Number(change.target.value) } })} /></label>
            <label><span>原件区域</span><input value={item[field].region} disabled={locked || !eventCurrent} onChange={change => updateMaterial(index, { ...item, [field]: { ...item[field], region: change.target.value } })} /></label>
            <label><span>原文短引文</span><input value={item[field].quote} disabled={locked || !eventCurrent} onChange={change => updateMaterial(index, { ...item, [field]: { ...item[field], quote: change.target.value } })} /></label></div>)}
          <label className="review-checkbox"><input type="checkbox" checked={!!rightsAccepted[item.document_id]} disabled={locked || !eventCurrent} onChange={change => setRightsAccepted(value => ({ ...value, [item.document_id]: change.target.checked }))} /><span>我明确声明有权在本地留存、重开并引用身份与测试结果短摘录；系统不认证许可真实性。</span></label>
        </fieldset>)}
        <h5>本场精确 SKU 证据关系引用 · 可选，身份断言另填</h5>
        {event.participants.map(participant => <label key={participant.key}><span>{participant.brand} {participant.model} · {participant.key}</span><select value={linkRefs.find(item => item.participant_key === participant.key)?.link_id || ""} disabled={locked || !eventCurrent} onChange={change => {
          const choice = linksPage.find(item => item.id === change.target.value);
          setLinkRefs(current => [...current.filter(item => item.participant_key !== participant.key), ...(choice?.id && choice.revision_id ? [{ participant_key: participant.key, link_id: choice.id, link_revision_id: choice.revision_id, link_fingerprint: choice.fingerprint }] : [])]);
        }}><option value="">不引用关系</option>{linkRefs.find(item => item.participant_key === participant.key && !linksPage.some(choice => choice.id === item.link_id))
          ? <option value={linkRefs.find(item => item.participant_key === participant.key)!.link_id}>已选关系不在当前页 · {short(linkRefs.find(item => item.participant_key === participant.key)!.link_id)}</option> : null}
          {linksPage.filter(item => item.id && item.revision_id && item.selection.event_revision_id === event.revision_id && item.selection.participant_key === participant.key)
            .map(item => <option key={item.id} value={item.id!}>{short(item.id!)} · 修订 #{item.revision} · {item.eligibility === "conditional_reviewed_transcription" ? "有限人工关联" : "当前未关联"}{item.blockers.length ? ` · 阻断 ${item.blockers.join("、")}` : ""}</option>)}</select></label>)}
        <Pages label="本场身份关系" offset={linkOffset} total={linkTotal} step={50} busy={locked} onChange={setLinkOffset} />
        <p>关系引用不会自动决定 linked/not_linked，也不按名称或尺寸猜测 SKU。</p>
        <label><span>本次操作署名（本地自报）</span><input maxLength={100} value={operator} disabled={locked || !(eventCurrent || reviewSignatureEditable)} onChange={change => { setOperator(change.target.value); setReviewConfirmed(false); }} /></label>
        <label><span>保存或审核理由</span><textarea maxLength={2000} value={reason} disabled={locked || !(eventCurrent || reviewSignatureEditable)} onChange={change => { setReason(change.target.value); setReviewConfirmed(false); }} /></label>
        <button type="submit" className="primary-button" disabled={locked || !eventCurrent || !materials.length || !title.trim() || !evidenceNote.trim() || !operator.trim() || !reason.trim() || (record ? !record.is_current || !caseDirty : false)}>保存待审修订</button>
      </form> : null}
    </section>

    {record ? <section className="review-boundary" aria-label="审核测试事件 Golden 样本"><h4>2 · 审核已保存的精确内容</h4><p>样本 #{record.revision} · {record.review_status} · 内容指纹 {record.fingerprint}</p>
      {record.blockers.length ? <p className="inline-error">当前阻断：{record.blockers.join("、")}</p> : null}
      {draftDirty ? <p className="inline-error">有未保存的修改。请先保存新待审修订，再审核该修订。</p> : null}
      {eventBindingChanged ? <p className="inline-error">场次已产生新修订；旧样本不能批准，但可明确拒绝或撤回原审核。</p> : null}
      <JsonDetails label="已保存的独立预期、场次快照与关系引用" value={{ expected: record.expected, event_ref: record.event_ref, event_snapshot: record.event_snapshot, link_refs: record.link_refs, evidence_note: record.evidence_note }} />
      {record.materials.map(item => <div className="review-boundary" key={item.document_id}><p>原件 {short(item.document_id)} · SHA {item.expected_raw_hash}</p>
        <button type="button" className="secondary-button" disabled={locked || !materialChoice(item)} onClick={() => void downloadMaterial(item)}>校验完整 SHA 并下载供审原件</button>
        {!materialChoice(item) ? <p>请在上方材料目录翻页找到与冻结 SHA、元数据指纹相同的原件后再下载。</p> : null}
        <label className="review-checkbox"><input type="checkbox" checked={!!opened[item.document_id]} disabled={locked || downloaded[item.document_id] !== `${item.expected_raw_hash}:${item.expected_metadata_hash}`} onChange={change => { setOpened(value => ({ ...value, [item.document_id]: change.target.checked })); setReviewConfirmed(false); }} /><span>我已自行打开并核读此完整 PDF，逐项对照测试条件、参测对象、原始成绩与定位。这只是本账户声明，下载不证明阅读。</span></label>
      </div>)}
      <label><span>人工决定</span><select value={reviewAction} disabled={locked || !administrator || !currentView} onChange={change => { setReviewAction(change.target.value as TestEventGoldenReviewRequest["action"]); setReviewConfirmed(false); }}><option value="approve">确认当前预期</option><option value="reject">不认可当前预期</option><option value="revoke">撤回审核</option></select></label>
      {record.actor_user_id === userId ? <p className="review-boundary">当前账户是内容作者，不能自审；请由另一位管理员账户核对原件后签署。</p> : null}
      <label className="review-checkbox"><input type="checkbox" checked={reviewConfirmed} disabled={locked || !administrator || !currentView || draftDirty || record.actor_user_id === userId || (reviewAction === "approve" && (!eventCurrent || eventBindingChanged || !!record.blockers.length || !record.materials.every(materialOpened)))} onChange={change => setReviewConfirmed(change.target.checked)} /><span>我已核对固定修订、材料与独立预期，确认作出所选决定；本地签署不等于真人 Golden 资格。</span></label>
      <button type="button" className="primary-button" disabled={!canReview} onClick={reviewCase}>签署当前测试预期修订</button>
      <JsonDetails label="当前审核与审核历史" value={{ latest_review: record.latest_review, reviews: record.reviews }} />
      <details className="quality-technical"><summary>读取指定样本历史（只读）</summary>{record.history.map(item => <p key={item.revision}>#{item.revision} · {stamp(item.created_at)} <button type="button" className="text-button" disabled={locked} onClick={() => void readHistory("case", record.id, item.revision)}>读取历史 #{item.revision}</button></p>)}</details>
    </section> : null}

    <section className="review-boundary" aria-label="冻结测试事件 Golden 集合"><div className="panel-title"><h4>3 · 冻结和撤回独立集合</h4><button type="button" className="secondary-button" disabled={locked || !administrator || !eventCurrent} onClick={() => { setSetId(""); setFrozen(null); setCollectionTitle(""); setSetAction("freeze"); setSelected([]); setFreezeConfirmed(false); setEvaluation(null); }}>新建冻结集合</button></div>
      <p>可选 1–3 个当前有效的已审核样本；不同事件仍分别核对，不拼接跨测试总榜。</p>
      {sets.map(item => <button type="button" className="report-list-item" key={item.id} aria-pressed={setId === item.id} disabled={locked} onClick={() => setSetId(item.id)}><strong>{item.title} · #{item.revision}</strong><span>{item.state === "revoked" ? "已撤回" : item.eligible ? "当前可核对" : "当前有阻断"}</span><small>{stamp(item.created_at)} · {short(item.id)}</small></button>)}
      <Pages label="冻结集合" offset={setOffset} total={setTotal} step={10} busy={locked} onChange={setSetOffset} />
      {frozen ? <div className="review-boundary"><p>集合 #{frozen.revision} · {frozen.fingerprint}</p>{frozen.blockers.length ? <p className="inline-error">当前阻断：{frozen.blockers.join("、")}</p> : null}
        {frozen.state === "revoked" ? <p>当前集合已撤回。可重新选择当前有效的样本及审核指纹，明确追加新的冻结修订；旧冻结历史仍不可作为当前集合使用。</p> : null}
        <JsonDetails label="已冻结的精确样本与审核指纹" value={{ case_refs: frozen.case_refs, cases: frozen.cases }} />
        <div className="test-event-actions"><button type="button" className="secondary-button" disabled={locked || frozen.state !== "frozen"} onClick={() => void evaluate("frozen_revision")}>核对冻结版本</button>
          <button type="button" className="secondary-button" disabled={locked || frozen.state !== "frozen"} onClick={() => void evaluate("current_head")}>核对当前版本</button></div>
        <details className="quality-technical"><summary>读取指定冻结历史（只读）</summary>{frozen.history.map(item => <p key={item.revision}>#{item.revision} · {item.action} · {stamp(item.created_at)} <button type="button" className="text-button" disabled={locked} onClick={() => void readHistory("set", frozen.id, item.revision)}>读取历史 #{item.revision}</button></p>)}</details>
      </div> : null}
      {evaluation ? <EvaluationView value={evaluation} /> : null}
      <h5>选择当前有效的已审核样本</h5>{allCases.map(item => <label className="review-checkbox" key={item.id}><input type="checkbox" checked={selected.some(row => row.case_id === item.id)} disabled={locked || !administrator || !eventCurrent || item.review_status !== "approved" || !!item.blockers.length || (!selected.some(row => row.case_id === item.id) && selected.length >= 3)} onChange={() => toggleCase(item)} /><span>{item.title} · #{item.revision} · {short(item.event_id)} · {item.review_status}{item.blockers.length ? ` · ${item.blockers.join("、")}` : ""}</span></label>)}
      <Pages label="全部审核样本" offset={allOffset} total={allTotal} step={10} busy={locked} onChange={setAllOffset} />
      <form className="review-form" onSubmit={submit => { submit.preventDefault(); writeSet(); }}>
        <label><span>集合标题</span><input maxLength={200} value={collectionTitle} disabled={locked || !canSetWrite} onChange={change => { setCollectionTitle(change.target.value); setFreezeConfirmed(false); }} /></label>
        {frozen ? <label><span>集合操作</span><select value={setAction} disabled={locked || !administrator || !currentView} onChange={change => { setSetAction(change.target.value as "freeze" | "revoke"); setFreezeConfirmed(false); }}><option value="freeze">重新冻结所选审核修订</option><option value="revoke">撤回当前集合</option></select></label> : null}
        {setAction === "freeze" ? <JsonDetails label={`将冻结的 ${selected.length}/3 个样本精确引用`} value={selected} /> : <p>撤回后历史仍可读取；不能用作新的有效集合。</p>}
        <label><span>集合操作署名（本地自报）</span><input maxLength={100} value={collectionOperator} disabled={locked || !canSetWrite} onChange={change => { setCollectionOperator(change.target.value); setFreezeConfirmed(false); }} /></label>
        <label><span>冻结或撤回理由</span><textarea maxLength={2000} value={collectionReason} disabled={locked || !canSetWrite} onChange={change => { setCollectionReason(change.target.value); setFreezeConfirmed(false); }} /></label>
        <label className="review-checkbox"><input type="checkbox" checked={freezeConfirmed} disabled={locked || !canSetWrite} onChange={change => setFreezeConfirmed(change.target.checked)} /><span>已核对本次集合操作、全部样本和审核指纹。冻结不等于评估或真人审核通过。</span></label>
        <button type="submit" className="primary-button" disabled={locked || !canSetWrite || !freezeConfirmed || !collectionTitle.trim() || !collectionOperator.trim() || !collectionReason.trim() || (setAction === "freeze" && !selected.length)}>提交冻结或撤回修订</button>
      </form>
    </section>
    {history ? <section className="review-boundary"><h4>{history.kind === "case" ? "样本" : "集合"}历史 #{history.value.revision} · 只读</h4><p>历史修订不会替换当前编辑状态或恢复当前有效资格。</p><JsonDetails label="历史修订完整内容" value={history.value} /><button type="button" className="text-button" onClick={() => setHistory(null)}>收起历史</button></section> : null}
  </section>;
}
