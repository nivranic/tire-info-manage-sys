export type TireFilterOperator = "eq" | "gte" | "lte" | "is_known" | "is_unknown";
/** Device criteria preserve a JSON number before any JavaScript Number projection. */
export interface ExactNumericToken {
  readonly token: string;
  readonly kind: "integer" | "float";
  readonly integer: bigint | null;
  readonly float: number | null;
  toString(): string;
}
export type TireFilterValue = string | number | boolean | ExactNumericToken;

export interface TireFilter {
  field: string;
  op: TireFilterOperator;
  value?: TireFilterValue;
}

export interface TireFilterField {
  key: string;
  label: string;
  type: "text" | "number" | "boolean";
  operators: TireFilterOperator[];
  unit?: string;
  options?: { value: TireFilterValue; label: string }[];
  description?: string;
}

export interface TireFilterCatalog {
  version: "tire-query-filters@1";
  max_conditions: number;
  fields: TireFilterField[];
  notice: string;
}

export interface TireQuerySelection {
  filters: TireFilter[];
  source_count: number | null;
  matched_count: number | null;
  excluded_count: number | null;
  undetermined_count: number | null;
}
