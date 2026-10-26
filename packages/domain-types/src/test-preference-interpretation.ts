import type { DrivingWeightKey, DrivingWeights, TestEventPayload, TestMeasurement, TestMetricDefinition, TestParticipant } from "./index";

export interface TestMetricDimension {
  metric_key: string;
  dimension: DrivingWeightKey | null;
}

/** One calculation over a current event and the actor's current saved preferences. */
export interface TestPreferenceInterpretationRequest {
  expected_event_revision: number;
  expected_event_fingerprint: string;
  expected_preference_revision: number;
  expected_preference_fingerprint: string;
  participant_ids: string[];
  metric_dimensions: TestMetricDimension[];
}

export interface TestMeasurementReference {
  event_id: string;
  revision: number;
  participant_id: string;
  metric_key: string;
}

export type TestPreferenceLimitation = "excluded_by_user" | "missing_measurements" | "direction_unspecified" | "insufficient_observations";
export type TestPreferenceInterpretationErrorCode = "test_event_not_found" | "test_event_revoked" | "test_event_changed"
  | "driving_preference_missing" | "driving_preference_changed" | "invalid_preference_interpretation";

export interface TestPreferenceInterpretation {
  schema: "test-preference-interpretation@1";
  data_state: "local_snapshot";
  scope: "actor";
  evidence_scope: "local_workspace";
  comparison_scope: "same_event_only";
  ranking: "source_reported_only";
  policy_version: "same-event-preference@1";
  binding: {
    event: { id: string; revision_id: string; revision: number; fingerprint: string };
    preference: { revision: number; fingerprint: string };
    interpretation_fingerprint: string;
  };
  source_evidence: {
    event: Omit<TestEventPayload, "participants" | "metrics" | "measurements">;
    participants: (TestParticipant & { id: string; identity_status: "participant_only" })[];
    metrics: TestMetricDefinition[];
    measurements: (TestMeasurement & { participant_id: string; evidence_id: string; reference: TestMeasurementReference })[];
    record_kind: "manual_transcription";
    verification_status: "unverified";
    verified_at: null;
    recorded_at: string;
    recorded_participant_count: number;
    selected_participant_count: number;
  };
  personal_interpretation: {
    mapping_origin: "user_explicit_once";
    weights: DrivingWeights;
    metric_dimensions: TestMetricDimension[];
    dimensions: {
      dimension: DrivingWeightKey;
      weight: number;
      metric_keys: string[];
      complete_comparable_metric_keys: string[];
    }[];
    metrics: {
      metric_key: string;
      dimension: DrivingWeightKey | null;
      observed_participant_ids: string[];
      missing_participant_ids: string[];
      evidence_ids: string[];
      limitations: TestPreferenceLimitation[];
      complete_comparable: boolean;
      observation_comparison: {
        scope: "selected_recorded_observations";
        favorable_participant_ids: string[];
        evidence_ids: string[];
      } | null;
    }[];
    coverage: {
      mapped_weight: number;
      fully_comparable_weight: number;
      unmapped_weight: number;
      mapped_not_fully_comparable_weight: number;
    };
  };
  notices: string[];
}
