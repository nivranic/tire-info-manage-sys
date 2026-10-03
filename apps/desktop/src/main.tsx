import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { setApiTransport, tireApi } from "@tire/api-client";
import Workbench from "../../web/components/workbench";
import { OfflineLibraryEntry } from "../../web/components/offline-library";
import { DesktopDeviceAiEntry } from "./device-ai-panel";
import { createNativePlatform, createNativeTransport, DesktopError, externalLink, openNativeExternal, type DesktopStatus } from "./native-platform";
import "../../web/app/globals.css";
import "./styles.css";

const nativePlatform = createNativePlatform(invoke);
const nativeTransport = createNativeTransport(invoke);
let reportSessionFailure: ((error: DesktopError) => void) | undefined;
setApiTransport(async (path, init) => {
  if (!isTauri()) throw new DesktopError("desktop_unavailable");
  try { return await nativeTransport(path, init); }
  catch (cause) {
    if (cause instanceof DesktopError && /^(SESSION_|INVALID_SESSION_)/.test(cause.code)) reportSessionFailure?.(cause);
    throw cause;
  }
});

function validStatus(status: DesktopStatus): boolean {
  if (status.session_store !== "os_secure_store" || !status.session_persistent || status.error) return false;
  try {
    const url = new URL(status.api_base_url);
    return url.protocol === "http:" && url.hostname === "127.0.0.1" && !url.username && !url.password && url.pathname === "/" && !url.search && !url.hash;
  } catch { return false; }
}

function DesktopApp() {
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [phase, setPhase] = useState<"connecting" | "ready" | "failed">("connecting");
  const [error, setError] = useState("");
  const [linkError, setLinkError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [resetRequested, setResetRequested] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const sessionEpoch = useRef(0);

  const failSession = useCallback((cause: DesktopError) => {
    setError(cause.message);
    setPhase("failed");
  }, []);

  useEffect(() => {
    reportSessionFailure = failSession;
    return () => { if (reportSessionFailure === failSession) reportSessionFailure = undefined; };
  }, [failSession]);

  useEffect(() => {
    const controller = new AbortController();
    const epoch = ++sessionEpoch.current;
    const current = () => !controller.signal.aborted && sessionEpoch.current === epoch;
    setPhase("connecting"); setError(""); setStatus(null); setLinkError("");
    void (async () => {
      try {
        if (!isTauri()) throw new DesktopError("desktop_unavailable");
        if (resetRequested) { try { await invoke("reset_session"); } finally { window.dispatchEvent(new Event("tire-offline-owner-changed")); } }
        if (!current()) return;
        const initial = await invoke<DesktopStatus>("desktop_status");
        if (!current()) return;
        if (!validStatus(initial)) throw new DesktopError(initial.error || "SESSION_STORE_UNAVAILABLE");
        await tireApi.health(controller.signal);
        if (!current()) return;
        const connected = await invoke<DesktopStatus>("desktop_status");
        if (!current()) return;
        if (!validStatus(connected)) throw new DesktopError(connected.error || "SESSION_STORE_UNAVAILABLE");
        setStatus(connected); setPhase("ready");
      } catch (cause) {
        if (current()) { setError(cause instanceof DesktopError ? cause.message : new DesktopError(cause).message); setPhase("failed"); }
      }
    })();
    return () => controller.abort();
  }, [attempt, resetRequested]);

  useEffect(() => {
    const capture = (event: MouseEvent) => {
      const anchor = event.composedPath().find(node => node instanceof HTMLAnchorElement) as HTMLAnchorElement | undefined;
      if (!anchor) return;
      const link = externalLink(anchor.getAttribute("href") || "");
      if (link.action === "internal") return;
      event.preventDefault(); event.stopPropagation();
      if (event.type === "auxclick" && event.button !== 1) return;
      setLinkError("");
      if (link.action === "blocked") { setLinkError(new DesktopError("invalid_external_url").message); return; }
      void openNativeExternal(invoke, link.url!).catch(cause => setLinkError(cause instanceof DesktopError ? cause.message : new DesktopError("external_open_failed").message));
    };
    document.addEventListener("click", capture, true);
    document.addEventListener("auxclick", capture, true);
    return () => { document.removeEventListener("click", capture, true); document.removeEventListener("auxclick", capture, true); };
  }, []);

  function reconnect(reset = false) {
    setConfirmReset(false); setPhase("connecting"); setResetRequested(reset); setAttempt(value => value + 1);
  }

  return <div className="desktop-root">
    <header className="desktop-bar" aria-label="桌面连接与安全会话">
      <strong>胎迹 <span>桌面工作台</span></strong>
      <span className={`desktop-connection ${phase}`} role="status">{phase === "ready" ? "本机 API 已连接 · 系统安全会话" : phase === "connecting" ? "正在连接本机 API…" : "本机连接未就绪"}</span>
      <OfflineLibraryEntry platform={nativePlatform} onlineEnabled={phase === "ready"} /><DesktopDeviceAiEntry platform={nativePlatform} online={phase === "ready"} /><details className="desktop-settings"><summary>连接与会话</summary><div>
        <p>API：{status?.api_base_url || "等待安全连接检查"}</p>
        <p>会话仅存储在操作系统凭据库，独立于 Web 浏览器；本机 API 服务须另外启动。</p>
        <p>重置后将进入新会话，旧会话私有报告可能无法再访问。设备离线资料会锁定并保留密文，需单独确认查看旧归属历史。重置不会删除后端工作区数据。</p>
        {confirmReset ? <p className="desktop-reset-actions"><span>确认重置本机安全会话？</span><button type="button" onClick={() => reconnect(true)}>确认重置</button><button type="button" onClick={() => setConfirmReset(false)}>保留当前会话</button></p> : <button type="button" disabled={phase === "connecting"} onClick={() => setConfirmReset(true)}>重置本机安全会话</button>}
      </div></details>
    </header>
    {linkError ? <div className="desktop-link-error" role="alert">{linkError}<button type="button" onClick={() => setLinkError("")}>关闭提示</button></div> : null}
    {phase === "ready" && status ? <Workbench key={attempt} platform={nativePlatform} pwa={false} /> : <main className="desktop-connect-screen">
      <section className="desktop-connect-card" aria-labelledby="desktop-connect-title"><span className="desktop-eyebrow">LOCAL RESEARCH WORKSPACE</span><h1 id="desktop-connect-title">{phase === "connecting" ? "正在准备本机工作台" : "本机工作台尚未连接"}</h1>
        <p>桌面应用通过本机 API 读取来源、证据与工作区记录。连接成功后继续使用同一套工作台。</p>
        {phase === "connecting" ? <p className="desktop-progress" role="status">正在核对本机服务与系统安全会话…</p> : <><p className="desktop-error" role="alert">{error}</p><button type="button" className="desktop-retry" onClick={() => reconnect()}>重新检查连接</button></>}
        <dl><div><dt>本机服务</dt><dd>请先按项目说明启动 API；默认使用本机 8000 端口。</dd></div><div><dt>安全会话</dt><dd>本轮面向 Windows 与 macOS，使用凭据管理器或钥匙串；安全存储不可用时停止连接，不会回退到明文保存。</dd></div><div><dt>文件与外部链接</dt><dd>下载先校验再选择保存位置；来源网页通过系统浏览器打开。</dd></div></dl>
      </section>
    </main>}
  </div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><DesktopApp /></StrictMode>);
