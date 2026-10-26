/** Isolated real React fixture. No API client, provider, router or database. */
import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import CommandPalette, { type CommandItem } from "../apps/web/components/command-palette";
import { consumeMobileBack } from "../apps/mobile/src/back-navigation";

declare global {
  interface Window {
    paletteQA: {
      runs: string[];
      backgroundClicks: number;
      backRoutes: number;
      setCount: (count: number) => void;
      setOpen: (open: boolean) => void;
      remountOpen: () => void;
      unmount: () => void;
      mobileBack: () => boolean;
    };
  }
}

function Fixture() {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(true);
  const [count, setCount] = useState(4);
  const business = useRef<HTMLDialogElement>(null);
  const runs = useRef<string[]>([]);
  const commands: CommandItem[] = [
    { id: "first", label: "跳转查询", hint: "Query", run: () => { runs.current.push("first"); } },
    { id: "second", label: "跳转证据", hint: "Evidence", run: () => { runs.current.push("second"); } },
    { id: "focus", label: "聚焦尺寸", hint: "Focus", run: () => { runs.current.push("focus"); document.getElementById("command-focus-target")?.focus(); } },
    { id: "dialog", label: "打开业务弹窗", hint: "Dialog", run: () => { runs.current.push("dialog"); business.current?.showModal(); document.getElementById("business-input")?.focus(); } },
  ].slice(0, count);

  useEffect(() => {
    // Match the existing workbench shortcut guard; the palette owns closing itself.
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (document.querySelector("dialog[open]")) return;
        setOpen(previous => !previous);
      }
    };
    window.addEventListener("keydown", onKey);
    window.paletteQA = {
      runs: runs.current,
      backgroundClicks: 0,
      backRoutes: 0,
      setCount: value => flushSync(() => setCount(value)),
      setOpen: value => flushSync(() => setOpen(value)),
      remountOpen: () => {
        flushSync(() => { setMounted(false); setOpen(false); });
        flushSync(() => { setMounted(true); setOpen(true); });
      },
      unmount: () => flushSync(() => setMounted(false)),
      mobileBack: () => consumeMobileBack(document, () => { window.paletteQA.backRoutes++; return true; }),
    };
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return <main className="offline-portal" data-theme="light" style={{ minHeight: "100dvh", padding: 16 }}>
    <button id="opener" type="button" onClick={() => setOpen(true)}>打开命令面板</button>
    <button id="background" type="button" onClick={() => { window.paletteQA.backgroundClicks++; }}>背景操作</button>
    <label>命令焦点目标<input id="command-focus-target" /></label>
    {mounted ? <CommandPalette open={open} commands={commands} onClose={() => setOpen(false)} /> : null}
    <dialog ref={business} aria-label="业务弹窗" onCancel={event => { event.preventDefault(); business.current?.close(); }}>
      <label>业务输入<input id="business-input" /></label>
      <button type="button" onClick={() => business.current?.close()}>关闭业务弹窗</button>
    </dialog>
  </main>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><Fixture /></StrictMode>);
