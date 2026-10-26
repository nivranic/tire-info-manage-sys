/** Synthetic frontend host only: real theme controls and real Web body portals. */
import { StrictMode, useState } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { tireApi } from "@tire/api-client";
import type { OfflineReadResult, OfflineSlot, OfflineStorage } from "@tire/domain-types";
import OfflineLibraryDialog from "../apps/web/components/offline-library";
import DeviceAiDialog from "../apps/web/components/device-ai-panel";
import ThemePreferenceControl from "../apps/web/components/theme-preference-control";
import { ThemeProvider, WorkbenchThemeBoundary, useThemePreferences } from "../apps/web/components/theme-preferences";
import type { NativeBrightness } from "../apps/web/components/theme-preference-values";
import type { WorkbenchPlatform } from "../apps/web/components/workbench-platform";

interface ThemeQa {
  callbacks: { owner: "provider" | "nested-boundary"; brightness: NativeBrightness; mounted: boolean; preference: string | null }[];
  storageCalls: string[];
  mount: () => void;
  unmount: () => void;
}

declare global { interface Window { themeQA: ThemeQa } }

const instant = "2026-10-22T00:00:00.000Z";
const slot: OfflineSlot = {
  slot_id: "theme-ui-only-slot", generation: 1, package_id: "theme-ui-only-empty-material",
  sha256: "0".repeat(64), byte_count: 0, title: "主题验证合成本地资料槽", created_at: instant, installed_at: instant,
  privacy_class: "private", owner_scope_id: "theme-ui-only-owner", locked: false, previous_owner: false,
  counts: { garage_profiles: 0, watch_items: 0, recent_queries: 0, distinct_evidence: 0, searchable_documents: 1 },
};
const document: OfflineReadResult["document"] = {
  id: "theme-ui-only-document", category: "evidence", kind: "tire", member_key: "theme-ui-only-member",
  context_id: null, record_index: null, title: "仅用于显示本机问题字段的空载荷", text: "Synthetic UI fixture; no tire facts.",
  facets: { brand: null, model: null, size: null, source_id: null, campaign_number: null },
  membership: ["explicit"], privacy_class: "private", observed_at: instant, verified_at: null,
};

let root: Root | null = null;
const qa: ThemeQa = { callbacks: [], storageCalls: [], mount, unmount };
window.themeQA = qa;
const forbidden = async (): Promise<never> => { throw Error("theme_fixture_mutation_forbidden"); };
const offline: OfflineStorage = {
  async status() {
    qa.storageCalls.push("status");
    return { schema: "offline-host@1", available: true, state: "ready", storage: "indexeddb", profile_id: "theme-ui-only-profile",
      owner_epoch: 1, total_bytes: 0, max_store_bytes: 1024, max_package_bytes: 1024, max_slots: 1,
      encryption: "webcrypto", persistence: "best_effort", manual_updates: true, background_updates: false, error: null };
  },
  async list() {
    qa.storageCalls.push("list");
    return { schema: "offline-host@1", data_state: "local_snapshot", profile_id: "theme-ui-only-profile", owner_epoch: 1, items: [slot] };
  },
  async search(request) {
    qa.storageCalls.push("search");
    const items = request.query || request.kind && request.kind !== "tire" ? [] : [document];
    return { data_state: "local_snapshot", slot, items, total: items.length, offset: request.offset, limit: request.limit, has_more: false };
  },
  async read() {
    qa.storageCalls.push("read");
    return { data_state: "local_snapshot", slot, document, context: null, member: {
      key: "theme-ui-only-member", reference: { kind: "tire", snapshot_id: "theme-ui-only-snapshot", variant_id: "theme-ui-only-variant", verification_id: "theme-ui-only-verification" },
      member_reasons: [], privacy_class: "private", raw_included: false,
      source: { source_id: null, source_url: null, raw_hash: null, parser_version: null, parser_identity: null,
        observed_at: instant, verified_at: null, verification_id: null }, payload: {},
    } };
  },
  install: forbidden, remove: forbidden, unlockPreviousOwner: forbidden,
};
const platform: WorkbenchPlatform = { kind: "web", sessionLabel: "合成组件验证", offline, saveDownload: forbidden };
// The real dialog performs this optional mount-time budget read. No API endpoint is called.
tireApi.aiStatus = async () => { throw Error("theme_fixture_budget_unavailable"); };

function notify(owner: "provider" | "nested-boundary", brightness: NativeBrightness) {
  qa.callbacks.push({ owner, brightness, mounted: root !== null,
    preference: window.document.documentElement.getAttribute("data-theme-preference") });
}
const notifyProvider = (brightness: NativeBrightness) => notify("provider", brightness);
const notifyNested = (brightness: NativeBrightness) => notify("nested-boundary", brightness);

function Fixture() {
  const { appearance, ready } = useThemePreferences();
  const [portal, setPortal] = useState<"offline" | "ai" | null>(null);
  return <main id="theme-fixture" data-theme={appearance.palette}>
    <h1>主题偏好组件验证</h1>
    <p>合成本机空载荷；不验证业务事实、模型、生产工作台或原生系统栏。</p>
    <div className="qa-tools">
      <ThemePreferenceControl />
      <button id="open-offline" className="secondary-button" onClick={() => setPortal("offline")}>打开真实离线库</button>
      <button id="open-ai" className="secondary-button" onClick={() => setPortal("ai")}>打开真实设备 AI</button>
    </div>
    <output id="theme-state" data-ready={String(ready)} data-preference={appearance.preference}
      data-palette={appearance.palette} data-brightness={appearance.nativeBrightness}>{appearance.preference} / {appearance.palette}</output>
    <section className="qa-sample"><p id="qa-text">正文与边界可读性</p><p id="qa-muted" className="muted">次要文字仍需可读。</p>
      <a id="qa-link" className="accent" href="#theme-state">本地重点链接</a>
      <label className="review-checkbox"><input id="qa-checkbox" type="checkbox" /> 原生勾选框与文字状态</label>
      <p className="inline-error">示例错误：仅表示主题验证状态。</p><span className="tag success">示例成功</span>
    </section>
    {portal === "offline" ? <OfflineLibraryDialog platform={platform} onlineEnabled={false} onClose={() => setPortal(null)} /> : null}
    {portal === "ai" ? <DeviceAiDialog platform={platform} onClose={() => setPortal(null)} /> : null}
  </main>;
}

function mount() {
  if (root) return;
  root = createRoot(window.document.getElementById("root")!);
  flushSync(() => root!.render(<StrictMode><ThemeProvider onThemeChange={notifyProvider}>
    <WorkbenchThemeBoundary onThemeChange={notifyNested}><WorkbenchThemeBoundary onThemeChange={notifyNested}>
      <Fixture />
    </WorkbenchThemeBoundary></WorkbenchThemeBoundary>
  </ThemeProvider></StrictMode>));
}
function unmount() {
  const previous = root;
  root = null;
  if (previous) flushSync(() => previous.unmount());
}
mount();
