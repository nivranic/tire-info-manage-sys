/* Hold a genuine private GET response to exercise owner-epoch discard. */
(async () => {
  const output = { schema: 'r77-private-owner-qa@1', records: [], done: false,
    synthetic_only: true, delayed_transport: 'actual HTTP response held in browser memory' };
  const nativeFetch = window.fetch;
  let release, held = false;
  const pause = (ms = 75) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, passed) => { output.records.push({ name, passed: !!passed }); if (!passed) throw new Error(name); };
  const until = async (read, label) => { const start = Date.now(); while (Date.now() - start < 20000) { const value = read(); if (value) return value; await pause(); } throw new Error('timeout: ' + label); };
  try {
    const previous = performance.getEntriesByType('resource').filter(row => row.name.includes('/candidate-recommendations?')).at(-1);
    const key = (previous && new URL(previous.name).searchParams.get('key')) || window.__r77RecoveryKeySeed;
    if (!key) throw new Error('prior request key unavailable');
    const input = document.querySelector('[aria-label="规格辅助请求标识"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, key);
    input.dispatchEvent(new Event('input', { bubbles: true })); await pause();
    window.fetch = async function (...args) {
      const response = await nativeFetch.apply(this, args);
      const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (!held && path.includes('/candidate-recommendations?')) {
        held = true;
        check('genuine-private-get-completed-before-delay', response.ok && (await response.clone().json()).schema === 'candidate-ai-recommendation@1');
        await new Promise(resolve => { release = resolve; });
      }
      return response;
    };
    document.querySelector('[data-testid="candidate-ai-recover"]').click();
    await until(() => held && release, 'actual recovery held');
    window.dispatchEvent(new Event('tire-session-unavailable'));
    await until(() => !document.querySelector('.personalized-home'), 'private tree cleared');
    check('owner-loss-clears-private-panel', !document.querySelector('[data-testid="candidate-ai-assistance"]'));
    release(); await pause(250);
    check('late-get-cannot-restore-old-owner-result', !document.querySelector('[data-testid="candidate-ai-result"]') && !document.querySelector('.personalized-home'));
    window.fetch = nativeFetch;
    window.dispatchEvent(new Event('tire-session-revalidate'));
    await until(() => document.querySelector('.personalized-home'), 'owner revalidated');
    check('new-owner-epoch-has-no-old-preparation', !document.querySelector('[data-testid="candidate-ai-preparation"]') && !document.querySelector('[data-testid="candidate-ai-result"]'));
    const state = await (await nativeFetch('/api/fixture/state', { credentials: 'include' })).json();
    check('owner-qa-never-recalls-provider', state.provider_calls === 1);
    output.done = true; output.passed = output.records.length;
  } catch (error) { output.error = String(error); }
  finally { if (release) release(); window.fetch = nativeFetch; }
  return output;
})();
