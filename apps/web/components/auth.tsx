"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { AuthState } from "@tire/domain-types";
import { ApiError, tireApi } from "@tire/api-client";

export type AuthResult = { ok: true } | { ok: false; error: string };

type WorkbenchAuth = {
  state: AuthState;
  ready: boolean;
  refresh: () => Promise<AuthState | null>;
  login: (username: string, password: string) => Promise<AuthResult>;
  register: (username: string, password: string, displayName?: string) => Promise<AuthResult>;
  logout: () => Promise<void>;
};

const anonymous: AuthState = { authenticated: false, user: null };
const WorkbenchAuthContext = createContext<WorkbenchAuth>({
  state: anonymous, ready: false,
  refresh: async () => null,
  login: async () => ({ ok: false, error: "账户服务尚未就绪，请稍后重试。" }),
  register: async () => ({ ok: false, error: "账户服务尚未就绪，请稍后重试。" }),
  logout: async () => {},
});
export const useWorkbenchAuth = () => useContext(WorkbenchAuthContext);

const authErrorText = (cause: unknown) => {
  if (cause instanceof ApiError) {
    if (cause.code === "username_taken") return "此用户名已被注册。";
    if (cause.code === "bad_credentials") return "用户名或密码不正确。";
    if (cause.code === "auth_too_many_attempts") return "连续失败次数过多，请稍后再试。";
  }
  return cause instanceof Error && cause.message ? cause.message : "账户操作未完成，请重试。";
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(anonymous);
  const [ready, setReady] = useState(false);
  const session = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    session.current?.abort();
    const controller = new AbortController(); session.current = controller;
    try {
      const result = await tireApi.authMe(controller.signal);
      if (controller.signal.aborted) return null;
      setState(result); setReady(true); return result;
    } catch {
      if (controller.signal.aborted) return null;
      // Without a readable session we can only conclude "not authenticated on this client".
      setState(anonymous); setReady(true); return null;
    } finally { if (session.current === controller) session.current = null; }
  }, []);

  useEffect(() => { void refresh(); return () => session.current?.abort(); }, [refresh]);

  const login = useCallback(async (username: string, password: string): Promise<AuthResult> => {
    try { setState(await tireApi.authLogin({ username, password })); setReady(true); return { ok: true }; }
    catch (cause) { return { ok: false, error: authErrorText(cause) }; }
  }, []);

  const register = useCallback(async (username: string, password: string, displayName?: string): Promise<AuthResult> => {
    const trimmed = displayName?.trim();
    try {
      setState(await tireApi.authRegister({ username, password, ...(trimmed ? { display_name: trimmed } : {}) }));
      setReady(true); return { ok: true };
    } catch (cause) { return { ok: false, error: authErrorText(cause) }; }
  }, []);

  const logout = useCallback(async () => {
    try { setState(await tireApi.authLogout()); }
    catch { // The cookie may already be gone; re-check instead of asserting a stale view.
      await refresh();
    }
  }, [refresh]);

  return <WorkbenchAuthContext.Provider value={{ state, ready, refresh, login, register, logout }}>{children}</WorkbenchAuthContext.Provider>;
}
