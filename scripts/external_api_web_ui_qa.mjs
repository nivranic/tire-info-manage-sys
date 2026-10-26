/* Real React events and private HTTP. API tokens stay in local function memory. */
(async () => {
  const out = { schema: "r79-private-ui@1", viewport: { width: innerWidth, height: innerHeight }, records: [], done: false,
    synthetic_only: true, token_values_recorded: false, real_provider_calls: 0 };
  const originalFetch = window.fetch;
  const pause = (ms = 60) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, value) => { out.records.push({ name, passed: !!value }); if (!value) throw new Error(name); };
  const until = async (read, label) => { const end = Date.now() + 20000; while (Date.now() < end) { const v = read(); if (v) return v; await pause(); } throw new Error("timeout: " + label); };
  const panel = () => document.querySelector(".api-key-panel");
  const button = (root, label) => [...root.querySelectorAll("button")].find(n => n.textContent.trim() === label);
  const checkbox = (root, phrase) => [...root.querySelectorAll("label")].find(n => n.textContent.includes(phrase))?.querySelector('input[type="checkbox"]');
  const click = async node => { if (!node || node.disabled) throw new Error("enabled control required"); node.click(); await pause(); };
  const input = async (node, value) => { if (!node) throw new Error("input required"); node.focus(); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(node, value); node.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value })); node.dispatchEvent(new Event("change", { bubbles: true })); await pause(); };
  const call = async (path, payload, headers = {}) => {
    const response = await originalFetch("/api" + path, { credentials: "include", ...(payload === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(payload) }) });
    if (!response.ok) throw new Error("private-http-" + response.status); return response.json();
  };
  let drop = false, hold = false, release = null, held = false, posts = 0, recoveries = 0;
  window.fetch = async (...args) => {
    const path = String(args[0]), init = args[1] || {};
    if (path.startsWith("/api/v1/api-key-operations?")) recoveries++;
    const response = await originalFetch(...args);
    if (path === "/api/v1/api-keys" && init.method === "POST") {
      posts++;
      if (drop) { drop = false; throw new TypeError("synthetic caller lost response after real server commit"); }
      if (hold) { hold = false; held = true; await new Promise(resolve => { release = resolve; }); }
    }
    return response;
  };
  try {
    location.hash = "#/watch";
    await call("/fixture/session", {}); window.dispatchEvent(new Event("tire-session-revalidate"));
    await pause(200);
    await until(() => panel()?.querySelector("form"), "authenticated panel");
    await until(() => !panel().textContent.includes("正在读取密钥"), "initial list");
    check("signed-in panel renders", !!panel().querySelector("form"));
    check("empty acknowledgement blocks issuance", button(panel(), "创建密钥").disabled);
    const unique = "合成" + crypto.randomUUID().slice(0, 8) + "<img src=x>";
    async function prepare(name) {
      await input(panel().querySelector('input:not([type="checkbox"])'), name);
      const scope = checkbox(panel(), "读取本人 Webhook"); if (!scope.checked) await click(scope);
      const ack = checkbox(panel(), "允许持有密钥"); if (!ack.checked) await click(ack);
    }
    await prepare(unique); check("explicit scope and acknowledgement allow issuance", !button(panel(), "创建密钥").disabled);
    await click(button(panel(), "创建密钥"));
    let secret = (await until(() => panel()?.querySelector("textarea"), "one-time token")).value;
    check("one-time token matches credential format", /^ti_[a-f0-9]{32}\.[a-f0-9]{64}$/.test(secret));
    check("name is rendered as text", panel().textContent.includes(unique) && !panel().querySelector("img"));
    check("token absent from browser stores", !Object.values(sessionStorage).some(v => v.includes(secret)) && !Object.values(localStorage).some(v => v.includes(secret)));
    const read = (path, value = secret) => originalFetch("/api" + path, { credentials: "omit", headers: value ? { Authorization: "Bearer " + value } : {}, redirect: "error" });
    const sources = await read("/external/v1/sources?limit=1"); const sourcePage = await sources.json();
    check("issued credential reads actual source catalog", sources.status === 200 && sourcePage.schema === "external-sources@1" && sourcePage.data_state === "local_snapshot");
    check("cookie alone cannot authorize external API", (await read("/external/v1/sources", null)).status === 401);
    check("Bearer cannot become local cookie authority", (await read("/v1/api-keys?mode=history")).status === 401);
    const target = (await call("/v1/webhooks/targets")).items.find(v => v.ready);
    const subscription = await call("/v1/webhooks", { name: "合成外部引用", target_id: target.id, target_fingerprint: target.policy_fingerprint,
      channels: ["tire_monitor"], enabled: true, acknowledged_external_delivery: true }, { "Idempotency-Key": crypto.randomUUID() });
    await call("/fixture/emit", {}); await call("/fixture/emit", {});
    const path = "/external/v1/webhook-deliveries?limit=1&webhook_id=" + subscription.resource_id;
    const r1 = await read(path), p1 = await r1.json(); check("actual notification hook appears through external cursor API", r1.status === 200 && p1.items.length === 1 && typeof p1.next_cursor === "string");
    const p2 = await (await read(path + "&cursor=" + encodeURIComponent(p1.next_cursor))).json();
    check("cursor advances without duplicate reference", p2.items.length === 1 && p2.items[0].id !== p1.items[0].id && p2.next_cursor === null);
    const detail = await (await read("/external/v1/webhook-deliveries/" + p1.items[0].id)).json();
    check("detail exports reference-only body", detail.body.data_scope === "notification_reference_only" && !Object.hasOwn(detail.body, "facts"));
    await click(button(panel(), "关闭密钥显示")); check("closing display removes raw token", !panel().querySelector("textarea"));
    check("intentional close does not claim credential was lost", !panel().textContent.includes("首次密钥未保留"));
    const row = await until(() => [...panel().querySelectorAll(".api-key-row")].find(n => n.querySelector("strong")?.textContent === unique), "issued row");
    await click(checkbox(row, "确认撤销")); await click(button(row, "撤销密钥")); await until(() => panel().textContent.includes("密钥已撤销"), "revocation receipt");
    check("revocation immediately rejects old credential", (await read("/external/v1/sources")).status === 401); secret = null;
    await prepare("合成失落响应" + crypto.randomUUID().slice(0, 6)); drop = true; await click(button(panel(), "创建密钥"));
    await until(() => panel().textContent.includes("操作结果待确认"), "unknown write"); await until(() => !button(panel(), "核对未确认操作").disabled, "unknown response settled");
    check("unknown outcome blocks another issuance", button(panel(), "创建密钥").disabled);
    const before = posts; await click(button(panel(), "核对未确认操作")); await until(() => panel().textContent.includes("首次密钥未保留"), "readonly recovery");
    check("recovery reads metadata without repeating POST", posts === before && recoveries > 0 && !panel().querySelector("textarea"));
    await until(() => !button(panel(), "创建密钥").disabled || panel().querySelector('input:not([type="checkbox"])').value === "", "recovered unlock");
    await prepare("合成迟到" + crypto.randomUUID().slice(0, 6)); hold = true; await click(button(panel(), "创建密钥")); await until(() => held, "held response");
    window.dispatchEvent(new Event("tire-session-unavailable")); await until(() => !panel().querySelector("form"), "owner invalidation"); release(); release = null; await pause(200);
    check("late create cannot restore token or old owner UI", !panel().querySelector("textarea") && !panel().querySelector(".api-key-row"));
    await call("/fixture/session", {}); window.dispatchEvent(new Event("tire-session-revalidate")); await pause(200); await until(() => panel()?.querySelector("form"), "owner restored");
    await until(() => button(panel(), "核对未确认操作") && !button(panel(), "核对未确认操作").disabled, "pending recovery after epoch");
    await click(button(panel(), "核对未确认操作")); await until(() => panel().textContent.includes("首次密钥未保留"), "late readonly recovery");
    check("owner revalidation preserves only recovery UUID", !panel().querySelector("textarea") && !panel().textContent.includes("操作结果待确认"));
    const all = await call("/v1/api-keys?mode=history");
    for (const k of all.items.filter(k => !k.revoked_at)) await call("/v1/api-keys/" + k.id + "/revoke", { acknowledged: true }, { "Idempotency-Key": crypto.randomUUID() });
    check("test credentials all revoked", (await call("/v1/api-keys?mode=history")).items.every(k => !!k.revoked_at));
    check("viewport has no horizontal overflow", document.documentElement.scrollWidth <= innerWidth + 1);
    check("panel controls have accessible text", [...panel().querySelectorAll("button")].every(n => !!n.textContent.trim()));
    out.done = true;
  } catch (cause) { out.failure = cause instanceof Error ? cause.message : "unknown"; }
  finally { release?.(); window.fetch = originalFetch; }
  return out;
})();
