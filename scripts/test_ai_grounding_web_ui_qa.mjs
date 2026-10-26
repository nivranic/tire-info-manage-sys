/* Rendered React UI with real isolated API and a synthetic model adapter. */
(async () => {
  const records = [];
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const until = async (read, label) => {
    // The existing SSE window may buffer in the development proxy for 25 s.
    for (let index = 0; index < 500; index++) {
      const value = read(); if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 80));
    }
    throw new Error('UI timeout: ' + label);
  };
  const button = (root, label) => [...root.querySelectorAll('button')].find(node => node.textContent.includes(label));
  const input = (node, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value);
    node.dispatchEvent(new Event('input', { bubbles: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const state = async () => (await fetch('/api/fixture/state', { credentials: 'include' })).json();
  const output = { schema: 'test-ai-private-ui-qa@1', records, done: false,
    viewport: { width: innerWidth, height: innerHeight }, real_http: true, model: 'synthetic adapter only' };
  window.__testAiUiQA = output;
  try {
    await fetch('/api/fixture/model?mode=valid', { method: 'POST', credentials: 'include' });
    location.hash = '#/compare';
    const events = await until(() => document.querySelector('.test-events'), 'test events');
    const open = await until(() => button(events, '核对本场成绩'), 'event button'); open.click();
    const event = await until(() => document.querySelector('.test-event-detail'), 'event detail');
    const ai = await until(() => button(event, 'AI 摘录本场事实'), 'fact selector entry');
    check('explicit-fact-entry-and-preference-retained', !!ai && !!button(event, '按我的偏好解读本场'));
    ai.click();
    const dialog = await until(() => document.querySelector('.ai-dialog[open]'), 'AI dialog');
    check('scope-before-preparation', dialog.textContent.includes('仅摘录已录事实') && dialog.textContent.includes('精确 SKU 性能关联和推荐尚未建立'));
    const before = (await state()).counters.synthetic_model_calls;
    const prepare = await until(() => { const node = button(dialog, '准备所选历史证据'); return node && !node.disabled && node; }, 'prepare enabled');
    prepare.click();
    const boundary = await until(() => dialog.querySelector('[data-test-analysis-boundary="test-grounding@1"]'), 'server boundary');
    check('prepared-server-boundary', boundary.textContent.includes('SKU'));
    check('prepare-no-model-call', (await state()).counters.synthetic_model_calls === before);
    check('unverified-history-not-upgraded', dialog.textContent.includes('历史证据') && dialog.textContent.includes('人工'));
    const consent = await until(() => dialog.querySelector('.ai-form input[type="checkbox"]'), 'consent checkbox'); consent.click();
    const submit = await until(() => { const node = button(dialog, '发送到 AI Provider 并分析'); return node && !node.disabled && node; }, 'submit enabled');
    const submittedAt = performance.now(); submit.click();
    const result = await until(() => {
      const node = dialog.querySelector('.ai-result');
      return node?.textContent.includes('已完成引用校验') && node;
    }, 'completed UI');
    output.stream_completion_ms = Math.round(performance.now() - submittedAt);
    check('real-stream-fact-result', result.querySelectorAll('.ai-claim.fact').length > 0);
    check('no-model-freeform-result', !result.querySelector('.ai-claim.inference'));
    check('completed-server-boundary', !!result.querySelector('[data-test-analysis-boundary="test-grounding@1"]'));
    check('original-measurement-rendered', result.textContent.includes('38.00') && result.textContent.includes('source_rank'));
    const save = await until(() => button(dialog, '保存含分析的报告'), 'save analysis'); save.click();
    const saveDialog = await until(() => document.querySelector('.report-save-dialog[open]'), 'save dialog');
    check('save-preview-boundary', !!saveDialog.querySelector('[data-test-analysis-boundary="test-grounding@1"]'));
    const title = 'R70 浏览器事实 ' + Date.now(); input(saveDialog.querySelector('input'), title);
    const saveSubmit = await until(() => { const node = button(saveDialog, '保存报告（不调用模型）'); return node && !node.disabled && node; }, 'save enabled');
    const beforeSave = (await state()).counters.synthetic_model_calls;
    saveSubmit.click();
    await until(() => !document.querySelector('.report-save-dialog[open]') && dialog.textContent.includes('已保存报告：' + title), 'saved report');
    check('save-did-not-call-model', (await state()).counters.synthetic_model_calls === beforeSave);
    dialog.querySelector('[aria-label="关闭 AI 分析"]').click();
    const libraryButton = await until(() => button(document.querySelector('main'), '打开证据报告库'), 'report library entry'); libraryButton.click();
    const library = await until(() => document.querySelector('.reports-dialog[open]'), 'report library');
    const saved = await until(() => [...library.querySelectorAll('.report-list-item')].find(node => node.textContent.includes(title)), 'saved report row'); saved.click();
    const body = await until(() => library.querySelector('.report-frozen-body'), 'frozen body');
    check('frozen-boundary-and-decimal', !!body.querySelector('[data-test-analysis-boundary="test-grounding@1"]') && body.textContent.includes('38.00'));
    check('frozen-report-no-inference-section', !body.querySelector('.ai-claim.inference'));
    library.querySelector('[aria-label="关闭报告库"]').click();
    const topbar = document.querySelector('.topbar');
    const connection = topbar.querySelector('.connection');
    check('full-connection-label', connection.textContent.includes('API 已连接') && getComputedStyle(connection).whiteSpace === (innerWidth <= 767 ? 'nowrap' : 'normal'));
    const controls = [...topbar.querySelectorAll('button')].filter(node => node.getBoundingClientRect().width > 0);
    const rect = node => { const r = node.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; };
    const boxes = controls.map(rect);
    check('topbar-controls-visible-without-overlap', boxes.every(box => box.left >= 0 && box.right <= innerWidth + 1)
      && boxes.every((box, index) => boxes.slice(index + 1).every(other => box.right <= other.left + 0.5 || other.right <= box.left + 0.5 || box.bottom <= other.top + 0.5 || other.bottom <= box.top + 0.5)), boxes);
    if (innerWidth <= 767) {
      check('mobile-touch-targets', boxes.every(box => box.height >= 44 && box.width >= 44), boxes);
      check('mobile-header-two-rows', rect(topbar.querySelector('.breadcrumb')).bottom <= rect(topbar.querySelector('.topbar-actions')).top + 0.5);
    }
    check('no-page-horizontal-overflow', document.documentElement.scrollWidth <= innerWidth + 1, document.documentElement.scrollWidth);
    output.layout = { topbar: rect(topbar), connection: rect(connection), controls: boxes };
    output.done = true; output.outcome = 'passed';
  } catch (cause) { output.done = true; output.outcome = 'failed'; output.error = String(cause); }
  return output;
})();
