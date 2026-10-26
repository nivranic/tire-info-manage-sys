/* Real React controls + private production HTTP; synthetic PDF/identity only. */
(async () => {
  const records = [];
  const output = { schema: 'test-sku-bridge-private-ui-qa@1', records, done: false,
    viewport: { width: innerWidth, height: innerHeight }, real_http: true,
    material: 'project-authored synthetic PDF; not a real source Golden' };
  window.__bridgeUiQA = output;
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const pause = () => new Promise(resolve => setTimeout(resolve, 65));
  const until = async (read, name) => {
    for (let index = 0; index < 300; index++) { const value = read(); if (value) return value; await pause(); }
    throw new Error('UI timeout: ' + name);
  };
  const button = (root, text) => [...root.querySelectorAll('button')].find(node => node.textContent.trim() === text);
  const labelInput = (root, text) => [...root.querySelectorAll('label')]
    .find(label => label.querySelector(':scope > span')?.textContent.trim().startsWith(text))?.querySelector('input,textarea,select');
  const set = (node, value) => {
    if (!node) throw new Error('Expected labelled form control');
    const prototype = node instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(node, String(value));
    node.dispatchEvent(new Event('input', { bubbles: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const click = async node => { if (!node || node.disabled) throw new Error('UI control unavailable'); node.click(); await pause(); };
  const state = async () => (await fetch('/api/fixture/state', { credentials: 'include' })).json();
  const req = async (path, method = 'GET', body) => {
    const response = await fetch('/api' + path, { method, credentials: 'include',
      headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    return { status: response.status, body: await response.json() };
  };
  const signIn = async actor => {
    const credentials = window.__bridgeCredentials[actor];
    await click(document.querySelector('.sidebar-foot'));
    const dialog = await until(() => document.querySelector('.account-dialog[open]'), 'account dialog');
    const signout = button(dialog, '退出登录');
    if (signout) await click(signout);
    await until(() => dialog.querySelector('input[type=password]'), 'login form');
    set(dialog.querySelector('input[autocomplete=username]'), credentials.username);
    set(dialog.querySelector('input[type=password]'), credentials.password);
    await pause();
    await click(dialog.querySelector('button[type=submit]'));
    await until(() => button(dialog, '退出登录'), 'signed-in account');
    await click(dialog.querySelector('.dialog-close') || [...dialog.querySelectorAll('button')]
      .find(node => (node.getAttribute('aria-label') || '').includes('关闭')));
    await until(() => !document.querySelector('.account-dialog[open]'), 'account dialog closed');
  };
  const openMain = async () => {
    location.hash = '#/compare';
    const events = await until(() => document.querySelector('.test-events'), 'test events');
    let detail = events.querySelector('.test-event-detail');
    if (!detail?.textContent.includes('R71 合成验收 · 测试对象与精确 SKU')) {
      const card = await until(() => [...events.querySelectorAll('.quarantine-item')]
        .find(item => item.querySelector('h3')?.textContent === 'R71 合成验收 · 测试对象与精确 SKU'), 'main fixture event');
      await click(button(card, '核对本场成绩'));
      detail = await until(() => events.querySelector('.test-event-detail'), 'event detail');
    }
    const workspace = await until(() => detail.querySelector('.test-sku-links'), 'bridge workspace');
    await click(await until(() => workspace.querySelector('.bridge-participants article button:not(:disabled)'), 'participant action'));
    return until(() => workspace.querySelector('.bridge-editor'), 'bridge editor');
  };
  const fillConfirmation = async (editor, reason) => {
    const preview = editor.querySelector('.bridge-preview');
    set(labelInput(preview, '本次处理署名'), 'Synthetic UI reviewer');
    set(labelInput(preview, '本次理由'), reason);
    await pause();
    await click(labelInput(preview, '确认固定测试修订'));
  };
  try {
    check('api-precondition', window.__bridgeApiQA?.outcome === 'passed' && !!window.__bridgeCredentials);
    const fixture = await state();
    await signIn('author');
    let editor = await openMain();
    check('new-explicit-snapshot-required', editor.querySelector('.bridge-snapshot select') === null
      && editor.querySelector('.bridge-preview-button').disabled);
    await click(await until(() => [...editor.querySelectorAll('.bridge-candidates button')]
      .find(node => node.textContent.includes('SYNTHETIC-001')), 'exact SKU candidate'));
    const snapshot = await until(() => [...(editor.querySelector('.bridge-snapshot select')?.options || [])]
      .find(option => option.value.includes(fixture.tire_snapshot_id) && option.value.includes(fixture.fact_version_id)), 'exact snapshot and fact option');
    set(editor.querySelector('.bridge-snapshot select'), snapshot.value);
    set(labelInput(editor, '本次证据等级'), 'source_explicit_identifiers_in_supplied_material');
    set(labelInput(editor, '添加已有 PDF 材料'), window.__bridgeApiQA.material_id);
    const material = await until(() => editor.querySelector('.bridge-material-editor'), 'material editor');
    for (const [index, locator] of [...material.querySelectorAll('fieldset.bridge-locator')].entries()) {
      set(labelInput(locator, '页内区域'), index === 0 ? 'Synthetic event heading' : 'Synthetic participant heading');
      set(labelInput(locator, '对照短引文'), index === 0 ? 'R71 Synthetic same-event test' : 'Participant a: Synthetic Tire');
    }
    set(labelInput(material, '声明的权利人'), 'Project fixture author');
    set(labelInput(material, '保存原件、工作区重开'), 'Project-authored synthetic material, authorized for local workflow QA only.');
    await pause();
    await click(labelInput(material, '明确声明三项权限'));
    const assertions = [...editor.querySelectorAll('.bridge-assertion')];
    check('material-values-not-copied-from-sku', assertions.every(node => !node.querySelector('input[type=checkbox]').checked));
    const values = Object.entries(fixture.identity);
    check('all-actual-identity-fields-visible', assertions.length === values.length);
    for (let index = 0; index < values.length; index++) {
      const [field, value] = values[index];
      const row = assertions[index];
      await click(row.querySelector('summary'));
      await click(row.querySelector('input[type=checkbox]'));
      const control = labelInput(row, '材料所载原值');
      check('empty-source-value-' + field, control.value === '');
      set(control, value);
      const locator = row.querySelector('fieldset.bridge-locator');
      set(labelInput(locator, '页内区域'), 'Synthetic identity row ' + field);
      set(labelInput(locator, '对照短引文'), field + ': ' + JSON.stringify(value));
      await pause();
    }
    await click(editor.querySelector('.bridge-preview-button'));
    let preview = await until(() => editor.querySelector('.bridge-preview'), 'full preview');
    check('three-sided-evidence-rendered', preview.textContent.includes('完整场次、原参测对象')
      && preview.textContent.includes('完整原成员') && preview.textContent.includes('材料元数据'));
    check('explicit-unknown-source-boundary', preview.textContent.includes('未经来源在线核验')
      && preview.textContent.includes('双账户不证明两个真人独立'));
    check('all-identity-comparisons-match', !preview.querySelector('.bridge-check-row.conflict')
      && !preview.querySelector('.bridge-check-row.unknown'));
    check('exact-original-version-preview', preview.textContent.includes(fixture.tire_snapshot_id)
      && preview.textContent.includes(fixture.fact_version_id) && preview.textContent.includes(fixture.event_revision_id));
    const initialSourceValue = labelInput(assertions[0], '材料所载原值');
    set(initialSourceValue, String(values[0][1]) + ' '); await pause();
    check('editing-invalidates-preview', !editor.querySelector('.bridge-preview'));
    set(initialSourceValue, values[0][1]); await pause();
    await click(editor.querySelector('.bridge-preview-button'));
    preview = await until(() => editor.querySelector('.bridge-preview'), 'fresh preview after edit');
    await fillConfirmation(editor, 'Project-authored synthetic declaration; no real test provenance claim.');
    const beforeWrite = (await state()).counts.link_revisions;
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      if (String(args[0]).endsWith('/v1/test-sku-links/decisions') && args[1]?.method === 'POST') {
        window.fetch = originalFetch;
        throw new TypeError('Synthetic response loss after committed private HTTP operation');
      }
      return response;
    };
    await click(preview.querySelector('button[type=submit]'));
    await until(() => button(editor, '核对同一次操作'), 'ambiguous operation recovery');
    check('ambiguous-write-stays-locked', editor.textContent.includes('固定 UUID')
      && !editor.querySelector('.bridge-preview button[type=submit]:not(:disabled)'));
    await click(button(editor, '核对同一次操作'));
    await until(() => editor.querySelector('.snapshot-banner')?.textContent.includes('修订 #1'), 'exact create replay receipt');
    check('response-loss-does-not-duplicate', (await state()).counts.link_revisions === beforeWrite + 1);
    check('self-review-ui-unavailable', !editor.querySelector('.bridge-actions')?.textContent.includes('确认双账户人工复核')
      && editor.textContent.includes('审核须换另一管理员账户'));
    const link = (await req('/v1/test-sku-links?mode=history&event_id=' + fixture.event_id)).body.items[0];
    output.ui_link_id = link.id;
    await signIn('reviewer');
    editor = await openMain();
    await click(button(editor.querySelector('.bridge-actions'), '确认双账户人工复核'));
    await click(editor.querySelector('.bridge-preview-button'));
    preview = await until(() => editor.querySelector('.bridge-preview'), 'review preview');
    const readConfirmation = labelInput(preview, '我已自行完整打开');
    check('read-confirmation-requires-own-download', readConfirmation.disabled && !readConfirmation.checked);
    await click(button(preview.querySelector('.bridge-material-card'), '校验并下载完整原件'));
    await until(() => !readConfirmation.disabled, 'SHA-verified own download');
    check('download-does-not-auto-attest-reading', !readConfirmation.checked);
    await click(readConfirmation);
    await fillConfirmation(editor, 'Different synthetic admin account manually confirms the supplied PDF identifiers.');
    await click(preview.querySelector('button[type=submit]'));
    await until(() => editor.querySelector('.snapshot-banner')?.textContent.includes('已人工复核'), 'reviewed state');
    check('conditional-review-wording', editor.textContent.includes('仅条件化人工转录关联')
      && editor.textContent.includes('未在线核验'));
    await click(editor.querySelector('.bridge-history summary'));
    await click(button(editor.querySelector('.bridge-history'), '查看精确修订 #1'));
    await until(() => editor.textContent.includes('正在查看明确选择的历史修订 #1'), 'exact history');
    check('history-not-rewritten-or-editable', editor.querySelector('.snapshot-banner').textContent.includes('声明待复核')
      && !editor.querySelector('.bridge-declaration'));
    await click(button(editor, '返回当前关系'));
    await until(() => editor.querySelector('.snapshot-banner')?.textContent.includes('已人工复核'), 'current review restored');
    const event = (await req('/v1/test-events/' + fixture.event_id + '?mode=history')).body;
    const revoked = await req('/v1/test-events/' + fixture.event_id + '/state', 'POST', {
      expected_revision: event.revision, action: 'revoke', operator: 'Synthetic browser QA',
      reason: 'Verify current eligibility changes without rewriting old evidence' });
    check('real-event-transition', revoked.status === 200);
    await click(button(editor, '重新读取当前关系'));
    await until(() => editor.querySelector('.snapshot-banner')?.textContent.includes('需重新复核'), 'current stale explanation');
    check('stale-evidence-remains-readable', editor.textContent.includes('原声明不能自动沿用')
      && editor.textContent.includes('适用性未成立') && editor.textContent.includes('完整场次、原参测对象'));
    check('r70-fact-selector-remains', !!button(document.querySelector('.test-event-detail'), 'AI 摘录本场事实'));
    check('desktop-no-page-overflow', document.documentElement.scrollWidth <= innerWidth);
    check('private-guards-remain-zero', Object.values((await state()).counters).every(value => value === 0));
    output.done = true; output.outcome = 'passed';
  } catch (error) { output.outcome = 'failed'; output.error = String(error); }
  return output;
})()
