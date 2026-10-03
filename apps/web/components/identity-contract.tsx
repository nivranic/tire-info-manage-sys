import type { IdentityContract } from "@tire/domain-types";
import { DataTree } from "./reparse-review";

const states = { current: "现行身份 v2", legacy_unbound: "旧身份尚未绑定", legacy_needs_review: "旧身份需要核对" };
const valueText = (value: unknown) => typeof value === "string" && value.trim() ? value : "未确认";
const reasonLabels: Record<string, string> = {
  identity_migration_required: "旧身份尚未完成迁移判定",
  legacy_evidence_missing: "缺少可核对的历史来源证据",
  legacy_raw_integrity_failed: "历史原文完整性未通过核验",
  legacy_identity_evidence_mismatch: "历史身份与原始证据不一致",
  legacy_namespace_unknown: "历史证据中存在未确认的编码类型",
  legacy_identity_invalid: "历史身份结构无法可靠校验",
  legacy_fact_evidence_mismatch: "来源事实与历史证据不一致",
  legacy_identity_ambiguous: "历史观察无法唯一确定现行身份",
  canonical_key_collision: "现行身份键对应多个记录，不能自动合并",
};
export const identityReasonLabel = (code: string) => reasonLabels[code] || code;

/** Only server-issued contract metadata is authoritative; never consult facts or overrides. */
export function identityContractText(contract?: IdentityContract, context: "current" | "saved" | "search" = "current") {
  if (!contract) return "此记录未保存身份合同信息";
  const state = `${context === "saved" ? "保存时：" : context === "search" ? "检索时身份状态：" : ""}${states[contract.state] || "身份合同状态未确认"}`;
  if (contract.state !== "current") return state;
  const type = valueText(contract.current_identity?.product_code_type);
  return `${state} · 编码类型 ${type}${contract.identity_status === "source_scoped" ? " · 来源范围身份" : ""}`;
}

export function IdentityContractBadge({ contract, context = "current" }: { contract?: IdentityContract; context?: "current" | "saved" | "search" }) {
  return <span className={`identity-contract-badge${contract && contract.state !== "current" ? " needs-review" : ""}`}>{identityContractText(contract, context)}</span>;
}

export function IdentityContractEvidence({ contract, historical = false }: { contract?: IdentityContract; historical?: boolean }) {
  if (!contract) return <p className="identity-contract-note">此记录未保存身份合同信息。保留记录中的产品代码；不能从参数值推定现行编码类型。</p>;
  return <section className="identity-contract-evidence">
    <h4>{historical ? "证据保存时的身份合同" : "服务端现行身份合同"}</h4><IdentityContractBadge contract={contract} context={historical ? "saved" : "current"} />
    <p>{historical ? "此处展示随证据冻结的信息，不表示当前迁移状态。" : "原快照和旧身份字段仍保留原貌；以下状态来自当前权威绑定。"}</p>
    {contract.current_identity ? <p>合同中的产品代码：<code>{valueText(contract.current_identity.manufacturer_product_code)}</code> · 类型 {valueText(contract.current_identity.product_code_type)}</p> : null}
    {contract.tracking_state === "identity_review_required" ? <p className="review-warning">{historical ? "记录时标明：" : ""}旧关注或监控需要身份核对；不会自动跟随相关候选或迁移到新 SKU。</p> : null}
    {contract.reason_codes.length ? <p>核对原因：{contract.reason_codes.map(identityReasonLabel).join("；")}</p> : null}
    {contract.related_candidates.length ? <details><summary>相关候选仅供核对（{contract.related_candidates.length}）</summary>{contract.related_candidates.map(item => <p key={`${item.relationship}:${item.variant_id}`}><code>{item.variant_id}</code> · {item.relationship === "unconfirmed_legacy" ? "尚未确认的旧记录" : "尚未确认的现行记录"} · 编码类型 {item.product_code_type || "未确认"}</p>)}<p>这些关联不代表同一 SKU，没有自动合并或替换引用。</p></details> : null}
    <DataTree label="身份合同、规则与权威绑定详情" value={contract} />
  </section>;
}
