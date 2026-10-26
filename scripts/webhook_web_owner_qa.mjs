/* Delay an actual private HTTP operation response across owner invalidation. */
(async () => {
  const out = { schema: 'r78-private-owner-qa@1', records: [], done: false,
    synthetic_only: true, delayed_transport: 'real private GET response held in memory' };
  const nativeFetch = window.fetch;
  let held = false, release;
  const pause = (ms = 70) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, passed) => { out.records.push({ name, passed: !!passed }); if (!passed) throw new Error(name); };
  const until = async (read, label) => { const start = Date.now(); while (Date.now() - start < 20000) {
    const value = read(); if (value) return value; await pause();
  } throw new Error('timeout: ' + label); };
  try {
    const key = window.__r78OwnerRecoveryKey;
    if (!key) throw new Error('prior actual operation key required');
    const input = document.querySelector('[aria-label="Webhook操作UUID"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, key);
    input.dispatchEvent(new Event('input', { bubbles: true })); await pause();
    window.fetch = async function (...args) {
      const response = await nativeFetch.apply(this, args);
      const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (!held && path.includes('/webhook-operations?')) {
        held = true;
        check('actual-private-get-completed-before-delay', response.ok
          && (await response.clone().json()).idempotency_key === key);
        await new Promise(resolve => { release = resolve; });
      }
      return response;
    };
    document.querySelector('[data-testid="webhooks-recover"]').click();
    await until(() => held && release, 'actual GET held');
    window.dispatchEvent(new Event('tire-session-unavailable'));
    await until(() => !document.querySelector('[data-testid="webhooks-panel"]'), 'private panel cleared');
    check('owner-loss-clears-private-webhook-tree', !document.querySelector('[data-testid="webhook-operation"]')
      && !document.querySelector('[data-testid="webhook-detail"]'));
    release(); await pause(250);
    check('late-http-cannot-restore-old-owner-receipt', !document.querySelector('[data-testid="webhook-operation"]'));
    window.fetch = nativeFetch;
    window.dispatchEvent(new Event('tire-session-revalidate'));
    await until(() => document.querySelector('[data-testid="webhooks-panel"]'), 'revalidated panel');
    check('new-owner-epoch-has-no-old-private-detail', !document.querySelector('[data-testid="webhook-operation"]')
      && !document.querySelector('[data-testid="webhook-detail"]'));
    const state = await (await nativeFetch('/api/fixture/state', { credentials: 'include' })).json();
    check('owner-delay-never-calls-external-receiver', state.controlled_receiver_calls === 0
      && state.real_webhook_receivers === 0 && state.real_provider_calls === 0);
    out.done = true; out.passed = out.records.length;
  } catch (error) { out.error = String(error); }
  finally { if (release) release(); window.fetch = nativeFetch; }
  return out;
})();
