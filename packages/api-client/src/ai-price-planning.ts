import type { AIPricePlanningRequest, AIPricePlanningResult, AIPriceVersion,
  AIPriceVersionCreate, AIPriceVersionPage } from "@tire/domain-types";

type Send = <T>(path: string, init?: RequestInit) => Promise<T>;

/** Uses the existing authenticated transport. Decimal strings and caller retry keys pass through unchanged. */
export function createAiPricePlanningApi(send: Send) {
  return {
    aiPriceVersions: (signal?: AbortSignal, offset = 0, limit = 10) =>
      send<AIPriceVersionPage>(`/v1/ai/price-versions?${new URLSearchParams({ offset: String(offset), limit: String(limit) })}`, { signal }),
    aiPriceVersionCreate: (payload: AIPriceVersionCreate, key: string, signal?: AbortSignal) =>
      send<AIPriceVersion>("/v1/ai/price-versions", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
    aiPricePlanning: (payload: AIPricePlanningRequest, signal?: AbortSignal) =>
      send<AIPricePlanningResult>("/v1/ai/price-planning", { method: "POST", body: JSON.stringify(payload), signal }),
  };
}
