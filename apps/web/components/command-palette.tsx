"use client";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "./icons";

export type CommandItem = { id: string; label: string; hint?: string; run: () => void };

/** 轻量命令面板：Ctrl/⌘+K 唤起，子串过滤，方向键 + Enter 执行，Esc / 点击遮罩关闭。
 * a11y（第61轮圆桌 G3）：打开时记录先前焦点，关闭时归还（命令自身 focus 时优先命令焦点）。 */
export default function CommandPalette({ open, commands, onClose }: { open: boolean; commands: CommandItem[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const id = useId();
  const listboxId = `${id}-listbox`;
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const focusFrame = useRef<number | null>(null);
  const closing = useRef(false);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter(command => command.label.toLowerCase().includes(needle) || (command.hint ? command.hint.toLowerCase().includes(needle) : false));
  }, [commands, query]);
  const activeIndex = filtered.length ? Math.max(0, Math.min(active, filtered.length - 1)) : -1;
  const optionId = (index: number) => `${id}-option-${index}`;
  const cancelFocusFrame = () => {
    if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current);
    focusFrame.current = null;
  };
  const closePalette = () => {
    if (closing.current) return;
    closing.current = true;
    cancelFocusFrame();
    // Exit the modal layer before commands focus a field or open another dialog.
    dialog.current?.close();
    onClose();
  };
  useEffect(() => {
    const node = dialog.current;
    if (!open || !node) return;
    closing.current = false;
    restoreFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setQuery(""); setActive(0);
    if (!node.open) node.showModal();
    focusFrame.current = requestAnimationFrame(() => {
      focusFrame.current = null;
      if (node.isConnected && node.open && !closing.current && node.contains(document.activeElement)) input.current?.focus();
    });
    return () => {
      cancelFocusFrame();
      if (node.open) node.close();
      const previous = restoreFocus.current;
      // Native close normally restores focus; preserve any command's new target.
      if (previous?.isConnected && (document.activeElement === document.body || node.contains(document.activeElement))) previous.focus({ preventScroll: true });
      restoreFocus.current = null;
    };
  }, [open]);
  useEffect(() => { setActive(previous => Math.max(0, Math.min(previous, filtered.length - 1))); }, [filtered.length]);
  useEffect(() => {
    if (!open) return;
    const option = list.current?.querySelectorAll<HTMLElement>(".palette-option")[activeIndex];
    option?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open, filtered]);
  if (!open) return null;
  const runCommand = (index: number) => {
    const command = filtered[index];
    if (!command || closing.current) return;
    closePalette();
    command.run();
  };
  return <dialog ref={dialog} className="palette-backdrop" aria-label="命令面板" aria-modal="true"
    onCancel={event => { event.preventDefault(); closePalette(); }}
    onClick={event => { if (event.target === event.currentTarget) closePalette(); }}
    onKeyDown={event => {
      if (event.nativeEvent.isComposing) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); event.stopPropagation(); closePalette();
      } else if (event.key === "Escape") {
        event.preventDefault(); event.stopPropagation(); closePalette();
      } else if (event.key === "Tab") {
        // Keep the combobox's two Tab stops inside the modal, including focus
        // placed on a non-tabbable option by a pointer or assistive technology.
        const optionFocused = event.target instanceof Element && !!event.target.closest(".palette-option");
        if (optionFocused || event.target === event.currentTarget || event.shiftKey && event.target === input.current || !event.shiftKey && event.target === closeButton.current) {
          event.preventDefault();
          (event.shiftKey ? closeButton.current : input.current)?.focus();
        }
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (filtered.length) setActive(Math.max(0, Math.min(activeIndex + (event.key === "ArrowDown" ? 1 : -1), filtered.length - 1)));
        input.current?.focus();
      } else if (event.key === "Enter" && (event.target === input.current || event.target instanceof Element && event.target.closest(".palette-option"))) {
        event.preventDefault(); runCommand(activeIndex);
      }
    }}>
    <div className="command-palette">
      <div className="palette-input-row">
        <Icon name="search" size={16} />
        <input ref={input} role="combobox" aria-expanded="true" aria-controls={listboxId} aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined} aria-autocomplete="list" aria-label="搜索命令" autoComplete="off" spellCheck={false}
          value={query} placeholder="跳转视图或执行操作…"
          onChange={event => { setQuery(event.target.value); setActive(0); }} />
        <button ref={closeButton} type="button" className="palette-close" aria-label="关闭命令面板" onClick={closePalette}><kbd aria-hidden="true">Esc</kbd><Icon name="close" size={16} /></button>
      </div>
      <div className="palette-list">
        <div id={listboxId} role="listbox" aria-label="命令列表" ref={list}>
        {filtered.map((command, index) => <button type="button" role="option" id={optionId(index)} aria-selected={index === activeIndex} tabIndex={-1} key={command.id}
          className={["palette-option", index === activeIndex ? "active" : ""].filter(Boolean).join(" ")}
          onPointerEnter={() => setActive(index)}
          onFocus={() => setActive(index)}
          onClick={() => runCommand(index)}>
          <span>{command.label}</span>
          {command.hint ? <small>{command.hint}</small> : null}
        </button>)}
        </div>
        {!filtered.length ? <p className="palette-empty" role="status">没有匹配的命令。</p> : null}
      </div>
    </div>
  </dialog>;
}
