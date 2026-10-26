/* Actual React + private HTTP; no API response mock and no credential recording. */
(async () => {
  const records = [];
  const output = { schema: 'r77-private-react-qa@1', records, done: false,
    synthetic_only: true, real_private_http: true, real_provider: false,
    viewport: { width: innerWidth, height: innerHeight } };
  window.__candidateAiUiQA = output;
  const nativeFetch = window.fetch;
  const pause = (ms = 75) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name);
  };
  const until = async (read, label) => {
    const started = Date.now();
    while (Date.now() - started < 25000) { const value = read(); if (value) return value; await pause(); }
    throw new Error('UI timeout: ' + label);
  };
  const request = async (path, body) => {
    const response = await nativeFetch('/api' + path, { credentials: 'include',
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    const value = await response.json();
    if (!response.ok) throw new Error('Private HTTP status ' + response.status + ' at ' + path);
    return value;
  };
  const input = async (node, value) => {
    if (!node || node.disabled) throw new Error('Expected enabled input');
    const type = node.tagName === 'SELECT' ? HTMLSelectElement : node.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(type.prototype, 'value').set.call(node, String(value));
    node.dispatchEvent(new Event(node.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    await pause();
  };
  const click = async node => { if (!node || node.disabled) throw new Error('Expected enabled control'); node.click(); await pause(); };
  const findButton = (root, label) => [...root.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const panel = () => document.querySelector('[data-testid="candidate-ai-assistance"]');
  let preparation = null, recommendation = null, postCount = 0, getCount = 0;
  window.fetch = async function (...args) {
    const response = await nativeFetch.apply(this, args);
    const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    const method = String(args[1]?.method || 'GET').toUpperCase();
    if (path.endsWith('/candidate-preparations') && response.ok) preparation = await response.clone().json();
    if (path.includes('/candidate-recommendations')) {
      if (method === 'POST') postCount++; else getCount++;
      if (response.ok) recommendation = await response.clone().json();
    }
    return response;
  };
  try {
    await request('/health');
    await request('/fixture/session', {});
    window.dispatchEvent(new Event('tire-session-revalidate'));
    const fixture = await request('/fixture/state');
    location.hash = '#/home';
    const root = await until(() => document.getElementById('fitment-candidates-title')?.closest('section'), 'candidate home');
    const selects = root.querySelectorAll('.home-candidate-selection select');
    await until(() => [...selects[0].options].some(option => option.value === fixture.selection.vehicle_snapshot_id), 'vehicle catalog');
    await input(selects[0], fixture.selection.vehicle_snapshot_id);
    await until(() => [...selects[1].options].some(option => option.value === fixture.selection.trim_id), 'trim');
    await input(selects[1], fixture.selection.trim_id);
    await input(selects[2], fixture.selection.wheel_option_id);
    await input(selects[3], fixture.selection.axle);
    await click(findButton(root, '核对所选轴位候选'));
    await until(panel, 'dedicated C panel');
    check('dedicated-spec-panel-and-performance-boundary', /七维精确.*性能证据未建立/.test(panel().textContent));
    for (const identifier of fixture.variants) await click(panel().querySelector('[data-candidate-ai-variant="' + identifier + '"]'));
    await input(panel().querySelector('[aria-label="规格辅助问题"]'), '合成自有目录：选择有规格依据的后续核对选项，保留全部不足。');
    await click(panel().querySelector('[data-testid="candidate-ai-prepare"]'));
    await until(() => preparation && panel().querySelector('[data-testid="candidate-ai-preparation"]'), 'blocked preparation');
    const first = preparation;
    check('missing-source-rights-blocks-external-consent', !first.sendable && !first.consent_hash && panel().querySelector('[data-testid="candidate-ai-consent"]').disabled);
    check('all-source-dependencies-present', first.dependencies.length >= 5 && ['vehicle', 'tire', 'relation'].every(kind => first.dependencies.some(row => row.source_kind === kind)));
    check('blocked-prepare-zero-provider-calls', (await request('/fixture/state')).provider_calls === 0);
    const declaration = fixture.synthetic_rights_declaration;
    const dependency = first.dependencies[0];
    const dependencyPanel = panel().querySelector('[data-candidate-ai-dependency="' + dependency.id + '"]');
    const admin = dependencyPanel.querySelector('.candidate-ai-admin');
    admin.open = true;
    const field = label => [...admin.querySelectorAll('label')].find(node => node.querySelector('span')?.textContent === label)?.querySelector('input,textarea,select');
    await input(field('实际权利人'), declaration.rights_holder);
    await input(field('许可证据 URL（无凭据或身份参数）'), declaration.license_basis_url);
    await input(field('许可依据与本用途范围'), declaration.license_basis_note);
    await input(field('真实许可证据 SHA-256'), declaration.license_evidence_sha256);
    const expiry = new Date(Date.now() + 3600000);
    const localExpiry = new Date(expiry.getTime() - expiry.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    await input(field('许可有效期'), localExpiry);
    await click(admin.querySelector('input[type="checkbox"]'));
    await click(findButton(admin, '记录这项用途许可修订'));
    await until(() => panel().querySelector('[data-testid="candidate-ai-preparation"]').textContent.includes('用途许可修订已记录'), 'recorded authorization');
    check('source-grant-does-not-enable-old-preparation', panel().querySelector('[data-testid="candidate-ai-consent"]').disabled && panel().querySelector('[data-testid="candidate-ai-submit"]').disabled);
    for (const dep of first.dependencies.slice(1)) await request('/v1/ai/candidate-preparations/' + first.preparation_id + '/authorizations',
      { ...declaration, dependency_id: dep.id, expected_revision: 0, action: 'grant' });
    preparation = null;
    await click(panel().querySelector('[data-testid="candidate-ai-prepare"]'));
    await until(() => preparation?.sendable, 'new ready preparation');
    check('new-preparation-binds-real-recipient-and-body', preparation.provider.endpoint_host === 'api.openai.com' && /^[a-f0-9]{64}$/.test(preparation.provider.body_hash));
    check('submit-disabled-before-personal-consent', panel().querySelector('[data-testid="candidate-ai-submit"]').disabled);
    await click(panel().querySelector('[data-testid="candidate-ai-consent"]'));
    const priorId = preparation.preparation_id;
    await input(panel().querySelector('[aria-label="规格辅助问题"]'), '合成目录新问题：仍只核对规格，不作性能结论。');
    check('question-change-clears-preparation-and-consent', !panel().querySelector('[data-testid="candidate-ai-preparation"]'));
    preparation = null;
    await click(panel().querySelector('[data-testid="candidate-ai-prepare"]'));
    await until(() => preparation?.sendable, 'prepared new question');
    check('new-question-needs-new-consent', preparation.preparation_id !== priorId && !panel().querySelector('[data-testid="candidate-ai-consent"]').checked && panel().querySelector('[data-testid="candidate-ai-submit"]').disabled);
    await click(panel().querySelector('[data-testid="candidate-ai-consent"]'));
    await click(panel().querySelector('[data-testid="candidate-ai-submit"]'));
    await until(() => recommendation?.state === 'completed' && panel().querySelector('[data-testid="candidate-ai-result"]'), 'validated result');
    check('one-controlled-provider-call', (await request('/fixture/state')).provider_calls === 1 && postCount === 1);
    check('validated-selected-and-not-selected-partition', recommendation.answer.selections.length === 1 && recommendation.answer.not_selected_variant_ids.length === 1 && recommendation.answer.ranking === 'not_computed' && recommendation.answer.performance_score === null);
    check('uncertainty-and-history-displayed', recommendation.current === false && recommendation.answer.uncertainty.length >= 4 && /冻结历史/.test(panel().querySelector('[data-testid="candidate-ai-result"]').textContent));
    const id = recommendation.id;
    await click(panel().querySelector('[data-testid="candidate-ai-recover"]'));
    await until(() => getCount === 1, 'read-only recovery');
    check('recovery-no-second-model-call', recommendation.id === id && (await request('/fixture/state')).provider_calls === 1 && postCount === 1);
    await request('/v1/ai/candidate-preparations/' + first.preparation_id + '/authorizations',
      { dependency_id: dependency.id, provider: declaration.provider, expected_revision: 1,
        action: 'revoke', acknowledged: true, revocation_note: '撤销本次合成目录模型用途，用于验证冻结历史重新核对。' });
    await click(panel().querySelector('[data-testid="candidate-ai-recover"]'));
    await until(() => recommendation?.current_status.state === 'stale', 'recovery sees revoked rights');
    check('revocation-keeps-frozen-answer-and-marks-stale', recommendation.answer.selections.length === 1 && /许可或依据已变化/.test(panel().querySelector('[data-testid="candidate-ai-result"]').textContent) && (await request('/fixture/state')).provider_calls === 1);
    check('desktop-no-horizontal-overflow', document.documentElement.scrollWidth <= innerWidth,
      { document: document.documentElement.scrollWidth, viewport: innerWidth });
    output.done = true;
    output.passed = records.length;
  } catch (error) { output.error = String(error); }
  finally { window.fetch = nativeFetch; }
  return output;
})();
