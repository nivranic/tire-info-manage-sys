"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { FocusEvent as ReactFocusEvent, KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent, ReactNode } from "react";

export type ComparisonLayoutColumn = { id: string; label: string; header: ReactNode };
export type ComparisonLayoutRow = { id: string; label: string; cells: readonly ReactNode[] };

type Drag = { id: string; pointerId: number; startX: number; startWidth: number; handle: HTMLButtonElement };
type KeyboardResize = { id: string; startWidth: number };
type FocusTransaction = { target: HTMLElement; clear: () => void };
type PendingResizeFocus = { target: HTMLButtonElement };

const FIELD_WIDTH = 180;
const DATA_WIDTH = 248;
const limits = (index: number) => index === 0 ? { min: 136, max: 300 } : { min: 160, max: 480 };
const defaultWidth = (index: number) => index === 0 ? FIELD_WIDTH : DATA_WIDTH;
const clampWidth = (index: number, width: number) => {
  const { min, max } = limits(index);
  return Math.max(min, Math.min(max, width));
};
const focusCorrection = (viewport: HTMLDivElement, target: HTMLElement, dataControl: boolean) => {
  const box = target.getBoundingClientRect(), viewportBox = viewport.getBoundingClientRect();
  const stickyHeader = viewport.querySelector("thead th:first-child")?.getBoundingClientRect();
  const inset = 6;
  const left = Math.max(viewportBox.left, stickyHeader?.right ?? viewportBox.left) + inset;
  const right = viewportBox.right - inset;
  const top = Math.max(viewportBox.top, stickyHeader?.bottom ?? viewportBox.top) + inset;
  const bottom = viewportBox.bottom - inset;
  let nextLeft = viewport.scrollLeft, nextTop = viewport.scrollTop;
  if (box.width <= right - left) {
    if (box.left < left) nextLeft += box.left - left;
    else if (box.right > right) nextLeft += box.right - right;
  } else if (box.left < left || box.left >= right) nextLeft += box.left - left;
  if (dataControl) {
    if (box.height <= bottom - top) {
      if (box.top < top) nextTop += box.top - top;
      else if (box.bottom > bottom) nextTop += box.bottom - bottom;
    } else if (box.top < top || box.top >= bottom) nextTop += box.top - top;
  }
  return { left: nextLeft, top: nextTop,
    hidden: Math.abs(nextLeft - viewport.scrollLeft) >= 0.5 || Math.abs(nextTop - viewport.scrollTop) >= 0.5 };
};

export default function ComparisonTableLayout({ label, columns, rows }: {
  label: string; columns: readonly ComparisonLayoutColumn[]; rows: readonly ComparisonLayoutRow[];
}) {
  const hintId = useId();
  const scroll = useRef<HTMLDivElement>(null);
  const rowNodes = useRef(new Map<string, HTMLTableRowElement>());
  const drag = useRef<Drag | null>(null);
  const keyboardResize = useRef<KeyboardResize | null>(null);
  const focusTransaction = useRef<FocusTransaction | null>(null);
  const pendingResizeFocus = useRef<PendingResizeFocus | null>(null);
  const [widths, setWidths] = useState<Record<string, number>>({});
  const widthOf = (column: ComparisonLayoutColumn, index: number) =>
    clampWidth(index, widths[column.id] ?? defaultWidth(index));
  const measured = columns.map(widthOf);
  const tableWidth = measured.reduce((total, width) => total + width, 0);

  const setWidth = useCallback((id: string, index: number, width: number) => {
    const next = clampWidth(index, width);
    setWidths(previous => previous[id] === next ? previous : { ...previous, [id]: next });
  }, []);
  const clearFocusTransaction = useCallback(() => {
    const active = focusTransaction.current;
    focusTransaction.current = null;
    active?.clear();
  }, []);
  const clearPendingResizeFocus = useCallback(() => {
    pendingResizeFocus.current = null;
  }, []);
  const clearFocusState = useCallback(() => {
    clearPendingResizeFocus();
    clearFocusTransaction();
  }, [clearPendingResizeFocus, clearFocusTransaction]);
  const beginFocusTransaction = useCallback((viewport: HTMLDivElement, target: HTMLElement) => {
    clearFocusState();
    if (document.activeElement !== target || !target.isConnected || !viewport.contains(target)) return;
    const dataControl = !!target.closest("tbody td");
    const headerControl = !!target.closest("thead th:not(:first-child)");
    if (!dataControl && !headerControl) return;
    const transaction: FocusTransaction = { target, clear: () => {} };
    const cancel = () => clearFocusState();
    const cancelDrag = (move: PointerEvent) => { if (move.buttons) clearFocusState(); };
    const onScrollEnd = (scrollEvent: Event) => {
      if (scrollEvent.target !== viewport || focusTransaction.current !== transaction) return;
      if (document.activeElement !== target || !target.isConnected || !viewport.contains(target)) {
        clearFocusState();
        return;
      }
      const correction = focusCorrection(viewport, target, dataControl);
      if (!correction.hidden) return;
      clearFocusState();
      viewport.scrollTo({ left: correction.left, top: correction.top, behavior: "instant" });
    };
    transaction.clear = () => {
      viewport.removeEventListener("scrollend", onScrollEnd);
      document.removeEventListener("keydown", cancel, true);
      document.removeEventListener("wheel", cancel, true);
      document.removeEventListener("pointerdown", cancel, true);
      document.removeEventListener("touchmove", cancel, true);
      document.removeEventListener("pointermove", cancelDrag, true);
    };
    focusTransaction.current = transaction;
    viewport.addEventListener("scrollend", onScrollEnd);
    document.addEventListener("keydown", cancel, true);
    document.addEventListener("wheel", cancel, { capture: true, passive: true });
    document.addEventListener("pointerdown", cancel, { capture: true, passive: true });
    document.addEventListener("touchmove", cancel, { capture: true, passive: true });
    document.addEventListener("pointermove", cancelDrag, { capture: true, passive: true });
    const correction = focusCorrection(viewport, target, dataControl);
    viewport.scrollTo({ left: correction.left, top: correction.top, behavior: "instant" });
  }, [clearFocusState]);
  const finishDrag = useCallback((commit: boolean) => {
    const active = drag.current;
    if (!active) return;
    drag.current = null;
    if (!commit) {
      setWidths(previous => previous[active.id] === active.startWidth ? previous
        : { ...previous, [active.id]: active.startWidth });
    }
    if (keyboardResize.current?.id === active.id) keyboardResize.current = null;
    try {
      if (active.handle.hasPointerCapture(active.pointerId)) active.handle.releasePointerCapture(active.pointerId);
    } catch { /* The column or pointer may already have been removed. */ }
  }, []);

  useEffect(() => {
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || !drag.current) return;
      event.preventDefault(); event.stopPropagation();
      finishDrag(false);
    };
    window.addEventListener("keydown", escape, true);
    return () => {
      window.removeEventListener("keydown", escape, true);
      const active = drag.current;
      drag.current = null;
      try {
        if (active?.handle.hasPointerCapture(active.pointerId)) active.handle.releasePointerCapture(active.pointerId);
      } catch { /* Unmount also releases pointer capture. */ }
    };
  }, [finishDrag]);
  useEffect(() => {
    if (drag.current && !columns.some(column => column.id === drag.current?.id)) finishDrag(false);
    if (keyboardResize.current && !columns.some(column => column.id === keyboardResize.current?.id)) keyboardResize.current = null;
  }, [columns, finishDrag]);
  useEffect(() => () => clearFocusState(), [clearFocusState]);
  useLayoutEffect(() => {
    const pending = pendingResizeFocus.current;
    if (!pending) return;
    clearPendingResizeFocus();
    const viewport = scroll.current, target = pending.target;
    if (!viewport || document.activeElement !== target || !target.isConnected || !viewport.contains(target)) return;
    beginFocusTransaction(viewport, target);
  }, [widths, beginFocusTransaction, clearPendingResizeFocus]);

  const resizeKey = (event: ReactKeyboardEvent<HTMLButtonElement>, column: ComparisonLayoutColumn, index: number) => {
    const current = widthOf(column, index);
    if (event.key === "Escape" && keyboardResize.current?.id === column.id) {
      event.preventDefault();
      const restored = keyboardResize.current.startWidth;
      if (restored !== current) {
        pendingResizeFocus.current = { target: event.currentTarget };
        setWidth(column.id, index, restored);
      } else {
        const viewport = scroll.current;
        if (viewport) beginFocusTransaction(viewport, event.currentTarget);
      }
      keyboardResize.current = null;
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (keyboardResize.current?.id !== column.id) keyboardResize.current = { id: column.id, startWidth: current };
    const bound = limits(index);
    const next = event.key === "Home" ? bound.min : event.key === "End" ? bound.max
      : clampWidth(index, current + (event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 32 : 16));
    if (next !== current) {
      pendingResizeFocus.current = { target: event.currentTarget };
      setWidth(column.id, index, next);
    } else {
      const viewport = scroll.current;
      if (viewport) beginFocusTransaction(viewport, event.currentTarget);
    }
  };
  const startDrag = (event: ReactPointerEvent<HTMLButtonElement>, column: ComparisonLayoutColumn, index: number) => {
    if (event.button !== 0 || !event.isPrimary || drag.current) return;
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    clearFocusState();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { id: column.id, pointerId: event.pointerId, startX: event.clientX,
      startWidth: widthOf(column, index), handle: event.currentTarget };
  };
  const moveDrag = (event: ReactPointerEvent<HTMLButtonElement>, index: number) => {
    const active = drag.current;
    if (active?.pointerId === event.pointerId) setWidth(active.id, index, active.startWidth + event.clientX - active.startX);
  };
  const moveRow = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
      || !["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key) || !rows.length) return;
    const origin = event.target;
    if (origin !== event.currentTarget && !(origin instanceof HTMLTableRowElement && origin.parentElement?.tagName === "TBODY")) return;
    const currentIndex = origin === event.currentTarget ? -1 : rows.findIndex(row => row.id === (origin as HTMLTableRowElement).dataset.rowId);
    const next = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1
      : origin === event.currentTarget && event.key === "ArrowUp" ? rows.length - 1
      : Math.max(0, Math.min(rows.length - 1, currentIndex + (event.key === "ArrowDown" ? 1 : -1)));
    const target = rowNodes.current.get(rows[next].id), viewport = scroll.current;
    if (!target || !viewport) return;
    event.preventDefault();
    target.focus({ preventScroll: true });
    const rowBox = target.getBoundingClientRect(), viewportBox = viewport.getBoundingClientRect();
    const headerHeight = viewport.querySelector("thead")?.getBoundingClientRect().height ?? 0;
    const visibleTop = viewportBox.top + headerHeight;
    if (rowBox.top < visibleTop) viewport.scrollTop -= visibleTop - rowBox.top;
    else if (rowBox.bottom > viewportBox.bottom) viewport.scrollTop += rowBox.bottom - viewportBox.bottom;
  };
  const revealInteractive = (event: ReactFocusEvent<HTMLDivElement>) => {
    clearFocusState();
    const target = event.target, viewport = scroll.current;
    if (!viewport || !(target instanceof HTMLElement)
      || !target.matches("button, a[href], input, select, textarea, [tabindex]")) return;
    beginFocusTransaction(viewport, target);
  };

  return <section className="comparison-layout" aria-label={label}>
    <div className="comparison-layout-toolbar"><p id={hintId}>↑/↓ 移动字段行，Home/End 跳至首尾；拖动列边缘或聚焦后按 ←/→ 调整列宽，Esc 撤销。</p>
      <button type="button" className="text-button" onClick={() => { finishDrag(false); keyboardResize.current = null; setWidths({}); }}>重置列宽</button></div>
    <div ref={scroll} className="comparison-table-wrap comparison-layout-scroll" role="region" tabIndex={0}
      aria-label={`${label}，可横向与纵向滚动`} aria-describedby={hintId} onKeyDown={moveRow}
      onFocusCapture={revealInteractive} onBlurCapture={clearFocusState}
      style={{ scrollPaddingLeft: (measured[0] ?? FIELD_WIDTH) + 6 }}>
      <table className="comparison-table comparison-layout-table" aria-label={label} style={{ width: tableWidth }}>
        <colgroup>{columns.map((column, index) => <col key={column.id} style={{ width: measured[index] }} />)}</colgroup>
        <thead><tr>{columns.map((column, index) => <th key={column.id} scope="col">
          <span className="comparison-layout-heading">{column.header}</span>
          <button type="button" className="comparison-layout-resizer"
            aria-label={`调整${column.label}列宽，当前${measured[index]}像素`} aria-describedby={hintId}
            onFocus={() => { keyboardResize.current = { id: column.id, startWidth: widthOf(column, index) }; }}
            onBlur={() => { if (keyboardResize.current?.id === column.id) keyboardResize.current = null; }}
            onKeyDown={event => resizeKey(event, column, index)}
            onPointerDown={event => startDrag(event, column, index)}
            onPointerMove={event => moveDrag(event, index)}
            onPointerUp={event => { if (drag.current?.pointerId === event.pointerId) finishDrag(true); }}
            onPointerCancel={event => { if (drag.current?.pointerId === event.pointerId) finishDrag(false); }}
            onLostPointerCapture={event => { if (drag.current?.pointerId === event.pointerId) finishDrag(false); }} />
        </th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.id} data-row-id={row.id} tabIndex={-1}
          ref={node => { if (node) rowNodes.current.set(row.id, node); else rowNodes.current.delete(row.id); }}>
          <th scope="row">{row.label}</th>{columns.slice(1).map((column, index) => <td key={column.id}>{row.cells[index]}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}
