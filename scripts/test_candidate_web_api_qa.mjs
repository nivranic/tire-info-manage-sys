/* Real private HTTP through the browser origin, synthetic evidence only. */
(async () => {
  const records = [];
  const output = { schema: 'r75-private-http-qa@1', records, done: false, real_http: true,
    synthetic_only: true, real_source_golden: false, provider_calls: 0 };
  window.__candidateApiQA = output;
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const req = async (path, method = 'GET', body) => {
    const response = await fetch('/api' + path, { method, credentials: 'include', cache: 'no-store',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined });
    return { status: response.status, body: await response.json(), cache: response.headers.get('cache-control') };
  };
  const state = async () => (await req('/fixture/state')).body;
  const credentials = { first: { username: 'r75_ui_' + crypto.randomUUID().slice(0, 8), password: crypto.randomUUID() },
    second: { username: 'r75_other_' + crypto.randomUUID().slice(0, 8), password: crypto.randomUUID() } };
  window.__candidateCredentials = credentials; // Runtime only, never returned or persisted.
  const logout = () => req('/v1/auth/logout', 'POST', {});
  const login = actor => req('/v1/auth/login', 'POST', credentials[actor]);
  try {
    const fixture = await state();
    check('explicit-guid-private-fixture', fixture.synthetic_only && !fixture.normal_database_used && fixture.provider_calls === 0);
    const path = '/v1/test-events/' + encodeURIComponent(fixture.event_id) + '/candidate-interpretation?mode=history';
    await logout();
    const anonymous = await req(path, 'POST', fixture.request);
    check('anonymous-cannot-read-actor-interpretation', [401, 403].includes(anonymous.status), anonymous.status);
    check('register-transient-browser-user', (await req('/v1/auth/register', 'POST', credentials.first)).status === 200);
    const currentPreference = await req('/v1/driving-preferences');
    const saved = await req('/v1/driving-preferences', 'PUT', { expected_revision: currentPreference.body.revision, weights: fixture.weights });
    check('actor-saved-preferences', saved.status === 200 && saved.body.weights !== null);
    const payload = { ...fixture.request, expected_preference_revision: saved.body.revision,
      expected_preference_fingerprint: saved.body.fingerprint };
    const before = await state();
    const positive = await req(path, 'POST', payload);
    check('two-reviewed-skus-positive-http', positive.status === 200, { status: positive.status, code: positive.body?.detail?.code });
    const result = positive.body;
    check('success-no-store', positive.cache?.includes('no-store'));
    check('same-event-local-boundary', result.schema === 'test-candidate-interpretation@1'
      && result.comparison_scope === 'same_event_only' && result.status === 'conditional_observations'
      && result.eligible_count === 2 && result.requested_count === 2);
    check('no-performance-score-or-new-source-ranking', result.performance_score === null && result.ranking === 'source_reported_only'
      && result.official_oe.state === 'not_established');
    check('provider-export-unverified-boundaries', result.boundary.provider_use === false && result.boundary.export === false
      && result.boundary.origin_verification === 'unverified');
    check('all-original-identities-still-participant-only', result.source_evidence.participants.every(row => row.identity_status === 'participant_only'));
    check('exact-original-decimals-and-negative-zero', ['38.00', '-0', '0'].every(value => result.source_evidence.measurements.some(row => row.raw_value === value)));
    check('bridge-refs-separate-from-source', result.items.every((row, index) => row.variant_id === payload.candidates[index].variant_id
      && row.link.revision_id === payload.candidates[index].expected_link_revision_id && row.participant_key === row.link.selection.participant_key));
    check('compact-bridge-evidence-and-locators', result.items.every(row => row.link.material_evidence.length > 0
      && row.link.material_evidence.every(material => material.event_locator.page > 0 && material.participant_locator.quote)
      && !('frozen_evidence' in row.link) && !('allowed_actions' in row.link)));
    const after = await state();
    check('interpretation-does-not-append-business-or-audit', JSON.stringify(before.counts) === JSON.stringify(after.counts), { before: before.counts, after: after.counts });
    const again = await req(path, 'POST', payload);
    check('stable-read-fingerprint', again.status === 200 && again.body.binding.interpretation_fingerprint === result.binding.interpretation_fingerprint);
    const reversedMappings = await req(path, 'POST', { ...payload, metric_dimensions: [...payload.metric_dimensions].reverse() });
    check('mapping-order-canonical', reversedMappings.status === 200 && reversedMappings.body.binding.interpretation_fingerprint === result.binding.interpretation_fingerprint);
    const allNull = await req(path, 'POST', { ...payload, metric_dimensions: payload.metric_dimensions.map(row => ({ ...row, dimension: null })) });
    check('no-default-mapping-or-implicit-comparison', allNull.status === 200 && allNull.body.status === 'insufficient_evidence'
      && allNull.body.personal_interpretation.metrics.every(row => row.observation_comparison === null));
    const dry = result.personal_interpretation.metrics.find(row => row.metric_key === 'dry');
    const noise = result.personal_interpretation.metrics.find(row => row.metric_key === 'noise');
    check('decimal-tie-keeps-both-and-missing-is-not-zero', dry.observation_comparison.favorable_participant_ids.length === 2
      && noise.missing_participant_ids.length === 1 && noise.observation_comparison === null);
    for (const [name, mutation, status] of [
      ['strict-extra-field', { ...payload, weights: fixture.weights }, 422],
      ['strict-boolean-revision', { ...payload, expected_event_revision: true }, 422],
      ['stale-event-revision-id', { ...payload, expected_event_revision_id: 'synthetic-old' }, 409],
      ['stale-link-revision-id', { ...payload, candidates: payload.candidates.map((row, index) => index ? row : { ...row, expected_link_revision_id: 'synthetic-old' }) }, 409],
      ['duplicate-variants', { ...payload, candidates: [payload.candidates[0], payload.candidates[0]] }, 422],
      ['caller-participant-injection', { ...payload, participant_ids: ['a', 'b'] }, 422],
    ]) {
      const denied = await req(path, 'POST', mutation);
      check(name, denied.status === status && denied.cache?.includes('no-store'), denied.status);
    }
    await logout();
    check('second-runtime-actor-created', (await req('/v1/auth/register', 'POST', credentials.second)).status === 200);
    const other = await req(path, 'POST', payload);
    // Existing auth deliberately rebinds the same local cookie's data to the next
    // account (ADR-2026-057). Fresh-session isolation is an independent API test;
    // here verify that the composite signature still changes with current actor.
    check('shared-session-rebind-uses-current-actor-signature', other.status === 200
      && other.body.binding.interpretation_fingerprint !== result.binding.interpretation_fingerprint, other.status);
    output.account_boundary = 'existing same-cookie session aggregation retained; actor-bound signatures change; fresh-session isolation covered separately';
    await logout(); check('original-actor-login-restored', (await login('first')).status === 200);
    const changed = await req('/fixture/link-state', 'POST', { index: 1, action: 'revoke' });
    check('fixture-explicit-current-bridge-revoked', changed.status === 200);
    check('old-reviewed-link-not-reusable', (await req(path, 'POST', payload)).status === 409);
    const current = await state();
    const excluded = await req(path, 'POST', { ...current.request, expected_preference_revision: saved.body.revision,
      expected_preference_fingerprint: saved.body.fingerprint });
    check('current-revoked-bridge-explicitly-excluded', excluded.status === 200 && excluded.body.excluded.length === 1
      && excluded.body.eligible_count === 1 && excluded.body.status === 'insufficient_evidence');
    check('any-excluded-stops-whole-personal-interpretation', excluded.body.personal_interpretation === null
      && excluded.body.source_evidence.participants.length === 2);
    check('fixture-restore-pending', (await req('/fixture/link-state', 'POST', { index: 1, action: 'restore' })).status === 200);
    check('fixture-review-current-bridge', (await req('/fixture/link-state', 'POST', { index: 1, action: 'review' })).status === 200);
    const finalState = await state();
    check('private-guards-zero', Object.values(finalState.guard_counts).every(value => value === 0), finalState.guard_counts);
    output.binding = result.binding;
    output.passed = records.length; output.done = true;
    window.dispatchEvent(new Event('tire-session-revalidate'));
  } catch (error) { output.error = String(error); }
  return output;
})();
