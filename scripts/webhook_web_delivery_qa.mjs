/* Actual ASGI/Worker queue with a controlled 400 -> 204 receiver boundary. */
(async () => {
  const out = { schema: 'r78-private-delivery-ui-qa@1', records: [], done: false,
    synthetic_only: true, real_webhook_receivers: 0, receiver_mode: 'controlled_400_then_204' };
  const pause = (ms = 70) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, passed) => { out.records.push({ name, passed: !!passed }); if (!passed) throw new Error(name); };
  const until = async (read, label) => { const start = Date.now(); while (Date.now() - start < 20000) {
    const value = read(); if (value) return value; await pause();
  } throw new Error('timeout: ' + label); };
  const request = async (path, body) => {
    const response = await fetch('/api' + path, { credentials: 'include',
      ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
    if (!response.ok) throw new Error('private-http-' + response.status);
    return response.json();
  };
  const panel = () => document.querySelector('[data-testid="webhooks-panel"]');
  const node = id => panel()?.querySelector('[data-testid="' + id + '"]');
  const click = async target => { if (!target || target.disabled) throw new Error('expected enabled control'); target.click(); await pause(); };
  const input = async (target, value) => {
    const type = target.tagName === 'SELECT' ? HTMLSelectElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(type.prototype, 'value').set.call(target, value);
    target.dispatchEvent(new Event(target.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); await pause();
  };
  const originalFetch = window.fetch;
  let operation = null;
  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);
    const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    if (path.includes('/v1/webhooks') && String(args[1]?.method || 'GET').toUpperCase() !== 'GET' && response.ok)
      operation = await response.clone().json();
    return response;
  };
  try {
    const initial = await request('/fixture/state');
    await click(node('webhooks-create')); await until(() => node('webhooks-editor'), 'editor');
    await input(panel().querySelector('[aria-label="Webhook订阅名称"]'), '合成失败重试接收-' + Date.now());
    await input(panel().querySelector('[aria-label="Webhook受管理目标"]'), 'synthetic-receiver');
    await click(panel().querySelector('[data-webhook-channel="tire_monitor"]'));
    await click(node('webhooks-save')); await until(() => operation?.action === 'create', 'create');
    const id = operation.resource_id;
    await until(() => node('webhooks-resume-consent'), 'paused detail');
    await click(node('webhooks-resume-consent')); operation = null; await click(node('webhooks-resume'));
    await until(() => operation?.action === 'resume' && !node('webhooks-pause')?.disabled, 'resume');
    await request('/fixture/emit', {});
    const dispatch = await request('/fixture/dispatch?status=400', {});
    check('real-worker-dispatched-one-controlled-request', dispatch.jobs === 1 && dispatch.results[0].finalized);
    const deliveryId = dispatch.results[0].id;
    await click(node('webhooks-refresh'));
    await until(() => panel().querySelector('[data-webhook-delivery-id="' + deliveryId + '"]'), 'queued delivery');
    await click(panel().querySelector('[data-webhook-delivery-id="' + deliveryId + '"]'));
    await until(() => node('webhook-delivery')?.textContent.includes('HTTP 400'), 'terminal 400');
    const first = await request('/v1/webhooks/' + id + '/deliveries/' + deliveryId + '?mode=history');
    check('400-terminal-failure-shows-one-attempt', first.state === 'failed' && first.attempts === 1
      && first.attempt_history.length === 1 && first.attempt_history[0].http_status === 400);
    check('retry-waits-for-explicit-user-confirmation', node('webhooks-retry').disabled);
    await click(node('webhooks-delivery-consent')); operation = null; await click(node('webhooks-retry'));
    await until(() => operation?.action === 'retry', 'manual retry');
    check('retry-keeps-id-body-and-number-while-adding-five-budget', operation.resource_id === deliveryId
      && operation.response.attempts === 1 && operation.response.max_attempts === 10
      && operation.response.body_sha256 === first.body_sha256);
    await pause(1100);
    const success = await request('/fixture/dispatch?status=204', {});
    check('second-real-worker-claim-is-same-delivery', success.jobs === 1 && success.results[0].id === deliveryId);
    await click(node('webhooks-refresh'));
    await until(() => node('webhook-delivery')?.textContent.includes('HTTP 204'), 'successful attempt');
    const final = await request('/v1/webhooks/' + id + '/deliveries/' + deliveryId + '?mode=history');
    check('204-completion-retains-both-attempts', final.state === 'delivered' && final.attempts === 2
      && final.attempt_history.map(a => a.number).join(',') === '1,2'
      && final.attempt_history.map(a => a.http_status).join(',') === '400,204'
      && final.body_sha256 === first.body_sha256);
    check('delivered-disables-retry-and-cancel', node('webhooks-retry').disabled && node('webhooks-cancel').disabled);
    const state = await request('/fixture/state');
    check('independent-receiver-verified-both-production-signatures', state.signature_checks === initial.signature_checks + 2
      && state.controlled_receiver_calls === initial.controlled_receiver_calls + 2
      && state.real_webhook_receivers === 0 && state.real_provider_calls === 0);
    check('delivery-detail-fits-current-viewport', document.documentElement.scrollWidth <= innerWidth);
    out.done = true; out.passed = out.records.length;
  } catch (error) { out.error = String(error); }
  finally { window.fetch = originalFetch; }
  return out;
})();
