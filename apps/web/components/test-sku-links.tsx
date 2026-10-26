"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type {
  BridgeAction, BridgeAssertion, BridgeDecision, BridgeEvidenceLevel, BridgeIdentityField,
  BridgeLocator, BridgeMaterial, BridgeMaterialChoice, BridgeMaterialsPage, BridgeOpenedMaterial,
  BridgePreviewRequest, BridgeSelection, EvidenceDocumentMetadata, FitmentTireEvidencePage,
  IdentityCandidates, TestEventDetail, TestSkuLinkDetail, TestSkuLinkPage, TestSkuLinkPreview, TestSkuLinkView,
} from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { useWorkbenchPlatform } from "./workbench-platform";
import "./test-sku-links.css";

const fields: Record<BridgeIdentityField, string> = {
  brand: "品牌", model: "型号", manufacturer_product_code: "产品代码", product_code_type: "代码命名空间",
  region: "市场 / 地区", size: "尺寸（R / ZR 分别保留）", load_index: "载重指数", speed_rating: "速度级别",
  xl: "XL", hl: "HL", oe_mark: "OE 标记", acoustic_technology: "静音技术", run_flat: "缺气保用",
  gtin: "GTIN", technology_features: "技术配置数组", eprel_id: "EPREL 标识",
};
const actionText: Record<BridgeAction, string> = { create: "保存待复核声明", revise: "修订声明并重新待审", review: "确认双账户人工复核", revoke: "撤销关系", restore: "恢复为待复核" };
const stateText = { pending_review: "声明待复核", reviewed: "已人工复核", revoked: "已撤销", needs_review: "证据变化 · 需重新复核" };
const levelText: Record<BridgeEvidenceLevel, string> = { manual_assertion: "人工关联线索", source_explicit_identifiers_in_supplied_material: "供审材料所载明确标识" };
const checkText = { match: "所声明值一致", conflict: "存在矛盾", unknown: "未知 / 未声明", unsupported: "暂不支持该结构" };
const extraFieldText: Record<string, string> = { test_size_scope: "本场测试尺寸", test_participant_brand: "原参测对象品牌", test_participant_model: "原参测对象型号" };
const staleText: Record<string, string> = {
  event_changed: "测试事件修订已变化", test_event_changed: "测试事件修订已变化", event_revision_changed: "测试事件修订已变化",
  event_revoked: "测试事件已撤销", participant_changed: "参测对象内容已变化", tire_identity_changed: "精确 SKU 身份已变化",
  tire_identity_contract_changed: "身份合同已变化", tire_identity_resolution_changed: "身份决定已变化",
  tire_lifecycle_changed: "SKU 撤销 / 恢复代次已变化", tire_catalogs_changed: "来源目录成员代次已变化",
  material_changed: "原件材料或元数据已变化", material_integrity_failed: "原件完整性校验未通过",
  test_event_revision_changed: "测试事件修订已变化，需重新声明当前版本", test_participant_missing: "当前事件已无原参测对象",
  test_event_revoked: "测试事件已撤销", tire_identity_review_required: "SKU 身份决定需要重新核对",
  tire_lifecycle_revoked: "SKU 已撤销", tire_catalog_membership_changed: "来源目录成员关系已变化",
  material_identity_conflict: "材料标识与精确 SKU 存在矛盾", identity_assertions_incomplete: "实际身份字段的材料声明尚未完整",
  complete_identity_required: "SKU 当前精确身份尚不完整", test_size_scope_mismatch: "本场测试尺寸与所选 SKU 不一致",
  test_participant_brand_mismatch: "原参测对象品牌不一致", test_participant_model_mismatch: "原参测对象型号不一致",
  explicit_identifiers_require_material: "明确标识等级至少需要一份完整材料", material_event_source_scope_mismatch: "材料来源引用与本场测试来源不一致",
  fixed_link_scope_mismatch: "本关系固定的场次或参测对象不一致", revise_required_for_changed_declaration: "已更改声明内容，请先追加声明修订",
  test_sku_self_review: "须由另一管理员账户核对当前声明", restore_required: "须先恢复为待复核，再重新审核",
  link_not_revoked: "本关系尚未撤销，不能执行恢复", test_sku_link_scope_exists: "本场参测对象已有关系，请打开原关系修订",
  test_changed: "事件修订或参测对象绑定已变化", identity_contract_changed: "SKU 身份合同已变化",
  identity_resolution_changed: "SKU 身份决定代次已变化", lifecycle_changed: "SKU 撤销或恢复代次已变化", catalogs_changed: "来源目录出入代次已变化",
};
const valueText = (value: unknown) => value === null || value === undefined || value === "" ? "未声明" : typeof value === "object" ? JSON.stringify(value) : String(value);
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "本次证据操作未完成，请保留当前记录后重试。";
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const hash = (value: string) => /^[a-f0-9]{64}$/.test(value);
const blankLocator = (): BridgeLocator => ({ page: 1, region: "", quote: "" });
const locatorComplete = (value: BridgeLocator) => Number.isInteger(value.page) && value.page >= 1 && value.page <= 100000 && !!value.region.trim() && !!value.quote.trim();
const sameSelection = (a: BridgeSelection, b: BridgeSelection) =>
  (["event_id", "event_revision_id", "participant_key", "variant_id", "tire_snapshot_id", "fact_version_id"] as const).every(key => a[key] === b[key]);
type Attempt = { key: string; payload: BridgeDecision };
// Immutable unresolved writes survive a dialog close or auth revalidation.
// Stable scope keeps an old-revision request discoverable after event updates;
// its original payload can only be retried with the same UUID.
const unresolved = new Map<string, Attempt>();
const MAX_UNRESOLVED = 32;
const attemptScope = (user: string, event: TestEventDetail, participant: string) => JSON.stringify([user, event.id, participant]);

function assertView(view: TestSkuLinkView, eventId: string, participant: string) {
  if (view.schema !== "test-sku-link@1" || view.scope !== "local_workspace" || view.data_state !== "local_snapshot"
    || view.selection.event_id !== eventId || view.selection.participant_key !== participant
    || view.frozen_evidence.test.event_id !== eventId || view.frozen_evidence.test.participant.key !== participant
    || view.frozen_evidence.test.revision_id !== view.selection.event_revision_id
    || view.frozen_evidence.tire.variant_id !== view.selection.variant_id
    || view.frozen_evidence.tire.snapshot_id !== view.selection.tire_snapshot_id
    || view.frozen_evidence.tire.fact_version_id !== view.selection.fact_version_id
    || view.boundary.material_origin !== "operator_supplied" || view.boundary.origin_verification !== "unverified"
    || view.boundary.read_scope !== "local_workspace" || view.boundary.provider_use !== false || view.boundary.export !== false) {
    throw new Error("证据返回的对象、版本或共享材料边界不一致，未采用该结果。");
  }
}

function JsonDetails({ label, value }: { label: string; value: unknown }) {
  return <details className="bridge-technical"><summary>{label}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}
function LocatorFields({ label, value, onChange, disabled }: { label: string; value: BridgeLocator; onChange: (value: BridgeLocator) => void; disabled: boolean }) {
  return <fieldset className="bridge-locator" disabled={disabled}><legend>{label} · 人工定位</legend>
    <label><span>PDF 页码</span><input type="number" min={1} max={100000} required value={value.page} onChange={event => onChange({ ...value, page: Number(event.target.value) })} /></label>
    <label><span>页内区域 / 表格行</span><input maxLength={200} required value={value.region} onChange={event => onChange({ ...value, region: event.target.value })} /></label>
    <label className="bridge-full"><span>对照短引文（最多 300 字）</span><textarea rows={2} maxLength={300} required value={value.quote} onChange={event => onChange({ ...value, quote: event.target.value })} /></label>
  </fieldset>;
}
function ViewEvidence({ view, onOriginal }: { view: TestSkuLinkView; onOriginal: (material: BridgeMaterialChoice) => void }) {
  const test = view.frozen_evidence.test, tire = view.frozen_evidence.tire;
  return <div className="bridge-evidence-review">
    <p className="review-boundary">{view.boundary.notice}</p>
    <div className="bridge-pair"><article><span className="eyebrow">测试场次 / 参测对象</span><h4>{test.event.title}</h4>
      <p>{test.participant.brand} {test.participant.model} · {test.participant.source_designation || "版本描述未披露"}</p>
      <dl><div><dt>原事件修订</dt><dd>#{test.revision} · {test.state === "revoked" ? "已撤销" : "未撤销"}</dd></div><div><dt>测试尺寸 / 机构</dt><dd>{test.event.tested_size} · {test.event.organization}</dd></div><div><dt>测试条件</dt><dd>{test.event.conditions}</dd></div><div><dt>来源关系声明</dt><dd>{test.event.relationship}</dd></div><div><dt>来源 / 留存依据</dt><dd>{test.event.source_url}<br />{test.event.rights_basis}</dd></div></dl>
      <JsonDetails label="完整场次、原参测对象与版本指纹" value={test} /></article>
      <article><span className="eyebrow">明确选择的精确 SKU / 原始事实</span><h4>{valueText(tire.identity.brand)} {valueText(tire.identity.model)}</h4>
        <dl>{Object.entries(tire.identity).map(([field, value]) => <div key={field}><dt>{fields[field as BridgeIdentityField] || field}</dt><dd>{valueText(value)}</dd></div>)}</dl>
        <p>事实版本 #{tire.fact_version} · 原观察时间 {stamp(tire.provenance.observed_at)}</p><p className="bridge-hash">原文 SHA-256 {tire.raw_hash}</p>
        <JsonDetails label="完整原成员、来源事实、精确定位与出处" value={tire} /></article></div>
    <div className="bridge-checks" aria-label="材料声明与精确 SKU 逐字段核对"><div className="bridge-check-heading"><span>身份字段</span><span>材料所载原值</span><span>SKU 原值</span><span>核对</span></div>
      {view.checks.map(check => <div className={`bridge-check-row ${check.status}`} key={check.field}><strong>{fields[check.field as BridgeIdentityField] || extraFieldText[check.field] || check.field}</strong><span>{valueText(check.material_value)}</span><span>{valueText(check.sku_value)}</span><span>{checkText[check.status]}</span></div>)}</div>
    {view.unknown_fields.length ? <p className="review-boundary">未知或未完整声明：{view.unknown_fields.map(field => fields[field as BridgeIdentityField] || field).join("、")}。未知不等于否，不从 SKU 目录补填材料值。</p> : null}
    {view.blockers.length ? <div className="inline-error" role="alert"><strong>当前不能提交 / 不成立的条件</strong><ul>{view.blockers.map(code => <li key={code}>{staleText[code] || code}</li>)}</ul></div> : null}
    {view.material_evidence.map(material => <article className="bridge-material-card" key={material.document_id}><h4>{material.metadata.title} · 原件材料</h4>
      <p>共享工作区 · 操作者提供 · 未在线核验</p><p>{material.metadata.byte_count.toLocaleString()} 字节 · {material.metadata.source_url || "来源链接未声明"}</p><p className="bridge-hash">SHA-256 {material.raw_hash}</p>
      <p>场次对照：第 {material.event_locator.page} 页 · {material.event_locator.region} · {material.event_locator.quote}</p>
      <p>参测对象：第 {material.participant_locator.page} 页 · {material.participant_locator.region} · {material.participant_locator.quote}</p>
      <p>权利人声明：{material.rights.rights_holder}；留存 / 共享重开 / 短引文依据：{material.rights.basis}</p>
      <button className="secondary-button" type="button" onClick={() => onOriginal({ ...material.metadata, metadata_hash: material.metadata_hash })}>校验并下载完整原件</button>
      <JsonDetails label="材料元数据、双侧人工定位与引文哈希" value={material} /></article>)}
    <JsonDetails label="逐项材料短引文、原值与 UTF-8 哈希" value={view.assertions} />
  </div>;
}

export default function TestSkuLinks({ event, readOnly = false }: { event: TestEventDetail; readOnly?: boolean }) {
  const auth = useWorkbenchAuth();
  if (!auth.ready) return <section className="test-sku-links"><h4>参测对象与精确 SKU 证据关系</h4><p role="status">正在重新确认账户，旧预览和操作暂不显示。</p></section>;
  return <BridgeWorkspace key={`${auth.ownerEpoch}:${event.revision_id}`} event={event} readOnly={readOnly} ownerEpoch={auth.ownerEpoch} />;
}
function BridgeWorkspace({ event, readOnly, ownerEpoch }: { event: TestEventDetail; readOnly: boolean; ownerEpoch: number }) {
  const auth = useWorkbenchAuth();
  const [page, setPage] = useState<TestSkuLinkPage | null>(null), [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0);
  const [target, setTarget] = useState<{ participant: string; id: string | null } | null>(null), [error, setError] = useState("");
  const [finding, setFinding] = useState(false);
  const participantRequest = useRef<AbortController | null>(null);
  const awaiting = [...unresolved.entries()].filter(([key, attempt]) => key === attemptScope(auth.state.user?.id || "", event, attempt.payload.selection.participant_key));
  useEffect(() => () => participantRequest.current?.abort(), []);
  async function openParticipant(participant: string) {
    if (!page || finding) return;
    const pending = unresolved.get(attemptScope(auth.state.user?.id || "", event, participant));
    if (pending) { setTarget({ participant, id: pending.payload.link_id }); return; }
    participantRequest.current?.abort(); const request = new AbortController(); participantRequest.current = request;
    setFinding(true); setError("");
    try {
      let loaded = offset === 0 ? page : await tireApi.testSkuLinks(event.id, 0, request.signal);
      let scanned = 0;
      while (true) {
        if (request.signal.aborted || !auth.isCurrentOwner(ownerEpoch)) return;
        if (loaded.schema !== "test-sku-link@1" || loaded.scope !== "local_workspace") throw new Error("关系目录返回范围不一致。");
        loaded.items.forEach(item => assertView(item, event.id, item.selection.participant_key));
        const existing = loaded.items.find(item => item.selection.participant_key === participant);
        if (existing) { setTarget({ participant, id: existing.id }); return; }
        scanned += loaded.items.length;
        if (loaded.offset + loaded.items.length >= loaded.total) { setTarget({ participant, id: null }); return; }
        if (!loaded.items.length || scanned >= 200) throw new Error("尚未完整核对已有关系，未新建声明。请从下方分页列表明确选择已有关系，或缩小并重新读取场次。");
        loaded = await tireApi.testSkuLinks(event.id, loaded.offset + loaded.items.length, request.signal);
      }
    } catch (cause) { if (!request.signal.aborted && auth.isCurrentOwner(ownerEpoch)) setError(errorText(cause)); }
    finally { if (!request.signal.aborted && auth.isCurrentOwner(ownerEpoch)) setFinding(false); }
  }
  useEffect(() => {
    const controller = new AbortController(); setPage(null); setError("");
    void tireApi.testSkuLinks(event.id, offset, controller.signal).then(value => {
      if (controller.signal.aborted || !auth.isCurrentOwner(ownerEpoch)) return;
      if (value.schema !== "test-sku-link@1" || value.scope !== "local_workspace") throw new Error("关系列表合同不一致。");
      value.items.forEach(item => assertView(item, event.id, item.selection.participant_key)); setPage(value);
    }).catch(cause => { if (!controller.signal.aborted && auth.isCurrentOwner(ownerEpoch)) setError(errorText(cause)); });
    return () => controller.abort();
  }, [event.id, offset, refresh, ownerEpoch, auth.isCurrentOwner]);
  return <section className="test-sku-links" aria-label="参测对象与精确 SKU 证据关系">
    <div className="bridge-heading"><div><span className="eyebrow">PARTICIPANT × EXACT SKU</span><h4>参测对象与精确 SKU 证据关系</h4></div><span className="tag quiet">共享材料 · 人工核对</span></div>
    <p className="quality-intro">关联线索、材料所载标识和人工复核分别保存。双账户不证明两个真人独立；不改来源成绩，不开放 AI 推荐，也不等于官方适配或独立认证。</p>
    {!auth.state.user?.is_admin ? <p className="review-boundary">当前可读取共享历史。新建、预览与所有管理操作需要管理员账户。</p> : null}
    {awaiting.map(([, attempt]) => <section className="review-boundary" key={attempt.key}><strong>本账户有尚待核对的原请求</strong><p>参测对象 {attempt.payload.selection.participant_key} · 原事件修订 ID {attempt.payload.selection.event_revision_id} · 固定 UUID {attempt.key}。该范围在结果核对前不能另建操作。</p><button type="button" className="secondary-button" onClick={() => setTarget({ participant: attempt.payload.selection.participant_key, id: attempt.payload.link_id })}>找回并核对原请求</button></section>)}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    <div className="bridge-participants">{event.participants.map(participant => <article key={participant.key}><strong>{participant.brand} {participant.model}</strong><p>{participant.source_designation || "精确版本仍为参测对象范围"}</p>
      <button type="button" className="secondary-button" disabled={!page || finding || readOnly || event.state === "revoked" || !auth.state.user?.is_admin} onClick={() => void openParticipant(participant.key)}>{finding ? "正在核对已有关系…" : "核对此参测对象的 SKU 证据"}</button></article>)}</div>
    {page ? <><div className="bridge-records">{page.items.map(item => <button key={item.id} type="button" className="report-list-item" onClick={() => setTarget({ participant: item.selection.participant_key, id: item.id })}>
      <strong>{item.frozen_evidence.test.participant.brand} {item.frozen_evidence.test.participant.model} → {valueText(item.frozen_evidence.tire.identity.manufacturer_product_code)}</strong>
      <span>{stateText[item.effective_state]} · 修订 #{item.revision} · {levelText[item.evidence_level]}</span><small>{item.eligibility === "conditional_reviewed_transcription" ? "仅条件化人工转录关联" : "不具备精确 SKU 性能移植资格"}</small></button>)}</div>
      {!page.total ? <p className="quality-empty">本场尚无已保存证据关系。名称和尺寸相同不会自动建立关联。</p> : null}
      <div className="bridge-pagination"><button type="button" className="text-button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页关系</button><span>共 {page.total} 条</span><button type="button" className="text-button" disabled={offset + page.items.length >= page.total} onClick={() => setOffset(offset + page.items.length)}>下一页关系</button><button type="button" className="text-button" onClick={() => setRefresh(value => value + 1)}>刷新关系</button></div></> : !error ? <p role="status">正在读取本场关系…</p> : null}
    {target ? <BridgeEditor key={`${target.participant}:${target.id || "new"}`} event={event} participantKey={target.participant} linkId={target.id} readOnly={readOnly} ownerEpoch={ownerEpoch} onClose={() => setTarget(null)} onChanged={() => setRefresh(value => value + 1)} /> : null}
  </section>;
}

function BridgeEditor({ event, participantKey, linkId, readOnly, ownerEpoch, onClose, onChanged }: {
  event: TestEventDetail; participantKey: string; linkId: string | null; readOnly: boolean; ownerEpoch: number; onClose: () => void; onChanged: () => void;
}) {
  const auth = useWorkbenchAuth(), platform = useWorkbenchPlatform();
  const userId = auth.state.user?.id || "", scope = attemptScope(userId, event, participantKey);
  const originalAttempt = unresolved.get(scope);
  const [record, setRecord] = useState<TestSkuLinkDetail | null>(null), [currentId, setCurrentId] = useState(linkId);
  const [historyRevision, setHistoryRevision] = useState<number>(), [reload, setReload] = useState(0);
  const [action, setAction] = useState<BridgeAction | null>(originalAttempt?.payload.action || (linkId ? null : "create"));
  const [selection, setSelection] = useState<BridgeSelection>(originalAttempt?.payload.selection || { event_id: event.id, event_revision_id: event.revision_id, participant_key: participantKey, variant_id: "", tire_snapshot_id: "", fact_version_id: "" });
  const [materials, setMaterials] = useState<BridgeMaterial[]>(originalAttempt?.payload.materials || []);
  const [assertions, setAssertions] = useState<BridgeAssertion[]>(originalAttempt?.payload.assertions || []);
  const [level, setLevel] = useState<BridgeEvidenceLevel>(originalAttempt?.payload.evidence_level || "manual_assertion");
  const [preview, setPreview] = useState<TestSkuLinkPreview | null>(null), [pending, setPending] = useState<Attempt | null>(originalAttempt || null);
  const [operator, setOperator] = useState(originalAttempt?.payload.operator || ""), [reason, setReason] = useState(originalAttempt?.payload.reason || "");
  const [confirmed, setConfirmed] = useState(false), [opened, setOpened] = useState<Record<string, boolean>>({});
  const [downloaded, setDownloaded] = useState<Record<string, string>>({}), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [search, setSearch] = useState(""), [query, setQuery] = useState(""), [candidateOffset, setCandidateOffset] = useState(0);
  const [candidates, setCandidates] = useState<IdentityCandidates | null>(null), [selectedIdentity, setSelectedIdentity] = useState<Record<string, unknown> | null>(null);
  const [tirePage, setTirePage] = useState<FitmentTireEvidencePage | null>(null), [tireOffset, setTireOffset] = useState(0);
  const [materialPage, setMaterialPage] = useState<BridgeMaterialsPage | null>(null), [materialOffset, setMaterialOffset] = useState(0), [materialReload, setMaterialReload] = useState(0);
  const [file, setFile] = useState<File | null>(null), [uploadRights, setUploadRights] = useState(false);
  const [uploadMeta, setUploadMeta] = useState<EvidenceDocumentMetadata>({ title: "", source_url: "", operator: "", rights_basis: "" });
  const [rightsAccepted, setRightsAccepted] = useState<Record<string, boolean>>({});
  const requests = useRef(new Set<AbortController>()), generation = useRef(0), writing = useRef(false);
  const isCurrent = (controller: AbortController) => !controller.signal.aborted && auth.isCurrentOwner(ownerEpoch);
  const controller = () => { const value = new AbortController(); requests.current.add(value); return value; };
  const editing = action === "create" || action === "revise";
  const administrator = !!auth.state.user?.is_admin;
  const locked = busy || !!pending || readOnly || historyRevision !== undefined || !administrator;
  const contextParticipant = event.participants.find(item => item.key === participantKey);
  const declarationComplete = (!editing || materials.every(item => rightsAccepted[item.document_id]
    && item.rights.rights_holder.trim() && item.rights.basis.trim() && locatorComplete(item.event_locator) && locatorComplete(item.participant_locator)))
    && (level !== "source_explicit_identifiers_in_supplied_material" || materials.length > 0)
    && assertions.every(item => locatorComplete(item) && (typeof item.material_value === "boolean" || !!item.material_value.trim()));
  function invalidate() { generation.current++; setPreview(null); setConfirmed(false); setOpened({}); setError(""); }
  function change(work: () => void) { invalidate(); work(); }
  function remember(attempt: Attempt | null) { if (attempt) unresolved.set(scope, attempt); else unresolved.delete(scope); setPending(attempt); }
  useEffect(() => () => { generation.current++; requests.current.forEach(value => value.abort()); requests.current.clear(); }, []);
  useEffect(() => {
    if (!currentId) return;
    const request = new AbortController(); setError(""); setRecord(null); setPreview(null); setAction(null); setOpened({}); setConfirmed(false);
    void tireApi.testSkuLink(currentId, request.signal, historyRevision).then(value => {
      if (!isCurrent(request)) return;
      assertView(value, event.id, participantKey);
      if (value.id !== currentId || (historyRevision !== undefined && value.revision !== historyRevision)) throw new Error("未找到所指定的精确历史修订，未改读当前版本。");
      setRecord(value); setCurrentId(value.id);
    }).catch(cause => { if (isCurrent(request)) setError(errorText(cause)); });
    return () => request.abort();
  // User/event identity changes remount this entire editor and abort its requests.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkId, historyRevision, reload]);
  useEffect(() => {
    if (!editing || !administrator) return;
    const request = new AbortController(); setCandidates(null);
    void tireApi.identityCandidates(query, candidateOffset, request.signal).then(value => { if (isCurrent(request)) setCandidates(value); }).catch(cause => { if (isCurrent(request)) setError(errorText(cause)); });
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, query, candidateOffset, administrator]);
  useEffect(() => {
    setTirePage(null);
    if (!editing || !selection.variant_id || !administrator) return;
    const request = new AbortController();
    void tireApi.fitmentTireEvidence(selection.variant_id, tireOffset, request.signal).then(value => {
      if (!isCurrent(request)) return;
      if (value.variant_id !== selection.variant_id) throw new Error("SKU 来源证据返回范围不一致。");
      setTirePage(value); setSelectedIdentity(value.identity);
    }).catch(cause => { if (isCurrent(request)) setError(errorText(cause)); });
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, selection.variant_id, tireOffset, administrator]);
  useEffect(() => {
    if (!editing || !administrator) return;
    const request = new AbortController(); setMaterialPage(null);
    void tireApi.testSkuLinkMaterials(materialOffset, request.signal).then(value => { if (isCurrent(request)) setMaterialPage(value); }).catch(cause => { if (isCurrent(request)) setError(errorText(cause)); });
    return () => request.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, materialOffset, materialReload, administrator]);

  function chooseAction(next: BridgeAction) {
    if (locked || !record || !record.allowed_actions.includes(next)) return;
    change(() => {
      setAction(next); setSelection({ ...record.selection, ...(next === "revise" ? { event_revision_id: event.revision_id } : {}) });
      setMaterials(structuredClone(record.materials));
      setAssertions(record.assertions.map(({ field, material_document_id, material_value, quote, page, region }) => ({ field, material_document_id, material_value, quote, page, region })));
      setLevel(record.evidence_level); setSelectedIdentity(record.frozen_evidence.tire.identity); setReason(""); setNotice(""); setRightsAccepted({});
    });
  }
  function addMaterial(row: BridgeMaterialChoice) {
    if (materials.length >= 3 || materials.some(item => item.document_id === row.id)) return;
    change(() => setMaterials(previous => [...previous, { document_id: row.id, expected_raw_hash: row.raw_hash, expected_metadata_hash: row.metadata_hash,
      event_locator: blankLocator(), participant_locator: blankLocator(), rights: { rights_holder: "", basis: "", store_original: true, workspace_reopen: true, quote_identifiers: true } }]));
  }
  function changeMaterial(index: number, patch: Partial<BridgeMaterial>) { change(() => { setRightsAccepted(previous => ({ ...previous, [materials[index].document_id]: false })); setMaterials(previous => previous.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)); }); }
  async function upload() {
    if (!file || locked || !uploadRights) return;
    if (file.size > 8 * 1024 * 1024) { setError("PDF 原件不得超过 8 MiB。"); return; }
    const request = controller(); setBusy(true); setError("");
    try {
      const result = await tireApi.uploadDocument(uploadMeta, file, request.signal);
      if (!isCurrent(request)) return;
      setNotice(`原件“${result.title}”已留存。请在材料列表明确选择；上传并未核验出版来源或身份。`);
      setFile(null); setMaterialOffset(0); setMaterialReload(value => value + 1);
    } catch (cause) { if (isCurrent(request)) setError(errorText(cause)); }
    finally { requests.current.delete(request); if (isCurrent(request)) setBusy(false); }
  }
  async function download(row: BridgeMaterialChoice) {
    if (busy || !hash(row.raw_hash) || !hash(row.metadata_hash)) return;
    const request = controller(); setBusy(true); setError("");
    try {
      const blob = await tireApi.documentContent(row.id, request.signal);
      if (!isCurrent(request)) return;
      if (blob.type.split(";")[0].trim().toLowerCase() !== "application/pdf" || blob.size !== row.byte_count) throw new Error("原件 MIME 或字节数不符，未提供文件。");
      const bytesHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())), value => value.toString(16).padStart(2, "0")).join("");
      if (!isCurrent(request)) return;
      if (bytesHash !== row.raw_hash) throw new Error("完整 PDF 原件 SHA-256 不符，未提供文件。");
      const result = await platform.saveDownload({ blob, filename: `test-material-${row.raw_hash}.pdf`, signal: request.signal });
      if (!isCurrent(request)) return;
      if (result.saved) { setDownloaded(previous => ({ ...previous, [row.id]: `${row.raw_hash}:${row.metadata_hash}` })); setNotice("完整字节已核对并提供下载。请自行打开原件核读，再作人工确认；系统没有证明你已阅读，也未解析 PDF。"); }
    } catch (cause) { if (isCurrent(request)) setError(errorText(cause)); }
    finally { requests.current.delete(request); if (isCurrent(request)) setBusy(false); }
  }
  function requestBody(): BridgePreviewRequest {
    if (!action) throw new Error("请先选择本次操作。");
    return { mode: "history", action, link_id: currentId, selection: { ...selection }, materials: structuredClone(materials), assertions: structuredClone(assertions), evidence_level: level };
  }
  async function prepare() {
    if (locked || !action || !Object.values(selection).every(Boolean) || !declarationComplete) return;
    const payload = requestBody(); invalidate(); const token = generation.current, request = controller(); setBusy(true);
    try {
      const result = await tireApi.previewTestSkuLink(payload, request.signal);
      if (!isCurrent(request) || generation.current !== token) return;
      assertView(result, event.id, participantKey);
      if (!sameSelection(result.selection, payload.selection) || result.evidence_level !== payload.evidence_level) throw new Error("预览不属于当前明确选择，请重新读取。");
      setPreview(result);
    } catch (cause) { if (isCurrent(request) && generation.current === token) setError(errorText(cause)); }
    finally { requests.current.delete(request); if (isCurrent(request)) setBusy(false); }
  }
  async function perform(attempt: Attempt) {
    if (writing.current || !administrator || !auth.isCurrentOwner(ownerEpoch)) return;
    if (!unresolved.has(scope) && unresolved.size >= MAX_UNRESOLVED) { setError("待核对操作已达到本机上限，请先核对已有固定请求，不能丢弃旧 UUID 后重新提交。"); return; }
    writing.current = true; remember(attempt); const request = controller(); setBusy(true); setError("");
    try {
      const result = await tireApi.decideTestSkuLink(attempt.payload, attempt.key, request.signal);
      if (!isCurrent(request)) return;
      assertView(result.link, event.id, participantKey);
      if (result.link.revision !== attempt.payload.expected_revision + 1 || result.event.revision !== result.link.revision
        || result.event.action !== attempt.payload.action || result.event.actor_user_id !== userId
        || result.event.revision_id !== result.link.revision_id || !sameSelection(result.link.selection, attempt.payload.selection)
        || (attempt.payload.link_id !== null && result.link.id !== attempt.payload.link_id)) throw new Error("写入回执范围不一致；请保留同一 UUID 核对，不重新创建操作。");
      remember(null); setRecord(result.link); setCurrentId(result.link.id); setAction(null); setPreview(null); setConfirmed(false); setOpened({});
      setNotice(`已保存修订 #${result.event.revision}${result.idempotent_replay ? "（同一次固定请求）" : ""}。这是该操作的精确版本，当前状态请另行刷新；关联仍为未在线核验人工记录。`); onChanged();
    } catch (cause) {
      if (!isCurrent(request)) return;
      setError(errorText(cause)); setConfirmed(false);
      if (cause instanceof ApiError && [400, 404, 409, 422].includes(cause.status) && !cause.code?.includes("idempotency")) { remember(null); invalidate(); setAction(null); setError(`${errorText(cause)} 旧预览已清除。请关闭核对并重新读取当前关系或场次，再决定新的操作。`); onChanged(); }
    } finally { writing.current = false; requests.current.delete(request); if (isCurrent(request)) setBusy(false); }
  }
  const allOpened = !!preview && preview.material_evidence.every(material => opened[material.document_id]
    && downloaded[material.document_id] === `${material.raw_hash}:${material.metadata_hash}`);
  const canSubmit = !!preview?.can_submit && confirmed && operator.trim().length > 0 && reason.trim().length >= 5
    && !locked && (action !== "review" || allOpened);
  function submit() {
    if (!canSubmit || !preview) return;
    const openedMaterials: BridgeOpenedMaterial[] = preview.material_evidence.filter(item => opened[item.document_id]
      && downloaded[item.document_id] === `${item.raw_hash}:${item.metadata_hash}`).map(item => ({ document_id: item.document_id, raw_hash: item.raw_hash, metadata_hash: item.metadata_hash }));
    void perform({ key: crypto.randomUUID(), payload: { ...requestBody(), expected_revision: preview.revision, expected_fingerprint: preview.fingerprint,
      declaration_revision_id: preview.declaration_revision_id, operator: operator.trim(), reason: reason.trim(), acknowledged: true, opened_materials: openedMaterials,
      confirmed_event_revision_id: preview.confirmed_event_revision_id, confirmed_participant_hash: preview.confirmed_participant_hash } });
  }
  const identity = selectedIdentity || record?.frozen_evidence.tire.identity || {};
  const identityKeys = [...new Set([...Object.keys(identity), ...assertions.map(item => item.field)])].filter(key => key in fields) as BridgeIdentityField[];
  return <section className="bridge-editor" aria-label="参测对象 SKU 证据关系核对">
    <div className="bridge-heading"><h4>{contextParticipant ? `${contextParticipant.brand} ${contextParticipant.model}` : participantKey} · 证据关系核对</h4><button type="button" className="text-button" onClick={onClose}>关闭关系核对</button></div>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p className="review-saved" role="status">{notice}</p> : null}
    {pending ? <section className="review-boundary"><strong>操作结果尚待核对</strong><p>固定 UUID：<code>{pending.key}</code> · 原事件修订 ID <code>{pending.payload.selection.event_revision_id}</code>。即使场次已更新或正在查看历史，也只核对这个固定原请求，不能修改后作为新操作重发。</p><JsonDetails label="尚待核对的固定请求" value={pending.payload} /><button type="button" className="primary-button" disabled={busy || !administrator} onClick={() => void perform(pending)}>核对同一次操作</button></section> : null}
    {record ? <><div className="snapshot-banner"><strong>{stateText[record.effective_state]} · 修订 #{record.revision}</strong><span>{levelText[record.evidence_level]} · {record.eligibility === "conditional_reviewed_transcription" ? "仅条件化人工转录关联" : "适用性未成立"}</span><span>声明账户：{record.declared_by_user_id || "未记录"}；双账户复核不证明真人身份。</span></div>
      {historyRevision !== undefined ? <p className="review-boundary">正在查看明确选择的历史修订 #{historyRevision}；不表示当前有效，也不能在历史视图管理。<button type="button" className="text-button" onClick={() => { setHistoryRevision(undefined); setReload(value => value + 1); }}>返回当前关系</button></p> : <button type="button" className="text-button" disabled={busy || !!pending} onClick={() => { setPreview(null); setAction(null); setReload(value => value + 1); }}>重新读取当前关系</button>}
      {record.stale_reasons.length ? <div className="inline-error"><strong>原声明不能自动沿用</strong><ul>{record.stale_reasons.map(code => <li key={code}>{staleText[code] || code}</li>)}</ul></div> : null}
      {!action ? <ViewEvidence view={record} onOriginal={row => void download(row)} /> : null}
      <div className="bridge-actions">{record.allowed_actions.filter(value => value !== "create").map(value => <button type="button" className="secondary-button" key={value} disabled={locked} onClick={() => chooseAction(value)}>{actionText[value]}</button>)}</div>
      {record.declared_by_user_id === userId && record.review_state !== "revoked" ? <p className="review-boundary">这是当前账户的声明。审核须换另一管理员账户；更换署名或同账户另开会话不满足要求。</p> : null}
      <details className="bridge-history"><summary>追加修订历史（{record.history.length}{record.history_truncated ? "+" : ""} 条）</summary>{record.history.map(item => <article key={item.revision_id}><strong>#{item.revision} · {actionText[item.action]} · {stateText[item.review_state]}</strong><p>{stamp(item.created_at)} · {item.operator} · 账户 {item.actor_user_id}</p><p>{item.reason}</p><button type="button" className="text-button" disabled={busy || !!pending} onClick={() => { setAction(null); setHistoryRevision(item.revision); }}>查看精确修订 #{item.revision}</button></article>)}</details>
    </> : currentId && !error ? <p role="status">正在读取精确关系与追加历史…</p> : null}
    {action && !readOnly && historyRevision === undefined && administrator ? <div className="bridge-declaration">
      <h4>{actionText[action]}</h4>
      {editing ? <>
        <p className="review-boundary">固定测试修订 #{event.revision} 和参测对象。材料原值须逐项照录，不从下方 SKU 值预填；变更任何选择都会使旧预览和确认失效。</p>
        <div className="bridge-section-heading"><span>01</span><h5>明确选择精确 SKU 与来源版本</h5></div>
        <form className="bridge-search" onSubmit={submitEvent => { submitEvent.preventDefault(); setQuery(search.trim()); setCandidateOffset(0); }}><label><span>品牌、型号或产品代码</span><input maxLength={120} value={search} disabled={locked} onChange={inputEvent => setSearch(inputEvent.target.value)} /></label><button className="secondary-button" disabled={locked} type="submit">搜索历史 SKU</button></form>
        {candidates ? <><div className="bridge-candidates">{candidates.items.map(item => <button type="button" className={`report-list-item${selection.variant_id === item.id ? " selected" : ""}`} aria-pressed={selection.variant_id === item.id} key={item.id} disabled={locked} onClick={() => change(() => { setSelection(previous => ({ ...previous, variant_id: item.id, tire_snapshot_id: "", fact_version_id: "" })); setSelectedIdentity(item.identity); setTireOffset(0); })}>
          <strong>{valueText(item.identity.brand)} {valueText(item.identity.model)} · {valueText(item.identity.manufacturer_product_code)}</strong><span>{valueText(item.identity.product_code_type)} · {valueText(item.identity.region)} · {valueText(item.identity.size)}</span><small>载重 / 速度 {valueText(item.identity.load_index)} / {valueText(item.identity.speed_rating)} · OE {valueText(item.identity.oe_mark)}</small></button>)}</div>
          <div className="bridge-pagination"><button type="button" className="text-button" disabled={locked || !candidateOffset} onClick={() => setCandidateOffset(Math.max(0, candidateOffset - candidates.limit))}>上一页 SKU</button><span>共 {candidates.total} 条</span><button type="button" className="text-button" disabled={locked || candidateOffset + candidates.items.length >= candidates.total} onClick={() => setCandidateOffset(candidateOffset + candidates.limit)}>下一页 SKU</button></div></> : <p role="status">正在读取历史 SKU…</p>}
        {selection.variant_id ? <label className="bridge-snapshot"><span>明确选择来源快照与事实版本</span><select disabled={locked || !tirePage} value={`${selection.tire_snapshot_id}|${selection.fact_version_id}`} onChange={inputEvent => change(() => { const item = tirePage?.items.find(row => `${row.snapshot_id}|${row.fact_version_id}` === inputEvent.target.value); setSelection(previous => ({ ...previous, tire_snapshot_id: item?.snapshot_id || "", fact_version_id: item?.fact_version_id || "" })); })}><option value="|">请选择已采纳证据</option>{selection.tire_snapshot_id && !tirePage?.items.some(item => item.snapshot_id === selection.tire_snapshot_id && item.fact_version_id === selection.fact_version_id) ? <option value={`${selection.tire_snapshot_id}|${selection.fact_version_id}`}>原声明的明确旧引用 · {selection.tire_snapshot_id}</option> : null}{tirePage?.items.map(item => <option value={`${item.snapshot_id}|${item.fact_version_id}`} key={`${item.snapshot_id}:${item.fact_version_id}`}>{item.source_id} · 事实 #{item.fact_version} · {stamp(item.provenance.observed_at)}</option>)}</select></label> : null}
        {tirePage ? <div className="bridge-pagination"><button type="button" className="text-button" disabled={locked || !tireOffset} onClick={() => setTireOffset(Math.max(0, tireOffset - tirePage.limit))}>上一页证据</button><span>共 {tirePage.total} 份 SKU 证据</span><button type="button" className="text-button" disabled={locked || tireOffset + tirePage.items.length >= tirePage.total} onClick={() => setTireOffset(tireOffset + tirePage.limit)}>下一页证据</button></div> : null}
        <div className="bridge-section-heading"><span>02</span><h5>选择材料、声明共享权利及原文位置</h5></div>
        <label><span>本次证据等级</span><select value={level} disabled={locked} onChange={inputEvent => change(() => setLevel(inputEvent.target.value as BridgeEvidenceLevel))}><option value="manual_assertion">人工关联线索（可无材料，不移植性能）</option><option value="source_explicit_identifiers_in_supplied_material">供审材料所载明确标识（需要原件及逐字段声明）</option></select></label>
        <p className="muted">PDF 属于本地共享工作区，操作者提供、未在线核验；来源链接和保存授权均是声明。不得上传无权共享或不能再次打开的材料。</p>
        <details className="bridge-upload"><summary>上传一份已获共享许可的 PDF 原件</summary><div className="review-form">
          <label><span>PDF 原件（最大 8 MiB）</span><input type="file" accept="application/pdf,.pdf" disabled={locked} onChange={inputEvent => { setFile(inputEvent.target.files?.[0] || null); setUploadRights(false); }} /></label>
          {([['title', '原件名称', 160], ['source_url', '来源 HTTPS 引用（不自动访问）', 2048], ['operator', '留存署名', 80], ['rights_basis', '原件留存与共享依据', 500]] as const).map(([key, label, length]) => <label key={key}><span>{label}</span><input value={uploadMeta[key]} maxLength={length} disabled={locked} onChange={inputEvent => { setUploadMeta(previous => ({ ...previous, [key]: inputEvent.target.value })); setUploadRights(false); }} /></label>)}
          <label className="review-checkbox"><input type="checkbox" disabled={locked} checked={uploadRights} onChange={inputEvent => setUploadRights(inputEvent.target.checked)} /><span>确认有权在本地共享工作区保存和重开此完整原件；上传不会授予额外许可，也不会进行来源核验。</span></label>
          <button type="button" className="secondary-button" disabled={locked || !file || !uploadRights || !uploadMeta.title.trim() || !uploadMeta.operator.trim() || !uploadMeta.rights_basis.trim()} onClick={() => void upload()}>保存原件并刷新材料列表</button>
        </div></details>
        {materialPage ? <><label><span>添加已有 PDF 材料（最多 3 份）</span><select value="" disabled={locked || materials.length >= 3} onChange={inputEvent => { const row = materialPage.items.find(item => item.id === inputEvent.target.value); if (row) addMaterial(row); }}><option value="">请选择明确原件</option>{materialPage.items.map(item => <option key={item.id} value={item.id} disabled={materials.some(row => row.document_id === item.id)}>{item.title} · {item.byte_count} 字节 · {item.raw_hash.slice(0, 12)}</option>)}</select></label>
          <div className="bridge-pagination"><button type="button" className="text-button" disabled={locked || !materialOffset} onClick={() => setMaterialOffset(Math.max(0, materialOffset - 50))}>上一页材料</button><span>共 {materialPage.total} 份</span><button type="button" className="text-button" disabled={locked || materialOffset + materialPage.items.length >= materialPage.total} onClick={() => setMaterialOffset(materialOffset + materialPage.items.length)}>下一页材料</button></div></> : <p role="status">正在读取共享原件元数据…</p>}
        {materials.map((material, index) => <article className="bridge-material-editor" key={material.document_id}><div className="bridge-heading"><h5>材料 {index + 1} · {materialPage?.items.find(item => item.id === material.document_id)?.title || record?.material_evidence.find(item => item.document_id === material.document_id)?.metadata.title || material.document_id}</h5><button type="button" className="text-button" disabled={locked} onClick={() => change(() => { setMaterials(previous => previous.filter(item => item.document_id !== material.document_id)); setAssertions(previous => previous.filter(item => item.material_document_id !== material.document_id)); })}>移除此材料</button></div><p className="bridge-hash">完整原件 SHA-256 {material.expected_raw_hash}</p>
          <LocatorFields label="本场测试的材料对照" value={material.event_locator} disabled={locked} onChange={value => changeMaterial(index, { event_locator: value })} /><LocatorFields label="此参测对象的材料对照" value={material.participant_locator} disabled={locked} onChange={value => changeMaterial(index, { participant_locator: value })} />
          <div className="review-form"><label><span>声明的权利人 / 授权方</span><input maxLength={160} disabled={locked} value={material.rights.rights_holder} onChange={inputEvent => changeMaterial(index, { rights: { ...material.rights, rights_holder: inputEvent.target.value } })} /></label><label><span>保存原件、工作区重开和标识短引文的依据</span><textarea maxLength={1000} disabled={locked} value={material.rights.basis} onChange={inputEvent => changeMaterial(index, { rights: { ...material.rights, basis: inputEvent.target.value } })} /></label>
            <label className="review-checkbox"><input type="checkbox" disabled={locked} checked={!!rightsAccepted[material.document_id]} onChange={inputEvent => change(() => setRightsAccepted(previous => ({ ...previous, [material.document_id]: inputEvent.target.checked })))} /><span>明确声明三项权限：保存此完整原件、在本地共享工作区重开、引用身份标识短文。不允许向模型发送或新增导出使用；系统未授予额外许可。</span></label></div>
        </article>)}
        <div className="bridge-section-heading"><span>03</span><h5>逐身份字段照录材料值与短引文</h5></div>
        {!selection.variant_id ? <p className="muted">先明确选择 SKU，才能逐项核对其实际身份字段；材料值不会预填。</p> : identityKeys.map(field => {
          const assertion = assertions.find(item => item.field === field), sourceValue = identity[field];
          const unsupported = sourceValue !== null && typeof sourceValue === "object";
          return <details className="bridge-assertion" key={field} open={!!assertion}><summary>{fields[field]} · SKU 原值 {valueText(sourceValue)}{unsupported ? " · 数组 / 结构暂不支持，不扁平化" : ""}</summary>
            <label className="review-checkbox"><input type="checkbox" disabled={locked || unsupported || !materials.length} checked={!!assertion} onChange={inputEvent => change(() => setAssertions(previous => inputEvent.target.checked ? [...previous, { field, material_document_id: materials[0].document_id, material_value: "", quote: "", page: 1, region: "" }] : previous.filter(item => item.field !== field)))} /><span>材料中明确声明此字段（缺少时保持未知）</span></label>
            {assertion ? <div className="review-form"><label><span>字段原文所属 PDF</span><select disabled={locked} value={assertion.material_document_id} onChange={inputEvent => change(() => setAssertions(previous => previous.map(item => item.field === field ? { ...item, material_document_id: inputEvent.target.value } : item)))}>{materials.map((item, itemIndex) => <option key={item.document_id} value={item.document_id}>材料 {itemIndex + 1} · {item.document_id}</option>)}</select></label>
              <label><span>材料所载原值（不预填 SKU）</span>{typeof sourceValue === "boolean" || ["xl", "hl", "run_flat"].includes(field) ? <select disabled={locked} value={typeof assertion.material_value === "boolean" ? String(assertion.material_value) : ""} onChange={inputEvent => change(() => setAssertions(previous => previous.map(item => item.field === field ? { ...item, material_value: inputEvent.target.value === "" ? "" : inputEvent.target.value === "true" } : item)))}><option value="">尚未照录</option><option value="true">材料明确为是 / true</option><option value="false">材料明确为否 / false</option></select> : <input disabled={locked} value={String(assertion.material_value)} onChange={inputEvent => change(() => setAssertions(previous => previous.map(item => item.field === field ? { ...item, material_value: inputEvent.target.value } : item)))} />}</label>
              <LocatorFields label="该字段的直接出处" value={assertion} disabled={locked} onChange={value => change(() => setAssertions(previous => previous.map(item => item.field === field ? { ...item, page: value.page, region: value.region, quote: value.quote } : item)))} /></div> : null}
          </details>;
        })}
      </> : <p className="review-boundary">本次沿用已保存声明、材料与双侧原引用。要更换 SKU、测试修订、材料或原值，请先追加“修订声明”，不能在复核中同时改写。</p>}
      <button type="button" className="primary-button bridge-preview-button" disabled={locked || !Object.values(selection).every(Boolean) || !declarationComplete} onClick={() => void prepare()}>预览完整证据与本次操作</button>
      {preview ? <section className="bridge-preview"><div className="bridge-section-heading"><span>04</span><h5>完整证据预览 · 当前修订 #{preview.revision}</h5></div><ViewEvidence view={preview} onOriginal={row => void download(row)} />
        <form className="review-form" onSubmit={submitEvent => { submitEvent.preventDefault(); submit(); }}>
          {preview.material_evidence.map(material => <label className="review-checkbox" key={material.document_id}><input type="checkbox" disabled={locked || downloaded[material.document_id] !== `${material.raw_hash}:${material.metadata_hash}`} checked={!!opened[material.document_id]} onChange={inputEvent => { setOpened(previous => ({ ...previous, [material.document_id]: inputEvent.target.checked })); setConfirmed(false); }} /><span>我已自行完整打开并核读“{material.metadata.title}”，对照上述场次、参测对象、页内位置与逐项原值。这是本账户人工声明，不是系统阅读证明。</span></label>)}
          <label><span>本次处理署名（账户身份由服务器另行记录）</span><input required maxLength={100} disabled={locked} value={operator} onChange={inputEvent => { setOperator(inputEvent.target.value); setConfirmed(false); }} /></label><label><span>本次理由（至少 5 个字）</span><textarea required minLength={5} maxLength={2000} disabled={locked} value={reason} onChange={inputEvent => { setReason(inputEvent.target.value); setConfirmed(false); }} /></label>
          <label className="review-checkbox"><input type="checkbox" disabled={locked} checked={confirmed} onChange={inputEvent => setConfirmed(inputEvent.target.checked)} /><span>确认固定测试修订、原参测对象、精确 SKU、全部材料和未知/矛盾项；理解这是共享、未在线核验的人工关系，不证明适配、性能推荐或跨场排名。</span></label>
          <button type="submit" className="primary-button" disabled={!canSubmit}>{busy ? "正在保存并核对…" : actionText[action]}</button>
        </form></section> : null}
    </div> : null}
  </section>;
}
