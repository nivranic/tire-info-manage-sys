"use client";

/** 通用内联确认块：用于不可逆 / 高影响操作前的显式确认（复用 consent-box 视觉语言）。 */
export default function InlineConfirm({ title, description, confirmLabel = "确认", cancelLabel = "取消", busy = false, onConfirm, onCancel }: {
  title: string; description?: string; confirmLabel?: string; cancelLabel?: string; busy?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  return <section className="consent-box inline-confirm" role="group" aria-label={title}>
    <h3>{title}</h3>
    {description ? <p>{description}</p> : null}
    <div className="compare-toolbar">
      <button type="button" className="secondary-button" disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
      <button type="button" className="text-button" disabled={busy} onClick={onCancel}>{cancelLabel}</button>
    </div>
  </section>;
}
