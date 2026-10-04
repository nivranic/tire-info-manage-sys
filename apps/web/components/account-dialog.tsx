"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AuthUser, AuthUserListItem } from "@tire/domain-types";
import { tireApi } from "@tire/api-client";
import { useWorkbenchAuth, authErrorText } from "./auth";
import { useToast } from "./toast";
import { Icon } from "./icons";

const usernamePattern = "[A-Za-z0-9_-]{3,32}";

/** 登录态「我的资料」区：任何已登录用户可自改用户名 / 显示名（POST /v1/auth/profile）。 */
function ProfilePanel({ user, locked, onProfileChanged }: { user: AuthUser; locked: boolean; onProfileChanged: () => void }) {
  const toast = useToast();
  const [username, setUsername] = useState(user.username);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (locked || busy) return;
    setBusy(true); setError("");
    try {
      const result = await tireApi.authUpdateProfile({ username: username.trim(), display_name: displayName.trim() });
      setUsername(result.user.username); setDisplayName(result.user.display_name);
      toast("资料已更新", "success");
      onProfileChanged(); // 上层刷新 me，账户摘要与 @用户名 随之同步。
    } catch (cause) { setError(authErrorText(cause, "profile")); }
    finally { setBusy(false); }
  }

  return <section className="account-admin-panel" aria-labelledby="account-profile-title">
    <div className="account-admin-heading">
      <div><span className="eyebrow">PROFILE · MINE</span><h3 id="account-profile-title">我的资料</h3></div>
    </div>
    <p className="review-boundary">修改自己的用户名或显示名；不会影响其他账户，也不会使当前登录失效。</p>
    {error ? <div className="inline-error" role="alert">{error}</div> : null}
    <form className="review-form" onSubmit={submit}>
      <label><span>用户名</span><input value={username} required minLength={3} maxLength={32} pattern={usernamePattern} title="3-32 位字母、数字、下划线或连字符" autoComplete="username" disabled={busy || locked} onChange={event => setUsername(event.target.value)} /></label>
      <label><span>显示名称</span><input value={displayName} maxLength={80} disabled={busy || locked} onChange={event => setDisplayName(event.target.value)} /></label>
      <button type="submit" className="secondary-button" disabled={busy || locked}>{busy ? "正在保存…" : "保存资料"}</button>
    </form>
  </section>;
}

/** 管理员用户管理区：列出本机用户并支持角色切换、密码重置与删除账户（R-014）。降级保护以服务端裁决为准，前端仅按"唯一管理员是自己"预禁用。 */
function AdminUsersPanel({ selfId, locked, onIdentityChanged }: { selfId: string; locked: boolean; onIdentityChanged: () => void }) {
  const toast = useToast();
  const [users, setUsers] = useState<AuthUserListItem[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [deleteFor, setDeleteFor] = useState<string | null>(null);
  const [deleteAck, setDeleteAck] = useState(false);
  const session = useRef<AbortController | null>(null);

  const loadUsers = useCallback(async () => {
    session.current?.abort();
    const controller = new AbortController(); session.current = controller;
    setLoadError("");
    try {
      const result = await tireApi.authUsers(controller.signal);
      if (!controller.signal.aborted) setUsers(result.items);
    } catch (cause) {
      if (!controller.signal.aborted) { setUsers(previous => previous ?? []); setLoadError(authErrorText(cause)); }
    } finally { if (session.current === controller) session.current = null; }
  }, []);

  useEffect(() => { void loadUsers(); return () => session.current?.abort(); }, [loadUsers]);

  function closeReset() { setResetFor(null); setNewPassword(""); setConfirmPassword(""); setError(""); }
  function closeDelete() { setDeleteFor(null); setDeleteAck(false); setError(""); }

  async function toggleRole(item: AuthUserListItem) {
    if (locked || busyId) return;
    setBusyId(item.id); setError("");
    try {
      await tireApi.authSetRole(item.id, !item.is_admin);
      await loadUsers();
      await onIdentityChanged(); // 自己的角色可能已变化，刷新 me 保持账户摘要一致。
    } catch (cause) { setError(authErrorText(cause)); }
    finally { setBusyId(null); }
  }

  async function submitReset(event: React.FormEvent, item: AuthUserListItem) {
    event.preventDefault();
    if (locked || busyId) return;
    if (newPassword !== confirmPassword) { setError("两次输入的密码不一致。"); return; }
    setBusyId(item.id); setError("");
    try {
      await tireApi.authResetPassword(item.id, newPassword);
      closeReset();
      toast("已重置并将该用户全部会话登出", "success");
    } catch (cause) { setError(authErrorText(cause)); }
    finally { setBusyId(null); }
  }

  async function submitDelete(event: React.FormEvent, item: AuthUserListItem) {
    event.preventDefault();
    if (locked || busyId || !deleteAck) return;
    setBusyId(item.id); setError("");
    try {
      const result = await tireApi.authDeleteUser(item.id);
      closeDelete();
      toast(`已删除 ${result.username}，解绑 ${result.sessions_unbound} 个登录会话`, "success");
      if (item.id === selfId) { await onIdentityChanged(); return; } // 自删（合法）：会话已退化为匿名，刷新 me 即回到未登录视图。
      await loadUsers();
    } catch (cause) { setError(authErrorText(cause, "delete_user")); }
    finally { setBusyId(null); }
  }

  const adminCount = (users ?? []).filter(item => item.is_admin).length;
  const rowBusy = busyId !== null;
  return <section className="account-admin-panel" aria-labelledby="account-admin-title">
    <div className="account-admin-heading">
      <div><span className="eyebrow">ADMIN · USERS</span><h3 id="account-admin-title">用户管理</h3></div>
      {loadError ? <button type="button" className="text-button" disabled={locked} onClick={() => void loadUsers()}>重试</button> : null}
    </div>
    <p className="review-boundary">本机账户列表；角色切换即时生效，重置密码会使该用户全部会话强制登出，删除账户不可恢复。</p>
    {loadError ? <div className="inline-error" role="alert">{loadError}</div> : null}
    {error ? <div className="inline-error" role="alert">{error}</div> : null}
    {users === null ? <p className="account-admin-status">正在载入用户…</p> : users.length === 0 ? <p className="account-admin-status">暂无账户。</p> : <ul className="account-user-list">
      {users.map(item => {
        const isSelf = item.id === selfId;
        const demoteSelfLocked = isSelf && item.is_admin && adminCount === 1;
        return <li className="account-user-row" key={item.id}>
          <div className="account-user-name">
            <strong>{item.display_name || item.username}{isSelf ? "（本人）" : ""}</strong>
            <small>@{item.username} · 会话 {item.session_count}</small>
          </div>
          <span className={`tag ${item.is_admin ? "warning" : "quiet"}`}>{item.is_admin ? "管理员" : "研究员"}</span>
          <div className="account-user-actions">
            {item.is_admin
              ? <button type="button" className="text-button" disabled={locked || rowBusy || demoteSelfLocked} title={demoteSelfLocked ? "唯一管理员不能自降级" : undefined} onClick={() => void toggleRole(item)}>{busyId === item.id ? "处理中…" : "取消管理员"}</button>
              : <button type="button" className="text-button" disabled={locked || rowBusy} onClick={() => void toggleRole(item)}>{busyId === item.id ? "处理中…" : "设为管理员"}</button>}
            <button type="button" className="text-button" disabled={locked || rowBusy} aria-expanded={resetFor === item.id} onClick={() => { if (resetFor === item.id) closeReset(); else { closeDelete(); setResetFor(item.id); setError(""); } }}>重置密码</button>
            <button type="button" className="text-button" disabled={locked || rowBusy} aria-expanded={deleteFor === item.id} title="危险操作：删除该账户并解绑其全部登录，不可恢复" onClick={() => { if (deleteFor === item.id) closeDelete(); else { closeReset(); setDeleteFor(item.id); setDeleteAck(false); setError(""); } }}>删除用户</button>
          </div>
          {resetFor === item.id ? <form className="review-form account-reset-form" onSubmit={event => void submitReset(event, item)}>
            <label><span>新密码（8-200 位）</span><input type="password" value={newPassword} required minLength={8} maxLength={200} autoComplete="new-password" disabled={locked || rowBusy} onChange={event => setNewPassword(event.target.value)} /></label>
            <label><span>确认新密码</span><input type="password" value={confirmPassword} required minLength={8} maxLength={200} autoComplete="new-password" disabled={locked || rowBusy} onChange={event => setConfirmPassword(event.target.value)} /></label>
            <div className="compare-toolbar">
              <button type="submit" className="secondary-button" disabled={locked || rowBusy}>{busyId === item.id ? "正在重置…" : "确认重置"}</button>
              <button type="button" className="text-button" disabled={locked || rowBusy} onClick={closeReset}>取消</button>
            </div>
          </form> : null}
          {deleteFor === item.id ? <form className="review-form account-reset-form" onSubmit={event => void submitDelete(event, item)}>
            <p className="review-boundary">删除后账户消失、全部登录会话解绑；其名下数据不再对任何账户可见，此操作不可恢复。</p>
            <label className="review-checkbox"><input type="checkbox" checked={deleteAck} disabled={locked || rowBusy} onChange={event => setDeleteAck(event.target.checked)} /><span>我确认删除该账户及其登录</span></label>
            <div className="compare-toolbar">
              <button type="submit" className="secondary-button" disabled={locked || rowBusy || !deleteAck}>{busyId === item.id ? "正在删除…" : "确认删除"}</button>
              <button type="button" className="text-button" disabled={locked || rowBusy} onClick={closeDelete}>取消</button>
            </div>
          </form> : null}
        </li>;
      })}
    </ul>}
  </section>;
}

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
        <ProfilePanel user={user} locked={busy} onProfileChanged={() => void auth.refresh()} />
        {user.is_admin ? <AdminUsersPanel selfId={user.id} locked={busy} onIdentityChanged={() => void auth.refresh()} /> : null}
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
