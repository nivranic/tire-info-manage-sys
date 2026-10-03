"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IdentityContractBadge } from "./identity-contract";
import { tireApi } from "@tire/api-client";
import type { IdentityCandidates } from "@tire/domain-types";
import IdentityReviewDialog, { identityLabel } from "./identity-review";

export default function IdentityDirectory({ sessionReady }: { sessionReady: boolean }) {
  const toggle = useRef<HTMLButtonElement>(null);
  const [opened, setOpened] = useState(false);
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<IdentityCandidates | null>(null);
  const [error, setError] = useState("");
  const restoreFocus = useCallback(() => {
    (document.getElementById(`identity-option-${selected}`) || toggle.current)?.focus({ preventScroll: true });
  }, [selected]);
  useEffect(() => {
    if (!opened || !sessionReady) return;
    const controller = new AbortController(); setData(null); setError("");
    void tireApi.identityCandidates(query, offset, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "历史身份读取失败"); });
    return () => controller.abort();
  }, [opened, sessionReady, query, offset, refresh]);
  return <section className="quarantine-panel identity-directory" aria-label="历史精确版本身份">
    <div className="panel-title"><span>精确版本身份</span><button ref={toggle} type="button" className="secondary-button" disabled={!sessionReady} onClick={() => setOpened(value => !value)}>{opened ? "收起身份目录" : "查找历史版本"}</button></div>
    <p className="quality-intro">LOCAL SNAPSHOT · 从已有证据查找精确版本，核对身份更正、合并与撤回。这里的记录不代表当前在线参数。</p>
    {opened ? <>
      <form className="quarantine-filter" onSubmit={event => { event.preventDefault(); setQuery(search.trim()); setOffset(0); setRefresh(value => value + 1); }}><label><span>按品牌、型号或产品代码查找身份</span><input maxLength={120} value={search} onChange={event => setSearch(event.target.value)} /></label><button type="submit" className="secondary-button">查找已存身份</button></form>
      {error ? <p className="inline-error" role="alert">{error}<button type="button" className="text-button" onClick={() => setRefresh(value => value + 1)}>重新读取身份目录</button></p> : !data ? <p role="status">正在读取历史身份…</p> : <>
        <div className="identity-directory-list">{data.items.map(item => <button id={`identity-option-${item.id}`} type="button" className="report-list-item" key={item.id} onClick={() => setSelected(item.id)}><strong>{String(item.identity.brand)} {String(item.identity.model)} · {String(item.identity.manufacturer_product_code || "代码未知")}</strong><span>{String(item.identity.size)} · {String(item.identity.region)} · OE {String(item.identity.oe_mark ?? "未知")}</span><IdentityContractBadge contract={item.identity_contract} /><small>{item.identity_resolution ? identityLabel(item.identity_resolution.state) : "独立版本"} · <code>{item.id}</code></small></button>)}</div>
        {!data.items.length ? <p className="quality-empty">没有匹配的已采纳版本。</p> : null}
        <div className="reparse-pages"><button type="button" className="text-button" disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页身份</button><span>共 {data.total} 个 · 第 {offset / 20 + 1} 页</span><button type="button" className="text-button" disabled={offset + 20 >= data.total} onClick={() => setOffset(value => value + 20)}>下一页身份</button></div>
      </>}
    </> : null}
    {selected ? <IdentityReviewDialog key={selected} variantId={selected} onClose={() => setSelected("")} onSaved={() => setRefresh(value => value + 1)} restoreFocus={restoreFocus} /> : null}
  </section>;
}
