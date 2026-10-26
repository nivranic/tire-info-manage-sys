/** R124 synthetic document only: real Web boundary, nested boundaries and controls. */
import { StrictMode, useEffect } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import WebThemeBoundary from "../apps/web/components/web-theme-boundary";
import ThemePreferenceControl from "../apps/web/components/theme-preference-control";
import { WorkbenchThemeBoundary, useThemePreferences } from "../apps/web/components/theme-preferences";

interface WebThemeQa {
  mount: () => void;
  unmount: () => void;
  nestedCallbacks: string[];
  mounts: number;
  cleanups: number;
  originalMeta: HTMLMetaElement | null;
  retainedInput: HTMLInputElement | null;
}

declare global { interface Window { webThemeQA: WebThemeQa } }

let root: Root | null = null;
const qa: WebThemeQa = {
  mount, unmount, nestedCallbacks: [], mounts: 0, cleanups: 0,
  originalMeta: document.head.querySelector('meta[name="theme-color"]'), retainedInput: null,
};
window.webThemeQA = qa;
const nestedCallback = (brightness: "light" | "dark") => qa.nestedCallbacks.push(brightness);

function Inner({ outer }: { outer: ReturnType<typeof useThemePreferences> }) {
  const inner = useThemePreferences();
  useEffect(() => { qa.mounts++; return () => { qa.cleanups++; }; }, []);
  return <main id="web-theme-fixture">
    <h1>Web theme-color 组件验证</h1>
    <p>仅合成文档和真实主题组件；不代表浏览器栏、PWA安装或原生系统效果。</p>
    <ThemePreferenceControl />
    <label htmlFor="retained-input">保留中的输入</label>
    <input id="retained-input" defaultValue="" />
    <output id="theme-state" data-ready={String(inner.ready)} data-shared={String(inner === outer)}
      data-preference={inner.appearance.preference} data-palette={inner.appearance.palette}>
      {inner.appearance.preference} / {inner.appearance.palette}
    </output>
  </main>;
}

function Fixture() {
  const outer = useThemePreferences();
  return <WorkbenchThemeBoundary onThemeChange={nestedCallback}>
    <WorkbenchThemeBoundary onThemeChange={nestedCallback}><Inner outer={outer} /></WorkbenchThemeBoundary>
  </WorkbenchThemeBoundary>;
}

function mount() {
  if (root) return;
  root = createRoot(document.getElementById("root")!);
  flushSync(() => root!.render(<StrictMode><WebThemeBoundary><Fixture /></WebThemeBoundary></StrictMode>));
}

function unmount() {
  const previous = root;
  root = null;
  if (previous) flushSync(() => previous.unmount());
}

mount();
