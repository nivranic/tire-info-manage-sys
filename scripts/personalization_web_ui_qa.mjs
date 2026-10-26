/* Real rendered UI; delayed transport resolves actual HTTP responses without fixtures. */
(async () => {
  const records = [];
  const check = (name, ok, detail = null) => {
    records.push({ name, passed: Boolean(ok), detail });
    if (!ok) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const until = async (read, label) => {
    const started = Date.now();
    while (Date.now() - started < 15000) {
      const result = read();
      if (result) return result;
      await new Promise(resolve => setTimeout(resolve, 70));
    }
    throw new Error('UI timeout: ' + label);
  };
  const button = (root, label) => [...root.querySelectorAll('button')].find(row => row.textContent.includes(label));
  const select = (node, value) => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(node, value);
    node.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const region = id => document.getElementById(id)?.closest('section');
  const nativeFetch = window.fetch;
  let emptyScanPages = 0;
  window.fetch = async function (...args) {
    const response = await nativeFetch.apply(this, args);
    const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    if (path.includes('/v1/personal-feed/preview') && response.ok) {
      const value = await response.clone().json();
      if (value.scanned_count > 0 && value.items.length === 0 && value.next_cursor) emptyScanPages++;
    }
    return response;
  };
  window.__personalizationUiQA = { records, done: false };
  try {
    if (location.hash !== '#/home') location.hash = '#/home';
    const feed = await until(() => region('personal-feed-title')?.querySelector('.home-counts') && region('personal-feed-title'), 'home feed');
    check('ui:standalone-home-route', location.hash === '#/home' && document.querySelector('.personalized-home'));
    check('ui:history-not-notification', feed.textContent.includes('包含创建兴趣前的记录') && feed.textContent.includes('不是已投递通知'));
    select(feed.querySelector('.home-filters select'), 'tire');
    await until(() => feed.querySelector('.home-counts') && feed.querySelector('.home-filters select').value === 'tire', 'domain read');
    select(feed.querySelectorAll('.home-filters select')[1], '1');
    await until(() => feed.querySelector('.home-counts')?.textContent.includes('已核对 1 条'), 'scan one');
    check('ui:scan-budget-exposed', feed.querySelector('.home-counts').textContent.includes('已核对 1 条'));
    let emptyPageObserved = feed.textContent.includes('当前这段历史没有命中');
    for (let index = 0; index < 30; index++) {
      const more = button(feed, '继续读取下一段历史');
      if (!more) break;
      await until(() => !more.disabled, 'next enabled');
      const before = feed.querySelector('.home-counts').textContent;
      more.click();
      await until(() => feed.querySelector('.home-counts')?.textContent !== before && !feed.querySelector('button.home-more:disabled'), 'next page completion');
      emptyPageObserved ||= feed.textContent.includes('当前这段历史没有命中');
    }
    check('ui:continued-to-history-end', feed.textContent.includes('已到当前本地记录范围的末尾'));
    check('ui:actual-empty-scan-page-continued', emptyScanPages > 0, emptyScanPages);
    const cards = [...feed.querySelectorAll('[data-feed-event-id]')];
    check('ui:no-duplicate-event-cards', cards.length >= 2 && new Set(cards.map(row => row.dataset.feedEventId)).size === cards.length, cards.length);
    check('ui:all-current-interest-reasons', cards.some(row => row.textContent.includes('第二关注') && row.textContent.includes('我的历史品牌')));
    check('ui:hostile-label-is-text', feed.textContent.includes('<img src=x onerror=alert(1)>') && !feed.querySelector('img[src="x"]'));
    button(cards[0], '核对匹配理由与冻结依据').click();
    const details = await until(() => cards[0].querySelector('.home-frozen'), 'frozen reasons');
    check('ui:current-interest-revision-explicit', details.textContent.includes('兴趣指纹') && details.querySelector('select').options.length >= 2);
    check('ui:original-before-after-visible', details.querySelectorAll('.interest-facts pre').length === 2);
    details.querySelector('.interest-evidence > summary').click();
    const readerButton = await until(() => button(details, '按绑定版本重开原始记录'), 'frozen reader expanded');
    check('ui:existing-exact-reader-reused', Boolean(readerButton));
    readerButton.click();
    await until(() => details.querySelector('.interest-evidence pre'), 'exact source read');
    check('ui:old-evidence-read-no-alert', !details.querySelector('[role="alert"]'));
    const candidate = await until(() => region('fitment-candidates-title')?.querySelector('select option[value]:not([value=""])') && region('fitment-candidates-title'), 'vehicle catalog');
    check('ui:recommendation-gap-visible-before-action', candidate.textContent.includes('性能推荐尚未完成'));
    const snapshotSelect = candidate.querySelector('select');
    select(snapshotSelect, [...snapshotSelect.options].find(row => row.value).value);
    await until(() => !candidate.querySelectorAll('select')[1].disabled, 'vehicle detail');
    const trim = candidate.querySelectorAll('select')[1];
    select(trim, [...trim.options].find(row => row.value).value);
    await until(() => candidate.querySelectorAll('select')[2].options.length > 1, 'wheel options');
    const wheel = candidate.querySelectorAll('select')[2];
    select(wheel, [...wheel.options].find(row => row.value).value);
    select(candidate.querySelectorAll('select')[3], 'rear');
    button(candidate, '核对所选轴位候选').click();
    await until(() => candidate.querySelector('[data-candidate-variant-id]') || candidate.querySelector('[role="alert"]'), 'reviewed rear candidate');
    check('ui:rear-exact-candidate', candidate.querySelectorAll('[data-candidate-variant-id]').length === 1 && !candidate.querySelector('[role="alert"]'));
    check('ui:seven-explicit-performance-gaps', candidate.querySelectorAll('.home-focus small').length === 7
      && candidate.textContent.includes('无性能评分') && candidate.textContent.includes('不等于官方原配认证'));
    const relation = candidate.querySelector('.home-relation');
    relation.querySelector('summary').click();
    check('ui:relation-unknowns-not-zero-filled', relation.textContent.includes('仍有未知检查') && relation.textContent.includes('未知没有变成已证实'));
    relation.querySelector('.interest-evidence > summary').click();
    (await until(() => button(relation, '按绑定版本重开原始记录'), 'relation reader expanded')).click();
    await until(() => relation.querySelector('.interest-evidence pre') || relation.querySelector('[role="alert"]'), 'bound relation read');
    check('ui:exact-relation-reopened', !relation.querySelector('[role="alert"]') && Boolean(relation.querySelector('.interest-evidence pre')));
    select(candidate.querySelectorAll('select')[3], 'front');
    await until(() => !candidate.querySelector('[data-candidate-variant-id]'), 'old axle result cleared');
    check('ui:selection-change-clears-old-candidate', !candidate.querySelector('[data-candidate-variant-id]'));
    button(candidate, '核对所选轴位候选').click();
    await until(() => candidate.querySelector('.home-candidate-result') || candidate.querySelector('[role="alert"]'), 'front empty result');
    check('ui:front-real-empty-no-size-inference', !candidate.querySelector('[data-candidate-variant-id]') && candidate.textContent.includes('没有通过当前门禁的已审候选'));

    const originalFetch = window.fetch;
    let held = false;
    let release;
    window.fetch = async function (...args) {
      const response = await originalFetch.apply(this, args);
      const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (!held && path.includes('/v1/personal-feed/preview')) {
        held = true;
        await new Promise(resolve => { release = resolve; });
      }
      return response;
    };
    try {
      button(feed, '从头重新读取').click();
      await until(() => held && release, 'held actual HTTP response');
      window.dispatchEvent(new Event('tire-session-unavailable'));
      await until(() => !document.querySelector('.personalized-home'), 'private owner fence');
      check('ui:owner-unavailable-clears-private-tree', document.body.textContent.includes('正在确认当前账户归属'));
      release();
      await new Promise(resolve => setTimeout(resolve, 200));
      check('ui:late-real-response-not-restored', !document.querySelector('.personalized-home'));
    } finally {
      if (release) release();
      window.fetch = originalFetch;
      window.dispatchEvent(new Event('tire-session-revalidate'));
    }
    await until(() => region('personal-feed-title')?.querySelector('.home-counts'), 'fresh owner confirmed');
    check('ui:fresh-owner-reloads-current-history', Boolean(document.querySelector('.personalized-home')));
    check('ui:seven-navigation-items', [...document.querySelectorAll('.nav-item')].filter(row => row.getAttribute('aria-current') !== null || row.textContent).length >= 7);
    check('ui:no-document-horizontal-overflow', document.documentElement.scrollWidth <= innerWidth,
      { viewport: innerWidth, document: document.documentElement.scrollWidth });
    window.__personalizationUiQA = { records, done: true, passed: records.filter(row => row.passed).length,
      viewport: { width: innerWidth, height: innerHeight }, empty_scan_page_observed: emptyPageObserved,
      actual_empty_scan_pages_with_cursor: emptyScanPages,
      delayed_transport: 'actual HTTP response; synthetic session-unavailable event; no response mock' };
  } catch (error) { window.__personalizationUiQA.error = String(error); }
  finally { window.fetch = nativeFetch; }
  return window.__personalizationUiQA;
})();
