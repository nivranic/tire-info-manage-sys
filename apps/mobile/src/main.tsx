import { StrictMode, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Capacitor, registerPlugin } from "@capacitor/core";
import { setApiTransport, tireApi } from "@tire/api-client";
import { createNativeTransport, externalLink, NativeError, openNativeExternal } from "@tire/native-client";
import Workbench from "../../web/components/workbench";
import { OfflineLibraryEntry } from "../../web/components/offline-library";
import { consumeMobileBack } from "./back-navigation";
import { restoreWorkbenchDialogs, suspendWorkbenchDialogs, type SuspendedWorkbenchDialogs } from "./modal-lifecycle";
import { MobileDeviceAiEntry } from "./device-ai-panel";
import { createMobileInvoke, createMobilePlatform, mobileError, validateMobileStatus, type MobileStatus, type TireNativePlugin } from "./native-platform";
import "../../web/app/globals.css";
import "./styles.css";

const native = registerPlugin<TireNativePlugin>("TireNative");
const invoke = createMobileInvoke(native);
const transport = createNativeTransport(invoke);
let connected = false;
let connectionGeneration = 0;
let pauseConnection: ((error: NativeError) => void) | undefined;
let workbenchBack: (() => boolean) | undefined;
const platform = {
  ...createMobilePlatform(invoke),
  registerBackHandler(handler: () => boolean) {
    workbenchBack = handler;
    return () => { if (workbenchBack === handler) workbenchBack = undefined; };
  },
  onThemeChange(theme: "light" | "dark") {
    document.documentElement.dataset.mobileTheme = theme;
    void native.setSystemTheme({ theme }).catch(() => { /* Theme chrome does not change request safety or form state. */ });
  },
};

setApiTransport(async (path, init) => {
  if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") throw new NativeError("MOBILE_UNAVAILABLE");
  if (!connected && path !== "/health") throw new NativeError("session_unavailable");
  const generation = connectionGeneration;
  try { return await transport(path, init); }
  catch (cause) {
    if (generation === connectionGeneration && cause instanceof NativeError && /^(SESSION_|INVALID_SESSION_|API_UNAVAILABLE$|API_HEALTH_FAILED$|RELEASE_API_NOT_CONFIGURED$)/.test(cause.code)) {
      connected = false; pauseConnection?.(cause);
    }
    throw cause;
  }
});

function MobileApp() {
  const [status, setStatus] = useState<MobileStatus | null>(null);
  const [phase, setPhase] = useState<"connecting" | "ready" | "failed">("connecting");
  const [mounted, setMounted] = useState(false);
  const [workspaceEpoch, setWorkspaceEpoch] = useState(0);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<NativeError | null>(null);
  const [linkError, setLinkError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const connection = useRef<AbortController | null>(null);
  const mountedRef = useRef(false);
  const phaseRef = useRef(phase);
  const settingsRef = useRef<HTMLDialogElement>(null);
  const workbenchRef = useRef<HTMLDivElement>(null);
  const suspendedDialogs = useRef<SuspendedWorkbenchDialogs | null>(null);
  phaseRef.current = phase;

  function failConnection(cause: NativeError) {
    if (workbenchRef.current) suspendedDialogs.current = suspendWorkbenchDialogs(workbenchRef.current, suspendedDialogs.current);
    setError(cause); setPhase("failed");
  }

  const checkConnection = useCallback(async (reset = false) => {
    // A late failure from an earlier connection must not pause this new check or session.
    connectionGeneration += 1;
    connection.current?.abort();
    const controller = new AbortController(); connection.current = controller;
    const current = () => connection.current === controller && !controller.signal.aborted;
    setChecking(true); setError(null);
    if (!mountedRef.current || reset) setPhase("connecting");
    if (reset) {
      suspendedDialogs.current = null;
      connected = false; mountedRef.current = false; setMounted(false); setWorkspaceEpoch(value => value + 1);
    }
    try {
      if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") throw new NativeError("MOBILE_UNAVAILABLE");
      if (reset) { try { await native.resetSession({}); } finally { window.dispatchEvent(new Event("tire-offline-owner-changed")); } }
      if (!current()) return;
      const before = await native.status({});
      if (!current()) return;
      setStatus(before); validateMobileStatus(before);
      await tireApi.health(controller.signal);
      if (!current()) return;
      const after = await native.status({});
      if (!current()) return;
      validateMobileStatus(after); setStatus(after);
      connected = true; mountedRef.current = true; setMounted(true); setPhase("ready");
    } catch (cause) {
      if (current()) { connected = false; failConnection(mobileError(cause)); }
    } finally {
      if (current()) { setChecking(false); connection.current = null; }
    }
  }, []);

  useEffect(() => {
    const fail = (cause: NativeError) => failConnection(cause);
    pauseConnection = fail;
    void checkConnection();
    return () => {
      connection.current?.abort();
      if (pauseConnection === fail) pauseConnection = undefined;
    };
  }, [checkConnection]);

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    let disposed = false;
    const handles: { remove: () => Promise<void> }[] = [];
    const remember = (handle: { remove: () => Promise<void> }) => {
      if (disposed) void handle.remove(); else handles.push(handle);
    };
    void native.addListener("backRequested", ({ id }) => {
      if (disposed) return;
      const handled = settingsRef.current?.open
        ? (settingsRef.current.dispatchEvent(new Event("cancel", { cancelable: true })), true)
        : document.querySelector("dialog.offline-dialog[open]") ? consumeMobileBack(document) : phaseRef.current === "ready" && consumeMobileBack(document, workbenchBack);
      void native.resolveBack({ id, handled }).catch(() => { /* Native expires stale requests without exiting. */ });
    }).then(remember).catch(() => { /* The native host keeps unacknowledged back requests safe. */ });
    void native.addListener("resume", () => {
      if (!disposed) void checkConnection();
    }).then(remember).catch(() => { /* Manual connection retry remains available. */ });
    return () => { disposed = true; for (const handle of handles) void handle.remove(); };
  }, [checkConnection]);

  useLayoutEffect(() => {
    const dialog = settingsRef.current;
    if (settingsOpen) dialog?.showModal(); else dialog?.close();
  }, [settingsOpen]);

  useLayoutEffect(() => {
    const root = workbenchRef.current;
    if (!root) return;
    if (phase === "ready") {
      if (!settingsOpen) {
        restoreWorkbenchDialogs(root, suspendedDialogs.current);
        suspendedDialogs.current = null;
      }
      return;
    }
    const suspend = () => { suspendedDialogs.current = suspendWorkbenchDialogs(root, suspendedDialogs.current); };
    suspend();
    // A pending component effect may reopen a modal while the workspace is hidden.
    const observer = new MutationObserver(suspend);
    observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["open"] });
    return () => observer.disconnect();
  }, [phase, mounted, settingsOpen]);

  useEffect(() => {
    const capture = (event: MouseEvent) => {
      const anchor = event.composedPath().find(node => node instanceof HTMLAnchorElement) as HTMLAnchorElement | undefined;
      if (!anchor) return;
      const link = externalLink(anchor.getAttribute("href") || "");
      if (link.action === "internal") return;
      event.preventDefault(); event.stopPropagation();
      if (event.type === "auxclick" && event.button !== 1) return;
      setLinkError("");
      if (link.action === "blocked") { setLinkError(new NativeError("invalid_external_url").message); return; }
      void openNativeExternal(invoke, link.url!).catch(cause => setLinkError(mobileError(cause).message));
    };
    document.addEventListener("click", capture, true); document.addEventListener("auxclick", capture, true);
    return () => { document.removeEventListener("click", capture, true); document.removeEventListener("auxclick", capture, true); };
  }, []);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    let height = viewport.height;
    const resize = () => {
      const input = document.activeElement instanceof HTMLInputElement || document.activeElement instanceof HTMLTextAreaElement || document.activeElement instanceof HTMLSelectElement;
      if (!input) height = Math.max(height, viewport.height);
      document.documentElement.dataset.keyboardOpen = String(input && height - viewport.height > 140);
    };
    const rotate = () => { height = viewport.height; resize(); };
    viewport.addEventListener("resize", resize); window.addEventListener("orientationchange", rotate); document.addEventListener("focusout", resize);
    return () => { viewport.removeEventListener("resize", resize); window.removeEventListener("orientationchange", rotate); document.removeEventListener("focusout", resize); };
  }, []);

  function closeSettings() { setConfirmReset(false); setSettingsOpen(false); }

  return <div className="mobile-native-root">
    <header className="mobile-connection-bar" aria-label="移动端连接状态"><span className={`mobile-connection ${phase}`} role="status"><i />{phase === "ready" ? "本机调试已连接" : phase === "connecting" ? "正在检查安全连接…" : "连接未就绪"}</span><OfflineLibraryEntry platform={platform} onlineEnabled={phase === "ready"} /><MobileDeviceAiEntry plugin={native} online={phase === "ready"} platform={platform} /><button type="button" onClick={() => setSettingsOpen(true)} aria-haspopup="dialog">连接与会话</button></header>
    {linkError ? <div className="mobile-link-error" role="alert"><span>{linkError}</span><button type="button" onClick={() => setLinkError("")}>关闭</button></div> : null}
    {mounted ? <div ref={workbenchRef} className="mobile-workbench" aria-hidden={phase !== "ready"} inert={phase !== "ready"}><Workbench key={workspaceEpoch} platform={platform} pwa={false} /></div> : null}
    {phase !== "ready" ? <main className="mobile-connect-screen"><section aria-labelledby="mobile-connect-title"><span className="eyebrow">LOCAL RESEARCH WORKSPACE</span><h1 id="mobile-connect-title">{phase === "connecting" ? "正在准备移动工作台" : "移动工作台尚未连接"}</h1><p>{mounted ? "当前操作内容已保留，恢复安全连接后可继续核对。不会自动重试写入操作。" : "在移动端核对同一套轮胎参数、来源和历史证据。连接本机调试通道后进入工作台。"}</p>
      {error ? <p className="mobile-connect-error" role="alert">{error.message}</p> : <p role="status">正在检查原生通道与安全会话…</p>}
      {phase === "failed" ? <button className="mobile-primary" type="button" disabled={checking} onClick={() => void checkConnection()}>重新检查连接</button> : null}
      <p className="mobile-connect-note">本轮只支持 Android 调试包通过 ADB 本机通道连接；API 服务须另行启动。正式移动端服务与 iOS 尚未交付。此前明确保存到本应用的资料可从“设备离线资料库”独立查看。</p></section></main> : null}
    <dialog ref={settingsRef} className="mobile-settings-dialog" aria-labelledby="mobile-settings-title" onCancel={event => { event.preventDefault(); closeSettings(); }}>
      <header><h2 id="mobile-settings-title">连接与安全会话</h2><button type="button" onClick={closeSettings}>关闭</button></header>
      <div className="mobile-settings-content"><p><strong>{status?.mode === "release-unconfigured" ? "正式移动端服务尚未配置" : "Android · 本机调试通道"}</strong></p><p>会话通过 Android Keystore 保护，独立于浏览器和桌面端。安全存储不可用时停止连接。</p><p>当前调试包使用固定本机端口，经 ADB reverse 连接开发机 API；页面不能指定其他地址。</p><p>下载前校验原始字节，再由系统选择保存位置。来源网页通过系统浏览器打开。</p>
        <button className="mobile-secondary" type="button" disabled={checking} onClick={() => void checkConnection()}>{checking ? "正在检查…" : "重新检查连接"}</button>
        <section className="mobile-reset-section"><h3>重置本机安全会话</h3><p>重置会关闭当前编辑内容，并进入新会话。旧会话私有关注和报告将无法继续访问；设备离线资料会锁定并保留密文，需单独确认查看旧归属历史；后端工作区数据不会被删除。</p>{confirmReset ? <div className="mobile-reset-actions"><button className="mobile-primary" type="button" disabled={checking} onClick={() => { closeSettings(); void checkConnection(true); }}>确认重置</button><button className="mobile-secondary" type="button" onClick={() => setConfirmReset(false)}>保留当前会话</button></div> : <button className="mobile-secondary" type="button" disabled={checking} onClick={() => setConfirmReset(true)}>重置本机会话</button>}</section>
      </div>
    </dialog>
  </div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><MobileApp /></StrictMode>);
