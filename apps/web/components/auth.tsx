"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { AuthState } from "@tire/domain-types";
import { ApiError, tireApi } from "@tire/api-client";

export type AuthResult = { ok: true; user: AuthState["user"] } | { ok: false; error: string };

type WorkbenchAuth = {
  state: AuthState;
  ready: boolean;
  /** Changes at the start of every identity/revalidation operation. */
  ownerEpoch: number;
  ownerSignal: AbortSignal;
  isCurrentOwner: (epoch: number) => boolean;
  refresh: () => Promise<AuthState | null>;
  login: (username: string, password: string) => Promise<AuthResult>;
  register: (username: string, password: string, displayName?: string) => Promise<AuthResult>;
  logout: () => Promise<void>;
};

const anonymous: AuthState = { authenticated: false, user: null };
const unavailableOwner = AbortSignal.abort();
const WorkbenchAuthContext = createContext<WorkbenchAuth>({
  state: anonymous, ready: false, ownerEpoch: 0, ownerSignal: unavailableOwner, isCurrentOwner: () => false,
  refresh: async () => null,
  login: async () => ({ ok: false, error: "账户服务尚未就绪，请稍后重试。" }),
  register: async () => ({ ok: false, error: "账户服务尚未就绪，请稍后重试。" }),
  logout: async () => {},
});
export const useWorkbenchAuth = () => useContext(WorkbenchAuthContext);

/** context 用于同一 code 在不同操作下的文案区分（如 last_admin 同时服务于降级与删除）。 */
export const authErrorText = (cause: unknown, context?: "profile" | "delete_user") => {
  if (cause instanceof ApiError) {
    if (cause.code === "username_taken") return "此用户名已被注册。";
    if (cause.code === "bad_credentials") return "用户名或密码不正确。";
    if (cause.code === "auth_too_many_attempts") return "连续失败次数过多，请稍后再试。";
    if (cause.code === "last_admin") return context === "delete_user"
      ? "不能删除唯一管理员；请先提升另一位管理员。"
      : "不能取消唯一管理员的角色，请先将其他账户设为管理员。";
    if (cause.code === "user_not_found") return "目标用户不存在，请刷新列表后重试。";
    if (context === "profile") {
      if (cause.status === 403) return "修改资料需要先登录。";
      if (cause.status === 422) return "用户名需 3-32 位字母数字下划线连字符，显示名不超过 80 字。";
    }
  }
  return cause instanceof Error && cause.message ? cause.message : "账户操作未完成，请重试。";
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(anonymous);
  const [ready, setReady] = useState(false);
  const [ownerEpoch, setOwnerEpoch] = useState(0);
  const [ownerSignal, setOwnerSignal] = useState<AbortSignal>(unavailableOwner);
  const generation = useRef(0);
  const session = useRef<AbortController | null>(null);
  const mutation = useRef<AbortController | null>(null);

  const begin = useCallback(() => {
    session.current?.abort();
    const controller = new AbortController(); session.current = controller;
    setOwnerSignal(controller.signal);
    const epoch = ++generation.current;
    setOwnerEpoch(epoch); setReady(false);
    return controller;
  }, []);
  const isCurrentOwner = useCallback((epoch: number) => generation.current === epoch, []);
  const current = (controller: AbortController) => !controller.signal.aborted && session.current === controller;

  const readCurrent = useCallback(async (controller: AbortController) => {
    try {
      const result = await tireApi.authMe(controller.signal);
      if (!current(controller)) return null;
      setState(result); setReady(true); return result;
    } catch {
      if (!current(controller)) return null;
      // A failed identity read cannot authorize loading private actor state.
      setState(anonymous); setReady(false); return null;
    }
  }, []);
  const refresh = useCallback(async () => readCurrent(begin()), [begin, readCurrent]);

  useEffect(() => {
    void refresh();
    const revalidate = () => {
      // Window focus can return during an account write. Private state is
      // already invalidated; let that operation settle and confirm its owner.
      if (document.visibilityState !== "hidden" && (!mutation.current || mutation.current.signal.aborted)) void refresh();
    };
    const unavailable = () => { begin(); setState(anonymous); };
    window.addEventListener("online", revalidate);
    window.addEventListener("offline", unavailable);
    window.addEventListener("focus", revalidate);
    document.addEventListener("visibilitychange", revalidate);
    window.addEventListener("tire-session-revalidate", revalidate);
    window.addEventListener("tire-session-unavailable", unavailable);
    window.addEventListener("tire-offline-owner-changed", unavailable);
    return () => {
      session.current?.abort(); generation.current++;
      window.removeEventListener("online", revalidate);
      window.removeEventListener("offline", unavailable);
      window.removeEventListener("focus", revalidate);
      document.removeEventListener("visibilitychange", revalidate);
      window.removeEventListener("tire-session-revalidate", revalidate);
      window.removeEventListener("tire-session-unavailable", unavailable);
      window.removeEventListener("tire-offline-owner-changed", unavailable);
    };
  }, [begin, refresh]);

  const login = useCallback(async (username: string, password: string): Promise<AuthResult> => {
    const controller = begin();
    mutation.current = controller;
    try {
      const result = await tireApi.authLogin({ username, password }, controller.signal);
      if (!current(controller)) return { ok: false, error: "账户操作已变化，请重新核对当前账户。" };
      setState(result); setReady(true); return { ok: true, user: result.user };
    } catch (cause) {
      if (current(controller)) await readCurrent(controller);
      return { ok: false, error: authErrorText(cause) };
    } finally { if (mutation.current === controller) mutation.current = null; }
  }, [begin, readCurrent]);

  const register = useCallback(async (username: string, password: string, displayName?: string): Promise<AuthResult> => {
    const trimmed = displayName?.trim();
    const controller = begin();
    mutation.current = controller;
    try {
      const result = await tireApi.authRegister({ username, password, ...(trimmed ? { display_name: trimmed } : {}) }, controller.signal);
      if (!current(controller)) return { ok: false, error: "账户操作已变化，请重新核对当前账户。" };
      setState(result); setReady(true); return { ok: true, user: result.user };
    } catch (cause) {
      if (current(controller)) await readCurrent(controller);
      return { ok: false, error: authErrorText(cause) };
    } finally { if (mutation.current === controller) mutation.current = null; }
  }, [begin, readCurrent]);

  const logout = useCallback(async () => {
    const controller = begin();
    mutation.current = controller;
    try {
      const result = await tireApi.authLogout(controller.signal);
      if (current(controller)) { setState(result); setReady(true); }
    }
    catch { // The cookie may already be gone; re-check instead of asserting a stale view.
      if (current(controller)) await readCurrent(controller);
    } finally { if (mutation.current === controller) mutation.current = null; }
  }, [begin, readCurrent]);

  return <WorkbenchAuthContext.Provider value={{ state, ready, ownerEpoch, ownerSignal, isCurrentOwner, refresh, login, register, logout }}>{children}</WorkbenchAuthContext.Provider>;
}
