/* Real React events and private HTTP. API tokens stay in local function memory. */
(async () => {
  const out = { schema: "r80-private-ui@1", viewport: { width: innerWidth, height: innerHeight }, records: [], done: false,
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
    const response = await originalFetch("/api" + path, { credentials: "include", headers: { "Content-Type": "application/json", ...headers }, ...(payload === undefined ? {} : { method: "POST", body: JSON.stringify(payload) }) });
    if (!response.ok) throw new Error("private-http-" + response.status); return response.json();
  };
  let drop = false, hold = false, release = null, held = false, posts = 0, recoveries = 0;
  let historyFailure = false, holdHistory = false, releaseHistory = null, historyHeld = false;
  window.fetch = async (...args) => {
    const path = String(args[0]), init = args[1] || {};
    if (path.startsWith("/api/v1/api-key-operations?")) recoveries++;
    const response = await originalFetch(...args);
    if (path.startsWith("/api/v1/api-key-history?")) {
      if (historyFailure) { historyFailure = false; return Response.json({ detail: { code: "api_key_history_cursor_expired" } }, { status: 409 }); }
      if (holdHistory) { holdHistory = false; historyHeld = true; await new Promise(resolve => { releaseHistory = resolve; }); }
    }
    if (path === "/api/v1/api-keys" && init.method === "POST") {
      posts++;
      if (drop) { drop = false; throw new TypeError("synthetic caller lost response after real server commit"); }
      if (hold) { hold = false; held = true; await new Promise(resolve => { release = resolve; }); }
    }
    return response;
  };
  try {
    location.hash = "#/watch";
    await call("/fixture/session", {});
    const seeded = await call("/fixture/seed-inventory", {});
    const owner = (await call("/v1/auth/me")).user.id, inventoryHeaders = { "X-Tire-Expected-Account": owner };
    const legacy = await call("/v1/api-keys?mode=history");
    check("legacy recent100 really hides old active credential", legacy.items.length === 100 && !legacy.items.some(k => k.id === seeded.old_id));
    window.dispatchEvent(new Event("tire-session-revalidate"));
    await pause(200);
    await until(() => panel()?.querySelector("form"), "authenticated panel");
    await until(() => !panel().textContent.includes("正在读取密钥"), "initial list");
    check("signed-in panel renders", !!panel().querySelector("form"));
    check("empty acknowledgement blocks issuance", button(panel(), "创建密钥").disabled);
    const activePanel = () => panel().querySelector(".api-key-active"), historyPanel = () => panel().querySelector(".api-key-history");
    await until(() => activePanel()?.textContent.includes(seeded.old_name) && historyPanel()?.textContent.includes("第1页"), "independent inventories");
    check("all-active React list exposes old hidden credential", activePanel().textContent.includes(seeded.old_name));
    let page = 1, reachedOld = false;
    while (!button(historyPanel(), "查看更早记录").disabled && page < 80) {
      await click(button(historyPanel(), "查看更早记录")); page++;
      await until(() => historyPanel().textContent.includes("第" + page + "页") && !historyPanel().textContent.includes("正在读取历史"), "next history page");
      reachedOld ||= historyPanel().textContent.includes(seeded.old_name);
      check("history stays one bounded page " + page, historyPanel().querySelectorAll(".api-key-row").length <= 20);
    }
    check("history reaches old records and explicit last page", reachedOld && historyPanel().textContent.includes("已到最早记录"));
    await click(button(historyPanel(), "从最新记录重新读取")); await until(() => historyPanel().textContent.includes("第1页"), "restart history");
    historyFailure = true; await click(button(historyPanel(), "查看更早记录"));
    await until(() => historyPanel().textContent.includes("读取窗口已到期"), "history error");
    check("history failure keeps successful active inventory", activePanel().textContent.includes(seeded.old_name));
    check("expired history requires explicit restart", button(historyPanel(), "查看更早记录").disabled && !button(historyPanel(), "从最新记录重新读取").disabled);
    await click(button(historyPanel(), "从最新记录重新读取")); await until(() => !historyPanel().textContent.includes("读取窗口已到期") && !historyPanel().textContent.includes("正在读取历史"), "restart after expiry");
    holdHistory = true; historyHeld = false; await click(button(historyPanel(), "查看更早记录")); await until(() => historyHeld, "held old page");
    await click(button(activePanel(), "刷新密钥列表")); await until(() => historyPanel().textContent.includes("第1页") && !historyPanel().textContent.includes("正在读取历史"), "refresh fresh window");
    releaseHistory(); releaseHistory = null; await pause(150);
    check("refresh prevents late page from replacing latest window", historyPanel().textContent.includes("第1页"));
    const oldRow = [...activePanel().querySelectorAll(".api-key-row")].find(n => n.textContent.includes(seeded.old_name));
    await click(checkbox(oldRow, "确认撤销")); await click(button(oldRow, "撤销密钥"));
    await until(() => panel().textContent.includes("密钥已撤销") && !activePanel().textContent.includes(seeded.old_name), "old hidden credential revoked");
    check("old hidden credential revoked through React", !(await call("/v1/api-keys/active?mode=history", undefined, inventoryHeaders)).items.some(k => k.id === seeded.old_id));
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
    const row = await until(() => [...activePanel().querySelectorAll(".api-key-row")].find(n => n.querySelector("strong")?.textContent === unique), "issued row");
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
    await until(() => historyPanel()?.textContent.includes("第1页") && !historyPanel().textContent.includes("正在读取历史"), "restored history");
    holdHistory = true; historyHeld = false; await click(button(historyPanel(), "查看更早记录")); await until(() => historyHeld, "held page before owner change");
    await call("/fixture/session?account=other", {}); window.dispatchEvent(new Event("tire-session-revalidate"));
    await until(() => activePanel()?.textContent.includes("暂无有效密钥") && historyPanel()?.textContent.includes("尚无签发记录"), "other owner empty lists");
    releaseHistory(); releaseHistory = null; await pause(150);
    check("account change isolates late old history", !panel().querySelector(".api-key-row") && !panel().querySelector("textarea"));
    await call("/fixture/session", {}); window.dispatchEvent(new Event("tire-session-revalidate"));
    await until(() => activePanel() && !activePanel().textContent.includes("正在读取密钥"), "owner cleanup");
    const all = await call("/v1/api-keys/active?mode=history", undefined, inventoryHeaders);
    for (const k of all.items) await call("/v1/api-keys/" + k.id + "/revoke", { acknowledged: true }, { "Idempotency-Key": crypto.randomUUID() });
    check("test credentials all revoked using full active inventory", (await call("/v1/api-keys/active?mode=history", undefined, inventoryHeaders)).items.length === 0);
    check("viewport has no horizontal overflow", document.documentElement.scrollWidth <= innerWidth + 1);
    check("panel controls have accessible text", [...panel().querySelectorAll("button")].every(n => !!n.textContent.trim()));
    out.done = true;
  } catch (cause) { out.failure = cause instanceof Error ? cause.message : "unknown"; }
  finally { release?.(); releaseHistory?.(); window.fetch = originalFetch; }
  return out;
})();
