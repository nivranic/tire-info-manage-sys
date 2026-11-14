"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { SamrRecallEvidence, SamrRecallQuery, SamrRecallResult } from "@tire/domain-types";
import { DataTree } from "./reparse-review";
import QueryFallbackPolicy from "./query-fallback-policy";
import { useSourceAccess } from "./source-status";
import SamrNoticeHistoryPanel from "./samr-notice-history";
import { SamrMonitoring } from "./samr-monitoring";
import type { AITarget } from "./ai-analysis";
import { samrTarget } from "./samr-ai-values";

const sourceId = "samr-cn-recalls";
const states: Record<SamrRecallResult["data_state"], string> = {
  live: "已在线核验", live_verified_304: "已在线核验 · 官方响应304",
  local_snapshot: "已保存的历史", consent_required: "等待本次历史读取授权", source_unavailable: "来源暂不可用",
};
type Pending = { query: SamrRecallQuery; queryId: string };
type Active = { controller: AbortController; generation?: number; online: boolean };

function ResultStatus({ value }: { value: SamrRecallResult }) {
  return <>
    <p role="status">{states[value.data_state]} · 核验时间 {value.verified_at ?? "未知"} · 快照观察时间 {value.snapshot_observed_at ?? "未知"}</p>
    {value.data_state === "local_snapshot" ? <p className="snapshot-banner">历史证据 · 当前官网状态待在线核验</p> : null}
    {value.fallback_authorization ? <DataTree label="持续回退授权与消费回执" value={value.fallback_authorization} /> : null}
  </>;
}

export default function SamrRecallPanel({ sessionReady, onAnalyze }: { sessionReady: boolean; onAnalyze?: (target: AITarget) => void }) {
  const access = useSourceAccess();
  const generation = access.get(sourceId)?.management.access_generation;
  const [history, setHistory] = useState(false);
  const [keyword, setKeyword] = useState("轮胎");
  const [catalog, setCatalog] = useState<SamrRecallResult | null>(null);
  const [result, setResult] = useState<SamrRecallResult | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [evidence, setEvidence] = useState<SamrRecallEvidence | null>(null);
  const [historyArticle, setHistoryArticle] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<Active | null>(null);

  function cancel() {
    active.current?.controller.abort();
    active.current = null;
    setBusy(false);
    setPending(null);
    setEvidence(null);
    setError("");
  }

  function clearResults() {
    cancel();
    setHistoryArticle(null);
    setCatalog(null);
    setResult(null);
  }

  function begin(online: boolean) {
    cancel();
    const context = { controller: new AbortController(), generation, online };
    active.current = context;
    setBusy(true);
    return context;
  }

  const current = (context: Active) => active.current === context && !context.controller.signal.aborted;
  const failed = (cause: unknown, context: Active) => {
    if (current(context)) setError(cause instanceof Error ? cause.message : "中国召回操作未完成。");
  };

  useEffect(() => () => { active.current?.controller.abort(); active.current = null; }, []);
  useEffect(() => { if (!sessionReady) clearResults(); }, [sessionReady]);
  useEffect(() => {
    const context = active.current;
    if (context?.online && context.generation !== undefined && context.generation !== generation) {
      clearResults();
      setError("来源状态已变化，请核对来源后重新查询。");
    }
  }, [generation]);

  async function load(query: SamrRecallQuery, consentFor?: string) {
    if (!sessionReady) return;
    const context = begin(!history);
    setHistoryArticle(null);
    if (query.operation === "search") setCatalog(null);
    setResult(null);
    try {
      if (!history && !await access.ensure(sourceId)) throw new Error("来源当前无法查询，请核对来源管理状态。");
      if (!current(context)) return;
      context.generation = access.get(sourceId)?.management.access_generation;
      let consentId: string | undefined;
      if (consentFor) {
        consentId = (await tireApi.consent(consentFor, "allow", context.controller.signal)).id;
        if (!current(context)) return;
      }
      const value = history
        ? await tireApi.samrRecallHistory(query, context.controller.signal)
        : await tireApi.samrRecallQuery(query, consentId ? { consent_id: consentId } : {}, context.controller.signal);
      if (!current(context)) return;
      if (query.operation === "search") setCatalog(value);
      else setResult(value);
      if (value.data_state === "consent_required" && value.query_id) setPending({ query, queryId: value.query_id });
      if (value.reason && !value.document) setError(value.reason);
    } catch (cause) { failed(cause, context); }
    finally { if (current(context)) setBusy(false); }
  }

  async function deny() {
    if (!pending || !sessionReady) return;
    const { query, queryId } = pending;
    const context = begin(true);
    if (query.operation === "search") setCatalog(null);
    else setResult(null);
    try {
      await tireApi.consent(queryId, "deny", context.controller.signal);
      if (current(context)) setError("已记录本次拒绝决定。");
    } catch (cause) { failed(cause, context); }
    finally { if (current(context)) setBusy(false); }
  }

  async function showEvidence(id: string) {
    if (!sessionReady) return;
    const context = begin(false);
    try {
      const value = await tireApi.samrRecallEvidence(id, context.controller.signal);
      if (current(context)) setEvidence(value);
    } catch (cause) { failed(cause, context); }
    finally { if (current(context)) setBusy(false); }
  }

  const document = catalog?.document?.operation === "search" ? catalog.document : null;
  const notice = result?.document?.operation === "notice" ? result.document.notice : null;
  const target = result ? samrTarget(result) : null;
  const searchQuery = catalog?.query.operation === "search" ? catalog.query : null;
  const canLoad = sessionReady && !busy && (history || access.canQuery(sourceId));
  const searchPage = (page: number) => searchQuery && void load({ ...searchQuery, page: String(page) });

  return <section className="recall-discovery" aria-labelledby="samr-recall-title" aria-busy={busy}>
    <h3 id="samr-recall-title">中国市场监管召回</h3>
    <p className="recall-help">官方汽车召回栏目含轮胎及相关汽车公告。批次、缺陷和措施保留原文，具体SKU及实物适用性待核对。</p>
    <div className="recall-modes" role="group" aria-label="中国召回查询方式">
      <button type="button" aria-pressed={!history} onClick={() => { clearResults(); setHistory(false); }}>在线核验</button>
      <button type="button" aria-pressed={history} onClick={() => { clearResults(); setHistory(true); }}>读取已保存历史</button>
    </div>
    <form className="review-form" onSubmit={event => { event.preventDefault(); void load({ operation: "search", keyword: keyword.trim(), page: "1" }); }}>
      <label>公告关键字<input maxLength={80} value={keyword} onChange={event => { clearResults(); setKeyword(event.target.value); }} /></label>
      <button type="submit" className="primary-button" disabled={!canLoad}>{history ? "读取中国召回检索历史" : "在线检索中国召回"}</button>
    </form>
    {busy ? <p role="status">正在读取中国召回证据…</p> : null}
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    {pending ? <section className="recall-mode-notice">
      <h4>是否允许本次读取对应历史？</h4>
      <p>{pending.query.operation === "search" ? `关键字 ${pending.query.keyword || "全部"} · 第 ${pending.query.page} 页` : pending.query.reference}</p>
      <div className="consent-actions">
        <button type="button" className="primary-button" disabled={busy} onClick={() => void load(pending.query, pending.queryId)}>仅本次允许</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void deny()}>拒绝</button>
      </div>
    </section> : null}
    {catalog ? <>
      <ResultStatus value={catalog} />
      {document ? <>
        <p>关键字 {document.keyword || "全部"} · 官方声明 {document.declared_total} 条 · 本页 {document.notices.length} 条 · 第 {document.page} / {Math.max(1, document.source_navigation_pages)} 页</p>
        <p className="recall-help">每页最多 {document.page_size} 条，原站导航最多 {document.source_navigation_page_limit} 页。</p>
        {document.notices.length === 0 ? <p>本页没有公告结果，具体召回适用性仍需核对。</p> : null}
        {document.notices.map(item => <article className="recall-product" key={item.article_id}>
          <h4>{item.title}</h4>
          <p>原显示发布日期 {item.publication_date_raw} · 适用性待核对</p>
          <button type="button" className="secondary-button" disabled={!canLoad} onClick={() => void load({ operation: "notice", reference: item.reference })}>{history ? "读取此公告历史" : "在线核验此公告"}</button>
          <a href={item.source_url} target="_blank" rel="noreferrer">打开官方公告</a>
        </article>)}
      </> : null}
      {searchQuery ? <div className="reparse-pages">
        <button type="button" className="text-button" disabled={!canLoad || Number(searchQuery.page) <= 1} onClick={() => searchPage(Number(searchQuery.page) - 1)}>上一页中国召回</button>
        <button type="button" className="text-button" disabled={!canLoad || !document || document.page >= document.source_navigation_pages} onClick={() => searchPage(Number(searchQuery.page) + 1)}>下一页中国召回</button>
      </div> : null}
      {catalog.provenance.map(item => <button type="button" key={item.snapshot_id} className="text-button" disabled={!sessionReady || busy} onClick={() => void showEvidence(item.snapshot_id)}>查看检索页原始证据</button>)}
    </> : null}
    {result ? <>
      <ResultStatus value={result} />
      {notice ? <article className="recall-product" aria-label="中国召回公告详情">
        <h4>{notice.title}</h4>
        <p>原显示发布日期 {notice.publication_date_raw} · 规范日期 {notice.published_date}</p>
        <p>DeployTime 原值 {notice.deployed_at_raw} · PubDate 原值 {notice.pub_date_raw}</p>
        <p className="recall-help">日期字段差异原因待来源说明。内容来源 {notice.content_source_raw || "未声明"} · 适用性待核对</p>
        <DataTree key={result.provenance[0]?.snapshot_id} label="官方公告正文纯文本" value={notice.text} />
        <DataTree label="原始元数据" value={notice.metadata} />
        <DataTree label="图片与附件来源引用 · 尚未获取" value={notice.assets} />
        {target && onAnalyze ? <button type="button" className="secondary-button" disabled={!sessionReady || busy} onClick={() => onAnalyze({ samr: target, label: notice.title, defaultQuestion: "整理所选历史中国召回公告原文与日期字段。" })}>分析此中国召回公告</button> : null}
        <button type="button" className="text-button" disabled={!sessionReady || busy} onClick={() => { cancel(); setHistoryArticle(notice.article_id); }}>读取公告版本与变化</button>
        <a href={notice.source_url} target="_blank" rel="noreferrer">重开官方公告原文</a>
      </article> : null}
      {result.provenance.map(item => <button type="button" key={item.snapshot_id} className="text-button" disabled={!sessionReady || busy} onClick={() => void showEvidence(item.snapshot_id)}>查看公告原始证据</button>)}
    </> : null}
    {(result ?? catalog)?.notices.map(text => <p className="recall-help" key={text}>{text}</p>)}
    <p className="recall-help">持续回退分别授权检索页与公告查询。保存后从下一次普通查询生效。</p>
    {sessionReady ? <>
      <QueryFallbackPolicy kind="samr_recall_search" sourceIds={[sourceId]} sessionReady={sessionReady} />
      <QueryFallbackPolicy kind="samr_recall_notice" sourceIds={[sourceId]} sessionReady={sessionReady} />
    </> : null}
    <SamrMonitoring sessionReady={sessionReady} onEvidence={id => void showEvidence(id)} />
    {historyArticle ? <SamrNoticeHistoryPanel key={historyArticle} articleId={historyArticle} sessionReady={sessionReady} onClose={() => setHistoryArticle(null)} onEvidence={id => void showEvidence(id)} onAnalyze={onAnalyze ? (reference, label) => onAnalyze({ references: [reference], label, defaultQuestion: "整理此历史版本中国召回公告原文与日期字段。" }) : undefined} /> : null}
    {evidence ? <section className="recall-evidence" aria-label="中国召回历史原件">
      <h4>历史原件 · {evidence.content_type}</h4>
      <p>系统观察 {evidence.observed_at} · Parser {evidence.parser_version}</p>
      <p className="recall-help">{evidence.attribution}</p>
      <DataTree key={`${evidence.id}:metadata`} label="原始SHA-256、来源与访问依据" value={{ raw_hash: evidence.raw_hash, source_url: evidence.source_url, access_basis: evidence.access_basis, parser_identity: evidence.parser_identity }} />
      <DataTree key={evidence.id} label="完整原件纯文本" value={evidence.body} />
      <button type="button" className="text-button" onClick={() => setEvidence(null)}>收起原件</button>
    </section> : null}
  </section>;
}
