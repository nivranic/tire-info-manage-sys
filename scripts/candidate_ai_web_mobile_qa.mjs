/* Layout and blocked preparation with real private HTTP; no native-device claim. */
(async () => {
  const records = [];
  const output = { schema: 'r77-private-mobile-layout@1', records, done: false,
    synthetic_only: true, real_private_http: true, viewport: { width: innerWidth, height: innerHeight } };
  const pause = (ms = 80) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, ok, detail = null) => { records.push({ name, passed: !!ok, detail }); if (!ok) throw new Error(name); };
  const until = async (read, label) => { const start = Date.now(); while (Date.now() - start < 25000) { const value = read(); if (value) return value; await pause(); } throw new Error('timeout: ' + label); };
  const request = async path => { const response = await fetch('/api' + path, { credentials: 'include' }); if (!response.ok) throw new Error('HTTP ' + response.status); return response.json(); };
  const select = async (node, value) => { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(node, value); node.dispatchEvent(new Event('change', { bubbles: true })); await pause(); };
  const panel = () => document.querySelector('[data-testid="candidate-ai-assistance"]');
  try {
    const fixture = await request('/fixture/state'), calls = fixture.provider_calls;
    location.hash = '#/home';
    let root = await until(() => document.getElementById('fitment-candidates-title')?.closest('section'), 'home');
    if (!panel()) {
      const selects = root.querySelectorAll('.home-candidate-selection select');
      await until(() => [...selects[0].options].some(row => row.value === fixture.selection.vehicle_snapshot_id), 'catalog');
      await select(selects[0], fixture.selection.vehicle_snapshot_id);
      await until(() => [...selects[1].options].some(row => row.value === fixture.selection.trim_id), 'trim');
      await select(selects[1], fixture.selection.trim_id); await select(selects[2], fixture.selection.wheel_option_id); await select(selects[3], fixture.selection.axle);
      [...root.querySelectorAll('button')].find(node => node.textContent.trim() === '核对所选轴位候选').click();
      await until(panel, 'C panel');
    }
    const reset = [...panel().querySelectorAll('button')].find(node => node.textContent.trim() === '返回准备新的辅助');
    if (reset) { reset.click(); await pause(); }
    for (const identifier of fixture.variants) {
      const node = panel().querySelector('[data-candidate-ai-variant="' + identifier + '"]');
      if (!node.checked) { node.click(); await pause(); }
    }
    panel().querySelector('[data-testid="candidate-ai-prepare"]').click();
    await pause(150);
    await until(() => panel().querySelector('[data-testid="candidate-ai-preparation"]'), 'private preparation');
    panel().scrollIntoView({ block: 'start' }); await pause();
    check('dedicated-panel-visible', panel().getBoundingClientRect().width > 0);
    check('selected-candidates-two', panel().querySelectorAll('[data-candidate-ai-variant]:checked').length === 2);
    check('revoked-source-consent-disabled', panel().querySelector('[data-testid="candidate-ai-consent"]').disabled);
    check('submit-disabled', panel().querySelector('[data-testid="candidate-ai-submit"]').disabled);
    check('all-source-kinds-readable', ['车型来源', '轮胎来源', '人工适配关系'].every(label => panel().textContent.includes(label)));
    check('performance-boundary-visible', /七维精确.*性能证据未建立/.test(panel().textContent));
    check('recipient-host-readable', panel().textContent.includes('api.openai.com'));
    check('prepare-and-recover-controls-fit', ['candidate-ai-prepare', 'candidate-ai-recover'].every(id => {
      const box = panel().querySelector('[data-testid="' + id + '"]').getBoundingClientRect(); return box.left >= 0 && box.right <= innerWidth;
    }));
    for (const node of panel().querySelectorAll('.candidate-ai-facts, .candidate-ai-provider details')) node.open = true;
    await pause();
    check('expanded-hashes-no-horizontal-overflow', document.documentElement.scrollWidth <= innerWidth,
      { document: document.documentElement.scrollWidth, viewport: innerWidth });
    check('no-model-call-on-mobile-prepare', (await request('/fixture/state')).provider_calls === calls);
    output.done = true; output.passed = records.length;
  } catch (error) { output.error = String(error); }
  return output;
})();
