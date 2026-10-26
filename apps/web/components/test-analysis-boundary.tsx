import type { AIEvidence, TestAnalysisBoundary } from "@tire/domain-types";

export function containsTestEvidence(evidence: readonly AIEvidence[]) {
  return evidence.some(item => !!item.event_id || item.kind.startsWith("manual_test_"));
}

export function TestAnalysisScope({ boundary, pending = false, historical = false }: {
  boundary?: TestAnalysisBoundary; pending?: boolean; historical?: boolean;
}) {
  if (!boundary && !pending && !historical) return null;
  return <aside className="review-boundary" aria-label="测试证据的分析范围" data-test-analysis-boundary={boundary?.policy_version || "preview"}>
    <strong>{historical ? "历史测试分析 · 保留原记录" : "测试事实摘录 · 不建立 SKU 性能关联"}</strong>
    <p>{historical ? "这条历史结果未按本轮测试摘录规则重新复核；原结果保持。参测名称仍不能确立精确 SKU 身份或推荐。" : boundary?.notice || "含测试证据的分析仅按场次、参测对象分别摘录已录事实。参测对象尚未与精确 SKU 建立证据关联；不能移植成绩或据此推荐。"}</p>
  </aside>;
}
