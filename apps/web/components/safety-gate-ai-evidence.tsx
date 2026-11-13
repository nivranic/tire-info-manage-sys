"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { AIEvidence, SafetyGateAnalysisBoundary as Boundary } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { isSafetyGateEvidence, safetyGateAnalysisNotice, verifySafetyGateOriginal } from "./safety-gate-ai-values";

export function SafetyGateAnalysisBoundary({ boundary, pending = false }: { boundary?: Boundary; pending?: boolean }) {
  if (!boundary && !pending) return null;
  return <aside className="review-boundary" aria-label="Safety Gate 分析边界"><strong>仅告警事实 · 具体实物适用性尚未评估 · not_assessed</strong><p>{boundary?.notice || safetyGateAnalysisNotice}</p></aside>;
}

export function SafetyGateEvidenceMeta({ evidence }: { evidence: AIEvidence }) {
  if (!isSafetyGateEvidence(evidence)) return null;
  return <div className="recall-ai-meta"><p>{evidence.report_reference} · 告警 {evidence.alert_id} · {evidence.case_number}</p>
    <p>周报发布 {evidence.report_published_date} · 告警发布 {evidence.alert_published_date} · 适用性尚未评估</p>
    <p>{evidence.attribution}</p><details><summary>原件与许可出处</summary><pre>{JSON.stringify({ snapshot_id: evidence.snapshot_id, raw_hash: evidence.raw_hash, license_basis: evidence.license_basis }, null, 2)}</pre></details>
  </div>;
}

export function SafetyGateCitation({ evidence }: { evidence: AIEvidence }) {
  const auth = useWorkbenchAuth();
  const operation = useRef<AbortController | null>(null);
  const key = JSON.stringify([auth.ownerEpoch, evidence.snapshot_id, evidence.raw_hash, evidence.alert_id, evidence.case_number]);
  const [resolved, setResolved] = useState<{ key: string; xml: string; body: string } | null>(null);
  const [error, setError] = useState<{ key: string; text: string } | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  useEffect(() => () => { operation.current?.abort(); operation.current = null; }, [key]);

  async function resolve() {
    if (operation.current || auth.ownerSignal.aborted || !evidence.snapshot_id) return;
    const controller = new AbortController(); operation.current = controller;
    setBusyKey(key); setResolved(null); setError(null);
    const signal = AbortSignal.any([controller.signal, auth.ownerSignal]);
    try {
      const original = await tireApi.safetyGateEvidence(evidence.snapshot_id, signal);
      if (signal.aborted || operation.current !== controller) return;
      const xml = await verifySafetyGateOriginal(evidence, original);
      if (!signal.aborted && operation.current === controller) setResolved({ key, xml, body: original.body });
    } catch (cause) {
      if (!signal.aborted && operation.current === controller) setError({ key, text: cause instanceof Error ? cause.message : "原件核对未完成；冻结字段仍保留。" });
    } finally {
      if (operation.current === controller) { operation.current = null; setBusyKey(null); }
    }
  }

  if (!isSafetyGateEvidence(evidence)) return null;
  return <section className="ai-original-text" aria-label={`Safety Gate 原件引用 ${evidence.alert_id}`}>
    <button type="button" className="text-button" disabled={busyKey === key || auth.ownerSignal.aborted || !evidence.snapshot_id} onClick={() => void resolve()}>{busyKey === key ? "正在核对原件…" : "从周报原件核对这条告警"}</button>
    {resolved?.key === key ? <><p role="status">原件哈希与所选告警身份一致；不代表当前状态或实物适用性已确认。</p><pre>{resolved.xml}</pre><details><summary>完整周报 XML 原文</summary><pre>{resolved.body}</pre></details></> : null}
    {error?.key === key ? <p role="alert">{error.text}</p> : null}
  </section>;
}
