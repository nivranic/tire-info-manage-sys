"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { RecallDiscoveryCoverage, RecallDiscoveryList, RecallDiscoveryRun, RecallDiscoveryRunDetail, RecallSearchEvidence } from "@tire/domain-types";
import { DataTree } from "./reparse-review";
import { discoveryCampaignValid, discoveryCoverageComplete, discoveryNoticeHeading, discoveryReason, discoveryRunLabel } from "./recall-discovery-values";

const stamp = (value: string | null | undefined) => value ? new Date(value).toLocaleString("zh-CN") : "尚未记录";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "读取扫描记录未完成。";

export function DiscoveryPolicy() {
  return <p className="review-boundary discovery-policy">每轮从第一页开始扫描并再读一遍核对。每遍最多 20 页、200 个产品；两遍合计最多 40 次页面读取、300 秒、64 MiB 原文。页面读取次数不等于网络请求次数。两遍完整内容一致才推进基线，但不保证来源在同一时刻的原子快照。首次完整扫描只建立基线；不完整扫描不推进基线，也不产生新增候选提醒。</p>;
}

export function DiscoveryCoverage({ run }: { run: RecallDiscoveryRun }) {
  const coverage: RecallDiscoveryCoverage = run.coverage;
  const complete = discoveryCoverageComplete(coverage);
  return <section className="discovery-coverage" aria-label="本轮扫描覆盖"><div className="recall-section-heading"><h4>{discoveryRunLabel(run)}</h4><span className={`tag ${complete ? "success" : "warning"}`}>{complete ? "本轮双遍完整" : "仍有未确认范围"}</span></div>
    <p>{discoveryNoticeHeading(run)}</p><p className="recall-help">开始：{stamp(run.started_at)} · 结束：{stamp(run.finished_at)}。完整表示两遍返回内容一致，不是官方数据的原子快照，也不是轮胎安全结论。</p>
    <dl className="recall-meta"><div><dt>完成遍数</dt><dd>{coverage.passes_completed} / {coverage.passes_required}</dd></div><div><dt>页面读取操作</dt><dd>{coverage.page_operations} / {coverage.budget.max_page_operations}</dd></div><div><dt>已完成页记录</dt><dd>{coverage.pages_completed}</dd></div><div><dt>覆盖产品</dt><dd>{coverage.products_count}</dd></div><div><dt>候选公告</dt><dd>{coverage.candidates_count}</dd></div><div><dt>本轮新增观察</dt><dd>{complete && !coverage.is_initial_baseline ? coverage.new_candidates_count : "本轮不发送新增提醒"}</dd></div><div><dt>累计原文</dt><dd>{(coverage.raw_bytes / 1024 / 1024).toFixed(2)} / {(coverage.budget.max_raw_bytes / 1024 / 1024).toFixed(0)} MiB</dd></div><div><dt>扫描与核对用时</dt><dd>{coverage.elapsed_seconds.toFixed(1)} / {coverage.budget.max_elapsed_seconds} 秒</dd></div></dl>
    {!complete ? <p className="review-warning">本轮未确认全部返回范围，不能将已读取的页面当成全部结果。关键词过宽时请新建更具体的名称规则。{run.reason ? ` 原因：${discoveryReason(run.reason)}` : ""}</p> : null}
    <p className="recall-help">{coverage.baseline_advanced ? "本轮已推进完整基线。" : "本轮未推进完整基线。"}{run.previous_complete_id ? <> 上一完整扫描标识：<code>{run.previous_complete_id}</code></> : " 尚无上一完整扫描。"}</p>
    <DataTree label="双遍内容指纹与预算记录" value={{ pass_fingerprints: coverage.pass_fingerprints, budget: coverage.budget }} />
  </section>;
}

export function DiscoverySearchEvidence({ id, onClose }: { id: string; onClose: () => void }) {
  const [data, setData] = useState<RecallSearchEvidence | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    heading.current?.focus({ preventScroll: true });
    return () => { if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError("");
    void tireApi.recallSearchEvidence(id, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, version]);
  return <section className="recall-evidence discovery-page-evidence" aria-label="扫描页原始证据"><div className="recall-section-heading"><h4 ref={heading} tabIndex={-1}>检索页历史原文</h4><button type="button" className="text-button" onClick={onClose}>收起页证据</button></div><p className="review-boundary">只读取已保存的检索页，不在线查询，也不核验或采纳公告。</p>
    {error ? <p className="inline-error" role="alert">{error}<button type="button" className="text-button" onClick={() => setVersion(value => value + 1)}>重新读取页证据</button></p> : data ? <><dl className="recall-meta"><div><dt>检索条件</dt><dd>{data.query?.search || "记录中未提供"} · 起始位置 {data.query?.offset ?? "未记录"}</dd></div><div><dt>原文观察时间</dt><dd>{stamp(data.observed_at)}</dd></div><div><dt>历史核验时间</dt><dd>{stamp(data.verified_at)}</dd></div><div><dt>解析版本</dt><dd>{data.parser_version}</dd></div><div><dt>原文 SHA-256</dt><dd><code>{data.raw_hash}</code></dd></div><div><dt>官方来源地址</dt><dd>{data.source_url}</dd></div></dl><DataTree label="检索页完整原文" value={data.body} /><DataTree label="该页解析器身份" value={data.parser_identity} /></> : <p role="status">正在读取页证据…</p>}
  </section>;
}

export function DiscoveryRunDialog({ id, onClose, onChoose }: { id: string; onClose: () => void; onChoose?: (campaign: string) => void }) {
  const [data, setData] = useState<RecallDiscoveryRunDetail | null>(null);
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState("");
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); if (previous?.isConnected && !previous.closest("dialog:not([open])")) previous.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(""); setEvidenceId(null);
    void tireApi.discoveryRun(id, offset, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.scope !== "session" || value.id !== id || value.page_offset !== offset || !Array.isArray(value.pages)) throw new Error("扫描记录与当前会话或页码不匹配。");
      setData(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, offset, version]);
  return <dialog ref={dialog} className="fact-review-dialog discovery-run-dialog" aria-labelledby="discovery-run-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">RECALL DISCOVERY · SAVED SCAN</span><h2 id="discovery-run-title">名称发现扫描与页证据</h2></div><button type="button" className="text-button" onClick={onClose}>关闭扫描记录</button></header>
    <div className="fact-review-content"><p className="review-boundary">当前会话的历史扫描，只读取已保存记录；不重新执行，不自动核验公告。公告候选的实物适用性尚未评估。</p>
      {error ? <p className="inline-error" role="alert">{error}<button type="button" className="text-button" onClick={() => setVersion(value => value + 1)}>重新读取扫描</button></p> : data ? <><h3>名称关键词：{data.query.search}</h3><DiscoveryCoverage run={data} />
        <section className="discovery-pages" aria-label="双遍扫描分页证据"><h3>双遍页记录 · {data.pages_total}</h3><p className="recall-help">按遍次与页码查看查询、原文和在线验证引用。失败页可能没有可读取的快照；各页历史验证时间不表示同时取得。</p>
          {data.pages.map(page => <article className="discovery-page" key={page.id}><h4>第 {page.pass_number} 遍 · 第 {Math.floor(page.offset / 10) + 1} 页</h4><p>本页产品：{page.count ?? "未确认"} · 此页返回的匹配总数：{page.total ?? "未确认"} · 观察时间：{stamp(page.observed_at)}</p><dl className="discovery-reference-list"><div><dt>查询引用</dt><dd><code>{page.query_id || "未记录"}</code></dd></div><div><dt>原文快照</dt><dd><code>{page.snapshot_id || "未保存有效快照"}</code></dd></div><div><dt>在线验证引用</dt><dd><code>{page.verification_id || "未完成验证"}</code></dd></div><div><dt>内容指纹</dt><dd><code>{page.content_fingerprint || "未记录"}</code></dd></div></dl>{page.snapshot_id ? <button type="button" className="secondary-button" onClick={() => setEvidenceId(page.snapshot_id)}>查看第 {page.pass_number} 遍第 {Math.floor(page.offset / 10) + 1} 页原文</button> : null}</article>)}
          {!data.pages.length ? <p className="recall-empty">当前页没有已保存的扫描页记录。</p> : null}<div className="reparse-pages"><button type="button" className="text-button" disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一组页证据</button><span>第 {Math.floor(offset / 20) + 1} 组</span><button type="button" className="text-button" disabled={offset + data.pages.length >= data.pages_total} onClick={() => setOffset(value => value + 20)}>下一组页证据</button></div>
        </section>
        {evidenceId ? <DiscoverySearchEvidence key={evidenceId} id={evidenceId} onClose={() => setEvidenceId(null)} /> : null}
        <section className="discovery-candidates" aria-label="本轮首次记录的候选"><h3>本轮首次记录候选 · {data.candidates_total}</h3><p className="recall-help">不完整扫描仅保留页证据，不把其中的候选写入基线或提醒。首次基线候选也不等于新发布的公告。</p>{data.candidates_truncated ? <p className="review-warning">此处最多展示 100 个候选，完整页面证据可在上方分组读取。</p> : null}
          {data.candidates.map(candidate => <article className="discovery-candidate" key={candidate.id}><h4>{candidate.campaign_number}</h4><p className="recall-help">本监控首次观察：{stamp(candidate.first_seen_at)} · 实物适用性未评估</p><DataTree label="该候选保存的公告字段" value={candidate.campaign} /><DataTree label="匹配产品及页证据引用" value={candidate.evidence} />{onChoose ? <button type="button" className="secondary-button" disabled={!discoveryCampaignValid(candidate.campaign_number)} onClick={() => { onClose(); onChoose(candidate.campaign_number); }}>选用此编号，准备在线核验</button> : null}</article>)}{!data.candidates.length ? <p className="recall-empty">本轮没有可列出的首次记录候选，不能据此推导没有召回。</p> : null}
        </section>
      </> : <p role="status">正在读取扫描记录…</p>}
    </div>
  </dialog>;
}

export function DiscoveryRunHistory({ jobId, refreshKey, onChoose }: { jobId: string; refreshKey?: string | number | null; onChoose?: (campaign: string) => void }) {
  const [data, setData] = useState<RecallDiscoveryList<RecallDiscoveryRun> | null>(null);
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setError(""); setData(null);
    void tireApi.discoveryRuns(jobId, offset, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.scope !== "session" || value.offset !== offset || !Array.isArray(value.items) || value.items.some(run => run.job_id !== jobId)) throw new Error("扫描列表与当前任务范围不匹配。");
      setData(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [jobId, offset, version, refreshKey]);
  return <section className="discovery-run-history" aria-label="名称发现扫描历史"><div className="recall-section-heading"><h3>扫描覆盖与页证据{data ? ` · ${data.total}` : ""}</h3><button type="button" className="text-button" onClick={() => setVersion(value => value + 1)}>刷新扫描记录</button></div>
    {error ? <p className="inline-error" role="alert">{error}</p> : data ? <>{data.items.map(run => <article className="discovery-run-row" key={run.id}><div><h4>{discoveryRunLabel(run)}</h4><p>{stamp(run.finished_at)} · 完成 {run.coverage.passes_completed} / 2 遍 · {run.coverage.page_operations} 次页面读取</p><p className="recall-help">{discoveryNoticeHeading(run)}</p></div><button type="button" className="secondary-button" onClick={() => setRunId(run.id)}>查看扫描覆盖与原文</button></article>)}{!data.items.length ? <p className="recall-empty">尚无已保存的扫描终态。查看记录不会启动扫描。</p> : null}<div className="reparse-pages"><button type="button" className="text-button" disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页扫描</button><span>第 {Math.floor(offset / 20) + 1} 页</span><button type="button" className="text-button" disabled={offset + data.items.length >= data.total} onClick={() => setOffset(value => value + 20)}>下一页扫描</button></div></> : <p role="status">正在读取扫描历史…</p>}
    {runId ? <DiscoveryRunDialog key={runId} id={runId} onClose={() => setRunId(null)} onChoose={onChoose} /> : null}
  </section>;
}
