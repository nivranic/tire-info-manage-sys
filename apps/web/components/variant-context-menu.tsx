"use client";

import { useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

export type VariantMenuAction = {
  id: "evidence" | "compare" | "watch" | "review" | "lifecycle" | "ai" | "garage";
  label: string;
  disabledReason?: string;
  checked?: boolean;
  run: () => void;
};

export type VariantMenuAnchor =
  | { kind: "pointer"; clientX: number; clientY: number }
  | { kind: "trigger" };

export type VariantMenuCloseReason = "escape" | "tab" | "outside" | "action" | "viewport" | "replace";

type Placement = { left: number; top: number; maxWidth: number; maxHeight: number };

/** Only the open specification card mounts this view; business actions stay in VariantCard. */
export default function VariantContextMenu({ id, label, actions, anchor, triggerRef, onClose }: {
  id: string;
  label: string;
  actions: readonly VariantMenuAction[];
  anchor: VariantMenuAnchor;
  triggerRef: RefObject<HTMLButtonElement | null>;
  onClose: (reason: VariantMenuCloseReason) => void;
}) {
  const menu = useRef<HTMLDivElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const closing = useRef(false);
  const initialFocus = useRef(false);
  const closeRef = useRef(onClose);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [active, setActive] = useState(0);

  useLayoutEffect(() => { closeRef.current = onClose; }, [onClose]);

  const close = (reason: VariantMenuCloseReason) => {
    if (closing.current) return;
    closing.current = true;
    closeRef.current(reason);
    // showEvidence records activeElement synchronously. Never give it a disappearing item.
    if (["escape", "tab", "action"].includes(reason) && triggerRef.current?.isConnected) {
      triggerRef.current.focus({ preventScroll: true });
      if (reason !== "tab") triggerRef.current.scrollIntoView({ block: "nearest", behavior: "instant" });
    }
  };

  const focusItem = (index: number) => {
    if (closing.current) return;
    const item = items.current[index], viewport = menu.current;
    if (!item || !viewport) return;
    setActive(index);
    item.focus({ preventScroll: true });
    const itemBox = item.getBoundingClientRect(), box = viewport.getBoundingClientRect();
    if (itemBox.top < box.top + 4) viewport.scrollTop -= box.top + 4 - itemBox.top;
    else if (itemBox.bottom > box.bottom - 4) viewport.scrollTop += itemBox.bottom - box.bottom + 4;
  };

  useLayoutEffect(() => {
    const node = menu.current;
    if (!node) return;
    const measure = () => {
      if (closing.current || !node.isConnected) return;
      const viewport = window.visualViewport;
      const leftEdge = (viewport?.offsetLeft ?? 0) + 8;
      const topEdge = (viewport?.offsetTop ?? 0) + 8;
      const maxWidth = Math.max(0, (viewport?.width ?? document.documentElement.clientWidth) - 16);
      const maxHeight = Math.max(0, (viewport?.height ?? document.documentElement.clientHeight) - 16);
      node.style.maxWidth = `${maxWidth}px`;
      node.style.maxHeight = `${maxHeight}px`;
      const box = node.getBoundingClientRect(), trigger = triggerRef.current?.getBoundingClientRect();
      if (anchor.kind === "trigger" && !trigger) { closeRef.current("viewport"); return; }
      const x = anchor.kind === "pointer" ? anchor.clientX : trigger!.right - box.width;
      const below = anchor.kind === "pointer" ? anchor.clientY : trigger!.bottom + 4;
      const above = anchor.kind === "pointer" ? anchor.clientY - box.height : trigger!.top - box.height - 4;
      const bottomEdge = topEdge + maxHeight;
      const left = Math.max(leftEdge, Math.min(x, leftEdge + maxWidth - box.width));
      const top = Math.max(topEdge, Math.min(below + box.height <= bottomEdge ? below : above, bottomEdge - box.height));
      setPlacement(previous => previous && previous.left === left && previous.top === top
        && previous.maxWidth === maxWidth && previous.maxHeight === maxHeight
        ? previous : { left, top, maxWidth, maxHeight });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    const outside = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && !node.contains(target) && !triggerRef.current?.contains(target)) close("outside");
    };
    const scroll = (event: Event) => {
      if (event.target instanceof Node && node.contains(event.target)) return;
      close("viewport");
    };
    const viewportChanged = () => close("viewport");
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", outside, true);
    document.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", viewportChanged);
    window.addEventListener("blur", viewportChanged);
    window.visualViewport?.addEventListener("resize", viewportChanged);
    window.visualViewport?.addEventListener("scroll", viewportChanged);
    return () => {
      observer.disconnect();
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", outside, true);
      document.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", viewportChanged);
      window.removeEventListener("blur", viewportChanged);
      window.visualViewport?.removeEventListener("resize", viewportChanged);
      window.visualViewport?.removeEventListener("scroll", viewportChanged);
      // Actions/dialogs may already own focus. Unmount must never restore it again.
    };
  }, [anchor, triggerRef]);

  useLayoutEffect(() => {
    if (!placement || initialFocus.current || closing.current) return;
    initialFocus.current = true;
    focusItem(0);
  }, [placement]);

  const runAction = (index: number) => {
    const action = actions[index];
    if (!action || action.disabledReason || closing.current) return;
    close("action");
    action.run();
  };

  if (typeof document === "undefined") return null;
  return createPortal(<div ref={menu} id={id} className="variant-context-menu" role="menu" aria-label={label}
    style={{ left: placement?.left ?? 0, top: placement?.top ?? 0, maxWidth: placement?.maxWidth,
      maxHeight: placement?.maxHeight, visibility: placement ? "visible" : "hidden" }}
    onContextMenu={event => event.preventDefault()}
    onKeyDown={event => {
      if (event.defaultPrevented || event.nativeEvent.isComposing) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        close("action"); // Let the existing Workbench shortcut open the command palette.
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault(); event.stopPropagation(); close("escape");
      } else if (event.key === "Tab") {
        close("tab"); // Browser continues from the stable card trigger, without a modal trap.
      } else if (!event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
        const current = items.current.findIndex(item => item === document.activeElement);
        const index = current < 0 ? active : current;
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault(); event.stopPropagation();
          const next = event.key === "Home" ? 0 : event.key === "End" ? actions.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + actions.length) % actions.length;
          focusItem(next);
        } else if (event.key === "Enter" || event.key === " ") {
          event.preventDefault(); event.stopPropagation();
          if (!event.repeat) runAction(index);
        }
      }
    }}>
    {actions.map((action, index) => <button key={action.id} type="button"
      ref={node => { items.current[index] = node; }}
      className={`variant-context-item${active === index ? " is-active" : ""}`}
      data-variant-menu-action={action.id} role={action.checked === undefined ? "menuitem" : "menuitemcheckbox"}
      aria-checked={action.checked} aria-disabled={action.disabledReason ? true : undefined}
      aria-describedby={action.disabledReason ? `${id}-${action.id}-reason` : undefined}
      tabIndex={active === index ? 0 : -1}
      onFocus={() => setActive(index)}
      onPointerMove={event => { if (event.pointerType === "mouse" && document.activeElement !== event.currentTarget) focusItem(index); }}
      onClick={() => runAction(index)}>
      <span className="variant-context-check" aria-hidden="true">{action.checked ? "✓" : ""}</span>
      <span className="variant-context-item-text">{action.label}
        {action.disabledReason ? <small id={`${id}-${action.id}-reason`}>{action.disabledReason}</small> : null}
      </span>
    </button>)}
  </div>, document.body);
}
