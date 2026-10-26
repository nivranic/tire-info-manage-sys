/* Page IIFE for CDP sourcePath evaluation. No Node imports; real current React + private HTTP. */
(async () => {
  const out = { schema: "r96-private-react@1", viewport: { width: innerWidth, height: innerHeight }, started: new Date().toISOString(),
    records: [], stages: [], done: false, synthetic_only: true, receipt_is_synthetic: true,
    actual_parser_child: false, browser_delivery_spy: true, actual_os_file_save_checked: false,
    transport_epoch_coverage: "Independent Node production observer/native adapter tests; this page tests owner and selection lifecycle." };
  window.__r96RawQa = out;
  if (location.origin !== "http://127.0.0.1:18967") throw Error("Exact R96 private web origin required");
  const fetchReal = window.fetch.bind(window), pause = (ms = 60) => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, value, detail) => { out.records.push({ name, passed: !!value, ...(detail === undefined ? {} : { detail }) }); if (!value) throw Error(name); };
  const until = async (read, label) => { const end = Date.now() + 25_000; while (Date.now() < end) { const value = await read(); if (value) return value; await pause(); } throw Error("timeout: " + label); };
  const visible = element => element && element.getClientRects().length && getComputedStyle(element).visibility !== "hidden";
  const button = (root, text) => [...(root || document).querySelectorAll("button")].find(node => visible(node) && (node.textContent.trim() === text || node.getAttribute("aria-label") === text));
  const click = async element => { if (!element || element.disabled) throw Error("Enabled real control required"); element.click(); await pause(); };
  const choose = async (element, value) => { if (!element) throw Error("Real select required"); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(element, value); element.dispatchEvent(new Event("change", { bubbles: true })); await pause(); };
  const call = async (path, payload) => { const response = await fetchReal("/api" + path, { credentials: "include", ...(payload === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) }); if (!response.ok) throw Error("Private HTTP " + response.status + " " + path); return response.json(); };
  const stage = name => { out.stages.push(name); out.current_stage = name; };
  const qaScope = window.__r96QaScope || "all";
  const downloads = [], urls = new Map();
  const createURL = URL.createObjectURL.bind(URL), revokeURL = URL.revokeObjectURL.bind(URL), anchorClick = HTMLAnchorElement.prototype.click;
  let oldReviewPosts = 0;
  window.fetch = async (...args) => {
    const path = String(args[0]), init = args[1] || {};
    if (init.method === "POST" && /\/quarantines\/[^/]+\/(?:review|reviews)/.test(path)) oldReviewPosts++;
    return fetchReal(...args);
  };
  URL.createObjectURL = blob => { const url = createURL(blob); urls.set(url, blob); return url; };
  URL.revokeObjectURL = url => { urls.delete(url); return revokeURL(url); };
  HTMLAnchorElement.prototype.click = function () {
    const blob = urls.get(this.href);
    if (!blob || !this.download) return anchorClick.call(this);
    downloads.push({ blob, filename: this.download, bytes: blob.size });
  };
  const raw = parent => parent?.querySelector(".raw-evidence-v2");
  const pdf = parent => raw(parent)?.textContent.includes("PDF 原件") && button(raw(parent), "核验并下载 PDF 原件");
  const inspectPdf = async (parent, hash, bytes, label) => {
    await until(() => pdf(parent) || raw(parent)?.querySelector('[role="alert"]'), label + " PDF metadata");
    check(label + " metadata passed the production decoder", !!pdf(parent), raw(parent)?.querySelector('[role="alert"]')?.textContent);
    const root = raw(parent);
    check(label + " displays hash and exact byte count", root.textContent.includes(hash) && root.textContent.includes(bytes.toLocaleString("zh-CN")));
    check(label + " has no embedded document or raw content link", !root.querySelector("iframe,object,embed") && ![...root.querySelectorAll("a")].some(a => /\/content\?/.test(a.href)));
    check(label + " accessible download control", !!button(root, "核验并下载 PDF 原件")?.textContent.trim());
  };
  const download = async (parent, expectedHash, expectedBytes, label) => {
    const before = downloads.length;
    await click(button(raw(parent), "核验并下载 PDF 原件"));
    await until(() => downloads.length > before || raw(parent)?.querySelector('[role="alert"]'), label + " download outcome");
    check(label + " reaches browser delivery once", downloads.length === before + 1, raw(parent)?.textContent.slice(0, 300));
    const delivered = downloads.at(-1), bytes = await delivered.blob.arrayBuffer();
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(v => v.toString(16).padStart(2, "0")).join("");
    check(label + " delivered bytes and filename match frozen SHA", hash === expectedHash && bytes.byteLength === expectedBytes && delivered.filename === `raw-evidence-${expectedHash}.pdf`);
  };
  const inspectText = async (parent, body, label) => {
    await until(() => raw(parent)?.textContent.includes("纯文本原件"), label + " text metadata");
    const root = raw(parent), details = [...root.querySelectorAll("details")].find(n => n.querySelector("summary")?.textContent.includes("展开纯文本原文"));
    details.open = true; await pause();
    check(label + " text is exact and inert", details.querySelector("pre")?.textContent === body && !details.querySelector("script,img,iframe,object,embed"));
    check(label + " text has no PDF action", !button(root, "核验并下载 PDF 原件"));
  };
  try {
    if (navigator.serviceWorker) { for (const registration of await navigator.serviceWorker.getRegistrations()) await registration.unregister(); }
    await call("/fixture/session", {});
    const fixture = await call("/fixture/state"), seed = fixture.seed;
    out.seed_binding = { source_bundle: seed.source_bundle, s2_sha256: seed.s2_sha256, s2_bytes: seed.s2_bytes };
    window.dispatchEvent(new Event("tire-session-revalidate")); await pause(200);
    location.hash = "#/sources";
    await until(() => button(document, "查看接收日志"), "sources authenticated");
    const capturePanel = () => document.querySelector('[aria-labelledby="capture-journal-title"]');
    const captureDetail = () => document.querySelector("#capture-evidence");
    const captureRow = bytes => [...capturePanel().querySelectorAll(".quarantine-item")].find(row => row.textContent.includes(bytes.toLocaleString("zh-CN") + " 字节"));
    async function openCapture(bytes) {
      if (!document.querySelector("#capture-journal-list")) await click(button(capturePanel(), "查看接收日志"));
      await until(() => captureRow(bytes), "capture row");
      const close = button(captureDetail(), "关闭接收原文"); if (close) await click(close);
      await click(button(captureRow(bytes), "核对接收原文"));
      await until(() => captureDetail(), "capture detail mounted");
    }
    stage("capture");
    await openCapture(seed.s2_bytes); await inspectPdf(captureDetail(), seed.s2_sha256, seed.s2_bytes, "capture");
    check("capture receipt boundary is explicit", captureDetail().textContent.includes("仅证明收到原件") && captureDetail().textContent.includes("已被采纳"));
    await download(captureDetail(), seed.s2_sha256, seed.s2_bytes, "capture");
    await openCapture(new TextEncoder().encode(seed.text_body).length); await inspectText(captureDetail(), seed.text_body, "capture");
    if (qaScope === "all") {
      stage("capture-failures");
      const metadataPath = "/v1/captures/" + seed.unknown_capture;
      for (const code of ["403", "404", "409", "503"]) {
        if (captureDetail()) await click(button(captureDetail(), "关闭接收原文"));
        await call("/fixture/fault", { path: metadataPath, action: code }); await openCapture(seed.unknown_bytes);
        await until(() => raw(captureDetail())?.querySelector('[role="alert"]'), "metadata " + code);
        check("metadata " + code + " fails closed", !pdf(captureDetail()));
      }
      await openCapture(seed.unknown_bytes); await inspectPdf(captureDetail(), seed.unknown_sha256, seed.unknown_bytes, "unknown capture");
      for (const action of ["source-mismatch", "query-state-mismatch"]) {
        const before = downloads.length;
        await call("/fixture/fault", { path: metadataPath, action });
        await click(button(raw(captureDetail()), "核验并下载 PDF 原件"));
        await until(() => raw(captureDetail())?.querySelector('[role="alert"]'), action);
        check(action + " rejects same PDF and clears qualification", downloads.length === before && !pdf(captureDetail()));
        await click(button(raw(captureDetail()), "重新读取原件")); await until(() => pdf(captureDetail()), "reload after mismatch");
      }
      await call("/fixture/fault", { path: metadataPath, action: "key-order" });
      await download(captureDetail(), seed.unknown_sha256, seed.unknown_bytes, "key order only");
      for (const invalidate of ["close", "selection", "owner"]) {
        const before = downloads.length;
        await call("/fixture/fault", { path: metadataPath + "/content", action: "hold" });
        await click(button(raw(captureDetail()), "核验并下载 PDF 原件"));
        await until(async () => (await call("/fixture/state")).held, "held content");
        check("pending repeated save is disabled " + invalidate, [...raw(captureDetail()).querySelectorAll("button")].some(node => node.disabled && node.textContent.includes("等待保存")));
        if (invalidate === "close") await click(button(captureDetail(), "关闭接收原文"));
        else if (invalidate === "selection") { await openCapture(new TextEncoder().encode(seed.text_body).length); await openCapture(seed.unknown_bytes); await until(() => pdf(captureDetail()), "A-B-A new display"); }
        else { await call("/fixture/session?account=other", {}); window.dispatchEvent(new Event("tire-session-revalidate")); await pause(100); }
        await call("/fixture/release", {}); await pause(250);
        check(invalidate + " invalidation prevents late browser delivery", downloads.length === before);
        if (invalidate === "owner") { await call("/fixture/session", {}); window.dispatchEvent(new Event("tire-session-revalidate")); await pause(250); }
        await openCapture(seed.unknown_bytes); await until(() => pdf(captureDetail()), "new capture after " + invalidate);
      }
    }
    await click(button(captureDetail(), "关闭接收原文"));
    stage("quarantine");
    const quarantineList = () => document.querySelector('[aria-labelledby="quarantine-title"]');
    const quarantineDetail = () => document.querySelector("#quarantine-evidence");
    await choose(quarantineList().querySelector("select"), "");
    await until(() => quarantineList().getAttribute("aria-busy") !== "true", "quarantine inventory settled");
    const quarantineInventory = await call("/v1/quarantines?mode=history");
    const quarantineRow = id => {
      const index = quarantineInventory.items.findIndex(item => item.id === id);
      if (index < 0) throw Error("Known quarantine ID absent from private HTTP inventory");
      const rows = quarantineList().querySelectorAll(".quarantine-list > .quarantine-item");
      return rows.length === quarantineInventory.items.length ? rows[index] : null;
    };
    const quarantinedRow = await until(() => quarantineRow(seed.binary_quarantine), "quarantine exact ID from real inventory");
    await click(button(quarantinedRow, "核对隔离原文"));
    await inspectPdf(quarantineDetail(), seed.s2_sha256, seed.s2_bytes, "quarantine");
    check("quarantine detail matches the selected exact ID", raw(quarantineDetail()).textContent.includes(seed.binary_quarantine));
    check("binary quarantine retains accepted false and no legacy approval", quarantineDetail().textContent.includes("accepted:false") && quarantineDetail().textContent.includes("二进制审批界面尚未接入") && !quarantineDetail().querySelector("form"));
    await download(quarantineDetail(), seed.s2_sha256, seed.s2_bytes, "quarantine");
    await click(button(quarantineDetail(), "关闭隔离原文"));
    const textRejectedRow = await until(() => quarantineRow(seed.text_quarantine), "text rejection exact ID from real inventory");
    await click(button(textRejectedRow, "核对隔离原文")); await inspectText(quarantineDetail(), seed.text_body, "quarantine");
    check("legacy text rejection retains accepted false", quarantineDetail().textContent.includes("accepted:false"));
    await click(button(quarantineDetail(), "关闭隔离原文"));
    stage("golden");
    await click(button(document, "管理 Golden 样本"));
    let dialog = await until(() => document.querySelector("dialog.golden-dialog[open]"), "golden modal");
    await choose(dialog.querySelector("select"), seed.source);
    const goldenArticle = await until(() => [...dialog.querySelectorAll(".parser-capture-options article")].find(row => row.textContent.includes(seed.binary_capture.slice(0, 12))), "golden capture");
    await click(goldenArticle.querySelector('input[type="radio"]')); await inspectPdf(dialog, seed.s2_sha256, seed.s2_bytes, "golden");
    check("Golden remains unconfirmed", dialog.textContent.includes("不代表 Golden 已经人工确认"));
    const goldenText = await until(() => [...dialog.querySelectorAll(".parser-capture-options article")].find(row => row.textContent.includes(seed.text_capture.slice(0, 12))), "golden text capture");
    await click(goldenText.querySelector('input[type="radio"]')); await inspectText(dialog, seed.text_body, "golden");
    await click(button(dialog, "关闭 Golden 工作区"));
    stage("parser-release");
    await click(button(document, "管理解析器发布"));
    dialog = await until(() => document.querySelector('dialog[aria-labelledby="parser-release-title"][open]'), "release modal");
    await choose(dialog.querySelector(".parser-release-toolbar select"), seed.source);
    await choose([...dialog.querySelectorAll("select")].find(node => [...node.options].some(o => o.value === "relative")), "relative");
    const releaseArticle = await until(() => [...dialog.querySelectorAll(".parser-capture-options article")].find(row => row.textContent.includes(seed.binary_capture.slice(0, 12))), "release capture");
    await click(button(releaseArticle, "核对这份原文")); await inspectPdf(dialog, seed.s2_sha256, seed.s2_bytes, "release");
    check("release original stays receipt only", dialog.querySelector(".parser-raw-preview").textContent.includes("receipt-only"));
    const releaseText = await until(() => [...dialog.querySelectorAll(".parser-capture-options article")].find(row => row.textContent.includes(seed.text_capture.slice(0, 12))), "release text");
    await click(button(releaseText, "核对这份原文")); await inspectText(dialog, seed.text_body, "release");
    await click(button(dialog, "关闭解析器发布"));
    stage("workbench-vehicle");
    location.hash = "#/vehicles";
    const vehiclePanel = await until(() => document.querySelector(".vehicle-query-controls"), "vehicle panel");
    async function vehicleHistory(vehicle, hash, bytes, text) {
      await choose(vehiclePanel.querySelector("select"), vehicle); await click(button(vehiclePanel, "在线核验配置"));
      await until(() => button(document, "仅本次允许"), "synthetic unavailable explicit consent");
      await click(button(document, "仅本次允许"));
      await until(() => button(document, "查看车型原始证据"), "historical vehicle config");
      check("vehicle history is visibly local snapshot " + vehicle, document.querySelector(".vehicle-fitment-panel").textContent.includes("历史车型配置"));
      await click(button(document, "查看车型原始证据"));
      const inspector = document.querySelector(".evidence-panel");
      if (text !== undefined) await inspectText(inspector, text, "workbench text"); else { await inspectPdf(inspector, hash, bytes, "workbench"); await download(inspector, hash, bytes, "workbench"); }
      await click(button(inspector, "关闭车型原件"));
    }
    await vehicleHistory(seed.vehicle, seed.s2_sha256, seed.s2_bytes);
    await vehicleHistory(seed.current_vehicle, null, null, seed.text_body);
    stage("interest"); location.hash = "#/watch";
    const notice = await until(() => [...document.querySelectorAll(".interest-center .quarantine-item")].find(row => row.querySelector("h3")?.textContent.startsWith("R96合成车型冻结历史 ·")), "private binary vehicle notification");
    await click(button(notice, "重开通知冻结证据"));
    dialog = await until(() => document.querySelector('dialog[aria-label="冻结的兴趣变化证据"][open]'), "frozen interest dialog");
    const binaryBinding = await until(() => [...dialog.querySelectorAll("details.interest-evidence")].find(node => node.querySelector("summary")?.textContent.includes(seed.binary_snapshot)), "binary frozen snapshot binding");
    await click(binaryBinding.querySelector("summary"));
    const reopen = await until(() => binaryBinding.open && button(binaryBinding, "按绑定版本重开原始记录"), "expanded frozen version action");
    await click(reopen); await inspectPdf(dialog, seed.s2_sha256, seed.s2_bytes, "interest");
    check("interest uses exact frozen snapshot", raw(dialog).textContent.includes(seed.binary_snapshot));
    await click(button(dialog, "关闭冻结证据"));
    const textNotice = await until(() => [...document.querySelectorAll(".interest-center .quarantine-item")].find(row => row.querySelector("h3")?.textContent.startsWith("R96合成文本车型冻结历史 ·")), "private text vehicle notification");
    await click(button(textNotice, "重开通知冻结证据"));
    dialog = await until(() => document.querySelector('dialog[aria-label="冻结的兴趣变化证据"][open]'), "frozen text interest dialog");
    const textBinding = await until(() => [...dialog.querySelectorAll("details.interest-evidence")].find(node => node.querySelector("summary")?.textContent.includes(seed.text_snapshot)), "text frozen snapshot binding");
    await click(textBinding.querySelector("summary"));
    await click(await until(() => textBinding.open && button(textBinding, "按绑定版本重开原始记录"), "expanded frozen text version action"));
    await inspectText(dialog, seed.text_body, "interest");
    check("text interest uses exact frozen snapshot", raw(dialog).textContent.includes(seed.text_snapshot));
    await click(button(dialog, "关闭冻结证据"));
    stage("layout");
    location.hash = "#/sources"; await pause(100);
    await openCapture(seed.s2_bytes); await inspectPdf(captureDetail(), seed.s2_sha256, seed.s2_bytes, "layout");
    check("document has no horizontal overflow", document.documentElement.scrollWidth <= innerWidth + 1, { scrollWidth: document.documentElement.scrollWidth, innerWidth });
    check("PDF original card has no horizontal overflow", raw(captureDetail()).scrollWidth <= raw(captureDetail()).clientWidth + 1);
    check("no binary old approval POST", oldReviewPosts === 0);
    const final = await call("/fixture/state");
    check("HTTP guard remains clean", final.guard_counts.external_network_attempts === 0 && final.guard_counts.child_process_attempts === 0 && final.guard_counts.normal_database_attempts === 0);
    out.deliveries = downloads.map(d => ({ bytes: d.bytes, filename: d.filename })); out.guard_counts = final.guard_counts;
    out.passed = true;
  } catch (error) { out.passed = false; out.error = String(error); }
  finally {
    window.fetch = fetchReal; URL.createObjectURL = createURL; URL.revokeObjectURL = revokeURL; HTMLAnchorElement.prototype.click = anchorClick;
    for (const url of urls.keys()) revokeURL(url);
    urls.clear(); downloads.length = 0;
    out.done = true; out.ended = new Date().toISOString(); window.__r96RawQa = out;
  }
  return out;
})();
