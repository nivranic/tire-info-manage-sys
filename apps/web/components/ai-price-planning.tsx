"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIPricePlanningRequest, AIPricePlanningResult, AIPriceProvider,
  AIPriceVersion, AIPriceVersionCreate, AIPriceVersionPage } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";

const PAGE_SIZE = 10;
const providerLabels: Record<AIPriceProvider, string> = {
  openai_responses: "OpenAI Responses", openai_chat: "OpenAI Chat Completions",
  anthropic: "Anthropic Messages", openai_embeddings: "OpenAI Embeddings",
};
const ratePattern = /^(0|[1-9][0-9]{0,8})(\.[0-9]{1,8})?$/;
const zeroRate = (value: string) => /^0(?:\.0+)?$/.test(value);
const planningNotice = "只按所选人工价格与工作量进行费用规划，价格未在线核验；不是实际消费、供应商账单或金额硬预算。";
const exclusionLabels: Record<AIPricePlanningResult["exclusions"][number], string> = {
  cached_input: "缓存输入折扣", tools: "工具费用", long_context: "长上下文阶梯",
  images_audio_video: "图像、音频与视频", tax: "税费", fx: "汇率换算", supplier_adjustments: "供应商其他调整",
};
type PriceDraft = Omit<AIPriceVersionCreate, "source_url" | "effective_until"> & { source_url: string; effective_until: string };
type PlanningDraft = { planned_for: string; request_count: string; input_tokens_per_request: string; output_tokens_per_request: string };
type Attempt = { key: string; payload: AIPriceVersionCreate };
const blankPrice = (): PriceDraft => ({ vendor_label: "", provider: "openai_responses", model: "", currency: "",
  input_per_million: "", output_per_million: "", source_note: "", source_url: "", effective_from: "", effective_until: "" });
const blankPlanning = (): PlanningDraft => ({ planned_for: new Date().toISOString(), request_count: "1", input_tokens_per_request: "0", output_tokens_per_request: "0" });

/** Validate UTC calendar syntax without converting prices or discarding microseconds. */
function utcKey(value: string): string | null {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$/.exec(value);
  if (!match || value.startsWith("0000-")) return null;
  const date = new Date(`${match[1]}Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 19) !== match[1]) return null;
  return `${match[1]}.${(match[2] || "").padEnd(6, "0")}Z`;
}
function safeSourceUrl(value: string): boolean {
  if (value.length > 2048 || /[\u0000-\u001f\u007f\\]/.test(value) || !/^https?:\/\//i.test(value)) return false;
  try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) && !!url.hostname && !url.username && !url.password; }
  catch { return false; }
}
function operationError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const messages: Record<string, string> = {
      login_required: "请先登录，再读取价格或进行费用规划。",
      admin_required: "追加价格需要管理员权限，请重新确认账户。",
      ai_price_version_not_found: "找不到所选价格版本，未生成金额；请重新读取并选择版本。",
      ai_price_version_not_effective: "所选价格版本不覆盖规划时点，未生成金额；请核对 UTC 时间和版本有效期。",
      ai_price_idempotency_conflict: "本次提交与此前内容冲突，未追加价格；请重新核对表单。",
    };
    return messages[cause.code || ""] || (cause.status === 422 ? "输入不符合价格或费用规划规则，请核对金额字符串、UTC 日期和整数范围。" : "操作未完成，请重新确认账户并重试。");
  }
  return "未收到可确认的响应，请检查连接后重试。";
}
function validatePrice(value: PriceDraft): string {
  if (!value.vendor_label.trim() || value.vendor_label.trim().length > 100) return "请填写 1–100 字符的人工厂商 / 计费方标签。";
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(value.model)) return "模型需为精确标识，最多 120 位，仅含字母、数字、点、下划线、冒号或连字符。";
  if (!/^[A-Z]{3}$/.test(value.currency)) return "币种需为三个大写英文字母。";
  if (!ratePattern.test(value.input_per_million) || !ratePattern.test(value.output_per_million)) return "输入和输出费率需为非负十进制字符串，最多 9 位整数、8 位小数；不使用指数、空白或前导零。";
  if (value.provider === "openai_embeddings" && !zeroRate(value.output_per_million)) return "Embeddings 的输出费率必须为零。";
  if (!value.source_note.trim() || value.source_note.trim().length > 1000) return "请填写 1–1000 字符的人工来源说明。";
  if (value.source_url && !safeSourceUrl(value.source_url)) return "来源链接需为无凭据和控制字符的完整 HTTP(S) URL。";
  const from = utcKey(value.effective_from), until = value.effective_until ? utcKey(value.effective_until) : null;
  if (!from || value.effective_until && !until) return "有效期需为 UTC 时间，格式为 YYYY-MM-DDTHH:mm:ss[.小数秒]Z。";
  if (until && until <= from) return "有效结束时间必须晚于开始时间。";
  return "";
}
function integerInput(value: string, minimum: number, maximum: number): number | null {
  if (!/^(0|[1-9][0-9]*)$/.test(value) || value.length > 9) return null;
  const count = Number(value);
  return Number.isSafeInteger(count) && count >= minimum && count <= maximum ? count : null;
}

function PriceDetails({ version }: { version: AIPriceVersion }) {
  return <dl className="ai-price-meta">
    <div><dt>版本 ID</dt><dd className="mono">{version.id}</dd></div>
    <div><dt>人工厂商 / 计费方</dt><dd>{version.vendor_label}</dd></div>
    <div><dt>协议 / 精确模型</dt><dd>{providerLabels[version.provider]} · <code>{version.model}</code></dd></div>
    <div><dt>币种 / 每百万 tokens 费率</dt><dd>{version.currency} · 输入 <code>{version.input_per_million}</code> · 输出 <code>{version.output_per_million}</code>{zeroRate(version.input_per_million) && zeroRate(version.output_per_million) ? " · 已明确录入零价" : ""}</dd></div>
    <div><dt>有效期（UTC，含开始、不含结束）</dt><dd><time>{version.effective_from}</time> 至 {version.effective_until ? <time>{version.effective_until}</time> : "无结束上界"}</dd></div>
    <div><dt>人工来源说明 · 未在线核验</dt><dd>{version.source_note}</dd></div>
    <div><dt>来源链接</dt><dd>{version.source_url && safeSourceUrl(version.source_url) ? <a href={version.source_url} target="_blank" rel="noopener noreferrer">{version.source_url}（人工提供，未在线核验）</a> : "未提供可打开的来源链接"}</dd></div>
    <div><dt>记录时间（UTC）/ 录入账户</dt><dd><time>{version.recorded_at}</time> · {version.actor_user_id}</dd></div>
  </dl>;
}

export default function AiPricePlanning() {
  const auth = useWorkbenchAuth();
  return <section className="ai-price-panel" aria-labelledby="ai-price-title">
    <div className="panel-title"><span id="ai-price-title">AI 费用规划</span></div>
    <p className="ai-price-intro">{planningNotice} 既有 Token 护栏与历史用量独立记账，不为历史或预留量补算消费金额。</p>
    {!auth.ready ? <p className="ai-price-intro" role="status">正在确认账户，旧价格、草稿与结果暂不显示。</p>
      : !auth.state.authenticated || !auth.state.user ? <p className="ai-price-intro" role="status">登录后可读取人工价格版本并进行费用规划；管理员可以追加新版本。</p>
      : <PriceWorkspace key={`${auth.ownerEpoch}:${auth.state.user.id}:${auth.state.user.is_admin}`} ownerEpoch={auth.ownerEpoch} />}
  </section>;
}

function PriceWorkspace({ ownerEpoch }: { ownerEpoch: number }) {
  const auth = useWorkbenchAuth();
  const [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<AIPriceVersionPage | null>(null), [listBusy, setListBusy] = useState(true), [listError, setListError] = useState("");
  const [selected, setSelected] = useState<AIPriceVersion | null>(null), [planning, setPlanning] = useState(blankPlanning);
  const [planBusy, setPlanBusy] = useState(false), [planError, setPlanError] = useState(""), [result, setResult] = useState<AIPricePlanningResult | null>(null);
  const [draft, setDraft] = useState(blankPrice), [createBusy, setCreateBusy] = useState(false), [createError, setCreateError] = useState("");
  const [retryAvailable, setRetryAvailable] = useState(false), [created, setCreated] = useState<AIPriceVersion | null>(null);
  const attempt = useRef<Attempt | null>(null), creating = useRef(false);
  const requests = useRef(new Set<AbortController>());
  const listGeneration = useRef(0), planGeneration = useRef(0), createGeneration = useRef(0);
  const planController = useRef<AbortController | null>(null);
  const current = useCallback((controller: AbortController) => !controller.signal.aborted && !auth.ownerSignal.aborted && auth.isCurrentOwner(ownerEpoch), [auth.ownerSignal, auth.isCurrentOwner, ownerEpoch]);
  const requestController = () => { const controller = new AbortController(); requests.current.add(controller); if (auth.ownerSignal.aborted || !auth.isCurrentOwner(ownerEpoch)) controller.abort(); return controller; };

  useEffect(() => {
    const controllers = requests.current;
    const cancel = () => { controllers.forEach(controller => controller.abort()); controllers.clear(); attempt.current = null; };
    auth.ownerSignal.addEventListener("abort", cancel, { once: true });
    if (auth.ownerSignal.aborted) cancel();
    return () => { auth.ownerSignal.removeEventListener("abort", cancel); cancel(); };
  }, [auth.ownerSignal]);

  useEffect(() => {
    const controller = new AbortController(), generation = ++listGeneration.current;
    requests.current.add(controller); setListBusy(true); setListError(""); setPage(null);
    if (auth.ownerSignal.aborted || !auth.isCurrentOwner(ownerEpoch)) controller.abort();
    void tireApi.aiPriceVersions(controller.signal, offset, PAGE_SIZE).then(value => {
      if (current(controller) && generation === listGeneration.current) setPage(value);
    }).catch(cause => { if (current(controller) && generation === listGeneration.current) setListError(operationError(cause)); })
      .finally(() => { requests.current.delete(controller); if (current(controller) && generation === listGeneration.current) setListBusy(false); });
    return () => { controller.abort(); requests.current.delete(controller); };
  }, [offset, refresh, ownerEpoch, auth.ownerSignal, auth.isCurrentOwner, current]);

  function invalidatePlan() {
    planController.current?.abort(); planGeneration.current++; setPlanBusy(false); setPlanError(""); setResult(null);
  }
  function chooseVersion(version: AIPriceVersion | null) {
    invalidatePlan(); setSelected(version);
    if (version?.provider === "openai_embeddings") setPlanning(value => ({ ...value, output_tokens_per_request: "0" }));
  }
  function changePlanning(field: keyof PlanningDraft, value: string) { invalidatePlan(); setPlanning(previous => ({ ...previous, [field]: value })); }
  function changePrice(patch: Partial<PriceDraft>) {
    attempt.current = null; setRetryAvailable(false); setCreateError(""); setCreated(null); setDraft(value => ({ ...value, ...patch }));
  }
  async function submitPlanning(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!auth.isCurrentOwner(ownerEpoch) || auth.ownerSignal.aborted) return;
    invalidatePlan();
    if (!selected) { setPlanError("请明确选择一个价格版本；缺少价格不能作为零价计算。"); return; }
    const time = utcKey(planning.planned_for);
    if (!time) { setPlanError("规划时间需为有效 UTC 日期，格式为 YYYY-MM-DDTHH:mm:ss[.小数秒]Z；历史与未来均可。"); return; }
    const from = utcKey(selected.effective_from), until = selected.effective_until ? utcKey(selected.effective_until) : null;
    if (!from || time < from || until && time >= until) { setPlanError("所选价格版本不覆盖规划时点，未生成金额；有效期含开始、不含结束。"); return; }
    const count = integerInput(planning.request_count, 1, 1000000), input = integerInput(planning.input_tokens_per_request, 0, 100000000), output = integerInput(planning.output_tokens_per_request, 0, 100000000);
    if (count === null || input === null || output === null) { setPlanError("请求次数需为 1–1,000,000 整数；每次输入 / 输出 tokens 需为 0–100,000,000 整数。"); return; }
    if (selected.provider === "openai_embeddings" && output !== 0) { setPlanError("Embeddings 的每次输出 tokens 必须为零。"); return; }
    const payload: AIPricePlanningRequest = { planned_for: planning.planned_for, items: [{ price_version_id: selected.id, request_count: count, input_tokens_per_request: input, output_tokens_per_request: output }] };
    const controller = requestController(), generation = ++planGeneration.current; planController.current = controller; setPlanBusy(true);
    try { const value = await tireApi.aiPricePlanning(payload, controller.signal); if (current(controller) && generation === planGeneration.current) setResult(value); }
    catch (cause) { if (current(controller) && generation === planGeneration.current) setPlanError(operationError(cause)); }
    finally { requests.current.delete(controller); if (current(controller) && generation === planGeneration.current) setPlanBusy(false); }
  }
  async function submitPrice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (creating.current || !auth.isCurrentOwner(ownerEpoch) || auth.ownerSignal.aborted || !auth.state.user?.is_admin) return;
    const error = validatePrice(draft); setCreateError(error); if (error) return;
    const payload: AIPriceVersionCreate = { ...draft, vendor_label: draft.vendor_label.trim(), source_note: draft.source_note.trim(),
      source_url: draft.source_url || null, effective_until: draft.effective_until || null };
    if (!attempt.current || JSON.stringify(attempt.current.payload) !== JSON.stringify(payload)) {
      attempt.current = { key: crypto.randomUUID(), payload };
    }
    const pending = attempt.current, controller = requestController(), generation = ++createGeneration.current;
    creating.current = true; setCreateBusy(true); setCreated(null); setCreateError("");
    try {
      const value = await tireApi.aiPriceVersionCreate(pending.payload, pending.key, controller.signal);
      if (current(controller) && generation === createGeneration.current) {
        attempt.current = null; setRetryAvailable(false); setCreated(value); setOffset(0); setRefresh(value => value + 1);
      }
    } catch (cause) {
      if (current(controller) && generation === createGeneration.current) { setRetryAvailable(true); setCreateError(operationError(cause)); }
    } finally {
      requests.current.delete(controller);
      if (current(controller) && generation === createGeneration.current) { creating.current = false; setCreateBusy(false); }
    }
  }
  const choices = selected && !page?.items.some(item => item.id === selected.id) ? [selected, ...(page?.items || [])] : page?.items || [];

  return <div className="ai-price-workspace">
    <section aria-labelledby="ai-price-versions-title">
      <div className="ai-price-heading"><h3 id="ai-price-versions-title">人工价格版本</h3><button type="button" className="text-button" disabled={listBusy} onClick={() => { setOffset(0); setRefresh(value => value + 1); }}>刷新最新版本</button></div>
      <p>仅展示本页记录；更早版本可继续翻页。协议不代表已核验厂商或计费账户。版本只追加，修正价格需追加新版本。</p>
      {listBusy ? <p role="status">正在读取价格版本…</p> : null}
      {listError ? <p className="inline-error" role="alert">{listError}<button type="button" className="text-button" onClick={() => setRefresh(value => value + 1)}>重试读取</button></p> : null}
      {page && !page.items.length ? <p role="status">本页没有价格版本。缺少人工价格不能视为零价；请由管理员追加价格或返回上一页。</p> : null}
      <div className="ai-price-versions">{page?.items.map(version => <article key={version.id} className="ai-price-version">
        <h4>{version.vendor_label} · {version.model}</h4><PriceDetails version={version} />
        <button type="button" className="secondary-button compact" aria-pressed={selected?.id === version.id} onClick={() => chooseVersion(version)}>{selected?.id === version.id ? "已选此版本" : "选择此版本进行规划"}</button>
      </article>)}</div>
      <div className="ai-price-pages"><button type="button" className="text-button" disabled={listBusy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>上一页价格</button>
        <span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span><button type="button" className="text-button" disabled={listBusy || !page?.has_more || page.next_offset === null} onClick={() => { if (page?.next_offset !== null && page?.next_offset !== undefined) setOffset(page.next_offset); }}>更早版本</button></div>
    </section>

    <section className="ai-price-planning" aria-labelledby="ai-price-workload-title">
      <h3 id="ai-price-workload-title">按工作量进行费用规划 · 单项</h3>
      <form onSubmit={event => void submitPlanning(event)}>
        <div className="ai-price-fields">
          <label className="ai-price-wide">明确选择价格版本<select value={selected?.id || ""} onChange={event => chooseVersion(choices.find(value => value.id === event.target.value) || null)}>
            <option value="">请选择版本，不自动选价</option>{choices.map(version => <option key={version.id} value={version.id}>{version.vendor_label} · {version.model} · {version.currency} · {version.id}</option>)}
          </select></label>
          <label className="ai-price-wide">规划时点（UTC，末尾 Z）<input type="text" value={planning.planned_for} onChange={event => changePlanning("planned_for", event.target.value)} placeholder="YYYY-MM-DDTHH:mm:ssZ" spellCheck={false} /></label>
          <label>请求次数（1–1,000,000）<input type="text" inputMode="numeric" value={planning.request_count} onChange={event => changePlanning("request_count", event.target.value)} /></label>
          <label>每次输入 tokens（0–100,000,000）<input type="text" inputMode="numeric" value={planning.input_tokens_per_request} onChange={event => changePlanning("input_tokens_per_request", event.target.value)} /></label>
          <label>每次输出 tokens（0–100,000,000）<input type="text" inputMode="numeric" value={planning.output_tokens_per_request} readOnly={selected?.provider === "openai_embeddings"} onChange={event => changePlanning("output_tokens_per_request", event.target.value)} /></label>
        </div>
        {selected?.provider === "openai_embeddings" ? <p>Embeddings 输出 tokens 固定为 0。</p> : null}
        <p>UTC 时间可为历史或未来；只检查所选版本的有效期。翻页或追加价格不会自动替换已选版本。</p>
        <button type="submit" className="primary-button" disabled={planBusy || !selected}>{planBusy ? "正在计算费用规划…" : "计算费用规划"}</button>
      </form>
      {selected ? <details className="ai-price-selected"><summary>已选版本与人工来源 · {selected.id}</summary><PriceDetails version={selected} /></details> : <p>尚未选价，不生成金额。</p>}
      {planError ? <p className="inline-error" role="alert">{planError}</p> : null}
      {result ? <section className="ai-price-result" aria-label="费用规划结果" role="status">
        <h4>费用规划结果</h4><p>{planningNotice}</p><p>规划时点（UTC）：<time>{result.planned_for}</time>；计算时间（UTC）：<time>{result.calculated_at}</time>。</p>
        {result.items.map(item => <article key={item.item_index}>
          <PriceDetails version={item.price_version} />
          <p>工作量：{item.request_count} 次请求；每次输入 {item.input_tokens_per_request} tokens，输出 {item.output_tokens_per_request} tokens。</p>
          <p>公式：<code>{item.formula}</code></p>
          <p className="ai-price-formula"><code>{item.request_count} × ({item.input_tokens_per_request} × {item.price_version.input_per_million} + {item.output_tokens_per_request} × {item.price_version.output_per_million}) ÷ 1000000</code></p>
          <dl className="ai-price-amounts"><div><dt>精确输入费用（{item.price_version.currency}）</dt><dd>{item.exact_input_total}</dd></div>
            <div><dt>精确输出费用（{item.price_version.currency}）</dt><dd>{item.exact_output_total}</dd></div>
            <div><dt>精确合计（{item.price_version.currency}）</dt><dd>{item.exact_total}</dd></div>
            <div><dt>舍入合计（{item.price_version.currency}，六位小数）</dt><dd>{item.rounded_total}</dd></div></dl>
          {item.exact_total !== "0" && item.rounded_total === "0.000000" ? <p>精确费用非零，按六位小数舍入后为零；这不表示免费。</p> : null}
          {item.exact_total === "0" ? <p>按所选明确费率与工作量算得精确零额；并非缺价。</p> : null}
        </article>)}
        <p>计算版本：<code>{result.calculation_version}</code> · 小数位：{result.scale} · 舍入：<code>{result.rounding}</code>（四舍五入）。</p>
        <p>未计入：{result.exclusions.map(value => exclusionLabels[value]).join("、")}。</p><p>{result.notice}</p>
      </section> : null}
    </section>

    {auth.state.user?.is_admin ? <section className="ai-price-admin" aria-labelledby="ai-price-create-title">
      <h3 id="ai-price-create-title">管理员 · 追加人工价格版本</h3>
      <p>请自行核对来源与适用范围；本系统不会抓取或核验链接。提交仅追加新版本，不覆盖旧价。</p>
      <form onSubmit={event => void submitPrice(event)}>
        <fieldset disabled={createBusy} className="ai-price-fieldset"><legend>价格与来源</legend><div className="ai-price-fields">
          <label>人工厂商 / 计费方<input type="text" maxLength={100} value={draft.vendor_label} onChange={event => changePrice({ vendor_label: event.target.value })} /></label>
          <label>接口协议<select value={draft.provider} onChange={event => { const provider = event.target.value as AIPriceProvider; changePrice({ provider, ...(provider === "openai_embeddings" ? { output_per_million: "0" } : {}) }); }}>{Object.entries(providerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>精确模型标识（区分大小写）<input type="text" maxLength={120} value={draft.model} onChange={event => changePrice({ model: event.target.value })} spellCheck={false} /></label>
          <label>币种（三个大写英文字母）<input type="text" maxLength={3} value={draft.currency} onChange={event => changePrice({ currency: event.target.value })} autoCapitalize="characters" spellCheck={false} /></label>
          <label>输入费率（每百万 tokens）<input type="text" inputMode="decimal" maxLength={18} value={draft.input_per_million} onChange={event => changePrice({ input_per_million: event.target.value })} /></label>
          <label>输出费率（每百万 tokens）<input type="text" inputMode="decimal" maxLength={18} value={draft.output_per_million} readOnly={draft.provider === "openai_embeddings"} onChange={event => changePrice({ output_per_million: event.target.value })} /></label>
          <label className="ai-price-wide">人工来源说明（必填，未在线核验）<textarea rows={3} maxLength={1000} value={draft.source_note} onChange={event => changePrice({ source_note: event.target.value })} /></label>
          <label className="ai-price-wide">来源 URL（可选，完整 HTTP(S) 链接）<input type="text" maxLength={2048} value={draft.source_url} onChange={event => changePrice({ source_url: event.target.value })} spellCheck={false} /></label>
          <label>有效开始（UTC，含此时点）<input type="text" value={draft.effective_from} onChange={event => changePrice({ effective_from: event.target.value })} placeholder="YYYY-MM-DDTHH:mm:ssZ" spellCheck={false} /></label>
          <label>有效结束（UTC，不含；可留空）<input type="text" value={draft.effective_until} onChange={event => changePrice({ effective_until: event.target.value })} placeholder="留空表示无结束上界" spellCheck={false} /></label>
        </div></fieldset>
        <p>非负十进制费率最多 9 位整数和 8 位小数，零价有效；所有金额保留原始字符串。Embeddings 输出费率必须为 0。</p>
        <button type="submit" className="secondary-button" disabled={createBusy}>{createBusy ? "正在追加价格…" : retryAvailable ? "按原提交重试追加" : "追加新价格版本"}</button>
      </form>
      {createError ? <p className="inline-error" role="alert">{createError}</p> : null}
      {retryAvailable ? <p role="status">提交尚未确认。保持原内容重试会复用同次提交；编辑任一字段将开始新的追加。</p> : null}
      {created ? <div className="ai-price-created" role="status"><p>已追加新版本并刷新首页。规划仍保留原选择；如需采用新价，请明确选择。</p><PriceDetails version={created} />
        <button type="button" className="secondary-button compact" onClick={() => chooseVersion(created)}>明确选择新版本进行规划</button></div> : null}
    </section> : <p>当前账户可读取价格和进行费用规划；追加价格仅限管理员。</p>}
  </div>;
}
