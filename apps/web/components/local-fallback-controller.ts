import type { LocalFallbackDecideRequest, LocalFallbackGrant, LocalFallbackIntent, LocalFallbackResult, OfflineHostList, OfflineStorage } from "@tire/domain-types";
import { OfflineError } from "./offline-crypto";
import { validateFallbackIntent, validateFallbackReceipt, validateFallbackResult } from "./local-fallback-values";
import { ApiTransportError, cloneExactDeviceValue, createDeviceFallbackIntent, validateDeviceFallbackGrant, validateDeviceFallbackResult } from "@tire/api-client";
import type { DeviceFallbackIntentV2, DeviceFallbackDecideRequestV2, DeviceFallbackAuthorizeRequest, DeviceFallbackGrantV2, DeviceFallbackResultV2, DeviceFallbackQueryKind, TireFilter } from "@tire/domain-types";

/** A device-only lifecycle. No server consent, QueryResult or online action conversion. */
export class LocalFallbackController {
  private generation = 0;
  private grant: LocalFallbackGrant | null = null;
  private grantV2: DeviceFallbackGrantV2 | null = null;
  private busy = false;
  constructor(private readonly storage: OfflineStorage) {}
  invalidate(): void {
    this.generation++; this.busy = false;
    const grant = this.grant; this.grant = null;
    if (grant) void this.storage.revokeFallback?.({ grant_id: grant.id }).catch(() => {});
    const next = this.grantV2; this.grantV2 = null;
    if (next) void this.storage.revokeFallbackV2?.({ grant_id: next.id }).catch(() => {});
  }
  async metadata(): Promise<OfflineHostList> { return this.storage.list(); }
  private async consumeV2(grant: DeviceFallbackGrantV2, request: DeviceFallbackAuthorizeRequest, generation: number): Promise<DeviceFallbackResultV2 | null> {
    validateDeviceFallbackGrant(grant, request, "allowed");
    if (generation !== this.generation) { await this.storage.revokeFallbackV2?.({ grant_id: grant.id }); return null; }
    this.grantV2 = grant;
    const value = await this.storage.consumeFallbackV2!({ grant_id: grant.id, intent: request.intent });
    if (this.grantV2?.id === grant.id) this.grantV2 = null;
    if (generation !== this.generation) return null;
    validateDeviceFallbackResult(value, request);
    if (value.grant.id !== grant.id) throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
    return value;
  }
  async answerV2(request: DeviceFallbackDecideRequestV2): Promise<DeviceFallbackResultV2 | "denied" | null> {
    if (this.busy) throw new OfflineError("OFFLINE_FALLBACK_USED");
    if (!this.storage.decideFallbackV2 || !this.storage.consumeFallbackV2 || !this.storage.revokeFallbackV2) throw new OfflineError("OFFLINE_FALLBACK_UNSUPPORTED");
    request = cloneExactDeviceValue(request); const generation = this.generation; this.busy = true;
    try {
      const grant = await this.storage.decideFallbackV2(request);
      validateDeviceFallbackGrant(grant, request, request.decision === "deny" ? "denied" : "allowed");
      if (request.decision === "deny") return generation === this.generation ? "denied" : null;
      return await this.consumeV2(grant, request, generation);
    } finally { if (generation === this.generation) this.busy = false; }
  }
  async authorizeV2(request: DeviceFallbackAuthorizeRequest): Promise<DeviceFallbackResultV2 | "ask" | "denied" | null> {
    if (this.busy) throw new OfflineError("OFFLINE_FALLBACK_USED");
    if (!this.storage.authorizeFallback || !this.storage.consumeFallbackV2 || !this.storage.revokeFallbackV2) throw new OfflineError("OFFLINE_FALLBACK_UNSUPPORTED");
    request = cloneExactDeviceValue(request); const generation = this.generation; this.busy = true;
    try {
      const authorization = await this.storage.authorizeFallback(request);
      if (generation !== this.generation) { if (authorization.grant) await this.storage.revokeFallbackV2({ grant_id: authorization.grant.id }); return null; }
      if (authorization.schema !== "device-fallback-authorization@1") throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
      if (authorization.state === "ask" && authorization.grant === null) return "ask";
      if (authorization.state === "blocked" && authorization.grant === null) return "denied";
      if (authorization.state !== "allowed" || !authorization.grant) throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
      return await this.consumeV2(authorization.grant, request, generation);
    } finally { if (generation === this.generation) this.busy = false; }
  }
  async answer(request: LocalFallbackDecideRequest): Promise<LocalFallbackResult | "denied" | null> {
    if (this.busy) throw new OfflineError("OFFLINE_FALLBACK_USED");
    if (!this.storage.decideFallback || !this.storage.consumeFallback || !this.storage.revokeFallback) throw new OfflineError("OFFLINE_FALLBACK_UNSUPPORTED");
    validateFallbackIntent(request.intent); request = structuredClone(request);
    const generation = this.generation; this.busy = true;
    try {
      const grant = await this.storage.decideFallback(request);
      if (generation !== this.generation) { await this.storage.revokeFallback({ grant_id: grant.id }); return null; }
      validateFallbackReceipt(grant, request, request.decision === "deny" ? "denied" : "allowed");
      if (request.decision === "deny") {
        if (grant.state !== "denied") throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
        return "denied";
      }
      if (grant.state !== "allowed") throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
      this.grant = grant;
      const value = await this.storage.consumeFallback({ grant_id: grant.id, intent: request.intent });
      this.grant = null;
      if (generation !== this.generation) return null;
      if (value?.grant?.id !== grant.id) throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
      validateFallbackResult(value, request); return value;
    } finally { if (generation === this.generation) this.busy = false; }
  }
}
export type LocalFallbackOffer = { intent: LocalFallbackIntent | DeviceFallbackIntentV2; sourceName: string };
export function deviceFailure(cause: unknown, sourceId: string): DeviceFallbackIntentV2["failure"] | null {
  if (cause instanceof ApiTransportError) return { scope: "api_transport", reason: cause.code, query_id: null };
  if (!cause || typeof cause !== "object") return null;
  const value = cause as Record<string, unknown>;
  if (value.source_id !== sourceId || !["source_unavailable", "consent_required"].includes(String(value.data_state)) || typeof value.query_id !== "string" || !/^[0-9a-f-]{36}$/i.test(value.query_id)) return null;
  if (value.reason === "upstream_timeout" || value.reason === "upstream_network_error") return { scope: "source_response", reason: value.reason, query_id: value.query_id };
  const failure = value.fallback_failure as Record<string, unknown> | undefined;
  return failure && Object.keys(failure).length === 3 && failure.scope === "source_response" && failure.query_id === value.query_id && (failure.reason === "upstream_timeout" || failure.reason === "upstream_network_error") ? { scope: "source_response", reason: failure.reason, query_id: value.query_id } : null;
}
export async function createDeviceOffer(storage: OfflineStorage | undefined, kind: DeviceFallbackQueryKind, query: unknown, filters: readonly TireFilter[], sourceId: string, generation: number, cause: unknown, attemptId: string, sourceName: string): Promise<LocalFallbackOffer | null> {
  const failure = deviceFailure(cause, sourceId);
  if (!failure || !storage?.fallbackStatus) return null;
  const status = await storage.fallbackStatus();
  if (status.authority.state !== "last_observed") return null;
  const intent = await createDeviceFallbackIntent(kind, query, cloneExactDeviceValue([...filters]), sourceId, generation, failure, attemptId,
    { runtime_session_id: status.authority.runtime_session_id, authority_revision: status.authority.authority_revision });
  return { intent, sourceName };
}
