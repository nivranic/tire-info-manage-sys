"use client";

import { useEffect, useRef, useState } from "react";
import { useWorkbenchAuth } from "./auth";
import { useToast } from "./toast";
import { Icon } from "./icons";

const usernamePattern = "[A-Za-z0-9_-]{3,32}";

/** 本机多用户工作台账户对话框：已登录态显示账户信息，未登录态提供登录 / 注册两个表单。 */
export default function AccountDialog({ onClose }: { onClose: () => void }) {
  const auth = useWorkbenchAuth();
  const toast = useToast();
  const dialog = useRef<HTMLDialogElement>(null);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); };
  }, []);

  function switchMode(next: "login" | "register") {
    if (busy || mode === next) return;
    setMode(next); setError("");
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const result = mode === "login"
        ? await auth.login(username.trim(), password)
        : await auth.register(username.trim(), password, displayName);
      if (result.ok) {
        setPassword(""); setError("");
        const role = result.user?.is_admin ? "管理员" : "研究员";
        toast(mode === "login" ? `已登录 · 角色：${role}` : `已注册并登录 · 角色：${role}`, "success");
        return; // 登录态由 context 更新，视图随之切换。
      }
      setError(result.error);
    } finally { setBusy(false); }
  }

  async function signOut() {
    if (busy) return;
    setBusy(true); setError("");
    try { await auth.logout(); setUsername(""); setPassword(""); setDisplayName(""); setMode("login"); }
    finally { setBusy(false); }
  }

  const user = auth.state.user;
  return <dialog ref={dialog} className="fact-review-dialog account-dialog" aria-labelledby="account-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="fact-review-heading"><div><span className="eyebrow">LOCAL WORKSPACE · ACCOUNT</span><h2 id="account-title">本机账户</h2></div><button type="button" className="icon-button" aria-label="关闭账户窗口" disabled={busy} onClick={onClose}><Icon name="close" size={20} /></button></div>
    <div className="fact-review-content">
      {auth.state.authenticated && user ? <>
        <p className="review-boundary">本机多用户工作台账户，用于区分研究者并控制管理操作；不改变证据与快照的本地保留方式。</p>
        <div className="account-summary">
          <span className="avatar">{(user.display_name || user.username).slice(0, 1) || "研"}</span>
          <div><strong>{user.display_name || user.username}</strong><small>@{user.username}</small></div>
          <span className={`tag ${user.is_admin ? "warning" : "quiet"}`}>{user.is_admin ? "管理员" : "研究员"}</span>
        </div>
        {error ? <div className="inline-error" role="alert">{error}</div> : null}
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void signOut()}>{busy ? "正在退出…" : "退出登录"}</button>
      </> : <>
        <div className="account-form-switch" role="tablist" aria-label="账户操作">
          <button type="button" className="text-button" aria-pressed={mode === "login"} disabled={busy} onClick={() => switchMode("login")}>登录</button>
          <button type="button" className="text-button" aria-pressed={mode === "register"} disabled={busy} onClick={() => switchMode("register")}>注册新账户</button>
        </div>
        {error ? <div className="inline-error" role="alert">{error}</div> : null}
        <form className="review-form" onSubmit={submit}>
          <label><span>用户名</span><input value={username} required minLength={3} maxLength={32} pattern={usernamePattern} title="3-32 位字母、数字、下划线或连字符" autoComplete="username" disabled={busy} onChange={event => setUsername(event.target.value)} /></label>
          {mode === "register" ? <label><span>显示名称（可选）</span><input value={displayName} maxLength={80} disabled={busy} onChange={event => setDisplayName(event.target.value)} /></label> : null}
          <label><span>密码</span><input type="password" value={password} required minLength={8} maxLength={200} autoComplete={mode === "login" ? "current-password" : "new-password"} disabled={busy} onChange={event => setPassword(event.target.value)} /></label>
          {mode === "register" ? <p className="review-boundary">首个注册用户自动成为管理员；后续账户为研究员。注册即创建本机工作台账户。</p> : null}
          <button type="submit" className="primary-button" disabled={busy}>{busy ? "正在提交…" : mode === "login" ? "登录" : "注册并登录"}</button>
        </form>
      </>}
      <p className="account-note">本机多用户工作台账户；不用于服务器部署，详见部署密钥政策。</p>
    </div>
  </dialog>;
}
