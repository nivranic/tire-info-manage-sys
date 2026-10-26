import type { Variant } from "@tire/domain-types";

export interface QuerySelectionRow { rowKey: string; variant: Variant }
export interface QuerySelection { ids: string[]; anchor: string | null; orderKey: string }

export type ComparisonAdditionPlan =
  | { ok: true; compared: Variant[]; addedIds: string[] }
  | { ok: false; reason: "empty_selection" | "unknown_selection" | "ineligible_selection" | "capacity_exceeded"; rejectedIds: string[] };

function selectionRows(rows: readonly QuerySelectionRow[]) {
  const revokedIds = new Set(rows.filter(row => row.variant.lifecycle?.state === "revoked").map(row => row.variant.id));
  const variants = new Map<string, Variant>();
  const visibleIds = new Set<string>();
  for (const row of rows) {
    const id = row.variant.id;
    visibleIds.add(id);
    if (!revokedIds.has(id) && !variants.has(id)) variants.set(id, row.variant);
  }
  return {
    variants,
    visibleIds,
    eligibleIds: [...variants.keys()],
    orderKey: JSON.stringify(rows.map(row => [row.rowKey, row.variant.id, !revokedIds.has(row.variant.id)])),
  };
}

export function querySelectionOrderKey(rows: readonly QuerySelectionRow[]): string {
  return selectionRows(rows).orderKey;
}

export function querySelectionEligibleIds(rows: readonly QuerySelectionRow[]): string[] {
  return selectionRows(rows).eligibleIds;
}

function sameIds(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((id, index) => id === right[index]);
}

function reconcileSelection(selection: QuerySelection, rows: readonly QuerySelectionRow[], context: ReturnType<typeof selectionRows>): QuerySelection {
  const selectedIds = new Set(selection.ids);
  const ids = context.eligibleIds.filter(id => selectedIds.has(id));
  const anchor = selection.orderKey === context.orderKey
    && rows.some(row => row.rowKey === selection.anchor && context.variants.has(row.variant.id)) ? selection.anchor : null;
  if (selection.orderKey === context.orderKey && selection.anchor === anchor && sameIds(selection.ids, ids)) return selection;
  return { ids, anchor, orderKey: context.orderKey };
}

export function reconcileQuerySelection(selection: QuerySelection, rows: readonly QuerySelectionRow[]): QuerySelection {
  return reconcileSelection(selection, rows, selectionRows(rows));
}

export function clearQuerySelection(rows: readonly QuerySelectionRow[]): QuerySelection {
  return { ids: [], anchor: null, orderKey: querySelectionOrderKey(rows) };
}

export function toggleQuerySelection(
  selection: QuerySelection, rows: readonly QuerySelectionRow[], rowKey: string, checked: boolean, shiftKey = false,
): QuerySelection {
  const context = selectionRows(rows);
  const current = reconcileSelection(selection, rows, context);
  const targetIndex = rows.findIndex(row => row.rowKey === rowKey);
  if (targetIndex < 0 || !context.variants.has(rows[targetIndex].variant.id)) return current;
  const anchorIndex = shiftKey && current.anchor !== null ? rows.findIndex(row => row.rowKey === current.anchor) : -1;
  const start = anchorIndex < 0 ? targetIndex : Math.min(anchorIndex, targetIndex);
  const end = anchorIndex < 0 ? targetIndex : Math.max(anchorIndex, targetIndex);
  const selectedIds = new Set(current.ids);
  for (let index = start; index <= end; index += 1) {
    const id = rows[index].variant.id;
    if (!context.variants.has(id)) continue;
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
  }
  const ids = context.eligibleIds.filter(id => selectedIds.has(id));
  const anchor = anchorIndex < 0 ? rowKey : current.anchor;
  if (anchor === current.anchor && sameIds(ids, current.ids)) return current;
  return { ids, anchor, orderKey: context.orderKey };
}

export function planComparisonAddition(
  previous: readonly Variant[], selectedIds: readonly string[], rows: readonly QuerySelectionRow[],
): ComparisonAdditionPlan {
  const requestedIds = [...new Set(selectedIds)];
  if (!requestedIds.length) return { ok: false, reason: "empty_selection", rejectedIds: [] };
  const context = selectionRows(rows);
  const unknownIds = requestedIds.filter(id => !context.visibleIds.has(id));
  if (unknownIds.length) return { ok: false, reason: "unknown_selection", rejectedIds: unknownIds };
  const ineligibleIds = requestedIds.filter(id => !context.variants.has(id));
  if (ineligibleIds.length) return { ok: false, reason: "ineligible_selection", rejectedIds: ineligibleIds };
  const requested = new Set(requestedIds);
  const existing = new Set(previous.map(variant => variant.id));
  const addedIds = context.eligibleIds.filter(id => requested.has(id) && !existing.has(id));
  if (previous.length + addedIds.length > 4) return { ok: false, reason: "capacity_exceeded", rejectedIds: addedIds };
  return { ok: true, compared: [...previous, ...addedIds.map(id => context.variants.get(id)!)], addedIds };
}
