/* Real private HTTP and React events; only outbound receiver is controlled. */
(async () => {
  const out = { schema: 'r78-private-ui-qa@1', records: [], done: false,
    synthetic_only: true, real_webhook_receivers: 0 };
  const originalFetch = window.fetch;
  const pause = (ms = 70) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, passed, detail) => {
    out.records.push({ name, passed: !!passed, ...(detail ? { detail } : {}) });
    if (!passed) throw new Error(name);
  };
  const until = async (read, label) => { const start = Date.now(); while (Date.now() - start < 20000) {
    const value = read(); if (value) return value; await pause();
  } throw new Error('timeout: ' + label); };
  const request = async (path, body) => {
    const response = await originalFetch('/api' + path, { credentials: 'include',
      ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
    if (!response.ok) throw new Error('private-http-' + response.status);
    return response.json();
  };
  const input = async (node, value) => {
    if (!node) throw new Error('missing input');
    const type = node.tagName === 'SELECT' ? HTMLSelectElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(type.prototype, 'value').set.call(node, value);
    node.dispatchEvent(new Event(node.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    await pause();
  };
  const click = async node => { if (!node || node.disabled) throw new Error('expected enabled control'); node.click(); await pause(); };
  const panel = () => document.querySelector('[data-testid="webhooks-panel"]');
  const node = id => panel()?.querySelector('[data-testid="' + id + '"]');
  const button = (root, label) => [...root.querySelectorAll('button')].find(n => n.textContent.trim() === label);
  let operation = null, postCount = 0, operationGets = 0, loseNextCreate = false, lost = null;
  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);
    const path = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    const method = String(args[1]?.method || 'GET').toUpperCase();
    if (path.includes('/webhook-operations?')) operationGets++;
    if (path.includes('/v1/webhooks') && method !== 'GET') {
      postCount++;
      if (response.ok) {
        const value = await response.clone().json();
        if (loseNextCreate && method === 'POST' && /\/webhooks$/.test(path)) {
          loseNextCreate = false; lost = value;
          throw new TypeError('synthetic response loss after real HTTP commit');
        }
        operation = value;
      }
    }
    return response;
  };
  async function createDraft(label, target = 'synthetic-receiver') {
    operation = null;
    await click(node('webhooks-create'));
    await until(() => node('webhooks-editor'), 'editor');
    check('create-has-no-default-channels-or-consent-' + label,
      !node('webhooks-enabled').checked && !node('webhooks-external-consent').checked
      && ![...panel().querySelectorAll('[data-webhook-channel]')].some(n => n.checked));
    await input(panel().querySelector('[aria-label="Webhook订阅名称"]'), '合成通知-' + label + '-' + Date.now());
    await input(panel().querySelector('[aria-label="Webhook受管理目标"]'), target);
    await click(panel().querySelector('[data-webhook-channel="tire_monitor"]'));
    await click(panel().querySelector('[data-webhook-channel="interest"]'));
    if (target === 'synthetic-missing-key') check('missing-key-cannot-enable', node('webhooks-enabled').disabled);
    await click(node('webhooks-save'));
    return until(() => operation || lost, 'create operation');
  }
  try {
    await request('/health'); await request('/fixture/session', {});
    const previousPanel = panel();
    window.dispatchEvent(new Event('tire-session-revalidate')); location.hash = '#/watch';
    await until(() => panel() && panel() !== previousPanel && node('webhooks-targets')?.textContent.includes('2 项'), 'revalidated private webhook panel');
    check('managed-targets-show-host-without-url-or-key', node('webhooks-targets').textContent.includes('receiver.example.com')
      && !node('webhooks-targets').textContent.includes('https://'));
    const first = await createDraft('primary');
    const primaryId = first.resource_id, firstKey = first.idempotency_key;
    await until(() => node('webhook-detail')?.textContent.includes(first.response.name), 'paused detail');
    check('create-is-paused-frozen-operation', first.schema === 'webhook-operation@1' && !first.replayed
      && !first.response.enabled && first.current === false && first.response.revision === 1);
    check('creation-and-reads-zero-receiver-calls', (await request('/fixture/state')).controlled_receiver_calls === 0);
    const firstResponse = JSON.stringify(first.response), priorPosts = postCount;
    await click(node('webhooks-recover'));
    await until(() => node('webhook-operation')?.textContent.includes('只读重放'), 'operation recovery');
    const recovered = await request('/v1/webhook-operations?mode=history&key=' + firstKey);
    check('uuid-recovery-is-read-only-and-frozen', recovered.replayed && JSON.stringify(recovered.response) === firstResponse
      && postCount === priorPosts && operationGets >= 1);
    const missing = await createDraft('missing', 'synthetic-missing-key');
    await until(() => node('webhook-detail')?.textContent.includes(missing.response.name), 'missing key draft');
    check('missing-key-draft-explicitly-not-ready', missing.response.readiness === 'key_unavailable'
      && node('webhooks-resume').disabled && node('webhooks-resume-consent').disabled);
    await click(panel().querySelector('[data-webhook-id="' + primaryId + '"]'));
    await until(() => node('webhook-detail')?.textContent.includes(first.response.name), 'select primary');
    check('resume-needs-explicit-consent', node('webhooks-resume').disabled && !node('webhooks-resume-consent').checked);
    await click(node('webhooks-resume-consent')); operation = null; await click(node('webhooks-resume'));
    await until(() => operation?.action === 'resume' && node('webhooks-pause') && !node('webhooks-pause').disabled, 'enabled revision');
    check('enable-does-not-backfill', (await request('/v1/webhooks/' + primaryId + '/deliveries?mode=history')).total === 0);
    await request('/fixture/emit', {}); await click(node('webhooks-refresh'));
    const queued = await request('/v1/webhooks/' + primaryId + '/deliveries?mode=history');
    await until(() => panel().querySelectorAll('[data-webhook-delivery-id]').length === queued.total && queued.total === 2, 'future queue');
    check('new-production-notifications-queue-shared-and-private', queued.items.some(n => n.channel === 'tire_monitor')
      && queued.items.some(n => n.channel === 'interest') && queued.items.every(n => n.attempts === 0 && n.state === 'pending'));
    const deliveryId = queued.items[0].id;
    await click(panel().querySelector('[data-webhook-delivery-id="' + deliveryId + '"]'));
    await until(() => node('webhook-delivery'), 'frozen delivery');
    const delivery = await request('/v1/webhooks/' + primaryId + '/deliveries/' + deliveryId + '?mode=history');
    check('frozen-body-excludes-facts-and-personal-fields', Object.keys(delivery.body).sort().join(',') ===
      ['schema','delivery_id','channel','notification_id','event_id','domain','occurred_at','data_scope','notice'].sort().join(',')
      && delivery.body.data_scope === 'notification_reference_only' && !JSON.stringify(delivery.body).includes(first.response.name));
    check('cancel-needs-explicit-confirmation', node('webhooks-cancel').disabled);
    await click(node('webhooks-delivery-consent')); operation = null; await click(node('webhooks-cancel'));
    await until(() => operation?.action === 'cancel' && node('webhook-delivery')?.textContent.includes('后续派送已取消'), 'cancelled queue');
    check('cancel-retains-frozen-body-and-no-http', operation.response.state === 'cancelled' && operation.response.attempts === 0
      && operation.response.body_sha256 === delivery.body_sha256 && (await request('/fixture/state')).controlled_receiver_calls === 0);
    operation = null; await click(node('webhooks-pause'));
    await until(() => operation?.action === 'pause' && node('webhooks-resume')?.disabled, 'pause revision');
    await request('/fixture/emit', {}); await click(node('webhooks-refresh'));
    check('pause-does-not-add-future-queue', (await request('/v1/webhooks/' + primaryId + '/deliveries?mode=history')).total === 2);
    operation = null; await click(node('webhooks-archive'));
    await until(() => operation?.action === 'archive' && button(panel(), '恢复为暂停订阅'), 'archived');
    operation = null; await click(button(panel(), '恢复为暂停订阅'));
    await until(() => operation?.action === 'restore' && node('webhooks-resume'), 'restored paused');
    check('restore-stays-paused-and-avoids-test-message', !operation.response.enabled
      && (await request('/fixture/state')).controlled_receiver_calls === 0);
    loseNextCreate = true; lost = null;
    const lostOperation = await createDraft('response-loss');
    await until(() => node('webhooks-error') && panel().textContent.includes(lostOperation.idempotency_key), 'lost write locked');
    check('real-committed-response-loss-retains-uuid', node('webhooks-create').disabled && lostOperation.action === 'create');
    const postsBeforeRecovery = postCount;
    await input(panel().querySelector('[aria-label="Webhook操作UUID"]'), firstKey); await click(node('webhooks-recover'));
    await until(() => node('webhook-operation')?.textContent.includes(firstKey), 'other operation read');
    check('other-key-recovery-does-not-unlock-unknown-write', node('webhooks-create').disabled
      && panel().textContent.includes(lostOperation.idempotency_key));
    await input(panel().querySelector('[aria-label="Webhook操作UUID"]'), lostOperation.idempotency_key); await click(node('webhooks-recover'));
    await until(() => !node('webhooks-create').disabled && node('webhook-detail')?.textContent.includes(lostOperation.response.name), 'matching recovery');
    check('matching-key-restores-one-resource-without-post-retry', postCount === postsBeforeRecovery
      && (await request('/v1/webhooks?mode=history')).items.filter(n => n.id === lostOperation.resource_id).length === 1);
    window.__r78OwnerRecoveryKey = lostOperation.idempotency_key;
    check('viewport-no-horizontal-overflow', document.documentElement.scrollWidth <= innerWidth,
      { document: document.documentElement.scrollWidth, viewport: innerWidth });
    out.done = true; out.passed = out.records.length; out.post_count = postCount; out.operation_gets = operationGets;
  } catch (error) { out.error = String(error); }
  finally { window.fetch = originalFetch; }
  return out;
})();
