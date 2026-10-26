import { assertExternalTireFactPage, createExternalApiClient } from "@tire/api-client";
import type { ExternalTireFactPage, ExternalTireFactPageRequest, ExternalTireFactProjection } from "@tire/domain-types";

declare const client: ReturnType<typeof createExternalApiClient>;
declare const request: ExternalTireFactPageRequest;
const result: Promise<ExternalTireFactPage> = client.tireFacts(request);
declare let unknownValue: unknown;
assertExternalTireFactPage(unknownValue);
const item: ExternalTireFactProjection | undefined = unknownValue.items[0];
const noRefresh: false = unknownValue.source_refresh_performed;
// @ts-expect-error A page requires the exact owned Q/V selectors.
client.tireFacts({ source_id: "source", query_id: "query" });
// @ts-expect-error The list does not accept a single-item selector.
client.tireFacts({ source_id: "source", query_id: "query", verification_id: "verification", variant_id: "variant" });
// @ts-expect-error The SDK emits an integer numeric limit.
client.tireFacts({ source_id: "source", query_id: "query", verification_id: "verification", limit: "20" });
// @ts-expect-error A page cursor is an opaque string, never a principal object.
client.tireFacts({ source_id: "source", query_id: "query", verification_id: "verification", cursor: {} });
// @ts-expect-error Projection items are not single-item result envelopes.
const wrongItem: ExternalTireFactPage["items"][number] = { status: "projected", reason: "projected", item };
// @ts-expect-error The page schema is distinct from the older external list schemas.
const wrongSchema: ExternalTireFactPage["schema"] = "external-sources@1";
void [result, item, noRefresh, wrongItem, wrongSchema];
