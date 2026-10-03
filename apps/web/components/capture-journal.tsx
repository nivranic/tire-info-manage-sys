"use client";

import { useEffect, useRef, useState } from "react";
import type { RawCaptureEvidence, RawCaptureRecord, Source } from "@tire/domain-types";
import { tireApi } from "@tire/api-client";
import { Icon } from "./icons";
import ReparseReviewDialog, { queryScope, targetLabel } from "./reparse-review";

const time = (value: string) => new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
const errorText = (value: unknown) => value instanceof Error ? value.message : "读取未完成，请重试。";
const queryLabel = (row: RawCaptureRecord) => row.processing_unconfirmed ? "处理结果未确认"
  : row.query_state === "live" ? "已完成在线核验" : "在线核验未完成";

export default function CaptureJournal({ sources, sessionReady }: { sources: Source[]; sessionReady: boolean }) {
  const [opened, setOpened] = useState(false);
  const [pendingOnly, setPendingOnly] = useState(false);
  const [revision, setRevision] = useState(0);
  const [rows, setRows] = useState<RawCaptureRecord[] | null>(null);
  const [listError, setListError] = useState("");
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<RawCaptureEvidence | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailRevision, setDetailRevision] = useState(0);
  const [reparseCapture, setReparseCapture] = useState<RawCaptureRecord | null>(null);
  const listRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);
  const panel = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const name = (id: string) => sources.find(source => source.id === id)?.name || (id.startsWith("xiaomi") ? "小米汽车官方配置" : id);

  useEffect(() => {
    if (!opened || !sessionReady) return;
    const controller = new AbortController();
    listRequest.current = controller;
    void tireApi.captures(pendingOnly, controller.signal).then(result => {
      if (!controller.signal.aborted) setRows(result.items);
    }).catch(error => { if (!controller.signal.aborted) setListError(errorText(error)); });
    return () => controller.abort();
  }, [opened, pendingOnly, revision, sessionReady]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    detailRequest.current = controller;
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    void tireApi.captureEvidence(selected, controller.signal).then(result => {
      if (!controller.signal.aborted) setDetail(result);
    }).catch(error => { if (!controller.signal.aborted) setDetailError(errorText(error)); });
    return () => controller.abort();
  }, [selected, detailRevision]);

  function closeDetail(restoreFocus = false) {
    detailRequest.current?.abort(); setSelected(""); setDetail(null); setDetailError("");
    if (restoreFocus) trigger.current?.focus();
  }
  function reload(pending = pendingOnly) {
    listRequest.current?.abort(); closeDetail(); setRows(null); setListError("");
    setPendingOnly(pending); setRevision(value => value + 1);
  }

  return <section className="quarantine-panel" aria-labelledby="capture-journal-title">
    <div className="panel-title"><span id="capture-journal-title">原文接收日志</span><button type="button" className="text-button" disabled={!sessionReady} aria-expanded={opened} aria-controls="capture-journal-list" onClick={() => {
      listRequest.current?.abort(); closeDetail(); setRows(null); setListError(""); setOpened(value => !value);
    }}>{opened ? "收起日志" : "查看接收日志"}</button></div>
    <p className="quality-intro">来源原文先保存，再进行结构与质量核验。若处理意外中断，仍可在这里核对已收到的内容；收到原文不代表解析结果已被采纳。</p>
    {opened ? <div id="capture-journal-list">
      <div className="quarantine-filter"><label><span>处理状态</span><select value={pendingOnly ? "pending" : "all"} onChange={event => reload(event.target.value === "pending")}><option value="all">全部接收记录</option><option value="pending">仅处理结果未确认</option></select></label><button type="button" className="secondary-button" onClick={() => reload()}><Icon name="refresh" size={15} />刷新接收记录</button></div>
      <p className="quality-intro">“处理结果未确认”可能表示仍在处理，也可能是处理已中断。此日志只提供接收证据，且不会自动重新解析。</p>
      {listError ? <div className="inline-error" role="alert">{listError}<button type="button" className="text-button" onClick={() => reload()}>重试</button></div> : rows === null ? <div className="run-loading" role="status"><span className="spinner" />正在读取接收记录…</div> : rows.length ? <>
        <p className="quarantine-list-count">显示最近 {rows.length} 条（最多 50 条）；早于接收日志启用时间的查询不会补造记录。</p>
        <div className="quarantine-list">{rows.map(row => <article className={`quarantine-item${selected === row.id ? " selected" : ""}`} key={row.id}>
          <div className="quality-item-heading"><h3>{name(row.source_id)}</h3><time dateTime={row.observed_at}>{time(row.observed_at)}</time></div>
          <p className="quarantine-comparison">{targetLabel(row.target_kind, row.query)}{row.target_kind === "recall" ? "" : "原文"} · {row.byte_count.toLocaleString("zh-CN")} 字节</p>
          {row.query && queryScope(row.query) ? <p>{queryScope(row.query)}</p> : null}
          <p><span className={`tag ${row.processing_unconfirmed ? "warning" : "quiet"}`}>{queryLabel(row)}</span></p>
          <div className="variant-actions"><button type="button" className="secondary-button" aria-expanded={selected === row.id} aria-controls="capture-evidence" onClick={event => {
            if (selected === row.id) { closeDetail(true); return; }
            closeDetail(); trigger.current = event.currentTarget; setSelected(row.id); setDetailRevision(value => value + 1);
          }}><Icon name="file" size={15} />{selected === row.id ? "关闭接收原文" : "核对接收原文"}</button><button type="button" className="secondary-button" onClick={() => setReparseCapture(row)}>历史重解析与审阅</button></div>
        </article>)}</div>
      </> : <p className="quality-empty">{pendingOnly ? "暂无处理结果未确认的接收记录。" : "暂无原文接收记录。"}</p>}
      {selected ? <section id="capture-evidence" className="quarantine-evidence" aria-labelledby="capture-evidence-title" ref={panel} tabIndex={-1} onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); closeDetail(true); } }}>
        <div className="panel-title"><span id="capture-evidence-title">已接收的原始内容</span><button type="button" className="icon-button" aria-label="关闭接收原文" onClick={() => closeDetail(true)}><Icon name="close" size={18} /></button></div>
        <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 原文接收记录</strong><span>此处只证明原文已收到，不据此判断数据有效或召回适用性，也不会加入比较或离线回退。</span></div>
        {detailError ? <div className="inline-error" role="alert">{detailError}<button type="button" className="text-button" onClick={() => { setDetailError(""); setDetailRevision(value => value + 1); }}>重试读取</button></div> : detail?.id === selected ? <div className="quarantine-detail-content">
          <dl className="quality-detail-meta"><div><dt>来源</dt><dd>{name(detail.source_id)}</dd></div><div><dt>原文接收时间</dt><dd>{time(detail.observed_at)}</dd></div><div><dt>处理情况</dt><dd>{queryLabel(detail)}</dd></div><div><dt>来源地址</dt><dd>{detail.source_url}</dd></div></dl>
          <details className="quality-technical"><summary>查看记录校验信息</summary><dl className="quality-detail-meta"><div><dt>解析器版本</dt><dd>{detail.parser_version}</dd></div><div><dt>SHA-256</dt><dd className="mono">{detail.raw_hash}</dd></div><div><dt>原文大小</dt><dd>{detail.byte_count.toLocaleString("zh-CN")} 字节</dd></div></dl></details>
          <details className="raw-evidence"><summary>展开接收原文<span className="mono">TEXT</span></summary><p>仅作纯文本核对，不执行网页脚本或指令。内容类型：{detail.content_type}</p><pre>{detail.body}</pre></details>
        </div> : <div className="run-loading" role="status"><span className="spinner" />正在读取接收原文…</div>}
      </section> : null}
    </div> : null}
    {reparseCapture ? <ReparseReviewDialog key={reparseCapture.id} capture={reparseCapture} sourceName={name(reparseCapture.source_id)} onClose={() => setReparseCapture(null)} /> : null}
  </section>;
}
