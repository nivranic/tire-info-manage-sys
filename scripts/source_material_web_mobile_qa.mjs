/* Layout and history reading only; no mobile/native capture lifecycle claim. */
(async () => {
  const records = [];
  const out = { schema: 'r72-mobile-layout@1', viewport: { width: innerWidth, height: innerHeight }, records,
    scope: 'actual shared React layout and existing source receipt reading; not full mobile capture E2E or native device acceptance' };
  const check = (name, passed, detail = null) => {
    records.push({ name, passed: Boolean(passed), detail });
    if (!passed) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  try {
    const panel = document.querySelector('[data-testid=source-materials]');
    check('source-panel-exists', Boolean(panel));
    for (const detail of panel.querySelectorAll('details')) detail.open = true;
    panel.scrollIntoView({ block: 'start' });
    await new Promise(resolve => setTimeout(resolve, 120));
    const receipt = panel.querySelector('[aria-label="来源传输凭证"]');
    check('existing-exact-receipt-readable', Boolean(receipt)
      && receipt.textContent.includes(window.__materialUiQA.document_id));
    check('source-reference-distinct-from-download', panel.textContent.includes('https://fixture.invalid/test')
      && panel.textContent.includes('https://source-fixture.invalid/material.pdf')
      && panel.textContent.includes('关系来自配置声明'));
    check('transport-authenticity-boundary', receipt.textContent.includes('传输已观察')
      && receipt.textContent.includes('内容未核验'));
    check('full-sha-and-original-type-visible', receipt.textContent.includes(window.__materialFixtureHash)
      && receipt.textContent.includes('application/pdf') && receipt.textContent.includes('identity'));
    check('rights-not-expanded', panel.textContent.includes('不授权模型使用或导出'));
    check('unknown-publication-date-retained', panel.textContent.includes('日期未声明'));
    check('robots-and-redirect-detail-open', receipt.textContent.includes('HTTP 302')
      && receipt.textContent.includes('robots SHA-256'));
    check('no-arbitrary-url-input', !panel.querySelector('input[type=url]'));
    const sizes = [...panel.querySelectorAll('button,input:not([type=checkbox]),select')]
      .filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden')
      .map(node => ({ label: node.textContent.trim().slice(0, 70) || node.getAttribute('placeholder') || node.tagName,
        height: node.getBoundingClientRect().height }));
    out.control_sizes = sizes;
    check('visible-form-controls-at-least-44px', sizes.length > 0 && sizes.every(row => row.height >= 43.9));
    const rectangle = panel.getBoundingClientRect();
    check('source-panel-fits-viewport', rectangle.left >= -1 && rectangle.right <= innerWidth + 1,
      { left: rectangle.left, right: rectangle.right, viewport: innerWidth });
    check('no-document-horizontal-overflow', document.documentElement.scrollWidth <= innerWidth + 1,
      { scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth });
    out.outcome = 'passed';
  } catch (error) { out.outcome = 'failed'; out.error = String(error); }
  return out;
})()
