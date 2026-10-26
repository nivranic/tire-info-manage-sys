"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, apiTransportAuthorityEpoch, observeApiTransportAuthority, tireApi } from "@tire/api-client";
import type { VehicleEvidenceV2, RawCaptureEvidenceV2, QuarantineEvidenceV2 } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { useWorkbenchPlatform } from "./workbench-platform";
import { assertRawEvidenceDisplay, createRawEvidenceOperations, freezeRawEvidenceDisplay, rawEvidenceCanonical,
  RawEvidenceDisplayChanged, RawEvidenceViewChanged, type RawEvidenceKind, type RawEvidenceOwner } from "./raw-evidence-v2-context";

type MetadataByKind = { vehicle: VehicleEvidenceV2; capture: RawCaptureEvidenceV2; quarantine: QuarantineEvidenceV2 };
export type RawEvidenceMetadata = MetadataByKind[RawEvidenceKind];
type Display<T> = ReturnType<typeof freezeRawEvidenceDisplay<T>>;
export interface RawEvidenceReader<T extends RawEvidenceMetadata = RawEvidenceMetadata> {
  metadata: T | null;
  loading: boolean;
  downloading: boolean;
  error: string;
  notice: string;
  reload(): void;
  cancel(): void;
  abortOperations(): void;
  download(): Promise<void>;
}
const errorText = (cause: unknown) => cause instanceof RawEvidenceViewChanged || cause instanceof RawEvidenceDisplayChanged
  ? cause.message : cause instanceof ApiError ? `原件读取未完成（HTTP ${cause.status}），请重新读取。`
    : "原件未通过读取或完整性校验，请重新读取。";

/** All six entry points use one fence through SDK reads and browser/native delivery. */
export function useRawEvidenceV2<K extends RawEvidenceKind>({ kind, id, selectionKey = "", enabled = true, validate }: {
  kind: K; id: string; selectionKey?: string; enabled?: boolean; validate?: (metadata: MetadataByKind[K]) => void;
}): RawEvidenceReader<MetadataByKind[K]> {
  type Metadata = MetadataByKind[K];
  const auth = useWorkbenchAuth(), platform = useWorkbenchPlatform();
  const [revision, setRevision] = useState(0);
  const selection = rawEvidenceCanonical([kind, id, selectionKey, revision, enabled]);
  const transportEpoch = apiTransportAuthorityEpoch();
  const stamp = rawEvidenceCanonical([selection, auth.ownerEpoch, transportEpoch]);
  const current = useRef<RawEvidenceOwner>({ ...auth, selection, transportEpoch });
  const operations = useRef<ReturnType<typeof createRawEvidenceOperations> | null>(null);
  if (!operations.current) operations.current = createRawEvidenceOperations(() => current.current, revoke => observeApiTransportAuthority(revoke));
  const previous = current.current;
  current.current = { ready: auth.ready && enabled && !!id, ownerEpoch: auth.ownerEpoch, ownerSignal: auth.ownerSignal,
    isCurrentOwner: auth.isCurrentOwner, selection, transportEpoch: apiTransportAuthorityEpoch() };
  // Selection and ABA revoke synchronously during the render that changes them.
  if (previous.selection !== selection || previous.ownerEpoch !== auth.ownerEpoch || previous.ownerSignal !== auth.ownerSignal
    || previous.transportEpoch !== transportEpoch || previous.ready !== current.current.ready) operations.current.invalidate();
  const validator = useRef(validate); validator.current = validate;
  const displayed = useRef<{ stamp: string; display: Display<Metadata> } | null>(null);
  const [state, setState] = useState<{ stamp: string; display: Display<Metadata> | null; loading: boolean; downloading: boolean; error: string; notice: string }>({ stamp, display: null, loading: false, downloading: false, error: "", notice: "" });
  const abortOperations = () => { operations.current!.invalidate(); setState(value => ({ ...value, loading: false, downloading: false })); };
  const cancel = () => {
    operations.current!.invalidate(); displayed.current = null;
    setState({ stamp, display: null, loading: false, downloading: false, error: "", notice: "" });
  };
  const reload = () => { cancel(); setRevision(value => value + 1); };
  useLayoutEffect(() => {
    const stop = observeApiTransportAuthority(() => {
      operations.current!.invalidate(); displayed.current = null;
      setState(value => ({ ...value, display: null, loading: false, downloading: false, error: "连接上下文已变化，请重新读取原件。", notice: "" }));
    });
    return () => { operations.current!.invalidate(); displayed.current = null; stop(); };
  }, []);
  useEffect(() => {
    displayed.current = null;
    if (!id || !enabled || !auth.ready) return;
    let operation: ReturnType<ReturnType<typeof createRawEvidenceOperations>["begin"]>;
    try { operation = operations.current!.begin(); } catch { return; }
    setState({ stamp, display: null, loading: true, downloading: false, error: "", notice: "" });
    const read = kind === "vehicle" ? tireApi.vehicleEvidenceV2 : kind === "capture" ? tireApi.captureEvidenceV2 : tireApi.quarantineEvidenceV2;
    void (async () => {
      try {
        const metadata = await read(id, operation.fence, operation.controller.signal) as Metadata;
        operation.fence.assertCurrent(); validator.current?.(metadata); operation.fence.assertCurrent();
        const display = freezeRawEvidenceDisplay(kind, metadata);
        operation.fence.assertCurrent(); displayed.current = { stamp, display };
        setState({ stamp, display, loading: false, downloading: false, error: "", notice: "" });
      } catch (cause) {
        try { operation.fence.assertCurrent(); } catch { return; }
        displayed.current = null;
        setState({ stamp, display: null, loading: false, downloading: false, error: errorText(cause), notice: "" });
      } finally { operation.finish(); }
    })();
    return () => { operation.controller.abort(); operation.finish(); };
  // Host validation is read through a live ref, while selectionKey binds its immutable scope.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp, auth.ready, enabled, id, kind]);

  async function download() {
    const basis = displayed.current;
    if (!basis || basis.stamp !== stamp || !current.current.ready || basis.display.metadata.body_encoding !== "binary") return;
    let operation: ReturnType<ReturnType<typeof createRawEvidenceOperations>["begin"]>;
    try { operation = operations.current!.begin(); } catch { return; }
    setState(value => ({ ...value, downloading: true, error: "", notice: "" }));
    try {
      const read = kind === "vehicle" ? tireApi.vehicleEvidenceContent : kind === "capture" ? tireApi.captureEvidenceContent : tireApi.quarantineEvidenceContent;
      const content = await read(id, operation.fence, operation.controller.signal);
      operation.fence.assertCurrent(); assertRawEvidenceDisplay(basis.display, kind, content.metadata);
      validator.current?.(content.metadata as Metadata); operation.fence.assertCurrent();
      const result = await platform.saveDownload({ blob: content.blob, filename: `raw-evidence-${content.metadata.raw_hash}.pdf`,
        signal: operation.controller.signal, assertCurrent: operation.fence.assertCurrent });
      operation.fence.assertCurrent();
      setState(value => ({ ...value, downloading: false, notice: result.saved
        ? platform.kind === "web" ? "已交给浏览器下载，请在下载列表核对文件。" : "宿主已完成保存，请核对目标文件。"
        : "已取消保存，未报告保存成功。" }));
    } catch (cause) {
      try { operation.fence.assertCurrent(); } catch { return; }
      // A changed complete basis permanently removes this display's save eligibility.
      if (cause instanceof RawEvidenceDisplayChanged) {
        displayed.current = null; setState(value => ({ ...value, display: null, downloading: false, error: cause.message, notice: "" }));
      } else setState(value => ({ ...value, downloading: false, error: cause instanceof ApiError ? errorText(cause)
        : "保存未完成；未报告保存成功。请重新核对后重试。", notice: "" }));
    } finally { operation.finish(); }
  }
  const visible = current.current.ready && state.stamp === stamp;
  return { metadata: visible ? state.display?.metadata ?? null : null, loading: visible && state.loading,
    downloading: visible && state.downloading, error: visible ? state.error : "", notice: visible ? state.notice : "", reload, cancel, abortOperations, download };
}

const show = (value: unknown) => value === null || value === undefined || value === "" ? "未提供（未解析）" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
/** No iframe, object, embedded PDF, or server-supplied content link. */
export function RawEvidenceV2View({ reader, locators }: { reader: RawEvidenceReader; locators?: readonly string[] }) {
  const value = reader.metadata;
  const frozenLocators = value && "vehicle_payload" in value ? value.vehicle_payload.fitments.map(item => item.evidence_locator)
    : locators;
  const technical = value ? Object.fromEntries(Object.entries(value).filter(([key]) => key !== "body")) : null;
  return <div className="raw-evidence-v2">
    {reader.error ? <p className="inline-error" role="alert">{reader.error}</p> : null}
    {reader.notice ? <p role="status">{reader.notice}</p> : null}
    {reader.loading ? <p role="status">正在读取原件与校验依据…</p> : null}
    {!value ? <button type="button" className="text-button" disabled={reader.loading} onClick={reader.reload}>重新读取原件</button> : <>
      <div className="snapshot-banner"><strong>历史原件 · LOCAL SNAPSHOT</strong><span>未执行新的在线核验。</span></div>
      <h4>{value.body_encoding === "binary" ? "PDF 原件" : "纯文本原件"}</h4>
      <dl className="quality-detail-meta">
        <div><dt>来源</dt><dd>{value.source_id}</dd></div><div><dt>来源地址</dt><dd>{value.source_url}</dd></div>
        {"source_page" in value ? <div><dt>来源页面 URL</dt><dd>{value.source_page}</dd></div> : null}
        <div><dt>原观察时间</dt><dd>{value.observed_at}</dd></div><div><dt>核验时间</dt><dd>{"verified_at" in value ? show(value.verified_at) : "未提供（仅原文收件或隔离记录）"}</dd></div>
        <div><dt>真实原件大小</dt><dd>{value.byte_count.toLocaleString("zh-CN")} 字节</dd></div><div><dt>SHA-256</dt><dd className="mono">{value.raw_hash}</dd></div>
        <div><dt>原件记录</dt><dd>{value.id}</dd></div><div><dt>解析器版本</dt><dd>{value.parser_version}</dd></div>
        <div><dt>Parser identity</dt><dd><pre>{show("parser_identity" in value ? value.parser_identity : null)}</pre></dd></div>
        <div><dt>解析方法</dt><dd>{show(value.parse_method)}</dd></div><div><dt>映射版本</dt><dd>{show(value.mapping_id)}</dd></div>
      </dl>
      {"quality_review" in value && value.quality_review ? <div className="snapshot-banner">
        <strong>{value.quality_review.action === "approve" ? "历史质量审批 · 缺失变化经人工确认后在线采纳" : "历史人工复核 · 保留隔离"}</strong>
        <span>{value.quality_review.operator} · {value.quality_review.created_at}</span><p>{value.quality_review.reason}</p>
        <span>审批记录 {value.quality_review.id}</span>
      </div> : null}
      {"receipt_only" in value ? <p className="review-boundary">仅证明收到原件；{value.processing_unconfirmed ? "处理结果未确认" : `处理状态：${value.query_state}`}。读取或下载不代表数据已被采纳。</p> : null}
      {"accepted" in value ? <p className="review-boundary">此隔离记录 accepted:false，原件读取与下载不构成审批或正式事实。</p> : null}
      <p>已有原文定位：{frozenLocators?.length ? frozenLocators.join("；") : "未提供，不从 PDF 补造定位。"}</p>
      {value.body_encoding === "binary" ? <button type="button" className="secondary-button" disabled={reader.downloading} onClick={() => void reader.download()}>{reader.downloading ? "正在核验并等待保存…" : "核验并下载 PDF 原件"}</button>
        : <details className="raw-evidence" onToggle={event => { if (!event.currentTarget.open) reader.abortOperations(); }}><summary>展开纯文本原文<span className="mono">TEXT</span></summary><p>仅作纯文本核对，不执行来源内容。内容类型：{value.content_type}</p><pre>{value.body}</pre></details>}
      <details className="raw-evidence" onToggle={event => { if (!event.currentTarget.open) reader.abortOperations(); }}><summary>完整冻结原件元数据</summary><pre>{JSON.stringify(technical, null, 2)}</pre></details>
    </>}
  </div>;
}
