"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { DeviceFallbackQueryKind } from "@tire/domain-types";
import { createDeviceOffer, deviceFailure, type LocalFallbackOffer } from "./local-fallback-controller";
import LocalFallbackPanel from "./local-fallback-panel";
import { useWorkbenchPlatform } from "./workbench-platform";

/** Ordinary-page lifecycle only. Permission and answer filtering stay in the host. */
export function useDeviceQueryFallback(kind: DeviceFallbackQueryKind, sourceId: string) {
  const { offline } = useWorkbenchPlatform();
  const [offer, setOffer] = useState<LocalFallbackOffer | null>(null), [error, setError] = useState("");
  const generation = useRef(0), alive = useRef(true);
  const clear = useCallback(() => { generation.current++; setOffer(null); setError(""); }, []);
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; }; }, []);
  useEffect(() => { window.addEventListener("tire-offline-owner-changed", clear); return () => window.removeEventListener("tire-offline-owner-changed", clear); }, [clear]);
  const show = useCallback(async (query: unknown, accessGeneration: number, cause: unknown, attemptId: string, sourceName: string, current: () => boolean = () => true) => {
    if (!deviceFailure(cause, sourceId)) return;
    const version = generation.current;
    try {
      const next = await createDeviceOffer(offline, kind, query, [], sourceId, accessGeneration, cause, attemptId, sourceName);
      if (!alive.current || version !== generation.current || !current()) return;
      setOffer(next); if (!next) setError("设备来源权限尚未在本次运行确认。请先主动刷新设备固定来源元数据，再发起新的普通查询；独立历史库仍可查看。");
    } catch (cause) { if (alive.current && version === generation.current && current()) setError(cause instanceof Error ? cause.message : "设备回退未完成。"); }
  }, [kind, offline, sourceId]);
  return { clear, show, panel: <>{error ? <p className="inline-error" role="status">{error}</p> : null}{offer && offline ? <LocalFallbackPanel key={offer.intent.attempt_id} offer={offer} storage={offline} onClose={clear} /> : null}</> };
}
