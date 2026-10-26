/** Pure helpers shared by the reader and its target tests. No browser storage. */
export type RawEvidenceKind = "vehicle" | "capture" | "quarantine";
export class RawEvidenceViewChanged extends Error {
  constructor() { super("读取原件的上下文已变化，请重新读取。"); this.name = "RawEvidenceViewChanged"; }
}
export class RawEvidenceDisplayChanged extends Error {
  constructor() { super("原件的完整展示依据已变化，未保存。请重新读取并核对。"); this.name = "RawEvidenceDisplayChanged"; }
}

/** Closed JSON: sorted object keys, ordered arrays, distinct null, no omitted values. */
export function rawEvidenceCanonical(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${Array.from(value, rawEvidenceCanonical).join(",")}]`;
  if (value && typeof value === "object" && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${rawEvidenceCanonical((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  throw new RawEvidenceDisplayChanged();
}
function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object") { for (const item of Object.values(value)) deepFreeze(item); Object.freeze(value); }
  return value;
}
export function freezeRawEvidenceDisplay<T>(endpoint: RawEvidenceKind, metadata: T): Readonly<{ endpoint: RawEvidenceKind; metadata: T; canonical: string }> {
  const canonical = rawEvidenceCanonical({ endpoint, metadata });
  const copy = JSON.parse(canonical) as { endpoint: RawEvidenceKind; metadata: T };
  return Object.freeze({ ...deepFreeze(copy), canonical });
}
export function assertRawEvidenceDisplay(display: { canonical: string }, endpoint: RawEvidenceKind, metadata: unknown): void {
  if (display.canonical !== rawEvidenceCanonical({ endpoint, metadata })) throw new RawEvidenceDisplayChanged();
}
/** Existing Golden/evaluation inputs remain the authority for the selected capture. */
export function assertRawEvidenceInput(metadata: unknown, input: unknown): void {
  if (!metadata || typeof metadata !== "object" || !input || typeof input !== "object") throw new RawEvidenceDisplayChanged();
  const actual = metadata as Record<string, unknown>, expected = input as Record<string, unknown>;
  const fields = ["query_id", "source_id", "target_kind", "query", "source_url", "content_type", "raw_hash", "byte_count", "observed_at", "storage_kind"];
  if (actual.id !== expected.capture_id || actual.parser_version !== expected.original_parser_version
    || fields.some(key => rawEvidenceCanonical(actual[key]) !== rawEvidenceCanonical(expected[key]))) throw new RawEvidenceDisplayChanged();
}

export interface RawEvidenceOwner {
  ready: boolean;
  ownerEpoch: number;
  ownerSignal: AbortSignal;
  isCurrentOwner(epoch: number): boolean;
  selection: string;
  transportEpoch: number;
}
export function createRawEvidenceOperations(current: () => RawEvidenceOwner,
  observeTransport: (revoke: () => void) => () => void) {
  let generation = 0;
  let active: { controller: AbortController; finish(): void } | null = null;
  const invalidate = () => { generation++; const previous = active; active = null; previous?.controller.abort(); previous?.finish(); };
  const begin = () => {
    invalidate();
    const owner = current(), revision = generation, controller = new AbortController();
    let stopped = false, stopTransport = () => {};
    const finish = () => {
      if (stopped) return; stopped = true;
      owner.ownerSignal.removeEventListener("abort", revoke); stopTransport();
      if (active?.controller === controller) active = null;
    };
    const revoke = () => { controller.abort(); finish(); };
    const fence = { assertCurrent() {
      const now = current();
      if (controller.signal.aborted || owner.ownerSignal.aborted || revision !== generation || !now.ready || !owner.ready
        || !now.isCurrentOwner(owner.ownerEpoch) || now.ownerEpoch !== owner.ownerEpoch || now.ownerSignal !== owner.ownerSignal
        || now.selection !== owner.selection || now.transportEpoch !== owner.transportEpoch) throw new RawEvidenceViewChanged();
    } };
    active = { controller, finish };
    owner.ownerSignal.addEventListener("abort", revoke, { once: true });
    stopTransport = observeTransport(revoke);
    try { fence.assertCurrent(); } catch (cause) { revoke(); throw cause; }
    return { controller, fence, finish };
  };
  return { begin, invalidate };
}

export interface BrowserRawDownload {
  blob: Blob; filename: string; signal?: AbortSignal; assertCurrent?: () => void;
}
export interface BrowserDownloadEnvironment {
  createObjectURL(blob: Blob): string;
  revokeObjectURL(url: string): void;
  createLink(): { href: string; download: string; click(): void; remove(): void };
  appendLink(link: ReturnType<BrowserDownloadEnvironment["createLink"]>): void;
  deferRevoke(callback: () => void): void;
}
export function deliverBrowserRawDownload(download: BrowserRawDownload, environment: BrowserDownloadEnvironment): { saved: boolean } {
  const check = () => { if (download.signal?.aborted) throw new DOMException("操作已取消", "AbortError"); download.assertCurrent?.(); if (download.signal?.aborted) throw new DOMException("操作已取消", "AbortError"); };
  check();
  const url = environment.createObjectURL(download.blob);
  let link: ReturnType<BrowserDownloadEnvironment["createLink"]> | undefined, delivered = false;
  try {
    link = environment.createLink(); link.href = url; link.download = download.filename;
    environment.appendLink(link); check(); link.click(); delivered = true;
    return { saved: true };
  } finally {
    try { link?.remove(); } finally {
      if (delivered) environment.deferRevoke(() => environment.revokeObjectURL(url));
      else environment.revokeObjectURL(url);
    }
  }
}
