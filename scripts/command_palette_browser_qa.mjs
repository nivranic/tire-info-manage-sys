/** Pure frontend component QA: prepare is child/network free; run launches only private headless Chrome. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, relative, resolve } from "node:path";

const require = createRequire(import.meta.url);
const root = resolve(import.meta.dirname, "..");
const [action, rawOutput, reviewedSha] = process.argv.slice(2);
if (!["prepare", "run"].includes(action) || process.argv.length !== (action === "prepare" ? 4 : 5)) throw Error("Usage: node scripts/command_palette_browser_qa.mjs prepare fresh-output OR run prepared-output reviewed-prepare-sha256");
const output = resolve(rawOutput);
assert.equal(dirname(output), resolve(root, ".artifacts"));
assert.match(basename(output), /^command-palette-qa-[a-z0-9-]+$/);
const entry = resolve(root, "scripts/command_palette_browser_qa.tsx");
const loader = resolve(root, "scripts/command_palette_browser_qa_loader.cjs");
const playwrightPath = resolve(root, ".artifacts/browser-qa/python/playwright/driver/package/index.js");
const chrome = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const sha = value => createHash("sha256").update(value).digest("hex");
const input = path => {
  assert.ok(lstatSync(path).isFile() && !lstatSync(path).isSymbolicLink(), "nonregular input");
  const bytes = readFileSync(path);
  return { bytes: bytes.length, sha256: sha(bytes) };
};
const save = (name, value) => writeFileSync(resolve(output, name), JSON.stringify(value, null, 2) + "\n");
const initialPaths = [import.meta.filename, entry, loader, resolve(root, "apps/web/components/command-palette.tsx"), resolve(root, "apps/web/components/icons.tsx"), resolve(root, "apps/web/app/globals.css"), resolve(root, "apps/mobile/src/back-navigation.ts"), resolve(root, "tsconfig.json"), resolve(root, "package-lock.json"), require.resolve("typescript"), require.resolve("next/dist/compiled/webpack/webpack"), require.resolve("next/dist/compiled/webpack/bundle5"), playwrightPath, resolve(dirname(playwrightPath), "package.json"), process.execPath, chrome];
const snapshot = paths => Object.fromEntries([...new Set(paths)].sort().map(path => [path, input(path)]));

if (action === "prepare") {
  assert.ok(!existsSync(output), "fresh output required");
  mkdirSync(output);
  const before = snapshot(initialPaths);
  const ts = require("typescript");
  const config = ts.readConfigFile(resolve(root, "tsconfig.json"), ts.sys.readFile);
  assert.ok(!config.error, "base tsconfig readable");
  const options = ts.convertCompilerOptionsFromJson({ ...config.config.compilerOptions, jsx: "react-jsx", types: ["react", "react-dom"], incremental: false }, root);
  const program = ts.createProgram([entry], options.options);
  const diagnostics = [...options.errors, ...ts.getPreEmitDiagnostics(program)];
  const errors = diagnostics.map(item => ({ file: item.file ? relative(root, item.file.fileName) : null, line: item.file && item.start !== undefined ? item.file.getLineAndCharacterOfPosition(item.start).line + 1 : null, message: ts.flattenDiagnosticMessageText(item.messageText, "\n") }));
  save("typecheck.json", { scope: "fixture and its actual CommandPalette/Icon/mobile-back imports", errors });
  assert.equal(errors.length, 0, "targeted TypeScript check failed; see typecheck.json");
  const { webpack } = require("next/dist/compiled/webpack/webpack");
  const compiler = webpack({ mode: "development", context: root, target: "web", entry, cache: false, devtool: false,
    output: { path: output, filename: "fixture.js" }, optimization: { minimize: false }, performance: false,
    resolve: { extensions: [".tsx", ".ts", ".js"] }, infrastructureLogging: { level: "none" },
    module: { rules: [{ test: /\.tsx?$/, include: [resolve(root, "apps/web/components"), resolve(root, "apps/mobile/src"), resolve(root, "scripts")], use: [loader] }] },
  });
  const stats = await new Promise((done, fail) => compiler.run((error, result) => error ? fail(error) : done(result)));
  await new Promise((done, fail) => compiler.close(error => error ? fail(error) : done()));
  const summary = stats.toJson({ all: false, errors: true, warnings: true });
  save("compile.json", summary);
  assert.ok(!stats.hasErrors(), "bundle failed; see compile.json");
  const dependencyPaths = [...stats.compilation.fileDependencies].filter(path => existsSync(path) && lstatSync(path).isFile());
  assert.deepEqual(snapshot(initialPaths), before, "source changed during prepare");
  const inputs = snapshot([...initialPaths, ...dependencyPaths, resolve(output, "fixture.js")]);
  const prepared = { schema: "command-palette-browser-qa@1", scope: "isolated real React component and shared mobile DOM-back helper", output, node: realpathSync(process.execPath), inputs,
    browser: { executablePath: chrome, headless: true, profile: resolve(output, "chrome-profile"), transport: "Playwright remote-debugging-pipe; no listener or service", args: ["--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-breakpad", "--no-first-run", "--no-default-browser-check"], launchTimeoutMs: 20000, testTimeoutMs: 120000, closeTimeoutMs: 15000 },
    no_normal_api_web_database_provider: true, no_python_process: true, normal_user_profile_used: false };
  save("prepare.json", prepared);
  console.log(JSON.stringify({ prepared_not_launched: true, output, prepare_sha256: input(resolve(output, "prepare.json")).sha256, input_count: Object.keys(inputs).length, targeted_typecheck_errors: 0, bundle_errors: 0 }));
  process.exit(0);
}

assert.ok(lstatSync(output).isDirectory() && !lstatSync(output).isSymbolicLink(), "regular output required");
assert.equal(input(resolve(output, "prepare.json")).sha256, reviewedSha, "reviewed prepare hash mismatch");
const prepared = JSON.parse(readFileSync(resolve(output, "prepare.json"), "utf8"));
assert.equal(prepared.schema, "command-palette-browser-qa@1");
assert.equal(prepared.output, output);
assert.equal(prepared.node, realpathSync(process.execPath));
assert.deepEqual(snapshot(Object.keys(prepared.inputs)), prepared.inputs, "prepared inputs drifted");
assert.ok(!existsSync(resolve(output, "report.json")), "single-use run required");
const report = { scope: prepared.scope, status: "running", ui_checks: [], screenshots: [], geometry: [], page_errors: [], console_errors: [], unexpected_requests: [], lifecycle: { launched: false, context_closed: false }, normal_api_web_database_provider_used: false, python_process_started: false, actual_device_back_verified: false, real_screenreader_verified: false, complete_wcag_gate_verified: false };
const persist = () => save("report.json", report);
persist();
const { chromium } = require(playwrightPath);
let context;
let timeout;
const checked = (width, name) => { report.ui_checks.push({ width, name }); persist(); };
const raf = page => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
const focus = async (page, selector) => { await page.waitForFunction(value => document.activeElement?.matches(value), selector, { timeout: 5000 }); };
const open = async page => { await page.locator("#opener").click(); await focus(page, '.palette-backdrop input[role="combobox"]'); await raf(page); };
const closed = async page => page.waitForFunction(() => !document.querySelector(".palette-backdrop"), null, { timeout: 5000 });
const aria = async (page, label) => {
  const state = await page.evaluate(() => {
    const input = document.querySelector('[role="combobox"]');
    const id = input?.getAttribute("aria-activedescendant");
    const option = id ? document.getElementById(id) : null;
    const ids = [...document.querySelectorAll("[id]")].map(node => node.id);
    return { option: option?.querySelector("span")?.textContent ?? null, selected: option?.getAttribute("aria-selected") ?? null,
      role: option?.getAttribute("role") ?? null, unique: ids.length === new Set(ids).size, id,
      listbox: document.getElementById(input?.getAttribute("aria-controls") || "")?.getAttribute("role"),
      selectedCount: document.querySelectorAll('[role="option"][aria-selected="true"]').length };
  });
  assert.equal(state.unique, true);
  assert.equal(state.listbox, "listbox");
  assert.equal(state.option, label);
  assert.equal(state.selectedCount, label === null ? 0 : 1);
  if (label === null) assert.equal(state.id, null);
  else { assert.equal(state.role, "option"); assert.equal(state.selected, "true"); }
};

async function suite(page, width) {
  const query = page.getByRole("combobox", { name: "搜索命令" });
  await page.locator("#opener").focus();
  await page.keyboard.press("Control+k");
  await focus(page, '[role="combobox"]');
  assert.equal(await page.locator(".palette-backdrop").evaluate(node => node.matches(":modal")), true);
  await aria(page, "跳转查询");
  await page.keyboard.press("Control+k"); await closed(page); await focus(page, "#opener");
  checked(width, "control_k_open_close_modal_initial_focus_restore");
  await page.keyboard.press("Meta+k"); await focus(page, '[role="combobox"]');
  await page.keyboard.press("Meta+k"); await closed(page); await focus(page, "#opener");
  checked(width, "meta_k_open_close_without_workbench_reopen");

  await open(page);
  await page.keyboard.press("ArrowDown"); await aria(page, "跳转证据");
  await page.keyboard.press("ArrowUp"); await aria(page, "跳转查询");
  await page.keyboard.press("ArrowUp"); await aria(page, "跳转查询");
  await query.fill("evidence"); await aria(page, "跳转证据");
  const before = await page.evaluate(() => window.paletteQA.runs.length);
  await page.keyboard.press("Enter"); await closed(page); await focus(page, "#opener");
  assert.deepEqual(await page.evaluate(() => window.paletteQA.runs.slice(-1)), ["second"]);
  assert.equal(await page.evaluate(() => window.paletteQA.runs.length), before + 1);
  checked(width, "arrows_filter_aria_selected_and_enter_once");

  await open(page); await query.fill("不存在xyz"); await aria(page, null);
  const emptyBefore = await page.evaluate(() => window.paletteQA.runs.length);
  for (const key of ["ArrowDown", "ArrowUp", "Enter"]) await page.keyboard.press(key);
  await aria(page, null); assert.equal(await page.evaluate(() => window.paletteQA.runs.length), emptyBefore);
  await query.fill(""); await aria(page, "跳转查询");
  await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowDown");
  await aria(page, "打开业务弹窗");
  await page.evaluate(() => window.paletteQA.setCount(1)); await aria(page, "跳转查询");
  await page.evaluate(() => window.paletteQA.setCount(0)); await aria(page, null);
  await page.evaluate(() => window.paletteQA.setCount(4)); await aria(page, "跳转查询");
  checked(width, "empty_enter_no_execution_and_dynamic_commands_clamp_no_dangling_idrefs");

  for (const key of ["Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab"]) {
    await page.keyboard.press(key);
    assert.equal(await page.evaluate(() => !!document.activeElement?.closest("dialog.palette-backdrop[open]")), true);
    assert.equal(await page.evaluate(() => ["opener", "background", "command-focus-target"].includes(document.activeElement?.id || "")), false);
  }
  await page.getByRole("button", { name: "关闭命令面板" }).focus();
  await page.keyboard.press("Enter"); await closed(page); await focus(page, "#opener");
  assert.equal(await page.evaluate(() => window.paletteQA.runs.length), emptyBefore);
  checked(width, "native_tab_shift_tab_background_inert_explicit_close_keyboard");
  await open(page); await page.getByRole("button", { name: "关闭命令面板" }).focus();
  await page.keyboard.press("Control+k"); await closed(page); await focus(page, "#opener");
  await open(page); await page.getByRole("option").nth(1).focus();
  await page.keyboard.press("Meta+k"); await closed(page); await focus(page, "#opener");
  checked(width, "control_meta_k_from_close_button_and_at_focused_option");

  await open(page);
  const option = page.getByRole("option").nth(1);
  const optionBox = await option.boundingBox();
  const rowBox = await page.locator(".palette-input-row").boundingBox();
  await page.mouse.move(optionBox.x + 20, optionBox.y + 20); await page.mouse.down();
  await focus(page, '[role="option"]');
  await page.mouse.move(rowBox.x + 2, rowBox.y + 2); await page.mouse.up();
  assert.equal(await page.locator(".palette-backdrop").count(), 1);
  assert.equal(await page.evaluate(() => window.paletteQA.runs.length), emptyBefore);
  await page.keyboard.press("Escape"); await closed(page); await focus(page, "#opener");
  checked(width, "real_pointer_down_drag_release_option_focus_then_escape");

  await open(page); await page.getByRole("option").nth(1).focus(); await aria(page, "跳转证据");
  await page.keyboard.press("Escape"); await closed(page); await focus(page, "#opener");
  checked(width, "programmatic_at_style_option_focus_then_keyboard_escape");
  await open(page); await page.getByRole("option").nth(1).focus();
  await page.keyboard.press("Enter"); await closed(page);
  assert.equal(await page.evaluate(() => window.paletteQA.runs.length), emptyBefore + 1);
  checked(width, "focused_option_enter_once_without_button_default_duplicate");

  await open(page);
  const composingBefore = await page.evaluate(() => window.paletteQA.runs.length);
  for (const key of ["ArrowDown", "ArrowUp", "Escape", "Enter"]) {
    await query.evaluate((node, value) => node.dispatchEvent(new KeyboardEvent("keydown", { key: value, code: value, isComposing: true, bubbles: true, cancelable: true })), key);
    assert.equal(await page.locator(".palette-backdrop").count(), 1);
    assert.equal(await page.evaluate(() => window.paletteQA.runs.length), composingBefore);
    await aria(page, "跳转查询");
  }
  await query.fill("focus"); await page.keyboard.press("Enter"); await closed(page); await raf(page); await focus(page, "#command-focus-target");
  checked(width, "composing_arrow_escape_enter_event_contract_and_command_focus_priority_not_os_ime");
  await open(page); await query.fill("dialog"); await page.keyboard.press("Enter"); await closed(page); await raf(page); await focus(page, "#business-input");
  assert.equal(await page.getByRole("dialog", { name: "业务弹窗" }).evaluate(node => node.matches(":modal")), true);
  await page.keyboard.press("Escape");
  checked(width, "command_opens_business_dialog_after_leaving_palette_modal_focus_retained");

  await open(page);
  assert.equal(await page.evaluate(() => window.paletteQA.mobileBack()), true);
  await closed(page); await focus(page, "#opener");
  assert.equal(await page.evaluate(() => window.paletteQA.backRoutes), 0);
  checked(width, "real_mobile_back_helper_cancel_dom_path_without_workbench_route");
  await open(page); await page.mouse.click(4, 4); await closed(page); await focus(page, "#opener");
  assert.equal(await page.evaluate(() => window.paletteQA.backgroundClicks), 0);
  checked(width, "backdrop_pointer_dismiss_without_background_click");

  const frames = await page.evaluate(() => {
    const originalRaf = window.requestAnimationFrame, originalCancel = window.cancelAnimationFrame;
    const pending = new Map(); let serial = 100000;
    window.requestAnimationFrame = callback => { const id = ++serial; pending.set(id, callback); return id; };
    window.cancelAnimationFrame = id => { pending.delete(id); };
    try {
      document.getElementById("opener").focus();
      window.paletteQA.setOpen(true); const opening = pending.size;
      window.paletteQA.setOpen(false); const closing = pending.size;
      document.getElementById("command-focus-target").focus();
      for (const callback of pending.values()) callback(performance.now()); pending.clear();
      const preserved = document.activeElement.id === "command-focus-target";
      document.getElementById("opener").focus(); window.paletteQA.setOpen(true);
      const reopening = pending.size;
      window.paletteQA.unmount(); const unmounted = pending.size;
      const restored = document.activeElement.id === "opener";
      window.paletteQA.remountOpen(); const strictMode = pending.size;
      for (const callback of pending.values()) callback(performance.now()); pending.clear();
      return { opening, closing, preserved, reopening, unmounted, restored, strictMode, focus: document.activeElement.getAttribute("role"), modal: !!document.querySelector(".palette-backdrop:modal") };
    } finally { window.requestAnimationFrame = originalRaf; window.cancelAnimationFrame = originalCancel; }
  });
  assert.deepEqual(frames, { opening: 1, closing: 0, preserved: true, reopening: 1, unmounted: 0, restored: true, strictMode: 1, focus: "combobox", modal: true });
  await page.keyboard.press("Escape"); await closed(page);
  checked(width, "held_raf_close_reopen_unmount_and_strictmode_cancel_stale_frames");

  for (const theme of ["light", "dark"]) {
    await page.locator("main").evaluate((node, value) => { node.dataset.theme = value; }, theme);
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await open(page); await page.keyboard.press("Tab");
    const layout = await page.evaluate(() => {
      const card = document.querySelector(".command-palette"), close = document.querySelector(".palette-close"), input = document.querySelector('[role="combobox"]');
      const rect = node => { const r = node.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth }; };
      const active = document.activeElement;
      return { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth, card: rect(card), close: rect(close), input: rect(input), focusVisible: active.matches(":focus-visible"), outlineStyle: getComputedStyle(active).outlineStyle, outlineWidth: getComputedStyle(active).outlineWidth, reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches };
    });
    assert.ok(layout.documentWidth <= width && layout.card.left >= 0 && layout.card.right <= width && layout.card.bottom <= layout.height);
    assert.ok(layout.card.scrollWidth <= layout.card.clientWidth && layout.input.height >= 44 && layout.close.width >= 44 && layout.close.height >= 44);
    assert.ok(layout.focusVisible && layout.outlineStyle !== "none" && layout.outlineWidth !== "0px" && layout.reducedMotion);
    report.geometry.push({ width, theme, ...layout });
    const screenshot = `palette-${width}-${theme}.png`;
    await page.screenshot({ path: resolve(output, screenshot) }); report.screenshots.push(screenshot);
    await page.keyboard.press("Escape"); await closed(page);
    checked(width, `${theme}_reduced_motion_44px_targets_visible_focus_no_overflow`);
  }
  await page.locator("main").evaluate(node => { node.style.zoom = "2"; });
  await open(page);
  const zoom = await page.locator(".command-palette").evaluate(node => ({ left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, viewport: innerWidth }));
  assert.ok(zoom.left >= 0 && zoom.right <= zoom.viewport && zoom.scrollWidth <= zoom.clientWidth);
  report.geometry.push({ width, css_zoom_200_percent: true, ...zoom });
  await page.keyboard.press("Escape"); await closed(page);
  checked(width, "css_zoom_200_percent_horizontal_reflow_only_not_browser_zoom_acceptance");
  await page.locator("main").evaluate(node => { node.style.zoom = ""; });
  await open(page); await page.locator("#opener").evaluate(node => node.remove());
  await page.keyboard.press("Escape"); await closed(page); await raf(page);
  const detachedFocus = await page.evaluate(() => ({ connected: !!document.activeElement?.isConnected, palette: !!document.activeElement?.closest(".palette-backdrop"), tag: document.activeElement?.tagName, id: document.activeElement?.id }));
  assert.ok(detachedFocus.connected && !detachedFocus.palette);
  await raf(page);
  assert.deepEqual(await page.evaluate(() => ({ connected: !!document.activeElement?.isConnected, palette: !!document.activeElement?.closest(".palette-backdrop"), tag: document.activeElement?.tagName, id: document.activeElement?.id })), detachedFocus);
  checked(width, "removed_opener_close_no_detached_focus_or_late_focus");
}

try {
  context = await chromium.launchPersistentContext(prepared.browser.profile, { executablePath: prepared.browser.executablePath, headless: true, args: prepared.browser.args, timeout: prepared.browser.launchTimeoutMs, serviceWorkers: "block", viewport: { width: 1440, height: 1000 } });
  report.lifecycle.launched = true;
  await context.route("**/*", route => { report.unexpected_requests.push({ url: route.request().url().split("?")[0] }); return route.abort(); });
  const run = async () => {
    for (const [width, height] of [[1440, 1000], [390, 844], [320, 740]]) {
      const page = await context.newPage(); await page.setViewportSize({ width, height }); page.setDefaultTimeout(5000);
      page.on("pageerror", error => report.page_errors.push({ name: error.name, message: error.message.slice(0, 240) }));
      page.on("console", event => { if (event.type() === "error") report.console_errors.push(event.text().slice(0, 240)); });
      await page.setContent('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>命令面板隔离验证</title></head><body><div id="root"></div></body></html>');
      await page.addStyleTag({ content: readFileSync(resolve(root, "apps/web/app/globals.css"), "utf8") });
      await page.addScriptTag({ content: readFileSync(resolve(output, "fixture.js"), "utf8") });
      await page.waitForFunction(() => !!window.paletteQA); await suite(page, width); await page.close();
    }
  };
  await Promise.race([run(), new Promise((_, reject) => { timeout = setTimeout(() => reject(Error("component browser QA deadline exceeded")), prepared.browser.testTimeoutMs); })]);
  assert.deepEqual(report.page_errors, []); assert.deepEqual(report.console_errors, []); assert.deepEqual(report.unexpected_requests, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = { name: error.name, message: error.message.slice(0, 1200), stack: error.stack?.slice(0, 2400) };
  process.exitCode = 1;
} finally {
  clearTimeout(timeout);
  if (context) {
    let closingTimeout;
    try { await Promise.race([context.close(), new Promise((_, reject) => { closingTimeout = setTimeout(() => reject(Error("browser close deadline exceeded")), prepared.browser.closeTimeoutMs); })]); report.lifecycle.context_closed = true; }
    catch (error) { report.status = "failed"; report.lifecycle.close_error = error.message.slice(0, 240); process.exitCode = 1; }
    finally { clearTimeout(closingTimeout); }
  }
  try { assert.deepEqual(snapshot(Object.keys(prepared.inputs)), prepared.inputs); report.inputs_unchanged = true; }
  catch { report.inputs_unchanged = false; report.status = "failed"; process.exitCode = 1; }
  persist();
  console.log(JSON.stringify({ status: report.status, output, checks: report.ui_checks.length, lifecycle: report.lifecycle, inputs_unchanged: report.inputs_unchanged, error: report.error }));
}
