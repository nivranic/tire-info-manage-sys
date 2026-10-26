/* Actual React controls; synthetic upstream, controlled response loss/corruption. */
(async () => {
  const records = [];
  const output = { schema: 'r72-private-ui-qa@1', records, outcome: 'running', done: false,
    viewport: { width: innerWidth, height: innerHeight }, real_http: true,
    synthetic_upstream_session: true, public_source_dns_tls_exercised: false };
  window.__materialUiQA = output;
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const pause = () => new Promise(resolve => setTimeout(resolve, 65));
  const until = async (read, name) => {
    for (let i = 0; i < 300; i++) { const value = read(); if (value) return value; await pause(); }
    throw new Error('UI timeout: ' + name);
  };
  const panel = () => document.querySelector('[data-testid=source-materials]');
  const button = (root, text) => [...root.querySelectorAll('button')].find(node => node.textContent.trim() === text);
  const input = (root, text) => [...root.querySelectorAll('label')]
    .find(label => label.querySelector(':scope > span')?.textContent.trim().startsWith(text))?.querySelector('input,select,textarea');
  const set = (node, value) => {
    if (!node) throw new Error('Labelled form control missing');
    const prototype = node instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(node, value);
    node.dispatchEvent(new Event('input', { bubbles: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const click = async node => { if (!node || node.disabled) throw new Error('UI control unavailable'); node.click(); await pause(); };
  const state = async () => (await fetch('/api/fixture/state', { credentials: 'include' })).json();
  const signIn = async who => {
    const credentials = window.__materialCredentials[who];
    await click(document.querySelector('.sidebar-foot'));
    const dialog = await until(() => document.querySelector('.account-dialog[open]'), 'account dialog');
    const exit = button(dialog, '退出登录');
    if (exit) await click(exit);
    await until(() => dialog.querySelector('input[type=password]'), 'login form');
    set(dialog.querySelector('input[autocomplete=username]'), credentials.username);
    set(dialog.querySelector('input[type=password]'), credentials.password);
    await pause();
    await click(dialog.querySelector('button[type=submit]'));
    await until(() => button(dialog, '退出登录'), 'signed-in account');
    await click([...dialog.querySelectorAll('button')].find(node => (node.getAttribute('aria-label') || '').includes('关闭')));
    await until(() => !document.querySelector('.account-dialog[open]'), 'account closed');
    await until(() => panel() && !panel().textContent.includes('正在重新确认账户'), 'source owner revalidated');
    await until(() => input(panel(), '固定 PDF 来源') && button(panel(), '预览来源与许可'), 'source catalogue ready');
  };
  const originalFetch = window.fetch;
  const originalCreate = URL.createObjectURL;
  try {
    check('api-precondition', window.__materialApiQA?.outcome === 'passed' && Boolean(window.__materialCredentials));
    location.hash = '#/sources';
    await until(() => panel(), 'source material panel');
    await signIn('author');
    const select = await until(() => input(panel(), '固定 PDF 来源'), 'fixed policy selector');
    set(select, 'qa-source');
    set(input(panel(), '捕获署名'), 'Synthetic React QA');
    await pause();
    check('policy-shows-declared-and-download-addresses', panel().textContent.includes('https://fixture.invalid/test')
      && panel().textContent.includes('https://source-fixture.invalid/begin'));
    check('policy-keeps-unknown-and-use-limits', panel().textContent.includes('日期未声明')
      && panel().textContent.includes('不授权模型使用或导出'));
    const beforePreview = await state();
    await click(button(panel(), '预览来源与许可'));
    await until(() => panel().querySelector('[aria-label="来源捕获预览"]'), 'preview');
    check('preview-has-explicit-rights-confirmation', button(panel(), '确认并捕获原件').disabled
      && Boolean(panel().querySelector('input[type=checkbox]')));
    set(input(panel(), '捕获署名'), 'Synthetic React QA revised');
    await pause();
    check('editing-clears-preview', !panel().querySelector('[aria-label="来源捕获预览"]'));
    await click(button(panel(), '预览来源与许可'));
    await until(() => panel().querySelector('[aria-label="来源捕获预览"]'), 'fresh preview');
    const afterPreview = await state();
    check('real-preview-does-not-download-or-save', afterPreview.upstream_requests.length === beforePreview.upstream_requests.length
      && afterPreview.counts.documents === beforePreview.counts.documents);
    await click(panel().querySelector('input[type=checkbox]'));

    let lost = false, posted = 0, lostKey = '', documentId = '';
    window.fetch = async (...args) => {
      const url = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
      const response = await originalFetch(...args);
      if (url.pathname.endsWith('/source-materials/captures') && args[1]?.method === 'POST') {
        posted++;
        const value = await response.clone().json();
        lostKey = JSON.parse(args[1].body).idempotency_key;
        documentId = value.document?.id || '';
        if (!lost && response.ok && value.state === 'succeeded') {
          lost = true;
          throw new TypeError('Synthetic QA response loss after a real successful server commit');
        }
      }
      return response;
    };
    const beforeCapture = await state();
    await click(button(panel(), '确认并捕获原件'));
    await until(() => button(panel(), '核对原捕获请求') && !button(panel(), '核对原捕获请求').disabled, 'unknown result retains UUID');
    check('response-loss-injected-after-commit', lost && Boolean(documentId) && posted === 1);
    check('unknown-request-retains-original-uuid', panel().textContent.includes(lostKey)
      && panel().textContent.includes('不会自动重新联网'));
    check('unknown-request-does-not-enable-hidden-retry', !button(panel(), '确认并捕获原件'));
    const afterCommit = await state();
    check('server-saved-exactly-one-document', afterCommit.counts.documents === beforeCapture.counts.documents + 1);
    const fetchesAfterCommit = afterCommit.upstream_requests.length;
    await signIn('viewer');
    check('account-switch-clears-private-pending', !panel().textContent.includes(lostKey)
      && !button(panel(), '核对原捕获请求'));
    check('viewer-cannot-start-capture', button(panel(), '预览来源与许可').disabled);
    await signIn('author');
    await until(() => button(panel(), '核对原捕获请求'), 'same-account pending restored');
    check('same-account-relogin-restores-original-key', panel().textContent.includes(lostKey));
    await click(button(panel(), '核对原捕获请求'));
    const result = await until(() => panel().querySelector('[aria-label="原捕获请求结果"] [aria-label="来源传输凭证"]'), 'lookup success receipt');
    check('lookup-reopens-same-document', result.textContent.includes(documentId));
    const afterLookup = await state();
    check('lookup-never-reposts-or-redownloads', posted === 1
      && afterLookup.upstream_requests.length === fetchesAfterCommit
      && afterLookup.counts.documents === afterCommit.counts.documents);
    check('receipt-separates-transport-and-content', result.textContent.includes('传输已观察')
      && result.textContent.includes('内容未核验') && result.textContent.includes('https://source-fixture.invalid/material.pdf'));
    check('receipt-exposes-hash-size-and-identity-encoding', result.textContent.includes(afterLookup.material_sha256)
      && result.textContent.includes('application/pdf') && result.textContent.includes('identity'));
    check('source-capture-does-not-claim-authentication', result.textContent.includes('未核验')
      && result.textContent.includes('关系来自配置声明'));
    const docs = await until(() => document.querySelector('.evidence-documents'), 'existing document panel');
    await until(() => docs.querySelectorAll('.quarantine-item').length === afterLookup.counts.documents, 'original list refreshed');
    check('original-list-refreshed-after-lookup', docs.querySelectorAll('.quarantine-item').length === afterLookup.counts.documents
      && afterLookup.counts.documents === beforeCapture.counts.documents + 1);

    let downloadObjects = 0;
    URL.createObjectURL = function (...args) { downloadObjects++; return originalCreate.apply(this, args); };
    let corruptOnce = true;
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      const url = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
      if (corruptOnce && url.pathname.endsWith('/documents/' + documentId + '/content')) {
        corruptOnce = false;
        const data = new Uint8Array(await response.arrayBuffer());
        data[data.length - 1] ^= 1;
        return new Response(data, { status: 200, headers: { 'Content-Type': 'application/pdf' } });
      }
      return response;
    };
    await click(button(result, '校验完整 SHA 与大小并下载来源原件'));
    await until(() => panel().textContent.includes('SHA-256 校验失败'), 'corrupted response rejected');
    check('corrupt-complete-download-not-published', downloadObjects === 0 && !corruptOnce);
    window.fetch = originalFetch;
    await click(button(result, '校验完整 SHA 与大小并下载来源原件'));
    await until(() => panel().textContent.includes('完整 SHA-256 与字节数已校验'), 'complete original verified');
    check('verified-download-initiated', downloadObjects === 1 && panel().textContent.includes('下载不证明已阅读'));

    for (const detail of result.querySelectorAll('details')) detail.open = true;
    check('frozen-rights-and-robots-reopen', result.textContent.includes('robots')
      && result.textContent.includes('HTTP 302') && result.textContent.includes('不授权模型使用或导出'));
    const historyRow = await until(() => [...panel().querySelectorAll('.source-material-history-row')]
      .find(row => row.textContent.includes(lostKey)), 'saved request history row');
    await click(button(historyRow, '查看捕获请求'));
    await until(() => panel().querySelector('[aria-label="原捕获请求结果"]')?.textContent.includes(documentId), 'history exact document');
    check('history-keeps-exact-document', panel().querySelector('[aria-label="原捕获请求结果"]').textContent.includes(lostKey));
    const manual = [...docs.querySelectorAll('.quarantine-item')]
      .find(row => row.querySelector('h3')?.textContent.includes('same bytes, manual upload'));
    check('manual-upload-row-precondition', Boolean(manual));
    await click(button(manual, '查看此原件的来源捕获凭证'));
    await until(() => manual.textContent.includes('没有来源捕获凭证'), 'manual upload remains unverified');
    check('same-bytes-no-source-retroactive-label', manual.textContent.includes('不会按相同字节追认来源'));
    const final = await state();
    check('ui-does-not-mutate-source-facts', final.counts.facts === beforeCapture.counts.facts
      && final.counts.snapshots === beforeCapture.counts.snapshots);
    check('private-guards-zero', Object.values(final.counters).every(n => n === 0));
    output.document_id = documentId;
    output.request_key = lostKey;
    output.done = true;
    output.outcome = 'passed';
  } catch (error) { output.outcome = 'failed'; output.done = true; output.error = String(error); }
  finally { window.fetch = originalFetch; URL.createObjectURL = originalCreate; }
  return output;
})()
