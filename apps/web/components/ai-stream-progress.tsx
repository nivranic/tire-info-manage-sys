"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIStreamDetail, AIStreamEvent } from "@tire/domain-types";
import { RecallAnalysisBoundary } from "./recall-evidence-meta";
import { useWorkbenchPlatform } from "./workbench-platform";
import { advanceAIEvent, AI_RECOVERY_KEY, aiStreamStateLabels, visibleAIDrafts, type AIEventPosition, type AIRecoveryPointer } from "./ai-stream-values";

type Connection = "connecting" | "streaming" | "polling" | "reconnecting" | "disconnected" | "paused" | "finished" | "unavailable";
const connectionLabels: Record<Connection, string> = {
  connecting: "正在读取已保存进度", streaming: "已连接分析进度", polling: "正在定时读取分析进度",
  reconnecting: "正在恢复同一请求的进度", disconnected: "进度连接中断，最新状态未知",
  paused: "页面已隐藏，暂停读取进度", finished: "已读取本次调用终态", unavailable: "当前会话无法读取此请求",
};
function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const cancel = () => { clearTimeout(timer); signal.removeEventListener("abort", cancel); reject(new DOMException("停止读取进度。", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, ms);
    if (signal.aborted) cancel(); else signal.addEventListener("abort", cancel, { once: true });
  });
}

export function AIStreamProgress({ initial, recovery, onDetail, onFact, errorLabel }: {
  initial: AIStreamDetail; recovery: AIRecoveryPointer | null;
  onDetail: (detail: AIStreamDetail) => void; onFact: (id: string) => void; errorLabel: (code: string) => string;
}) {
  const platform = useWorkbenchPlatform();
  const requestId = initial.analysis.id;
  const [detail, setDetail] = useState(initial);
  const [connection, setConnection] = useState<Connection>(initial.execution.terminal ? "finished" : "connecting");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [visible, setVisible] = useState(true);
  const [invalidated, setInvalidated] = useState(false);
  const position = useRef<AIEventPosition>({ cursor: recovery?.requestId === requestId && recovery.cursor ? recovery.cursor : initial.cursor, sequence: 0, eventId: null });
  const generation = useRef(0);
  const detailCallback = useRef(onDetail);
  const recoveryRef = useRef(recovery);
  const terminalObserved = useRef(initial.execution.terminal);
  useEffect(() => { detailCallback.current = onDetail; recoveryRef.current = recovery; }, [onDetail, recovery]);
  useEffect(() => {
    const changed = () => setVisible(document.visibilityState === "visible");
    changed(); document.addEventListener("visibilitychange", changed);
    return () => document.removeEventListener("visibilitychange", changed);
  }, []);
  useEffect(() => {
    if (!visible) { setConnection("paused"); return; }
    const controller = new AbortController(), signal = controller.signal, runGeneration = ++generation.current;
    const current = () => !signal.aborted && runGeneration === generation.current;
    let failures = 0, resets = 0, finished = false;
    function remember() {
      const pointer = recoveryRef.current;
      if (!pointer || pointer.requestId !== requestId) return;
      try { sessionStorage.setItem(AI_RECOVERY_KEY, JSON.stringify({ key: pointer.key, requestId, cursor: position.current.cursor })); } catch { /* History remains available if tab storage is blocked. */ }
    }
    async function readDetail(reset = false) {
      const value = await tireApi.aiStream(requestId, signal);
      if (!current()) return;
      if (terminalObserved.current && !value.execution.terminal) throw new Error("已收到终态提示，最终记录尚未核对成功；草稿已隐藏。");
      if (reset) position.current = { cursor: value.cursor, sequence: 0, eventId: null };
      finished = value.execution.terminal; terminalObserved.current = finished;
      setDetail(value); setInvalidated(false); setError(""); detailCallback.current(value); remember();
      if (finished) setConnection("finished");
      return value;
    }
    function accept(event: AIStreamEvent) {
      position.current = advanceAIEvent(requestId, position.current, event); remember();
      if (["completed", "failed", "outcome_unknown"].includes(event.type)) {
        terminalObserved.current = true; setInvalidated(true);
      }
    }
    async function follow() {
      setConnection("connecting"); setError("");
      while (current() && !finished) {
        try {
          await readDetail(!position.current.cursor);
          if (!current() || finished) return;
          if (platform.kind === "web") {
            setConnection("streaming");
            const result = await tireApi.streamAIEvents(requestId, position.current.cursor, async message => {
              if (!current()) return;
              if (message.type === "reset") {
                if (++resets > 3) throw new Error("AI 进度游标连续失效，请手动重新读取。");
                position.current = { cursor: "", sequence: 0, eventId: null };
                setInvalidated(true); setConnection("reconnecting"); return;
              }
              if (message.type === "ai_event") accept(message.data);
              else if (message.data.cursor !== position.current.cursor) throw new Error("AI 心跳跳过了未读取事件，请重新核对进度。");
              await readDetail();
              if (current()) { failures = 0; resets = 0; if (finished) controller.abort(); }
            }, signal);
            if (!current() || finished) return;
            if (result === "reset") continue;
            await delay(250, signal);
          } else {
            setConnection("polling");
            let pages = 0, more = true;
            while (more && current() && !finished && pages < 4) {
              const page = await tireApi.aiStreamEvents(requestId, position.current.cursor, signal);
              if (!current()) return;
              for (const event of page.items) accept(event);
              position.current.cursor = page.next_cursor; remember(); more = page.has_more; pages++;
              await readDetail();
            }
            if (!current() || finished) return;
            failures = 0; resets = 0; await delay(more ? 500 : 2500, signal);
          }
        } catch (cause) {
          if (!current() || (cause instanceof Error && cause.name === "AbortError")) return;
          setInvalidated(true);
          if (cause instanceof ApiError && cause.code === "ai_stream_cursor_reset_required" && ++resets <= 3) {
            position.current = { cursor: "", sequence: 0, eventId: null }; setConnection("reconnecting"); continue;
          }
          if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
            setConnection("unavailable"); setError("会话或访问范围已变化。此处不会重新提交模型调用。"); return;
          }
          setConnection("disconnected"); setError(cause instanceof Error ? cause.message : "分析进度暂时无法读取。");
          if (++failures >= 5) return;
          try { await delay(Math.min(1000 * 2 ** (failures - 1), 8000), signal); } catch { return; }
        }
      }
    }
    void follow();
    return () => { generation.current++; controller.abort(); };
  }, [requestId, platform.kind, refresh, visible]);

  const draft = visibleAIDrafts(detail, invalidated);
  const terminal = detail.execution.terminal;
  const recallPack = !!detail.analysis.pack?.evidence.some(evidence => evidence.evidence_type === "recall");
  return <section className="ai-stream-progress" aria-label="AI 分析实时进度">
    <div className="ai-stream-heading"><h3>{aiStreamStateLabels[detail.execution.state]}</h3><button type="button" className="secondary-button" onClick={() => setRefresh(value => value + 1)}>重新读取进度</button></div>
    <RecallAnalysisBoundary boundary={detail.analysis.pack?.recall_boundary} pending={recallPack} />
    <p className="ai-stream-question">本次问题：{detail.analysis.question}</p>
    <p className="ai-stream-connection" role="status" aria-live="polite">{connectionLabels[connection]} · 最后读取 {new Date(detail.server_time).toLocaleTimeString("zh-CN")}</p>
    <p className="review-boundary">只读取同一调用的已保存进度。断线、刷新或关闭窗口不会重复调用模型，也不能保证已取消供应商处理或免于计费。</p>
    {platform.kind !== "web" ? <p className="ai-stream-meta">原生端使用同一游标定时读取进度。</p> : null}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {detail.execution.projection_only ? <p className="review-warning">执行期限已过，尚无可确认的完成记录。此状态不代表供应商没有计费，也不会恢复或重试模型调用。</p> : null}
    {detail.analysis.error_code ? <p className="review-warning">{errorLabel(detail.analysis.error_code)} 生成中内容已作废。</p> : null}
    {!terminal ? <section className="ai-stream-drafts" aria-label="未完成校验的分析草稿">
      <h4>生成中草稿 · 整份结果尚未完成引用校验</h4>
      <p className="review-warning">以下仅为完整片段的临时投影，仍可能被最终校验拒绝。不能作为正式分析或保存为含分析的报告。</p>
      {draft.claims.filter(({ claim }) => !recallPack || claim.type === "fact").map(({ index, claim }) => <article className={`ai-claim ${claim.type}`} key={index}>
        <strong>{claim.type === "fact" ? "证据字段草稿" : "模型推断草稿 · 需人工核对"}</strong><p>{claim.text}</p>
        <div className="compare-toolbar">{claim.fact_ids.map(id => <button type="button" className="text-button" key={id} onClick={() => onFact(id)}>核对 {id}</button>)}</div>
      </article>)}
      {!recallPack && draft.uncertainty !== null ? <article className="ai-claim inference"><strong>生成中的不确定性说明 · 尚未正式采纳</strong><p>{draft.uncertainty}</p></article> : null}
      {!draft.claims.length && draft.uncertainty === null ? <p>{invalidated ? "连接或校验状态待核对，已隐藏临时草稿。" : "尚未收到可展示的完整片段。"}</p> : null}
    </section> : null}
  </section>;
}
