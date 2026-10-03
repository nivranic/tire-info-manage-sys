package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Runs the frozen Python oracle on the actual Android numeric/Unicode runtime. */
@RunWith(AndroidJUnit4.class)
public final class OfflineTireCriteriaTest {
    @Test public void sourceDrivenAllFieldVectorsMatch() throws Exception {
        runReference("reference.json", true);
    }
    @Test public void sourceDrivenUnicodeDigitVectorsMatch() throws Exception {
        runReference("extra.json", false);
    }
    private static void runReference(String filename, boolean primary) throws Exception {
        JSONObject fixture;
        try (InputStream stream = InstrumentationRegistry.getInstrumentation().getContext().getAssets()
                .open("query-filters49/" + filename)) {
            fixture = new JSONObject(new String(stream.readAllBytes(), StandardCharsets.UTF_8));
        }
        assertEquals("tire-query-filter-reference@1", fixture.getString("schema"));
        assertEquals(28, fixture.getJSONObject("catalog").getJSONArray("fields").length());
        assertEquals(16, fixture.getJSONObject("catalog").getInt("max_conditions"));
        JSONArray cases = fixture.getJSONArray("cases");
        Set<String> covered = new HashSet<>();
        int comparedRows = 0, rejectedCases = 0;
        for (int at = 0; at < cases.length(); at++) {
            JSONObject test = cases.getJSONObject(at);
            String id = test.getString("id");
            JSONArray input = (JSONArray) OfflineTireCriteria.parse(test.getString("input_filters_json"));
            if (!test.isNull("validation_error")) {
                try { OfflineTireCriteria.validateFilters(input); fail("Accepted invalid filters: " + id); }
                catch (IllegalArgumentException expected) { rejectedCases++; }
                continue;
            }
            OfflineTireCriteria.validateFilters(input);
            JSONArray filters = OfflineTireCriteria.validateFilters((JSONArray)
                OfflineTireCriteria.parse(test.getString("canonical_filters_json")));
            for (int filter = 0; filter < filters.length(); filter++) covered.add(filters.getJSONObject(filter).getString("field"));
            JSONArray rows = (JSONArray) OfflineTireCriteria.parse(test.getString("rows_json"));
            JSONObject expected = test.getJSONObject("expected").getJSONObject("selection");
            JSONArray matchedIndexes = test.getJSONObject("expected").getJSONArray("matched_row_indexes");
            JSONArray actualIndexes = new JSONArray();
            int matched = 0, excluded = 0, unknown = 0;
            for (int rowIndex = 0; rowIndex < rows.length(); rowIndex++) {
                JSONObject row = rows.getJSONObject(rowIndex);
                OfflineTireCriteria.Truth result = OfflineTireCriteria.evaluate(row, filters);
                if (result == OfflineTireCriteria.Truth.TRUE) { matched++; actualIndexes.put(rowIndex); }
                else if (result == OfflineTireCriteria.Truth.FALSE) excluded++;
                else unknown++;
                comparedRows++;
            }
            assertEquals(id + " matched_row_indexes", matchedIndexes.toString(), actualIndexes.toString());
            assertEquals(id + " source_count", expected.getInt("source_count"), rows.length());
            assertEquals(id + " matched_count", expected.getInt("matched_count"), matched);
            assertEquals(id + " excluded_count", expected.getInt("excluded_count"), excluded);
            assertEquals(id + " undetermined_count", expected.getInt("undetermined_count"), unknown);
        }
        if (primary) assertEquals("Every original field must be evaluated", 28, covered.size());
        assertTrue("Reference contains meaningful row coverage", comparedRows >= 100);
        assertTrue("Invalid typed requests must be covered", rejectedCases > 0);
    }

    @Test public void fullCasefoldAndCategoryBoundaries() {
        assertEquals("strasse σσ i\u0307 ı ffi", OfflineFilterUnicode.text("ＳＴＲＡＳＳＥ Σς İ ı ﬃ"));
        assertEquals("Ꭰ", OfflineFilterUnicode.text("ꭰ"));
        try { OfflineFilterUnicode.text("x\u200b"); fail("Invisible category C accepted"); }
        catch (IllegalArgumentException expected) { }
    }

    @Test public void integerPrecisionAndBinaryFloatBoundary() throws Exception {
        assertEquals(OfflineTireCriteria.Truth.FALSE, OfflineTireCriteria.evaluateVariantJson(
            "{\"facts\":{\"utqg_treadwear\":9007199254740993}}",
            "[{\"field\":\"utqg_treadwear\",\"op\":\"eq\",\"value\":9007199254740992}]"));
        assertEquals(OfflineTireCriteria.Truth.TRUE, OfflineTireCriteria.evaluateVariantJson(
            "{\"facts\":{\"utqg_treadwear\":1000000000000000000000000000000000000001}}",
            "[{\"field\":\"utqg_treadwear\",\"op\":\"gte\",\"value\":1000000000000000000000000000000000000000}]"));
        assertEquals(OfflineTireCriteria.Truth.FALSE, OfflineTireCriteria.evaluateVariantJson(
            "{\"facts\":{\"utqg_treadwear\":100000000000000000000000}}",
            "[{\"field\":\"utqg_treadwear\",\"op\":\"eq\",\"value\":1e23}]"));
    }

    @Test public void duplicateAndMalformedJsonFailClosed() throws Exception {
        for (String bad : new String[]{"{\"facts\":{},\"facts\":{}}", "[01]", "{} {}", "{\"a\":NaN}"}) {
            try { OfflineTireCriteria.parse(bad); fail("Malformed JSON accepted: " + bad); }
            catch (Exception expected) { }
        }
    }
}
