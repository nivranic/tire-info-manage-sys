"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type VariantPreviewSummary = {
  fields: readonly { id: string; label: string; text: string }[];
  identity: string;
  risks: readonly { id: string; text: string }[];
};

export function previewExcerpt(text: string, limit: number) {
  const points = Array.from(text.replace(/\s+/gu, " ").trim());
  return points.length > limit ? `${points.slice(0, limit - 1).join("")}…` : points.join("");
}

const modalIsOpen = () => !!document.querySelector('dialog[open], [role="dialog"][aria-modal="true"], .variant-context-menu');

/** One owner for the workbench, including the 300 ms pending-open interval. */
export function useVariantPreviewOwner(blocked: boolean, contextKey: string) {
  const [owner, setOwner] = useState<string | null>(null);
  const current = useRef<{ key: string; dismiss: () => void } | null>(null);
  const blockedRef = useRef(blocked);
  const keyboard = useRef(true);
  const tabFocusEvent = useRef<Event | null>(null);
  const consumeTabFocus = useCallback((event: Event) => {
    const matches = tabFocusEvent.current === event;
    tabFocusEvent.current = null;
    return matches;
  }, []);
  const release = useCallback((key: string) => {
    if (current.current?.key !== key) return;
    current.current = null;
    setOwner(previous => previous === key ? null : previous);
  }, []);
  const claim = useCallback((key: string, dismiss: () => void) => {
    if (blockedRef.current || modalIsOpen() || document.hidden) return false;
    if (current.current?.key !== key) current.current?.dismiss();
    current.current = { key, dismiss };
    setOwner(key);
    return true;
  }, []);
  const isCurrent = useCallback((key: string) => current.current?.key === key, []);
  const canOpen = useCallback(() => !blockedRef.current && !document.hidden && !modalIsOpen(), []);

  useLayoutEffect(() => {
    blockedRef.current = blocked;
    if (blocked) current.current?.dismiss();
  }, [blocked]);
  useLayoutEffect(() => () => { current.current?.dismiss(); }, [contextKey]);
  useEffect(() => {
    let pendingTab = false;
    let intentTimer: ReturnType<typeof setTimeout> | null = null;
    const clearIntent = () => {
      if (intentTimer !== null) clearTimeout(intentTimer);
      intentTimer = null;
      pendingTab = false;
      tabFocusEvent.current = null;
    };
    const key = (event: KeyboardEvent) => {
      clearIntent();
      if (event.key === "Tab" && !event.defaultPrevented && !event.altKey && !event.ctrlKey && !event.metaKey) {
        keyboard.current = true;
        pendingTab = true;
        intentTimer = setTimeout(clearIntent, 0);
      }
    };
    const focus = (event: FocusEvent) => {
      // Only this Tab's first native focus event may lift a previous dismissal.
      // Tabs inside evidence/dialogs cannot authorize a later programmatic return.
      tabFocusEvent.current = pendingTab ? event : null;
      pendingTab = false;
    };
    const pointer = () => { keyboard.current = false; clearIntent(); };
    document.addEventListener("keydown", key, true);
    document.addEventListener("pointerdown", pointer, true);
    document.addEventListener("focusin", focus, true);
    return () => {
      clearIntent();
      document.removeEventListener("keydown", key, true);
      document.removeEventListener("pointerdown", pointer, true);
      document.removeEventListener("focusin", focus, true);
    };
  }, []);
  return { owner, claim, release, isCurrent, canOpen, keyboard, consumeTabFocus };
}

type PreviewOwner = ReturnType<typeof useVariantPreviewOwner>;

/** Local holds belong to this trigger; old cleanup can only release its own owner. */
export function useVariantPreview({ ownerKey, snapshotId, owner, describedBy }: {
  ownerKey: string; snapshotId: string; owner: PreviewOwner; describedBy?: string;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const triggerHover = useRef(false);
  const keyboardFocus = useRef(false);
  const popupHover = useRef(false);
  const suppressed = useRef(false);
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [ready, setReady] = useState(false);
  const { claim, release, isCurrent, canOpen, keyboard, consumeTabFocus } = owner;
  const clearTimers = useCallback(() => {
    if (openTimer.current !== null) clearTimeout(openTimer.current);
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
    openTimer.current = null;
    closeTimer.current = null;
  }, []);
  const dismiss = useCallback(() => {
    clearTimers();
    suppressed.current = true;
    keyboardFocus.current = false;
    popupHover.current = false;
    setReady(false);
    release(ownerKey);
  }, [clearTimers, ownerKey, release]);
  const held = () => triggerHover.current || keyboardFocus.current || popupHover.current;
  const cancelClose = () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
    closeTimer.current = null;
  };
  const leave = () => {
    if (held() || !isCurrent(ownerKey)) return;
    cancelClose();
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null;
      if (!held()) dismiss();
    }, 150);
  };
  const enter = (immediate: boolean) => {
    cancelClose();
    if (suppressed.current) return;
    if (!canOpen() || !claim(ownerKey, dismiss)) { dismiss(); return; }
    if (openTimer.current !== null) clearTimeout(openTimer.current);
    openTimer.current = null;
    if (immediate) setReady(true);
    else openTimer.current = setTimeout(() => {
      openTimer.current = null;
      if (!suppressed.current && held() && isCurrent(ownerKey) && canOpen() && trigger.current?.isConnected) setReady(true);
      else dismiss();
    }, 300);
  };

  // Snapshot replacement and unmount invalidate pending opens without touching a new card.
  useLayoutEffect(() => () => { dismiss(); }, [snapshotId, dismiss]);
  const isOwner = owner.owner === ownerKey;
  useLayoutEffect(() => {
    if (!isOwner) return;
    const outside = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && !trigger.current?.contains(target) && !popup.current?.contains(target)) dismiss();
    };
    const scroll = (event: Event) => {
      if (event.target instanceof Node && popup.current?.contains(event.target)) return;
      dismiss();
    };
    const key = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { dismiss(); return; }
      if (event.key !== "Escape") return;
      // A menu/dialog owns its own Escape even during the same opening commit.
      const blockedByModal = !canOpen();
      dismiss();
      if (!blockedByModal) { event.preventDefault(); event.stopPropagation(); }
    };
    const hidden = () => { if (document.hidden) dismiss(); };
    const checkModal = () => { if (!canOpen()) dismiss(); };
    const observer = new MutationObserver(checkModal);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["open"] });
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", outside, true);
    document.addEventListener("scroll", scroll, true);
    document.addEventListener("keydown", key, true);
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("resize", dismiss);
    window.addEventListener("blur", dismiss);
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", dismiss);
    viewport?.addEventListener("scroll", dismiss);
    checkModal();
    return () => {
      observer.disconnect();
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", outside, true);
      document.removeEventListener("scroll", scroll, true);
      document.removeEventListener("keydown", key, true);
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("blur", dismiss);
      viewport?.removeEventListener("resize", dismiss);
      viewport?.removeEventListener("scroll", dismiss);
    };
  }, [isOwner, dismiss, canOpen]);

  const open = isOwner && ready;
  return {
    id, open, trigger, popup, dismiss,
    triggerProps: {
      "data-variant-preview-trigger": ownerKey,
      "aria-describedby": [describedBy, open ? id : undefined].filter(Boolean).join(" ") || undefined,
      onPointerEnter: (event: React.PointerEvent<HTMLButtonElement>) => {
        if (event.pointerType !== "mouse" || event.buttons !== 0) return;
        if (!triggerHover.current) suppressed.current = false;
        triggerHover.current = true;
        enter(false);
      },
      onPointerLeave: () => { triggerHover.current = false; leave(); },
      onPointerDown: dismiss,
      onPointerMove: (event: React.PointerEvent<HTMLButtonElement>) => { if (event.buttons !== 0) dismiss(); },
      onFocus: (event: React.FocusEvent<HTMLButtonElement>) => {
        const enteredByTab = consumeTabFocus(event.nativeEvent);
        if (!keyboard.current || !event.currentTarget.matches(":focus-visible")) return;
        if (suppressed.current && enteredByTab) suppressed.current = false;
        if (suppressed.current) return;
        keyboardFocus.current = true;
        enter(true);
      },
      onBlur: () => { keyboardFocus.current = false; leave(); },
    },
    popupProps: {
      onPointerEnter: (event: React.PointerEvent<HTMLDivElement>) => {
        if (event.pointerType !== "mouse") return;
        popupHover.current = true;
        cancelClose();
      },
      onPointerLeave: () => { popupHover.current = false; leave(); },
      onContextMenu: (event: React.MouseEvent<HTMLDivElement>) => event.stopPropagation(),
    },
  };
}

type Placement = { left: number; top: number; width: number };
const excerptLimits = [32, 20, 12, 8, 4];
const identityLimits = [64, 48, 40, 32, 24];

export default function VariantPreview({ preview, ownerKey, summary }: {
  preview: ReturnType<typeof useVariantPreview>; ownerKey: string; summary: VariantPreviewSummary;
}) {
  const [tier, setTier] = useState(0);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const { popup, trigger, dismiss } = preview;
  useLayoutEffect(() => {
    const node = popup.current;
    const anchor = trigger.current;
    if (!node || !anchor) return;
    const measure = () => {
      if (!node.isConnected || !anchor.isConnected) return;
      const viewport = window.visualViewport;
      const left = (viewport?.offsetLeft ?? 0) + 8, top = (viewport?.offsetTop ?? 0) + 8;
      const width = Math.max(0, (viewport?.width ?? document.documentElement.clientWidth) - 16);
      const height = Math.max(0, (viewport?.height ?? document.documentElement.clientHeight) - 16);
      const right = left + width, bottom = top + height;
      const target = anchor.getBoundingClientRect();
      const gap = 6;
      const areas = [
        { left, top: Math.max(top, target.bottom + gap), width, height: bottom - Math.max(top, target.bottom + gap), side: "below" },
        { left, top, width, height: Math.min(bottom, target.top - gap) - top, side: "above" },
        { left: Math.max(left, target.right + gap), top, width: right - Math.max(left, target.right + gap), height, side: "right" },
        { left, top, width: Math.min(right, target.left - gap) - left, height, side: "left" },
      ];
      for (const area of areas) {
        if (area.width < 160 || area.height <= 0) continue;
        const candidateWidth = Math.min(480, area.width);
        node.style.width = `${candidateWidth}px`;
        const box = node.getBoundingClientRect();
        if (box.height > area.height || box.width > area.width) continue;
        const x = Math.max(area.left, Math.min(target.left, area.left + area.width - box.width));
        const y = area.side === "above" ? area.top + area.height - box.height
          : area.side === "below" ? area.top : Math.max(area.top, Math.min(target.top, bottom - box.height));
        setPlacement(previous => previous && previous.left === x && previous.top === y && previous.width === candidateWidth
          ? previous : { left: x, top: y, width: candidateWidth });
        return;
      }
      // Shorter ordinary excerpts retain every field and every complete risk sentence.
      // Never clip text or turn this unfocusable tooltip into a scroll container.
      if (tier < excerptLimits.length - 1) { setPlacement(null); setTier(tier + 1); }
      else dismiss(); // There is no usable adjacent area in this viewport.
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    observer.observe(anchor);
    document.fonts?.addEventListener("loadingdone", measure);
    return () => {
      observer.disconnect();
      document.fonts?.removeEventListener("loadingdone", measure);
    };
  }, [popup, trigger, dismiss, summary, tier]);

  if (typeof document === "undefined") return null;
  return createPortal(<div ref={popup} id={preview.id} role="tooltip" className="variant-preview"
    data-variant-preview-owner={ownerKey} data-variant-preview-excerpt-limit={excerptLimits[tier]}
    style={{ left: placement?.left ?? 0, top: placement?.top ?? 0, width: placement?.width ?? 480,
      visibility: placement ? "visible" : "hidden" }} {...preview.popupProps}>
    <strong className="variant-preview-title">已加载规格摘要</strong>
    <p className="variant-preview-note">摘要节选，完整信息见卡片</p>
    <section data-variant-preview-original><strong className="variant-preview-label">原记录规格</strong>
      <dl className="variant-preview-fields">{summary.fields.map(field => <div key={field.id}>
        <dt>{field.label}：</dt><dd data-variant-preview-field={field.id}>{previewExcerpt(field.text, excerptLimits[tier])}</dd>
      </div>)}</dl>
    </section>
    <section data-variant-preview-identity><strong className="variant-preview-label">本次加载的身份状态</strong>
      <p>{previewExcerpt(summary.identity, identityLimits[tier])}</p>
    </section>
    {summary.risks.length ? <ul className="variant-preview-risks" data-variant-preview-risks>
      {summary.risks.map(risk => <li key={risk.id} data-variant-preview-risk={risk.id}>{risk.text}</li>)}
    </ul> : null}
  </div>, document.body);
}
