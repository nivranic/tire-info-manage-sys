/* Narrow-screen shared flow and layout with private actual HTTP; no native device claim. */
(async () => {
  const pause = () => new Promise(resolve => setTimeout(resolve, 80));
  const until = async read => { const start = Date.now(); while (Date.now() - start < 20000) { const value = read(); if (value) return value; await pause(); } throw new Error('Responsive setup timed out'); };
  const set = async (node, value) => { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(node, value); node.dispatchEvent(new Event('change', { bubbles: true })); await pause(); };
  const button = (root, text) => [...root.querySelectorAll('button')].find(node => node.textContent.trim() === text);
  let panel = document.querySelector('[data-testid="test-candidate-interpretation"]');
  if (!panel?.querySelector('[data-testid="test-candidate-result"]')) {
    const fixture = await (await fetch('/api/fixture/state', { credentials: 'include' })).json();
    const root = await until(() => document.getElementById('fitment-candidates-title')?.closest('section'));
    await until(() => root.querySelector('select')?.options.length > 1);
    await set(root.querySelector('select'), fixture.selections[0].vehicle_snapshot_id);
    await until(() => !root.querySelectorAll('select')[1].disabled);
    await set(root.querySelectorAll('select')[1], fixture.selections[0].trim_id);
    await set(root.querySelectorAll('select')[2], fixture.selections[0].wheel_option_id);
    button(root, '核对所选轴位候选').click();
    panel = await until(() => document.querySelector('[data-testid="test-candidate-interpretation"]'));
    await until(() => panel.querySelector('select[aria-label="选择当前测试场次"]')?.options.length > 1);
    await set(panel.querySelector('select[aria-label="选择当前测试场次"]'), fixture.event_id);
    await until(() => panel.querySelectorAll('[data-candidate-bridge]').length === 2 && [...panel.querySelectorAll('[data-candidate-bridge]')].every(node => !node.disabled));
    for (const variant of fixture.variants) {
      panel.querySelector(`[data-candidate-choice="${variant}"] input[type=checkbox]`).click(); await pause();
      const bridge = panel.querySelector(`select[data-candidate-bridge="${variant}"]`);
      await set(bridge, [...bridge.options].find(option => option.value).value);
    }
    for (const metric of fixture.event.event.metrics) await set(panel.querySelector(`select[aria-label="${metric.label}的候选解读维度"]`), metric.key === 'noise' ? 'quiet' : metric.key);
    await until(() => !button(panel, '按已选桥与映射解读候选').disabled);
    button(panel, '按已选桥与映射解读候选').click();
    await until(() => panel.querySelector('[data-testid="test-candidate-result"]'));
  }
  const result = panel?.querySelector('[data-testid="test-candidate-result"]');
  const checks = {
    requestedViewport: [390, 320].includes(innerWidth), rendered: !!panel, resultRetained: !!result,
    explicitEvent: !!panel?.querySelector('select[aria-label="选择当前测试场次"]')?.value,
    explicitTwoBridges: panel?.querySelectorAll('input[type=checkbox]:checked').length === 2,
    allMetrics: panel?.querySelectorAll('.test-candidate-mapping').length === 3,
    coverageFour: result?.querySelectorAll('.test-candidate-coverage>div').length === 4,
    sourceString: !!result?.querySelector('[data-raw-value="38.00"]'), negativeZero: !!result?.querySelector('[data-raw-value="-0"]'),
    noHorizontalOverflow: document.documentElement.scrollWidth <= innerWidth,
    controlsFit: !!panel && [...panel.querySelectorAll('select')].every(node => node.getBoundingClientRect().width <= innerWidth),
    readableBody: !!panel && getComputedStyle(panel).fontSize !== '0px',
  };
  panel?.scrollIntoView({ block: 'start' });
  return { schema: 'r75-responsive-checks@1', viewport: { width: innerWidth, height: innerHeight }, checks,
    passed: Object.values(checks).filter(Boolean).length, done: Object.values(checks).every(Boolean),
    scope: 'narrow-screen shared selection/computation and layout with actual private HTTP; not complete desktop regression or native device acceptance' };
})();
