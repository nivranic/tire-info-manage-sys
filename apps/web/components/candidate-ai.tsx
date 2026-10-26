"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ApiError, CandidateAiContractError, tireApi } from "@tire/api-client";
import type {
  CandidateAiAuthorization, CandidateAiAuthorizationRequest, CandidateAiCandidate,
  CandidateAiDependency, CandidateAiPreparation, CandidateAiRecommendation, FitmentCandidates,
} from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { aiProviderLabel } from "./ai-budget";
import "./candidate-ai.css";

const recoveryStorage = "tire-candidate-ai-recovery@1";
const uuid = (value: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const valueText = (value: unknown): string => value === null || value === undefined ? "未知 / 未声明" : Array.isArray(value) ? value.map(valueText).join("、") : typeof value === "boolean" ? value ? "是" : "否" : String(value);
const sourceLabels = { vehicle: "车型来源", tire: "轮胎来源", relation: "人工适配关系" };
const authLabels = { granted: "已声明本用途许可", revoked: "已撤销用途许可", expired: "用途许可已过期" };
const stateLabels = { pending: "调用处理中", outcome_unknown: "调用结果尚未确认", completed: "规格辅助已完成校验", failed: "本次规格辅助未完成" };
const fieldLabels: Record<string, string> = { brand: "品牌", model: "型号", manufacturer_product_code: "产品代码", product_code_type: "代码命名空间", region: "市场", size: "完整尺寸", load_index: "载重指数", speed_rating: "速度级别", xl: "XL", hl: "HL", oe_mark: "OE 声明", acoustic_technology: "静音技术声明", run_flat: "缺气保用", technology_features: "技术配置", gtin: "GTIN", eprel_id: "EPREL" };
const performanceBoundary = "七维精确 SKU 性能证据未建立。此处只辅助核对已有规格与人工关系，不判断抓地、安静或耐磨，不产生性能排名、官方原配或安装安全结论。";
const candidateLabel = (candidate: { identity: Record<string, unknown>; variant_id: string }) => `${valueText(candidate.identity.brand)} ${valueText(candidate.identity.model)} · ${valueText(candidate.identity.manufacturer_product_code)}`;
function errorText(cause: unknown) {
  if (cause instanceof CandidateAiContractError) return cause.message;
  if (cause instanceof ApiError) {
    if (cause.status === 401 || cause.status === 403) return "当前账户没有执行此操作的权限。请重新确认登录或管理员身份。";
    if (cause.status === 404) return "未找到本账户的专用记录。没有自动重新提交，也不能据此认定原调用未处理或未计费。";
    if (cause.status === 409) return "准备依据、用途许可或模型配置已变化，或本准备已经消费。请先只读核对已有提交；新的分析须重新准备。";
    if (cause.status === 422) return "所选范围或许可声明未通过核对，请检查完整输入。没有补齐或替换候选。";
    return `规格辅助未完成${cause.code ? `（${cause.code}）` : ""}。请保留本次标识核对。`;
  }
  return "连接或响应未确认。若已提交，请只读核对同一请求，不要自动重发。";
}
function blockerText(code: string) {
  if (/authorization|permission|license/.test(code)) return `用途许可不足或已变化（${code}）`;
  if (/configuration|disabled|provider|model/.test(code)) return `当前模型配置不允许提交（${code}）`;
  if (/preference/.test(code)) return `本人偏好需要重新核对（${code}）`;
  return `本次依据未满足发送条件（${code}）`;
}

type Props = { candidates: FitmentCandidates; onRefreshCandidates: () => void; onPreferences: () => void };
export default function CandidateAiAssistance(props: Props) {
  const auth = useWorkbenchAuth();
  if (!auth.ready || !auth.state.authenticated) return <section className="candidate-ai-panel"><h3>规格候选 AI 辅助</h3><p>登录并确认当前账户后，才能准备本人偏好与候选范围。</p></section>;
  const basis = JSON.stringify([auth.ownerEpoch, props.candidates.selection, props.candidates.vehicle_binding, props.candidates.preference,
    props.candidates.items.map(candidate => [candidate.variant_id, candidate.relations.map(relation => [relation.revision_id, relation.binding_hash])])]);
  return <CandidateAiWorkspace key={basis} {...props} ownerEpoch={auth.ownerEpoch} />;
}

function CandidateAiWorkspace({ candidates, onRefreshCandidates, onPreferences, ownerEpoch }: Props & { ownerEpoch: number }) {
  const auth = useWorkbenchAuth(), titleId = useId();
  const [selected, setSelected] = useState<string[]>([]);
  const [question, setQuestion] = useState("根据已录规格和人工适配依据，列出可继续核对的候选与不足。");
  const [preparation, setPreparation] = useState<CandidateAiPreparation | null>(null);
  const [consent, setConsent] = useState<string | null>(null);
  const [run, setRun] = useState<CandidateAiRecommendation | null>(null);
  const [attempt, setAttempt] = useState<string | null>(null);
  const [recoveryKey, setRecoveryKey] = useState("");
  const [busy, setBusy] = useState<"prepare" | "submit" | "recover" | "authorize" | null>(null);
  const [error, setError] = useState("");
  const [expired, setExpired] = useState(false);
  const [authorizationChanges, setAuthorizationChanges] = useState<Record<string, CandidateAiAuthorization>>({});
  const operation = useRef<AbortController | null>(null), generation = useRef(0);
  const authorizationDirty = Object.keys(authorizationChanges).length > 0;
  const consentBinding = preparation ? JSON.stringify([preparation.preparation_id, preparation.pack_id, preparation.fingerprint, preparation.consent_hash,
    preparation.provider, question, ownerEpoch]) : null;
  const locked = busy !== null || attempt !== null;
  const canPrepare = !locked && !candidates.truncated && selected.length >= 2 && selected.length <= 20 && question.trim().length >= 2 && question.length <= 2000;
  const canSend = !!preparation?.sendable && !!preparation.consent_hash && !!preparation.provider && !expired && !authorizationDirty && consent === consentBinding && !locked;
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(recoveryStorage), pointer: unknown = raw ? JSON.parse(raw) : null;
      if (pointer && typeof pointer === "object" && "actor_id" in pointer && pointer.actor_id === auth.state.user?.id && "key" in pointer && typeof pointer.key === "string" && uuid(pointer.key)) setRecoveryKey(pointer.key);
    } catch { /* A request identifier can still be entered manually. */ }
    return () => { operation.current?.abort(); generation.current++; };
  }, [auth.state.user?.id]);
  useEffect(() => {
    if (!preparation) { setExpired(false); return; }
    const remaining = Date.parse(preparation.expires_at) - Date.now();
    setExpired(remaining <= 0);
    const timer = setTimeout(() => setExpired(Date.now() >= Date.parse(preparation.expires_at)), Math.max(0, Math.min(remaining, 2147483647)));
    return () => clearTimeout(timer);
  }, [preparation]);
  function remember(key: string | null) {
    try {
      if (key) sessionStorage.setItem(recoveryStorage, JSON.stringify({ schema: "candidate-ai-recovery@1", actor_id: auth.state.user?.id, key }));
      else sessionStorage.removeItem(recoveryStorage);
    } catch { /* Server history remains available through the request identifier. */ }
  }
  function clearPrepared() {
    operation.current?.abort(); operation.current = null; generation.current++;
    setPreparation(null); setConsent(null); setRun(null); setError(""); setBusy(null); setAuthorizationChanges({});
  }
  async function perform(kind: NonNullable<typeof busy>, work: (signal: AbortSignal, current: () => boolean) => Promise<void>) {
    if (operation.current || !auth.isCurrentOwner(ownerEpoch)) return;
    const controller = new AbortController(), epoch = ++generation.current; operation.current = controller;
    const current = () => !controller.signal.aborted && operation.current === controller && generation.current === epoch && auth.isCurrentOwner(ownerEpoch);
    setBusy(kind); setError("");
    try { await work(controller.signal, current); }
    catch (cause) { if (current()) setError(errorText(cause)); }
    finally { if (current()) { operation.current = null; setBusy(null); } }
  }
  async function prepare() {
    if (!canPrepare) return;
    setPreparation(null); setRun(null); setConsent(null); setAuthorizationChanges({});
    await perform("prepare", async (signal, current) => {
      const value = await tireApi.prepareCandidateAI({ selection: { ...candidates.selection }, expected_preference_revision: candidates.preference.revision,
        expected_preference_fingerprint: candidates.preference.fingerprint, variant_ids: [...selected], question: question.trim() }, signal);
      if (current()) setPreparation(value);
    });
  }
  async function authorize(dependency: CandidateAiDependency, payload: CandidateAiAuthorizationRequest) {
    if (!preparation || locked) return;
    setConsent(null);
    await perform("authorize", async (signal, current) => {
      const value = await tireApi.authorizeCandidateAI(preparation.preparation_id, payload, signal);
      if (current()) setAuthorizationChanges(previous => ({ ...previous, [dependency.id]: value }));
    });
  }
  async function submit() {
    if (operation.current || !auth.isCurrentOwner(ownerEpoch) || !canSend || !preparation || !preparation.consent_hash) return;
    if (Date.now() >= Date.parse(preparation.expires_at)) { setExpired(true); setConsent(null); return; }
    const key = crypto.randomUUID(); setAttempt(key); setRecoveryKey(key); remember(key); setConsent(null);
    await perform("submit", async (signal, current) => {
      const value = await tireApi.submitCandidateAI({ preparation_id: preparation.preparation_id, consent_hash: preparation.consent_hash!, allow_external_processing: true }, key, signal);
      if (current()) setRun(value);
    });
  }
  async function recover() {
    if (operation.current || !auth.isCurrentOwner(ownerEpoch) || !uuid(recoveryKey) || busy) return;
    const key = recoveryKey; setConsent(null);
    await perform("recover", async (signal, current) => {
      const value = await tireApi.lookupCandidateAIRecommendation(key, signal);
      if (current()) { setAttempt(key); setRun(value); remember(key); }
    });
  }
  function reset() { clearPrepared(); setAttempt(null); setRecoveryKey(""); remember(null); }
  return <section className="candidate-ai-panel" aria-labelledby={titleId} data-testid="candidate-ai-assistance">
    <div className="candidate-ai-heading"><div><span className="eyebrow">SPECIFICATION / EVIDENCE FIRST</span><h3 id={titleId}>规格候选 AI 辅助</h3></div><span className="tag quiet">独立 C · 规格域首批</span></div>
    <p>{performanceBoundary}</p><p>模型只能选择已有候选及服务器核对理由，也可以拒选。选择不表明优于未选项，未选项仍保留原适配资格。同场 B 的客观观察保持原样；测试材料及其成绩不会发送到 Provider。</p>
    {candidates.truncated ? <p className="review-warning">当前轴位候选不完整，请先重新核对全部候选；不能据此准备辅助。</p> : null}
    <fieldset className="candidate-ai-selection" disabled={locked}><legend>1 / 明确选择 2–20 个规格候选</legend>
      {candidates.items.map(candidate => <label className="candidate-ai-choice" key={candidate.variant_id}>
        <input type="checkbox" data-candidate-ai-variant={candidate.variant_id} aria-label={`选择规格候选 ${candidateLabel(candidate)}`} checked={selected.includes(candidate.variant_id)} disabled={!selected.includes(candidate.variant_id) && selected.length >= 20}
          onChange={() => { clearPrepared(); setSelected(previous => previous.includes(candidate.variant_id) ? previous.filter(id => id !== candidate.variant_id) : [...previous, candidate.variant_id]); }} />
        <span><strong>{candidateLabel(candidate)}</strong><small>{valueText(candidate.identity.product_code_type)} · {valueText(candidate.identity.region)} · {valueText(candidate.identity.size)}</small></span>
      </label>)}
      <p>已选择 {selected.length} 项。没有默认勾选，也不会按型号或同尺寸补齐。</p>
      <label className="candidate-ai-field"><span>规格辅助问题</span><textarea aria-label="规格辅助问题" maxLength={2000} minLength={2} rows={3} value={question} onChange={event => { clearPrepared(); setQuestion(event.target.value); }} /></label>
    </fieldset>
    <div className="candidate-ai-actions"><button type="button" className="secondary-button" data-testid="candidate-ai-prepare" disabled={!canPrepare} onClick={() => void prepare()}>{busy === "prepare" ? "正在核对规格与用途许可…" : "准备规格辅助证据"}</button><button type="button" className="text-button" disabled={busy !== null} onClick={onPreferences}>核对本人偏好</button><button type="button" className="text-button" disabled={busy !== null} onClick={onRefreshCandidates}>重新核对轴位候选</button></div>
    <p className="review-boundary">准备只在本地核对，不调用模型。未配置模型仍可查看许可缺口；个人同意不能替代来源用途许可。</p>
    {error ? <p className="inline-error" role="alert" data-testid="candidate-ai-error">{error}</p> : null}
    {preparation ? <section className="candidate-ai-preparation" data-testid="candidate-ai-preparation" aria-label="规格辅助准备与用途许可">
      <h4>2 / 核对本次最小外发投影</h4><p>所选{preparation.selection.axle === "front" ? "前轴" : "后轴"} · 本人偏好修订 #{preparation.preference.revision} · 准备有效期至 {stamp(preparation.expires_at)}</p>
      <p>仅包含下列精确身份、轴位检查、已审关系引用、偏好与问题；不包含整份来源 facts、自由原文、URL、原件、审核备注或专业测试内容。</p>
      {preparation.candidates.map(candidate => <CandidateFacts key={candidate.variant_id} candidate={candidate} />)}
      <div className="candidate-ai-dependencies"><h4>逐项来源用途许可</h4>{preparation.dependencies.map(dependency => {
        const changed = authorizationChanges[dependency.id], head = changed || dependency.authorization;
        return <article className="candidate-ai-dependency" key={dependency.id} data-candidate-ai-dependency={dependency.id}>
          <strong>{sourceLabels[dependency.source_kind]}</strong><span className={`tag ${head?.state === "granted" ? "quiet" : "warning"}`}>{head ? authLabels[head.state] : "缺少本用途许可"}</span>
          <p>所用字段：{dependency.fields.join("、")}</p>{head ? <p>许可修订 #{head.revision} · 有效期至 {stamp(head.expires_at)}</p> : null}
          <details><summary>核对原件与用途投影绑定</summary><p className="candidate-ai-hash">依赖 {dependency.id}<br />快照 {dependency.snapshot_id}<br />原件 SHA-256 {dependency.raw_hash}<br />投影 SHA-256 {dependency.projection_hash}{head ? <><br />许可修订 {head.revision_id}</> : null}</p></details>
          {auth.state.user?.is_admin ? <AuthorizationForm key={`${preparation.preparation_id}:${dependency.id}`} dependency={dependency} changed={changed} provider={preparation.provider?.provider || ""} disabled={locked} onAuthorize={payload => authorize(dependency, payload)} /> : <p>如缺少许可，请由有合法依据的管理员逐项核对；勾选下方个人同意不会解锁材料。</p>}
        </article>;
      })}</div>
      {authorizationDirty ? <p className="review-warning" role="status">用途许可修订已记录。当前准备和个人同意不能继续使用；请重新准备规格辅助证据，再核对新许可代次。</p> : null}
      {preparation.blockers.length ? <ul className="candidate-ai-blockers">{preparation.blockers.map((code, index) => <li key={`${code}:${index}`}>{blockerText(code)}</li>)}</ul> : null}
      {preparation.provider ? <div className="candidate-ai-provider"><strong>{aiProviderLabel(preparation.provider.provider)} · {preparation.provider.model}</strong><p>实际接收方主机：<code>{preparation.provider.endpoint_host}</code>。已配置，真实连接及语义质量未由配置状态证明。预计预留 {preparation.provider.reserved_tokens.toLocaleString()} tokens；这不是账单金额。</p><details><summary>核对本次提交绑定</summary><p className="candidate-ai-hash">准备 {preparation.preparation_id}<br />包 {preparation.pack_id}<br />准备指纹 {preparation.fingerprint}<br />实际 body hash {preparation.provider.body_hash}<br />策略指纹 {preparation.provider.policy_fingerprint}<br />单次同意 hash {preparation.consent_hash || "不可提交，未提供"}</p></details></div> : <p className="review-warning">专用模型未配置或当前配置不可用。可以继续核对本地缺口，不能发送。</p>}
      {expired ? <p className="review-warning">准备已过期，请重新准备并重新核对同意。</p> : null}
      <label className="candidate-ai-consent"><input type="checkbox" data-testid="candidate-ai-consent" aria-label="仅本次同意外发规格辅助投影" checked={consent === consentBinding && consent !== null} disabled={locked || !preparation.sendable || authorizationDirty || expired} onChange={event => setConsent(event.target.checked ? consentBinding : null)} /><span>仅本次允许将当前问题、上述最小投影与本人偏好发送给此 Provider／模型及接收方主机 {preparation.provider?.endpoint_host || "（未配置）"} 处理。我理解这不是七维性能推荐或安装建议。</span></label>
      <button type="button" className="primary-button" data-testid="candidate-ai-submit" disabled={!canSend} onClick={() => void submit()}>{busy === "submit" ? "正在确认本次辅助结果…" : "同意后发送规格辅助"}</button>
    </section> : null}
    {attempt ? <div className="candidate-ai-attempt"><p>本次请求标识 <code>{attempt}</code>。提交内容和标识已锁定；刷新、超时或关闭页面不代表未处理、未计费或已取消。</p><button type="button" className="text-button" disabled={busy !== null} onClick={reset}>返回准备新的辅助</button><p>返回不会取消原调用；新的辅助需要重新准备与同意，可能另行计费。</p></div> : null}
    {run ? <RecommendationResult run={run} /> : null}
    <details className="candidate-ai-recovery" open={!!recoveryKey}><summary>只读核对专用调用记录</summary><p>只用本账户的原请求标识读取已有结果，不会重新发送问题或调用模型。</p><label className="candidate-ai-field"><span>规格辅助请求标识</span><input aria-label="规格辅助请求标识" value={recoveryKey} maxLength={36} disabled={busy !== null} onChange={event => setRecoveryKey(event.target.value)} /></label><button type="button" className="secondary-button" data-testid="candidate-ai-recover" disabled={!uuid(recoveryKey) || busy !== null} onClick={() => void recover()}>只读恢复规格辅助</button></details>
  </section>;
}

function CandidateFacts({ candidate }: { candidate: CandidateAiCandidate }) {
  return <details className="candidate-ai-facts"><summary>{candidateLabel(candidate)}</summary><dl>{Object.entries(candidate.identity).map(([field, value]) => <div key={field}><dt>{fieldLabels[field] || field}</dt><dd>{valueText(value)}</dd></div>)}</dl>
    {candidate.unknown_fields.length ? <p className="review-warning">仍有未知或未声明检查：{candidate.unknown_fields.join("、")}。未知没有作为匹配理由。</p> : null}
    <h5>服务器核对理由与引用</h5>{candidate.reasons.length ? candidate.reasons.map(reason => <article key={reason.id}><p>{reason.text}</p><p className="candidate-ai-hash">理由 {reason.id}<br />SKU {reason.reference.variant_id}<br />关系 {reason.reference.relation_id} · 修订 #{reason.reference.relation_revision} · {reason.reference.relation_revision_id}<br />检查 {reason.reference.field} · match · 原值 {valueText(reason.reference.value)}</p></article>) : <p>没有可供选择的肯定理由，模型不得补写来源事实。</p>}
  </details>;
}

function AuthorizationForm({ dependency, changed, provider, disabled, onAuthorize }: { dependency: CandidateAiDependency; changed?: CandidateAiAuthorization; provider: string; disabled: boolean; onAuthorize: (payload: CandidateAiAuthorizationRequest) => Promise<void> }) {
  const [action, setAction] = useState<"grant" | "revoke">("grant"), [providerName, setProviderName] = useState(provider);
  const [holder, setHolder] = useState(""), [url, setUrl] = useState(""), [note, setNote] = useState(""), [hash, setHash] = useState(""), [expiry, setExpiry] = useState(""), [revocationNote, setRevocationNote] = useState("");
  const [ack, setAck] = useState(false);
  const head = changed || dependency.authorization;
  return <details className="candidate-ai-admin"><summary>管理员：追加用途许可或撤销</summary><p>管理员身份不证明来源权利。只按已核实的精确许可依据声明，不自动授予生产来源许可；过期许可仍可追加撤销。</p>
    <form onSubmit={event => {
      event.preventDefault(); if (!ack || disabled) return;
      const command = { dependency_id: dependency.id, provider: providerName, expected_revision: head?.revision || 0, acknowledged: true as const };
      if (action === "revoke") {
        if (!head || !revocationNote.trim()) return;
        void onAuthorize({ ...command, action, revocation_note: revocationNote.trim() });
      } else {
        if (!expiry || !Number.isFinite(Date.parse(expiry))) return;
        void onAuthorize({ ...command, action, rights_holder: holder, license_basis_url: url, license_basis_note: note, license_evidence_sha256: hash, expires_at: new Date(expiry).toISOString() });
      }
    }}>
      <fieldset disabled={disabled}><div className="candidate-ai-admin-grid">
        <label><span>许可操作</span><select value={action} onChange={event => { setAction(event.target.value as "grant" | "revoke"); setAck(false); }}><option value="grant">追加本用途许可</option><option value="revoke">追加撤销</option></select></label>
        <label><span>许可适用 Provider</span><input value={providerName} maxLength={100} required onChange={event => { setProviderName(event.target.value); setAck(false); }} /></label>
        {action === "grant" ? <><label><span>实际权利人</span><input value={holder} maxLength={200} required onChange={event => { setHolder(event.target.value); setAck(false); }} /></label>
        <label><span>许可证据 URL（无凭据或身份参数）</span><input type="url" value={url} maxLength={2048} required onChange={event => { setUrl(event.target.value); setAck(false); }} /></label>
        <label className="candidate-ai-full"><span>许可依据与本用途范围</span><textarea value={note} rows={3} maxLength={2000} required onChange={event => { setNote(event.target.value); setAck(false); }} /></label>
        <label className="candidate-ai-full"><span>真实许可证据 SHA-256</span><input value={hash} pattern="[a-f0-9]{64}" minLength={64} maxLength={64} required onChange={event => { setHash(event.target.value); setAck(false); }} /></label>
        <label><span>许可有效期</span><input type="datetime-local" value={expiry} required onChange={event => { setExpiry(event.target.value); setAck(false); }} /></label></> : <label className="candidate-ai-full"><span>撤销说明</span><textarea value={revocationNote} rows={3} maxLength={2000} required onChange={event => { setRevocationNote(event.target.value); setAck(false); }} /></label>}
      </div>{action === "revoke" ? <p>{head ? `撤销许可修订 #${head.revision}，继承原权利人与证据，不重新授予许可。` : "本项没有可撤销的许可记录。"}</p> : null}<label className="candidate-ai-consent"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)} /><span>{action === "grant" ? "我已核对权利人、许可证据及本 Provider 的规格辅助用途；这不是个人外发同意。" : "我确认追加上述用途许可的撤销记录；这不会取消既有调用。"}</span></label>
      <button type="submit" className="secondary-button" disabled={!ack || action === "revoke" && !head}>{action === "grant" ? "记录这项用途许可修订" : "记录这项用途撤销"}</button></fieldset>
    </form>
  </details>;
}

function RecommendationResult({ run }: { run: CandidateAiRecommendation }) {
  const names = new Map(run.preparation.candidates.map(candidate => [candidate.variant_id, candidateLabel(candidate)]));
  return <section className="candidate-ai-result" data-testid="candidate-ai-result" aria-live="polite"><h4>{stateLabels[run.state]}</h4><p className="review-boundary">冻结历史 · {stamp(run.created_at)}。这不是当前有效推荐；{run.current_status.state === "stale" ? "重新核对时，许可或依据已变化。" : "最近只读核对未发现依据变化，仍不构成实时承诺。"}</p>
    <p>{performanceBoundary}</p><p>本次{run.preparation.selection.axle === "front" ? "前轴" : "后轴"} · 包 {run.pack_id}</p>
    {run.current_status.blockers.map((code, index) => <p className="review-warning" key={`${code}:${index}`}>{blockerText(code)}</p>)}
    {run.error_code ? <p role="alert">本次辅助未完成（{run.error_code}），没有采纳草稿或补写建议。</p> : null}
    {run.answer ? <><h5>{run.answer.decision === "abstain" ? "模型未选择规格候选" : "模型提出的后续核对选项 · 无优劣排序"}</h5>
      {run.answer.selections.map(selection => <article className="candidate-ai-proposal" key={selection.variant_id}><strong>{names.get(selection.variant_id)}</strong>{selection.reasons.map(reason => <div key={reason.id}><p>{reason.text}</p><p className="candidate-ai-hash">核对理由 {reason.id} · 关系修订 {reason.reference.relation_revision_id} · 字段 {reason.reference.field} · 原值 {valueText(reason.reference.value)}</p></div>)}</article>)}
      <p>本次未选：{run.answer.not_selected_variant_ids.map(id => names.get(id) || id).join("；") || "无"}。未选不表示不适配，也不证明被选项性能更好。</p>
      <h5>完整不足与不确定性</h5><ul>{run.answer.uncertainty.map((item, index) => <li key={`${item.code}:${index}`}>{item.text}</li>)}</ul><p className="review-boundary">{run.answer.notice}</p>
      <details><summary>重开全部冻结来源事实及未知项</summary>{run.preparation.candidates.map(candidate => <CandidateFacts key={candidate.variant_id} candidate={candidate} />)}</details>
    </> : <p>没有可正式展示的建议。待确认或失败的调用不自动重试；请只读核对原记录。</p>}
    <p className="candidate-ai-usage">{run.usage ? `已记账 ${run.usage.total_tokens.toLocaleString()} tokens` : `实际用量未确认，保留 ${run.reserved_tokens.toLocaleString()} tokens 预留`}；不是供应商账单金额。</p>
  </section>;
}
