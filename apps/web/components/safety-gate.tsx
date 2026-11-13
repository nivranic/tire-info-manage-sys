"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { SafetyGateEvidence, SafetyGateQuery, SafetyGateReport, SafetyGateResult } from "@tire/domain-types";
import { DataTree } from "./reparse-review";
import { useSourceAccess } from "./source-status";

type Slot = "catalog" | "report";
type Pending = { query: SafetyGateQuery; slot: Slot; queryId: string };
const sourceId = "eu-safety-gate";
const failure = (cause: unknown) => cause instanceof Error ? cause.message : "Safety Gate操作未完成。";

export default function SafetyGatePanel({ sessionReady }: { sessionReady: boolean }) {
  const access = useSourceAccess();
  const generation = access.get(sourceId)?.management.access_generation;
  const [history, setHistory] = useState(false);
  const [catalog, setCatalog] = useState<SafetyGateResult | null>(null);
  const [result, setResult] = useState<SafetyGateResult | null>(null);
  const [selected, setSelected] = useState<SafetyGateReport | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [evidence, setEvidence] = useState<SafetyGateEvidence | null>(null);
  const [filter, setFilter] = useState("tyre");
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<{ controller: AbortController; generation?: number } | null>(null);

  function cancel() {
    active.current?.controller.abort();
    active.current = null;
    setPending(null);
    setEvidence(null);
    setBusy(false);
    setError("");
  }

  useEffect(() => () => { active.current?.controller.abort(); active.current = null; }, []);
  useEffect(() => {
    if (!sessionReady) {
      cancel();
      setCatalog(null);
      setResult(null);
      setSelected(null);
    }
  }, [sessionReady]);
  useEffect(() => {
    if (!history && active.current && active.current.generation !== undefined && active.current.generation !== generation) {
      cancel();
      setResult(null);
      setError("来源状态已变化，请重新核对来源后发起查询。");
    }
  }, [generation, history]);

  async function load(query: SafetyGateQuery, slot: Slot, consentFor?: string) {
    cancel();
    const context = { controller: new AbortController(), generation };
    active.current = context;
    const current = () => active.current === context && !context.controller.signal.aborted;
    setBusy(true);
    if (slot === "catalog") { setCatalog(null); setSelected(null); }
    setResult(null);
    setPage(0);
    try {
      if (!history && !await access.ensure(sourceId)) throw new Error("来源当前无法查询，请核对来源管理状态。");
      if (!current()) return;
      context.generation = access.get(sourceId)?.management.access_generation;
      let consentId: string | undefined;
      if (consentFor) {
        consentId = (await tireApi.consent(consentFor, "allow", context.controller.signal)).id;
        if (!current()) return;
      }
      const value = history
        ? await tireApi.safetyGateHistory(query, context.controller.signal)
        : await tireApi.safetyGateQuery(query, consentId ? { consent_id: consentId } : {}, context.controller.signal);
      if (!current()) return;
      if (slot === "catalog") {
        setCatalog(value);
        setSelected(value.document?.reports[0] ?? null);
      } else setResult(value);
      if (value.data_state === "consent_required" && value.query_id) setPending({ query, slot, queryId: value.query_id });
      if (value.reason && !value.document) setError(value.reason);
    } catch (cause) {
      if (current()) setError(failure(cause));
    } finally {
      if (current()) setBusy(false);
    }
  }

  async function deny() {
    if (!pending) return;
    const value = pending;
    cancel();
    const context = { controller: new AbortController(), generation };
    active.current = context;
    setBusy(true);
    try {
      await tireApi.consent(value.queryId, "deny", context.controller.signal);
      if (active.current === context && !context.controller.signal.aborted) setError("已记录本次拒绝决定。");
    } catch (cause) {
      if (active.current === context && !context.controller.signal.aborted) setError(failure(cause));
    } finally {
      if (active.current === context && !context.controller.signal.aborted) setBusy(false);
    }
  }

  async function showEvidence(id: string) {
    cancel();
    const context = { controller: new AbortController(), generation };
    active.current = context;
    setBusy(true);
    try {
      const value = await tireApi.safetyGateEvidence(id, context.controller.signal);
      if (active.current === context && !context.controller.signal.aborted) setEvidence(value);
    } catch (cause) {
      if (active.current === context && !context.controller.signal.aborted) setError(failure(cause));
    } finally {
      if (active.current === context && !context.controller.signal.aborted) setBusy(false);
    }
  }

  const reports = catalog?.document?.reports ?? [];
  const alerts = result?.document?.alerts ?? [];
  const term = filter.trim().toLowerCase();
  const filtered = alerts.filter(alert => !term || Object.values(alert.fields).some(value => value?.toLowerCase().includes(term)));
  const pages = Math.max(1, Math.ceil(filtered.length / 10));
  const shownPage = Math.min(page, pages - 1);
  const provenance = result?.provenance[0] ?? catalog?.provenance[0];
  const querySelected = () => selected && void load({ operation: "report", report_id: selected.report_id, reference: selected.reference }, "report");

  return <section className="safety-gate-panel recall-discovery" aria-labelledby="safety-gate-title">
    <h3 id="safety-gate-title">Safety Gate 欧盟周报</h3>
    <p className="recall-help">先读取官方英文周报索引，再选择周报。告警身份、原始字段及适用性分别保留。</p>
    <div className="recall-modes" role="group" aria-label="Safety Gate查询方式">
      <button type="button" aria-pressed={!history} onClick={() => { cancel(); setHistory(false); setCatalog(null); setResult(null); setSelected(null); }}>在线核验</button>
      <button type="button" aria-pressed={history} onClick={() => { cancel(); setHistory(true); setCatalog(null); setResult(null); setSelected(null); }}>读取已保存历史</button>
    </div>
    <button type="button" className="secondary-button" disabled={!sessionReady || busy || !history && !access.canQuery(sourceId)} onClick={() => void load({ operation: "reports" }, "catalog")}>{history ? "读取索引历史" : "在线读取周报索引"}</button>
    {catalog?.document ? <p role="status">索引状态 {catalog.data_state.toUpperCase()} · 共 {reports.length} 份周报 · 核验时间 {catalog.verified_at ?? "未知"}</p> : null}
    {reports.length ? <form className="review-form" onSubmit={event => { event.preventDefault(); querySelected(); }}>
      <label>官方周报<select value={selected?.report_id ?? ""} onChange={event => { cancel(); setSelected(reports.find(report => report.report_id === event.target.value) ?? null); setResult(null); }}>
        {reports.map(report => <option key={report.report_id} value={report.report_id}>{report.reference} · {report.published_date}</option>)}
      </select></label>
      <button type="submit" className="primary-button" disabled={!sessionReady || busy || !selected || !history && !access.canQuery(sourceId)}>{history ? "读取所选周报历史" : "在线核验所选周报"}</button>
    </form> : null}
    {busy ? <p role="status">正在读取Safety Gate证据…</p> : null}
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    {pending ? <section className="recall-mode-notice"><h4>是否允许本次读取对应历史？</h4><p>{pending.query.operation === "report" ? pending.query.reference : "官方周报索引"} · 此次查询需单次授权。</p><div className="consent-actions">
      <button type="button" className="primary-button" disabled={busy} onClick={() => void load(pending.query, pending.slot, pending.queryId)}>仅本次允许</button>
      <button type="button" className="secondary-button" disabled={busy} onClick={() => void deny()}>拒绝</button>
    </div></section> : null}
    {result?.document?.report ? <>
      <h4>{result.document.report.reference} · {result.data_state.toUpperCase()}</h4>
      <p>周报发布日期 {result.document.report.published_date} · 本周报共 {alerts.length} 条告警 · 最近核验 {result.verified_at ?? "未知"}</p>
      {result.document.report.addendum_raw ? <DataTree label="周报补充声明原文" value={result.document.report.addendum_raw} /> : null}
      <label className="field-caption">在当前周报原文中筛选<input value={filter} maxLength={120} onChange={event => { setFilter(event.target.value); setPage(0); }} /></label>
      <p className="recall-help">当前匹配 {filtered.length} 条，显示第 {shownPage + 1} / {pages} 页。覆盖所选周报中的英文声明，具体SKU及实物适用性待核对。</p>
      {filtered.slice(shownPage * 10, (shownPage + 1) * 10).map(alert => <article className="recall-product" key={alert.alert_id}>
        <h4>{alert.case_number} · {alert.fields.brand ?? "品牌未知"}</h4>
        <p>{alert.fields.product ?? "产品类型未知"} · {alert.fields.name ?? "型号未知"}</p>
        <p>告警发布日期 {alert.published_date} · 适用性待核对</p>
        <DataTree label="官方风险原文" value={alert.fields.danger} />
        <DataTree label="官方措施原文" value={alert.fields.measures} />
        <DataTree label="完整官方字段与图片来源地址" value={{ ...alert.fields, pictures: alert.pictures }} />
        <a href={alert.source_url} target="_blank" rel="noreferrer">打开官方告警 {alert.case_number}</a>
      </article>)}
      {pages > 1 ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!shownPage} onClick={() => setPage(shownPage - 1)}>上一页告警</button><button type="button" className="text-button" disabled={shownPage + 1 >= pages} onClick={() => setPage(shownPage + 1)}>下一页告警</button></div> : null}
    </> : null}
    {provenance ? <><p className="recall-help">{provenance.attribution}</p><button type="button" className="text-button" disabled={busy} onClick={() => void showEvidence(provenance.snapshot_id)}>{result?.document ? "查看所选周报原始证据" : "查看索引原始证据"}</button></> : null}
    {evidence ? <section className="recall-evidence"><h4>历史XML原件</h4><p>观察时间 {evidence.observed_at} · Parser {evidence.parser_version}</p><DataTree label="原始SHA-256与许可出处" value={{ raw_hash: evidence.raw_hash, source_url: evidence.source_url, license_basis: evidence.license_basis }} /><DataTree label="完整官方XML纯文本" value={evidence.body} /><button type="button" className="text-button" onClick={() => setEvidence(null)}>收起原件</button></section> : null}
  </section>;
}
