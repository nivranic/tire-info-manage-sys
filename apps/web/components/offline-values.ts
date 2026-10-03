import type { OfflineContext, OfflineDocumentV2 as OfflineDocument, AnyOfflineEnvelope as OfflineEnvelope, OfflineInstallRequest, OfflineMemberV2 as OfflineMember, AnyOfflinePackDescriptor as OfflinePackDescriptor,
  OfflineReadRequest, OfflineReadResult, OfflineScope, OfflineSearchRequest, OfflineSearchResult, OfflineSlot } from "@tire/domain-types";
import { MAX_OFFLINE_BYTES, OfflineError, offlineSha256, parseOfflineJson } from "./offline-crypto";
import { ExactJsonNumber, exactSafeInteger, materializeExactMetadata, parseExactJson, canonicalDeviceQuery, stableExactDeviceJson } from "@tire/api-client";

function fail(): never { throw new OfflineError("OFFLINE_INVALID_PACK"); }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const hash = /^[0-9a-f]{64}$/;
const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) && !(value instanceof ExactJsonNumber) ? value as Record<string, unknown> : fail();
function shape(value: unknown, required: string[], optional: string[] = []) {
  const row = object(value), allowed = new Set([...required, ...optional]);
  if (required.some(key => !Object.hasOwn(row, key)) || Object.keys(row).some(key => !allowed.has(key))) fail();
  return row;
}
const text = (value: unknown, nullable = false): void => { if (nullable && value === null) return; if (typeof value !== "string") fail(); };
const id = (value: unknown): void => { if (typeof value !== "string" || !value || value.length > 200) fail(); };
const number = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): void => { try { exactSafeInteger(value, min, max); } catch { fail(); } };
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : fail();
const oneOf = (value: unknown, allowed: readonly unknown[]) => { if (!allowed.includes(value)) fail(); };
const date = (value: unknown, nullable = false) => { if (nullable && value === null) return; if (typeof value !== "string" || !/^\d{4}-\d\d-\d\dT/.test(value) || !Number.isFinite(Date.parse(value))) fail(); };
const digest = (value: unknown, nullable = false) => { if (nullable && value === null) return; if (typeof value !== "string" || !hash.test(value)) fail(); };
const identifier = (value: unknown, nullable = false) => { if (nullable && value === null) return; if (typeof value !== "string" || !uuid.test(value)) fail(); };
const privacy = (value: unknown, publicAllowed = true) => oneOf(value, publicAllowed ? ["public", "private", "restricted"] : ["private", "restricted"]);
const equal = (first: unknown, second: unknown) => { if (first instanceof ExactJsonNumber) { if (exactSafeInteger(first) !== second) fail(); } else if (first !== second) fail(); };

export function defaultOfflineScope(): OfflineScope {
  return { garage: { include: true, vehicle_ids: null }, watchlist: { include: true, item_ids: null }, recent: { include: true, limit: 20 }, references: [] };
}

function reference(value: unknown, resolved: boolean, v2 = false) {
  const row = object(value);
  const fields = row.kind === "tire" ? ["kind", "snapshot_id", "variant_id"] : row.kind === "vehicle" ? ["kind", "snapshot_id"]
    : row.kind === "test_event" ? ["kind", "event_id", "event_revision"] : row.kind === "recall" ? ["kind", "snapshot_id", "recall_revision_id"] : v2 && row.kind === "recall_search" ? ["kind", "snapshot_id", "verification_id"] : fail();
  shape(row, resolved && row.kind !== "test_event" && row.kind !== "recall_search" ? [...fields, "verification_id"] : fields, row.kind !== "test_event" && row.kind !== "recall_search" && !resolved ? ["verification_id"] : []);
  if (row.kind === "test_event") { id(row.event_id); number(row.event_revision, 1); }
  else { id(row.snapshot_id); if (row.verification_id !== undefined) id(row.verification_id); }
  if (row.kind === "tire") id(row.variant_id);
  if (row.kind === "recall" && row.recall_revision_id !== null) id(row.recall_revision_id);
  return row;
}

function scope(value: unknown, v2 = false) {
  const row = shape(value, ["garage", "watchlist", "recent", "references"]);
  for (const [key, ids] of [["garage", "vehicle_ids"], ["watchlist", "item_ids"]]) {
    const group = shape(row[key], ["include", ids]);
    if (typeof group.include !== "boolean") fail();
    if (group[ids] !== null) { const values = list(group[ids]); if (values.length > 1000) fail(); values.forEach(value => id(value)); }
  }
  const recent = shape(row.recent, ["include", "limit"]);
  if (typeof recent.include !== "boolean") fail();
  number(recent.limit, 0, 20); const references = list(row.references); if (references.length > 1000) fail(); references.forEach(value => reference(value, false, v2));
}

function reasons(value: unknown) {
  for (const item of list(value)) {
    const row = shape(item, ["selector", "scope", "object_id", "revision", "axle"]);
    oneOf(row.selector, ["garage", "watchlist", "recent", "explicit"]);
    equal(row.scope, row.selector === "garage" ? "local_workspace" : row.selector === "explicit" ? "explicit" : "current_session");
    text(row.object_id, true); if (row.revision !== null) number(row.revision, 1); oneOf(row.axle, [null, "front", "rear"]);
  }
}

function omissions(value: unknown) {
  for (const item of list(value)) {
    const row = shape(item, ["selector", "object_id", "reason", "blocking"]);
    text(row.selector); text(row.object_id, true); text(row.reason); equal(row.blocking, false);
  }
}

function counts(value: unknown) {
  const row = shape(value, ["garage_profiles", "watch_items", "recent_queries", "distinct_evidence", "searchable_documents"]);
  number(row.garage_profiles, 0, 50); number(row.watch_items, 0, 100); number(row.recent_queries, 0, 20);
  number(row.distinct_evidence, 0, 200); number(row.searchable_documents, 0, 4000);
  return row;
}

export function validateOfflineDescriptor(value: unknown): OfflinePackDescriptor {
  const row = shape(value, ["schema", "id", "plan_id", "created_at", "content_created_at", "plan_fingerprint", "owner_scope_id", "privacy_class", "sha256", "byte_count", "base_pack_id", "counts", "download_path", "data_state", "source_refresh_performed"]);
  oneOf(row.schema, ["offline-pack-descriptor@1", "offline-pack-descriptor@2"]); identifier(row.id); identifier(row.plan_id); identifier(row.base_pack_id, true);
  date(row.created_at); date(row.content_created_at); digest(row.plan_fingerprint); digest(row.owner_scope_id); digest(row.sha256);
  privacy(row.privacy_class, false); number(row.byte_count, 1, MAX_OFFLINE_BYTES); counts(row.counts);
  equal(row.download_path, `/v1/offline-packs/${row.id}/download?mode=history`);
  equal(row.data_state, "local_snapshot"); equal(row.source_refresh_performed, false);
  return value as OfflinePackDescriptor;
}

export function validateOfflineInstall(request: OfflineInstallRequest) {
  const row = shape(request, ["package_id", "expected_sha256", "expected_byte_count", "approved_plan_fingerprint", "slot_id", "expected_generation", "allow_device_storage"]);
  identifier(row.package_id); identifier(row.slot_id); digest(row.expected_sha256); digest(row.approved_plan_fingerprint);
  number(row.expected_byte_count, 1, MAX_OFFLINE_BYTES); number(row.expected_generation); equal(row.allow_device_storage, true);
}

function payload(member: OfflineMember, v2 = false) {
  const value = member.payload, ref = member.reference;
  if (ref.kind === "tire") {
    const row = shape(value, ["variant", "identity_contract", "snapshot_identity_contract", "field_resolution", "lifecycle"]);
    equal(object(row.variant).id, ref.variant_id); object(object(row.variant).facts); object(row.identity_contract);
    text(row.snapshot_identity_contract, true); object(row.field_resolution); text(row.lifecycle);
  } else if (ref.kind === "vehicle") {
    const row = shape(value, ["vehicle", "trims", "fitments", "footnotes", "fact_hash", "fact_version", "excluded_document_count"]);
    object(row.vehicle); list(row.trims).forEach(object); list(row.fitments).forEach(object); list(row.footnotes).forEach(value => text(value));
    digest(row.fact_hash); number(row.fact_version, 1); number(row.excluded_document_count);
  } else if (ref.kind === "test_event") {
    const row = shape(value, ["metadata", "event"]), metadata = object(row.metadata), event = object(row.event);
    equal(metadata.id, ref.event_id); equal(metadata.revision, ref.event_revision); equal(metadata.record_kind, "manual_transcription");
    equal(metadata.verification_status, "unverified"); equal(metadata.verified_at, null);
    list(event.participants).forEach(object); list(event.metrics).forEach(object); list(event.measurements).forEach(object);
  } else if (ref.kind === "recall_search") {
    if (!v2) fail();
    const row = shape(value, ["query", "discovery", "discovery_hash", "evidence", "empty_observation", "notices", "boundary"]);
    const query = canonicalDeviceQuery("recall_search", row.query); equal(stableExactDeviceJson(query), stableExactDeviceJson(row.query));
    const discovery = shape(row.discovery, ["products", "pagination"]), products = list(discovery.products);
    const pagination = shape(discovery.pagination, ["count", "has_next", "has_previous", "max", "offset", "total"]);
    number(pagination.count, 0, 10); equal(pagination.count, products.length); number(pagination.max, 10, 10); number(pagination.offset, 0, 10000); equal(pagination.offset, Number(query.offset)); number(pagination.total);
    if (typeof pagination.has_next !== "boolean" || typeof pagination.has_previous !== "boolean") fail();
    equal(row.empty_observation, products.length === 0); digest(row.discovery_hash); list(row.notices).forEach(value => text(value));
    const evidence = shape(row.evidence, ["snapshot_id", "query_id", "verification_id", "data_state", "observed_at", "verified_at"]);
    equal(evidence.snapshot_id, ref.snapshot_id); equal(evidence.verification_id, ref.verification_id); id(evidence.query_id); equal(evidence.data_state, "local_snapshot"); date(evidence.observed_at); date(evidence.verified_at);
    equal(evidence.observed_at, member.source.observed_at); equal(evidence.verified_at, member.source.verified_at);
    const boundary = shape(row.boundary, ["kind", "formal_campaign_revision", "applicability", "complete_query_result"]);
    equal(boundary.kind, "recall_search_candidate_page"); equal(boundary.formal_campaign_revision, false); equal(boundary.applicability, "not_assessed"); equal(boundary.complete_query_result, false);
    for (const product of products) {
      const item = shape(product, ["id", "artemis_id", "brand", "tireline", "size", "recalls_count", "campaigns", "applicability"]);
      for (const key of ["id", "artemis_id"]) { const numeric = item[key]; if (numeric instanceof ExactJsonNumber ? numeric.integer === null || numeric.integer <= 0n : typeof numeric !== "number" || !Number.isSafeInteger(numeric) || numeric <= 0) fail(); }
      text(item.brand); text(item.tireline); text(item.size, true); number(item.recalls_count, 0, 1000); equal(item.applicability, "not_assessed");
      const campaigns = list(item.campaigns); equal(item.recalls_count, campaigns.length);
      for (const campaign of campaigns) {
        const detail = shape(campaign, ["campaign_number", "consequence", "manufacturer", "notes", "remedy", "report_received_at", "subject", "summary", "associated_products", "documents"]);
        text(detail.campaign_number); for (const key of ["consequence", "manufacturer", "notes", "remedy", "report_received_at", "subject", "summary"]) text(detail[key], true);
        list(detail.associated_products).forEach(object); list(detail.documents).forEach(object);
      }
    }
  } else {
    const row = shape(value, ["evidence", "records", "facts", "policy", "boundary"]), evidence = object(row.evidence);
    const records = list(row.records), recordKeys = new Set<string>();
    equal(evidence.evidence_type, "recall"); equal(evidence.kind, "regulatory"); equal(evidence.snapshot_id, ref.snapshot_id);
    equal(evidence.recall_revision_id, ref.recall_revision_id); equal(evidence.verification_id, ref.verification_id);
    equal(evidence.applicability, "not_assessed"); equal(evidence.record_count, records.length);
    equal(evidence.observation_kind, records.length ? "records" : "empty");
    if (records.length ? ref.recall_revision_id === null : ref.recall_revision_id !== null) fail();
    records.forEach(record => {
      const item = shape(record, ["campaign_number", "manufacturer", "report_received_date", "report_received_date_raw", "component", "potential_units", "summary", "consequence", "remedy", "notes", "make", "model", "model_year_raw", "applicability"]);
      equal(item.applicability, "not_assessed"); equal(item.campaign_number, evidence.campaign_number);
    });
    const scopes = list(evidence.record_scopes);
    equal(scopes.length, records.length);
    scopes.forEach((record, index) => { const item = shape(record, ["record_key", "record_hash", "occurrence", "index"]); id(item.record_key); digest(item.record_hash); number(item.occurrence, 1); equal(item.index, index); if (recordKeys.has(String(item.record_key))) fail(); recordKeys.add(String(item.record_key)); });
    for (const fact of list(row.facts)) {
      const item = object(fact); equal(item.domain, "recall"); oneOf(item.scope, ["record", "observation"]);
      if (item.scope === "record" ? !recordKeys.has(String(item.record_key)) : item.record_key !== null) fail();
      if (typeof item.field_code !== "string" || !item.field_code.startsWith("recall.")) fail(); text(item.text);
    }
    const policy = shape(row.policy, ["version", "digest"]); equal(policy.version, "recall-fact-selection@1"); digest(policy.digest);
    const boundary = shape(row.boundary, ["policy", "applicability", "mode", "notice"]);
    equal(boundary.policy, "recall-fact-selection@1"); equal(boundary.applicability, "not_assessed"); equal(boundary.mode, "announcement_facts_only"); text(boundary.notice);
  }
}

export async function validateOfflineBytes(bytes: Uint8Array, descriptorValue: unknown): Promise<OfflineEnvelope> {
  const descriptor = validateOfflineDescriptor(descriptorValue);
  if (bytes.length !== descriptor.byte_count || await offlineSha256(bytes) !== descriptor.sha256) throw new OfflineError("OFFLINE_HASH_MISMATCH");
  const v2 = descriptor.schema === "offline-pack-descriptor@2";
  const value = v2 ? materializeExactMetadata(parseExactJson(bytes)) : parseOfflineJson(bytes), row = shape(value, ["schema", "package_id", "created_at", "plan_fingerprint", "owner_scope_id", "privacy_class", "data_state", "source_refresh_performed", "base_pack_id", "scope", "contracts", "contexts", "members", "documents", "omissions"]);
  equal(row.schema, v2 ? "offline-pack@2" : "offline-pack@1"); equal(row.package_id, descriptor.id); equal(row.created_at, descriptor.content_created_at);
  equal(row.plan_fingerprint, descriptor.plan_fingerprint); equal(row.owner_scope_id, descriptor.owner_scope_id); equal(row.privacy_class, descriptor.privacy_class);
  equal(row.base_pack_id, descriptor.base_pack_id); equal(row.data_state, "local_snapshot"); equal(row.source_refresh_performed, false); scope(row.scope, v2);
  const contracts = shape(row.contracts, ["offline_policy", "field_policy", "recall_policy"]);
  equal(contracts.offline_policy, "offline-policy@1"); object(contracts.field_policy); object(contracts.recall_policy); omissions(row.omissions);
  const members = new Map<string, OfflineMember>(), contexts = new Map<string, OfflineContext>(), documentIds = new Set<string>();
  for (const item of list(row.members)) {
    const member = shape(item, ["key", "reference", "member_reasons", "privacy_class", "raw_included", "source", "payload"]);
    digest(member.key); if (members.has(String(member.key))) fail(); reference(member.reference, true, v2); reasons(member.member_reasons); privacy(member.privacy_class); equal(member.raw_included, false);
    const source = shape(member.source, ["source_id", "source_url", "raw_hash", "parser_version", "parser_identity", "observed_at", "verified_at", "verification_id"]);
    text(source.source_id, true); text(source.source_url, true); digest(source.raw_hash, true); text(source.parser_version, true);
    if (source.parser_identity !== null) object(source.parser_identity); date(source.observed_at); date(source.verified_at, true); text(source.verification_id, true);
    const ref = object(member.reference); if (ref.kind !== "test_event") equal(source.verification_id, ref.verification_id);
    payload(item as OfflineMember, v2); members.set(String(member.key), item as OfflineMember);
  }
  for (const item of list(row.contexts)) {
    const context = shape(item, ["id", "kind", "scope", "privacy_class", "payload", "evidence_keys"]);
    if (contexts.has(String(context.id))) fail(); oneOf(context.kind, ["garage", "watchlist"]); equal(context.privacy_class, "private");
    equal(context.scope, context.kind === "garage" ? "local_workspace" : "current_session");
    const content = context.kind === "garage" ? shape(context.payload, ["vehicle_id", "revision", "basis", "profile", "fitment_reference", "created_at"])
      : shape(context.payload, ["item_id", "variant_id", "created_at"]);
    const identifierValue = context.kind === "garage" ? content.vehicle_id : content.item_id; id(identifierValue); equal(context.id, `${context.kind}:${identifierValue}`); date(content.created_at);
    if (context.kind === "garage") {
      number(content.revision, 1); oneOf(content.basis, ["user_entry", "copied_fitment"]);
      const profile = shape(content.profile, ["nickname", "manufacturer", "model", "model_year", "generation", "trim", "wheel_option", "optional_wheels", "front", "rear"]);
      for (const key of ["nickname", "manufacturer", "model"]) text(profile[key]);
      for (const key of ["generation", "trim", "wheel_option"]) text(profile[key], true);
      if (profile.model_year !== null) number(profile.model_year); list(profile.optional_wheels).forEach(value => text(value));
      for (const key of ["front", "rear"]) { const axle = shape(profile[key], ["size", "current_variant_id"]); text(axle.size, true); text(axle.current_variant_id, true); }
      if (content.fitment_reference !== null) object(content.fitment_reference);
    }
    else id(content.variant_id);
    list(context.evidence_keys).forEach(key => { if (!members.has(String(key))) fail(); }); contexts.set(String(context.id), item as OfflineContext);
  }
  for (const item of list(row.documents)) {
    const document = shape(item, ["id", "category", "kind", "member_key", "context_id", "record_index", "title", "text", "facets", "membership", "privacy_class", "observed_at", "verified_at"]);
    id(document.id); if (documentIds.has(String(document.id))) fail(); documentIds.add(String(document.id)); text(document.title); text(document.text); privacy(document.privacy_class);
    date(document.observed_at, true); date(document.verified_at, true);
    const facets = shape(document.facets, ["brand", "model", "size", "source_id", "campaign_number"]); Object.values(facets).forEach(value => text(value, true));
    list(document.membership).forEach(value => oneOf(value, ["garage", "watchlist", "recent", "explicit"]));
    if (document.category === "evidence") {
      equal(document.context_id, null); const member = members.get(String(document.member_key)); if (!member) fail();
      equal(document.kind, member.reference.kind); equal(document.privacy_class, member.privacy_class);
      equal(document.observed_at, member.source.observed_at); equal(document.verified_at, member.source.verified_at); equal(facets.source_id, member.source.source_id);
      const records = member.reference.kind === "recall" ? member.payload.records as unknown[] : member.reference.kind === "test_event" ? object(member.payload.event).participants as unknown[] : member.reference.kind === "recall_search" ? list(object(member.payload.discovery).products) : null;
      if (records?.length) {
        number(document.record_index, 0, records.length - 1); equal(document.id, `member:${member.key}:record:${document.record_index}`);
        const record = object(records[Number(document.record_index)]);
        equal(facets.brand, member.reference.kind === "recall" ? record.make : record.brand); equal(facets.model, member.reference.kind === "recall_search" ? record.tireline : record.model);
        if (member.reference.kind === "recall_search") equal(facets.size, record.size);
      } else { equal(document.record_index, null); equal(document.id, `member:${member.key}`); }
    } else {
      oneOf(document.category, ["garage", "watchlist"]); equal(document.member_key, null); equal(document.record_index, null);
      const context = contexts.get(String(document.context_id)); if (!context) fail();
      equal(document.kind, context.kind); equal(document.category, context.kind); equal(document.id, `context:${context.id}`);
      equal(document.privacy_class, context.privacy_class);
    }
  }
  for (const member of members.values()) {
    const size = member.reference.kind === "recall" ? list(member.payload.records).length : member.reference.kind === "test_event" ? list(object(member.payload.event).participants).length : member.reference.kind === "recall_search" ? list(object(member.payload.discovery).products).length : 0;
    if (size) { for (let index = 0; index < size; index++) if (!documentIds.has(`member:${member.key}:record:${index}`)) fail(); }
    else if (!documentIds.has(`member:${member.key}`)) fail();
  }
  for (const context of contexts.values()) if (!documentIds.has(`context:${context.id}`)) fail();
  equal(members.size, descriptor.counts.distinct_evidence); equal(documentIds.size, descriptor.counts.searchable_documents);
  equal([...contexts.values()].filter(value => value.kind === "garage").length, descriptor.counts.garage_profiles);
  equal([...contexts.values()].filter(value => value.kind === "watchlist").length, descriptor.counts.watch_items);
  return value as OfflineEnvelope;
}

export async function readOfflineResponse(response: Response, descriptor: OfflinePackDescriptor): Promise<Uint8Array> {
  if (response.headers.get("content-type")?.split(";")[0].trim() !== "application/json" || !response.body) fail();
  const length = response.headers.get("content-length"), digestHeader = response.headers.get("x-content-sha256");
  if ((length !== null && Number(length) !== descriptor.byte_count) || (digestHeader !== null && digestHeader !== descriptor.sha256)) throw new OfflineError("OFFLINE_HASH_MISMATCH");
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let bytes = 0;
  try { while (true) { const next = await reader.read(); if (next.done) break; bytes += next.value.byteLength; if (bytes > descriptor.byte_count || bytes > MAX_OFFLINE_BYTES) throw new OfflineError("OFFLINE_TOO_LARGE"); chunks.push(next.value); } }
  catch (cause) { await reader.cancel().catch(() => {}); throw cause; }
  finally { reader.releaseLock(); }
  if (bytes !== descriptor.byte_count) throw new OfflineError("OFFLINE_HASH_MISMATCH");
  const body = new Uint8Array(bytes); let offset = 0; for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; } return body;
}

export function searchOfflineEnvelope(envelope: OfflineEnvelope, slot: OfflineSlot, request: OfflineSearchRequest): OfflineSearchResult {
  if (request.slot_id !== slot.slot_id || request.expected_generation !== slot.generation) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
  if (typeof request.query !== "string" || request.query.length > 500 || !Number.isInteger(request.limit) || request.limit < 1 || request.limit > 50 || !Number.isSafeInteger(request.offset) || request.offset < 0 || request.offset > 4000) throw new OfflineError("OFFLINE_INVALID_REQUEST");
  if (request.kind && !["tire", "vehicle", "test_event", "recall", "recall_search", "garage", "watchlist"].includes(request.kind)) throw new OfflineError("OFFLINE_INVALID_REQUEST");
  const terms = request.query.toLowerCase().match(/[\p{L}\p{N}_]+/gu) || [];
  const matches = envelope.documents.filter(document => {
    if (request.kind && document.kind !== request.kind) return false;
    const content = [document.title, document.text, ...Object.values(document.facets)].filter(value => typeof value === "string").join("\n").toLowerCase(), words = new Set(content.match(/[\p{L}\p{N}_]+/gu) || []);
    return terms.every(term => /[^\x00-\x7f]/.test(term) ? content.includes(term) : words.has(term));
  });
  return { data_state: "local_snapshot", slot, items: matches.slice(request.offset, request.offset + request.limit), total: matches.length, offset: request.offset, limit: request.limit, has_more: request.offset + request.limit < matches.length };
}

export function readOfflineEnvelope(envelope: OfflineEnvelope, slot: OfflineSlot, request: OfflineReadRequest): OfflineReadResult {
  if (request.slot_id !== slot.slot_id || request.expected_generation !== slot.generation) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
  const document = envelope.documents.find(value => value.id === request.document_id); if (!document) throw new OfflineError("OFFLINE_NOT_FOUND");
  return { ...(envelope.schema === "offline-pack@2" ? { schema: "offline-read-result@2" as const, package_schema: "offline-pack@2" as const } : {}), data_state: "local_snapshot", slot, document, member: envelope.members.find(value => value.key === document.member_key) || null, context: envelope.contexts.find(value => value.id === document.context_id) || null };
}
