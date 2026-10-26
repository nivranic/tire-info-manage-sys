-- Frozen current 023 schema; no custom overlays.
CREATE TABLE ai_completions (
	request_id VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	error_code VARCHAR(80), 
	answer JSON, 
	usage JSON, 
	provider_response_id VARCHAR(128), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (request_id), 
	FOREIGN KEY(request_id) REFERENCES ai_requests (id)
);
CREATE TABLE ai_draft_applications (
	id VARCHAR(64) NOT NULL, 
	draft_request_id VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	reviewed_rule JSON NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	rule_snapshot JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	UNIQUE (draft_request_id), 
	FOREIGN KEY(draft_request_id) REFERENCES ai_requests (id), 
	UNIQUE (rule_id), 
	FOREIGN KEY(rule_id) REFERENCES alert_rules (id)
);
CREATE TABLE ai_evidence_packs (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	mode VARCHAR(16) NOT NULL, 
	data_state VARCHAR(24) NOT NULL, 
	privacy_class VARCHAR(16) NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE ai_requests (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	pack_id VARCHAR(64) NOT NULL, 
	question TEXT NOT NULL, 
	provider VARCHAR(32) NOT NULL, 
	model VARCHAR(120) NOT NULL, 
	request_contract JSON NOT NULL, 
	reserved_tokens INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(pack_id) REFERENCES ai_evidence_packs (id)
);
CREATE TABLE ai_stream_events (
	id VARCHAR(64) NOT NULL, 
	request_id VARCHAR(64) NOT NULL, 
	sequence INTEGER NOT NULL, 
	event_key VARCHAR(24) NOT NULL, 
	type VARCHAR(24) NOT NULL, 
	payload JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (request_id, sequence), 
	UNIQUE (request_id, event_key), 
	CHECK (sequence >= 1 AND sequence <= 64), 
	CHECK (type IN ('accepted', 'started', 'claim_draft', 'uncertainty_draft', 'completed', 'failed', 'outcome_unknown')), 
	FOREIGN KEY(request_id) REFERENCES ai_stream_executions (request_id)
);
CREATE TABLE ai_stream_executions (
	request_id VARCHAR(64) NOT NULL, 
	owner_token_hash VARCHAR(64) NOT NULL, 
	deadline_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (request_id), 
	FOREIGN KEY(request_id) REFERENCES ai_requests (id)
);
CREATE TABLE alert_events (
	id VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(64) NOT NULL, 
	rule_revision_id VARCHAR(64) NOT NULL, 
	change_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (rule_id, change_id), 
	FOREIGN KEY(rule_id) REFERENCES alert_rules (id), 
	FOREIGN KEY(rule_revision_id) REFERENCES alert_rule_revisions (id), 
	FOREIGN KEY(change_id) REFERENCES change_events (id)
);
CREATE TABLE alert_rule_revisions (
	id VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	interval_seconds INTEGER NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	archived BOOLEAN NOT NULL, 
	kinds JSON NOT NULL, 
	fields JSON NOT NULL, 
	conditions JSON, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (rule_id, revision), 
	FOREIGN KEY(rule_id) REFERENCES alert_rules (id)
);
CREATE TABLE alert_rules (
	id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES monitor_jobs (id), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id)
);
CREATE TABLE audit_events (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64), 
	consent_id VARCHAR(64), 
	action VARCHAR(48) NOT NULL, 
	detail JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE candidate_ai_authorizations (
	id VARCHAR(64) NOT NULL, 
	scope_hash VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	actor_user_id VARCHAR(64) NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (scope_hash, revision)
);
CREATE TABLE candidate_ai_claims (
	id VARCHAR(64) NOT NULL, 
	preparation_id VARCHAR(64) NOT NULL, 
	request_id VARCHAR(64) NOT NULL, 
	actor_user_id VARCHAR(64) NOT NULL, 
	consent_hash VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (preparation_id), 
	FOREIGN KEY(preparation_id) REFERENCES candidate_ai_preparations (id), 
	UNIQUE (request_id), 
	FOREIGN KEY(request_id) REFERENCES ai_requests (id)
);
CREATE TABLE candidate_ai_preparations (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	actor_user_id VARCHAR(64) NOT NULL, 
	pack_id VARCHAR(64) NOT NULL, 
	request JSON NOT NULL, 
	binding JSON NOT NULL, 
	"view" JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (pack_id), 
	FOREIGN KEY(pack_id) REFERENCES ai_evidence_packs (id)
);
CREATE TABLE capture_objects (
	capture_id VARCHAR(64) NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	PRIMARY KEY (capture_id), 
	FOREIGN KEY(capture_id) REFERENCES raw_captures (id), 
	FOREIGN KEY(raw_hash) REFERENCES evidence_objects (raw_hash)
);
CREATE TABLE change_events (
	id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	previous_snapshot_id VARCHAR(64), 
	kind VARCHAR(32) NOT NULL, 
	changes JSON NOT NULL, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(snapshot_id) REFERENCES snapshots (id)
);
CREATE TABLE device_ai_consent_claims (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	preparation_id VARCHAR(64) NOT NULL, 
	ai_request_id VARCHAR(64) NOT NULL, 
	analysis_key VARCHAR(36) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	provider_consent_hash VARCHAR(64) NOT NULL, 
	provider VARCHAR(32) NOT NULL, 
	model VARCHAR(120) NOT NULL, 
	provider_policy_fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, analysis_key), 
	FOREIGN KEY(preparation_id, actor_session_id) REFERENCES device_ai_preparations (id, actor_session_id), 
	UNIQUE (preparation_id), 
	UNIQUE (ai_request_id), 
	FOREIGN KEY(ai_request_id) REFERENCES ai_requests (id)
);
CREATE TABLE device_ai_preparations (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(36) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	offline_pack_id VARCHAR(64) NOT NULL, 
	offline_content_hash VARCHAR(64) NOT NULL, 
	host_receipt_id VARCHAR(36) NOT NULL, 
	intent_id VARCHAR(36) NOT NULL, 
	selection_hash VARCHAR(64) NOT NULL, 
	projection_hash VARCHAR(64) NOT NULL, 
	projection_byte_count INTEGER NOT NULL, 
	device_context_fingerprint VARCHAR(64) NOT NULL, 
	question_sha256 VARCHAR(64) NOT NULL, 
	ai_pack_id VARCHAR(64) NOT NULL, 
	contract JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	UNIQUE (actor_session_id, host_receipt_id), 
	UNIQUE (actor_session_id, intent_id), 
	UNIQUE (id, actor_session_id), 
	CONSTRAINT ck_device_ai_projection_bytes CHECK (projection_byte_count >= 1 AND projection_byte_count <= 44000), 
	CONSTRAINT ck_device_ai_preparation_expiry CHECK (expires_at > created_at), 
	FOREIGN KEY(offline_pack_id) REFERENCES offline_packs (id), 
	FOREIGN KEY(offline_content_hash) REFERENCES evidence_objects (raw_hash), 
	FOREIGN KEY(projection_hash) REFERENCES evidence_objects (raw_hash), 
	UNIQUE (ai_pack_id), 
	FOREIGN KEY(ai_pack_id) REFERENCES ai_evidence_packs (id)
);
CREATE TABLE driving_preference_revisions (
	id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	weights JSON, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (revision), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE embedding_cache (
	id VARCHAR(64) NOT NULL, 
	model_space VARCHAR(64) NOT NULL, 
	provider VARCHAR(32) NOT NULL, 
	model VARCHAR(120) NOT NULL, 
	dimensions INTEGER NOT NULL, 
	text_contract VARCHAR(80) NOT NULL, 
	privacy_class VARCHAR(16) NOT NULL, 
	text_hash VARCHAR(64) NOT NULL, 
	vector JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE embedding_completions (
	request_id VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	error_code VARCHAR(80), 
	usage JSON, 
	result JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (request_id), 
	FOREIGN KEY(request_id) REFERENCES embedding_requests (id)
);
CREATE TABLE embedding_plans (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	model_space VARCHAR(64) NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE embedding_requests (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	model_space VARCHAR(64), 
	plan_id VARCHAR(64), 
	payload JSON NOT NULL, 
	billable BOOLEAN NOT NULL, 
	reserved_tokens INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(plan_id) REFERENCES embedding_plans (id)
);
CREATE TABLE evidence_documents (
	id VARCHAR(64) NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	title VARCHAR(160) NOT NULL, 
	source_url TEXT NOT NULL, 
	operator VARCHAR(120) NOT NULL, 
	rights_basis TEXT NOT NULL, 
	content_type VARCHAR(100) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(raw_hash) REFERENCES evidence_objects (raw_hash)
);
CREATE TABLE evidence_objects (
	raw_hash VARCHAR(64) NOT NULL, 
	byte_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (raw_hash)
);
CREATE TABLE external_api_key_minutes (
	key_id VARCHAR(32) NOT NULL, 
	minute INTEGER NOT NULL, 
	requests INTEGER NOT NULL, 
	PRIMARY KEY (key_id), 
	FOREIGN KEY(key_id) REFERENCES external_api_keys (id)
);
CREATE TABLE external_api_key_operations (
	id VARCHAR(32) NOT NULL, 
	owner_user_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(36) NOT NULL, 
	action VARCHAR(12) NOT NULL, 
	method VARCHAR(8) NOT NULL, 
	path VARCHAR(200) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	key_id VARCHAR(32) NOT NULL, 
	key_snapshot JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_user_id, idempotency_key), 
	FOREIGN KEY(key_id) REFERENCES external_api_keys (id)
);
CREATE TABLE external_api_key_revocations (
	key_id VARCHAR(32) NOT NULL, 
	revoked_at DATETIME NOT NULL, 
	reason VARCHAR(32) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	PRIMARY KEY (key_id), 
	FOREIGN KEY(key_id) REFERENCES external_api_keys (id)
);
CREATE TABLE external_api_keys (
	id VARCHAR(32) NOT NULL, 
	owner_user_id VARCHAR(64) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	scopes JSON NOT NULL, 
	bearer_sha256 VARCHAR(64) NOT NULL, 
	cursor_secret VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (bearer_sha256)
);
CREATE TABLE fact_versions (
	id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	facts JSON NOT NULL, 
	facts_hash VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (variant_id, source_id, version), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(snapshot_id) REFERENCES snapshots (id)
);
CREATE TABLE fallback_consents (
	id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	decision VARCHAR(8) NOT NULL, 
	scope VARCHAR(8) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	used_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id)
);
CREATE TABLE fitment_relation_revisions (
	id VARCHAR(64) NOT NULL, 
	relation_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	review_state VARCHAR(24) NOT NULL, 
	selection JSON NOT NULL, 
	vehicle_evidence JSON NOT NULL, 
	tire_evidence JSON NOT NULL, 
	binding JSON NOT NULL, 
	binding_hash VARCHAR(64) NOT NULL, 
	checks JSON NOT NULL, 
	"before" JSON, 
	"after" JSON NOT NULL, 
	acknowledged_unknowns BOOLEAN NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (relation_id, revision), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(relation_id) REFERENCES fitment_relations (id)
);
CREATE TABLE fitment_relations (
	id VARCHAR(64) NOT NULL, 
	vehicle_id VARCHAR(80) NOT NULL, 
	trim_id VARCHAR(120) NOT NULL, 
	wheel_option_id VARCHAR(64) NOT NULL, 
	axle VARCHAR(8) NOT NULL, 
	scope JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicle_models (id)
);
CREATE TABLE garage_revisions (
	id VARCHAR(64) NOT NULL, 
	vehicle_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	operation VARCHAR(24) NOT NULL, 
	archived BOOLEAN NOT NULL, 
	profile JSON NOT NULL, 
	basis VARCHAR(24) NOT NULL, 
	fitment_reference JSON, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (vehicle_id, revision), 
	FOREIGN KEY(vehicle_id) REFERENCES garage_vehicles (id), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE garage_vehicles (
	id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE golden_case_reviews (
	id VARCHAR(64) NOT NULL, 
	case_id VARCHAR(64) NOT NULL, 
	case_revision INTEGER NOT NULL, 
	case_fingerprint VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	previous_fingerprint VARCHAR(64), 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (case_id, revision), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(case_id) REFERENCES golden_cases (id)
);
CREATE TABLE golden_case_revisions (
	id VARCHAR(64) NOT NULL, 
	case_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	capture_id VARCHAR(64) NOT NULL, 
	input JSON NOT NULL, 
	evidence_note VARCHAR(2000) NOT NULL, 
	expected JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	previous_fingerprint VARCHAR(64), 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (case_id, revision), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(case_id) REFERENCES golden_cases (id), 
	FOREIGN KEY(capture_id) REFERENCES raw_captures (id)
);
CREATE TABLE golden_cases (
	id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE golden_set_revisions (
	id VARCHAR(64) NOT NULL, 
	set_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	cases JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	previous_fingerprint VARCHAR(64), 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (set_id, revision), 
	UNIQUE (actor_session_id, idempotency_key)
);
CREATE TABLE identity_revisions (
	id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	target_id VARCHAR(64), 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	binding JSON NOT NULL, 
	binding_hash VARCHAR(64) NOT NULL, 
	differences JSON NOT NULL, 
	field_reasons JSON NOT NULL, 
	acknowledged_unknowns BOOLEAN NOT NULL, 
	evidence JSON NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (variant_id, revision), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(target_id) REFERENCES tire_variants (id)
);
CREATE TABLE interest_events (
	id VARCHAR(64) NOT NULL, 
	domain VARCHAR(24) NOT NULL, 
	origin_id VARCHAR(64) NOT NULL, 
	observed_at DATETIME NOT NULL, 
	event_hash VARCHAR(64) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (domain, origin_id)
);
CREATE TABLE interest_notifications (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	interest_id VARCHAR(64) NOT NULL, 
	interest_revision_id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64) NOT NULL, 
	"match" JSON NOT NULL, 
	delivered_at DATETIME NOT NULL, 
	read_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (interest_id, event_id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id), 
	FOREIGN KEY(interest_id) REFERENCES interests (id), 
	FOREIGN KEY(interest_revision_id) REFERENCES interest_revisions (id), 
	FOREIGN KEY(event_id) REFERENCES interest_events (id)
);
CREATE TABLE interest_revisions (
	id VARCHAR(64) NOT NULL, 
	interest_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	archived BOOLEAN NOT NULL, 
	conditions JSON NOT NULL, 
	metric_keys JSON NOT NULL, 
	changed_fields JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (interest_id, revision), 
	FOREIGN KEY(interest_id) REFERENCES interests (id), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE interests (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id)
);
CREATE TABLE knowledge_documents (
	id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	source_id VARCHAR(80), 
	variant_id VARCHAR(64), 
	tokens TEXT NOT NULL, 
	search_vector TEXT, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE knowledge_facets (
	document_id VARCHAR(64) NOT NULL, 
	name VARCHAR(24) NOT NULL, 
	value VARCHAR(400) NOT NULL, 
	PRIMARY KEY (document_id, name, value), 
	FOREIGN KEY(document_id) REFERENCES knowledge_documents (id) ON DELETE CASCADE
);
CREATE TABLE knowledge_index_state (
	id VARCHAR(16) NOT NULL, 
	version VARCHAR(80) NOT NULL, 
	signature VARCHAR(64) NOT NULL, 
	documents INTEGER NOT NULL, 
	refreshed_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE local_sessions (
	id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	user_id VARCHAR(64), 
	PRIMARY KEY (id)
);
CREATE TABLE manual_fact_revisions (
	id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	base_fact_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	field VARCHAR(80) NOT NULL, 
	action VARCHAR(24) NOT NULL, 
	operator_session_id VARCHAR(64) NOT NULL, 
	operator VARCHAR(80) NOT NULL, 
	reason TEXT NOT NULL, 
	"before" JSON NOT NULL, 
	"after" JSON NOT NULL, 
	source_before JSON NOT NULL, 
	evidence JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (variant_id, source_id, revision), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(base_fact_id) REFERENCES fact_versions (id), 
	FOREIGN KEY(operator_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE monitor_jobs (
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	"query" JSON NOT NULL, 
	next_due_at DATETIME NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	last_finished_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE TABLE monitor_runs (
	id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	lease_token VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	reason VARCHAR(100), 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES monitor_jobs (id), 
	UNIQUE (lease_token)
);
CREATE TABLE monitor_task_attempts (
	id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	"query" JSON NOT NULL, 
	lease_token_hash VARCHAR(64) NOT NULL, 
	source_access_generation INTEGER, 
	started_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (kind, job_id, lease_token_hash), 
	CHECK (kind IN ('tire', 'recall'))
);
CREATE TABLE monitor_task_events (
	id VARCHAR(64) NOT NULL, 
	attempt_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	sequence BIGINT NOT NULL, 
	phase VARCHAR(16) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	result_state VARCHAR(32), 
	reason VARCHAR(100), 
	query_id VARCHAR(64), 
	run_id VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (kind, job_id, sequence), 
	UNIQUE (attempt_id, phase), 
	CHECK (kind IN ('tire', 'recall')), 
	CHECK (sequence > 0 AND sequence <= 9007199254740991), 
	CHECK (phase IN ('claimed', 'running', 'finished')), 
	CHECK (state IN ('running', 'succeeded', 'failed', 'blocked', 'interrupted')), 
	CHECK ((phase = 'finished' AND state <> 'running') OR (phase <> 'finished' AND state = 'running')), 
	FOREIGN KEY(attempt_id) REFERENCES monitor_task_attempts (id)
);
CREATE TABLE notification_deliveries (
	id VARCHAR(64) NOT NULL, 
	alert_id VARCHAR(64) NOT NULL, 
	channel VARCHAR(16) NOT NULL, 
	delivered_at DATETIME NOT NULL, 
	read_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (alert_id), 
	FOREIGN KEY(alert_id) REFERENCES alert_events (id)
);
CREATE TABLE offline_pack_plans (
	id VARCHAR(64) NOT NULL, 
	package_id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	preview JSON NOT NULL, 
	content_hash VARCHAR(64), 
	byte_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (package_id), 
	FOREIGN KEY(content_hash) REFERENCES evidence_objects (raw_hash)
);
CREATE TABLE offline_packs (
	id VARCHAR(64) NOT NULL, 
	plan_id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(36) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	byte_count INTEGER NOT NULL, 
	descriptor JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	UNIQUE (plan_id), 
	FOREIGN KEY(plan_id) REFERENCES offline_pack_plans (id), 
	FOREIGN KEY(content_hash) REFERENCES evidence_objects (raw_hash)
);
CREATE TABLE parser_bundles (
	id VARCHAR(64) NOT NULL, 
	manifest JSON NOT NULL, 
	descriptors JSON NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	origin VARCHAR(40) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE parser_deployment_revisions (
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	revision INTEGER NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	bundle_id VARCHAR(64) NOT NULL, 
	descriptor JSON NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	evaluation_review_id VARCHAR(64), 
	rollback_revision INTEGER, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (source_id, revision), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(bundle_id) REFERENCES parser_bundles (id), 
	FOREIGN KEY(evaluation_review_id) REFERENCES parser_evaluation_reviews (id)
);
CREATE TABLE parser_evaluation_completions (
	evaluation_id VARCHAR(64) NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	results JSON NOT NULL, 
	hard_blocks JSON NOT NULL, 
	reference_gaps JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	completed_at DATETIME NOT NULL, 
	PRIMARY KEY (evaluation_id), 
	FOREIGN KEY(evaluation_id) REFERENCES parser_evaluations (id)
);
CREATE TABLE parser_evaluation_reviews (
	id VARCHAR(64) NOT NULL, 
	evaluation_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	completion_fingerprint VARCHAR(64) NOT NULL, 
	acknowledged_reference_gaps BOOLEAN NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (evaluation_id, revision), 
	FOREIGN KEY(evaluation_id) REFERENCES parser_evaluations (id)
);
CREATE TABLE parser_evaluations (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	target_bundle_id VARCHAR(64) NOT NULL, 
	control_bundle_id VARCHAR(64) NOT NULL, 
	deployment_revision INTEGER NOT NULL, 
	bindings JSON NOT NULL, 
	input_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(target_bundle_id) REFERENCES parser_bundles (id), 
	FOREIGN KEY(control_bundle_id) REFERENCES parser_bundles (id)
);
CREATE TABLE parser_executions (
	query_run_id VARCHAR(64) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	error_code VARCHAR(80), 
	receipt JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (query_run_id), 
	FOREIGN KEY(query_run_id) REFERENCES parser_selections (query_run_id)
);
CREATE TABLE parser_selections (
	query_run_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	deployment_id VARCHAR(64) NOT NULL, 
	bundle_id VARCHAR(64) NOT NULL, 
	deployment_revision INTEGER NOT NULL, 
	descriptor JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (query_run_id), 
	FOREIGN KEY(query_run_id) REFERENCES query_runs (id), 
	FOREIGN KEY(deployment_id) REFERENCES parser_deployment_revisions (id), 
	FOREIGN KEY(bundle_id) REFERENCES parser_bundles (id)
);
CREATE TABLE quarantine_approval_uses (
	review_id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	used_at DATETIME NOT NULL, 
	PRIMARY KEY (review_id), 
	FOREIGN KEY(review_id) REFERENCES quarantine_reviews (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE quarantine_reviews (
	id VARCHAR(64) NOT NULL, 
	quarantine_id VARCHAR(64) NOT NULL, 
	binding_hash VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(24) NOT NULL, 
	operator VARCHAR(80) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (binding_hash, revision)
);
CREATE TABLE query_fallback_policy_revisions (
	id VARCHAR(64) NOT NULL, 
	policy_id VARCHAR(64) NOT NULL, 
	revision BIGINT NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	state VARCHAR(12) NOT NULL, 
	mode VARCHAR(20) NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(36) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (policy_id, revision), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE query_fallback_previews (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	policy_id VARCHAR(64) NOT NULL, 
	expected_revision BIGINT NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	applied_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE query_fallback_uses (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	policy_id VARCHAR(64) NOT NULL, 
	policy_revision BIGINT NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	query_kind VARCHAR(24) NOT NULL, 
	audience VARCHAR(24) NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (query_id, query_kind, audience), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE query_runs (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	"query" JSON NOT NULL, 
	selection_filters JSON, 
	source_access_generation INTEGER, 
	fallback_policy VARCHAR(12) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	reason TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id)
);
CREATE TABLE raw_captures (
	id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	target_kind VARCHAR(16) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	raw_body BLOB NOT NULL, 
	byte_count INTEGER NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE recall_discovery_candidates (
	id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	campaign_number VARCHAR(9) NOT NULL, 
	first_seen_run_id VARCHAR(64) NOT NULL, 
	first_seen_at DATETIME NOT NULL, 
	campaign JSON NOT NULL, 
	evidence JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (job_id, campaign_number), 
	FOREIGN KEY(job_id) REFERENCES recall_discovery_jobs (id), 
	FOREIGN KEY(first_seen_run_id) REFERENCES recall_discovery_runs (id)
);
CREATE TABLE recall_discovery_jobs (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	"query" JSON NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	next_due_at DATETIME NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	last_finished_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (session_id, query_key), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id)
);
CREATE TABLE recall_discovery_notifications (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(64) NOT NULL, 
	rule_revision_id VARCHAR(64) NOT NULL, 
	candidate_id VARCHAR(64) NOT NULL, 
	delivered_at DATETIME NOT NULL, 
	read_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (rule_id, candidate_id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id), 
	FOREIGN KEY(rule_id) REFERENCES recall_discovery_rules (id), 
	FOREIGN KEY(rule_revision_id) REFERENCES recall_discovery_rule_revisions (id), 
	FOREIGN KEY(candidate_id) REFERENCES recall_discovery_candidates (id)
);
CREATE TABLE recall_discovery_pages (
	id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	attempt_id VARCHAR(64) NOT NULL, 
	pass_number INTEGER NOT NULL, 
	"offset" INTEGER NOT NULL, 
	query_id VARCHAR(64), 
	verification_id VARCHAR(64), 
	snapshot_id VARCHAR(64), 
	total INTEGER, 
	count INTEGER, 
	content_fingerprint VARCHAR(64), 
	raw_bytes INTEGER NOT NULL, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id, pass_number, "offset"), 
	CHECK (pass_number IN (1, 2) AND "offset" >= 0 AND "offset" <= 10000 AND "offset" % 10 = 0), 
	CHECK (raw_bytes >= 0), 
	FOREIGN KEY(job_id) REFERENCES recall_discovery_jobs (id), 
	FOREIGN KEY(attempt_id) REFERENCES recall_discovery_task_attempts (id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id), 
	FOREIGN KEY(verification_id) REFERENCES recall_search_verifications (id), 
	FOREIGN KEY(snapshot_id) REFERENCES recall_search_snapshots (id)
);
CREATE TABLE recall_discovery_rule_revisions (
	id VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	archived BOOLEAN NOT NULL, 
	interval_seconds INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	idempotency_key VARCHAR(36), 
	request_hash VARCHAR(64), 
	PRIMARY KEY (id), 
	UNIQUE (rule_id, revision), 
	UNIQUE (rule_id, idempotency_key), 
	CHECK (revision > 0 AND interval_seconds >= 3600 AND interval_seconds <= 604800), 
	FOREIGN KEY(rule_id) REFERENCES recall_discovery_rules (id)
);
CREATE TABLE recall_discovery_rules (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	idempotency_key VARCHAR(36), 
	request_hash VARCHAR(64), 
	PRIMARY KEY (id), 
	UNIQUE (session_id, idempotency_key), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id), 
	FOREIGN KEY(job_id) REFERENCES recall_discovery_jobs (id)
);
CREATE TABLE recall_discovery_runs (
	id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	attempt_id VARCHAR(64) NOT NULL, 
	lease_token VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	reason VARCHAR(200), 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME NOT NULL, 
	previous_complete_id VARCHAR(64), 
	coverage VARCHAR(16) NOT NULL, 
	pass_fingerprints JSON NOT NULL, 
	page_operations INTEGER NOT NULL, 
	pages_completed INTEGER NOT NULL, 
	products_count INTEGER NOT NULL, 
	candidates_count INTEGER NOT NULL, 
	new_candidates_count INTEGER NOT NULL, 
	raw_bytes INTEGER NOT NULL, 
	elapsed_seconds FLOAT NOT NULL, 
	budget JSON NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (coverage IN ('complete', 'incomplete')), 
	FOREIGN KEY(job_id) REFERENCES recall_discovery_jobs (id), 
	UNIQUE (attempt_id), 
	FOREIGN KEY(attempt_id) REFERENCES recall_discovery_task_attempts (id), 
	UNIQUE (lease_token), 
	FOREIGN KEY(previous_complete_id) REFERENCES recall_discovery_runs (id)
);
CREATE TABLE recall_discovery_task_attempts (
	id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	"query" JSON NOT NULL, 
	lease_token_hash VARCHAR(64) NOT NULL, 
	source_access_generation INTEGER, 
	started_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (kind, job_id, lease_token_hash), 
	CHECK (kind = 'recall_discovery')
);
CREATE TABLE recall_discovery_task_events (
	id VARCHAR(64) NOT NULL, 
	attempt_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	sequence BIGINT NOT NULL, 
	phase VARCHAR(16) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	result_state VARCHAR(32), 
	reason VARCHAR(100), 
	query_id VARCHAR(64), 
	run_id VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (kind, job_id, sequence), 
	UNIQUE (attempt_id, phase), 
	CHECK (kind = 'recall_discovery'), 
	CHECK (sequence > 0 AND sequence <= 9007199254740991), 
	CHECK (phase IN ('claimed', 'running', 'finished')), 
	CHECK (state IN ('running', 'succeeded', 'failed', 'blocked', 'interrupted')), 
	CHECK ((phase = 'finished' AND state <> 'running') OR (phase <> 'finished' AND state = 'running')), 
	FOREIGN KEY(attempt_id) REFERENCES recall_discovery_task_attempts (id)
);
CREATE TABLE recall_events (
	id VARCHAR(64) NOT NULL, 
	revision_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	changes JSON NOT NULL, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (revision_id), 
	FOREIGN KEY(revision_id) REFERENCES recall_revisions (id)
);
CREATE TABLE recall_monitor_jobs (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	campaign_number VARCHAR(9) NOT NULL, 
	next_due_at DATETIME NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	last_finished_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id)
);
CREATE TABLE recall_monitor_rules (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id), 
	FOREIGN KEY(job_id) REFERENCES recall_monitor_jobs (id)
);
CREATE TABLE recall_monitor_runs (
	id VARCHAR(64) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	lease_token VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	reason VARCHAR(200), 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES recall_monitor_jobs (id), 
	UNIQUE (lease_token)
);
CREATE TABLE recall_notifications (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(64) NOT NULL, 
	rule_revision_id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64) NOT NULL, 
	delivered_at DATETIME NOT NULL, 
	read_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (rule_id, event_id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id), 
	FOREIGN KEY(rule_id) REFERENCES recall_monitor_rules (id), 
	FOREIGN KEY(rule_revision_id) REFERENCES recall_rule_revisions (id), 
	FOREIGN KEY(event_id) REFERENCES recall_events (id)
);
CREATE TABLE recall_revisions (
	id VARCHAR(64) NOT NULL, 
	campaign_number VARCHAR(9) NOT NULL, 
	revision INTEGER NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	previous_snapshot_id VARCHAR(64), 
	records_hash VARCHAR(64) NOT NULL, 
	records JSON NOT NULL, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (campaign_number, revision), 
	FOREIGN KEY(snapshot_id) REFERENCES recall_snapshots (id), 
	FOREIGN KEY(previous_snapshot_id) REFERENCES recall_snapshots (id)
);
CREATE TABLE recall_rule_revisions (
	id VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	archived BOOLEAN NOT NULL, 
	interval_seconds INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (rule_id, revision), 
	FOREIGN KEY(rule_id) REFERENCES recall_monitor_rules (id)
);
CREATE TABLE recall_search_snapshots (
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	"query" JSON NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	body TEXT NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	discovery JSON NOT NULL, 
	discovery_hash VARCHAR(64) NOT NULL, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE recall_search_verifications (
	id VARCHAR(64) NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	etag TEXT, 
	last_modified TEXT, 
	parser_identity JSON, 
	verified_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(snapshot_id) REFERENCES recall_search_snapshots (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE recall_snapshots (
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	campaign_number VARCHAR(9) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	body TEXT NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	records JSON NOT NULL, 
	records_hash VARCHAR(64) NOT NULL, 
	revision INTEGER, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE recall_verifications (
	id VARCHAR(64) NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	etag TEXT, 
	last_modified TEXT, 
	parser_identity JSON, 
	verified_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(snapshot_id) REFERENCES recall_snapshots (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE rejected_observations (
	id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	target_kind VARCHAR(16) NOT NULL, 
	stage VARCHAR(16) NOT NULL, 
	reason VARCHAR(80) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	raw_body BLOB NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	observed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE reparse_completions (
	id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	error_code VARCHAR(80), 
	candidate JSON, 
	quality JSON, 
	diff JSON, 
	receipt JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	completed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id), 
	FOREIGN KEY(run_id) REFERENCES reparse_runs (id)
);
CREATE TABLE reparse_reviews (
	id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	completion_fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, revision), 
	FOREIGN KEY(run_id) REFERENCES reparse_runs (id)
);
CREATE TABLE reparse_runs (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	capture_id VARCHAR(64) NOT NULL, 
	input JSON NOT NULL, 
	parser JSON NOT NULL, 
	baseline JSON, 
	input_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(capture_id) REFERENCES raw_captures (id)
);
CREATE TABLE report_exports (
	id VARCHAR(64) NOT NULL, 
	report_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	format VARCHAR(16) NOT NULL, 
	renderer_version VARCHAR(80) NOT NULL, 
	document_hash VARCHAR(64) NOT NULL, 
	content_type VARCHAR(80) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	byte_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (report_id, revision, format, renderer_version), 
	FOREIGN KEY(report_id) REFERENCES research_reports (id)
);
CREATE TABLE research_report_revisions (
	id VARCHAR(64) NOT NULL, 
	report_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	title VARCHAR(160) NOT NULL, 
	notes VARCHAR(4000) NOT NULL, 
	archived BOOLEAN NOT NULL, 
	operation VARCHAR(16) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (report_id, revision), 
	FOREIGN KEY(report_id) REFERENCES research_reports (id)
);
CREATE TABLE research_reports (
	id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	pack_id VARCHAR(64) NOT NULL, 
	analysis_id VARCHAR(64), 
	privacy_class VARCHAR(16) NOT NULL, 
	body JSON NOT NULL, 
	body_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_session_id, idempotency_key), 
	FOREIGN KEY(pack_id) REFERENCES ai_evidence_packs (id), 
	FOREIGN KEY(analysis_id) REFERENCES ai_requests (id)
);
CREATE TABLE saved_comparison_revisions (
	id VARCHAR(64) NOT NULL, 
	comparison_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	title VARCHAR(120) NOT NULL, 
	notes TEXT NOT NULL, 
	archived BOOLEAN NOT NULL, 
	operation VARCHAR(16) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (comparison_id, revision), 
	FOREIGN KEY(comparison_id) REFERENCES saved_comparisons (id), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE saved_comparisons (
	id VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	payload JSON NOT NULL, 
	variant_count INTEGER NOT NULL, 
	include_manual BOOLEAN NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE snapshots (
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	body TEXT NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	identity_contract_version VARCHAR(80), 
	observed_at DATETIME NOT NULL, 
	etag TEXT, 
	last_modified TEXT, 
	parsed_variants JSON NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE source_material_outcomes (
	request_id VARCHAR(64) NOT NULL, 
	state VARCHAR(20) NOT NULL, 
	failure_code VARCHAR(80), 
	document_id VARCHAR(64), 
	receipt JSON, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (request_id), 
	CHECK (state IN ('succeeded','failed')), 
	FOREIGN KEY(request_id) REFERENCES source_material_requests (id), 
	UNIQUE (document_id), 
	FOREIGN KEY(document_id) REFERENCES evidence_documents (id)
);
CREATE TABLE source_material_requests (
	id VARCHAR(64) NOT NULL, 
	actor_user_id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(36) NOT NULL, 
	operator VARCHAR(80) NOT NULL, 
	payload JSON NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	policy JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_user_id, idempotency_key)
);
CREATE TABLE source_quarantines (
	id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	previous_snapshot_id VARCHAR(64) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	body TEXT NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	observed_at DATETIME NOT NULL, 
	candidates JSON NOT NULL, 
	quality JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id), 
	FOREIGN KEY(previous_snapshot_id) REFERENCES snapshots (id)
);
CREATE TABLE source_setting_revisions (
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(20) NOT NULL, 
	state VARCHAR(20) NOT NULL, 
	notes VARCHAR(2000) NOT NULL, 
	access_generation INTEGER NOT NULL, 
	"before" JSON NOT NULL, 
	"after" JSON NOT NULL, 
	catalog_fingerprint VARCHAR(64) NOT NULL, 
	preview_fingerprint VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (source_id, revision), 
	UNIQUE (actor_session_id, idempotency_key), 
	CHECK (revision > 0 AND access_generation >= 0), 
	CHECK (state IN ('enabled', 'paused', 'archived')), 
	CHECK (action IN ('enable', 'pause', 'archive', 'restore', 'edit_notes'))
);
CREATE TABLE test_event_revisions (
	id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	payload JSON NOT NULL, 
	summary JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	operator VARCHAR(80) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (event_id, revision), 
	FOREIGN KEY(event_id) REFERENCES test_events (id)
);
CREATE TABLE test_events (
	id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE test_sku_link_revisions (
	id VARCHAR(64) NOT NULL, 
	link_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	review_state VARCHAR(24) NOT NULL, 
	declaration_revision_id VARCHAR(64) NOT NULL, 
	declared_by_user_id VARCHAR(64) NOT NULL, 
	selection JSON NOT NULL, 
	materials JSON NOT NULL, 
	evidence_level VARCHAR(80) NOT NULL, 
	frozen_evidence JSON NOT NULL, 
	material_evidence JSON NOT NULL, 
	assertions JSON NOT NULL, 
	checks JSON NOT NULL, 
	binding JSON NOT NULL, 
	binding_hash VARCHAR(64) NOT NULL, 
	"before" JSON, 
	"after" JSON NOT NULL, 
	attestation JSON NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_user_id VARCHAR(64) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (link_id, revision), 
	UNIQUE (actor_user_id, idempotency_key), 
	FOREIGN KEY(link_id) REFERENCES test_sku_links (id)
);
CREATE TABLE test_sku_links (
	id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64) NOT NULL, 
	participant_key VARCHAR(40) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (event_id, participant_key), 
	FOREIGN KEY(event_id) REFERENCES test_events (id)
);
CREATE TABLE tire_catalog_revisions (
	id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	verification_id VARCHAR(64) NOT NULL, 
	previous_verification_id VARCHAR(64), 
	snapshot_id VARCHAR(64) NOT NULL, 
	previous_snapshot_id VARCHAR(64), 
	revision INTEGER NOT NULL, 
	action VARCHAR(12) NOT NULL, 
	before_present BOOLEAN NOT NULL, 
	after_present BOOLEAN NOT NULL, 
	binding JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (variant_id, source_id, query_key, revision), 
	UNIQUE (variant_id, verification_id), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(verification_id) REFERENCES verifications (id), 
	FOREIGN KEY(previous_verification_id) REFERENCES verifications (id), 
	FOREIGN KEY(snapshot_id) REFERENCES snapshots (id), 
	FOREIGN KEY(previous_snapshot_id) REFERENCES snapshots (id)
);
CREATE TABLE tire_curation_applicability_events (
	id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	before_fact_id VARCHAR(64) NOT NULL, 
	after_fact_id VARCHAR(64) NOT NULL, 
	verification_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(24) NOT NULL, 
	manual_revision_watermark INTEGER NOT NULL, 
	affected JSON NOT NULL, 
	binding JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (variant_id, source_id, revision), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(before_fact_id) REFERENCES fact_versions (id), 
	UNIQUE (after_fact_id), 
	FOREIGN KEY(after_fact_id) REFERENCES fact_versions (id), 
	FOREIGN KEY(verification_id) REFERENCES verifications (id)
);
CREATE TABLE tire_schema_versions (version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE tire_variants (
	id VARCHAR(64) NOT NULL, 
	identity_key VARCHAR(64) NOT NULL, 
	identity JSON NOT NULL, 
	identity_status VARCHAR(24) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (identity_key)
);
CREATE TABLE users (
	id VARCHAR(64) NOT NULL, 
	username VARCHAR(32) NOT NULL, 
	display_name VARCHAR(80) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE variant_identity_bindings (
	id VARCHAR(64) NOT NULL, 
	schema VARCHAR(80) NOT NULL, 
	canonical_key VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	current_identity JSON NOT NULL, 
	identity_status VARCHAR(24) NOT NULL, 
	origin VARCHAR(40) NOT NULL, 
	proof JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	migration_id VARCHAR(64), 
	legacy_candidate_id VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (schema, canonical_key), 
	UNIQUE (schema, variant_id), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(migration_id) REFERENCES variant_identity_migration_applications (id), 
	FOREIGN KEY(legacy_candidate_id) REFERENCES tire_variants (id)
);
CREATE TABLE variant_identity_migration_applications (
	id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	schema VARCHAR(80) NOT NULL, 
	contract_digest VARCHAR(64) NOT NULL, 
	preview_fingerprint VARCHAR(64) NOT NULL, 
	summary JSON NOT NULL, 
	assessments JSON NOT NULL, 
	binding_ids JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	operator VARCHAR(100) NOT NULL, 
	reason VARCHAR(2000) NOT NULL, 
	actor_session_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (revision), 
	UNIQUE (actor_session_id, idempotency_key)
);
CREATE TABLE variant_lifecycle_events (
	id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	before_state VARCHAR(16) NOT NULL, 
	after_state VARCHAR(16) NOT NULL, 
	operator_session_id VARCHAR(64) NOT NULL, 
	operator VARCHAR(80) NOT NULL, 
	reason TEXT NOT NULL, 
	evidence JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (variant_id, revision), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id), 
	FOREIGN KEY(operator_session_id) REFERENCES local_sessions (id)
);
CREATE TABLE vehicle_manufacturers (
	id VARCHAR(80) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE vehicle_models (
	id VARCHAR(80) NOT NULL, 
	manufacturer_id VARCHAR(80) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	generation VARCHAR(80) NOT NULL, 
	model_year INTEGER, 
	region VARCHAR(40) NOT NULL, 
	source_vehicle_id VARCHAR(80) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(manufacturer_id) REFERENCES vehicle_manufacturers (id)
);
CREATE TABLE vehicle_quarantines (
	id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	vehicle_id VARCHAR(80) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	previous_snapshot_id VARCHAR(64) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	body TEXT NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	observed_at DATETIME NOT NULL, 
	payload JSON NOT NULL, 
	quality JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (query_id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicle_models (id), 
	FOREIGN KEY(previous_snapshot_id) REFERENCES vehicle_snapshots (id)
);
CREATE TABLE vehicle_snapshots (
	id VARCHAR(64) NOT NULL, 
	vehicle_id VARCHAR(80) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	source_url TEXT NOT NULL, 
	raw_hash VARCHAR(64) NOT NULL, 
	body TEXT NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	parser_identity JSON, 
	observed_at DATETIME NOT NULL, 
	payload JSON NOT NULL, 
	fact_hash VARCHAR(64) NOT NULL, 
	fact_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicle_models (id)
);
CREATE TABLE vehicle_trims (
	id VARCHAR(120) NOT NULL, 
	vehicle_id VARCHAR(80) NOT NULL, 
	source_trim_id VARCHAR(80) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	model_year INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicle_models (id)
);
CREATE TABLE vehicle_verifications (
	id VARCHAR(64) NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	vehicle_id VARCHAR(80) NOT NULL, 
	parser_identity JSON, 
	verified_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(snapshot_id) REFERENCES vehicle_snapshots (id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE vehicle_wheel_fitments (
	id VARCHAR(64) NOT NULL, 
	option_id VARCHAR(64) NOT NULL, 
	trim_id VARCHAR(120) NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	specification JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(trim_id) REFERENCES vehicle_trims (id), 
	FOREIGN KEY(snapshot_id) REFERENCES vehicle_snapshots (id)
);
CREATE TABLE verifications (
	id VARCHAR(64) NOT NULL, 
	snapshot_id VARCHAR(64) NOT NULL, 
	query_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(80) NOT NULL, 
	query_key VARCHAR(64) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	parser_identity JSON, 
	etag TEXT, 
	last_modified TEXT, 
	verified_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(snapshot_id) REFERENCES snapshots (id), 
	FOREIGN KEY(query_id) REFERENCES query_runs (id)
);
CREATE TABLE watch_items (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (session_id, variant_id), 
	FOREIGN KEY(session_id) REFERENCES local_sessions (id), 
	FOREIGN KEY(variant_id) REFERENCES tire_variants (id)
);
CREATE TABLE webhook_attempts (
	id VARCHAR(64) NOT NULL, 
	envelope_id VARCHAR(64) NOT NULL, 
	number INTEGER NOT NULL, 
	token VARCHAR(64) NOT NULL, 
	started_at DATETIME NOT NULL, 
	lease_until DATETIME NOT NULL, 
	signing_timestamp VARCHAR(24) NOT NULL, 
	body_sha256 VARCHAR(64) NOT NULL, 
	policy_fingerprint VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (envelope_id, number), 
	FOREIGN KEY(envelope_id) REFERENCES webhook_envelopes (id), 
	UNIQUE (token)
);
CREATE TABLE webhook_completions (
	attempt_id VARCHAR(64) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	error_code VARCHAR(80), 
	http_status INTEGER, 
	completed_at DATETIME NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	PRIMARY KEY (attempt_id), 
	FOREIGN KEY(attempt_id) REFERENCES webhook_attempts (id)
);
CREATE TABLE webhook_dispatch_slots (
	id VARCHAR(16) NOT NULL, 
	token VARCHAR(64), 
	attempt_id VARCHAR(64), 
	lease_until DATETIME, 
	PRIMARY KEY (id)
);
CREATE TABLE webhook_envelopes (
	id VARCHAR(64) NOT NULL, 
	subscription_id VARCHAR(64) NOT NULL, 
	revision_id VARCHAR(64) NOT NULL, 
	owner_user_id VARCHAR(64) NOT NULL, 
	channel VARCHAR(24) NOT NULL, 
	notification_id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64) NOT NULL, 
	domain VARCHAR(24), 
	association JSON NOT NULL, 
	body TEXT NOT NULL, 
	body_sha256 VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (subscription_id, channel, notification_id), 
	FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions (id), 
	FOREIGN KEY(revision_id) REFERENCES webhook_revisions (id)
);
CREATE TABLE webhook_operations (
	id VARCHAR(64) NOT NULL, 
	owner_user_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	action VARCHAR(24) NOT NULL, 
	method VARCHAR(8) NOT NULL, 
	path VARCHAR(300) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	resource_type VARCHAR(16) NOT NULL, 
	resource_id VARCHAR(64) NOT NULL, 
	response JSON NOT NULL, 
	response_hash VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_user_id, idempotency_key)
);
CREATE TABLE webhook_overflows (
	revision_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (revision_id), 
	FOREIGN KEY(revision_id) REFERENCES webhook_revisions (id)
);
CREATE TABLE webhook_queue (
	id VARCHAR(64) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	attempts INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	next_attempt_at DATETIME, 
	completed_at DATETIME, 
	error_code VARCHAR(80), 
	http_status INTEGER, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(id) REFERENCES webhook_envelopes (id)
);
CREATE TABLE webhook_revisions (
	id VARCHAR(64) NOT NULL, 
	subscription_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (subscription_id, revision), 
	FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions (id)
);
CREATE TABLE webhook_statistics (
	subscription_id VARCHAR(64) NOT NULL, 
	suppressed_count INTEGER NOT NULL, 
	last_suppressed_at DATETIME, 
	PRIMARY KEY (subscription_id), 
	FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions (id)
);
CREATE TABLE webhook_subscriptions (
	id VARCHAR(64) NOT NULL, 
	owner_user_id VARCHAR(64) NOT NULL, 
	target_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE webhook_target_slots (
	target_id VARCHAR(64) NOT NULL, 
	next_allowed_at DATETIME NOT NULL, 
	PRIMARY KEY (target_id)
);
CREATE VIRTUAL TABLE knowledge_fts USING fts5(document_id UNINDEXED, tokens, tokenize="unicode61");
CREATE INDEX ix_ai_draft_applications_actor_session_id ON ai_draft_applications (actor_session_id);
CREATE INDEX ix_ai_evidence_packs_actor_session_id ON ai_evidence_packs (actor_session_id);
CREATE INDEX ix_ai_requests_actor_session_id ON ai_requests (actor_session_id);
CREATE INDEX ix_ai_requests_created_at ON ai_requests (created_at);
CREATE INDEX ix_ai_stream_events_request_id ON ai_stream_events (request_id);
CREATE INDEX ix_alert_events_change_id ON alert_events (change_id);
CREATE INDEX ix_alert_events_rule_id ON alert_events (rule_id);
CREATE INDEX ix_alert_rule_revisions_rule_id ON alert_rule_revisions (rule_id);
CREATE INDEX ix_alert_rules_job_id ON alert_rules (job_id);
CREATE INDEX ix_audit_events_session_id ON audit_events (session_id);
CREATE INDEX ix_candidate_ai_authorizations_scope_hash ON candidate_ai_authorizations (scope_hash);
CREATE INDEX ix_candidate_ai_preparations_actor_session_id ON candidate_ai_preparations (actor_session_id);
CREATE INDEX ix_candidate_ai_preparations_actor_user_id ON candidate_ai_preparations (actor_user_id);
CREATE INDEX ix_change_events_variant_id ON change_events (variant_id);
CREATE INDEX ix_device_ai_consent_claims_actor_session_id ON device_ai_consent_claims (actor_session_id);
CREATE INDEX ix_device_ai_preparations_actor_session_id ON device_ai_preparations (actor_session_id);
CREATE INDEX ix_discovery_attempt_job_started ON recall_discovery_task_attempts (kind, job_id, started_at);
CREATE INDEX ix_discovery_event_stream ON recall_discovery_task_events (kind, job_id, sequence);
CREATE INDEX ix_embedding_cache_model_space ON embedding_cache (model_space);
CREATE INDEX ix_embedding_plans_actor_session_id ON embedding_plans (actor_session_id);
CREATE INDEX ix_embedding_requests_actor_session_id ON embedding_requests (actor_session_id);
CREATE INDEX ix_embedding_requests_created_at ON embedding_requests (created_at);
CREATE INDEX ix_evidence_documents_raw_hash ON evidence_documents (raw_hash);
CREATE INDEX ix_external_api_key_operations_owner_user_id ON external_api_key_operations (owner_user_id);
CREATE INDEX ix_external_api_keys_expires_at ON external_api_keys (expires_at);
CREATE INDEX ix_external_api_keys_owner_user_id ON external_api_keys (owner_user_id);
CREATE INDEX ix_fact_versions_source_id ON fact_versions (source_id);
CREATE INDEX ix_fact_versions_variant_id ON fact_versions (variant_id);
CREATE INDEX ix_fitment_relation_revisions_relation_id ON fitment_relation_revisions (relation_id);
CREATE INDEX ix_fitment_relation_revisions_review_state ON fitment_relation_revisions (review_state);
CREATE INDEX ix_fitment_relations_axle ON fitment_relations (axle);
CREATE INDEX ix_fitment_relations_trim_id ON fitment_relations (trim_id);
CREATE INDEX ix_fitment_relations_vehicle_id ON fitment_relations (vehicle_id);
CREATE INDEX ix_garage_revisions_vehicle_id ON garage_revisions (vehicle_id);
CREATE INDEX ix_golden_case_reviews_case_id ON golden_case_reviews (case_id);
CREATE INDEX ix_golden_case_revisions_case_id ON golden_case_revisions (case_id);
CREATE INDEX ix_golden_cases_source_id ON golden_cases (source_id);
CREATE INDEX ix_golden_set_revisions_set_id ON golden_set_revisions (set_id);
CREATE INDEX ix_golden_set_revisions_source_id ON golden_set_revisions (source_id);
CREATE INDEX ix_identity_revisions_target_id ON identity_revisions (target_id);
CREATE INDEX ix_identity_revisions_variant_id ON identity_revisions (variant_id);
CREATE INDEX ix_interest_events_domain ON interest_events (domain);
CREATE INDEX ix_interest_events_observed_at ON interest_events (observed_at);
CREATE INDEX ix_interest_notifications_event_id ON interest_notifications (event_id);
CREATE INDEX ix_interest_notifications_interest_id ON interest_notifications (interest_id);
CREATE INDEX ix_interest_notifications_session_id ON interest_notifications (session_id);
CREATE INDEX ix_interest_revisions_interest_id ON interest_revisions (interest_id);
CREATE INDEX ix_interests_session_id ON interests (session_id);
CREATE INDEX ix_knowledge_documents_kind ON knowledge_documents (kind);
CREATE INDEX ix_knowledge_documents_source_id ON knowledge_documents (source_id);
CREATE INDEX ix_knowledge_documents_variant_id ON knowledge_documents (variant_id);
CREATE INDEX ix_knowledge_facet_lookup ON knowledge_facets (name, value, document_id);
CREATE INDEX ix_local_sessions_user_id ON local_sessions (user_id);
CREATE INDEX ix_manual_fact_revisions_source_id ON manual_fact_revisions (source_id);
CREATE INDEX ix_manual_fact_revisions_variant_id ON manual_fact_revisions (variant_id);
CREATE INDEX ix_monitor_attempt_job_started ON monitor_task_attempts (kind, job_id, started_at);
CREATE INDEX ix_monitor_event_stream ON monitor_task_events (kind, job_id, sequence);
CREATE INDEX ix_monitor_jobs_next_due_at ON monitor_jobs (next_due_at);
CREATE INDEX ix_monitor_runs_job_id ON monitor_runs (job_id);
CREATE INDEX ix_monitor_task_events_attempt_id ON monitor_task_events (attempt_id);
CREATE INDEX ix_monitor_task_events_run_id ON monitor_task_events (run_id);
CREATE INDEX ix_offline_pack_plans_actor_session_id ON offline_pack_plans (actor_session_id);
CREATE INDEX ix_offline_packs_actor_session_id ON offline_packs (actor_session_id);
CREATE INDEX ix_parser_deployment_revisions_source_id ON parser_deployment_revisions (source_id);
CREATE INDEX ix_parser_evaluation_reviews_evaluation_id ON parser_evaluation_reviews (evaluation_id);
CREATE INDEX ix_parser_evaluations_source_id ON parser_evaluations (source_id);
CREATE INDEX ix_quarantine_reviews_binding_hash ON quarantine_reviews (binding_hash);
CREATE INDEX ix_quarantine_reviews_quarantine_id ON quarantine_reviews (quarantine_id);
CREATE INDEX ix_query_fallback_policy_revisions_actor_session_id ON query_fallback_policy_revisions (actor_session_id);
CREATE INDEX ix_query_fallback_policy_revisions_policy_id ON query_fallback_policy_revisions (policy_id);
CREATE INDEX ix_query_fallback_previews_actor_session_id ON query_fallback_previews (actor_session_id);
CREATE INDEX ix_query_fallback_previews_policy_id ON query_fallback_previews (policy_id);
CREATE INDEX ix_query_fallback_uses_actor_session_id ON query_fallback_uses (actor_session_id);
CREATE INDEX ix_query_fallback_uses_policy_id ON query_fallback_uses (policy_id);
CREATE INDEX ix_query_fallback_uses_query_id ON query_fallback_uses (query_id);
CREATE INDEX ix_query_runs_query_key ON query_runs (query_key);
CREATE INDEX ix_query_runs_session_id ON query_runs (session_id);
CREATE INDEX ix_raw_captures_observed_at ON raw_captures (observed_at);
CREATE INDEX ix_raw_captures_source_id ON raw_captures (source_id);
CREATE INDEX ix_recall_discovery_candidates_first_seen_run_id ON recall_discovery_candidates (first_seen_run_id);
CREATE INDEX ix_recall_discovery_candidates_job_id ON recall_discovery_candidates (job_id);
CREATE INDEX ix_recall_discovery_jobs_next_due_at ON recall_discovery_jobs (next_due_at);
CREATE INDEX ix_recall_discovery_jobs_session_id ON recall_discovery_jobs (session_id);
CREATE INDEX ix_recall_discovery_notifications_session_id ON recall_discovery_notifications (session_id);
CREATE INDEX ix_recall_discovery_pages_attempt_id ON recall_discovery_pages (attempt_id);
CREATE INDEX ix_recall_discovery_pages_job_id ON recall_discovery_pages (job_id);
CREATE INDEX ix_recall_discovery_rule_revisions_rule_id ON recall_discovery_rule_revisions (rule_id);
CREATE INDEX ix_recall_discovery_rules_job_id ON recall_discovery_rules (job_id);
CREATE INDEX ix_recall_discovery_rules_session_id ON recall_discovery_rules (session_id);
CREATE INDEX ix_recall_discovery_runs_job_id ON recall_discovery_runs (job_id);
CREATE INDEX ix_recall_discovery_task_events_attempt_id ON recall_discovery_task_events (attempt_id);
CREATE INDEX ix_recall_discovery_task_events_run_id ON recall_discovery_task_events (run_id);
CREATE INDEX ix_recall_monitor_jobs_campaign_number ON recall_monitor_jobs (campaign_number);
CREATE INDEX ix_recall_monitor_jobs_session_id ON recall_monitor_jobs (session_id);
CREATE INDEX ix_recall_monitor_rules_session_id ON recall_monitor_rules (session_id);
CREATE INDEX ix_recall_monitor_runs_job_id ON recall_monitor_runs (job_id);
CREATE INDEX ix_recall_notifications_session_id ON recall_notifications (session_id);
CREATE INDEX ix_recall_revisions_campaign_number ON recall_revisions (campaign_number);
CREATE INDEX ix_recall_rule_revisions_rule_id ON recall_rule_revisions (rule_id);
CREATE INDEX ix_recall_search_snapshots_query_key ON recall_search_snapshots (query_key);
CREATE INDEX ix_recall_search_verifications_query_key ON recall_search_verifications (query_key);
CREATE INDEX ix_recall_search_verifications_snapshot_id ON recall_search_verifications (snapshot_id);
CREATE INDEX ix_recall_snapshots_campaign_number ON recall_snapshots (campaign_number);
CREATE INDEX ix_recall_snapshots_query_key ON recall_snapshots (query_key);
CREATE INDEX ix_recall_verifications_query_key ON recall_verifications (query_key);
CREATE INDEX ix_recall_verifications_snapshot_id ON recall_verifications (snapshot_id);
CREATE INDEX ix_rejected_observations_observed_at ON rejected_observations (observed_at);
CREATE INDEX ix_rejected_observations_query_key ON rejected_observations (query_key);
CREATE INDEX ix_rejected_observations_source_id ON rejected_observations (source_id);
CREATE INDEX ix_reparse_reviews_run_id ON reparse_reviews (run_id);
CREATE INDEX ix_reparse_runs_capture_id ON reparse_runs (capture_id);
CREATE INDEX ix_report_exports_report_id ON report_exports (report_id);
CREATE INDEX ix_research_report_revisions_report_id ON research_report_revisions (report_id);
CREATE INDEX ix_research_reports_actor_session_id ON research_reports (actor_session_id);
CREATE INDEX ix_saved_comparison_revisions_comparison_id ON saved_comparison_revisions (comparison_id);
CREATE INDEX ix_snapshots_query_key ON snapshots (query_key);
CREATE INDEX ix_snapshots_source_id ON snapshots (source_id);
CREATE INDEX ix_source_material_requests_actor_user_id ON source_material_requests (actor_user_id);
CREATE INDEX ix_source_quarantines_observed_at ON source_quarantines (observed_at);
CREATE INDEX ix_source_quarantines_query_key ON source_quarantines (query_key);
CREATE INDEX ix_source_quarantines_source_id ON source_quarantines (source_id);
CREATE INDEX ix_source_setting_revisions_source_id ON source_setting_revisions (source_id);
CREATE INDEX ix_test_event_revisions_event_id ON test_event_revisions (event_id);
CREATE INDEX ix_test_sku_link_revisions_link_id ON test_sku_link_revisions (link_id);
CREATE INDEX ix_test_sku_links_event_id ON test_sku_links (event_id);
CREATE INDEX ix_tire_catalog_revisions_query_key ON tire_catalog_revisions (query_key);
CREATE INDEX ix_tire_catalog_revisions_source_id ON tire_catalog_revisions (source_id);
CREATE INDEX ix_tire_catalog_revisions_variant_id ON tire_catalog_revisions (variant_id);
CREATE INDEX ix_tire_catalog_revisions_verification_id ON tire_catalog_revisions (verification_id);
CREATE INDEX ix_tire_curation_applicability_events_source_id ON tire_curation_applicability_events (source_id);
CREATE INDEX ix_tire_curation_applicability_events_variant_id ON tire_curation_applicability_events (variant_id);
CREATE INDEX ix_tire_curation_applicability_events_verification_id ON tire_curation_applicability_events (verification_id);
CREATE UNIQUE INDEX ix_users_username ON users (username);
CREATE INDEX ix_variant_identity_bindings_legacy_candidate_id ON variant_identity_bindings (legacy_candidate_id);
CREATE INDEX ix_variant_identity_bindings_variant_id ON variant_identity_bindings (variant_id);
CREATE INDEX ix_variant_lifecycle_events_variant_id ON variant_lifecycle_events (variant_id);
CREATE INDEX ix_vehicle_quarantines_observed_at ON vehicle_quarantines (observed_at);
CREATE INDEX ix_vehicle_quarantines_source_id ON vehicle_quarantines (source_id);
CREATE INDEX ix_vehicle_quarantines_vehicle_id ON vehicle_quarantines (vehicle_id);
CREATE INDEX ix_vehicle_snapshots_vehicle_id ON vehicle_snapshots (vehicle_id);
CREATE INDEX ix_vehicle_trims_vehicle_id ON vehicle_trims (vehicle_id);
CREATE INDEX ix_vehicle_verifications_snapshot_id ON vehicle_verifications (snapshot_id);
CREATE INDEX ix_vehicle_verifications_vehicle_id ON vehicle_verifications (vehicle_id);
CREATE INDEX ix_vehicle_wheel_fitments_option_id ON vehicle_wheel_fitments (option_id);
CREATE INDEX ix_vehicle_wheel_fitments_trim_id ON vehicle_wheel_fitments (trim_id);
CREATE INDEX ix_verifications_query_id ON verifications (query_id);
CREATE INDEX ix_verifications_query_key ON verifications (query_key);
CREATE INDEX ix_verifications_snapshot_id ON verifications (snapshot_id);
CREATE INDEX ix_watch_items_session_id ON watch_items (session_id);
CREATE INDEX ix_webhook_attempts_envelope_id ON webhook_attempts (envelope_id);
CREATE INDEX ix_webhook_envelopes_subscription_id ON webhook_envelopes (subscription_id);
CREATE INDEX ix_webhook_operations_owner_user_id ON webhook_operations (owner_user_id);
CREATE INDEX ix_webhook_queue_next_attempt_at ON webhook_queue (next_attempt_at);
CREATE INDEX ix_webhook_queue_state ON webhook_queue (state);
CREATE INDEX ix_webhook_revisions_subscription_id ON webhook_revisions (subscription_id);
CREATE INDEX ix_webhook_subscriptions_owner_user_id ON webhook_subscriptions (owner_user_id);
CREATE TRIGGER candidate_ai_authorizations_no_delete BEFORE DELETE ON candidate_ai_authorizations BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_authorizations_no_replace BEFORE INSERT ON candidate_ai_authorizations WHEN EXISTS (SELECT 1 FROM candidate_ai_authorizations WHERE id = NEW.id OR (scope_hash = NEW.scope_hash AND revision = NEW.revision)) BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_authorizations_no_update BEFORE UPDATE ON candidate_ai_authorizations BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_claims_no_delete BEFORE DELETE ON candidate_ai_claims BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_claims_no_replace BEFORE INSERT ON candidate_ai_claims WHEN EXISTS (SELECT 1 FROM candidate_ai_claims WHERE id = NEW.id OR (preparation_id = NEW.preparation_id OR request_id = NEW.request_id)) BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_claims_no_update BEFORE UPDATE ON candidate_ai_claims BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_preparations_no_delete BEFORE DELETE ON candidate_ai_preparations BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_preparations_no_replace BEFORE INSERT ON candidate_ai_preparations WHEN EXISTS (SELECT 1 FROM candidate_ai_preparations WHERE id = NEW.id OR (pack_id = NEW.pack_id)) BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER candidate_ai_preparations_no_update BEFORE UPDATE ON candidate_ai_preparations BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END;
CREATE TRIGGER device_ai_consent_claims_no_delete BEFORE DELETE ON device_ai_consent_claims BEGIN SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END;
CREATE TRIGGER device_ai_consent_claims_no_replace BEFORE INSERT ON device_ai_consent_claims WHEN EXISTS(SELECT 1 FROM device_ai_consent_claims WHERE id = NEW.id OR (actor_session_id = NEW.actor_session_id AND analysis_key = NEW.analysis_key) OR preparation_id = NEW.preparation_id OR ai_request_id = NEW.ai_request_id) BEGIN SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END;
CREATE TRIGGER device_ai_consent_claims_no_update BEFORE UPDATE ON device_ai_consent_claims BEGIN SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END;
CREATE TRIGGER device_ai_preparations_no_delete BEFORE DELETE ON device_ai_preparations BEGIN SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END;
CREATE TRIGGER device_ai_preparations_no_replace BEFORE INSERT ON device_ai_preparations WHEN EXISTS(SELECT 1 FROM device_ai_preparations WHERE id = NEW.id OR (actor_session_id = NEW.actor_session_id AND idempotency_key = NEW.idempotency_key) OR (actor_session_id = NEW.actor_session_id AND host_receipt_id = NEW.host_receipt_id) OR (actor_session_id = NEW.actor_session_id AND intent_id = NEW.intent_id) OR ai_pack_id = NEW.ai_pack_id) BEGIN SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END;
CREATE TRIGGER device_ai_preparations_no_update BEFORE UPDATE ON device_ai_preparations BEGIN SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END;
CREATE TRIGGER external_api_key_operations_no_delete BEFORE DELETE ON external_api_key_operations BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_key_operations_no_replace BEFORE INSERT ON external_api_key_operations WHEN EXISTS (SELECT 1 FROM external_api_key_operations WHERE id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key)) BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_key_operations_no_update BEFORE UPDATE ON external_api_key_operations BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_key_revocations_no_delete BEFORE DELETE ON external_api_key_revocations BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_key_revocations_no_replace BEFORE INSERT ON external_api_key_revocations WHEN EXISTS (SELECT 1 FROM external_api_key_revocations WHERE key_id = NEW.key_id) BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_key_revocations_no_update BEFORE UPDATE ON external_api_key_revocations BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_keys_no_delete BEFORE DELETE ON external_api_keys BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_keys_no_replace BEFORE INSERT ON external_api_keys WHEN EXISTS (SELECT 1 FROM external_api_keys WHERE id = NEW.id OR bearer_sha256 = NEW.bearer_sha256) BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER external_api_keys_no_update BEFORE UPDATE ON external_api_keys BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END;
CREATE TRIGGER source_material_outcomes_no_delete BEFORE DELETE ON source_material_outcomes BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END;
CREATE TRIGGER source_material_outcomes_no_replace BEFORE INSERT ON source_material_outcomes WHEN EXISTS(SELECT 1 FROM source_material_outcomes WHERE request_id = NEW.request_id OR (document_id IS NOT NULL AND document_id = NEW.document_id)) BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END;
CREATE TRIGGER source_material_outcomes_no_update BEFORE UPDATE ON source_material_outcomes BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END;
CREATE TRIGGER source_material_requests_no_delete BEFORE DELETE ON source_material_requests BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END;
CREATE TRIGGER source_material_requests_no_replace BEFORE INSERT ON source_material_requests WHEN EXISTS(SELECT 1 FROM source_material_requests WHERE id = NEW.id OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)) BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END;
CREATE TRIGGER source_material_requests_no_update BEFORE UPDATE ON source_material_requests BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END;
CREATE TRIGGER test_sku_link_revisions_no_delete BEFORE DELETE ON test_sku_link_revisions BEGIN SELECT RAISE(FAIL, 'test_sku_link_immutable'); END;
CREATE TRIGGER test_sku_link_revisions_no_replace BEFORE INSERT ON test_sku_link_revisions WHEN EXISTS(SELECT 1 FROM test_sku_link_revisions WHERE id = NEW.id OR (link_id = NEW.link_id AND revision = NEW.revision) OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)) BEGIN SELECT RAISE(FAIL, 'test_sku_link_immutable'); END;
CREATE TRIGGER test_sku_link_revisions_no_update BEFORE UPDATE ON test_sku_link_revisions BEGIN SELECT RAISE(FAIL, 'test_sku_link_immutable'); END;
CREATE TRIGGER test_sku_links_no_delete BEFORE DELETE ON test_sku_links BEGIN SELECT RAISE(FAIL, 'test_sku_link_immutable'); END;
CREATE TRIGGER test_sku_links_no_replace BEFORE INSERT ON test_sku_links WHEN EXISTS(SELECT 1 FROM test_sku_links WHERE id = NEW.id OR (event_id = NEW.event_id AND participant_key = NEW.participant_key)) BEGIN SELECT RAISE(FAIL, 'test_sku_link_immutable'); END;
CREATE TRIGGER test_sku_links_no_update BEFORE UPDATE ON test_sku_links BEGIN SELECT RAISE(FAIL, 'test_sku_link_immutable'); END;
CREATE TRIGGER webhook_attempts_no_delete BEFORE DELETE ON webhook_attempts BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_attempts_no_replace BEFORE INSERT ON webhook_attempts WHEN EXISTS (SELECT 1 FROM webhook_attempts WHERE id = NEW.id OR token = NEW.token OR (envelope_id = NEW.envelope_id AND number = NEW.number)) BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_attempts_no_update BEFORE UPDATE ON webhook_attempts BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_completions_no_delete BEFORE DELETE ON webhook_completions BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_completions_no_replace BEFORE INSERT ON webhook_completions WHEN EXISTS (SELECT 1 FROM webhook_completions WHERE attempt_id = NEW.attempt_id) BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_completions_no_update BEFORE UPDATE ON webhook_completions BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_envelopes_no_delete BEFORE DELETE ON webhook_envelopes BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_envelopes_no_replace BEFORE INSERT ON webhook_envelopes WHEN EXISTS (SELECT 1 FROM webhook_envelopes WHERE id = NEW.id OR (subscription_id = NEW.subscription_id AND channel = NEW.channel AND notification_id = NEW.notification_id)) BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_envelopes_no_update BEFORE UPDATE ON webhook_envelopes BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_operations_no_delete BEFORE DELETE ON webhook_operations BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_operations_no_replace BEFORE INSERT ON webhook_operations WHEN EXISTS (SELECT 1 FROM webhook_operations WHERE id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key)) BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_operations_no_update BEFORE UPDATE ON webhook_operations BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_overflows_no_delete BEFORE DELETE ON webhook_overflows BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_overflows_no_replace BEFORE INSERT ON webhook_overflows WHEN EXISTS (SELECT 1 FROM webhook_overflows WHERE revision_id = NEW.revision_id) BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_overflows_no_update BEFORE UPDATE ON webhook_overflows BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_revisions_no_delete BEFORE DELETE ON webhook_revisions BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_revisions_no_replace BEFORE INSERT ON webhook_revisions WHEN EXISTS (SELECT 1 FROM webhook_revisions WHERE id = NEW.id OR (subscription_id = NEW.subscription_id AND revision = NEW.revision)) BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_revisions_no_update BEFORE UPDATE ON webhook_revisions BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_subscriptions_no_delete BEFORE DELETE ON webhook_subscriptions BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_subscriptions_no_replace BEFORE INSERT ON webhook_subscriptions WHEN EXISTS (SELECT 1 FROM webhook_subscriptions WHERE id = NEW.id) BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
CREATE TRIGGER webhook_subscriptions_no_update BEFORE UPDATE ON webhook_subscriptions BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END;
