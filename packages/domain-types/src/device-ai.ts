/**
 * Device AI @1 contracts implemented by the existing closed decoders.
 *
 * These declarations describe the current SDK/server shapes, not the historical
 * public-types draft. Runtime decoders still enforce key closure, bounded values,
 * modes, ownership and consent. Types and this freeze record grant no permission
 * and make no claim about complete V1, real Provider or platform acceptance.
 */

export interface DeviceAiTireReferenceWire {
  kind: "tire";
  snapshot_id: string;
  variant_id: string;
  verification_id: string;
}
export interface DeviceAiVehicleReferenceWire {
  kind: "vehicle";
  snapshot_id: string;
  verification_id: string;
}
export interface DeviceAiRecallReferenceWire {
  kind: "recall";
  snapshot_id: string;
  recall_revision_id: string | null;
  verification_id: string;
}
export interface DeviceAiRecallSearchReferenceWire {
  kind: "recall_search";
  snapshot_id: string;
  verification_id: string;
}
/** Reference/input shape only; @1 projection and prepare reject this restricted domain. */
export interface DeviceAiTestEventReferenceWire {
  kind: "test_event";
  event_id: string;
  event_revision: number;
}
export type DeviceAiReferenceWire =
  | DeviceAiTireReferenceWire
  | DeviceAiVehicleReferenceWire
  | DeviceAiRecallReferenceWire
  | DeviceAiRecallSearchReferenceWire
  | DeviceAiTestEventReferenceWire;

export interface DeviceAiTireSelectorWire {
  kind: "tire";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiTireReferenceWire;
}
export interface DeviceAiVehicleSelectorWire {
  kind: "vehicle";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiVehicleReferenceWire;
}
export interface DeviceAiRecallSelectorWire {
  kind: "recall";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiRecallReferenceWire;
}
export interface DeviceAiRecallSearchSelectorWire {
  kind: "recall_search";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiRecallSearchReferenceWire;
}
/** General projection input; runtime checks correlate kind and reference. */
export interface DeviceAiSelectorWire {
  kind: DeviceAiReferenceWire["kind"];
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiReferenceWire;
}

/** Only the four domains accepted by the current server prepare DTO. */
export type DeviceAiPrepareSelectorWire =
  | DeviceAiTireSelectorWire
  | DeviceAiVehicleSelectorWire
  | DeviceAiRecallSelectorWire
  | DeviceAiRecallSearchSelectorWire;
export type DeviceAiPrepareProjectionMode =
  | "single_observation"
  | "frozen_decision_closure"
  | "complete_observation"
  | "complete_formal_observation"
  | "candidate_page_context";
/** Pure projection includes the test-event mode so its rejection is representable. */
export type DeviceAiProjectionMode =
  | DeviceAiPrepareProjectionMode
  | "complete_event_context";

/** Host metadata binding; this is not an installation attestation or API body. */
export interface DeviceAiOriginBindingWire {
  expected_profile_id: string;
  expected_owner_epoch: number;
  slot_id: string;
  expected_generation: number;
  package_id: string;
  expected_sha256: string;
  expected_byte_count: number;
  owner_scope_id: string;
  package_schema: "offline-pack@1" | "offline-pack@2";
}

/** Exact twelve-key body of POST /v1/ai/device-evidence-packs. */
export type DeviceAiPrepareBody = {
  package_id: string;
  expected_sha256: string;
  expected_byte_count: number;
  expected_schema: "offline-pack@1" | "offline-pack@2";
  expected_owner_scope_id: string;
  selectors: DeviceAiPrepareSelectorWire[];
  projection_mode: DeviceAiPrepareProjectionMode;
  /** Explicit null outside closure mode; runtime checks closure equality and limits. */
  approved_closure: DeviceAiPrepareSelectorWire[] | null;
  expected_projection_sha256: string;
  question_sha256: string;
  host_receipt_id: string;
  intent_id: string;
};
/** Independent Provider consent echo; authoritative values are checked server-side. */
export interface DeviceAiProviderConsentBody {
  expected_pack_fingerprint: string;
  expected_device_context_fingerprint: string;
  question_sha256: string;
  provider: string;
  model: string;
  expected_provider_policy_fingerprint: string;
}
/** Exact device_submission subobject of the existing analysis request. */
export interface DeviceAiSubmissionBody {
  prepare_id: string;
  host_receipt_id: string;
  device_context_fingerprint: string;
  provider_consent: DeviceAiProviderConsentBody;
}
/** SDK orchestration input; submitStream nests device fields before HTTP dispatch. */
export interface DeviceAiStreamSubmission {
  pack_id: string;
  /** Raw question text; the SDK normalizes it once before dispatch. */
  question: string;
  prepare_id: string;
  host_receipt_id: string;
  device_context_fingerprint: string;
  provider_consent: DeviceAiProviderConsentBody;
}
/** Shared preparation read view; opaque nested objects are not closed schemas. */
export interface DeviceAiPreparationView {
  id: string;
  created_at: string;
  expires_at: string;
  expired: boolean;
  idempotency_key: string;
  host_receipt_id: string;
  intent_id: string;
  pack_id: string;
  offline_pack_id: string;
  question_sha256: string;
  selection_sha256: string;
  projection_sha256: string;
  projection_byte_count: number;
  device_context_fingerprint: string;
  request_hash: string;
  contract: Record<string, unknown>;
  pack: Record<string, unknown>;
}
/** POST preparation result; GET read/lookup responses carry no replay outcome. */
export interface DeviceAiPrepareResultView extends DeviceAiPreparationView {
  replayed: boolean;
  /** Fresh creation only; replay responses omit this field. */
  provider_preview?: Record<string, unknown>;
}

/**
 * Freeze record for product code contracts, not an outbound payload or a runtime
 * capability probe. ADR-052/053 govern decoder tolerances and immutable vectors.
 * A future mixed-domain or personal-context protocol requires @2; @1 stays closed.
 */
export const DEVICE_AI_WIRE_CONTRACT = {
  schema: "device-ai-wire-contract@1",
  wire_frozen: true,
  basis: "implemented_closed_dtos_and_host_decoders",
  decisions: ["ADR-2026-052", "ADR-2026-053"],
  frozen_surfaces: {
    prepare_body: "12_explicit_keys_including_closed_selector_and_reference_objects",
    provider_consent: "6_explicit_keys",
    device_submission: "4_explicit_keys",
  },
  response_view: "minimum_checked_sdk_view_nested_payload_not_frozen",
  excluded_surfaces: [
    "historical_draft_host_commands",
    "sdk_ast_crypto_journal_and_preview_implementation_types",
    "opaque_contract_pack_and_provider_preview_payloads",
  ],
  remaining_shared_type_obligations: ["value_encoding", "device_citations"],
  reference_kinds: ["tire", "vehicle", "recall", "recall_search", "test_event"],
  prepare_kinds: ["tire", "vehicle", "recall", "recall_search"],
  prepare_modes: [
    "single_observation", "frozen_decision_closure", "complete_observation",
    "complete_formal_observation", "candidate_page_context",
  ],
  package_schemas: ["offline-pack@1", "offline-pack@2"],
  limits: {
    package_bytes: 8_388_608,
    requested_selectors: 6,
    approved_closure_selectors: 6,
    projection_bytes: 44_000,
  },
  rules: {
    request_fields: "explicit_presence_unknown_keys_rejected",
    non_closure_approved_closure: "explicit_null",
    closure: "explicit_exact_set_recomputed_from_actor_owned_original_bytes",
    test_event: "reference_shape_only_restricted_projection_and_prepare_rejected",
    mixed_domain: "not_supported_requires_device_ai_selection_v2",
    personal_context: "empty_only_requires_v2_to_enable",
    host_receipt: "client_metadata_not_server_authorization_or_installation_proof",
  },
  acceptance: {
    declaration_only: true,
    runtime_acceptance_claimed: false,
    real_provider_acceptance_claimed: false,
    all_platform_acceptance_claimed: false,
    complete_v1_acceptance_claimed: false,
  },
} as const;
