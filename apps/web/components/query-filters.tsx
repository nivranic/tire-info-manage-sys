import { useRef } from "react";
import type { TireFilter, TireFilterCatalog, TireFilterOperator, TireQuerySelection } from "@tire/domain-types";
import { normalizeFilterNumber, parseExactJson } from "@tire/api-client";

export type FilterDraft = { id: string; field: string; op: TireFilterOperator; value: string };
const operatorLabels: Record<TireFilterOperator, string> = {
  eq: "等于", gte: "大于或等于", lte: "小于或等于", is_known: "已明确记录", is_unknown: "来源未声明（不含冲突）",
};
const needsValue = (op: TireFilterOperator) => op !== "is_known" && op !== "is_unknown";

export function parseFilterDrafts(drafts: FilterDraft[], catalog: TireFilterCatalog | null): { filters: TireFilter[]; error: string } {
  const filters: TireFilter[] = [];
  if (!drafts.length) return { filters, error: "" };
  if (!catalog) return { filters, error: "筛选目录尚未就绪，现有条件已保留。请重试加载目录。" };
  if (drafts.length > catalog.max_conditions) return { filters, error: `最多可组合 ${catalog.max_conditions} 个条件。` };
  for (const [index, draft] of drafts.entries()) {
    const field = catalog.fields.find(item => item.key === draft.field);
    const prefix = `条件 ${index + 1}`;
    if (!field || !field.operators.includes(draft.op)) return { filters: [], error: `${prefix} 已不在当前目录支持范围，请重新选择或删除该条件。` };
    if (!needsValue(draft.op)) { filters.push({ field: draft.field, op: draft.op }); continue; }
    const value = field.type === "text" ? draft.value : draft.value.trim();
    if (!value.trim()) return { filters: [], error: `${prefix}「${field.label}」尚未填写条件值。` };
    if (field.options?.length && !field.options.some(option => String(option.value) === value)) return { filters: [], error: `${prefix}「${field.label}」请选择目录提供的值。` };
    if (field.type === "boolean" && value !== "true" && value !== "false") return { filters: [], error: `${prefix}「${field.label}」请选择明确的是或否；未知请使用独立运算符。` };
    let parsed: import("@tire/domain-types").TireFilterValue = value;
    if (field.type === "number") { try { parsed = normalizeFilterNumber(parseExactJson(value)); } catch { return { filters: [], error: `${prefix}「${field.label}」请输入有效 JSON 数字。` }; } }
    filters.push({ field: field.key, op: draft.op, value: field.type === "boolean" ? value === "true" : parsed });
  }
  return { filters, error: "" };
}

export function describeFilter(filter: TireFilter, catalog: TireFilterCatalog | null) {
  const field = catalog?.fields.find(item => item.key === filter.field);
  const value = field?.options?.find(option => option.value === filter.value)?.label
    ?? (typeof filter.value === "boolean" ? filter.value ? "是" : "否" : String(filter.value ?? ""));
  return `${field?.label || filter.field} · ${operatorLabels[filter.op]}${needsValue(filter.op) ? ` ${value}${field?.unit ? ` ${field.unit}` : ""}` : ""}`;
}

export default function QueryFilters({ drafts, catalog, loading, error, validationError, onChange, onRetry }: {
  drafts: FilterDraft[];
  catalog: TireFilterCatalog | null;
  loading: boolean;
  error: string;
  validationError: string;
  onChange: (drafts: FilterDraft[]) => void;
  onRetry: () => void;
}) {
  const editor = useRef<HTMLDetailsElement>(null);
  const unavailable = loading || !!error || !catalog;
  const limit = catalog?.max_conditions ?? 16;
  function update(id: string, update: Partial<FilterDraft>) {
    onChange(drafts.map(draft => draft.id === id ? { ...draft, ...update } : draft));
  }
  function add() {
    const field = catalog?.fields[0];
    if (unavailable || !field || drafts.length >= limit) return;
    onChange([...drafts, { id: `filter-${crypto.randomUUID()}`, field: field.key, op: field.operators[0], value: "" }]);
  }
  function focusAfterRemoval(index: number) {
    requestAnimationFrame(() => {
      const node = editor.current;
      const remaining = node?.querySelectorAll<HTMLButtonElement>(".query-filter-remove");
      const adjacent = remaining?.[Math.min(index, remaining.length - 1)];
      const addButton = node?.querySelector<HTMLButtonElement>(".query-filter-add");
      (adjacent || (addButton && !addButton.disabled ? addButton : null) || node?.querySelector("summary"))?.focus();
    });
  }
  return <details ref={editor} id="query-filter-editor" className="query-filters">
    <summary><span>更多规格条件 <b className="count-badge">{drafts.length}</b></span><span className={`query-filters-summary-note${error ? " query-filters-error" : ""}`}>{error ? "目录加载失败 · 展开重试" : "全部满足 · AND"}</span></summary>
    <div className="query-filters-body">
      <p className="query-filters-scope">只筛选本次所选型号、尺寸与来源实际返回的规格，不扩大已接入目录范围。所有条件同时满足；未知或冲突不等于「否」。</p>
      {catalog?.notice ? <p className="query-filters-notice">{catalog.notice}</p> : null}
      {loading ? <p className="query-filters-status" role="status">正在加载可用字段与单位…</p> : null}
      {error ? <div className="query-filters-error" role="alert"><span>筛选目录加载失败：{error}。已有条件已保留；带条件的查询需加载成功后提交。</span><button type="button" className="text-button" onClick={onRetry}>重试加载筛选目录</button></div> : null}
      <div className="query-filter-rows">{drafts.map((draft, index) => {
        const field = catalog?.fields.find(item => item.key === draft.field);
        const hintId = `${draft.id}-hint`;
        const options = field?.type === "boolean"
          ? (field.options?.length ? field.options : [{ value: true, label: "是" }, { value: false, label: "否" }])
          : field?.options;
        return <fieldset className="query-filter-row" key={draft.id}>
          <legend>条件 {index + 1}<span>AND</span></legend>
          <div className="query-filter-controls">
            <label><span>规格字段</span><select aria-label={`条件 ${index + 1} 规格字段`} value={draft.field} disabled={unavailable} onChange={event => {
              const next = catalog?.fields.find(item => item.key === event.target.value);
              if (next) update(draft.id, { field: next.key, op: next.operators[0], value: "" });
            }}>{!field ? <option value={draft.field}>{draft.field} · 目录待核对</option> : null}{catalog?.fields.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label><span>判断方式</span><select aria-label={`条件 ${index + 1} 判断方式`} value={draft.op} disabled={unavailable || !field} onChange={event => update(draft.id, { op: event.target.value as TireFilterOperator, value: "" })}>
              {!field?.operators.includes(draft.op) ? <option value={draft.op}>{operatorLabels[draft.op]} · 待核对</option> : null}
              {field?.operators.map(op => <option key={op} value={op}>{operatorLabels[op]}</option>)}
            </select></label>
            {needsValue(draft.op) ? <label><span>条件值{field?.unit ? `（${field.unit}）` : ""}</span>{options?.length ? <select aria-label={`条件 ${index + 1} 条件值`} aria-describedby={hintId} value={draft.value} disabled={unavailable || !field} onChange={event => update(draft.id, { value: event.target.value })}>
              <option value="">请选择{field?.type === "boolean" ? "是或否" : "条件值"}</option>
              {draft.value && !options.some(option => String(option.value) === draft.value) ? <option value={draft.value}>{draft.value} · 目录待核对</option> : null}
              {options.map(option => <option key={String(option.value)} value={String(option.value)}>{typeof option.value === "boolean" ? option.value ? "是" : "否" : option.label}</option>)}
            </select> : <input aria-label={`条件 ${index + 1} 条件值`} aria-describedby={hintId} type="text" inputMode={field?.type === "number" ? "decimal" : undefined} value={draft.value} maxLength={field?.type === "number" ? undefined : 1024} disabled={unavailable || !field} autoComplete="off" onChange={event => update(draft.id, { value: event.target.value })} />}</label>
              : <p className="query-filter-no-value">此判断无需填写值</p>}
            <button type="button" className="text-button query-filter-remove" aria-label={`删除条件 ${index + 1}`} onClick={() => { onChange(drafts.filter(item => item.id !== draft.id)); focusAfterRemoval(index); }}>删除</button>
          </div>
          <p id={hintId} className="query-filter-description">{field?.description || "按来源明确记录的字段值判断。"}{field?.unit ? ` 数值单位：${field.unit}。` : ""}</p>
        </fieldset>;
      })}</div>
      <div className="query-filters-actions"><button type="button" className="secondary-button query-filter-add" disabled={unavailable || !catalog?.fields.length || drafts.length >= limit} onClick={add}>添加条件</button><button type="button" className="text-button" disabled={!drafts.length} onClick={() => { onChange([]); focusAfterRemoval(0); }}>清空条件</button><span>{drafts.length} / {limit} 项</span></div>
      <p className="query-filters-notice">这里的修改仅保存为草稿；点击「查询轮胎」后重新请求来源，已显示结果不会随编辑改变。</p>
      {validationError ? <p className="query-filters-error" role="alert">{validationError}</p> : null}
    </div>
  </details>;
}

export function QuerySelectionCounts({ selection, local }: { selection: TireQuerySelection; local: boolean }) {
  if ([selection.source_count, selection.matched_count, selection.excluded_count, selection.undetermined_count].some(value => value === null)) return null;
  return <div className="query-selection-counts" aria-label={local ? "本包历史观察的完整条件筛选统计" : "本次来源筛选统计"}>
    <p>{local ? "本包所选来源的历史观察 · 型号、尺寸与全部条件共同判断" : "本次已核验的来源返回范围"}</p>
    <dl><div><dt>{local ? "包内历史观察" : "来源返回"}</dt><dd>{selection.source_count}</dd></div><div><dt>匹配规格</dt><dd>{selection.matched_count}</dd></div><div><dt>明确不匹配</dt><dd>{selection.excluded_count}</dd></div><div><dt>未能判定</dt><dd>{selection.undetermined_count}</dd></div></dl>
    {local ? <p>计数按历史观察分别统计；同一规格的不同核验仍为独立观察。本包没有匹配不表示来源没有产品，也不代表完整 SKU 数量。</p> : null}
    {selection.filters.length ? <p>未能判定表示来源缺失、存在未解决冲突或字段类型不合法，不计入匹配；不据此推断技术配置为「否」。</p> : null}
  </div>;
}
