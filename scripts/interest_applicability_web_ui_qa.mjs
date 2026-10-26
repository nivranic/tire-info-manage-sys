/* Rendered production UI checks. Caller injects only public frozen references.
 * Authentication material is never accessed; no requests or responses are mocked.
 */
(async () => {
  const records = [];
  const check = (name, ok, detail = null) => {
    records.push({ name, passed: Boolean(ok), detail });
    if (!ok) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const until = async (read, label) => {
    const start = Date.now();
    while (Date.now() - start < 12000) {
      const value = read();
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 60));
    }
    throw new Error('UI did not reach ' + label);
  };
  const button = (root, label) => [...root.querySelectorAll('button')].find(item => item.textContent.trim() === label);
  const close = async () => {
    const dialog = document.querySelector('dialog[open]');
    if (dialog) {
      button(dialog, '关闭冻结证据').click();
      await until(() => !document.querySelector('dialog[open]'), 'closed evidence');
    }
  };
  const originalPayload = async (reader, reference) => until(() => {
    if (reader.querySelector('[role="alert"]')) throw new Error(reader.querySelector('[role="alert"]').textContent);
    return [...reader.querySelectorAll('pre')].map(pre => {
      try { return JSON.parse(pre.textContent); } catch { return null; }
    }).find(value => value?.record_id === reference.record_id && value?.kind === reference.kind);
  }, 'exact original record ' + reference.record_id);
  const open = async reference => {
    await close();
    const region = document.querySelector('[aria-label="兴趣关注与私人通知"]');
    const candidates = [...region.querySelectorAll('article.quarantine-item')].filter(item =>
      item.querySelector('h3')?.textContent.startsWith('适用性R状态 ·') && item.querySelector('.monitor-text')?.textContent.includes('人工处理适用性')).reverse();
    for (const article of candidates) {
      button(article, '重开通知冻结证据').click();
      const dialog = await until(() => document.querySelector('dialog[open]'), 'frozen evidence dialog');
      await until(() => dialog.querySelector('details.interest-evidence'), 'frozen evidence references');
      const entry = [...dialog.querySelectorAll('details.interest-evidence')].find(item => item.querySelector('summary')?.textContent.includes(reference.record_id));
      if (entry) {
        entry.querySelector('summary').click();
        return { dialog, reader: await until(() => entry.querySelector('.interest-original-record'), 'derived original reader') };
      }
      await close();
    }
    throw new Error('Missing rendered exact notification: ' + reference.record_id);
  };
  window.__interestApplicabilityUiQA = { records, done: false };
  try {
    const refs = window.__applicabilityExpectedReferences;
    check('ui:public-frozen-references-present', Boolean(refs?.firstRef && refs?.crossRef && refs?.manualRef));
    const region = await until(() => document.querySelector('[aria-label="兴趣关注与私人通知"]'), 'private interest region');
    const capabilities = region.querySelector('details.interest-capabilities');
    if (!capabilities.open) capabilities.querySelector('summary').click();
    check('ui:derived-domain-human-explanation', capabilities.textContent.includes('人工处理适用性')
      && /待复核|需要复核/.test(capabilities.textContent));
    capabilities.querySelector('summary').click();
    for (const spec of [
      { key: 'first', ref: refs.firstRef, before: { value: 300, depth: 7 }, after: { value: 300, depth: 8 }, effectiveBefore: 450, effectiveAfter: 300 },
      { key: 'equal', ref: refs.equalRef, before: { value: 300, depth: 9 }, after: { value: 0, depth: 9 }, effectiveBefore: 0, effectiveAfter: 0 },
      { key: 'cross', ref: refs.crossRef, before: { value: 320, depth: 10 }, after: { value: 100, depth: 9 }, effectiveBefore: 420, effectiveAfter: 100 },
    ]) {
      const { dialog, reader } = await open(spec.ref);
      check('ui:frozen-criteria:' + spec.key, dialog.textContent.includes('通知采用的兴趣原修订 #1')
        && dialog.querySelector('[aria-label="当时冻结的匹配条件"]')?.textContent.includes('265/40R20'));
      const effective = [...dialog.querySelectorAll('.interest-facts pre')].map(pre => JSON.parse(pre.textContent));
      check('ui:effective-facts-preserved:' + spec.key, effective.length === 2
        && effective[0].facts.utqg_treadwear === spec.effectiveBefore && effective[1].facts.utqg_treadwear === spec.effectiveAfter);
      button(reader, '按绑定版本重开原始记录').click();
      const original = await originalPayload(reader, spec.ref);
      check('ui:exact-derived-record:' + spec.key, original.fingerprint === spec.ref.fingerprint
        && original.revision === spec.ref.revision && original.record.action === 'invalidate');
      check('ui:derived-and-human-revisions-distinguished:' + spec.key, reader.textContent.includes('派生适用性修订 #')
        && reader.textContent.includes('原人工修订 #'));
      if (spec.key === 'first') {
        const target = button(reader, '重开原人工决定 #' + refs.manualRef.revision);
        check('ui:explicit-original-human-action', Boolean(target));
        target.click();
        const manual = await originalPayload(reader, refs.manualRef);
        check('ui:old-human450-not-new-source', manual.fingerprint === refs.manualRef.fingerprint && manual.record.after.value === 450);
      }
      if (spec.key === 'equal') check('ui:equal-value-is-not-fabricated-UTQG-change',
        effective[0].facts.utqg_treadwear === effective[1].facts.utqg_treadwear);
      if (spec.key === 'cross') check('ui:cross-query-and-actual-member-separation', original.record.binding.before.query_key !== original.record.binding.after.query_key
        && original.record.binding.after.fact_version > original.record.binding.after.snapshot_member_fact_version
        && original.record.binding.after.verification_status === 'not_modified');
      for (const side of ['before', 'after']) {
        const action = side === 'before' ? '重开适用性变化前完整来源原文' : '重开适用性变化后完整来源原文';
        const target = button(reader, action);
        check('ui:whole-source-button:' + spec.key + ':' + side, Boolean(target));
        target.click();
        const raw = await until(() => {
          if (reader.querySelector('[role="alert"]')) throw new Error(reader.querySelector('[role="alert"]').textContent);
          const heading = side === 'before' ? '变化前指定快照原文' : '变化后指定快照原文';
          const last = [...reader.querySelectorAll('pre')].at(-1)?.textContent || '';
          return [...reader.querySelectorAll('h4')].some(item => item.textContent === heading)
            && last.startsWith('Synthetic interest evidence ') ? last : null;
        }, 'complete source ' + spec.key + ':' + side);
        const body = JSON.parse(raw.slice(raw.indexOf('{')));
        check('ui:complete-old-source-body:' + spec.key + ':' + side,
          body.values['265/40R20'] === spec[side].value && body.depths['265/40R20'] === spec[side].depth);
      }
    }
    window.__interestApplicabilityUiQA = { records, done: true, viewport: { width: innerWidth, height: innerHeight },
      no_document_horizontal_overflow: document.documentElement.scrollWidth <= innerWidth };
  } catch (error) { window.__interestApplicabilityUiQA.error = String(error); }
  return window.__interestApplicabilityUiQA;
})();
