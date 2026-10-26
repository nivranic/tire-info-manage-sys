import { tireApi } from "@tire/api-client";
import type {
  AIRuleDraftPack, AlertRuleSettings, LocalNotification, SourcePageUrlMove,
  SourcePageUrlMoveNotification, SourcePageUrlMoveNotificationDetail,
  SourcePageUrlMoveNotificationRead, SourcePageUrlMoveNotifications, SourcePageUrlMoveSide,
} from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type ListResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.sourcePageUrlMoveNotifications>>, SourcePageUrlMoveNotifications>>;
type DetailResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.sourcePageUrlMoveNotification>>, SourcePageUrlMoveNotificationDetail>>;
type ReadResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.markSourcePageUrlMoveNotification>>, SourcePageUrlMoveNotificationRead>>;
type History = Assert<Equal<SourcePageUrlMoveNotifications["data_state"], "local_snapshot">>;
type Shared = Assert<Equal<SourcePageUrlMoveNotificationDetail["scope"], "local_workspace">>;

declare const side: SourcePageUrlMoveSide;
declare const event: SourcePageUrlMove;
declare const notice: SourcePageUrlMoveNotification;
const urlKind: AlertRuleSettings["kinds"] = ["url_moved"];
// @ts-expect-error URL moves are not SKU events and cannot enter old notification/AI explanation contracts.
const oldKind: LocalNotification["kind"] = "url_moved";
// @ts-expect-error Frozen AI capability kinds remain the original two kinds.
const aiKind: AIRuleDraftPack["capabilities"]["kinds"][number] = "url_moved";
// @ts-expect-error A move never compares content, so its sides carry no raw hash.
const fakeHash: SourcePageUrlMoveSide = { ...side, raw_hash: "a".repeat(64) };
// @ts-expect-error The independent move event must not grow a fake SKU identity.
const fakeSku: SourcePageUrlMove = { ...event, variant_id: "variant" };
// @ts-expect-error Move notifications contain no parameter diff.
const fakeDiff: SourcePageUrlMoveNotification = { ...notice, changes: {} };
// @ts-expect-error The shared history envelope must not claim private ownership.
const privateScope: SourcePageUrlMoveNotificationDetail = { scope: "current_account", data_state: "local_snapshot", item: notice };
