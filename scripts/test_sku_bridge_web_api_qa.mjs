/* Production HTTP through the private browser origin; no real source/material/model. */
(async () => {
  const records = [];
  const output = { schema: 'test-sku-bridge-private-api-qa@1', records, done: false,
    real_http: true, material: 'project-authored synthetic PDF', production_model_calls: 0 };
  window.__bridgeApiQA = output;
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const request = async (path, method = 'GET', body, key) => {
    const response = await fetch('/api' + path, { method, credentials: 'include',
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(key ? { 'Idempotency-Key': key } : {}) },
      body: body ? JSON.stringify(body) : undefined });
    return { status: response.status, body: await response.json(),
      cacheControl: response.headers.get('cache-control') };
  };
  const preview = body => request('/v1/test-sku-links/preview', 'POST', body);
  const read = (id, revision) => request('/v1/test-sku-links/' + encodeURIComponent(id)
    + '?mode=history' + (revision ? '&revision=' + revision : ''));
  const credentials = { author: { username: 'r71_author_' + crypto.randomUUID().slice(0, 8), password: crypto.randomUUID() },
    reviewer: { username: 'r71_reviewer_' + crypto.randomUUID().slice(0, 8), password: crypto.randomUUID() } };
  // Runtime memory only. Never include credentials in receipts, files, logs or returned results.
  window.__bridgeCredentials = credentials;
  const login = actor => request('/v1/auth/login', 'POST', credentials[actor]);
  const logout = () => request('/v1/auth/logout', 'POST', {});
  const decisionBody = (body, proposed) => ({ ...body,
    expected_revision: proposed.revision, expected_fingerprint: proposed.fingerprint,
    declaration_revision_id: proposed.declaration_revision_id ?? null,
    operator: 'Synthetic HTTP QA', reason: 'Project-authored evidence workflow verification only',
    acknowledged: true,
    opened_materials: body.materials.map(item => ({ document_id: item.document_id,
      raw_hash: item.expected_raw_hash, metadata_hash: item.expected_metadata_hash })),
    confirmed_event_revision_id: body.selection.event_revision_id,
    confirmed_participant_hash: proposed.frozen_evidence.test.participant_hash,
  });
  const decide = async (body, key = crypto.randomUUID()) => {
    const proposed = await preview(body);
    check(body.action + '-preview-http', proposed.status === 200, proposed.status);
    const payload = decisionBody(body, proposed.body);
    return { ...(await request('/v1/test-sku-links/decisions', 'POST', payload, key)), payload, key };
  };
  try {
    const fixture = (await request('/fixture/state')).body;
    check('private-runtime', fixture.synthetic_only && !fixture.normal_database_used && fixture.provider_calls === 0);
    const anonymous = await preview({});
    check('admin-guard-before-body', anonymous.status === 403, anonymous.status);
    const author = await request('/v1/auth/register', 'POST', credentials.author);
    check('author-admin-created', author.status === 200 && author.body.user.is_admin);
    await logout();
    const reviewer = await request('/v1/auth/register', 'POST', credentials.reviewer);
    check('reviewer-starts-non-admin', reviewer.status === 200 && !reviewer.body.user.is_admin);
    check('nonadmin-write-rejected', (await preview({})).status === 403);
    await logout();
    check('author-real-login', (await login('author')).status === 200);
    const promoted = await request('/v1/auth/users/' + reviewer.body.user.id + '/role', 'POST', { is_admin: true });
    check('reviewer-promoted-through-production-role-route', promoted.status === 200 && promoted.body.user.is_admin);

    const main = await request('/v1/test-events/' + fixture.event_id + '?mode=history');
    const event = await request('/v1/test-events', 'POST', { event: { ...main.body.event,
      title: 'R71 独立 HTTP 合成事件；界面事件保持原样' },
      operator: 'Synthetic HTTP QA', reason: 'Separate event for destructive lifecycle API checks' });
    check('separate-event-created', event.status === 201);
    const selectedEvent = event.body;
    const materialBytes = await (await fetch('/api/fixture/material', { credentials: 'include' })).arrayBuffer();
    const metadata = { title: 'Project-authored synthetic PDF, not a professional test',
      source_url: selectedEvent.event.source_url, operator: 'Synthetic HTTP QA',
      rights_basis: 'Project-authored synthetic fixture. Local workspace storage and review allowed.' };
    const metadataHeader = btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(metadata))));
    const uploaded = await fetch('/api/v1/documents', { method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/pdf', 'X-Evidence-Metadata': metadataHeader }, body: materialBytes });
    const document = await uploaded.json();
    output.material_id = document.id;
    check('raw-pdf-upload', uploaded.status === 201 && document.status === 'unparsed_receipt'
      && document.accepted_as_facts === false);
    const materials = await request('/v1/test-sku-links/materials?mode=history');
    const material = materials.body.items.find(row => row.id === document.id);
    check('material-metadata-hash-available', materials.status === 200 && /^[0-9a-f]{64}$/.test(material.metadata_hash));
    const source = { document_id: document.id, expected_raw_hash: document.raw_hash,
      expected_metadata_hash: material.metadata_hash,
      event_locator: { page: 1, region: 'Synthetic event heading', quote: 'R71 Synthetic same-event test' },
      participant_locator: { page: 1, region: 'Synthetic participant heading', quote: 'Participant a: Synthetic Tire' },
      rights: { rights_holder: 'Project fixture author', basis: metadata.rights_basis,
        store_original: true, workspace_reopen: true, quote_identifiers: true } };
    const body = { mode: 'history', action: 'create', link_id: null,
      selection: { event_id: selectedEvent.id, event_revision_id: selectedEvent.revision_id,
        participant_key: 'a', variant_id: fixture.variant_id, tire_snapshot_id: fixture.tire_snapshot_id,
        fact_version_id: fixture.fact_version_id }, materials: [source],
      assertions: Object.entries(fixture.identity).map(([field, value]) => ({ field,
        material_document_id: document.id, material_value: value,
        quote: field + ': ' + JSON.stringify(value), page: 1, region: 'Synthetic identity row ' + field })),
      evidence_level: 'source_explicit_identifiers_in_supplied_material' };
    const proposed = await preview(body);
    check('full-explicit-preview', proposed.status === 200 && proposed.body.can_submit, proposed.body.blockers);
    check('boundary-not-upgraded', proposed.body.boundary.material_origin === 'operator_supplied'
      && proposed.body.boundary.origin_verification === 'unverified'
      && proposed.body.boundary.read_scope === 'local_workspace'
      && proposed.body.boundary.provider_use === false && proposed.body.boundary.export === false);
    check('new-preview-not-performance-eligible', proposed.body.eligibility !== 'conditional_reviewed_transcription');
    const beforeWrites = (await request('/fixture/state')).body.counts;
    await preview(body);
    const afterPreview = (await request('/fixture/state')).body.counts;
    check('preview-no-domain-write', JSON.stringify(beforeWrites) === JSON.stringify(afterPreview));

    const created = await decide(body);
    const link = created.body.link;
    check('created-pending-review', created.status === 201 && link.review_state === 'pending_review', created.status);
    output.api_link_id = link.id;
    const replay = await request('/v1/test-sku-links/decisions', 'POST', created.payload, created.key);
    check('idempotent-exact-operation', replay.status < 300 && replay.body.idempotent_replay
      && replay.body.event.revision === created.body.event.revision);
    const mismatch = await request('/v1/test-sku-links/decisions', 'POST', { ...created.payload,
      reason: 'A different request must not replace the saved operation' }, created.key);
    check('same-key-different-payload-rejected', mismatch.status === 409);
    const reviewBody = { ...body, action: 'review', link_id: link.id };
    const self = await preview(reviewBody);
    check('same-account-cannot-self-review', self.status === 200 && !self.body.can_submit
      && self.body.blockers.length > 0);
    const rejectedSelf = await request('/v1/test-sku-links/decisions', 'POST', decisionBody(reviewBody, self.body), crypto.randomUUID());
    check('self-review-write-rejected', rejectedSelf.status === 409 || rejectedSelf.status === 403, rejectedSelf.status);

    await logout();
    check('reviewer-real-login', (await login('reviewer')).status === 200);
    const rawResponse = await fetch('/api/v1/documents/' + document.id + '/content?mode=history', { credentials: 'include' });
    const raw = new Uint8Array(await rawResponse.arrayBuffer());
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))].map(value => value.toString(16).padStart(2, '0')).join('');
    check('reviewer-receives-original-sha-and-size', rawResponse.status === 200
      && raw.byteLength === document.byte_count && digest === document.raw_hash);
    const reviewed = await decide(reviewBody);
    check('two-account-review', reviewed.status === 201 && reviewed.body.link.review_state === 'reviewed', reviewed.status);
    check('conditional-transcription-only', reviewed.body.link.eligibility === 'conditional_reviewed_transcription'
      && reviewed.body.link.boundary.origin_verification === 'unverified');
    check('immutable-declaration-user', reviewed.body.link.declared_by_user_id === author.body.user.id
      && reviewed.body.link.declaration_revision_id === link.declaration_revision_id);
    const historical = await read(link.id, 1);
    check('exact-history-reopens', historical.status === 200 && historical.body.revision === 1
      && historical.body.review_state === 'pending_review');
    const revokedEvent = await request('/v1/test-events/' + selectedEvent.id + '/state', 'POST', {
      expected_revision: selectedEvent.revision, action: 'revoke', operator: 'Synthetic HTTP QA',
      reason: 'Test event revision/state invalidates old link review' });
    check('event-revoked', revokedEvent.status === 200);
    const stale = await read(link.id);
    check('event-change-invalidates-review', stale.status === 200 && stale.body.effective_state === 'needs_review'
      && stale.body.eligibility === 'none' && stale.body.stale_reasons.length > 0);
    const restoredEvent = await request('/v1/test-events/' + selectedEvent.id + '/state', 'POST', {
      expected_revision: revokedEvent.body.revision, action: 'restore', operator: 'Synthetic HTTP QA',
      reason: 'Same payload restoration must not restore old reviewed identity link' });
    check('event-restored-same-payload', restoredEvent.status === 200
      && restoredEvent.body.fingerprint === selectedEvent.fingerprint);
    const aba = await read(link.id);
    check('event-aba-does-not-revive-review', aba.body.effective_state === 'needs_review'
      && aba.body.eligibility === 'none');
    const exactAgain = await read(link.id, 1);
    check('old-evidence-not-rewritten-after-aba', exactAgain.body.fingerprint === historical.body.fingerprint
      && exactAgain.body.frozen_evidence.test.revision_id === selectedEvent.revision_id);
    const finalState = (await request('/fixture/state')).body;
    check('manufacturer-facts-not-mutated', finalState.counts.facts === fixture.counts.facts
      && finalState.counts.snapshots === fixture.counts.snapshots);
    check('all-private-guards-zero', Object.values(finalState.counters).every(value => value === 0));
    await logout();
    await login('author');
    output.done = true;
    output.outcome = 'passed';
  } catch (error) { output.outcome = 'failed'; output.error = String(error); }
  return output;
})()
