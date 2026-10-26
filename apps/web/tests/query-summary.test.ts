import assert from "node:assert/strict";
import { test } from "node:test";
import { getQuerySummary, hasQueryData, type QuerySummaryRun, type QuerySummary } from "../components/query-summary.ts";

const run = (overrides: Partial<QuerySummaryRun> = {}): QuerySummaryRun => ({ loading: false, ...overrides });
const live = run({ data: { data_state: "live" } });
const consent = run({ data: { data_state: "consent_required" } });
const denied = run({ ...consent, denied: true });
const unavailable = run({ data: { data_state: "source_unavailable" } });

const cases: { name: string; runs: QuerySummaryRun[]; resultsCount?: number; expected: QuerySummary }[] = [
  {
    name: "initial view retains the original guidance",
    runs: [],
    expected: { text: "LIVE FIRST / EVIDENCE ALWAYS", busy: false, state: "idle" },
  },
  {
    name: "active online requests are busy",
    runs: [run({ loading: true }), run({ loading: true })],
    expected: { text: "正在在线查询 / 2 SOURCES", busy: true, state: "querying" },
  },
  {
    name: "a submitted fallback decision is busy without claiming snapshot access",
    runs: [run({ ...consent, consentPending: true })],
    expected: { text: "正在处理回退决定 / 1 SOURCES", busy: true, state: "fallback_pending" },
  },
  {
    name: "all HTTP failures terminate the waiting status",
    runs: [run({ error: "HTTP 503" }), run({ error: "网络请求失败" })],
    expected: { text: "本次未获得可核验结果 / 2 SOURCES", busy: false, state: "unavailable" },
  },
  {
    name: "successful HTTP responses with unavailable business states are terminal",
    runs: [unavailable, unavailable],
    expected: { text: "本次未获得可核验结果 / 2 SOURCES", busy: false, state: "unavailable" },
  },
  {
    name: "consent requests wait for the person without marking a network action busy",
    runs: [consent, consent],
    expected: { text: "在线查询未完成，等待回退授权 / 2 SOURCES", busy: false, state: "consent_required" },
  },
  {
    name: "all denials override the retained consent DTO",
    runs: [denied, denied],
    expected: { text: "已拒绝全部回退，本次无可核验结果 / 2 SOURCES", busy: false, state: "denied" },
  },
  {
    name: "source directory verification failure is terminal",
    runs: [run({ error: "来源目录待核对或许可已变化。" })],
    expected: { text: "本次未获得可核验结果 / 1 SOURCES", busy: false, state: "unavailable" },
  },
  {
    name: "source permission cancellation is terminal",
    runs: [run({ error: "来源状态已变化，旧请求已失效。已完成证据仍可读取。" })],
    expected: { text: "本次未获得可核验结果 / 1 SOURCES", busy: false, state: "unavailable" },
  },
  {
    name: "a failed consent submission does not resurrect its old consent status",
    runs: [run({ ...consent, error: "授权提交失败" })],
    expected: { text: "本次未获得可核验结果 / 1 SOURCES", busy: false, state: "unavailable" },
  },
  {
    name: "an ended run without any DTO or error is terminal",
    runs: [run()],
    expected: { text: "本次未获得可核验结果 / 1 SOURCES", busy: false, state: "unavailable" },
  },
  {
    name: "one denial and one failure are not described as all denied",
    runs: [denied, unavailable],
    expected: { text: "本次未获得可核验结果 / 2 SOURCES · 1 个来源已拒绝回退", busy: false, state: "unavailable" },
  },
  {
    name: "one valid consent request remains actionable beside a failed consent submission",
    runs: [consent, run({ ...consent, error: "授权提交失败" })],
    expected: { text: "在线查询未完成，等待回退授权 / 2 SOURCES · 1 个来源未获得可核验结果", busy: false, state: "consent_required" },
  },
  {
    name: "a single denial leaves the other source awaiting authorization",
    runs: [denied, consent],
    expected: { text: "在线查询未完成，等待回退授权 / 2 SOURCES · 1 个来源已拒绝回退", busy: false, state: "consent_required" },
  },
  {
    name: "online work and a fallback decision are reported together",
    runs: [run({ loading: true }), run({ ...consent, consentPending: true }), unavailable],
    expected: { text: "正在在线查询 / 3 SOURCES · 1 个来源正在处理回退决定；1 个来源未获得可核验结果", busy: true, state: "querying" },
  },
];

for (const item of cases) test(item.name, () => {
  assert.deepEqual(getQuerySummary(item.runs, item.resultsCount ?? 0), item.expected);
});

test("all accepted data states count as completed even with zero matched SKUs", () => {
  for (const data_state of ["live", "live_verified_304", "local_snapshot"] as const) {
    const current = run({ data: { data_state } });
    assert.equal(hasQueryData(current.data), true, data_state);
    assert.deepEqual(getQuerySummary([current], 0), {
      text: "0 MATCHED SKU / 1 SOURCES", busy: false, state: "complete",
    }, data_state);
  }
  for (const data of [undefined, consent.data, unavailable.data]) assert.equal(hasQueryData(data), false);
});

test("the supplied SKU count is retained without deriving a new filtering or deduplication count", () => {
  assert.deepEqual(getQuerySummary([live, run({ data: { data_state: "live_verified_304" } }), run({ data: { data_state: "local_snapshot" } })], 47), {
    text: "47 MATCHED SKU / 3 SOURCES", busy: false, state: "complete",
  });
});

test("partial results remain visible beside each active, actionable or terminal state", () => {
  const others: { run: QuerySummaryRun; detail: string; state: QuerySummary["state"]; busy: boolean }[] = [
    { run: run({ loading: true }), detail: "正在在线查询", state: "querying", busy: true },
    { run: run({ ...consent, consentPending: true }), detail: "正在处理回退决定", state: "fallback_pending", busy: true },
    { run: consent, detail: "等待回退授权", state: "consent_required", busy: false },
    { run: denied, detail: "已拒绝回退", state: "partial", busy: false },
    { run: unavailable, detail: "未获得可核验结果", state: "partial", busy: false },
    { run: run({ ...consent, error: "授权提交失败" }), detail: "未获得可核验结果", state: "partial", busy: false },
  ];
  for (const item of others) for (const resultsCount of [0, 7]) {
    assert.deepEqual(getQuerySummary([live, item.run], resultsCount), {
      text: `${resultsCount} MATCHED SKU / 2 SOURCES · 1 个来源${item.detail}`,
      state: item.state, busy: item.busy,
    }, `${resultsCount} matches with ${item.detail}`);
  }
});

test("a mixed batch reports every unfinished and unsuccessful source alongside its usable result", () => {
  const runs = [live, run({ loading: true }), run({ ...consent, consentPending: true }), consent, denied, unavailable];
  assert.deepEqual(getQuerySummary(runs, 3), {
    text: "3 MATCHED SKU / 6 SOURCES · 1 个来源正在在线查询；1 个来源正在处理回退决定；1 个来源等待回退授权；1 个来源已拒绝回退；1 个来源未获得可核验结果",
    state: "querying", busy: true,
  });
});

test("allow and deny submissions share the decision-pending status until their actual outcome", () => {
  for (const outcome of [denied, run({ data: { data_state: "local_snapshot" } }), run({ ...consent, error: "决定提交失败" })]) {
    assert.equal(getQuerySummary([consent], 0).busy, false);
    assert.deepEqual(getQuerySummary([run({ ...consent, consentPending: true })], 0), {
      text: "正在处理回退决定 / 1 SOURCES", busy: true, state: "fallback_pending",
    });
    assert.equal(getQuerySummary([outcome], 0).busy, false);
    assert.equal(getQuerySummary([outcome], 0).text.includes("正在"), false);
  }
});

test("retry feedback follows current flags, then a new query clears the previous terminal result", () => {
  const failed = run({ ...consent, error: "授权提交失败" });
  assert.equal(getQuerySummary([failed], 0).state, "unavailable");
  assert.equal(getQuerySummary([run({ ...failed, consentPending: true })], 0).state, "fallback_pending");
  assert.equal(getQuerySummary([run({ loading: true })], 0).state, "querying");
  assert.deepEqual(getQuerySummary([live], 5), { text: "5 MATCHED SKU / 1 SOURCES", busy: false, state: "complete" });
});

test("summaries are independent of source ordering and leave frozen inputs untouched", () => {
  const runs = [live, run({ loading: true }), consent, denied, unavailable, run({ ...consent, error: "授权提交失败" })];
  runs.forEach(item => { if (item.data) Object.freeze(item.data); Object.freeze(item); });
  Object.freeze(runs);
  const before = JSON.stringify(runs);
  const expected = getQuerySummary(runs, 4);
  assert.deepEqual(getQuerySummary([...runs].reverse(), 4), expected);
  assert.deepEqual(getQuerySummary(runs, 4), expected);
  runs.forEach(item => hasQueryData(item.data));
  assert.equal(JSON.stringify(runs), before);
});
