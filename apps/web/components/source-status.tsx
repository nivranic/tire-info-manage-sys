"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { SourceSettingView } from "@tire/domain-types";
import { tireApi } from "@tire/api-client";
import { canFetchSource, canQuerySource, hasSourceManagementAccess, sourceBlockerText, sourceCapabilityLabels, sourceStateLabels } from "./source-management-values";

type SourceAccess = {
  items: SourceSettingView[]; fresh: boolean; loading: boolean; error: string;
  get: (id: string) => SourceSettingView | undefined; canFetch: (id: string) => boolean; canQuery: (id: string) => boolean;
  refresh: (onFailure?: (cause: unknown) => void) => Promise<SourceSettingView[] | null>; ensure: (id: string, mode?: "query" | "management") => Promise<boolean>;
  accept: (source: SourceSettingView) => void;
};
const SourceAccessContext = createContext<SourceAccess>({ items: [], fresh: false, loading: false, error: "来源目录尚未核对", get: () => undefined, canFetch: () => false, canQuery: () => false, refresh: async () => null, ensure: async () => false, accept: () => {} });
export const useSourceAccess = () => useContext(SourceAccessContext);

export function SourceAccessProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<SourceSettingView[]>([]);
  const [fresh, setFresh] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const snapshot = useRef<{ items: SourceSettingView[]; fresh: boolean }>({ items: [], fresh: false });
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const initialized = useRef(false);
  const get = useCallback((id: string) => snapshot.current.items.find(item => item.source_id === id), []);
  const canFetch = useCallback((id: string) => canFetchSource(snapshot.current.items.find(item => item.source_id === id), snapshot.current.fresh), []);
  const canQuery = useCallback((id: string) => canQuerySource(snapshot.current.items.find(item => item.source_id === id), snapshot.current.fresh), []);
  const refresh = useCallback(async (onFailure?: (cause: unknown) => void) => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    const current = ++generation.current; initialized.current = true;
    snapshot.current.fresh = false; setFresh(false); setLoading(true); setError("");
    try {
      const result = await tireApi.sourceSettings(controller.signal);
      if (controller.signal.aborted || current !== generation.current) return null;
      if (result.scope !== "local_workspace" || !Array.isArray(result.items) || result.items.some(item => !item.source_id || !item.management || !Number.isInteger(item.management.access_generation))) throw new Error("来源管理目录格式不受支持。");
      const next = result.items.map(item => { const previous = snapshot.current.items.find(value => value.source_id === item.source_id); return previous && previous.management.revision > item.management.revision ? previous : item; });
      snapshot.current = { items: next, fresh: true }; setItems(next); setFresh(true); return next;
    } catch (cause) { if (!controller.signal.aborted && current === generation.current) { setError(cause instanceof Error ? cause.message : "来源目录刷新未完成。"); onFailure?.(cause); } return null; }
    finally { if (current === generation.current) { request.current = null; setLoading(false); } }
  }, []);
  const ensure = useCallback(async (id: string, mode: "query" | "management" = "query") => { const next = await refresh(); return !!next && (mode === "management" ? hasSourceManagementAccess : canQuerySource)(next.find(item => item.source_id === id), true); }, [refresh]);
  const accept = useCallback((source: SourceSettingView) => {
    request.current?.abort(); generation.current++;
    const previous = snapshot.current.items.find(item => item.source_id === source.source_id);
    if (!previous || previous.management.revision <= source.management.revision) {
      const next = [...snapshot.current.items.filter(item => item.source_id !== source.source_id), source];
      snapshot.current = { items: next, fresh: false }; setItems(next); setFresh(false);
    }
    void refresh();
  }, [refresh]);
  useEffect(() => {
    const focus = () => { if (initialized.current && document.visibilityState === "visible") void refresh(); };
    window.addEventListener("focus", focus); document.addEventListener("visibilitychange", focus);
    return () => { request.current?.abort(); generation.current++; window.removeEventListener("focus", focus); document.removeEventListener("visibilitychange", focus); };
  }, [refresh]);
  return <SourceAccessContext.Provider value={{ items, fresh, loading, error, get, canFetch, canQuery, refresh, ensure, accept }}>{children}</SourceAccessContext.Provider>;
}

export function SourceStatus({ sourceId, source }: { sourceId?: string; source?: SourceSettingView }) {
  const access = useSourceAccess(); const value = source || access.get(sourceId || "");
  if (!value) return <span className="tag warning">来源目录待核对</span>;
  return <div className="source-status-tags"><span className={`tag ${value.management.state === "enabled" ? "quiet" : "warning"}`}>{sourceStateLabels[value.management.state]}</span><span className="tag quiet">底层能力：{sourceCapabilityLabels[value.registered_status] || value.registered_status}</span>{value.environment_disabled ? <span className="tag warning">环境已停用</span> : null}<span className={`tag ${access.fresh && value.can_fetch ? "success" : "warning"}`}>{!access.fresh ? "在线许可待刷新" : value.can_fetch ? "允许在线采集" : "当前不采集"}</span></div>;
}
export function SourceOnlineNotice({ sourceId }: { sourceId: string }) {
  const access = useSourceAccess(); const source = access.get(sourceId);
  if (access.canFetch(sourceId)) return null;
  return <p className="source-access-notice" role="status">{!access.fresh ? "来源目录待核对，暂不发起新的在线操作。" : source?.blockers.map(sourceBlockerText).join("；") || "此来源当前不能在线采集。"}{access.canQuery(sourceId) ? " 可发起查询，仍按原规则询问是否读取历史；不代表已完成在线采集。" : ""} 历史证据与已保存记录仍可读取。</p>;
}
