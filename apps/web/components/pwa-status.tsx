"use client";

import { useEffect, useState } from "react";
import { OfflineLibraryEntry } from "./offline-library";

type InstallEvent = Event & { prompt(): Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };

export default function PwaStatus() {
  const [offline, setOffline] = useState(false);
  const [install, setInstall] = useState<InstallEvent | null>(null);
  const [update, setUpdate] = useState<ServiceWorker | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const connection = () => setOffline(!navigator.onLine || !!document.querySelector('meta[name="tire-offline-shell"]'));
    connection();
    window.addEventListener("online", connection);
    window.addEventListener("offline", connection);
    if (!("serviceWorker" in navigator)) return () => { window.removeEventListener("online", connection); window.removeEventListener("offline", connection); };
    let disposed = false;
    let registration: ServiceWorkerRegistration | undefined;
    let installing: ServiceWorker | null = null;
    const prompt = (event: Event) => { event.preventDefault(); setInstall(event as InstallEvent); };
    const installed = () => setInstall(null);
    const ready = () => {
      if (!disposed && registration?.waiting && navigator.serviceWorker.controller) setUpdate(registration.waiting);
    };
    const found = () => { installing = registration?.installing || null; installing?.addEventListener("statechange", ready); };
    let hadController = !!navigator.serviceWorker.controller;
    const changed = () => {
      if (hadController) location.reload();
      else hadController = true;
    };
    if (process.env.NODE_ENV === "production") {
      window.addEventListener("beforeinstallprompt", prompt);
      window.addEventListener("appinstalled", installed);
      navigator.serviceWorker.addEventListener("controllerchange", changed);
      void navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).then(value => {
        registration = value;
        if (disposed) return;
        ready(); registration.addEventListener("updatefound", found); found();
      }).catch(() => { if (!disposed && !navigator.serviceWorker.controller) setError("离线应用外壳尚未就绪；当前仍可在线使用。"); });
    } else {
      // Do not let an earlier production installation retain a stale shell in dev.
      void navigator.serviceWorker.getRegistrations().then(async registrations => {
        for (const item of registrations) {
          const script = item.active?.scriptURL || item.waiting?.scriptURL || item.installing?.scriptURL;
          if (script && new URL(script).origin === location.origin && new URL(script).pathname === "/sw.js") await item.unregister();
        }
        if ("caches" in window) for (const key of await caches.keys()) if (key.startsWith("tire-shell-")) await caches.delete(key);
      }).catch(() => { /* Development is always network-only. */ });
    }
    return () => {
      disposed = true;
      window.removeEventListener("online", connection); window.removeEventListener("offline", connection);
      window.removeEventListener("beforeinstallprompt", prompt); window.removeEventListener("appinstalled", installed);
      navigator.serviceWorker.removeEventListener("controllerchange", changed);
      registration?.removeEventListener("updatefound", found); installing?.removeEventListener("statechange", ready);
    };
  }, []);
  async function requestInstall() {
    if (!install || busy) return;
    setBusy(true); setError("");
    try { await install.prompt(); await install.userChoice; setInstall(null); }
    catch { setError("未完成安装，可通过浏览器菜单再次安装。"); }
    finally { setBusy(false); }
  }
  if (!offline && !install && !update && !error) return null;
  return <section className="pwa-status" aria-label="应用安装与连接状态">
    {offline ? <p role="status">当前网络核验不可用。应用外壳可打开；您可主动进入设备离线资料库查看先前明确保存的历史。在线查询不会自动使用这些旧参数。</p> : null}
    {error ? <p role="status">{error}</p> : null}
    <div className="variant-actions">{offline ? <OfflineLibraryEntry /> : null}{offline ? <button type="button" className="text-button" onClick={() => location.reload()}>恢复连接后重新载入</button> : null}{install && !offline ? <button type="button" className="text-button" disabled={busy} onClick={() => void requestInstall()}>安装胎迹</button> : null}{update ? <button type="button" className="text-button" onClick={() => update.postMessage({ type: "ACTIVATE_UPDATE" })}>更新应用并重新载入</button> : null}</div>
  </section>;
}
