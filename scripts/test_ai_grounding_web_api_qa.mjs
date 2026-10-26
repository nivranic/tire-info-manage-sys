/* Execute inside the isolated browser origin; all calls use real private HTTP. */
(async () => {
  const records = [];
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const request = async (path, method = 'GET', body, key) => {
    const response = await fetch('/api' + path, { method, credentials: 'include',
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(key ? { 'Idempotency-Key': key } : {}) },
      body: body ? JSON.stringify(body) : undefined });
    return { status: response.status, body: await response.json() };
  };
  const prepare = refs => request('/v1/ai/evidence-packs', 'POST', { mode: 'history', references: refs });
  const analyze = pack => request('/v1/ai/analyses', 'POST', {
    pack_id: pack.id, question: '摘录所选历史测试的原始事实', allow_external_processing: true }, crypto.randomUUID());
  const wait = async id => {
    for (let index = 0; index < 100; index++) {
      const response = await request('/v1/ai/analysis-streams/' + id + '?mode=history');
      if (response.body.execution?.terminal) return response.body;
      await new Promise(resolve => setTimeout(resolve, 80));
    }
    throw new Error('Stream did not reach terminal');
  };
  const output = { schema: 'test-ai-private-api-qa@1', records, done: false, model: 'synthetic adapter only', real_http: true };
  window.__testAiApiQA = output;
  try {
    const state = (await request('/fixture/state')).body;
    check('private-isolation', state.synthetic_only && !state.normal_database_used);
    const testRef = { kind: 'test_event', event_id: state.event_id, event_revision: state.event_revision };
    const tireRef = { kind: 'tire', snapshot_id: state.tire_snapshot_id, variant_id: state.variant_id };
    const prepared = await prepare([testRef]);
    check('prepare-test-pack', prepared.status === 200, prepared.status);
    const pack = prepared.body.pack;
    check('server-test-boundary', pack.test_boundary?.policy_version === 'test-grounding@1'
      && pack.test_boundary.sku_link === 'not_established' && pack.test_boundary.verification_status === 'unverified');
    check('source-remains-manual-unverified', pack.evidence[0].verified_at === null
      && pack.evidence[0].verification_status === 'unverified');
    await request('/fixture/model?mode=valid', 'POST');
    const valid = await analyze(pack);
    check('sync-fact-completed', valid.status === 200 && valid.body.state === 'completed', valid.status);
    check('sync-boundary-and-no-freeform', valid.body.answer.test_boundary?.mode === 'fact_selection_only'
      && valid.body.answer.uncertainty === '' && valid.body.answer.claims.every(claim => claim.type === 'fact'));
    check('original-decimal-and-rank-preserved', valid.body.answer.claims[0].text.includes('38.00')
      && valid.body.answer.claims[0].text.includes('source_rank') && valid.body.answer.claims[0].text.includes('3'));
    check('usage-accounted', valid.body.usage.total_tokens === 600);
    check('versioned-request-contract', valid.body.request_contract.prompt_version === 'test-grounding@1');
    await request('/fixture/model?mode=inference', 'POST');
    const rejected = await analyze(pack);
    check('test-only-inference-rejected', rejected.status === 200 && rejected.body.state === 'failed'
      && rejected.body.error_code === 'ai_grounding_validation_failed' && rejected.body.answer === null);
    const mixed = await prepare([tireRef, testRef]);
    check('mixed-pack-still-available', mixed.status === 200 && mixed.body.pack.evidence.length === 2);
    const mixedRejected = await analyze(mixed.body.pack);
    check('unbridged-mixed-inference-rejected', mixedRejected.body.state === 'failed' && mixedRejected.body.answer === null);
    await request('/fixture/model?mode=uncertainty', 'POST');
    const accepted = await request('/v1/ai/analysis-streams', 'POST', {
      pack_id: pack.id, question: '摘录本场事实', allow_external_processing: true }, crypto.randomUUID());
    check('stream-accepted', accepted.status === 202, accepted.status);
    const failed = await wait(accepted.body.analysis.id);
    check('stream-uncertainty-rejected', failed.analysis.state === 'failed'
      && failed.analysis.error_code === 'ai_grounding_validation_failed');
    const events = (await request('/v1/ai/analysis-streams/' + failed.analysis.id + '/events?mode=history')).body;
    check('no-forbidden-uncertainty-draft', !JSON.stringify(events).includes('Synthetic forbidden')
      && !events.items.some(item => item.type === 'uncertainty_draft' && item.payload.text));
    await request('/fixture/model?mode=valid', 'POST');
    const stream = await request('/v1/ai/analysis-streams', 'POST', {
      pack_id: pack.id, question: '分别摘录本场原始成绩', allow_external_processing: true }, crypto.randomUUID());
    const completed = await wait(stream.body.analysis.id);
    check('valid-stream-completed', completed.analysis.state === 'completed');
    check('valid-stream-fixed-boundary', completed.analysis.answer.test_boundary?.policy_version === 'test-grounding@1'
      && completed.analysis.answer.uncertainty === '');
    const beforeSaveCalls = (await request('/fixture/state')).body.counters.synthetic_model_calls;
    const report = await request('/v1/reports', 'POST', { mode: 'history', pack_id: pack.id,
      analysis_id: valid.body.id, title: 'Synthetic R70 test facts', notes: 'Project-authored acceptance evidence' }, crypto.randomUUID());
    check('report-created', report.status === 201, report.status);
    check('report-frozen-test-boundary', report.body.body.test_boundary?.policy_version === 'test-grounding@1');
    for (const format of ['markdown', 'html', 'pdf']) {
      const exported = await request('/v1/reports/' + report.body.id + '/exports', 'POST', {
        revision: report.body.revision, format });
      check('export-' + format, exported.status === 201 && exported.body.renderer_version === 'frozen-research-export@5', exported.status);
      const response = await fetch('/api' + exported.body.content_url, { credentials: 'include' });
      const bytes = new Uint8Array(await response.arrayBuffer());
      check('export-bytes-' + format, response.status === 200 && bytes.length === exported.body.byte_count && bytes.length > 0);
      if (format !== 'pdf') check('export-boundary-' + format, new TextDecoder().decode(bytes).replaceAll('\\-', '-').includes('test-grounding@1'));
    }
    const finalState = (await request('/fixture/state')).body;
    check('save-export-no-new-model-call', finalState.counters.synthetic_model_calls === beforeSaveCalls);
    check('guard-counters-clear', ['external_network_attempts', 'parser_children', 'actual_provider_attempts', 'normal_database_attempts']
      .every(key => finalState.counters[key] === 0), finalState.counters);
    output.done = true; output.outcome = 'passed'; output.report_id = report.body.id;
  } catch (cause) {
    output.done = true; output.outcome = 'failed'; output.error = String(cause);
  }
  return output;
})();
