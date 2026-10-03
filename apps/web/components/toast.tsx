"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "./icons";

export type ToastKind = "success" | "info" | "error";
type ToastItem = { id: number; kind: ToastKind; text: string };
type ShowToast = (text: string, kind?: ToastKind) => void;

const ToastContext = createContext<ShowToast | null>(null);
const TOAST_LIFETIME_MS = 4600;
const TOAST_STACK_LIMIT = 3;

export function useToast(): ShowToast {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast 必须在 ToastProvider 内使用。");
  return value;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());
  const dismiss = useCallback((id: number) => {
    setItems(previous => previous.filter(item => item.id !== id));
    const timer = timers.current.get(id);
    if (timer !== undefined) { window.clearTimeout(timer); timers.current.delete(id); }
  }, []);
  const show = useCallback((text: string, kind: ToastKind = "info") => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const id = nextId.current++;
    setItems(previous => [...previous, { id, kind, text: trimmed }].slice(-TOAST_STACK_LIMIT));
    timers.current.set(id, window.setTimeout(() => dismiss(id), TOAST_LIFETIME_MS));
  }, [dismiss]);
  useEffect(() => () => { for (const timer of timers.current.values()) window.clearTimeout(timer); timers.current.clear(); }, []);
  return <ToastContext.Provider value={show}>
    {children}
    <div className="toast-stack" aria-live="polite">
      {items.map(item => <div className={`toast toast-${item.kind}`} key={item.id} role={item.kind === "error" ? "alert" : "status"}>
        <span className="toast-dot" aria-hidden="true" />
        <span className="toast-text">{item.text}</span>
        <button type="button" className="icon-button toast-close" aria-label="关闭提示" onClick={() => dismiss(item.id)}><Icon name="close" size={14} /></button>
      </div>)}
    </div>
  </ToastContext.Provider>;
}
