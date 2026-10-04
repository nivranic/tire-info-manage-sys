"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { QuarantineReviewState } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";

const labels: Record<QuarantineReviewState["state"], string> = {
  pending: "尚未人工处理", restricted: "涉及身份或证据问题，不能直接批准",
  stale_baseline: "对照基线已更新，需重新在线核验",
  kept_quarantined: "已决定保留隔离", expired: "批准已过期，需重新核对",
  approved_waiting_online: "已批准，等待下一次匹配的在线核验",
  applied_on_online_fetch: "批准已随在线核验生效",
};
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "审批操作未完成，请重试。";

export default function QuarantineReview({ id }: { id: string }) {
  const auth = useWorkbenchAuth();
  // 会话未就绪（ready=false，如首帧或桌面宿主未注入）时不禁用，避免误伤只读浏览。
  const adminBlocked = auth.ready && (!auth.state.authenticated || !auth.state.user?.is_admin);
  const [state, setState] = useState<QuarantineReviewState | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); setState(null); setError(""); setNotice(""); setConfirmed(false);
    void tireApi.quarantineReview(id, controller.signal).then(result => {
      if (!controller.signal.aborted) setState(result);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, revision]);
  async function save(action: "approve" | "keep_quarantined") {
    if (!state || busy || !confirmed || !operator.trim() || reason.trim().length < 5) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(""); setNotice("");
    try {
      const result = await tireApi.reviewQuarantine(id, { action, expected_revision: state.revision,
        operator, reason, confirmed_loss: confirmed }, controller.signal);
      if (!controller.signal.aborted) {
        setState(result); setConfirmed(false); setReason("");
        setNotice(action === "approve" ? "批准已记录。此操作未采纳历史参数，也未发起在线查询。" : "保留隔离已记录，先前待生效的批准已撤回。");
      }
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  const disabled = busy || !confirmed || !operator.trim() || reason.trim().length < 5;
  return <section className="quarantine-review" aria-label="人工核验隔离记录">
    <div className="panel-title"><h4>人工核验</h4><button type="button" className="text-button" disabled={busy} onClick={() => setRevision(value => value + 1)}>重新载入审批</button></div>
    <p className="quality-intro">批准仅允许已核对的缺失变化通过质量门槛；24 小时内，下一次在线请求的原文、解析器、候选参数与对照基线均一致时才会生效一次。不会将此历史记录当作实时参数，也不会代替离线回退授权。</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {notice ? <p className="review-saved" role="status">{notice}</p> : null}
    {state ? <>
      <p className="quarantine-review-state"><strong>{labels[state.state]}</strong> · 修订 #{state.revision}</p>
      <details className="raw-evidence"><summary>对照已采纳参数与本次候选</summary><p>原始结构仅以文本展示。请核对缺失的记录、字段及其来源，不确定时保留隔离。</p><h5>已采纳的对照参数</h5><pre>{JSON.stringify(state.comparison.before, null, 2)}</pre><h5>本次尚未采纳的候选参数</h5><pre>{JSON.stringify(state.comparison.candidate, null, 2)}</pre></details>
      {!state.applied_query_id ? <form className="review-form" onSubmit={event => event.preventDefault()}>
        <label><span>核验署名（本地自报）</span><input value={operator} maxLength={80} disabled={busy} onChange={event => setOperator(event.target.value)} /></label>
        <label><span>决定依据（至少 5 字）</span><textarea value={reason} maxLength={2000} disabled={busy} placeholder="说明核对了什么、为什么允许缺失或继续保留隔离" onChange={event => setReason(event.target.value)} /></label>
        <label className="review-checkbox"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} /><span>已核对原文、对照参数与本次缺失，确认以上处理依据</span></label>
        <div className="quarantine-review-actions"><button type="button" className="primary-button" disabled={disabled || adminBlocked || !state.can_approve} title={adminBlocked ? "需要管理员账户" : undefined} onClick={() => void save("approve")}>批准，待在线核验</button><button type="button" className="secondary-button" disabled={disabled || adminBlocked} title={adminBlocked ? "需要管理员账户" : undefined} onClick={() => void save("keep_quarantined")}>保留隔离 / 撤回批准</button></div>
      </form> : <p className="quality-intro">原隔离记录继续保留。生效后如需更正事实，请使用人工纠错或版本管理，不能撤写历史。</p>}
      <details className="quality-technical"><summary>审批历史（{state.history.length}{state.history_truncated ? "+" : ""} 条）</summary>{state.history.length ? state.history.map(item => <article key={item.id}><p>#{item.revision} · {item.action === "approve" ? "批准待在线核验" : "保留隔离"} · {item.operator} · {new Date(item.created_at).toLocaleString("zh-CN")}</p><p>{item.reason}</p>{item.action === "approve" ? <p>批准截止：{new Date(item.expires_at).toLocaleString("zh-CN")}</p> : null}</article>) : <p>尚无人工决定。</p>}</details>
    </> : !error ? <p role="status">正在读取审批与对照参数…</p> : null}
  </section>;
}
