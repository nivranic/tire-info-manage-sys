/* Real private API acceptance over synthetic production source/curation writes.
 * Random credentials remain only in browser memory; no request is mocked.
 */
(async () => {
  const records = [];
  const check = (name, ok, detail = null) => {
    records.push({ name, passed: Boolean(ok), detail });
    if (!ok) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const request = async (path, method = 'GET', body) => {
    const response = await fetch('/api' + path, { method, credentials: 'include', cache: 'no-store',
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
    return { status: response.status, body: await response.json() };
  };
  const notices = async () => (await request('/v1/interest-notifications?mode=history&limit=100')).body;
  const create = async (name, conditions, changed_fields) => {
    const result = await request('/v1/interests', 'POST', { name, enabled: true, conditions, metric_keys: [], changed_fields });
    check('interest:create:' + name, result.status === 201, result.status);
    return result.body;
  };
  const original = async ref => {
    const response = await request('/v1/interest-evidence/' + ref.kind + '/' + ref.record_id + '?mode=history');
    check('reader:exact:' + ref.kind, response.status === 200 && response.body.schema === 'interest-original-evidence@1'
      && response.body.record_id === ref.record_id && response.body.entity_id === ref.entity_id
      && response.body.revision === ref.revision && response.body.fingerprint === ref.fingerprint, response.status);
    check('reader:no-internal-or-dynamic-fields', !Object.keys(response.body.record).some(key => /session_id|valid_to|idempotency_key/.test(key)));
    return response.body;
  };
  window.__interestApplicabilityQA = { records, done: false };
  try {
    const password = Array.from(crypto.getRandomValues(new Uint8Array(20)), byte => byte.toString(16).padStart(2, '0')).join('');
    const auth = await request('/v1/auth/register', 'POST', { username: 'applicability-qa-' + Date.now(), password });
    check('auth:private-first-admin', auth.status === 200);
    const capabilities = await request('/v1/interests/capabilities?mode=history');
    check('capabilities:seven-kinds-nine-domains', capabilities.status === 200 && capabilities.body.kinds.length === 7
      && capabilities.body.domains.length === 9 && capabilities.body.domains.some(item => item.domain === 'tire_curation_validity'
        && item.supported && item.event_kinds.includes('invalidate')) && capabilities.body.network_refresh === false);
    check('capabilities:applicability-delivered-other-gaps-retained', capabilities.body.changed_fields.includes('curation_applicability')
      && !capabilities.body.unsupported_events.some(item => item.kind === 'derived_manual_applicability')
      && ['source_quality_rejection', 'metadata_only_verification'].every(kind => capabilities.body.unsupported_events.some(item => item.kind === kind)));
    const state = (await request('/fixture/state')).body;
    check('fixture:typed-private-four-row-mode', state.applicability_qa_enabled && state.variants.length === 4);
    const variant = state.variants.find(item => item.identity.brand === 'Fixture Brand' && item.identity.size === '265/40R20');
    check('fixture:precise-typed-R-identity', variant?.identity.product_code_type === 'MSPN');
    const condition = [{ kind: 'brand', values: ['Fixture Brand'] }, { kind: 'size', values: ['265/40R20'] }];
    const all = await create('适用性R状态', condition, ['curation_applicability']);
    const facts = await create('适用性R有效UTQG', condition, ['facts.utqg_treadwear']);
    const depth = await create('适用性R有效胎纹', condition, ['facts.tread_depth']);
    const near = await create('适用性ZR不得混配', [{ kind: 'size', values: ['265/40ZR20'] }], ['curation_applicability']);
    const mixed = await create('适用性未审车型不得推配', [{ kind: 'vehicle_fitment', values: [{ vehicle_id: state.vehicle_id, axle: 'rear' }] }, ...condition], ['curation_applicability']);
    check('future-only:no-interest-backfill', (await notices()).total === 0);
    const review = async () => (await request('/v1/tire-variants/' + variant.id + '/fact-review?mode=history&source_id=fixture')).body;
    const curate = async (field, action, value) => {
      const head = await review();
      const response = await request('/v1/tire-variants/' + variant.id + '/fact-revisions', 'POST', {
        source_id: 'fixture', base_fact_id: head.base_fact_id, expected_revision: head.revision, field, action,
        ...(action === 'manual_override' ? { value } : {}), operator: 'Synthetic browser QA',
        reason: 'Project-authored synthetic applicability acceptance',
        evidence: [{ snapshot_id: head.provenance.snapshot_id, locator: '/parsed_variants/exact-synthetic-R' }],
      });
      check('curation:production:' + action + ':' + field, response.status === 201, response.status);
      return response.body;
    };
    const source = async params => {
      const response = await request('/fixture/applicability/source?' + new URLSearchParams(params), 'POST');
      check('source:accepted-production-observation', response.status === 200 && ['live', 'live_verified_304'].includes(response.body.data_state),
        { status: response.status, data_state: response.body.data_state, reason: response.body.reason });
      check('source:typed-identity-preserved-across-query', response.body.variants.some(item => item.id === variant.id));
      return response.body;
    };
    const changes = async () => (await notices()).items.filter(item => item.interest_id === all.id && item.event.domain === 'tire_curation_validity');
    await curate('utqg_treadwear', 'manual_override', 450);
    const revoked = await curate('tread_depth', 'revoke');
    check('curation:two-original-human-decisions', revoked.revision === 2 && revoked.effective_facts.utqg_treadwear === 450
      && !Object.hasOwn(revoked.effective_facts, 'tread_depth'));
    await source({ depth: '8' });
    let changed = await changes();
    check('applicability:one-aggregate-invalidation', changed.length === 1);
    const first = changed[0];
    const firstRef = first.event.evidence.find(ref => ref.kind === 'tire_curation_applicability_event');
    const firstOriginal = await original(firstRef);
    const affected = firstOriginal.record.affected;
    check('applicability:two-real-original-heads-frozen', affected.length === 2
      && affected.some(item => item.field === 'utqg_treadwear' && item.before_status === 'manual_override')
      && affected.some(item => item.field === 'tread_depth' && item.before_status === 'revoked')
      && affected.every(item => item.after_status === 'needs_review' && item.manual_revision_id && item.manual_fingerprint));
    check('applicability:effective-and-source-values-distinct', first.event.before.facts.utqg_treadwear === 450
      && first.event.before.source_facts.utqg_treadwear === 300 && first.event.after.facts.utqg_treadwear === 300
      && !Object.hasOwn(first.event.before.facts, 'tread_depth') && first.event.after.facts.tread_depth.value === 8);
    check('applicability:true-effective-paths', ['facts.utqg_treadwear', 'curation_applicability', 'state'].every(path =>
      first.event.changed_paths.some(changed => changed === path || changed.startsWith(path + '.'))));
    const human = await review();
    check('applicability:no-fabricated-human-revision', human.revision === 2 && human.history.length === 2
      && human.fields.utqg_treadwear.status === 'needs_review' && human.fields.tread_depth.status === 'needs_review');
    const manualRef = first.event.evidence.find(ref => ref.kind === 'tire_curation_revision'
      && ref.record_id === affected.find(item => item.field === 'utqg_treadwear').manual_revision_id);
    const manualOriginal = await original(manualRef);
    check('applicability:manual-original-still450', manualOriginal.record.after.value === 450);
    const late = await create('适用性之后启用不补发', condition, ['curation_applicability']);
    check('future-only:new-interest-does-not-receive-old-invalidation', !(await notices()).items.some(item => item.interest_id === late.id));
    await source({ depth: '9' });
    check('applicability:already-needs-review-not-repeated', (await changes()).length === 1);

    const zero = await curate('utqg_treadwear', 'manual_override', 0);
    await source({ raw_only: 'true' });
    check('applicability:raw-only-no-new-base', (await review()).base_fact_id === zero.base_fact_id && (await changes()).length === 1);
    const verified = await source({ verify_only: 'true' });
    check('applicability:ordinary304-no-new-base', verified.data_state === 'live_verified_304'
      && (await review()).base_fact_id === zero.base_fact_id && (await changes()).length === 1);
    await source({ value: '0' });
    changed = await changes();
    check('applicability:reapplied-zero-invalidates-on-new-source-base', changed.length === 2);
    const equal = changed.find(item => item.event.id !== first.event.id);
    const equalRef = equal.event.evidence.find(ref => ref.kind === 'tire_curation_applicability_event');
    const equalOriginal = await original(equalRef);
    check('applicability:equal-effective-value-is-state-change-only', equal.event.before.facts.utqg_treadwear === 0
      && equal.event.after.facts.utqg_treadwear === 0 && !equal.event.changed_paths.some(path => path === 'facts' || path.startsWith('facts.')));
    check('applicability:UTQG-selector-not-spammed-by-equal-value', !(await notices()).items.some(item =>
      item.interest_id === facts.id && item.event.id === equal.event.id));
    await curate('utqg_treadwear', 'clear_override');
    await source({ value: '100' });
    check('applicability:cleared-head-does-not-invalidate', (await changes()).length === 2 && (await review()).fields.utqg_treadwear.status === 'cleared');

    await source({ scope: 'b', value: '320', depth: '10' });
    const crossManual = await curate('utqg_treadwear', 'manual_override', 420);
    const reconciled = await source({ scope: 'a', verify_only: 'true' });
    changed = await changes();
    check('applicability:cross-query304-is-real-base-change', reconciled.data_state === 'live_verified_304' && changed.length === 3
      && (await review()).base_fact_id !== crossManual.base_fact_id && (await review()).effective_facts.utqg_treadwear === 100);
    const cross = changed.find(item => item.event.id !== first.event.id && item.event.id !== equal.event.id);
    const crossRef = cross.event.evidence.find(ref => ref.kind === 'tire_curation_applicability_event');
    const crossOriginal = await original(crossRef);
    const binding = crossOriginal.record.binding;
    check('applicability:cross-query304-frozen-independent-bases', binding.before.query_key !== binding.after.query_key
      && binding.after.fact_version > binding.after.snapshot_member_fact_version && binding.after.verification_status === 'not_modified'
      && binding.before.fact_version_id === crossManual.base_fact_id && crossOriginal.record.after_fact_id === binding.after.fact_version_id);
    check('applicability:cross-query-effective-original-values', cross.event.before.facts.utqg_treadwear === 420
      && cross.event.before.source_facts.utqg_treadwear === 320 && cross.event.after.facts.utqg_treadwear === 100);
    await curate('utqg_treadwear', 'manual_override', 500);
    await source({ scope: 'b', value: '333', depth: '11' });
    check('applicability:explicit-human-reapply-can-invalidate-again', (await changes()).length === 4);
    await source({ scope: 'b', value: '334' });
    check('applicability:later-refresh-not-repeated', (await changes()).length === 4);
    check('reader:old-derived-record-stable', JSON.stringify(await original(firstRef)) === JSON.stringify(firstOriginal));
    check('reader:old-zero-record-stable', JSON.stringify(await original(equalRef)) === JSON.stringify(equalOriginal));
    check('reader:old-cross-query-record-stable', JSON.stringify(await original(crossRef)) === JSON.stringify(crossOriginal));
    check('reader:old-human-record-stable', JSON.stringify(await original(manualRef)) === JSON.stringify(manualOriginal));
    check('matching:R-ZR-and-unreviewed-fitment-not-inferred', !(await notices()).items.some(item => [near.id, mixed.id].includes(item.interest_id)));
    for (const [kind, id] of [['tire_curation_applicability_event', 'missing-synthetic-record'], ['tire_lifecycle_event', firstRef.record_id]]) {
      check('reader:missing-or-wrong-kind404', (await request('/v1/interest-evidence/' + kind + '/' + id + '?mode=history')).status === 404);
    }
    const beforePreview = (await notices()).total;
    const preview = await request('/v1/interests/preview?mode=history&limit=100', 'POST', { conditions: condition, metric_keys: [], changed_fields: ['curation_applicability'] });
    check('history:read-only-no-delivery', preview.status === 200 && preview.body.matched_count >= 4 && (await notices()).total === beforePreview);
    const final = (await request('/fixture/state')).body;
    check('fixture:no-normal-db-provider-network-or-parser-child', final.normal_database_used === false
      && final.normal_database_attempts === 0 && final.provider_calls === 0 && final.external_network_attempts === 0 && final.parser_children === 0);
    window.__interestApplicabilityQA = { records, done: true, ids: { all: all.id, facts: facts.id, depth: depth.id, near: near.id, mixed: mixed.id, late: late.id },
      references: { firstRef, manualRef, equalRef, crossRef }, frozen_records: { firstOriginal, equalOriginal, crossOriginal },
      totals: { applicability: (await changes()).length, notifications: beforePreview },
      fixture_counters: { normal_database_used: final.normal_database_used, normal_database_attempts: final.normal_database_attempts,
        provider_calls: final.provider_calls, external_network_attempts: final.external_network_attempts, parser_children: final.parser_children } };
  } catch (error) { window.__interestApplicabilityQA.error = String(error); }
  return window.__interestApplicabilityQA;
})();
