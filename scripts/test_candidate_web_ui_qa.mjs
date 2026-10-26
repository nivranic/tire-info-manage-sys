/* Real React controls with actual private HTTP; only delayed delivery is instrumented. */
(async () => {
  const records = [];
  const output = { schema: 'r75-private-react-qa@1', records, done: false, real_http: true,
    synthetic_only: true, viewport: { width: innerWidth, height: innerHeight } };
  window.__candidateUiQA = output;
  const check = (name, passed, detail = null) => { records.push({ name, passed: Boolean(passed), detail }); if (!passed) throw new Error(name + ': ' + JSON.stringify(detail)); };
  const pause = (ms = 75) => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (read, label) => {
    const start = Date.now();
    while (Date.now() - start < 20000) { const result = read(); if (result) return result; await pause(); }
    throw new Error('UI timeout: ' + label);
  };
  const button = (root, text) => [...root.querySelectorAll('button')].find(node => node.textContent.trim() === text);
  const select = async (node, value) => {
    if (!node || node.disabled) throw new Error('Expected available select');
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(node, String(value));
    node.dispatchEvent(new Event('change', { bubbles: true })); await pause();
  };
  const click = async node => { if (!node || node.disabled) throw new Error('Expected enabled control'); node.click(); await pause(); };
  const req = async (path, body) => (await fetch('/api' + path, { method: body ? 'POST' : 'GET', credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined })).json();
  const panel = () => document.querySelector('[data-testid="test-candidate-interpretation"]');
  const result = () => panel()?.querySelector('[data-testid="test-candidate-result"]');
  const nativeFetch = window.fetch;
  try {
    const fixture = await req('/fixture/state');
    location.hash = '#/home';
    async function openCandidates() {
      const root = await until(() => document.getElementById('fitment-candidates-title')?.closest('section'), 'candidate section');
      await until(() => root.querySelector('select')?.options.length > 1, 'vehicle options');
      await select(root.querySelector('select'), fixture.selections[0].vehicle_snapshot_id);
      await until(() => !root.querySelectorAll('select')[1].disabled, 'trim loaded');
      await select(root.querySelectorAll('select')[1], fixture.selections[0].trim_id);
      await select(root.querySelectorAll('select')[2], fixture.selections[0].wheel_option_id);
      await click(button(root, '核对所选轴位候选'));
      await until(() => panel() || root.querySelector('[role="alert"]'), 'candidate projection');
      check('candidate-panel-real-entry', !!panel(), root.querySelector('[role="alert"]')?.textContent);
      await until(() => panel().querySelector('select[aria-label="选择当前测试场次"]')?.options.length > 1, 'event list');
      await select(panel().querySelector('select[aria-label="选择当前测试场次"]'), fixture.event_id);
      await until(() => panel().querySelectorAll('[data-candidate-bridge]').length === 2
        && [...panel().querySelectorAll('[data-candidate-bridge]')].every(node => !node.disabled), 'current bridge list');
      return root;
    }
    async function chooseSet() {
      for (const variant of fixture.variants) {
        const checkbox = panel().querySelector(`[data-candidate-choice="${variant}"] input[type="checkbox"]`);
        if (!checkbox.checked) await click(checkbox);
        const bridge = panel().querySelector(`select[data-candidate-bridge="${variant}"]`);
        await select(bridge, [...bridge.options].find(option => option.value)?.value);
      }
    }
    async function mapAll() {
      for (const metric of fixture.event.event.metrics) {
        await select(panel().querySelector(`select[aria-label="${metric.label}的候选解读维度"]`), metric.key === 'noise' ? 'quiet' : metric.key);
      }
    }
    async function calculate() {
      await click(button(panel(), '按已选桥与映射解读候选'));
      await until(() => result() || panel()?.querySelector('[data-testid="test-candidate-error"]'), 'interpretation completion');
      check('react-response-binding-accepted', !!result(), panel()?.querySelector('[data-testid="test-candidate-error"]')?.textContent);
      return result();
    }
    await openCandidates();
    check('all-metric-mappings-start-null', [...panel().querySelectorAll('.test-candidate-mapping select')].every(node => node.value === ''));
    check('no-name-size-auto-bridge-selection', [...panel().querySelectorAll('[data-candidate-bridge]')].every(node => !node.value)
      && !panel().querySelector('input[type=checkbox]:checked'));
    await chooseSet();
    const nullResult = await calculate();
    check('all-null-coverage-zero', nullResult.querySelector('.test-candidate-coverage')?.textContent.includes('0%')
      && !nullResult.textContent.includes('本次已录观察中的有利数值对象'));
    await mapAll();
    check('mapping-change-clears-old-result', !result());
    const positive = await calculate();
    check('source-original-strings-visible', ['38.00', '-0', '0'].every(value => positive.querySelector(`[data-raw-value="${value}"]`)));
    check('missing-and-direction-remain-explicit', positive.textContent.includes('未录入成绩，不补零') && positive.textContent.includes('来源未说明数值方向'));
    check('source-ranking-and-evidence-separate', positive.textContent.includes('来源名次')
      && positive.querySelector('section[aria-label="本次条件性身份桥"]') && positive.querySelector('section[aria-label="本场原始来源与成绩"]'));
    check('coverage-four-distinct-figures', positive.querySelectorAll('.test-candidate-coverage > div').length === 4);
    const bridgeEvidence = positive.querySelector('section[aria-label="本次条件性身份桥"] details');
    await click(bridgeEvidence.querySelector('summary'));
    check('material-locators-rights-and-hashes-visible', bridgeEvidence.textContent.includes('场次定位：第 1 页')
      && bridgeEvidence.textContent.includes('参测对象定位：第 1 页') && bridgeEvidence.textContent.includes('原件 SHA-256')
      && bridgeEvidence.textContent.includes('不可用于 Provider 或导出'));
    check('synthetic-identity-not-professional-golden', bridgeEvidence.textContent.includes('SYNTHETIC')
      && positive.textContent.includes('未在线核验'));
    await req('/fixture/link-state', { index: 1, action: 'revoke' });
    await click(button(panel(), '按已选桥与映射解读候选'));
    await until(() => panel()?.querySelector('[data-testid="test-candidate-error"]'), 'stale current link rejection');
    check('stale-bridge-409-clears-result', !result() && panel().textContent.includes('旧结果已清空'));
    await click(button(panel(), '刷新本场身份桥'));
    await until(() => [...panel().querySelectorAll('[data-candidate-bridge]')].every(node => !node.disabled && [...node.options].some(option => option.textContent.includes('已撤销')))
      || panel().textContent.includes('已撤销'), 'revoked bridge loaded');
    await chooseSet();
    const excluded = await calculate();
    check('excluded-set-has-no-personal-result', excluded.querySelector('.test-candidate-excluded')
      && excluded.textContent.includes('整次个人解释未生成') && !excluded.querySelector('.test-candidate-coverage'));
    check('excluded-set-still-has-participant-observations', excluded.querySelectorAll('[data-raw-value]').length === 5);
    await req('/fixture/link-state', { index: 1, action: 'restore' });
    await req('/fixture/link-state', { index: 1, action: 'review' });
    await click(button(panel(), '刷新本场身份桥'));
    await until(() => panel().querySelectorAll('[data-candidate-bridge]').length === 2
      && [...panel().querySelectorAll('[data-candidate-bridge]')].every(node => !node.disabled), 'reviewed current bridge refreshed');
    await chooseSet(); await calculate();
    let release, held = false;
    window.fetch = async function (...args) {
      const response = await nativeFetch.apply(this, args);
      const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (!held && path.includes('/candidate-interpretation')) { held = true; await new Promise(resolve => { release = resolve; }); }
      return response;
    };
    try {
      await click(button(panel(), '按已选桥与映射解读候选'));
      await until(() => held && release, 'actual delayed interpretation HTTP response');
      window.dispatchEvent(new Event('tire-session-unavailable'));
      await until(() => !document.querySelector('.personalized-home'), 'account unavailable clears private tree');
      check('account-change-clears-private-results', !result() && !panel());
      release(); await pause(250);
      check('late-actual-response-does-not-restore-old-owner', !result() && !panel());
    } finally { if (release) release(); window.fetch = nativeFetch; window.dispatchEvent(new Event('tire-session-revalidate')); }
    await until(() => document.querySelector('.personalized-home'), 'account refreshed');
    check('new-owner-epoch-has-no-old-draft', !panel());
    await openCandidates(); await chooseSet(); await mapAll(); await calculate();
    check('desktop-document-no-horizontal-overflow', document.documentElement.scrollWidth <= innerWidth,
      { viewport: innerWidth, document: document.documentElement.scrollWidth });
    output.done = true; output.passed = records.length;
    output.delayed_transport = 'actual private HTTP response held in browser memory; no response data mock';
  } catch (error) { output.error = String(error); }
  finally { window.fetch = nativeFetch; }
  return output;
})();
