/** 三端共享的 hash 路由编解码（纯函数，无平台依赖）。
 *
 * 路由形如 `#/query`、`#/compare?ids=a,b`（≤4）、`#/query?size=245%2F40%20R20`。
 * 证据检查器、弹窗与查询草稿保持瞬态，不进入 URL（深链诚实边界）。
 */
export type RouteView = "query" | "vehicles" | "garage" | "compare" | "watch" | "sources";
export type RouteState = { view: RouteView; compareIds?: string[]; size?: string };

const ROUTE_VIEWS: readonly RouteView[] = ["query", "vehicles", "garage", "compare", "watch", "sources"];

export function parseRouteHash(hash: string): RouteState | null {
  const raw = hash.replace(/^#/, "");
  if (!raw.startsWith("/")) return null;
  const [path, queryString] = raw.split("?");
  const segment = path.slice(1);
  if (!segment || segment.includes("/") || !(ROUTE_VIEWS as readonly string[]).includes(segment)) return null;
  const params = new URLSearchParams(queryString || "");
  const compareIds = (params.get("ids") || "").split(",").map(value => value.trim()).filter(Boolean).slice(0, 4);
  const size = params.get("size")?.trim() || undefined;
  const view = segment as RouteView;
  return { view,
    ...(view === "compare" && compareIds.length ? { compareIds } : {}),
    ...(view === "query" && size ? { size } : {}) };
}

export function serializeRouteHash(state: RouteState): string {
  const params = new URLSearchParams();
  if (state.view === "compare" && state.compareIds?.length) params.set("ids", state.compareIds.join(","));
  if (state.view === "query" && state.size) params.set("size", state.size);
  const query = params.toString();
  return "#/" + state.view + (query ? "?" + query : "");
}
