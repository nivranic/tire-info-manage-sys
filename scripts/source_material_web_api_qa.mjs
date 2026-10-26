/* Real private production HTTP; source transport uses synthetic session responses. */
(async () => {
  const records = [];
  const output = { schema: 'r72-private-api-qa@1', records, outcome: 'running', done: false,
    real_http: true, synthetic_upstream_session: true, public_source_dns_tls_exercised: false };
  window.__materialApiQA = output;
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const call = async (path, method = 'GET', body) => {
    const response = await fetch('/api' + path, { method, credentials: 'include',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: response.status, body: await response.json() };
  };
  const prefix = '/v1/source-materials';
  const state = async () => (await call('/fixture/state')).body;
  const countFetch = async () => (await state()).upstream_requests.length;
  const credentials = { author: { username: 'r72_author_' + crypto.randomUUID().slice(0, 8), password: crypto.randomUUID() },
    viewer: { username: 'r72_viewer_' + crypto.randomUUID().slice(0, 8), password: crypto.randomUUID() } };
  window.__materialCredentials = credentials; // Runtime memory only; never return or persist credentials.
  const logout = () => call('/v1/auth/logout', 'POST', {});
  const login = who => call('/v1/auth/login', 'POST', credentials[who]);
  const capture = payload => call(prefix + '/captures', 'POST', payload);
  const lookup = key => call(prefix + '/requests/' + encodeURIComponent(key) + '?mode=history');
  try {
    const baseline = await state();
    window.__materialFixtureHash = baseline.material_sha256;
    check('private-synthetic-runtime', baseline.synthetic_only && !baseline.normal_database_used
      && !baseline.public_source_dns_tls_exercised && baseline.production_source_transport_executed);
    const catalogue = await call(prefix + '/policies');
    check('fixed-policy-catalogue', catalogue.status === 200 && catalogue.body.items.length === 3);
    const policy = catalogue.body.items.find(row => row.policy_id === 'qa-source');
    check('explicit-source-license-boundary', policy.rights.store_original && policy.rights.workspace_reopen
      && !policy.rights.provider_use && !policy.rights.export && policy.published_at === null);
    check('reference-and-download-distinct', policy.source_reference_url === 'https://fixture.invalid/test'
      && policy.download_url === 'https://source-fixture.invalid/begin');
    check('anonymous-preview-guard-before-body', (await call(prefix + '/preview', 'POST', {})).status === 403);
    check('anonymous-capture-guard-before-body', (await capture({})).status === 403);
    const author = await call('/v1/auth/register', 'POST', credentials.author);
    check('real-admin-registration', author.status === 200 && author.body.user.is_admin);
    await logout();
    const viewer = await call('/v1/auth/register', 'POST', credentials.viewer);
    check('real-viewer-registration', viewer.status === 200 && !viewer.body.user.is_admin);
    check('non-admin-capture-rejected', (await capture({})).status === 403);
    await logout();
    check('real-admin-login', (await login('author')).status === 200);
    const selected = { policy_id: policy.policy_id, expected_policy_fingerprint: policy.policy_fingerprint };
    const preview = await call(prefix + '/preview', 'POST', selected);
    check('preview-fixed-policy', preview.status === 200 && preview.body.can_capture
      && preview.body.policy.policy_fingerprint === policy.policy_fingerprint);
    check('preview-no-fetch-or-document', await countFetch() === 0
      && (await state()).counts.documents === baseline.counts.documents);
    check('stale-policy-rejected', (await call(prefix + '/preview', 'POST', {
      ...selected, expected_policy_fingerprint: '0'.repeat(64) })).status === 409);
    const payload = { ...selected, idempotency_key: crypto.randomUUID(), operator: 'Synthetic HTTP QA', rights_confirmed: true };
    check('cannot-supply-arbitrary-url', (await capture({ ...payload, download_url: 'https://unexpected.invalid/a.pdf' })).status === 422);
    check('rights-confirmation-required', (await capture({ ...payload, rights_confirmed: false })).status === 422);
    check('rejected-requests-no-upstream', await countFetch() === 0);
    const saved = await capture(payload);
    check('source-capture-succeeded', saved.status < 300 && saved.body.state === 'succeeded',
      { status: saved.status, state: saved.body.state, failure: saved.body.failure_code });
    const document = saved.body.document;
    const receipt = saved.body.receipt;
    output.document_id = document.id;
    output.request_key = payload.idempotency_key;
    check('identity-byte-hash-and-size', document.raw_hash === baseline.material_sha256
      && document.byte_count === baseline.material_byte_count
      && receipt.raw_hash === document.raw_hash && receipt.byte_count === document.byte_count);
    check('observed-redirect-chain', receipt.initial_url === policy.download_url
      && receipt.final_url === 'https://source-fixture.invalid/material.pdf'
      && receipt.redirects.length === 1 && receipt.redirects[0].status === 302);
    check('robots-receipt-retained', receipt.robots.length > 0
      && receipt.robots.every(row => row.allowed && row.status === 200 && /^[a-f0-9]{64}$/.test(row.raw_hash)));
    check('transport-and-content-semantics', receipt.content_encoding === 'identity'
      && receipt.transport_verification === 'https_transport_observed'
      && receipt.content_authenticity === 'unverified'
      && receipt.source_reference_relation === 'operator_configured');
    check('document-ref-is-declared-page', document.source_url === policy.source_reference_url
      && document.source_url !== receipt.final_url && !document.accepted_as_facts);
    const byDocument = await call(prefix + '/documents/' + document.id + '?mode=history');
    check('document-provenance-reopens', byDocument.status === 200
      && byDocument.body.receipt.fingerprint === receipt.fingerprint);
    const rawResponse = await fetch('/api/v1/documents/' + document.id + '/content?mode=history', { credentials: 'include' });
    const bytes = await rawResponse.arrayBuffer();
    const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('');
    check('full-original-download-verified', rawResponse.status === 200 && hash === document.raw_hash
      && bytes.byteLength === document.byte_count && rawResponse.headers.get('x-evidence-sha256') === document.raw_hash);
    const fetches = await countFetch();
    const replay = await capture(payload);
    check('same-uuid-no-redownload', replay.status < 300 && replay.body.replayed
      && replay.body.document.id === document.id && await countFetch() === fetches);
    check('same-uuid-different-payload-conflict', (await capture({ ...payload, operator: 'Different payload' })).status === 409);
    check('saved-operation-found', (await lookup(payload.idempotency_key)).body.receipt.fingerprint === receipt.fingerprint);
    check('unknown-request-not-invented', (await lookup(crypto.randomUUID())).status === 404);
    await logout();
    await login('viewer');
    check('other-account-cannot-read-private-request', (await lookup(payload.idempotency_key)).status === 404);
    const otherList = await call(prefix + '/requests?mode=history&offset=0');
    check('other-account-history-isolated', otherList.status === 200 && otherList.body.items.length === 0);
    check('source-document-shared-workspace', (await call(prefix + '/documents/' + document.id + '?mode=history')).status === 200);
    await logout();
    await login('author');
    check('same-account-history-reopened', (await lookup(payload.idempotency_key)).body.document.id === document.id);

    const metadata = { title: 'R72 same bytes, manual upload; no source provenance',
      source_url: policy.source_reference_url, operator: 'Synthetic HTTP QA', rights_basis: policy.rights.basis };
    const metadataHeader = btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(metadata))));
    const manualResponse = await fetch('/api/v1/documents', { method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/pdf', 'X-Evidence-Metadata': metadataHeader }, body: bytes });
    const manual = await manualResponse.json();
    check('same-byte-manual-upload-separate-document', manualResponse.status === 201
      && manual.id !== document.id && manual.raw_hash === document.raw_hash);
    check('same-byte-upload-does-not-gain-provenance', (await call(prefix + '/documents/' + manual.id + '?mode=history')).status === 404);

    const beforeFailure = await state();
    const failedPolicy = catalogue.body.items.find(row => row.policy_id === 'qa-failure');
    const failedPayload = { ...payload, policy_id: failedPolicy.policy_id,
      expected_policy_fingerprint: failedPolicy.policy_fingerprint, idempotency_key: crypto.randomUUID() };
    const failed = await capture(failedPayload);
    check('upstream-error-durable-failure', failed.status < 300 && failed.body.state === 'failed'
      && failed.body.failure_code && failed.body.document === null && failed.body.receipt === null);
    const failedFetches = await countFetch();
    const failedReplay = await capture(failedPayload);
    check('failure-replay-no-automatic-retry', failedReplay.body.replayed && failedReplay.body.state === 'failed'
      && await countFetch() === failedFetches);
    const deniedPolicy = catalogue.body.items.find(row => row.policy_id === 'qa-robots-denied');
    const denied = await capture({ ...payload, policy_id: deniedPolicy.policy_id,
      expected_policy_fingerprint: deniedPolicy.policy_fingerprint, idempotency_key: crypto.randomUUID() });
    const afterDenied = await state();
    check('robots-denial-blocks-pdf-request', denied.body.state === 'failed'
      && afterDenied.upstream_requests.filter(row => row.url === deniedPolicy.download_url).length === 0);
    check('failed-requests-publish-no-documents', afterDenied.counts.documents === beforeFailure.counts.documents);

    const materials = await call('/v1/test-sku-links/materials?mode=history');
    const material = materials.body.items.find(row => row.id === document.id);
    check('captured-original-available-to-r71', materials.status === 200 && Boolean(material?.metadata_hash));
    const bridgeBody = { mode: 'history', action: 'create', link_id: null,
      selection: { event_id: baseline.event_id, event_revision_id: baseline.event_revision_id,
        participant_key: 'a', variant_id: baseline.variant_id, tire_snapshot_id: baseline.tire_snapshot_id,
        fact_version_id: baseline.fact_version_id },
      materials: [{ document_id: document.id, expected_raw_hash: document.raw_hash,
        expected_metadata_hash: material.metadata_hash,
        event_locator: { page: 1, region: 'Synthetic event heading', quote: 'R72 Synthetic same-event test' },
        participant_locator: { page: 1, region: 'Synthetic participant heading', quote: 'Participant a: Synthetic Tire' },
        rights: { rights_holder: policy.rights.rights_holder, basis: policy.rights.basis,
          store_original: true, workspace_reopen: true, quote_identifiers: true } }],
      assertions: Object.entries(baseline.identity).map(([field, value]) => ({ field,
        material_document_id: document.id, material_value: value, page: 1, region: 'Synthetic row ' + field,
        quote: field + ': ' + JSON.stringify(value) })), evidence_level: 'source_explicit_identifiers_in_supplied_material' };
    const bridge = await call('/v1/test-sku-links/preview', 'POST', bridgeBody);
    check('captured-pdf-reused-with-exact-ref-page', bridge.status === 200 && bridge.body.can_submit, bridge.body.blockers);
    check('transport-receipt-does-not-upgrade-bridge', bridge.body.boundary.material_origin === 'operator_supplied'
      && bridge.body.boundary.origin_verification === 'unverified' && !bridge.body.boundary.provider_use
      && !bridge.body.boundary.export && bridge.body.eligibility !== 'conditional_reviewed_transcription');
    const final = await state();
    check('facts-and-source-results-unchanged', final.counts.facts === baseline.counts.facts
      && final.counts.snapshots === baseline.counts.snapshots);
    check('all-private-guards-zero', Object.values(final.counters).every(n => n === 0));
    output.outcome = 'passed';
    output.done = true;
  } catch (error) { output.outcome = 'failed'; output.done = true; output.error = String(error); }
  return output;
})()
