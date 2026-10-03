"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./icons";

export type CommandItem = { id: string; label: string; hint?: string; run: () => void };

/** 轻量命令面板：Ctrl/⌘+K 唤起，子串过滤，方向键 + Enter 执行，Esc / 点击遮罩关闭。 */
export default function CommandPalette({ open, commands, onClose }: { open: boolean; commands: CommandItem[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter(command => command.label.toLowerCase().includes(needle) || (command.hint ? command.hint.toLowerCase().includes(needle) : false));
  }, [commands, query]);
  useEffect(() => { if (open) { setQuery(""); setActive(0); requestAnimationFrame(() => input.current?.focus()); } }, [open]);
  useEffect(() => { setActive(0); }, [query]);
  useEffect(() => {
    if (!open) return;
    const option = list.current?.querySelectorAll<HTMLElement>(".palette-option")[active];
    option?.scrollIntoView({ block: "nearest" });
  }, [active, open, query]);
  if (!open) return null;
  const runCommand = (index: number) => {
    const command = filtered[index];
    if (!command) return;
    onClose();
    command.run();
  };
  return <div className="palette-backdrop" onClick={onClose}>
    <div className="command-palette" role="presentation" onClick={event => event.stopPropagation()}>
      <div className="palette-input-row">
        <Icon name="search" size={16} />
        <input ref={input} role="combobox" aria-expanded="true" aria-controls="palette-listbox" aria-autocomplete="list" aria-label="搜索命令" autoComplete="off" spellCheck={false}
          value={query} placeholder="跳转视图或执行操作…"
          onChange={event => setQuery(event.target.value)}
          onKeyDown={event => {
            if (event.key === "ArrowDown") { event.preventDefault(); setActive(previous => Math.min(previous + 1, filtered.length - 1)); }
            else if (event.key === "ArrowUp") { event.preventDefault(); setActive(previous => Math.max(previous - 1, 0)); }
            else if (event.key === "Enter") { event.preventDefault(); runCommand(active); }
            else if (event.key === "Escape") { event.preventDefault(); onClose(); }
          }} />
        <kbd>Esc</kbd>
      </div>
      <div className="palette-list" id="palette-listbox" role="listbox" aria-label="命令列表" ref={list}>
        {filtered.length ? filtered.map((command, index) => <button type="button" role="option" aria-selected={index === active} key={command.id}
          className={["palette-option", index === active ? "active" : ""].filter(Boolean).join(" ")}
          onPointerEnter={() => setActive(index)}
          onClick={() => runCommand(index)}>
          <span>{command.label}</span>
          {command.hint ? <small>{command.hint}</small> : null}
        </button>) : <p className="palette-empty">没有匹配的命令。</p>}
      </div>
    </div>
  </div>;
}
