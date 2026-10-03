import type { AIAnalysisReference, AIPackReference, AIPrepareRequest, KnowledgeSearchItem } from "@tire/domain-types";

// A product search hit selects its complete announcement observation. Keep both
// bindings: a newer raw snapshot can legitimately reuse a semantic revision.
export function aiReferenceKey(reference: AIAnalysisReference): string {
  switch (reference.kind) {
    case "recall": return JSON.stringify([reference.kind, reference.snapshot_id, reference.recall_revision_id]);
    case "tire": return JSON.stringify([reference.kind, reference.snapshot_id, reference.variant_id]);
    case "vehicle": return JSON.stringify([reference.kind, reference.snapshot_id]);
    case "test_event": return JSON.stringify([reference.kind, reference.event_id, reference.event_revision]);
    case "change_event": return JSON.stringify([reference.kind, reference.change_id]);
  }
}

export function uniqueAIReferences<T extends AIAnalysisReference>(references: T[]): T[] {
  return [...new Map(references.map(reference => [aiReferenceKey(reference), reference])).values()];
}

export function selectedKnowledgeReferences(items: KnowledgeSearchItem[], selected: string[]): AIPackReference[] {
  return uniqueAIReferences(items.filter(item => selected.includes(item.id)).map(item => item.reference));
}

export function canSelectKnowledgeReference(references: AIPackReference[], reference: AIPackReference, limit = 6): boolean {
  return references.length < limit || references.some(value => aiReferenceKey(value) === aiReferenceKey(reference));
}

export function recallCurrentRequest(campaign_number: string): AIPrepareRequest {
  return { mode: "current", query_kind: "recall_by_campaign", source_id: "nhtsa-us-recalls", query: { campaign_number } };
}
