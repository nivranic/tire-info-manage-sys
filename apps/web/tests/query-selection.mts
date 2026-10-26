import assert from "node:assert/strict";
import { test } from "node:test";
import type { Variant } from "@tire/domain-types";
import {
  clearQuerySelection, planComparisonAddition, querySelectionEligibleIds, querySelectionOrderKey,
  reconcileQuerySelection, toggleQuerySelection,
} from "../components/query-selection-values.ts";
import type { QuerySelection, QuerySelectionRow } from "../components/query-selection-values.ts";

function variant(id: string, overrides: Partial<Variant> = {}): Variant {
  return {
    id, brand: "Fixture brand", model: "Same model", manufacturer_product_code: null,
    region: "CN", size: "225/45 R18", load_index: "95", speed_rating: "W", xl: null, hl: null,
    oe_mark: null, acoustic_technology: null, run_flat: null, facts: {}, snapshot_id: `snapshot-${id}`,
    ...overrides,
  };
}

function row(id: string, sourceId = "source-a", overrides: Partial<Variant> = {}): QuerySelectionRow {
  return { rowKey: JSON.stringify([sourceId, id]), variant: variant(id, { source_id: sourceId, ...overrides }) };
}

const revoked: Variant["lifecycle"] = {
  state: "revoked", revision: 1, event_id: null, operator: null, reason: "Synthetic revocation", changed_at: null,
};
const rows = [row("a"), row("b"), row("c"), row("d", "source-b"), row("e", "source-b")];
const click = (selection: QuerySelection, index: number, checked = true, shift = false, currentRows = rows) =>
  toggleQuerySelection(selection, currentRows, currentRows[index].rowKey, checked, shift);

test("ordinary toggles change one exact ID, use visual order and set the occurrence anchor", () => {
  let selection = click(clearQuerySelection(rows), 4);
  selection = click(selection, 1);
  assert.deepEqual(selection.ids, ["b", "e"]);
  assert.equal(selection.anchor, rows[1].rowKey);
  selection = click(selection, 4, false);
  assert.deepEqual(selection.ids, ["b"]);
  assert.equal(selection.anchor, rows[4].rowKey);
});

test("forward Shift includes both endpoints, crosses sources and preserves the original anchor", () => {
  const initial = click(clearQuerySelection(rows), 1);
  const selection = click(initial, 3, true, true);
  assert.deepEqual(selection.ids, ["b", "c", "d"]);
  assert.equal(selection.anchor, rows[1].rowKey);
  assert.deepEqual(click(selection, 4, true, true).ids, ["b", "c", "d", "e"]);
  assert.equal(click(selection, 4, true, true).anchor, rows[1].rowKey);
});

test("reverse Shift returns the inclusive range in visual order", () => {
  const initial = click(clearQuerySelection(rows), 3);
  const selection = click(initial, 1, true, true);
  assert.deepEqual(selection.ids, ["b", "c", "d"]);
  assert.equal(selection.anchor, rows[3].rowKey);
});

test("Shift cancellation assigns false throughout the range and preserves outside selections", () => {
  let selection = click(clearQuerySelection(rows), 0);
  selection = click(selection, 1);
  selection = click(selection, 4, true, true);
  selection = click(selection, 3, false, true);
  assert.deepEqual(selection.ids, ["a", "e"]);
  assert.equal(selection.anchor, rows[1].rowKey);
  assert.deepEqual(click(selection, 3, false, true).ids, ["a", "e"]);
});

test("Shift addition preserves selected IDs outside the interval", () => {
  const initial = click(click(clearQuerySelection(rows), 4), 1);
  assert.deepEqual(click(initial, 3, true, true).ids, ["b", "c", "d", "e"]);
});

test("Shift without an anchor changes only the endpoint and creates an anchor", () => {
  const initial: QuerySelection = { ids: ["a", "c"], anchor: null, orderKey: querySelectionOrderKey(rows) };
  const checked = click(initial, 4, true, true);
  assert.deepEqual(checked.ids, ["a", "c", "e"]);
  assert.equal(checked.anchor, rows[4].rowKey);
  const unchecked = click(initial, 2, false, true);
  assert.deepEqual(unchecked.ids, ["a"]);
  assert.equal(unchecked.anchor, rows[2].rowKey);
});

test("reordering clears the anchor and makes the next Shift a single-item operation", () => {
  const initial = click(clearQuerySelection(rows), 1);
  const reordered = [rows[4], rows[3], rows[2], rows[1], rows[0]];
  const reconciled = reconcileQuerySelection(initial, reordered);
  assert.deepEqual(reconciled.ids, ["b"]);
  assert.equal(reconciled.anchor, null);
  const selection = click(initial, 0, true, true, reordered);
  assert.deepEqual(selection.ids, ["e", "b"]);
  assert.equal(selection.anchor, reordered[0].rowKey);
});

test("expanding 20 visible rows to 40 retains visible IDs and clears the old range anchor", () => {
  const allRows = Array.from({ length: 40 }, (_, index) => row(`id-${index + 1}`));
  const firstPage = allRows.slice(0, 20);
  const initial = click(clearQuerySelection(firstPage), 18, true, false, firstPage);
  const reconciled = reconcileQuerySelection(initial, allRows);
  assert.deepEqual(reconciled.ids, ["id-19"]);
  assert.equal(reconciled.anchor, null);
  assert.deepEqual(click(initial, 39, true, true, allRows).ids, ["id-19", "id-40"]);
  assert.deepEqual(reconcileQuerySelection({ ...reconciled, ids: ["id-19", "id-40"] }, firstPage).ids, ["id-19"]);
});

test("clear removes pending IDs and the anchor while retaining the current order context", () => {
  const selection = click(click(clearQuerySelection(rows), 0), 3, true, true);
  const cleared = clearQuerySelection(rows);
  assert.deepEqual(cleared, { ids: [], anchor: null, orderKey: querySelectionOrderKey(rows) });
  assert.deepEqual(selection.ids, ["a", "b", "c", "d"]);
  assert.deepEqual(click(cleared, 4, true, true).ids, ["e"]);
});

test("reconcile prunes unknown IDs, deduplicates and retains its reference when already valid", () => {
  const input: QuerySelection = { ids: ["e", "unknown", "b", "b"], anchor: rows[1].rowKey, orderKey: querySelectionOrderKey(rows) };
  const reconciled = reconcileQuerySelection(input, rows);
  assert.deepEqual(reconciled.ids, ["b", "e"]);
  assert.equal(reconciled.anchor, rows[1].rowKey);
  assert.equal(reconcileQuerySelection(reconciled, rows.map(item => ({ ...item, variant: { ...item.variant } }))), reconciled);
  assert.deepEqual(input.ids, ["e", "unknown", "b", "b"]);
});

test("same-model different exact IDs remain separate and ID spelling is never normalized", () => {
  const exactRows = [row("ID"), row("id"), row(" id ")];
  assert.deepEqual(querySelectionEligibleIds(exactRows), ["ID", "id", " id "]);
  const initial = click(clearQuerySelection(exactRows), 0, true, false, exactRows);
  assert.deepEqual(click(initial, 2, true, true, exactRows).ids, ["ID", "id", " id "]);
});

test("duplicate IDs share membership while the source occurrence determines the range", () => {
  const duplicateRows = [row("same", "source-a"), row("middle", "source-a"), row("same", "source-b"), row("last", "source-b")];
  assert.deepEqual(querySelectionEligibleIds(duplicateRows), ["same", "middle", "last"]);
  const initial = click(clearQuerySelection(duplicateRows), 2, true, false, duplicateRows);
  const selection = click(initial, 3, true, true, duplicateRows);
  assert.deepEqual(selection.ids, ["same", "last"]);
  assert.equal(selection.anchor, duplicateRows[2].rowKey);
  const removed = click(selection, 2, false, false, duplicateRows);
  assert.deepEqual(removed.ids, ["last"]);
});

test("any revoked duplicate fails closed across sources and range selection skips its ID", () => {
  const currentRows = [row("a"), row("blocked", "source-a"), row("blocked", "source-b", { lifecycle: revoked }), row("d")];
  assert.deepEqual(querySelectionEligibleIds(currentRows), ["a", "d"]);
  const initial = click(clearQuerySelection(currentRows), 0, true, false, currentRows);
  const selection = click(initial, 3, true, true, currentRows);
  assert.deepEqual(selection.ids, ["a", "d"]);
  assert.equal(click(selection, 1, true, false, currentRows), selection);
});

test("eligibility changes prune selected IDs and invalidate anchors before Shift is evaluated", () => {
  const initial = click(click(clearQuerySelection(rows), 0), 1);
  const changedRows = rows.map(item => item.variant.id === "b" ? { ...item, variant: { ...item.variant, lifecycle: revoked } } : item);
  assert.notEqual(querySelectionOrderKey(changedRows), initial.orderKey);
  const reconciled = reconcileQuerySelection(initial, changedRows);
  assert.deepEqual(reconciled.ids, ["a"]);
  assert.equal(reconciled.anchor, null);
  assert.deepEqual(click(initial, 4, true, true, changedRows).ids, ["a", "e"]);
});

test("invalid endpoints and missing anchors cannot expand an interval", () => {
  const initial = click(clearQuerySelection(rows), 1);
  assert.equal(toggleQuerySelection(initial, rows, "missing-row", true, true), initial);
  const missingAnchor = { ...initial, anchor: "missing-anchor" };
  assert.deepEqual(click(missingAnchor, 4, true, true).ids, ["b", "e"]);
  assert.deepEqual(reconcileQuerySelection(initial, []).ids, []);
  assert.equal(reconcileQuerySelection(initial, []).anchor, null);
});

test("order signatures depend on occurrence order and eligibility, not refreshed parameter values", () => {
  const refreshed = rows.map(item => ({ ...item, variant: { ...item.variant, model: "Refreshed model", snapshot_id: "new-snapshot" } }));
  assert.equal(querySelectionOrderKey(refreshed), querySelectionOrderKey(rows));
  assert.notEqual(querySelectionOrderKey([rows[1], rows[0], ...rows.slice(2)]), querySelectionOrderKey(rows));
  assert.notEqual(querySelectionOrderKey([{ ...rows[0], rowKey: JSON.stringify(["other-source", "a"]) }, ...rows.slice(1)]), querySelectionOrderKey(rows));
  assert.equal(reconcileQuerySelection(click(clearQuerySelection(rows), 0), refreshed).anchor, rows[0].rowKey);
});

test("comparison addition preserves previous objects and appends current objects in visual order", () => {
  const existing = variant("existing");
  const currentRows = [row("a", "source-a", { model: "Current A" }), row("b")];
  const result = planComparisonAddition([existing], ["b", "a", "b"], currentRows);
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.compared.map(item => item.id), ["existing", "a", "b"]);
  assert.deepEqual(result.addedIds, ["a", "b"]);
  assert.equal(result.compared[0], existing);
  assert.equal(result.compared[1], currentRows[0].variant);
  assert.equal(result.compared[1].model, "Current A");
});

test("comparison addition keeps existing IDs without removing or replacing their objects", () => {
  const existing = variant("a", { model: "Previous object" });
  const result = planComparisonAddition([existing], ["a", "a", "b"], rows);
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.compared.map(item => item.id), ["a", "b"]);
  assert.equal(result.compared[0], existing);
  assert.deepEqual(result.addedIds, ["b"]);
  const repeated = planComparisonAddition(result.compared, ["a", "b"], rows);
  assert.equal(repeated.ok, true);
  if (!repeated.ok) return;
  assert.deepEqual(repeated.addedIds, []);
  assert.deepEqual(repeated.compared, result.compared);
  assert.equal(repeated.compared[0], existing);
});

test("comparison uses the first current eligible occurrence and deduplicates exact IDs only", () => {
  const currentRows = [row("same", "first", { model: "First occurrence" }), row("same", "second"), row("other", "second")];
  const result = planComparisonAddition([], ["same", "other", "same"], currentRows);
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.compared.map(item => item.id), ["same", "other"]);
  assert.equal(result.compared[0], currentRows[0].variant);
  assert.equal(result.compared[0].model, "First occurrence");
});

test("comparison may reach exactly four, and already-compared IDs consume no new slot", () => {
  const previous = [variant("old-1"), variant("a"), variant("old-2")];
  const result = planComparisonAddition(previous, ["a", "d", "d"], rows);
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.compared.length, 4);
  assert.deepEqual(result.addedIds, ["d"]);
  previous.forEach((item, index) => assert.equal(result.compared[index], item));
});

test("comparison rejects an over-capacity batch atomically and never silently truncates", () => {
  const previous = [variant("old-1"), variant("old-2"), variant("old-3")];
  const before = structuredClone(previous);
  const result = planComparisonAddition(previous, ["a", "b"], rows);
  assert.deepEqual(result, { ok: false, reason: "capacity_exceeded", rejectedIds: ["a", "b"] });
  assert.deepEqual(previous, before);
  assert.equal("compared" in result, false);
  const full = [...previous, variant("old-4")];
  assert.equal(planComparisonAddition(full, ["a"], rows).ok, false);
});

test("previous revoked items remain untouched and continue to occupy comparison capacity", () => {
  const existingRevoked = variant("revoked-existing", { lifecycle: revoked });
  const previous = [existingRevoked, variant("old-2"), variant("old-3")];
  const accepted = planComparisonAddition(previous, ["a"], rows);
  assert.equal(accepted.ok, true);
  if (!accepted.ok) return;
  assert.equal(accepted.compared[0], existingRevoked);
  assert.equal(accepted.compared[0].lifecycle?.state, "revoked");
  assert.equal(accepted.compared.length, 4);
  assert.deepEqual(planComparisonAddition(previous, ["a", "b"], rows), {
    ok: false, reason: "capacity_exceeded", rejectedIds: ["a", "b"],
  });
});

test("empty, unknown, hidden and no-longer-eligible selections reject the whole batch", () => {
  assert.deepEqual(planComparisonAddition([], [], rows), { ok: false, reason: "empty_selection", rejectedIds: [] });
  assert.deepEqual(planComparisonAddition([], ["a", "unknown", "unknown"], rows), {
    ok: false, reason: "unknown_selection", rejectedIds: ["unknown"],
  });
  assert.deepEqual(planComparisonAddition([], ["a", "e"], rows.slice(0, 4)), {
    ok: false, reason: "unknown_selection", rejectedIds: ["e"],
  });
  const changedRows = [row("a"), row("b", "source-a", { lifecycle: revoked })];
  assert.deepEqual(planComparisonAddition([], ["a", "b"], changedRows), {
    ok: false, reason: "ineligible_selection", rejectedIds: ["b"],
  });
  assert.equal(planComparisonAddition([variant("unknown")], ["unknown"], rows).ok, false);
  assert.equal(planComparisonAddition([variant("b")], ["b"], changedRows).ok, false);
});

test("a revoked duplicate rejects a batch even when the first occurrence is active", () => {
  const currentRows = [row("a"), row("same", "source-a"), row("same", "source-b", { lifecycle: revoked })];
  assert.deepEqual(planComparisonAddition([], ["a", "same"], currentRows), {
    ok: false, reason: "ineligible_selection", rejectedIds: ["same"],
  });
  assert.deepEqual(planComparisonAddition([], ["a", "same"], [...currentRows].reverse()), {
    ok: false, reason: "ineligible_selection", rejectedIds: ["same"],
  });
});

test("all helpers leave frozen selections, row objects, variants and compared inputs unchanged", () => {
  const currentRows = [row("a"), row("b"), row("c")];
  currentRows.forEach(item => { Object.freeze(item.variant.facts); Object.freeze(item.variant); Object.freeze(item); });
  Object.freeze(currentRows);
  const selection = click(clearQuerySelection(currentRows), 0, true, false, currentRows);
  Object.freeze(selection.ids);
  Object.freeze(selection);
  const previous = [variant("previous", { lifecycle: revoked })];
  Object.freeze(previous[0]);
  Object.freeze(previous);
  const selectedIds = Object.freeze(["c", "a", "c"]);
  const before = JSON.stringify({ currentRows, selection, previous, selectedIds });
  querySelectionOrderKey(currentRows);
  querySelectionEligibleIds(currentRows);
  reconcileQuerySelection(selection, currentRows);
  toggleQuerySelection(selection, currentRows, currentRows[2].rowKey, true, true);
  clearQuerySelection(currentRows);
  const result = planComparisonAddition(previous, selectedIds, currentRows);
  assert.equal(result.ok, true);
  assert.equal(JSON.stringify({ currentRows, selection, previous, selectedIds }), before);
});
