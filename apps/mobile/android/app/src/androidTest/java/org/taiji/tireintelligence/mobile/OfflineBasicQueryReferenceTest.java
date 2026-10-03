package org.taiji.tireintelligence.mobile;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Python TireQuery versus TireFilter oracle: basic rim spelling must not gain NFKC. */
@RunWith(AndroidJUnit4.class)
public final class OfflineBasicQueryReferenceTest {
    @Test public void allNinePythonCasesPreserveRawBasicSizeAndThreeValueAnd() throws Exception {
        JSONObject oracle;
        try (InputStream input = InstrumentationRegistry.getInstrumentation().getContext().getAssets()
            .open("query-filters49/basic-query-reference.json")) {
            byte[] bytes = input.readAllBytes();
            assertEquals("6f24f172069cbdb94c660ab68584700a181cded81df88370e51012297a676cf6", OfflineCipher.sha256(bytes));
            oracle = (JSONObject) OfflineTireCriteria.parse(new String(bytes, StandardCharsets.UTF_8));
        }
        JSONArray cases = oracle.getJSONArray("cases"); assertEquals(9, cases.length());
        for (int at = 0; at < cases.length(); at++) {
            JSONObject test = cases.getJSONObject(at), row = test.getJSONObject("row"), query = test.getJSONObject("canonical_query");
            String raw = test.getJSONObject("draft_query").getString("size");
            assertEquals(query.getString("size"), OfflineFallbackValues.canonicalTireSize(raw));
            OfflineTireCriteria.Truth basic = OfflineTireCriteria.evaluateBasicSize(row, query.getString("size"));
            assertEquals("basic case " + at, test.isNull("basic_match") ? OfflineTireCriteria.Truth.UNKNOWN
                : test.getBoolean("basic_match") ? OfflineTireCriteria.Truth.TRUE : OfflineTireCriteria.Truth.FALSE, basic);
            JSONArray filters = new JSONArray().put(test.getJSONObject("advanced_filter"));
            OfflineTireCriteria.Truth advanced = OfflineTireCriteria.evaluate(row, OfflineTireCriteria.validateFilters(filters));
            assertEquals("advanced case " + at, test.isNull("advanced_match") ? OfflineTireCriteria.Truth.UNKNOWN
                : test.getBoolean("advanced_match") ? OfflineTireCriteria.Truth.TRUE : OfflineTireCriteria.Truth.FALSE, advanced);
            JSONObject member = new JSONObject().put("reference", new JSONObject().put("kind", "tire"))
                .put("source", new JSONObject().put("source_id", "fixture"))
                .put("payload", new JSONObject().put("variant", row));
            JSONObject material = new JSONObject().put("schema", "offline-pack@2").put("members", new JSONArray().put(member));
            JSONObject intent = new JSONObject().put("query_kind", "tire").put("source_id", "fixture")
                .put("query", new JSONObject().put("model", "Different model").put("size", query.getString("size")))
                .put("filters", new JSONArray());
            JSONObject counts = OfflineFallbackSelection.select(material, intent).getJSONObject("selection");
            assertEquals("false model wins over unknown size " + at, 1, counts.getInt("excluded_count"));
            assertEquals(0, counts.getInt("undetermined_count"));
        }
    }
}
