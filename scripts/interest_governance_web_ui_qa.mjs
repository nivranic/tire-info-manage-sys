/* Real rendered UI checks after private production API QA. The caller supplies
 * only public frozen references as window.__governanceExpectedReferences.
 * No requests are mocked and no authentication material is read or recorded.
 */
(async () => {
  const records = [];
  const check = (name, ok, detail = null) => {
    records.push({ name, passed: Boolean(ok), detail });
    if (!ok) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const until = async (read, label) => {
    const started = Date.now();
    while (Date.now() - started < 12000) {
      const value = read();
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 60));
    }
    throw new Error('UI did not reach ' + label);
  };
  const button = (root, text) => [...root.querySelectorAll('button')].find(item => item.textContent.trim() === text);
  const closeDialog = async () => {
    const dialog = document.querySelector('dialog[open]');
    if (dialog) {
      button(dialog, '关闭冻结证据').click();
      await until(() => !document.querySelector('dialog[open]'), 'closed dialog');
    }
  };
  const openNotice = async (name, domain, ref) => {
    await closeDialog();
    const region = document.querySelector('[aria-label="兴趣关注与私人通知"]');
    const article = [...region.querySelectorAll('article.quarantine-item')].filter(item =>
      item.querySelector('h3')?.textContent.startsWith(name + ' ·') && item.querySelector('.monitor-text')?.textContent.includes(domain)).at(-1);
    if (!article) throw new Error('Missing rendered notice: ' + domain);
    button(article, '重开通知冻结证据').click();
    const dialog = await until(() => document.querySelector('dialog[open]'), 'frozen evidence');
    const entry = await until(() => [...dialog.querySelectorAll('details.interest-evidence')].find(item =>
      item.querySelector('summary')?.textContent.includes(ref.record_id)), 'exact frozen reference');
    entry.querySelector('summary').click();
    const reader = await until(() => entry.querySelector('.interest-original-record'), 'original reader');
    return { dialog, entry, reader };
  };
  const readOriginal = async (reader, ref) => {
    button(reader, '按绑定版本重开原始记录').click();
    return until(() => {
      if (reader.querySelector('[role="alert"]')) throw new Error(reader.querySelector('[role="alert"]').textContent);
      const pre = reader.querySelector('pre');
      if (!pre) return null;
      try { const value = JSON.parse(pre.textContent); return value.record_id === ref.record_id ? value : null; }
      catch { return null; }
    }, 'exact original payload');
  };
  window.__interestGovernanceUiQA = { records, done: false };
  try {
    const refs = window.__governanceExpectedReferences;
    check('ui:has-public-frozen-references', Boolean(refs?.manualRef && refs?.catalogRef));
    await closeDialog();
    const region = document.querySelector('[aria-label="兴趣关注与私人通知"]');
    check('ui:private-interest-section-rendered', Boolean(region));
    const capabilities = region.querySelector('details.interest-capabilities');
    if (!capabilities.open) capabilities.querySelector('summary').click();
    await until(() => capabilities.open, 'capabilities');
    check('ui:four-governance-domains-have-human-labels', ['手工参数纠错', 'SKU 本地状态', '身份映射决定', '来源目录成员'].every(text => capabilities.textContent.includes(text)));
    capabilities.querySelector('summary').click();
    for (const spec of [
      { name: '治理R完整条件', domain: '手工参数纠错', ref: refs.manualRef, action: 'manual_override' },
      { name: '治理R完整条件', domain: 'SKU 本地状态', ref: refs.lifecycleRef, action: 'revoke' },
      { name: '治理R完整条件', domain: '身份映射决定', ref: refs.identityRef, action: 'correct' },
      { name: '治理R目录', domain: '来源目录成员', ref: refs.catalogRef, action: 'removed' },
    ]) {
      const { dialog, reader } = await openNotice(spec.name, spec.domain, spec.ref);
      check('ui:frozen-criteria:' + spec.ref.kind, dialog.textContent.includes('通知采用的兴趣原修订 #1')
        && dialog.querySelector('[aria-label="当时冻结的匹配条件"]')?.textContent.includes('265/40R20'));
      const original = await readOriginal(reader, spec.ref);
      check('ui:exact-original:' + spec.ref.kind, original.fingerprint === spec.ref.fingerprint && original.record.action === spec.action
        && original.entity_id === spec.ref.entity_id && original.revision === spec.ref.revision);
      if (spec.ref.kind === 'tire_curation_revision') check('ui:old-manual-value-not-current-source', original.record.after.value === 450);
      if (spec.ref.kind === 'tire_lifecycle_event') check('ui:local-state-not-official-recall', dialog.textContent.includes('不表示官方召回'));
      if (spec.ref.kind === 'tire_identity_revision') check('ui:identity-is-local-mapping', dialog.textContent.includes('不自动改为目标 SKU'));
      if (spec.ref.kind === 'tire_catalog_revision') {
        check('ui:catalog-absence-not-SKU-revocation', dialog.textContent.includes('移出不表示 SKU 被撤销'));
        for (const side of ['before', 'after']) {
          const text = side === 'before' ? '重开目录变化前完整快照原文' : '重开目录变化后完整快照原文';
          const target = button(reader, text);
          check('ui:catalog-whole-resource-button:' + side, Boolean(target));
          target.click();
          const raw = await until(() => {
            if (reader.querySelector('[role="alert"]')) throw new Error(reader.querySelector('[role="alert"]').textContent);
            const all = [...reader.querySelectorAll('pre')];
            const last = all.at(-1)?.textContent || '';
            const expectedHeading = side === 'before' ? '变化前指定快照原文' : '变化后指定快照原文';
            return [...reader.querySelectorAll('h4')].some(item => item.textContent === expectedHeading)
              && last.startsWith('Synthetic interest evidence ') ? last : null;
          }, 'whole resource ' + side);
          const payload = JSON.parse(raw.slice(raw.indexOf('{')));
          check('ui:catalog-presence-proven-from-complete-old-body:' + side,
            payload.present.includes('265/40R20') === (side === 'before') && payload.values['265/40R20'] === 300);
        }
      }
    }
    window.__interestGovernanceUiQA = { records, done: true, viewport: { width: innerWidth, height: innerHeight },
      no_document_horizontal_overflow: document.documentElement.scrollWidth <= innerWidth };
  } catch (error) { window.__interestGovernanceUiQA.error = String(error); }
  return window.__interestGovernanceUiQA;
})();
