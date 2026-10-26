"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, apiKeyTime, tireApi } from "@tire/api-client";
import type { ActiveApiKeys, ApiKeyHistory, ApiKeyOperation, ApiKeyRecord, ApiKeyScope } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import "./api-keys.css";

const pointerName = "tire-api-key-pending@1";
const labels: Record<ApiKeyScope, string> = { "sources:read": "读取来源目录", "webhooks:read": "读取本人 Webhook 投递引用", "facts:read": "获准轮胎事实读取权限" };
const stamp = (v: string) => new Date(v).toLocaleString("zh-CN");
const message = (cause: unknown) => cause instanceof ApiError ? ({
  api_key_limit: "当前有效密钥已达上限，请先撤销不用的密钥。",
  api_key_login_required: "请重新核对当前登录账户。",
  api_key_owner_changed: "账户已变化，请重新核对当前登录账户。",
  api_key_active_limit_invalid: "有效密钥数量异常，本次未展示不完整列表，请联系管理员核查。",
  api_key_history_cursor_expired: "本次历史读取窗口已到期，请从最新记录重新读取。",
} as Record<string, string>)[cause.code || ""] || "请求未完成，请核对当前账户及输入。" : "连接或响应未确认，请先核对操作结果。";

export default function ApiKeyCenter() {
  const auth = useWorkbenchAuth();
  return <section className="api-key-panel" aria-label="外部 API 凭据">
    <h3>外部 API 凭据</h3>
    <p>按权限提供来源目录和本人 Webhook 投递引用。密钥等同所授予的读取权限，请仅交给可信应用。</p>
    {auth.ready && auth.state.authenticated ? <PrivateKeys key={auth.ownerEpoch} epoch={auth.ownerEpoch} /> : <p>登录并确认当前账户后可管理本人密钥。</p>}
  </section>;
}

function PrivateKeys({ epoch }: { epoch: number }) {
  const auth = useWorkbenchAuth();
  const [revision, setRevision] = useState(0);
  const [name, setName] = useState(""), [days, setDays] = useState(30), [scopes, setScopes] = useState<ApiKeyScope[]>(["sources:read"]), [consent, setConsent] = useState(false);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [pending, setPending] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ApiKeyOperation | null>(null), [secret, setSecret] = useState<string | null>(null);
  const write = useRef<AbortController | null>(null), pendingRef = useRef<string | null>(null);
  const current = () => auth.isCurrentOwner(epoch);
  const locked = busy || pending !== null;
  function remember(key: string | null) {
    pendingRef.current = key; setPending(key);
    try {
      // Recovery metadata only. Never persist the API token or response object.
      if (key) sessionStorage.setItem(pointerName, JSON.stringify({ actor: auth.state.user?.id, key }));
      else {
        const raw = sessionStorage.getItem(pointerName), value: unknown = raw ? JSON.parse(raw) : null;
        if (value && typeof value === "object" && "actor" in value && value.actor === auth.state.user?.id) sessionStorage.removeItem(pointerName);
      }
    } catch { /* The on-screen operation UUID remains usable while mounted. */ }
  }
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(pointerName), value: unknown = raw ? JSON.parse(raw) : null;
      if (value && typeof value === "object" && "actor" in value && value.actor === auth.state.user?.id && "key" in value
        && typeof value.key === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value.key)) {
        pendingRef.current = value.key; setPending(value.key);
      }
    } catch { /* Corrupt recovery metadata grants no authority. */ }
    return () => { write.current?.abort(); };
  }, [auth.state.user?.id]);
  function accept(v: ApiKeyOperation, key: string) {
    if (!current() || pendingRef.current !== key) return;
    setSecret(v.token); setReceipt({ ...v, token: null }); remember(null); setRevision(n => n + 1);
  }
  async function mutate(action: "create" | "revoke", id?: string) {
    if (!current() || pendingRef.current || write.current) return;
    const key = crypto.randomUUID(), controller = new AbortController(); write.current = controller;
    remember(key); setBusy(true); setError(""); setSecret(null); setReceipt(null);
    try {
      const v = action === "create" ? await tireApi.createApiKey({ name, scopes: [...scopes].sort(), expires_in_days: days, acknowledged: true }, key, controller.signal)
        : await tireApi.revokeApiKey(id!, key, controller.signal);
      accept(v, key); if (current() && action === "create") { setName(""); setConsent(false); }
    } catch (cause) {
      if (!current() || controller.signal.aborted) return;
      setError(message(cause));
      if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408 && pendingRef.current === key) remember(null);
    } finally { if (current()) setBusy(false); if (write.current === controller) write.current = null; }
  }
  async function recover() {
    const key = pendingRef.current; if (!key || !current() || write.current) return;
    const controller = new AbortController(); write.current = controller; setBusy(true); setError("");
    try { accept(await tireApi.apiKeyOperation(key, controller.signal), key); }
    catch (cause) { if (current() && !controller.signal.aborted) setError(cause instanceof ApiError && cause.status === 404 ? "暂未观察到该操作结果，请稍后再核对。不会自动重新创建。" : message(cause)); }
    finally { if (current()) setBusy(false); if (write.current === controller) write.current = null; }
  }
  return <>
    {error ? <p role="alert">{error}</p> : null}
    {pending ? <div className="api-key-result" role="status"><p>操作结果待确认。操作编号：<code>{pending}</code></p><button className="secondary-button" disabled={busy} onClick={() => void recover()}>核对未确认操作</button></div> : null}
    {receipt ? <div className="api-key-result" role="status"><p>{receipt.action === "revoke" ? "密钥已撤销。" : "密钥已创建。"} {receipt.key.name}</p>
      {receipt.action === "create" && receipt.replayed && !secret ? <p>首次密钥未保留，无法再次读取。请撤销这把密钥后重新创建。</p> : null}
    </div> : null}
    {secret ? <div className="api-key-result"><label className="api-key-field">仅本次显示的密钥<textarea aria-label="仅本次显示的密钥" readOnly value={secret} autoComplete="off" spellCheck={false} /></label>
      <p>请妥善保存。关闭显示、刷新页面或重新确认账户后，无法再次读取。</p><button className="secondary-button" onClick={() => setSecret(null)}>关闭密钥显示</button></div> : null}
    <form onSubmit={event => { event.preventDefault(); if (consent && scopes.length) void mutate("create"); }}>
      <fieldset disabled={locked} className="api-key-fields"><legend>创建读取密钥</legend>
        <label className="api-key-field">密钥名称<input value={name} onChange={e => { setName([...e.target.value].slice(0, 80).join("")); setConsent(false); }} maxLength={160} required autoComplete="off" /></label>
        <label className="api-key-field">有效期<select value={days} onChange={e => { setDays(Number(e.target.value)); setConsent(false); }}><option value={7}>7天</option><option value={30}>30天</option><option value={90}>90天</option></select></label>
        {(["sources:read", "webhooks:read"] as ApiKeyScope[]).map(scope => <label className="api-key-check" key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={e => { setScopes(v => e.target.checked ? [...v, scope].sort() : v.filter(s => s !== scope)); setConsent(false); }} />{labels[scope]}</label>)}
        <label className="api-key-check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />允许持有密钥的应用在有效期内读取以上所选内容。</label>
        <button className="secondary-button" disabled={locked || !consent || !name.trim() || !scopes.length} type="submit">创建密钥</button>
      </fieldset>
    </form>
    <KeyInventory key={revision} epoch={epoch} locked={locked} onRevoke={id => void mutate("revoke", id)} onRefresh={() => setRevision(n => n + 1)} />
  </>;
}

function KeyInventory({ epoch, locked, onRevoke, onRefresh }: { epoch: number; locked: boolean; onRevoke: (id: string) => void; onRefresh: () => void }) {
  const auth = useWorkbenchAuth(), owner = auth.state.user!.id;
  const [active, setActive] = useState<ActiveApiKeys | null>(null), [history, setHistory] = useState<ApiKeyHistory | null>(null);
  const [activeError, setActiveError] = useState(""), [historyError, setHistoryError] = useState("");
  const [activeLoading, setActiveLoading] = useState(true), [historyLoading, setHistoryLoading] = useState(true);
  const [consent, setConsent] = useState<string | null>(null), [page, setPage] = useState(1);
  const historyRequest = useRef<AbortController | null>(null);
  const current = (controller: AbortController) => auth.isCurrentOwner(epoch) && !controller.signal.aborted;
  function failure(cause: unknown) {
    if (cause instanceof ApiError && ["api_key_login_required", "api_key_owner_changed"].includes(cause.code || "")) {
      // Invalidate both private lists before the account is revalidated.
      window.dispatchEvent(new Event("tire-session-unavailable"));
    }
    return message(cause);
  }
  async function readHistory(previous: ApiKeyHistory | null, nextPage: number) {
    if (!auth.isCurrentOwner(epoch) || (previous && (!previous.next_cursor || historyRequest.current))) return;
    historyRequest.current?.abort();
    const controller = new AbortController(); historyRequest.current = controller;
    setHistoryLoading(true); setHistoryError("");
    try {
      const result = await tireApi.apiKeyHistory(owner, { limit: 20, ...(previous?.next_cursor ? { cursor: previous.next_cursor } : {}), signal: controller.signal });
      if (!current(controller) || historyRequest.current !== controller) return;
      const last = previous?.items.at(-1), first = result.items[0];
      if (previous && (result.window_started_at !== previous.window_started_at || apiKeyTime(result.read_at) < apiKeyTime(previous.read_at)
        || result.items.some(item => previous.items.some(old => old.id === item.id))
        || (last && first && (apiKeyTime(first.created_at) > apiKeyTime(last.created_at)
          || (apiKeyTime(first.created_at) === apiKeyTime(last.created_at) && first.id >= last.id))))) throw new Error("history window changed");
      setHistory(result); setPage(nextPage);
    } catch (cause) { if (current(controller) && historyRequest.current === controller) setHistoryError(failure(cause)); }
    finally {
      if (current(controller) && historyRequest.current === controller) setHistoryLoading(false);
      if (historyRequest.current === controller) historyRequest.current = null;
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    void tireApi.activeApiKeys(owner, controller.signal)
      .then(result => { if (current(controller)) setActive(result); })
      .catch(cause => { if (current(controller)) setActiveError(failure(cause)); })
      .finally(() => { if (current(controller)) setActiveLoading(false); });
    void readHistory(null, 1);
    return () => { controller.abort(); historyRequest.current?.abort(); };
    // The parent remounts on explicit refresh/write; an owner epoch also remounts it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epoch, owner]);
  const stateLabel = (item: ApiKeyRecord) => item.revoked_at ? "已撤销" : history && apiKeyTime(item.expires_at) <= apiKeyTime(history.read_at) ? "已到期" : "读取时有效";
  return <div className="api-key-inventory">
    <section className="api-key-list api-key-active" aria-label="全部有效密钥"><h4>本人全部有效密钥</h4>
      <button className="text-button" disabled={locked} onClick={onRefresh}>刷新密钥列表</button>
      <p>这里展示当前账户全部有效密钥，最多16把。撤销后，对应应用将失去访问权限。</p>
      {activeError ? <p role="alert">{activeError}</p> : null}
      {activeLoading ? <p role="status">正在读取密钥…</p> : active ? <>
        <p>读取时间：{stamp(active.read_at)}</p>
        {!active.items.length ? <p>暂无有效密钥。</p> : active.items.map(item => <article className="api-key-row" key={item.id}>
          <strong>{item.name}</strong><p>{item.scopes.map(s => labels[s]).join(" · ")}<br />有效至 {stamp(item.expires_at)} · 读取时有效</p>
          <label className="api-key-check"><input type="checkbox" disabled={locked} checked={consent === item.id} onChange={e => setConsent(e.target.checked ? item.id : null)} />确认撤销“{item.name}”的访问权限</label>
          <button className="secondary-button" disabled={locked || consent !== item.id} onClick={() => onRevoke(item.id)}>撤销密钥</button>
        </article>)}
      </> : null}
    </section>
    <section className="api-key-list api-key-history" aria-label="密钥签发历史"><h4>密钥签发历史</h4>
      <p>包含有效、到期和撤销记录；每次只展示一页。新签发记录请从最新重新读取，撤销状态以本页读取时为准。</p>
      <button className="text-button" disabled={locked} onClick={() => void readHistory(null, 1)}>从最新记录重新读取</button>
      {historyError ? <p role="alert">{historyError}</p> : null}
      {historyLoading ? <p role="status">正在读取历史…</p> : null}
      {history ? <><p>第{page}页 · 窗口开始：{stamp(history.window_started_at)} · 本页读取：{stamp(history.read_at)}</p>
        {!history.items.length ? <p>尚无签发记录。</p> : history.items.map(item => <article className="api-key-row" key={item.id}>
          <strong>{item.name}</strong><p>{item.scopes.map(s => labels[s]).join(" · ")}<br />签发于 {stamp(item.created_at)} · 有效至 {stamp(item.expires_at)} · {stateLabel(item)}</p>
        </article>)}
        <button className="secondary-button" disabled={locked || historyLoading || !!historyError || !history.next_cursor} onClick={() => void readHistory(history, page + 1)}>查看更早记录</button>
        {!history.next_cursor ? <p>已到最早记录。</p> : null}
      </> : null}
    </section>
  </div>;
}
