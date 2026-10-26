"use client";
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Icon } from "./icons";

export type ToastKind = "success" | "info" | "error";
type ToastItem = { id: number; kind: ToastKind; text: string };
type ShowToast = (text: string, kind?: ToastKind) => void;

type ToastLayout = {
  navigationRef: (node: HTMLElement | null) => void;
  comparisonRef: (node: HTMLElement | null) => void;
  mainRef: (node: HTMLElement | null) => void;
};
type ToastEntryHandle = {
  item: ToastItem;
  node: HTMLDivElement;
  cancel: () => void;
  setHidden: (hidden: boolean) => void;
  refreshFocus: () => void;
};
type RegisterEntry = (id: number, entry: ToastEntryHandle) => () => void;
type DismissToast = (id: number, manual: boolean) => void;

const ToastContext = createContext<{ show: ShowToast; layout: ToastLayout } | null>(null);
const TOAST_LIFETIME_MS = 4600;
const TOAST_STACK_LIMIT = 3;

export function useToast(): ShowToast {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast 必须在 ToastProvider 内使用。");
  return value.show;
}

export function useToastLayout(): ToastLayout {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToastLayout 必须在 ToastProvider 内使用。");
  return value.layout;
}

function focusable(node: HTMLElement | null): node is HTMLElement {
  return !!node && node.isConnected && !node.closest('[inert], [aria-hidden="true"]')
    && !node.matches(":disabled") && node.getClientRects().length > 0
    && getComputedStyle(node).visibility !== "hidden"
    && (node.hasAttribute("tabindex") || node.matches('button, input:not([type="hidden"]), select, textarea, a[href], [contenteditable="true"]'));
}

function ToastEntry({ item, dismiss, register }: { item: ToastItem; dismiss: DismissToast; register: RegisterEntry }) {
  const element = useRef<HTMLDivElement>(null);
  const life = useRef({ remaining: TOAST_LIFETIME_MS, started: null as number | null,
    timer: null as number | null, generation: 0, ready: false, hover: false, focus: false, hidden: false });
  const stop = useCallback(() => {
    const state = life.current;
    state.generation++;
    if (state.timer !== null) window.clearTimeout(state.timer);
    state.timer = null;
    if (state.started !== null) state.remaining = Math.max(0, state.remaining - (performance.now() - state.started));
    state.started = null;
  }, []);
  const reconcile = useCallback(() => {
    const state = life.current;
    if (!state.ready) return;
    if (state.hover || state.focus || state.hidden) { stop(); return; }
    if (state.timer !== null) return;
    const generation = ++state.generation;
    state.started = performance.now();
    state.timer = window.setTimeout(() => {
      if (!state.ready || state.generation !== generation) return;
      state.timer = null;
      // A queued timeout must not outrun a newer focus/visibility transition.
      state.focus = !!element.current?.contains(document.activeElement);
      state.hidden = document.hidden;
      if (state.hover || state.focus || state.hidden) { stop(); return; }
      state.remaining = 0;
      state.started = null;
      dismiss(item.id, false);
    }, state.remaining);
  }, [dismiss, item.id, stop]);
  useLayoutEffect(() => {
    const node = element.current;
    if (!node) return;
    const state = life.current;
    state.ready = true;
    state.hidden = document.hidden;
    state.focus = node.contains(document.activeElement);
    state.hover = window.matchMedia("(any-hover: hover)").matches && node.matches(":hover");
    const unregister = register(item.id, {
      item,
      node,
      cancel: () => { state.ready = false; stop(); },
      setHidden: hidden => { state.hidden = hidden; reconcile(); },
      refreshFocus: () => { state.ready = true; state.focus = node.contains(document.activeElement); reconcile(); },
    });
    reconcile();
    return () => {
      // Keep remaining time across StrictMode's cleanup/setup replay.
      state.ready = false;
      stop();
      unregister();
    };
  }, [item, reconcile, register, stop]);
  return <div ref={element} className={`toast toast-${item.kind}`} data-toast-id={item.id}
    role={item.kind === "error" ? "alert" : "status"}
    onPointerEnter={event => {
      if (event.pointerType === "touch" || !window.matchMedia("(any-hover: hover)").matches) return;
      life.current.hover = true; reconcile();
    }}
    onPointerLeave={event => { if (event.pointerType !== "touch") { life.current.hover = false; reconcile(); } }}
    onPointerCancel={event => { if (event.pointerType !== "touch") { life.current.hover = false; reconcile(); } }}
    onFocusCapture={() => { life.current.focus = true; reconcile(); }}
    onBlurCapture={event => {
      if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
      life.current.focus = false; reconcile();
    }}>
    <span className="toast-dot" aria-hidden="true" />
    <span className="toast-text">{item.text}</span>
    <button type="button" className="icon-button toast-close" aria-label="关闭提示" onClick={() => dismiss(item.id, true)}><Icon name="close" size={14} /></button>
  </div>;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const currentItems = useRef<ToastItem[]>([]);
  const nextId = useRef(1);
  const mounted = useRef(true);
  const entries = useRef(new Map<number, ToastEntryHandle>());
  const capacityEvictions = useRef(new Set<number>());
  const outsideFocus = useRef<HTMLElement | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const edge = useRef<HTMLDivElement>(null);
  const stack = useRef<HTMLDivElement>(null);
  const nodes = useRef<{ navigation: HTMLElement | null; comparison: HTMLElement | null; main: HTMLElement | null }>({ navigation: null, comparison: null, main: null });
  const observer = useRef<ResizeObserver | null>(null);
  const scheduleMeasure = useRef<() => void>(() => {});
  const measureNow = useRef<() => void>(() => {});
  const register = useCallback<RegisterEntry>((id, entry) => {
    entries.current.set(id, entry);
    return () => {
      if (entries.current.get(id) === entry) { entries.current.delete(id); capacityEvictions.current.delete(id); }
    };
  }, []);
  const publish = useCallback((next: ToastItem[]) => {
    if (!mounted.current) return;
    while (next.length > TOAST_STACK_LIMIT) {
      const oldest = next.findIndex(item => !entries.current.get(item.id)?.node.contains(document.activeElement));
      const [removed] = next.splice(oldest, 1);
      const entry = entries.current.get(removed.id);
      if (entry) { capacityEvictions.current.add(removed.id); entry.cancel(); }
    }
    currentItems.current = next;
    setItems(next);
  }, []);
  const dismiss = useCallback<DismissToast>((id, manual) => {
    if (!mounted.current) return;
    const index = currentItems.current.findIndex(item => item.id === id);
    if (index === -1) return;
    const entry = entries.current.get(id);
    const ownsFocus = !!entry?.node.contains(document.activeElement);
    if (!manual && ownsFocus) { entry?.refreshFocus(); return; }
    const remaining = currentItems.current.filter(item => item.id !== id);
    if (manual && ownsFocus && entry) {
      const adjacent = [...remaining.slice(index), ...remaining.slice(0, index).reverse()];
      const candidates = adjacent.map(item => entries.current.get(item.id)?.node.querySelector<HTMLElement>(".toast-close") || null);
      candidates.push(outsideFocus.current, nodes.current.main);
      for (const candidate of candidates) {
        // A focus handler may already have moved focus elsewhere; never overwrite it.
        if (!entry.node.contains(document.activeElement)) break;
        if (focusable(candidate)) candidate.focus({ preventScroll: true });
      }
    }
    if (!mounted.current) return;
    entry?.cancel();
    capacityEvictions.current.delete(id);
    // Focusing a fallback can synchronously show another toast.
    publish(currentItems.current.filter(item => item.id !== id));
  }, [publish]);
  const show = useCallback((text: string, kind: ToastKind = "info") => {
    const trimmed = text.trim();
    if (!trimmed || !mounted.current) return;
    const id = nextId.current++;
    publish([...currentItems.current, { id, kind, text: trimmed }]);
  }, [publish]);
  const registerNode = useCallback((name: "navigation" | "comparison" | "main", node: HTMLElement | null) => {
    const previous = nodes.current[name];
    if (previous === node) return;
    if (name !== "main" && previous) observer.current?.unobserve(previous);
    nodes.current[name] = node;
    if (name !== "main" && node) observer.current?.observe(node);
    scheduleMeasure.current();
  }, []);
  const navigationRef = useCallback((node: HTMLElement | null) => registerNode("navigation", node), [registerNode]);
  const comparisonRef = useCallback((node: HTMLElement | null) => registerNode("comparison", node), [registerNode]);
  const mainRef = useCallback((node: HTMLElement | null) => registerNode("main", node), [registerNode]);
  const layout = useMemo(() => ({ navigationRef, comparisonRef, mainRef }), [navigationRef, comparisonRef, mainRef]);
  const context = useMemo(() => ({ show, layout }), [show, layout]);
  useLayoutEffect(() => {
    mounted.current = true;
    let frame: number | null = null;
    const height = (node: HTMLElement | null) => node?.isConnected && node.getClientRects().length ? node.getBoundingClientRect().height : 0;
    const write = (name: string, value: number) => {
      const target = wrapper.current;
      const pixels = `${value}px`;
      if (target && target.style.getPropertyValue(name) !== pixels) target.style.setProperty(name, pixels);
    };
    const measure = () => {
      if (!wrapper.current || !edge.current || !stack.current) return;
      const navigation = height(nodes.current.navigation);
      const comparison = height(nodes.current.comparison);
      const base = navigation > 0 ? navigation + 8 : height(edge.current);
      const budget = Math.max(0, document.documentElement.clientHeight - base - comparison - (comparison > 0 ? 8 : 0) - 44 - 8);
      write("--toast-base-bottom", base);
      write("--toast-stack-max-height", budget);
      const toasts = stack.current.childElementCount ? height(stack.current) : 0;
      write("--toast-tray-bottom", base + (toasts > 0 ? toasts + 8 : 0));
      const empty = navigation > 0 ? navigation + 8 : parseFloat(getComputedStyle(edge.current).paddingBottom) || 0;
      write("--toast-content-offset", toasts > 0 || comparison > 0
        ? base + toasts + comparison + (toasts > 0 && comparison > 0 ? 8 : 0) + 8 : empty);
    };
    const schedule = () => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => { frame = null; measure(); });
    };
    const visibility = () => { for (const entry of entries.current.values()) entry.setHidden(document.hidden); };
    scheduleMeasure.current = schedule;
    measureNow.current = measure;
    observer.current = new ResizeObserver(schedule);
    for (const node of [edge.current, stack.current, nodes.current.navigation, nodes.current.comparison]) if (node) observer.current.observe(node);
    window.addEventListener("resize", schedule);
    document.addEventListener("visibilitychange", visibility);
    visibility();
    measure();
    return () => {
      mounted.current = false;
      for (const entry of entries.current.values()) entry.cancel();
      capacityEvictions.current.clear();
      observer.current?.disconnect(); observer.current = null;
      if (frame !== null) window.cancelAnimationFrame(frame);
      scheduleMeasure.current = () => {}; measureNow.current = () => {};
      window.removeEventListener("resize", schedule);
      document.removeEventListener("visibilitychange", visibility);
      for (const name of ["--toast-base-bottom", "--toast-tray-bottom", "--toast-content-offset", "--toast-stack-max-height"]) wrapper.current?.style.removeProperty(name);
    };
  }, []);
  useLayoutEffect(() => { measureNow.current(); }, [items]);
  return <ToastContext.Provider value={context}>
    <div className="toast-layout" ref={wrapper}>
      {children}
      <div className="toast-layout-edge" ref={edge} aria-hidden="true" />
      <div className="toast-stack" ref={stack} aria-live="polite" onFocusCapture={event => {
        // Focus can preempt a concurrent commit. Rescue only a still-mounted
        // capacity evictee; its metadata disappears in the entry cleanup.
        for (const [id, entry] of entries.current) {
          if (capacityEvictions.current.has(id) && entry.node.contains(document.activeElement)) {
            capacityEvictions.current.delete(id);
            publish([...currentItems.current, entry.item].sort((left, right) => left.id - right.id));
            entry.refreshFocus();
            break;
          }
        }
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
        outsideFocus.current = event.relatedTarget instanceof HTMLElement && focusable(event.relatedTarget) ? event.relatedTarget : null;
      }}>
        {items.map(item => <ToastEntry item={item} key={item.id} dismiss={dismiss} register={register} />)}
      </div>
    </div>
  </ToastContext.Provider>;
}
