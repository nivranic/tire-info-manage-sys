/* Production HTTP acceptance on a private synthetic fixture. Secrets stay in memory. */
(async () => {
  const records = [];
  const check = (name, ok, detail = null) => {
    records.push({ name, passed: Boolean(ok), detail });
    if (!ok) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const request = async (path, method = 'GET', body) => {
    const response = await fetch('/api' + path, { method, credentials: 'include', cache: 'no-store',
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
    return { status: response.status, cache: response.headers.get('cache-control'), body: await response.json() };
  };
  const feed = (body = {}) => request('/v1/personal-feed/preview?mode=history', 'POST', { domain: null, limit: 20, cursor: null, ...body });
  const create = async (name, conditions) => {
    const response = await request('/v1/interests', 'POST', { name, enabled: true, conditions, metric_keys: [], changed_fields: [] });
    check('interest:create:' + name, response.status === 201, response.status);
    return response.body;
  };
  window.__personalizationApiQA = { records, done: false };
  try {
    const password = Array.from(crypto.getRandomValues(new Uint8Array(20)), value => value.toString(16).padStart(2, '0')).join('');
    const registration = await request('/v1/auth/register', 'POST', { username: 'personalization-qa-' + Date.now(), password });
    check('auth:private-admin', registration.status === 200, registration.status);
    const empty = await feed();
    check('feed:actor-empty-no-scan', empty.status === 200 && empty.body.items.length === 0
      && empty.body.active_interest_count === 0 && empty.body.scanned_count === 0 && empty.body.next_cursor === null);
    check('feed:no-store', empty.cache?.includes('no-store'));
    const state = (await request('/fixture/state')).body;
    check('fixture:private-typed', state.synthetic_only && !state.normal_database_used && state.applicability_qa_enabled);
    const brand = [{ kind: 'brand', values: ['Fixture Brand'] }];
    const first = await create('我的历史品牌', brand);
    const second = await create('<img src=x onerror=alert(1)> 第二关注', brand);
    const noticesBefore = (await request('/v1/interest-notifications?mode=history&limit=100')).body.total;
    check('feed:no-notification-backfill-on-interest-save', noticesBefore === 0);
    const page = await feed({ domain: 'tire', limit: 1 });
    check('feed:scan-one-page', page.status === 200 && page.body.scanned_count === 1 && page.body.has_more && Boolean(page.body.next_cursor));
    const seen = new Set();
    const all = [];
    let current = page;
    for (let index = 0; index < 30; index++) {
      check('feed:bounded-page-' + index, current.status === 200 && current.body.scanned_count <= 1);
      for (const item of current.body.items) {
        check('feed:no-duplicate-event-' + index, !seen.has(item.event.id));
        seen.add(item.event.id);
        all.push(item);
      }
      if (!current.body.next_cursor) break;
      current = await feed({ domain: 'tire', limit: 1, cursor: current.body.next_cursor });
    }
    check('feed:history-before-subscription', all.length === 2 && all.every(item => Date.parse(item.event.observed_at) < Date.parse(first.created_at)), all.length);
    check('feed:dedup-with-independent-reasons', all.every(item => item.state === 'matched'
      && [first.id, second.id].every(id => item.matches.some(match => match.interest_id === id && match.match.state === 'matched'))));
    check('feed:frozen-evidence-preserved', all.every(item => item.event.event_hash && item.event.evidence.length > 0));
    const badCursor = page.body.next_cursor.slice(0, -3) + 'AAA';
    const bad = await feed({ domain: 'tire', limit: 1, cursor: badCursor });
    check('feed:tamper-refused', bad.status === 400 && bad.body.detail.code === 'personal_feed_cursor_invalid', bad.status);
    const extra = await request('/v1/personal-feed/preview?mode=history', 'POST', { actor: 'other', limit: 1 });
    check('feed:actor-override-refused', extra.status === 422);
    const edit = await request('/v1/interests/' + first.id, 'PUT', {
      name: '我的历史品牌（新修订）', enabled: true, conditions: brand, metric_keys: [], changed_fields: [], expected_revision: first.revision });
    check('interest:edit-head', edit.status === 200);
    const stale = await feed({ domain: 'tire', limit: 1, cursor: page.body.next_cursor });
    check('feed:old-interest-binding-refused', stale.status === 409 && stale.body.detail.code === 'personal_feed_binding_changed', stale.status);
    const beforeAppend = await feed({ domain: 'tire', limit: 1 });
    const changed = await request('/fixture/applicability/source?value=321', 'POST');
    check('source:production-private-update', changed.status === 200 && changed.body.data_state === 'live');
    const corpusStale = await feed({ domain: 'tire', limit: 1, cursor: beforeAppend.body.next_cursor });
    check('feed:corpus-append-invalidates', corpusStale.status === 409 && corpusStale.body.detail.code === 'personal_feed_binding_changed');
    const prefs = (await request('/v1/driving-preferences?mode=history')).body;
    const saved = await request('/v1/driving-preferences', 'PUT', { expected_revision: prefs.revision,
      weights: { dry: 10, wet: 30, quiet: 25, comfort: 15, wear: 10, energy: 10, appearance: 0 } });
    check('preference:private-save', saved.status === 200);
    const selection = { vehicle_id: state.vehicle_id, vehicle_snapshot_id: state.vehicle_snapshot_id,
      trim_id: 'synthetic-trim', wheel_option_id: 'synthetic-option', axle: 'rear' };
    const candidate = (overrides = {}) => request('/v1/fitment-candidates/preview?mode=history', 'POST', {
      selection, expected_preference_revision: saved.body.revision, expected_preference_fingerprint: saved.body.fingerprint, ...overrides });
    const noRelation = await candidate();
    check('candidate:true-empty-without-relation', noRelation.status === 200 && noRelation.body.items.length === 0);
    const created = await request('/fixture/relation?action=create', 'POST');
    check('relation:production-candidate', created.status === 200 && created.body.relation.effective_state === 'pending_review');
    const pending = await candidate();
    check('candidate:unreviewed-not-eligible', pending.status === 200 && pending.body.items.length === 0
      && pending.body.excluded_relations.length === 1);
    const reviewed = await request('/fixture/relation?action=review', 'POST');
    check('relation:production-review', reviewed.status === 200 && reviewed.body.relation.effective_state === 'reviewed');
    const eligible = await candidate();
    check('candidate:one-exact-reviewed-SKU', eligible.status === 200 && eligible.body.items.length === 1
      && eligible.body.items[0].variant_id === reviewed.body.relation.variant_id, eligible.status);
    check('candidate:no-fabricated-performance-ranking', eligible.body.items.every(item =>
      item.performance_score === null && item.ranking === 'not_computed' && item.official_oe.state === 'not_established'));
    check('candidate:all-seven-research-dimensions', eligible.body.research_focus.length === 7);
    const candidateItem = eligible.body.items[0];
    check('candidate:precise-relation-evidence', candidateItem.relations.length === 1 && candidateItem.relations[0].revision_id
      && candidateItem.relations[0].binding_hash && candidateItem.relations[0].evidence.length > 0);
    const opposite = await candidate({ selection: { ...selection, axle: 'front' } });
    check('candidate:rear-never-used-for-front', opposite.status === 200 && opposite.body.items.length === 0);
    const stalePreference = await candidate({ expected_preference_fingerprint: '0'.repeat(64) });
    check('candidate:preference-binding-refused', stalePreference.status === 409);
    const snapshot = await request('/v1/fitment-relations/vehicle-snapshots/' + state.vehicle_snapshot_id + '?mode=history');
    check('candidate:exact-vehicle-evidence-reopens', snapshot.status === 200 && snapshot.body.id === selection.vehicle_snapshot_id);
    const relationRevision = await request('/v1/fitment-relations/' + reviewed.body.relation.id + '/revisions/' + reviewed.body.relation.revision + '?mode=history');
    check('candidate:exact-relation-reopens', relationRevision.status === 200 && relationRevision.body.revision === reviewed.body.relation.revision);
    const noticesAfter = (await request('/v1/interest-notifications?mode=history&limit=100')).body.total;
    const stable = await feed();
    const stableAgain = await feed();
    check('feed:deterministic-repeat', stable.status === 200 && stableAgain.status === 200
      && JSON.stringify(stable.body.items) === JSON.stringify(stableAgain.body.items));
    check('feed:reads-do-not-deliver-notices', (await request('/v1/interest-notifications?mode=history&limit=100')).body.total === noticesAfter);
    const guard = (await request('/fixture/state')).body;
    check('fixture:all-isolation-guards-zero', ['external_network_attempts', 'parser_children', 'provider_calls', 'normal_database_attempts'].every(key => guard[key] === 0));
    window.__personalizationRefs = { selection, candidate_variant_id: candidateItem.variant_id,
      relation_id: reviewed.body.relation.id, relation_revision: reviewed.body.relation.revision,
      test_event_id: state.test_event_id, second_interest_id: second.id };
    window.__personalizationApiQA = { records, done: true, passed: records.filter(row => row.passed).length,
      reference_scope: 'public synthetic IDs only', normal_database_used: false, real_provider_used: false };
  } catch (error) { window.__personalizationApiQA.error = String(error); }
  return window.__personalizationApiQA;
})();
