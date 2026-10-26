/* R98 page IIFE for later reviewed CDP evaluation. No Node imports or mock responses.
 * Run once per exact viewport (1440, 390, 320), against the reviewed private
 * current-source web build + genuine FastAPI fixture. No OS download/save.
 */
(async () => {
  const out = { schema: "r98-private-review-react@1", started: new Date().toISOString(),
    viewport: { width: innerWidth, height: innerHeight }, records: [], stages: [], http: [],
    synthetic_only: true, historical_s2_offline_replay: true, receipt_is_synthetic: true,
    actual_parser_child: false, actual_online_adoption: false, formal_license_acceptance: false,
    actual_os_file_save_checked: false, self_reported_operator_is_authenticated_actor: false,
    coverage_limits: "Private synthetic session rebind, close, switch quarantine and source-health refresh only; no source-filter switch, list refresh, transport-authority change, same-stack timing proof or real login acceptance.",
    auth_transitions: [],
    done: false, passed: false };
  window.__r98ReviewQa = out;
  const fetchReal = window.fetch.bind(window), pause = (ms = 60) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, value, detail) => {
    out.records.push({ name, passed: !!value, ...(detail === undefined ? {} : { detail }) });
    if (!value) throw Error(name);
  };
  const until = async (read, label) => {
    const end = Date.now() + 25000;
    while (Date.now() < end) { const value = await read(); if (value) return value; await pause(); }
    throw Error("timeout: " + label);
  };
  const visible = element => !!element && !!element.getClientRects().length && getComputedStyle(element).visibility !== "hidden";
  const button = (root, text) => [...(root || document).querySelectorAll("button")].find(node => visible(node)
    && (node.textContent.trim() === text || node.getAttribute("aria-label") === text));
  const click = async element => { if (!visible(element) || element.disabled) throw Error("Enabled real control required"); element.click(); await pause(); };
  const change = async (element, value) => {
    if (!element || element.disabled) throw Error("Enabled real input required");
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, value);
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
    await pause();
  };
  const call = async (path, payload) => {
    const response = await fetchReal("/api" + path, { credentials: "include", ...(payload === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) });
    if (!response.ok) throw Error("Private HTTP " + response.status + " " + path);
    return response.json();
  };
  const observe = async (input, init) => {
    const url = new URL(typeof input === "string" || input instanceof URL ? String(input) : input.url, location.href);
    if (url.origin !== location.origin) throw Error("R98 page fetch must remain on its exact private web origin");
    const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const record = { method, path: url.pathname, query: url.search, status: null, rejected: false };
    if (/\/v1\//.test(url.pathname)) out.http.push(record);
    if (method === "POST" && /\/quarantines\/[^/]+\/reviews$/.test(url.pathname)) {
      const headers = new Headers(input instanceof Request ? input.headers : undefined);
      new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
      record.expected_account = headers.get("X-Tire-Expected-Account");
      try { record.body_keys = Object.keys(JSON.parse(init?.body)).sort(); } catch { record.body_keys = []; }
    }
    try {
      const response = await fetchReal(input, init); record.status = response.status;
      if (url.pathname.endsWith("/v1/auth/me")) {
        const value = await response.clone().json();
        record.auth = { authenticated: value.authenticated, user_id: value.user?.id ?? null, is_admin: value.user?.is_admin ?? false };
      }
      if (method === "POST" && /\/quarantines\/[^/]+\/reviews$/.test(url.pathname)) {
        // Observe the real body read failure; fetch may already have fulfilled
        // its header Promise before a deliberately truncated body fails.
        const json = response.json.bind(response);
        response.json = async () => {
          try { return await json(); }
          catch (error) { record.body_read_rejected = true; throw error; }
        };
      }
      return response;
    }
    catch (error) { record.rejected = true; throw error; }
  };
  const list = () => document.querySelector('[aria-labelledby="quarantine-title"]');
  const detail = () => document.querySelector("#quarantine-evidence");
  const review = () => detail()?.querySelector('[aria-label="车辆 PDF 二进制隔离人工核验"]');
  const approve = () => button(review(), "批准，等待后续在线核验");
  const keep = () => button(review(), "保留隔离 / 撤回待生效批准");
  const confirmation = () => review()?.querySelector('input[type="checkbox"]');
  const posts = () => out.http.filter(row => row.method === "POST" && /\/quarantines\/[^/]+\/reviews$/.test(row.path));
  const stage = name => { out.stages.push(name); out.current_stage = name; };
  let seed, inventory, finalState, ownerAccount;
  const labels = { pending: "尚未人工处理", restricted: "涉及身份或证据问题，须先修复",
    stale_baseline: "正式对照已更新，需后续在线核验", kept_quarantined: "已保留隔离",
    expired: "批准已过期，需重新核对", approved_waiting_online: "已批准，等待后续新在线请求",
    applied_on_online_fetch: "批准已随在线核验生效" };
  const stateText = () => review()?.querySelector(".quarantine-review-state")?.textContent || "";
  const expectedState = async value => until(() => review()?.getAttribute("aria-busy") === "false"
    && stateText().includes(labels[value]), "real review state " + value);
  async function close() {
    if (detail()) await click(button(detail(), "关闭隔离原文"));
    await until(() => !detail(), "detail closed");
  }
  async function open(name, expected) {
    await close();
    const identifier = seed[name].id;
    const index = inventory.items.findIndex(row => row.id === identifier);
    check("exact inventory includes " + name, index >= 0);
    const row = await until(() => {
      const rows = list()?.querySelectorAll(".quarantine-list > .quarantine-item");
      return rows?.length === inventory.items.length ? rows[index] : null;
    }, "exact current inventory row " + name);
    await click(button(row, "核对隔离原文"));
    await until(() => detail(), "detail mounted " + name);
    if (expected) await expectedState(expected);
    return identifier;
  }
  async function fillAndConfirm(name) {
    await until(() => confirmation() && review()?.getAttribute("aria-busy") === "false", "current form " + name);
    await change(review().querySelector('input:not([type="checkbox"])'), " R98 UI 自报署名 ");
    await change(review().querySelector("textarea"), " R98 私有浏览器实际核对依据 " + name + " ");
    await click(confirmation());
    check("fresh checkbox is checked " + name, confirmation().checked);
  }
  async function decide(name, action, expected) {
    await fillAndConfirm(name);
    const before = posts().length;
    await click(action === "approve" ? approve() : keep());
    await expectedState(expected);
    check("exactly one UI POST " + name + " " + action, posts().length === before + 1);
    check("new response clears one-use confirmation " + name, !confirmation()?.checked);
  }
  const currentReactAccount = () => review()?.querySelector(".review-form > p")?.textContent || "";
  async function account(name, requireReact = true) {
    const priorReads = out.http.filter(row => row.path.endsWith("/v1/auth/me")).length;
    const current = await call("/fixture/session?account=" + name, {});
    window.dispatchEvent(new Event("tire-session-revalidate"));
    // Auth revalidation must actually cross the production /auth/me request.
    await until(() => {
      const reads = out.http.filter(row => row.path.endsWith("/v1/auth/me"));
      const row = reads.at(-1);
      return reads.length > priorReads && row.status === 200 && row.auth?.authenticated === true
        && row.auth.user_id === current.user_id && row.auth.is_admin === current.is_admin;
    }, "actual auth revalidation for " + name);
    if (requireReact) {
      await until(() => currentReactAccount().includes("（" + current.user_id + "）")
        && review()?.getAttribute("aria-busy") === "false"
        && (current.is_admin ? !review().textContent.includes("可只读核对") : review().textContent.includes("可只读核对")),
      "React installs actual account " + name);
      check("account " + name + " installs actual id/role and clears previous confirmation", !confirmation()?.checked,
        { user_id: current.user_id, is_admin: current.is_admin, react_account_text: currentReactAccount() });
    }
    out.auth_transitions.push({ account: name, user_id: current.user_id, is_admin: current.is_admin,
      actual_auth_response_checked: true, react_account_installed: requireReact, synthetic_session_rebind: true });
    return current;
  }
  const snapshot = async () => (await call("/fixture/state")).ledger;
  const reviewCount = value => value.counts.QuarantineReview;
  const auditCount = value => value.review_audits.filter(row => row.action === "quarantine_review_recorded").length;
  function finalLedgerAssertions(current) {
    const before = out.ledger_before, after = current.ledger;
    check("this viewport commits exactly thirteen reviews and thirteen recorded review audits", reviewCount(after) === reviewCount(before) + 13
      && auditCount(after) === auditCount(before) + 13);
    check("this viewport dispatches exactly fourteen browser review POSTs", posts().length === 14);
    for (const name of ["VehicleSnapshot", "VehicleVerification", "QuarantineApprovalUse", "VehicleQuarantine", "RawCapture", "ParserExecution"])
      check("all decisions and fault paths leave " + name + " unchanged", after.counts[name] === before.counts[name]);
    const priorReviewIds = new Set(before.reviews.map(row => row.id));
    const additions = after.reviews.filter(row => !priorReviewIds.has(row.id));
    const priorAuditIds = new Set(before.review_audits.map(row => row.id));
    const audits = after.review_audits.filter(row => row.action === "quarantine_review_recorded" && !priorAuditIds.has(row.id));
    const reviewById = new Map(additions.map(row => [row.id, row]));
    check("thirteen new review rows have exactly one audit each with the actual frozen actor and matching Q/action", additions.length === 13
      && audits.length === 13 && new Set(audits.map(row => row.detail.review_id)).size === 13
      && audits.every(row => {
        const recorded = reviewById.get(row.detail.review_id);
        return recorded && row.detail.quarantine_id === recorded.quarantine_id && row.detail.decision === recorded.action
          && row.detail.actor_user_id === ownerAccount.user_id && recorded.actor_session_present === true;
      }));
    check("UI self-reported signature stays distinct from audit actor identity", additions.filter(row => row.operator === "R98 UI 自报署名").length === 12
      && additions.filter(row => row.operator === "R98 controlled competing administrator").length === 1
      && additions.every(row => row.operator_is_self_reported === true && !Object.hasOwn(row, "actor_session_id")));
    check("all fixed fault operations released and guard boundaries remain clean", !current.held && !current.fault_armed
      && current.guard_counts.filesystem_denied_attempts === 0 && current.guard_counts.external_network_attempts === 0
      && current.guard_counts.child_process_attempts === 0 && current.guard_counts.normal_database_attempts === 0);
  }
  async function invalidate(kind, name) {
    if (kind === "close") await close();
    if (kind === "selection") { await open("field"); await open(name); }
    if (kind === "account") { await account("other"); await account("owner"); }
    if (kind === "refresh") {
      await click(button(document.querySelector('[aria-labelledby="source-health-title"]'), "刷新记录"));
    }
  }
  try {
    check("exact private web origin", location.origin === "http://127.0.0.1:18987");
    check("reviewed viewport", [1440, 390, 320].includes(innerWidth));
    window.fetch = observe;
    await call("/fixture/session", {});
    const initial = await call("/fixture/state"); seed = initial.seed;
    out.seed_classification = seed.classification;
    out.seed_binding = { s2_sha256: seed.s2_sha256, s2_bytes: seed.s2_bytes, source_bundle: seed.source_bundle };
    out.ledger_before = initial.ledger; out.seed_ledger = initial.seed_ledger;
    const expectedSeed = { VehicleQuarantine: 15, RawCapture: 16, ParserExecution: 16, VehicleSnapshot: 2,
      VehicleVerification: 2, QuarantineReview: 2, QuarantineApprovalUse: 1 };
    check("exact seed model counts", Object.entries(expectedSeed).every(([name, count]) => initial.seed_ledger.counts[name] === count));
    check("only explicitly synthetic history/use seeded, with no recorded production review audit", initial.seed_ledger.review_audits.length === 0
      && initial.seed_ledger.reviews.length === 2 && initial.seed_ledger.reviews.every(row =>
        [seed.expiry.synthetic_review_id, seed.applied.synthetic_review_id].includes(row.id)));
    ownerAccount = await account("owner", false);
    location.hash = "#/sources";
    await until(() => list()?.querySelector("select"), "current source-quality UI");
    await change(list().querySelector("select"), "");
    await until(() => list().getAttribute("aria-busy") !== "true", "real inventory settled");
    inventory = await call("/v1/quarantines?mode=history");
    stage("three-independent-current-loss-cases");
    for (const name of ["row", "field", "combo"]) {
      await open(name);
      await until(() => stateText(), "decoded real review " + name);
      const text = review().textContent;
      check(name + " source receipt and quality boundaries are explicit", text.includes("来源用途许可") && text.includes("不会发起在线采集")
        && text.includes("Golden") && text.includes("署名为本地自报说明"));
      check(name + " visible loss classification", (name !== "field" ? text.includes("记录缺失") : true)
        && (name !== "row" ? text.includes("字段缺失") : true));
      const comparison = [...review().querySelectorAll("details")].find(node => node.querySelector("summary")?.textContent.includes("完整对照与本次候选"));
      const [beforeJson, candidateJson] = [...comparison.querySelectorAll("pre")].map(node => JSON.parse(node.textContent));
      check(name + " renders actual missing rows without filling from baseline", beforeJson.fitments.length === 4
        && candidateJson.fitments.length === (name === "field" ? 4 : 1));
      if (name !== "row") check(name + " preserves actual null candidate fields", candidateJson.fitments.every(row =>
        row.front.load_index === null && row.rear.speed_rating === null && row.constraints.length === 0)
        && beforeJson.fitments.every(row => row.front.load_index === "98"));
      const baseline = await snapshot();
      await decide(name, "approve", "approved_waiting_online");
      const approved = await snapshot();
      check(name + " approve writes exactly one review and audit", reviewCount(approved) === reviewCount(baseline) + 1
        && auditCount(approved) === auditCount(baseline) + 1);
      check(name + " approve does not adopt facts or consume approval", approved.counts.VehicleSnapshot === baseline.counts.VehicleSnapshot
        && approved.counts.VehicleVerification === baseline.counts.VehicleVerification
        && approved.counts.QuarantineApprovalUse === baseline.counts.QuarantineApprovalUse
        && !review().textContent.includes(labels.applied_on_online_fetch));
      await decide(name, "keep", "kept_quarantined");
    }
    stage("roles-and-production-permission");
    const roleBefore = await snapshot(), beforeRolePosts = posts().length;
    const readerAccount = await account("reader"); await open("row", "kept_quarantined");
    check("non-admin read remains available and both actions disabled", review().textContent.includes("可只读核对")
      && approve().disabled && keep().disabled && confirmation().disabled);
    check("non-admin causes no POST", posts().length === beforeRolePosts);
    const readonly = await call("/v1/quarantines/r98-row/review?mode=history&format=raw-evidence-v2");
    const deniedWrite = await window.fetch("/api/v1/quarantines/r98-row/reviews?mode=history&format=raw-evidence-v2", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-Tire-Expected-Account": readerAccount.user_id },
      body: JSON.stringify({ action: "keep_quarantined", expected_revision: readonly.revision,
        operator: "R98 controlled HTTP permission negative", reason: "Direct HTTP negative; disabled UI does not dispatch this request",
        confirmed_loss: true, expected_binding_hash: readonly.binding_hash }) });
    const deniedBody = await deniedWrite.json();
    check("controlled direct HTTP non-admin POST is actually denied by production", deniedWrite.status === 403 && deniedBody.detail.code === "admin_required");
    out.non_admin_write = { origin: "controlled direct HTTP negative, separate from UI clicks", status: deniedWrite.status, code: deniedBody.detail.code };
    await account("owner");
    await open("permission");
    await until(() => detail()?.querySelector('[role="alert"]'), "actual production source-purpose 403");
    const deniedState = await call("/fixture/state");
    check("permission 403 is a production response and offers no approval form", deniedState.requests.some(row =>
      row.path === "/v1/quarantines/r98-permission" && row.status === 403) && !review()?.querySelector("form"));
    const roleAfter = await snapshot();
    check("read-only role and permission checks create no review/audit", reviewCount(roleBefore) === reviewCount(roleAfter)
      && auditCount(roleBefore) === auditCount(roleAfter));
    stage("restricted-expiry-stale-explicit-synthetic-applied");
    for (const [name, state] of [["restricted", "restricted"], ["expiry", "expired"], ["stale", "stale_baseline"], ["applied", "applied_on_online_fetch"]]) {
      await open(name, state);
      check(name + " actual backend projection decoded", stateText().includes(labels[state]));
      if (name === "restricted" || name === "stale") check(name + " cannot approve", approve().disabled);
      if (name === "applied") check("applied is display-only synthetic seed with no decision form",
        seed.applied.synthetic_applied_use_seed === true && !review().querySelector("form"));
      if (name === "expiry") check("expiry is append-only synthetic historical seed", seed.expiry.synthetic_history_seed === true);
    }
    stage("real-production-409-no-automatic-post");
    await open("conflict"); await until(() => stateText(), "conflict basis ready"); await fillAndConfirm("conflict");
    await call("/fixture/fault", { path: "/v1/captures/" + seed.conflict.capture_id, method: "GET", action: "competing-review" });
    const conflictBefore = await snapshot(), conflictPosts = posts().length;
    await click(keep());
    await until(() => review()?.textContent.includes("不会自动重发") && stateText(), "409 readonly reconciliation");
    const conflictAfter = await snapshot(); await pause(250);
    check("one real UI POST receives backend 409", posts().length === conflictPosts + 1 && posts().at(-1).status === 409);
    check("only controlled competing production POST commits", reviewCount(conflictAfter) === reviewCount(conflictBefore) + 1
      && auditCount(conflictAfter) === auditCount(conflictBefore) + 1);
    check("409 readonly reload requires a new unchecked confirmation", !confirmation().checked && approve().disabled && keep().disabled);
    stage("committed-response-loss-and-response-403");
    for (const [name, action] of [["drop", "drop-after-commit"], ["post403", "postcommit403"]]) {
      await open(name); await until(() => stateText(), name + " basis"); await fillAndConfirm(name);
      await call("/fixture/fault", { path: "/v1/quarantines/" + seed[name].id + "/reviews", method: "POST", action });
      const faultBefore = await call("/fixture/state");
      const before = await snapshot(), sent = posts().length;
      await click(keep());
      await until(() => review()?.textContent.includes("提交结果待核对") && stateText(), name + " readonly reconciliation");
      const after = await snapshot(); await pause(250);
      const delivered = await call("/fixture/state"), path = "/v1/quarantines/" + seed[name].id + "/reviews";
      const entries = delivered.faults_applied.slice(faultBefore.faults_applied.length).filter(row =>
        row.path === path && row.method === "POST" && row.action === action);
      const responses = delivered.requests.slice(faultBefore.requests.length).filter(row => row.path === path && row.method === "POST");
      check(name + " applies exactly the specified fault after a real production 201", entries.length === 1
        && entries[0].production_route_completed === true && entries[0].original_status === 201
        && responses.length === 1 && responses[0].status === 201);
      const post = posts()[sent];
      check(name + " observes actual specified delivery rather than a generic error", name === "post403"
        ? post.status === 403 && responses[0].delivered_status === 403
        : responses[0].delivered_status === "truncated-http-201" && (post.rejected === true || post.body_read_rejected === true));
      check(name + " consumes its fault with no armed/held remainder", !delivered.held && !delivered.fault_armed);
      check(name + " preserves actual committed review and audit", reviewCount(after) === reviewCount(before) + 1 && auditCount(after) === auditCount(before) + 1);
      check(name + " performs exactly one UI POST and only readonly reconciliation", posts().length === sent + 1 && !confirmation().checked);
      check(name + " never claims server write rollback", !review().textContent.includes("已经回滚") && !review().textContent.includes("已取消服务器写入"));
    }
    stage("late-read-and-late-post-owner-selection-close-refresh");
    for (const kind of ["close", "selection", "account", "refresh"]) {
      for (const phase of ["read", "post"]) {
        const name = kind;
        if (phase === "post") {
          await open(name); await until(() => stateText(), name + " current post basis"); await fillAndConfirm(name);
        } else await close();
        const route = "/v1/quarantines/" + seed[name].id + (phase === "read" ? "/review" : "/reviews");
        await call("/fixture/fault", { path: route, method: phase === "read" ? "GET" : "POST", action: "hold" });
        const sent = posts().length, before = await snapshot();
        if (phase === "read") await open(name); else await click(keep());
        await until(async () => (await call("/fixture/state")).held, kind + " " + phase + " production response held");
        await invalidate(kind, name);
        check(kind + " " + phase + " immediately revokes old confirmation", !confirmation()?.checked);
        await call("/fixture/release", {});
        await until(async () => !(await call("/fixture/state")).held, "own held response released");
        await pause(180);
        check(kind + " " + phase + " late completion/finally does not restore confirmation", !confirmation()?.checked);
        check(kind + " " + phase + " never auto-reposts", posts().length === sent + (phase === "post" ? 1 : 0));
        await open(name); await until(() => stateText(), "fresh post-invalidation display");
        check(kind + " " + phase + " fresh read starts unconfirmed", !confirmation().checked && approve().disabled && keep().disabled);
        const after = await snapshot();
        check(kind + " " + phase + " actual server ledger matches dispatched write", reviewCount(after) === reviewCount(before) + (phase === "post" ? 1 : 0)
          && auditCount(after) === auditCount(before) + (phase === "post" ? 1 : 0));
        if (phase === "post") check(kind + " uncertain dispatched write remains disclosed after reopen", review().textContent.includes("提交结果待核对"));
      }
    }
    stage("layout-and-transport-contract");
    await open("combo", "kept_quarantined");
    check("document has no horizontal overflow at " + innerWidth, document.documentElement.scrollWidth <= innerWidth + 1,
      { scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth });
    check("review card stays in the viewport", review().getBoundingClientRect().left >= -1 && review().getBoundingClientRect().right <= innerWidth + 1);
    const inputs = [...review().querySelectorAll("input,textarea")];
    check("all decision inputs have visible descriptive labels", inputs.every(node => !!node.closest("label")?.textContent.trim()));
    check("real binary POST has exact query, six keys, and account intent", posts().every(row => row.query === "?mode=history&format=raw-evidence-v2"
      && /^[A-Za-z0-9_-]{1,64}$/.test(row.expected_account || "") && JSON.stringify(row.body_keys) === JSON.stringify([
        "action", "confirmed_loss", "expected_binding_hash", "expected_revision", "operator", "reason"])));
    finalState = await call("/fixture/state");
    check("private guard remains clean", finalState.guard_counts.external_network_attempts === 0
      && finalState.guard_counts.child_process_attempts === 0 && finalState.guard_counts.normal_database_attempts === 0
      && finalState.guard_counts.filesystem_denied_attempts === 0);
    out.ledger_after = finalState.ledger;
    out.actual_http_counts = { browser_production_requests: out.http.length, browser_review_posts: posts().length,
      server_production_requests: finalState.requests.length, actual_review_rows: finalState.ledger.counts.QuarantineReview,
      actual_recorded_review_audits: auditCount(finalState.ledger), actual_approval_uses: finalState.ledger.counts.QuarantineApprovalUse };
    out.controlled_faults = finalState.faults_applied;
    out.guard_counts = finalState.guard_counts;
    out.passed = true;
  } catch (error) {
    out.error = String(error);
  } finally {
    try { await call("/fixture/release", {}); } catch (error) { out.release_error = String(error); }
    try {
      const restored = await account("owner", false);
      if (seed && inventory) {
        await open("row"); await until(() => currentReactAccount().includes("（" + restored.user_id + "）")
          && review()?.getAttribute("aria-busy") === "false", "final React owner restore");
        check("final restore installs actual owner in React with no revived confirmation", !confirmation()?.checked
          && !review().textContent.includes("可只读核对"));
        out.auth_transitions.push({ account: "owner-final", user_id: restored.user_id, is_admin: restored.is_admin,
          actual_auth_response_checked: true, react_account_installed: true, synthetic_session_rebind: true });
      }
    }
    catch (error) { out.account_restore_error = String(error); }
    try {
      const current = await call("/fixture/state");
      out.ledger_after = current.ledger; out.guard_counts = current.guard_counts;
      out.held_response_remaining = current.held; out.fault_armed_remaining = current.fault_armed;
      finalLedgerAssertions(current);
      out.actual_http_counts = { browser_production_requests: out.http.length, browser_review_posts: posts().length,
        server_production_requests: current.requests.length, actual_review_rows: current.ledger.counts.QuarantineReview,
        actual_recorded_review_audits: auditCount(current.ledger), actual_approval_uses: current.ledger.counts.QuarantineApprovalUse };
      if (current.held || current.fault_armed) out.passed = false;
    } catch (error) { out.final_ledger_error = String(error); out.passed = false; }
    if (out.release_error || out.account_restore_error || out.final_ledger_error) out.passed = false;
    window.fetch = fetchReal;
    out.done = true; out.ended = new Date().toISOString();
    window.__r98ReviewQa = out;
    try { await call("/fixture/receipt", out); } catch (error) { out.receipt_write_error = String(error); out.passed = false; }
  }
  return out;
})();
