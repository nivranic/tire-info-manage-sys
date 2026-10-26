/* Run as a classic script in the private interest browser page after UI reconnaissance.
 * Exercises the real isolated API. It contains no credentials or normal-store paths.
 * UI interactions, ownership races and responsive checks are recorded separately.
 */
(async () => {
  const records = [];
  const check = (name, ok, detail = null) => {
    records.push({ name, passed: Boolean(ok), detail });
    if (!ok) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const request = async (path, method = 'GET', body) => {
    const response = await fetch('/api' + path, {
      method, credentials: 'include', cache: 'no-store',
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    });
    return { status: response.status, body: await response.json() };
  };
  const settings = (name, conditions, extras = {}) => ({ name, enabled: true, conditions,
    metric_keys: [], changed_fields: [], ...extras });
  const create = async (name, conditions, extras = {}) => {
    const value = settings(name, conditions, extras);
    const result = await request('/v1/interests', 'POST', value);
    check('create:' + name, result.status === 201 && result.body.scope === 'actor', result.status);
    return { ...result.body, original: value };
  };
  const notices = () => request('/v1/interest-notifications?mode=history&limit=100');
  window.__interestApiQA = { records, done: false };
  try {
    const cap = await request('/v1/interests/capabilities?mode=history');
    check('capabilities:seven-non-sku-and-original-four-domains', cap.status === 200 && cap.body.kinds.length === 7
      && ['tire', 'test_event', 'vehicle', 'fitment'].every(domain => cap.body.domains.some(item => item.domain === domain && item.supported))
      && cap.body.network_refresh === false);
    check('capabilities:precise-fact-selectors', cap.body.changed_fields.includes('facts.utqg_treadwear')
      && cap.body.changed_fields.includes('facts.tread_depth'));
    const initial = await notices();
    check('notifications:empty-before-follow', initial.body.total === 0, initial.body.total);
    const rules = [];
    rules.push(await create('API品牌', [{ kind: 'brand', values: ['Fixture Brand'] }]));
    rules.push(await create('API型号', [{ kind: 'model', values: [{ brand: 'Fixture Brand', model: 'Fixture Tire' }] }]));
    rules.push(await create('API尺寸ZR', [{ kind: 'size', values: ['265/40ZR20'] }]));
    rules.push(await create('APIOE', [{ kind: 'oe', values: ['LUC'] }]));
    rules.push(await create('API技术', [{ kind: 'technology', values: ['Acoustic'] }]));
    rules.push(await create('API机构', [{ kind: 'test_organization', values: ['Fixture Test Lab'] }], { metric_keys: ['wet'] }));
    rules.push(await create('API车型', [{ kind: 'vehicle_fitment', values: [{ vehicle_id: 'synthetic-vehicle-gen1' }] }]));
    const combined = await create('API组合R', [{ kind: 'brand', values: ['Fixture Brand'] },
      { kind: 'size', values: ['265/40R20'] }, { kind: 'technology', values: ['Acoustic'] }],
      { changed_fields: ['facts.utqg_treadwear'] });
    const near = await create('API近似不得命中', [{ kind: 'model', values: [{ brand: 'Fixture Brand', model: 'Fixture Tir' }] }]);
    const cross = await create('API同尺寸不得推断适配', [{ kind: 'size', values: ['265/40ZR20'] },
      { kind: 'vehicle_fitment', values: [{ vehicle_id: 'synthetic-vehicle-gen1' }] }]);
    const depth = await create('API只关胎纹深度', [{ kind: 'brand', values: ['Fixture Brand'] }],
      { changed_fields: ['facts.tread_depth'] });
    check('notifications:no-history-backfill', (await notices()).body.total === 0);
    const history = await request('/v1/interests/preview?mode=history&offset=0&limit=100', 'POST', {
      conditions: rules[0].conditions, metric_keys: [], changed_fields: [],
    });
    check('preview:read-only-local-history', history.status === 200 && history.body.data_state === 'local_snapshot'
      && history.body.matched_count > 0, { status: history.status, count: history.body.matched_count });
    check('preview:did-not-notify', (await notices()).body.total === 0);
    const tire = await request('/fixture/tire?value=420&size=265%2F40ZR20', 'POST');
    check('producer:real-tire-service', tire.status === 200 && tire.body.data_state === 'live', tire.status);
    const after = (await notices()).body;
    check('notifications:future-only-exact-zr', after.items.some(x => x.interest_id === rules[2].id)
      && !after.items.some(x => [combined.id, near.id, cross.id, depth.id].includes(x.interest_id)),
      { total: after.total, names: after.items.map(x => x.interest_name) });
    check('notifications:immutable-explanation-evidence', after.items.every(x => x.match.state === 'matched'
      && x.event.event_hash && x.event.evidence.length > 0 && x.interest_revision === 1));
    check('notifications:frozen-criteria-present', after.items.every(x => x.match.criteria
      && x.match.criteria.conditions.length > 0 && Array.isArray(x.match.criteria.changed_fields)
      && Array.isArray(x.match.criteria.metric_keys)));
    await request('/fixture/tire?value=420&size=265%2F40ZR20', 'POST');
    check('notifications:same-fact-replay-deduplicated', (await notices()).body.total === after.total);
    const read = after.items.find(x => x.interest_id === rules[2].id);
    const marked = await request('/v1/interest-notifications/' + read.id + '/read', 'PUT', { read: true });
    check('notifications:mark-read', marked.status === 200 && marked.body.read_at !== null);
    const unread = await request('/v1/interest-notifications?mode=history&unread=true&limit=100');
    check('notifications:unread-filter', !unread.body.items.some(x => x.id === read.id));
    const revised = await request('/v1/interests/' + combined.id, 'PUT', {
      ...combined.original, name: 'API组合R修订', expected_revision: 1,
    });
    check('interest:append-revision', revised.status === 200 && revised.body.revision === 2);
    const stale = await request('/v1/interests/' + combined.id, 'PUT', {
      ...combined.original, name: '不应覆盖', expected_revision: 1,
    });
    check('interest:stale-conflict', stale.status === 409 && stale.body.detail.code === 'interest_revision_conflict');
    const nextTire = await request('/fixture/tire?value=421&size=265%2F40R20', 'POST');
    check('producer:second-size', nextTire.status === 200);
    const all = (await notices()).body;
    check('notifications:revised-combination-and-fact-path', all.items.some(x => x.interest_id === combined.id
      && x.interest_revision === 2 && x.event.changed_paths.includes('facts.utqg_treadwear')));
    const archive = await request('/v1/interests/' + rules[2].id + '/state', 'POST', { expected_revision: 1, action: 'archive' });
    check('interest:archive-disables', archive.status === 200 && archive.body.archived && !archive.body.enabled);
    await request('/fixture/tire?value=422&size=265%2F40ZR20', 'POST');
    check('interest:archived-no-new-delivery', (await notices()).body.items.filter(x => x.interest_id === rules[2].id).length === 1);
    const restored = await request('/v1/interests/' + rules[2].id + '/state', 'POST', { expected_revision: 2, action: 'restore' });
    check('interest:restore-keeps-disabled', restored.status === 200 && !restored.body.archived && !restored.body.enabled);
    const crossPreview = await request('/v1/interests/preview?mode=history&limit=100', 'POST', {
      conditions: cross.conditions, metric_keys: [], changed_fields: [],
    });
    check('preview:cross-domain-binding-unavailable', crossPreview.status === 200 && crossPreview.body.indeterminate_count > 0
      && !crossPreview.body.items.some(x => x.match.state === 'matched'));
    const testBefore = (await notices()).body.items.filter(x => x.interest_id === rules[5].id).length;
    for (const action of ['revise', 'revoke', 'restore']) {
      const produced = await request('/fixture/test?action=' + action, 'POST');
      check('producer:test-' + action, produced.status === 200);
    }
    const testAfter = (await notices()).body.items.filter(x => x.interest_id === rules[5].id);
    check('notifications:test-state-revisions-not-payload-deduped', testAfter.length === testBefore + 3
      && new Set(testAfter.map(x => x.event.event_hash)).size === testAfter.length,
      { before: testBefore, after: testAfter.length });
    const linked = await create('API已审关系后的参数变化', [
      { kind: 'vehicle_fitment', values: [{ vehicle_id: 'synthetic-vehicle-gen1', axle: 'rear' }] },
      { kind: 'size', values: ['265/40R20'] }, { kind: 'technology', values: ['Acoustic'] },
    ], { changed_fields: ['facts.utqg_treadwear'] });
    const pending = await request('/fixture/relation?action=create', 'POST');
    check('producer:real-pending-fitment-relation', pending.status === 200, pending.status);
    const reviewed = await request('/fixture/relation?action=review', 'POST');
    check('producer:real-reviewed-fitment-relation', reviewed.status === 200, reviewed.status);
    check('notifications:field-selector-excludes-relation-only-edit', !(await notices()).body.items.some(x => x.interest_id === linked.id));
    await request('/fixture/tire?value=425&size=265%2F40R20', 'POST');
    const linkedNotices = (await notices()).body.items.filter(x => x.interest_id === linked.id);
    check('notifications:reviewed-chain-receives-future-tire-facts', linkedNotices.length === 1
      && linkedNotices[0].event.domain === 'tire'
      && linkedNotices[0].event.evidence.some(x => x.kind === 'fitment_relation_revision'), linkedNotices.length);
    const withdrawn = await request('/fixture/relation?action=revoke', 'POST');
    check('producer:real-fitment-revocation', withdrawn.status === 200, withdrawn.status);
    await request('/fixture/tire?value=426&size=265%2F40R20', 'POST');
    check('notifications:revoked-chain-does-not-authorize-later-facts',
      (await notices()).body.items.filter(x => x.interest_id === linked.id).length === 1);
    const state = await request('/fixture/state');
    check('fixture:no-normal-db-provider-network-children', state.body.normal_database_used === false
      && state.body.provider_calls === 0 && state.body.external_network_attempts === 0 && state.body.parser_children === 0);
    window.__interestApiQA = { records, done: true,
      ids: { rules: rules.map(x => x.id), combined: combined.id, near: near.id, cross: cross.id, depth: depth.id,
        linked: linked.id, notification: read.id }, totals: { notifications: (await notices()).body.total } };
  } catch (error) {
    window.__interestApiQA.error = String(error);
  }
  return window.__interestApiQA;
})();
