"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, apiTransportAuthorityEpoch, observeApiTransportAuthority, tireApi } from "@tire/api-client";
import type { BinaryQuarantineReviewRequestV2, BinaryQuarantineReviewStateV2 } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import type { RawEvidenceReader } from "./raw-evidence-v2";
import { assertRawEvidenceDisplay, createRawEvidenceOperations, freezeRawEvidenceDisplay, rawEvidenceCanonical,
  RawEvidenceDisplayChanged, type RawEvidenceOwner } from "./raw-evidence-v2-context";
import { assertFrozenBinaryReviewBasis, binaryReviewEventBasis, binaryReviewInput, binaryReviewLossRows, captureBinaryReviewOwner,
  freezeBinaryReviewBasis, isBinaryQuarantineDetail, type BinaryQuarantineDetail, type BinaryReviewBasis,
  type BinaryReviewDisplay, type BinaryReviewRevocation } from "./binary-quarantine-review-context";

const labels: Record<BinaryQuarantineReviewStateV2["state"], string> = {
  pending: "尚未人工处理", restricted: "涉及身份或证据问题，须先修复",
  stale_baseline: "正式对照已更新，需后续在线核验", kept_quarantined: "已保留隔离",
  expired: "批准已过期，需重新核对", approved_waiting_online: "已批准，等待后续新在线请求",
  applied_on_online_fetch: "批准已随在线核验生效",
};
const uncertainText = "提交结果待核对。请只读核对当前服务器状态后再决定；公开历史不能证明哪一条来自本次提交，不会自动重发。";
const errorText = (cause: unknown) => cause instanceof ApiError
  ? cause.status === 403 ? `当前权限或来源用途许可不允许读取/审批（HTTP 403${cause.code ? `，${cause.code}` : ""}）。`
    : `审批读取或提交未完成（HTTP ${cause.status}${cause.code ? `，${cause.code}` : ""}）。`
  : cause instanceof RawEvidenceDisplayChanged ? cause.message : "审批依据未通过读取或完整性校验，请重新读取原件与审批。";
type Operation = ReturnType<ReturnType<typeof createRawEvidenceOperations>["begin"]>;
type Basis = { display: BinaryReviewDisplay; owner: ReturnType<typeof captureBinaryReviewOwner> };
type View = { stamp: string; display: BinaryReviewDisplay | null; loading: boolean; busy: boolean; error: string; notice: string };
class DisplayedBinaryDetailChanged extends RawEvidenceDisplayChanged {}

export default function BinaryQuarantineReview({ detail, reader, selectionKey, revocation, enabled }: {
  detail: BinaryQuarantineDetail; reader: RawEvidenceReader; selectionKey: string;
  revocation: BinaryReviewRevocation; enabled: boolean;
}) {
  const auth = useWorkbenchAuth();
  const [revision, setRevision] = useState(0), [operator, setOperator] = useState(""), [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const selection = rawEvidenceCanonical([detail.id, selectionKey, detail, revision]);
  const transportEpoch = apiTransportAuthorityEpoch();
  const stamp = rawEvidenceCanonical([selection, revocation.generation(), auth.ownerEpoch, transportEpoch]);
  const mounted = useRef(true), current = useRef<RawEvidenceOwner>({ ...auth, selection, transportEpoch });
  const live = () => ({ ...current.current, ready: mounted.current && current.current.ready,
    // Read the getter on every check: legacy offline-sync can advance without notifying observers.
    transportEpoch: apiTransportAuthorityEpoch(), selection: rawEvidenceCanonical([current.current.selection, revocation.generation()]) });
  const getLive = useRef(live); getLive.current = live;
  const operations = useRef<ReturnType<typeof createRawEvidenceOperations> | null>(null);
  if (!operations.current) operations.current = createRawEvidenceOperations(() => getLive.current(), callback => observeApiTransportAuthority(callback));
  const basis = useRef<Basis | null>(null), confirmation = useRef<{ canonical: string; input: string } | null>(null);
  const pendingPost = useRef<Operation | null>(null), busy = useRef(false), reloadNotice = useRef("");
  const [view, setView] = useState<View>({ stamp, display: null, loading: false, busy: false, error: "", notice: "" });
  const previous = current.current;
  current.current = { ready: enabled && auth.ready, ownerEpoch: auth.ownerEpoch, ownerSignal: auth.ownerSignal,
    isCurrentOwner: auth.isCurrentOwner, selection, transportEpoch };
  if (previous.selection !== selection || previous.ownerEpoch !== auth.ownerEpoch || previous.ownerSignal !== auth.ownerSignal
    || previous.transportEpoch !== transportEpoch || previous.ready !== current.current.ready) {
    operations.current.invalidate(); basis.current = null; confirmation.current = null;
  }
  const revoke = useRef(() => {});
  revoke.current = () => {
    if (pendingPost.current) revocation.markUncertain(detail.id);
    pendingPost.current = null; operations.current!.invalidate(); basis.current = null; confirmation.current = null; busy.current = false;
    if (mounted.current) {
      setConfirmed(false);
      setView({ stamp, display: null, loading: false, busy: false, error: "", notice: revocation.isUncertain(detail.id) ? uncertainText : "审批上下文已变化，请重新读取并确认。" });
    }
  };
  useLayoutEffect(() => {
    mounted.current = true;
    const stopParent = revocation.subscribe(() => revoke.current());
    const stopTransport = observeApiTransportAuthority(() => { revoke.current(); setRevision(value => value + 1); });
    return () => {
      // No setState during unmount; any dispatched write remains uncertain.
      mounted.current = false; revoke.current(); stopParent(); stopTransport();
    };
  }, [revocation]);
  useLayoutEffect(() => {
    const signal = auth.ownerSignal, onAbort = () => revoke.current();
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
    return () => signal.removeEventListener("abort", onAbort);
  }, [auth.ownerSignal]);

  const selected = { id: detail.id, sourceId: detail.source_id, query: { vehicle_id: detail.vehicle_id } };
  async function readBasis(operation: Operation, displayedDetail: BinaryQuarantineDetail): Promise<BinaryReviewBasis> {
    const check = operation.fence.assertCurrent;
    check(); const nextDetail = await tireApi.quarantineEvidenceV2(selected.id, operation.fence, operation.controller.signal); check();
    // Original panel and approval panel must refer to the same complete detail metadata.
    try { assertRawEvidenceDisplay(freezeRawEvidenceDisplay("quarantine", displayedDetail), "quarantine", nextDetail); }
    catch (cause) { if (cause instanceof RawEvidenceDisplayChanged) throw new DisplayedBinaryDetailChanged(); throw cause; }
    if (!isBinaryQuarantineDetail(nextDetail)) throw new RawEvidenceDisplayChanged();
    check(); const review = await tireApi.quarantineReviewV2(selected.id, operation.fence, operation.controller.signal); check();
    check(); const capture = await tireApi.captureEvidenceV2(nextDetail.raw_capture_id, operation.fence, operation.controller.signal); check();
    const result = { detail: nextDetail, review, capture };
    freezeBinaryReviewBasis(result, selected); check();
    return result;
  }
  function install(operation: Operation, next: BinaryReviewBasis, notice: string) {
    operation.fence.assertCurrent();
    const display = freezeBinaryReviewBasis(next, selected), owner = captureBinaryReviewOwner(() => getLive.current());
    owner.assertCurrent(); operation.fence.assertCurrent();
    basis.current = { display, owner }; confirmation.current = null; busy.current = false; setConfirmed(false);
    setView({ stamp, display, loading: false, busy: false, error: "", notice });
  }
  useEffect(() => {
    basis.current = null; confirmation.current = null; busy.current = false; setConfirmed(false);
    if (!enabled || !auth.ready) return;
    let operation: Operation;
    try { operation = operations.current!.begin(); } catch { return; }
    const notice = revocation.isUncertain(detail.id) ? uncertainText : reloadNotice.current;
    reloadNotice.current = "";
    setView({ stamp, display: null, loading: true, busy: false, error: "", notice });
    void (async () => {
      try { operation.fence.assertCurrent(); const next = await readBasis(operation, detail); operation.fence.assertCurrent(); install(operation, next, notice); }
      catch (cause) {
        try { operation.fence.assertCurrent(); } catch { return; }
        basis.current = null; confirmation.current = null;
        setView({ stamp, display: null, loading: false, busy: false, error: errorText(cause), notice });
        if (cause instanceof DisplayedBinaryDetailChanged) reader.reload();
      } finally { operation.finish(); }
    })();
    return () => { operation.controller.abort(); operation.finish(); };
    // Selection contains all displayed detail metadata; async work is guarded by live refs/fences.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp, enabled, auth.ready]);

  function currentBasis(): Basis | null {
    const value = basis.current;
    try { value?.owner.assertCurrent(); return value; } catch { return null; }
  }
  function clearConfirmation() { confirmation.current = null; setConfirmed(false); }
  function confirm(value: boolean) {
    clearConfirmation();
    const valueBasis = binaryReviewEventBasis(basis.current, () => revoke.current()), input = binaryReviewInput(operator, reason);
    if (!value || !valueBasis || !input || busy.current) return;
    confirmation.current = { canonical: valueBasis.display.canonical, input: rawEvidenceCanonical(input) }; setConfirmed(true);
  }
  async function save(action: BinaryQuarantineReviewRequestV2["action"]) {
    const value = binaryReviewEventBasis(basis.current, () => revoke.current()), input = binaryReviewInput(operator, reason), token = confirmation.current;
    if (!value || !input || !token || token.canonical !== value.display.canonical || token.input !== rawEvidenceCanonical(input)
      || busy.current || !auth.ready || !auth.state.authenticated || !auth.state.user?.is_admin
      || !/^[A-Za-z0-9_-]{1,64}$/.test(auth.state.user.id) || value.display.metadata.review.applied_query_id
      || action === "approve" && !value.display.metadata.review.can_approve) return;
    const expectedAccountId = auth.state.user.id;
    let operation: Operation;
    try { value.owner.assertCurrent(); operation = operations.current!.begin(); } catch { revoke.current(); return; }
    busy.current = true; clearConfirmation();
    setView(state => ({ ...state, busy: true, error: "", notice: "正在重新核对完整审批依据…" }));
    let sent = false;
    try {
      value.owner.assertCurrent(); operation.fence.assertCurrent();
      const fresh = await readBasis(operation, value.display.metadata.detail); operation.fence.assertCurrent(); value.owner.assertCurrent();
      try { assertFrozenBinaryReviewBasis(value.display, fresh, selected); }
      catch (cause) {
        if (!(cause instanceof RawEvidenceDisplayChanged)) throw cause;
        install(operation, fresh, "完整审批依据已变化，已只读重新载入；请核对并重新确认。此次未发送审批。"); return;
      }
      const payload: BinaryQuarantineReviewRequestV2 = { action, expected_revision: fresh.review.revision, ...input,
        confirmed_loss: true, expected_binding_hash: fresh.review.binding_hash };
      // The original one-use confirmation is valid only for the exact frozen basis and inputs.
      value.owner.assertCurrent(); operation.fence.assertCurrent();
      if (token.canonical !== value.display.canonical || token.input !== rawEvidenceCanonical(input)) throw new RawEvidenceDisplayChanged();
      pendingPost.current = operation; sent = true;
      operation.fence.assertCurrent(); value.owner.assertCurrent();
      const result = await tireApi.reviewQuarantineV2(selected.id, payload, expectedAccountId, operation.fence, operation.controller.signal);
      operation.fence.assertCurrent(); value.owner.assertCurrent();
      // 201 is the real latest state; another same-binding review can already have superseded this action.
      install(operation, { ...fresh, review: result }, "已收到提交响应，以下展示服务器最新审批状态。批准如仍有效，仅供 24 小时内后续新在线请求尝试一次采纳。");
      pendingPost.current = null; setReason("");
    } catch (cause) {
      if (sent && !(cause instanceof ApiError && cause.status === 409)) revocation.markUncertain(selected.id);
      try { operation.fence.assertCurrent(); } catch { return; }
      basis.current = null; confirmation.current = null; busy.current = false; setConfirmed(false);
      if (sent) {
        reloadNotice.current = cause instanceof ApiError && cause.status === 409
          ? "审批依据、修订或账户已变化，正在只读重新核对；请核对后重新确认，不会自动重发。" : uncertainText;
        setView({ stamp, display: null, loading: false, busy: false, error: errorText(cause), notice: reloadNotice.current });
        setRevision(value => value + 1);
      } else {
        setView({ stamp, display: null, loading: false, busy: false, error: errorText(cause), notice: "未取得完整的当前审批依据，请重新读取。" });
        if (cause instanceof DisplayedBinaryDetailChanged) reader.reload();
      }
    } finally {
      if (pendingPost.current === operation) pendingPost.current = null;
      operation.finish();
    }
  }

  const visible = enabled && auth.ready && view.stamp === stamp;
  const display = visible ? view.display : null, review = display?.metadata.review;
  const input = binaryReviewInput(operator, reason), authenticatedAdmin = auth.ready && auth.state.authenticated && !!auth.state.user?.is_admin;
  const freshConfirm = !!confirmation.current && confirmation.current.canonical === display?.canonical && !!input
    && confirmation.current.input === rawEvidenceCanonical(input);
  const blocked = !authenticatedAdmin || !currentBasis() || !freshConfirm || !confirmed || !input || view.busy || view.loading;
  const losses = review ? binaryReviewLossRows(review.comparison.before, review.comparison.candidate) : [];
  return <section className="quarantine-review" aria-label="车辆 PDF 二进制隔离人工核验" aria-busy={visible && (view.loading || view.busy)}>
    <div className="panel-title"><h4>车辆 PDF 隔离人工核验</h4><button type="button" className="text-button" disabled={visible && view.busy} onClick={() => { revoke.current(); reader.reload(); }}>重新读取原件与审批</button></div>
    <p className="quality-intro">批准仅允许已经核对的缺行或字段缺失通过质量门槛；24 小时内后续新在线请求可尝试一次采纳，仍须完整 binding 一致。本操作不会发起在线采集或立即采纳这份历史内容。</p>
    <p className="review-boundary">原件收件、读取和质量批准均不代表来源用途许可、正式事实、Golden 人工真值或解析器发布批准。</p>
    {!auth.ready ? <p role="status">账户上下文尚未就绪，审批资格已撤销。</p> : !authenticatedAdmin ? <p className="review-warning" role="status">可只读核对；两个决定均须当前管理员账户登录并重新确认。</p> : null}
    {visible && view.error ? <p className="inline-error" role="alert">{view.error}</p> : null}
    {visible && view.notice ? <p className="review-saved" role="status">{view.notice}</p> : null}
    {visible && view.loading ? <p role="status">正在同一上下文内读取原件、审批对照与原件收件信息…</p> : null}
    {review ? <>
      <p className="quarantine-review-state"><strong>{labels[review.state]}</strong> · 修订 #{review.revision}</p>
      {review.restriction ? <p className="review-warning" role="status">限制：{review.restriction}。不能批准，须先修复身份或证据对应问题。</p> : null}
      <p>缺失类型：{display!.metadata.detail.reason_codes.filter(code => code === "row_loss_threshold" || code === "field_loss_threshold").map(code => code === "row_loss_threshold" ? "记录缺失" : "字段缺失").join("、") || "请核对限制原因"}</p>
      <details className="raw-evidence" open><summary>缺失记录与字段对照</summary>
        {losses.length ? losses.map((row, index) => <article key={`${row.path}:${index}`}><h5>{row.path}</h5><p>对照：{row.before}</p><p>本次候选：<strong>{row.candidate}</strong></p></article>) : <p>请继续核对下方完整结构与分组质量报告。</p>}
      </details>
      <details className="raw-evidence"><summary>完整对照与本次候选（保持真实 null 和缺失字段）</summary><h5>正式对照参数</h5><pre>{JSON.stringify(review.comparison.before, null, 2)}</pre><h5>本次尚未采纳的候选</h5><pre>{JSON.stringify(review.comparison.candidate, null, 2)}</pre></details>
      <details className="quality-technical"><summary>本次冻结的完整审批依据</summary><pre>{JSON.stringify(display!.metadata, null, 2)}</pre></details>
      {!review.applied_query_id ? <form className="review-form" onSubmit={event => event.preventDefault()}>
        <p>当前认证账户：{auth.state.authenticated && auth.state.user ? `${auth.state.user.display_name || auth.state.user.username}（${auth.state.user.id}）` : "未登录"}。下方署名为本地自报说明，历史记录不提供认证操作者归属。</p>
        <label><span>核验署名（自报，trim 后 1–80 个字符）</span><input value={operator} disabled={view.busy} onChange={event => { clearConfirmation(); setOperator(event.target.value); }} /></label>
        <label><span>决定依据（trim 后 5–2000 个字符）</span><textarea value={reason} disabled={view.busy} onChange={event => { clearConfirmation(); setReason(event.target.value); }} /></label>
        {!input && (operator || reason) ? <p role="status">请核对输入长度及字符；新输入将去除首尾空白，内部合法换行与制表符保留。</p> : null}
        <label className="review-checkbox"><input type="checkbox" checked={confirmed && freshConfirm} disabled={!authenticatedAdmin || !currentBasis() || !input || view.busy} onChange={event => confirm(event.target.checked)} /><span>已核对本次冻结的原件 metadata、完整解析身份、正式对照与所有缺失，确认处理依据</span></label>
        <div className="quarantine-review-actions"><button type="button" className="primary-button" disabled={blocked || !review.can_approve} onClick={() => void save("approve")}>批准，等待后续在线核验</button><button type="button" className="secondary-button" disabled={blocked} onClick={() => void save("keep_quarantined")}>保留隔离 / 撤回待生效批准</button></div>
      </form> : <p className="quality-intro">批准已随在线核验生效，原隔离历史仍保留。更正事实须另走人工纠错或版本管理。</p>}
      <details className="quality-technical"><summary>审批历史（{review.history.length}{review.history_truncated ? "+" : ""} 条）</summary><p>同一 binding 的其他隔离记录可能共享历史；署名为自报文本，不能据此认定本次认证操作者。</p>{review.history.length ? review.history.map(item => <article key={item.id}><p>#{item.revision} · {item.action === "approve" ? "批准待在线核验" : "保留隔离"} · 隔离记录 {item.quarantine_id}</p><pre>{item.operator}</pre><pre>{item.reason}</pre><p>记录时间：{item.created_at} · 截止：{item.expires_at}</p></article>) : <p>尚无人工决定。</p>}</details>
    </> : null}
  </section>;
}
