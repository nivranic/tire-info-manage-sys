/** External consumer compile witnesses; no runtime, network or credentials. */
import type {
  DeviceAiPrepareBody,
  DeviceAiPrepareProjectionMode,
  DeviceAiPrepareSelectorWire,
  DeviceAiProviderConsentBody,
  DeviceAiPreparationView,
  DeviceAiPrepareResultView,
  DeviceAiReferenceWire,
  DeviceAiSubmissionBody,
} from "@tire/domain-types";
import type {
  DeviceAiPrepareBody as PublicPrepare,
  DeviceAiHostClient,
  DeviceAiPreparationView as PublicPreparation,
  DeviceAiPrepareResultView as PublicPrepareResult,
  DeviceAiSubmissionBody as PublicSubmission,
} from "@tire/api-client";
import type {
  DeviceAiPrepareBody as LegacyPrepare,
  DeviceAiPreparationView as LegacyPreparation,
  DeviceAiPrepareResultView as LegacyPrepareResult,
} from "../../src/device-ai-host";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends
  (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type PublicPrepareMatchesDomain = Assert<Equal<PublicPrepare, DeviceAiPrepareBody>>;
type LegacyImportRemainsCompatible = Assert<Equal<LegacyPrepare, DeviceAiPrepareBody>>;
type PublicSubmissionMatchesDomain = Assert<Equal<PublicSubmission, DeviceAiSubmissionBody>>;
type PublicPreparationMatchesDomain = Assert<Equal<PublicPreparation, DeviceAiPreparationView>>;
type PublicPrepareResultMatchesDomain = Assert<Equal<PublicPrepareResult, DeviceAiPrepareResultView>>;
type LegacyPreparationRemainsCompatible = Assert<Equal<LegacyPreparation, DeviceAiPreparationView>>;
type LegacyPrepareResultRemainsCompatible = Assert<Equal<LegacyPrepareResult, DeviceAiPrepareResultView>>;
type LookupReturnsReadView = Assert<Equal<Awaited<ReturnType<DeviceAiHostClient["lookupPrepare"]>>, DeviceAiPreparationView>>;
type ReadReturnsReadView = Assert<Equal<Awaited<ReturnType<DeviceAiHostClient["readPrepare"]>>, DeviceAiPreparationView>>;
type PrepareReturnsPostResult = Assert<Equal<Awaited<ReturnType<DeviceAiHostClient["prepare"]>>, DeviceAiPrepareResultView>>;
type ReadHasNoPostOutcome = Assert<Equal<Extract<"replayed" | "provider_preview", keyof DeviceAiPreparationView>, never>>;
type PostReplayIsRequiredBoolean = Assert<Equal<DeviceAiPrepareResultView["replayed"], boolean>>;
type FiveReferenceKinds = Assert<Equal<DeviceAiReferenceWire["kind"],
  "tire" | "vehicle" | "test_event" | "recall" | "recall_search">>;
type FourPrepareKinds = Assert<Equal<DeviceAiPrepareSelectorWire["kind"],
  "tire" | "vehicle" | "recall" | "recall_search">>;
type FivePrepareModes = Assert<Equal<DeviceAiPrepareProjectionMode,
  "single_observation" | "frozen_decision_closure" | "complete_observation" |
  "complete_formal_observation" | "candidate_page_context">>;
type PrepareKeys = Assert<Equal<keyof DeviceAiPrepareBody,
  "package_id" | "expected_sha256" | "expected_byte_count" | "expected_schema" |
  "expected_owner_scope_id" | "selectors" | "projection_mode" | "approved_closure" |
  "expected_projection_sha256" | "question_sha256" | "host_receipt_id" | "intent_id">>;
type ConsentKeys = Assert<Equal<keyof DeviceAiProviderConsentBody,
  "expected_pack_fingerprint" | "expected_device_context_fingerprint" | "question_sha256" |
  "provider" | "model" | "expected_provider_policy_fingerprint">>;
type SubmissionKeys = Assert<Equal<keyof DeviceAiSubmissionBody,
  "prepare_id" | "host_receipt_id" | "device_context_fingerprint" | "provider_consent">>;

// Ordinary JSON strings are accepted without an unevidenced Validated<T> brand.
const prepare: PublicPrepare = {
  package_id: "synthetic-package",
  expected_sha256: "a".repeat(64),
  expected_byte_count: 128,
  expected_schema: "offline-pack@2",
  expected_owner_scope_id: "b".repeat(64),
  selectors: [{
    kind: "tire", member_key: "c".repeat(64), document_id: null, record_index: null,
    reference: { kind: "tire", snapshot_id: "snapshot", variant_id: "variant", verification_id: "receipt" },
  }],
  projection_mode: "single_observation",
  approved_closure: null,
  expected_projection_sha256: "d".repeat(64),
  question_sha256: "e".repeat(64),
  host_receipt_id: "11111111-2222-4333-8444-555555555555",
  intent_id: "22222222-3333-4444-8555-666666666666",
};
const { approved_closure: _closure, ...withoutClosure } = prepare;
// @ts-expect-error D8: the explicit null-carried key cannot disappear.
const missingClosure: DeviceAiPrepareBody = withoutClosure;
// @ts-expect-error The reference type does not grant test-event prepare access.
const restrictedKind: DeviceAiPrepareSelectorWire["kind"] = "test_event";
// @ts-expect-error complete_event_context remains outside the v1 prepare wire.
const restrictedMode: DeviceAiPrepareProjectionMode = "complete_event_context";
// @ts-expect-error Prepare exports metadata, never the plaintext question.
const plaintextQuestion: keyof DeviceAiPrepareBody = "question";
// @ts-expect-error Provider consent is separate from Host export/prepare.
const prematureConsent: keyof DeviceAiPrepareBody = "provider_consent";
// @ts-expect-error Personal context is a future protocol obligation.
const personalContext: keyof DeviceAiPrepareBody = "include_context_ids";
// @ts-expect-error The historical draft's device_binding wrapper is not a wire key.
const historicalWrapper: keyof DeviceAiPrepareBody = "device_binding";
// @ts-expect-error The consent six-tuple is not a generic authorization grant.
const genericGrant: keyof DeviceAiProviderConsentBody = "allow_external_processing";

declare const readPreparation: DeviceAiPreparationView;
declare const prepareResult: DeviceAiPrepareResultView;
const preparationFromPost: DeviceAiPreparationView = prepareResult;
// @ts-expect-error A GET view carries no POST replay outcome.
const resultFromRead: DeviceAiPrepareResultView = readPreparation;
// @ts-expect-error Reading a preparation does not promise a replayed boolean.
const inventedReplayState: boolean = readPreparation.replayed;
