import type { FieldDecision } from "@tire/domain-types";

export const fieldStateLabels: Record<FieldDecision["state"], string> = {
  uncontested: "现有证据无矛盾", conflict_preferred: "来源冲突 · 有默认展示值",
  conflict_tied: "同级来源冲突 · 暂无默认值", unknown: "来源未声明 · 暂无默认值",
  unavailable: "证据或适用范围不足 · 暂无默认值",
};

export function fieldValueText(value: unknown, unit?: string | null): string {
  if (value === null || value === undefined) return "未知（null）";
  if (typeof value === "boolean") return value ? "是（true）" : "否（false）";
  if (typeof value === "string") return value === "" ? "空文本（string）" : JSON.stringify(value);
  if (typeof value === "number") return `${value}${unit ? ` ${unit}` : ""}`;
  return JSON.stringify(value);
}

/** No raw/effective facts fallback: a tied or unavailable decision stays undecided. */
export function fieldDefaultText(decision: FieldDecision): string {
  return decision.has_default ? fieldValueText(decision.default_value, decision.unit) : fieldStateLabels[decision.state];
}
