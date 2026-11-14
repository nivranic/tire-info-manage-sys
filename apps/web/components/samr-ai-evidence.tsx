"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { AIEvidence, SamrRecallAnalysisBoundary as Boundary } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { isSamrEvidence, samrAnalysisNotice, verifySamrOriginal } from "./samr-ai-values";

export function SamrAnalysisBoundary({ boundary, pending = false }: { boundary?: Boundary; pending?: boolean }) {
  if (!boundary && !pending) return null;
  return <aside className="review-boundary" aria-label="中国召回分析边界"><strong>中国召回公告事实 · 实物适用性待核对 · not_assessed</strong><p>{boundary?.notice || samrAnalysisNotice}</p></aside>;
}

export function SamrEvidenceMeta({ evidence }: { evidence: AIEvidence }) {
  if (!isSamrEvidence(evidence)) return null;
  const values = evidence.notice_values;
  return <div className="recall-ai-meta"><p>原生文章 {evidence.article_id}</p>
    <p>原显示发布日期 {values?.publication_date_raw} · 规范发布日期 {values?.published_date}</p>
    <p>DeployTime {values?.deployed_at_raw} · PubDate {values?.pub_date_raw}</p>
    <p>{evidence.attribution}</p><details><summary>公告版本与访问依据</summary><pre>{JSON.stringify({ snapshot_id: evidence.snapshot_id,
      raw_hash: evidence.raw_hash, document_hash: evidence.document_hash, content_hash: evidence.content_hash,
      verification_id: evidence.verification_id, verification_query_id: evidence.verification_query_id,
      parser_identity: evidence.parser_identity, access_basis: evidence.access_basis }, null, 2)}</pre></details>
  </div>;
}

export function SamrCitation({ evidence }: { evidence: AIEvidence }) {
  const auth = useWorkbenchAuth();
  const operation = useRef<AbortController | null>(null);
  const key = JSON.stringify([auth.ownerEpoch, evidence.snapshot_id, evidence.raw_hash, evidence.article_id, evidence.reference, evidence.source_url]);
  const [resolved, setResolved] = useState<{ key: string; body: string } | null>(null);
  const [error, setError] = useState<{ key: string; text: string } | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  useEffect(() => () => { operation.current?.abort(); operation.current = null; }, [key]);

  async function resolve() {
    if (operation.current || auth.ownerSignal.aborted || !evidence.snapshot_id) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusyKey(key); setResolved(null); setError(null);
    const signal = AbortSignal.any([controller.signal, auth.ownerSignal]);
    try {
      const original = await tireApi.samrRecallEvidence(evidence.snapshot_id, signal);
      if (signal.aborted || operation.current !== controller) return;
      const body = await verifySamrOriginal(evidence, original);
      if (!signal.aborted && operation.current === controller) setResolved({ key, body });
    } catch (cause) {
      if (!signal.aborted && operation.current === controller) setError({ key, text: cause instanceof Error ? cause.message : "中国召回原件核对未完成。" });
    } finally {
      if (operation.current === controller) { operation.current = null; setBusyKey(null); }
    }
  }

  if (!isSamrEvidence(evidence)) return null;
  return <section className="ai-original-text" aria-label={`中国召回原件引用 ${evidence.article_id}`}>
    <button type="button" className="text-button" disabled={busyKey === key || auth.ownerSignal.aborted || !evidence.snapshot_id} onClick={() => void resolve()}>{busyKey === key ? "正在核对中国公告原件…" : "核对所选中国公告原件"}</button>
    {resolved?.key === key ? <><p role="status">原件 SHA-256、快照与所选公告身份一致。</p><pre>{resolved.body}</pre></> : null}
    {error?.key === key ? <p role="alert">{error.text}</p> : null}
  </section>;
}
