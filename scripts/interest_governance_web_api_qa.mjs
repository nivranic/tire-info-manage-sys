/* Private browser QA over production HTTP writes and synthetic source observations.
 * Credentials are generated only in browser memory and never included in results.
 * No normal-store URLs, cookies, model calls or external sources are used here.
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
  const create = async (name, conditions, changed_fields = []) => {
    const result = await request('/v1/interests', 'POST', { name, enabled: true, conditions, metric_keys: [], changed_fields });
    check('create:' + name, result.status === 201, result.status);
    return result.body;
  };
  const original = async ref => {
    const result = await request('/v1/interest-evidence/' + encodeURIComponent(ref.kind) + '/' + encodeURIComponent(ref.record_id) + '?mode=history');
    check('original:' + ref.kind, result.status === 200 && result.body.schema === 'interest-original-evidence@1'
      && result.body.record_id === ref.record_id && result.body.entity_id === ref.entity_id
      && result.body.revision === ref.revision && result.body.fingerprint === ref.fingerprint, result.status);
    check('original:no-internal-session-or-dynamic-applicability', !Object.keys(result.body.record).some(key =>
      /session_id|valid_to/.test(key)));
    return result.body;
  };
  window.__interestGovernanceQA = { records, done: false };
  try {
    const entropy = () => Array.from(crypto.getRandomValues(new Uint8Array(20)), x => x.toString(16).padStart(2, '0')).join('');
    const account = await request('/v1/auth/register', 'POST', { username: 'governance-qa-' + Date.now(), password: entropy() });
    check('auth:private-first-admin', account.status === 200, account.status);
    const cap = await request('/v1/interests/capabilities?mode=history');
    check('capabilities:seven-conditions-eight-domains', cap.status === 200 && cap.body.kinds.length === 7
      && ['tire_curation', 'tire_lifecycle', 'tire_identity', 'tire_catalog'].every(domain => cap.body.domains.some(item => item.domain === domain && item.supported))
      && cap.body.domains.length === 8 && cap.body.network_refresh === false);
    check('capabilities:explicit-governance-paths', ['curation', 'identity_resolution', 'catalog_membership'].every(field => cap.body.changed_fields.includes(field)));
    const state = (await request('/fixture/state')).body;
    check('fixture:private-governance-mode', state.governance_qa_enabled === true && state.variants.length === 4);
    const r = state.variants.find(item => item.identity.size === '265/40R20' && item.identity.brand === 'Fixture Brand');
    const zr = state.variants.find(item => item.identity.size === '265/40ZR20' && item.identity.brand === 'Fixture Brand');
    const condition = [{ kind: 'brand', values: ['Fixture Brand'] }, { kind: 'size', values: ['265/40R20'] }];
    const all = await create('治理R完整条件', condition);
    const facts = await create('治理R只看UTQG', condition, ['facts.utqg_treadwear']);
    const lifecycle = await create('治理R状态', condition, ['state']);
    const identity = await create('治理R身份', condition, ['identity_resolution']);
    const catalog = await create('治理R目录', condition, ['catalog_membership']);
    const target = await create('治理目标ZR不得重定向', [{ kind: 'size', values: ['265/40ZR20'] }], ['identity_resolution']);
    const linked = await create('治理已审车型链', [{ kind: 'vehicle_fitment', values: [{ vehicle_id: state.vehicle_id, axle: 'rear' }] }, ...condition]);
    check('future-only:no-creation-backfill', (await notices()).total === 0);
    const preview = await request('/v1/interests/preview?mode=history&limit=100', 'POST', { conditions: condition, metric_keys: [], changed_fields: [] });
    check('history:read-only-without-backfill', preview.status === 200 && preview.body.matched_count > 0 && (await notices()).total === 0);

    const curate = async (action, value) => {
      const head = await request('/v1/tire-variants/' + r.id + '/fact-review?mode=history&source_id=fixture');
      check('curation:load-current-head', head.status === 200);
      const result = await request('/v1/tire-variants/' + r.id + '/fact-revisions', 'POST', {
        source_id: 'fixture', base_fact_id: head.body.base_fact_id, expected_revision: head.body.revision,
        field: 'utqg_treadwear', action, ...(action === 'manual_override' ? { value } : {}),
        operator: 'Synthetic browser QA', reason: 'Project-authored synthetic governance check',
        evidence: [{ snapshot_id: head.body.provenance.snapshot_id, locator: '/parsed_variants/exact-synthetic-R' }],
      });
      check('curation:production-' + action, result.status === 201, result.status);
      return result.body;
    };
    await curate('manual_override', 450);
    const firstManual = (await notices()).items.find(item => item.interest_id === all.id && item.event.domain === 'tire_curation');
    check('curation:frozen-event-before-after', firstManual && firstManual.event.before && firstManual.event.after
      && firstManual.event.changed_paths.includes('facts.utqg_treadwear'));
    const manualRef = firstManual.event.evidence.find(item => item.kind === 'tire_curation_revision');
    const manualOriginal = await original(manualRef);
    await curate('revoke');
    await curate('clear_override');
    const zero = await curate('manual_override', 0);
    check('curation:real-zero-preserved', zero.effective_facts.utqg_treadwear === 0);
    await curate('clear_override');
    const manualNotices = (await notices()).items.filter(item => item.interest_id === facts.id && item.event.domain === 'tire_curation');
    check('curation:five-effective-field-transitions', manualNotices.length === 5, manualNotices.length);
    const manualAgain = await original(manualRef);
    check('curation:old-record-stable-after-newer-actions', JSON.stringify(manualAgain) === JSON.stringify(manualOriginal));

    check('fitment:production-create', (await request('/fixture/relation?action=create', 'POST')).status === 200);
    check('fitment:production-review', (await request('/fixture/relation?action=review', 'POST')).status === 200);
    const changeLifecycle = async action => {
      const head = await request('/v1/tire-variants/' + r.id + '/lifecycle?mode=history');
      const result = await request('/v1/tire-variants/' + r.id + '/lifecycle-events', 'POST', {
        action, expected_revision: head.body.lifecycle.revision, operator: 'Synthetic browser QA',
        reason: 'Synthetic local tombstone, not an official recall',
        evidence: [{ snapshot_id: r.snapshot_id, locator: '/parsed_variants/exact-synthetic-R' }],
      });
      check('lifecycle:production-' + action, result.status === 201, result.status);
      return result.body;
    };
    await changeLifecycle('revoke');
    const revoked = (await notices()).items.find(item => item.interest_id === all.id && item.event.domain === 'tire_lifecycle');
    check('lifecycle:revoke-notification', revoked?.event.action === 'revoke' && revoked.event.state === 'revoked');
    check('lifecycle:before-reviewed-chain-explains-exit', (await notices()).items.some(item => item.interest_id === linked.id
      && item.event.domain === 'tire_lifecycle' && item.event.action === 'revoke' && item.match.matched_sides.includes('before')));
    const lifecycleRef = revoked.event.evidence.find(item => item.kind === 'tire_lifecycle_event');
    const lifecycleOriginal = await original(lifecycleRef);
    await changeLifecycle('restore');
    const afterRestore = await notices();
    check('lifecycle:state-interest-gets-both-actions', afterRestore.items.filter(item => item.interest_id === lifecycle.id && item.event.domain === 'tire_lifecycle').length === 2);
    check('lifecycle:restore-does-not-reactivate-old-reviewed-chain', !afterRestore.items.some(item => item.interest_id === linked.id
      && item.event.domain === 'tire_lifecycle' && item.event.action === 'restore'));
    check('lifecycle:no-false-UTQG-change', !afterRestore.items.some(item => item.interest_id === facts.id && item.event.domain === 'tire_lifecycle'));
    check('lifecycle:old-original-after-restore', JSON.stringify(await original(lifecycleRef)) === JSON.stringify(lifecycleOriginal));
    check('fitment:explicit-rereview-after-restore', (await request('/fixture/relation?action=review', 'POST')).status === 200);

    const changeIdentity = async action => {
      const target_id = action === 'clear' ? null : zr.id;
      const proposed = await request('/v1/tire-variants/' + r.id + '/identity-preview', 'POST', { mode: 'history', target_id });
      check('identity:production-preview', proposed.status === 200);
      const payload = { mode: 'history', target_id, action, expected_revision: proposed.body.revision,
        expected_fingerprint: proposed.body.fingerprint, operator: 'Synthetic browser QA',
        reason: 'Synthetic explicit local mapping, not SKU equivalence', acknowledged: true,
        acknowledge_unknowns: Boolean(proposed.body.unknown_fields.length),
        field_reasons: Object.fromEntries(proposed.body.differences.map(item => [item.field, 'Project-authored synthetic difference acknowledged'])),
        evidence: [{ snapshot_id: r.snapshot_id, locator: '/parsed_variants/synthetic-both-identities' }] };
      const response = await fetch('/api/v1/tire-variants/' + r.id + '/identity-revisions', { method: 'POST',
        credentials: 'include', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify(payload) });
      const result = await response.json();
      check('identity:production-' + action, response.status === 201, response.status);
      return result;
    };
    await changeIdentity('correct');
    const corrected = (await notices()).items.find(item => item.interest_id === all.id && item.event.domain === 'tire_identity');
    check('identity:source-interest-notified', corrected?.event.action === 'correct' && corrected.event.subject_id === r.id);
    const identityRef = corrected.event.evidence.find(item => item.kind === 'tire_identity_revision');
    const identityOriginal = await original(identityRef);
    await changeIdentity('clear');
    check('identity:two-decisions-without-target-retargeting', (await notices()).items.filter(item => item.interest_id === identity.id
      && item.event.domain === 'tire_identity').length === 2 && !(await notices()).items.some(item => item.interest_id === target.id));
    check('identity:old-mapping-after-clear', JSON.stringify(await original(identityRef)) === JSON.stringify(identityOriginal));
    check('fitment:explicit-rereview-after-identity-clear', (await request('/fixture/relation?action=review', 'POST')).status === 200);

    const catalogTotals = async () => (await notices()).items.filter(item => item.interest_id === catalog.id && item.event.domain === 'tire_catalog');
    const directory = async (present, verify = false) => {
      const result = await request('/fixture/catalog?size=265%2F40R20&present=' + present + '&verify_only=' + verify, 'POST');
      check('catalog:production-observation', result.status === 200 && ['live', 'live_verified_304'].includes(result.body.data_state),
        { status: result.status, data_state: result.body.data_state, reason: result.body.reason });
      return result;
    };
    await directory(false);
    let changes = await catalogTotals();
    check('catalog:removal-even-with-unchanged-facts', changes.length === 1, changes.length);
    const linkedExit = (await notices()).items.find(item => item.interest_id === linked.id && item.event.domain === 'tire_catalog');
    check('catalog:reviewed-chain-receives-before-side-exit', linkedExit?.event.action === 'removed'
      && linkedExit.match.matched_sides.includes('before') && !linkedExit.match.matched_sides.includes('after'));
    const removed = changes[0];
    check('catalog:no-fabricated-fact-or-identity-change', removed.event.changed_paths.length > 0
      && removed.event.changed_paths.every(path => path === 'state' || path.startsWith('catalog_membership')));
    const catalogRef = removed.event.evidence.find(item => item.kind === 'tire_catalog_revision');
    const catalogOriginal = await original(catalogRef);
    await directory(false);
    await directory(false, true);
    check('catalog:same-members-and-304-no-duplicate', (await catalogTotals()).length === 1);
    for (const present of [true, false, true]) await directory(present);
    changes = await catalogTotals();
    check('catalog:reentry-and-repeated-snapshot-pairs-have-new-origins', changes.length === 4
      && new Set(changes.map(item => item.event.id)).size === 4, changes.length);
    check('catalog:reentry-does-not-reactivate-old-reviewed-chain', (await notices()).items.filter(item => item.interest_id === linked.id
      && item.event.domain === 'tire_catalog').length === 1);
    const catalogLife = await request('/v1/tire-variants/' + r.id + '/lifecycle?mode=history');
    check('catalog:absence-did-not-tombstone-SKU', catalogLife.body.lifecycle.state === 'active' && catalogLife.body.lifecycle.revision === 2);
    check('catalog:old-removal-original-still-exact', JSON.stringify(await original(catalogRef)) === JSON.stringify(catalogOriginal));
    check('catalog:UTQG-only-interest-not-spammed', !(await notices()).items.some(item => item.interest_id === facts.id && item.event.domain === 'tire_catalog'));
    const beforeFacts = (await notices()).items.filter(item => item.interest_id === linked.id && item.event.domain === 'tire').length;
    const freshFact = await request('/fixture/tire?value=333&size=265%2F40R20', 'POST');
    check('catalog:later-real-UTQG-observation', freshFact.status === 200 && freshFact.body.data_state === 'live');
    check('catalog:reentry-does-not-authorize-old-reviewed-chain-for-later-facts',
      (await notices()).items.filter(item => item.interest_id === linked.id && item.event.domain === 'tire').length === beforeFacts);
    check('catalog:ordinary-exact-fact-interest-still-notified', (await notices()).items.some(item => item.interest_id === facts.id
      && item.event.domain === 'tire' && item.event.changed_paths.includes('facts.utqg_treadwear')));
    check('original:manual-stable-after-source-refresh', JSON.stringify(await original(manualRef)) === JSON.stringify(manualOriginal));
    check('original:lifecycle-stable-after-source-refresh', JSON.stringify(await original(lifecycleRef)) === JSON.stringify(lifecycleOriginal));
    check('original:identity-stable-after-source-refresh', JSON.stringify(await original(identityRef)) === JSON.stringify(identityOriginal));
    check('original:catalog-stable-after-source-refresh', JSON.stringify(await original(catalogRef)) === JSON.stringify(catalogOriginal));
    const missing = await request('/v1/interest-evidence/tire_curation_revision/missing-synthetic-record?mode=history');
    check('original:missing-does-not-return-latest', missing.status === 404);
    const wrongKind = await request('/v1/interest-evidence/tire_identity_revision/' + manualRef.record_id + '?mode=history');
    check('original:wrong-kind-does-not-return-another-domain', wrongKind.status === 404);
    const endState = (await request('/fixture/state')).body;
    check('fixture:no-normal-db-provider-network-or-parser-child', endState.normal_database_used === false
      && endState.provider_calls === 0 && endState.external_network_attempts === 0 && endState.parser_children === 0);
    window.__interestGovernanceQA = { records, done: true, ids: { all: all.id, facts: facts.id, lifecycle: lifecycle.id,
      identity: identity.id, catalog: catalog.id, linked: linked.id, target: target.id }, references: { manualRef, lifecycleRef, identityRef, catalogRef },
      totals: { notifications: (await notices()).total }, fixture_counters: {
        normal_database_used: endState.normal_database_used, provider_calls: endState.provider_calls,
        external_network_attempts: endState.external_network_attempts, parser_children: endState.parser_children } };
  } catch (error) {
    window.__interestGovernanceQA.error = String(error);
  }
  return window.__interestGovernanceQA;
})();
