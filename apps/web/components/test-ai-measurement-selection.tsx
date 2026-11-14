"use client";

import { useEffect, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { AITestEventReference, TestEventDetail } from "@tire/domain-types";

export default function TestAIMeasurementSelection({ reference, disabled, onChange }: {
  reference: AITestEventReference;
  disabled: boolean;
  onChange: (numbers: number[] | undefined) => void;
}) {
  const [row, setRow] = useState<TestEventDetail | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setRow(null); setError("");
    void tireApi.testEvent(reference.event_id, controller.signal, reference.event_revision).then(value => {
      if (!controller.signal.aborted) setRow(value);
    }).catch(cause => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "成绩读取未完成。");
    });
    return () => controller.abort();
  }, [reference.event_id, reference.event_revision, retry]);

  const numbers = reference.measurement_numbers;
  const count = numbers?.length ?? row?.event.measurements.length;
  return <details>
    <summary>选择 AI 研究成绩 · {numbers === undefined ? "整场" : `已选 ${count} 条`}</summary>
    {!row && !error ? <p role="status">正在读取修订 #{reference.event_revision} 的原始成绩…</p> : null}
    {error ? <p className="inline-error" role="alert">{error} <button type="button" className="text-button" disabled={disabled} onClick={() => setRetry(value => value + 1)}>重试读取成绩</button></p> : null}
    {row ? <fieldset disabled={disabled}>
      <legend>{row.title} · 修订 #{row.revision} · 已选 {count} / {row.event.measurements.length} 条</legend>
      <p>保留原场次条件和成绩序号。证据包超限时可缩小选择，再准备证据。</p>
      <div className="compare-toolbar">
        <button type="button" className="text-button" onClick={() => onChange(undefined)}>选择整场成绩</button>
        <button type="button" className="text-button" onClick={() => onChange([])}>清空成绩选择</button>
      </div>
      {row.event.measurements.map((measurement, index) => {
        const number = index + 1;
        const person = row.event.participants.find(value => value.key === measurement.participant_key);
        const metric = row.event.metrics.find(value => value.key === measurement.metric_key);
        return <label className="review-checkbox" key={number}>
          <input type="checkbox" checked={numbers === undefined || numbers.includes(number)} onChange={event => {
            const current = numbers ?? row.event.measurements.map((_value, position) => position + 1);
            onChange(event.target.checked ? [...current, number].sort((a, b) => a - b) : current.filter(value => value !== number));
          }} />
          <span>本场成绩 {number} · {person?.brand} {person?.model} · {person?.tested_size || row.tested_size} · {metric?.label || measurement.metric_key} · {measurement.raw_value} {metric?.unit}</span>
        </label>;
      })}
      {count === 0 ? <p role="status">请至少选择一条成绩后准备证据。</p> : null}
    </fieldset> : null}
  </details>;
}
