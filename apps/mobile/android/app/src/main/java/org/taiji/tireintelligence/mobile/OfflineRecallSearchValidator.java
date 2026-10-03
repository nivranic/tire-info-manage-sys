package org.taiji.tireintelligence.mobile;

import java.math.BigInteger;
import java.net.URI;
import java.time.OffsetDateTime;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Frozen candidate pages only. Never adopts campaigns or fetches a document URL. */
final class OfflineRecallSearchValidator {
    private static final String[] NOTICES = {
        "本页为美国 NHTSA 轮胎产品目录检索候选，未采纳为召回公告版本。",
        "名称和尺寸匹配不确认具体 SKU 或实物适用；须核对 DOT/TIN、生产批次及官方措施。",
        "仅显示当前页；本页没有召回不表示其他页、其他地区或具体轮胎无召回风险。"
    };
    private static void require(boolean valid) throws NativeFailure { OfflinePackageValidator.require(valid); }
    private static String text(JSONObject row, String key) throws NativeFailure {
        String value = OfflinePackageValidator.text(row, key, 60000);
        require(value.indexOf('\u0000') < 0);
        return value;
    }
    private static void nullableText(JSONObject row, String key) throws NativeFailure {
        require(row.has(key)); if (!row.isNull(key)) text(row, key);
    }
    private static String positiveInteger(JSONObject row, String key) throws NativeFailure {
        Object value = row.opt(key);
        BigInteger integer = OfflineJsonInteger.integer(value);
        require(integer != null && integer.signum() > 0);
        return integer.toString();
    }
    static int canonicalOffset(JSONObject query) throws NativeFailure {
        String offset = OfflinePackageValidator.text(query, "offset", 5);
        require(offset.matches("0|[1-9][0-9]{0,4}"));
        int value = Integer.parseInt(offset); require(value <= 10000 && value % 10 == 0);
        return value;
    }
    static void query(JSONObject query) throws NativeFailure {
        OfflinePackageValidator.keys(query, "search", "offset");
        String search = OfflinePackageValidator.text(query, "search", 240);
        require(search.codePointCount(0, search.length()) >= 1 && search.codePointCount(0, search.length()) <= 120
            && search.codePoints().noneMatch(cp -> cp < 32));
        StringBuilder canonical = new StringBuilder(); boolean pending = false;
        for (int at = 0; at < search.length();) {
            int codepoint = search.codePointAt(at); at += Character.charCount(codepoint);
            if (OfflineFilterUnicode.isWhitespace(codepoint)) { pending = canonical.length() > 0; continue; }
            if (pending) canonical.append(' ');
            canonical.appendCodePoint(codepoint); pending = false;
        }
        require(search.equals(canonical.toString())); canonicalOffset(query);
    }
    static void validate(JSONObject payload, JSONObject reference, JSONObject source) throws NativeFailure {
        OfflinePackageValidator.keys(payload, "query", "discovery", "discovery_hash", "evidence",
            "empty_observation", "notices", "boundary");
        JSONObject query = OfflinePackageValidator.object(payload, "query"); query(query);
        OfflinePackageValidator.hash(payload, "discovery_hash");
        OfflinePackageValidator.equal(source, "source_id", "nhtsa-us-recalls");
        JSONObject evidence = OfflinePackageValidator.object(payload, "evidence");
        OfflinePackageValidator.keys(evidence, "snapshot_id", "query_id", "verification_id", "data_state", "observed_at", "verified_at");
        OfflinePackageValidator.equal(evidence, "snapshot_id", OfflinePackageValidator.uuid(reference, "snapshot_id"));
        OfflinePackageValidator.equal(evidence, "verification_id", OfflinePackageValidator.uuid(reference, "verification_id"));
        OfflinePackageValidator.uuid(evidence, "query_id");
        OfflinePackageValidator.equal(evidence, "data_state", "local_snapshot");
        for (String key : new String[]{"observed_at", "verified_at"}) {
            String time = OfflinePackageValidator.text(evidence, key, 80);
            try { OffsetDateTime.parse(time); } catch (Exception invalid) { require(false); }
            OfflinePackageValidator.equal(source, key, time);
        }
        JSONObject boundary = OfflinePackageValidator.object(payload, "boundary");
        OfflinePackageValidator.keys(boundary, "kind", "formal_campaign_revision", "applicability", "complete_query_result");
        OfflinePackageValidator.equal(boundary, "kind", "recall_search_candidate_page");
        OfflinePackageValidator.equal(boundary, "formal_campaign_revision", false);
        OfflinePackageValidator.equal(boundary, "applicability", "not_assessed");
        OfflinePackageValidator.equal(boundary, "complete_query_result", false);
        JSONArray notices = OfflinePackageValidator.array(payload, "notices", 3);
        require(notices.length() == 3);
        for (int at = 0; at < 3; at++) require(NOTICES[at].equals(notices.opt(at)));
        JSONObject discovery = OfflinePackageValidator.object(payload, "discovery");
        OfflinePackageValidator.keys(discovery, "products", "pagination");
        JSONArray products = OfflinePackageValidator.array(discovery, "products", 10);
        OfflinePackageValidator.equal(payload, "empty_observation", products.length() == 0);
        JSONObject pagination = OfflinePackageValidator.object(discovery, "pagination");
        OfflinePackageValidator.keys(pagination, "offset", "max", "count", "total", "has_next", "has_previous");
        long offset = OfflinePackageValidator.number(pagination, "offset", 10000);
        require(offset == canonicalOffset(query));
        require(OfflinePackageValidator.number(pagination, "max", 10) == 10);
        require(OfflinePackageValidator.number(pagination, "count", 10) == products.length());
        long total = OfflinePackageValidator.number(pagination, "total", 10000000);
        require(products.length() == Math.min(10, Math.max(0, total - offset)));
        OfflinePackageValidator.equal(pagination, "has_next", offset + products.length() < total);
        OfflinePackageValidator.equal(pagination, "has_previous", offset > 0);
        Set<String> productIds = new HashSet<>();
        for (int at = 0; at < products.length(); at++) {
            JSONObject product = OfflinePackageValidator.at(products, at);
            OfflinePackageValidator.keys(product, "id", "artemis_id", "brand", "tireline", "size", "recalls_count", "campaigns", "applicability");
            require(productIds.add(positiveInteger(product, "id"))); positiveInteger(product, "artemis_id");
            require(!OfflineFilterUnicode.blank(text(product, "brand")) && !OfflineFilterUnicode.blank(text(product, "tireline")));
            nullableText(product, "size"); OfflinePackageValidator.equal(product, "applicability", "not_assessed");
            JSONArray campaigns = OfflinePackageValidator.array(product, "campaigns", 1000);
            require(OfflinePackageValidator.number(product, "recalls_count", 1000) == campaigns.length());
            Set<String> campaignIds = new HashSet<>();
            for (int campaignIndex = 0; campaignIndex < campaigns.length(); campaignIndex++) {
                JSONObject campaign = OfflinePackageValidator.at(campaigns, campaignIndex);
                OfflinePackageValidator.keys(campaign, "campaign_number", "subject", "report_received_at", "summary",
                    "consequence", "remedy", "manufacturer", "notes", "documents", "associated_products");
                String number = text(campaign, "campaign_number");
                require(number.matches("[0-9]{2}T[0-9]{6}") && campaignIds.add(number));
                nullableText(campaign, "subject"); nullableText(campaign, "notes");
                for (String key : new String[]{"summary", "consequence", "remedy", "manufacturer"}) text(campaign, key);
                String date = text(campaign, "report_received_at");
                try { require(date.endsWith("Z")); OffsetDateTime.parse(date); } catch (Exception invalid) { require(false); }
                JSONArray associated = OfflinePackageValidator.array(campaign, "associated_products", 1000);
                for (int item = 0; item < associated.length(); item++) OfflinePackageValidator.at(associated, item);
                JSONArray documents = OfflinePackageValidator.array(campaign, "documents", 1000);
                for (int item = 0; item < documents.length(); item++) {
                    JSONObject document = OfflinePackageValidator.at(documents, item);
                    OfflinePackageValidator.keys(document, "url", "title"); nullableText(document, "title");
                    String url = OfflinePackageValidator.text(document, "url", 8192);
                    try {
                        URI parsed = new URI(url);
                        require("https".equals(parsed.getScheme()) && "static.nhtsa.gov".equals(parsed.getRawAuthority())
                            && parsed.getRawQuery() == null && parsed.getRawFragment() == null
                            && parsed.getRawPath().matches("/odi/rcl/[0-9]{4}/[A-Za-z0-9_-]+\\.(?:pdf|PDF)"));
                    } catch (Exception invalid) { require(false); }
                }
            }
        }
    }
}
