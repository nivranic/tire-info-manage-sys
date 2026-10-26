import { tireApi } from "@tire/api-client";
import type {
  AIRuleDraftPack, AlertRuleSettings, LocalNotification, SourcePageChange,
  SourcePageEvidenceSide, SourcePageNotification, SourcePageNotificationDetail,
  SourcePageNotificationRead, SourcePageNotifications,
} from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type ListResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.sourcePageNotifications>>, SourcePageNotifications>>;
type DetailResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.sourcePageNotification>>, SourcePageNotificationDetail>>;
type ReadResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.markSourcePageNotification>>, SourcePageNotificationRead>>;
type History = Assert<Equal<SourcePageNotifications["data_state"], "local_snapshot">>;
type Shared = Assert<Equal<SourcePageNotificationDetail["scope"], "local_workspace">>;

declare const side: SourcePageEvidenceSide;
declare const event: SourcePageChange;
declare const notice: SourcePageNotification;
const pageKind: AlertRuleSettings["kinds"] = ["page_changed"];
// @ts-expect-error Page events are not SKU events and cannot enter old notification/AI explanation contracts.
const oldKind: LocalNotification["kind"] = "page_changed";
// @ts-expect-error Frozen AI capability kinds remain the original two kinds.
const aiKind: AIRuleDraftPack["capabilities"]["kinds"][number] = "page_changed";
// @ts-expect-error Evidence references are required; no alternate snapshot may be guessed.
const absentSnapshot: SourcePageEvidenceSide = { ...side, snapshot_id: null };
// @ts-expect-error The independent page event must not grow a fake SKU identity.
const fakeSku: SourcePageChange = { ...event, variant_id: "variant" };
// @ts-expect-error Page notifications contain no parameter diff.
const fakeDiff: SourcePageNotification = { ...notice, changes: {} };
// @ts-expect-error The shared history envelope must not claim private ownership.
const privateScope: SourcePageNotificationDetail = { scope: "current_account", data_state: "local_snapshot", item: notice };
