"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { ChangeItem, Variant, WatchItem } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import type { ToastKind } from "./toast";

type WatchOwner = {
  epoch: number;
  signal: AbortSignal;
  isCurrentOwner: (epoch: number) => boolean;
  controller: AbortController;
  read: AbortController | null;
  operations: Map<string, AbortController>;
  revision: number;
  lastReadVersion: number;
  loaded: boolean;
  watches: WatchItem[];
};
type WatchState = {
  owner: WatchOwner | null;
  watches: WatchItem[];
  changes: ChangeItem[];
  watchError: string;
  changesError: string;
  loading: boolean;
  pending: string[];
};
const emptyState = (owner: WatchOwner | null = null): WatchState => ({
  owner, watches: [], changes: [], watchError: "", changesError: "", loading: !!owner, pending: [],
});
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求未完成，请重试。";

/** Private watch state follows an auth operation, including same-account revalidation. */
export function useOwnedWatch(changesVisible: boolean, onToast: (message: string, kind?: ToastKind) => void) {
  const { ready, ownerEpoch, ownerSignal, isCurrentOwner } = useWorkbenchAuth();
  const ownerRef = useRef<WatchOwner | null>(null);
  const [state, setState] = useState<WatchState>(() => emptyState());
  const [readVersion, setReadVersion] = useState(0);
  const current = useCallback((owner: WatchOwner | null): owner is WatchOwner => !!owner
    && ownerRef.current === owner && !owner.signal.aborted && !owner.controller.signal.aborted
    && owner.isCurrentOwner(owner.epoch), []);
  const updateState = useCallback((owner: WatchOwner, update: (previous: WatchState) => WatchState) => {
    setState(previous => current(owner) && previous.owner === owner ? update(previous) : previous);
  }, [current]);

  useLayoutEffect(() => {
    if (!ready || ownerSignal.aborted || !isCurrentOwner(ownerEpoch)) {
      ownerRef.current = null; setState(emptyState()); return;
    }
    const owner: WatchOwner = {
      epoch: ownerEpoch, signal: ownerSignal, isCurrentOwner, controller: new AbortController(),
      read: null, operations: new Map(), revision: 0, lastReadVersion: -1, loaded: false, watches: [],
    };
    ownerRef.current = owner; setState(emptyState(owner));
    const revoke = () => {
      owner.controller.abort(); owner.read?.abort();
      for (const operation of owner.operations.values()) operation.abort();
      owner.operations.clear(); owner.watches = [];
      // AuthProvider aborts synchronously, before React publishes the next epoch.
      if (ownerRef.current === owner) { ownerRef.current = null; setState(emptyState()); }
    };
    ownerSignal.addEventListener("abort", revoke, { once: true });
    if (ownerSignal.aborted) revoke();
    return () => { ownerSignal.removeEventListener("abort", revoke); revoke(); };
  }, [ready, ownerEpoch, ownerSignal, isCurrentOwner]);

  useEffect(() => {
    const owner = ownerRef.current;
    if (!current(owner) || owner.operations.size) return;
    // Leaving the view cancels its read; already loaded card markers need no duplicate read.
    if (!changesVisible && owner.loaded && owner.lastReadVersion === readVersion) return;
    const controller = new AbortController();
    owner.read?.abort(); owner.read = controller; owner.lastReadVersion = readVersion;
    const revision = owner.revision;
    const valid = () => current(owner) && owner.read === controller && !controller.signal.aborted
      && owner.revision === revision;
    updateState(owner, previous => ({ ...previous, loading: true, watchError: "", changesError: changesVisible ? "" : previous.changesError }));
    // StrictMode's setup/cleanup replay can revoke the first read before dispatch.
    queueMicrotask(() => {
      if (!valid()) return;
      void Promise.allSettled([
        tireApi.watchlists(controller.signal),
        changesVisible ? tireApi.changes(controller.signal) : Promise.resolve(null),
      ]).then(([watchResult, changesResult]) => {
        if (!valid()) return;
        if (watchResult.status === "fulfilled") {
          owner.watches = watchResult.value.items; owner.loaded = true;
        }
        updateState(owner, previous => ({
          ...previous, watches: owner.watches, loading: false,
          watchError: watchResult.status === "rejected" ? errorText(watchResult.reason) : "",
          changes: changesVisible && changesResult.status === "fulfilled" && changesResult.value ? changesResult.value.items : previous.changes,
          changesError: changesVisible ? changesResult.status === "rejected" ? errorText(changesResult.reason) : "" : previous.changesError,
        }));
      });
    });
    return () => {
      controller.abort();
      if (owner.read === controller) {
        owner.read = null;
        updateState(owner, previous => ({ ...previous, loading: false }));
      }
    };
  }, [ready, ownerEpoch, ownerSignal, isCurrentOwner, changesVisible, readVersion, current, updateState]);

  const ownerReady = ready && !ownerSignal.aborted && isCurrentOwner(ownerEpoch);
  const visible = ownerReady && state.owner?.epoch === ownerEpoch && state.owner.signal === ownerSignal && current(state.owner) ? state : null;
  const watchUnavailableReason = !ownerReady ? "账户尚未确认，暂不能修改关注。"
    : visible?.watchError ? "当前账户的关注记录未能读取，暂不能修改关注。请在我的关注中重试。"
    : !visible?.owner?.loaded ? "正在加载当前账户的关注记录，请稍候。" : undefined;

  async function toggleWatch(variant: Variant) {
    // Retain the rendered owner: an old menu/confirmation cannot authorize a new owner.
    const owner = visible?.owner ?? null;
    if (watchUnavailableReason || !current(owner) || !owner.loaded || owner.operations.has(variant.id)) return;
    const controller = new AbortController();
    owner.operations.set(variant.id, controller);
    owner.revision++; owner.read?.abort(); owner.read = null;
    updateState(owner, previous => ({ ...previous, loading: false, pending: [...owner.operations.keys()] }));
    const valid = () => current(owner) && !controller.signal.aborted && owner.operations.get(variant.id) === controller;
    const existing = owner.watches.find(item => item.variant_id === variant.id);
    try {
      if (existing) {
        await tireApi.unwatch(existing.id, controller.signal);
        if (!valid()) return;
        owner.watches = owner.watches.filter(item => item.id !== existing.id);
      } else {
        const added = await tireApi.watch(variant.id, controller.signal);
        if (!valid()) return;
        owner.watches = [...owner.watches.filter(item => item.variant_id !== variant.id), { ...added, variant: added.variant || variant }];
      }
      const watches = owner.watches;
      updateState(owner, previous => ({ ...previous, watches }));
      if (valid()) onToast(existing ? "已取消关注。" : "已加入关注。可在我的关注中单独创建监控规则。", "success");
    } catch (error) {
      if (valid()) onToast(errorText(error), "error");
    } finally {
      if (valid()) {
        owner.operations.delete(variant.id); owner.revision++;
        updateState(owner, previous => ({ ...previous, pending: [...owner.operations.keys()] }));
        // Reconcile an accepted or uncertain write only after all current writes settle.
        if (!owner.operations.size) setReadVersion(value => value + 1);
      }
    }
  }

  function updateWatchedVariants(update: (variant: Variant) => Variant) {
    const owner = visible?.owner ?? null;
    if (!current(owner)) return;
    owner.revision++; owner.read?.abort(); owner.read = null;
    owner.watches = owner.watches.map(item => item.variant ? { ...item, variant: update(item.variant) } : item);
    const watches = owner.watches;
    updateState(owner, previous => ({ ...previous, watches, loading: false }));
    setReadVersion(value => value + 1);
  }

  return {
    watches: visible?.watches ?? [], changes: visible?.changes ?? [],
    watchError: visible?.watchError ?? "", changesError: visible?.changesError ?? "",
    watchLoading: visible?.loading ?? false, pendingWatch: visible?.pending ?? [],
    ownerReady, watchUnavailableReason, toggleWatch, updateWatchedVariants,
    refreshWatches: () => { if (current(visible?.owner ?? null)) setReadVersion(value => value + 1); },
  };
}
