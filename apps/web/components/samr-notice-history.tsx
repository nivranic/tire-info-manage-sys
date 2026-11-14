"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { SamrNoticeHistory } from "@tire/domain-types";
import { DataTree } from "./reparse-review";

export default function SamrNoticeHistoryPanel({ articleId, sessionReady, onClose, onEvidence }: {
  articleId: string; sessionReady: boolean; onClose: () => void; onEvidence: (id: string) => void;
}) {
  const [value, setValue] = useState<SamrNoticeHistory | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);

  async function load(offset = 0, throughSequence?: number) {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setValue(null);
    setError("");
    setBusy(true);
    try {
      const result = await tireApi.samrNoticeHistory(articleId, { offset, through_sequence: throughSequence }, controller.signal);
      if (active.current === controller && !controller.signal.aborted) setValue(result);
    } catch (cause) {
      if (active.current === controller && !controller.signal.aborted) setError(cause instanceof Error ? cause.message : "公告历史读取未完成。");
    } finally {
      if (active.current === controller && !controller.signal.aborted) setBusy(false);
    }
  }

  useEffect(() => {
    setValue(null);
    setError("");
    setBusy(false);
    if (sessionReady) void load();
    return () => { active.current?.abort(); active.current = null; };
  }, [articleId, sessionReady]);

  return <section className="recall-evidence" aria-label="中国召回公告版本与变化" aria-busy={busy}>
    <h4>公告版本与变化 · 已保存历史</h4>
    {busy ? <p role="status">正在读取公告历史…</p> : null}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {value ? <>
      <p>{value.head.revision.notice.title} · 共 {value.total} 次观察，固定至第 {value.through_sequence} 次</p>
      <p className="recall-help">当前范围的最近观察 {value.head.observed_at} · 内容版本 {value.head.revision.revision} · 适用性待核对</p>
      {value.notices.map(text => <p className="recall-help" key={text}>{text}</p>)}
      {value.observations.map(row => <article className="recall-product" key={row.id}>
        <h5>第 {row.sequence} 次观察 · 内容版本 {row.revision.revision}</h5>
        <p>系统观察 {row.observed_at} · 原发布日期 {row.revision.notice.publication_date_raw}</p>
        <p>DeployTime {row.revision.notice.deployed_at_raw} · PubDate {row.revision.notice.pub_date_raw}</p>
        <p>{row.event?.kind === "first_observed" ? "系统首次观察" : row.event ? "公告内容发生变化" : "内容版本沿用既有观察"}</p>
        {row.event && Object.keys(row.event.changes).length ? <DataTree label="变化前后字段" value={row.event.changes} /> : null}
        <DataTree label="此观察的公告正文纯文本" value={row.revision.notice.text} />
        <DataTree label="内容摘要、版本和原件绑定" value={{ content_hash: row.revision.content_hash, revision_id: row.revision.id, first_snapshot_id: row.revision.first_snapshot_id, snapshot_id: row.snapshot_id, verification_id: row.verification_id }} />
        <button type="button" className="text-button" disabled={!sessionReady} onClick={() => onEvidence(row.snapshot_id)}>查看此观察原件</button>
        {row.event?.previous_snapshot_id ? <button type="button" className="text-button" disabled={!sessionReady} onClick={() => onEvidence(row.event!.previous_snapshot_id!)}>查看变化前原件</button> : null}
      </article>)}
      {value.total > value.limit ? <div className="reparse-pages">
        <button type="button" className="text-button" disabled={!sessionReady || busy || value.offset === 0} onClick={() => void load(Math.max(0, value.offset - value.limit), value.through_sequence)}>上一页公告观察</button>
        <button type="button" className="text-button" disabled={!sessionReady || busy || value.offset + value.limit >= value.total} onClick={() => void load(value.offset + value.limit, value.through_sequence)}>下一页公告观察</button>
      </div> : null}
    </> : null}
    <button type="button" className="text-button" onClick={onClose}>收起公告历史</button>
  </section>;
}
