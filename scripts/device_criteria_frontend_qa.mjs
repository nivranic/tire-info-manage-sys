import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadOfflineTypeScript } from "./load_offline_typescript.mjs";
const criteria = await loadOfflineTypeScript("../packages/api-client/src/device-criteria.ts", import.meta.url);
const exact = await loadOfflineTypeScript("../packages/api-client/src/exact-json.ts", import.meta.url);
for (const name of ["query-filters49.json", "query-filters49-extra.json"]) {
  const fixture = JSON.parse(await readFile(new URL("../apps/api/tests/data/" + name, import.meta.url), "utf8"));
  test(name + " original numeric and Unicode oracle", () => {
    let valid = 0, invalid = 0, rows = 0;
    for (const vector of fixture.cases) {
      if (vector.validation_error !== null) { assert.throws(() => criteria.canonicalDeviceFilters(exact.parseExactJson(vector.input_filters_json)), vector.id); invalid++; continue; }
      const filters = criteria.canonicalDeviceFilters(exact.parseExactJson(vector.input_filters_json));
      assert.equal(exact.stringifyExactJson(filters), vector.canonical_filters_json, vector.id + " canonical");
      const source = exact.parseExactJson(vector.rows_json);
      const selected = criteria.selectDeviceTires(source, filters);
      assert.deepEqual(selected.selected.map(row => source.indexOf(row)), vector.expected.matched_row_indexes, vector.id + " indexes");
      for (const [index, row] of source.entries()) for (const [j, condition] of filters.entries()) {
        const actual = criteria.readDeviceTireField(row, condition.field), expected = vector.expected.per_row[index].conditions[j];
        assert.equal(actual.status, expected.status, vector.id + " status " + index);
        assert.equal(exact.stringifyExactJson(actual.value), expected.value_json, vector.id + " value " + index);
        assert.equal(criteria.deviceConditionMatches(row, condition), expected.matched, vector.id + " truth " + index);
      }
      for (const key of ["source_count", "matched_count", "excluded_count", "undetermined_count"]) assert.equal(selected.selection[key], vector.expected.selection[key], vector.id + " " + key);
      valid++; rows += source.length;
    }
    console.log(JSON.stringify({ fixture: name, valid, invalid, rows }));
  });
}
test("full basic conditions AND advanced filters count all historical observations", () => {
  const rows = [{ model: "Pilot Sport EV", size: "245/40R20", facts: { utqg_treadwear: 300 } }, { model: "Other", size: "245/40R20", facts: {} }, { model: "Pilot Sport EV", facts: { utqg_treadwear: 400 } }, { model: "Pilot Sport EV", size: "245/40ZR20", facts: { utqg_treadwear: 500 } }];
  const filters = criteria.canonicalDeviceFilters([{ field: "utqg_treadwear", op: "gte", value: 300 }]);
  const result = criteria.selectDeviceTires(rows, filters, { model: "Pilot Sport EV", size: "245/40R20" });
  assert.equal(result.selection.source_count, 4); assert.equal(result.selection.matched_count, 1); assert.equal(result.selection.excluded_count, 2); assert.equal(result.selection.undetermined_count, 1);
  assert.deepEqual(criteria.canonicalDeviceQuery("tire", { size: "۲۴۵/۴۰R۲۰" }), { size: "245/40R۲۰" });
  assert.deepEqual(criteria.canonicalDeviceQuery("tire", { model: "MICHELIN PSEV" }), { model: "Pilot Sport EV" });
});
test("basic TireQuery raw size boundary matches the separate actual Python oracle", async () => {
  const fixture = JSON.parse(await readFile(new URL("../.artifacts/query-fallback49/basic-query-reference-a.json", import.meta.url), "utf8"));
  for (const [index, vector] of fixture.cases.entries()) {
    const query = criteria.canonicalDeviceQuery("tire", vector.draft_query);
    assert.deepEqual(query, vector.canonical_query, `${index} canonical query`);
    assert.equal(criteria.selectDeviceTires([vector.row], [], query).matches[0], vector.basic_match, `${index} basic`);
    assert.equal(criteria.selectDeviceTires([vector.row], criteria.canonicalDeviceFilters([vector.advanced_filter])).matches[0], vector.advanced_match, `${index} advanced`);
    assert.equal(criteria.selectDeviceTires([vector.row], [], { ...query, model: "Other" }).matches[0], vector.basic_with_false_model, `${index} false model`);
  }
  assert.equal(fixture.cases.length, 9);
});
