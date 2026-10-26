/** Manually entered prices for workload planning; never provider billing or a spending guard. */
export type AIPriceProvider = "openai_responses" | "openai_chat" | "anthropic" | "openai_embeddings";

export interface AIPriceVersionCreate {
  vendor_label: string;
  provider: AIPriceProvider;
  model: string;
  currency: string;
  input_per_million: string;
  output_per_million: string;
  source_note: string;
  source_url: string | null;
  effective_from: string;
  effective_until: string | null;
}

export interface AIPriceVersion extends AIPriceVersionCreate {
  id: string;
  recorded_at: string;
  actor_user_id: string;
}

export interface AIPriceVersionPage {
  items: AIPriceVersion[];
  offset: number;
  limit: number;
  has_more: boolean;
  next_offset: number | null;
}

export interface AIPricePlanningItem {
  price_version_id: string;
  request_count: number;
  input_tokens_per_request: number;
  output_tokens_per_request: number;
}

export interface AIPricePlanningRequest {
  planned_for: string;
  items: AIPricePlanningItem[];
}

export interface AIPricePlanningItemResult {
  item_index: number;
  price_version: AIPriceVersion;
  request_count: number;
  input_tokens_per_request: number;
  output_tokens_per_request: number;
  exact_input_total: string;
  exact_output_total: string;
  exact_total: string;
  rounded_total: string;
  formula: string;
}

export interface AIPricePlanningResult {
  planned_for: string;
  calculated_at: string;
  calculation_version: "standard-text-v1";
  scale: 6;
  rounding: "ROUND_HALF_UP";
  items: AIPricePlanningItemResult[];
  exclusions: ("cached_input" | "tools" | "long_context" | "images_audio_video" | "tax" | "fx" | "supplier_adjustments")[];
  notice: string;
}
