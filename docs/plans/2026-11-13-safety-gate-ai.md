# Safety Gate告警AI证据应用 Implementation Plan

**Goal:** 让用户从所选官方告警进入AI证据包、单次外发确认、同步／流式事实选择、引用恢复和冻结报告；保留原生告警身份及未知适用性。

**Architecture:** 复用现有Pack、预算、Responses网关、执行账本、grounding与报告链。新增源专属冻结合同，按snapshot_id＋alert_id精确选取；模型只选择事实ID，文字由服务器从冻结字段生成。客户端继续共享Workbench，Web与Native保留各自流式／轮询传输，不新增独立页面或放宽IPC权限。

**Tech Stack:** FastAPI、SQLAlchemy、现有OpenAI Responses网关、共享TypeScript SDK、React工作台。

## 交接执行状态

步骤 1–5 已接通，后端阶段后又完成共享类型／SDK／正常页面与报告消费。步骤 6–7 已取得后端专项、类型／Web／构建、官方历史材料正常 HTTP 与生产页面的对应证据；新增组合反例、真实模型与 Native 仍有待验项。见[当前交接卡](../AGENT-HANDOFF-CURRENT.md)、[后端验收](../assurance/evidence/safety-gate-ai-backend-2026-11-13.md)及[消费者验收](../assurance/evidence/safety-gate-ai-consumers-2026-11-13.md)。不据此宣称完整 V1 完成。

## 现状与取舍

### 12e726e 后续消费者实施

- 先扩 `packages/domain-types/src/safety-gate.ts` 与 `index.ts` 中的 AI 引用、在线请求、包／分析／报告边界；只扩 `AIAnalysisReference`，不扩离线包或知识搜索引用。同步 `packages/api-client/src/index.ts` 的 prepare 返回类型。
- 新增 `apps/web/components/safety-gate-ai-values.ts`，集中周报／历史观察的精确目标构造、当前请求与原件核验；新增边界／元信息和原件恢复组件。来源 XML 只以文本展示，恢复前校验原件 SHA256、周报 query 和原生告警 ID／通报编号，切换会话或目标时取消读取并丢弃迟到响应。
- 修改 `safety-gate.tsx`、`recalls.tsx`、`ai-analysis.tsx`、`ai-stream-progress.tsx` 与 `reports.tsx`：正常入口、历史／在线准备、固定边界、事实引用及报告均覆盖；保留现有 Native 轮询。
- 用 Node 测试覆盖目标绑定、去重、当前请求与拒绝反例，用共享 SDK 的合成传输验证请求／响应／取消。执行 Web 测试、三端类型与独立生产构建；随后使用官方历史材料和合成 Provider 跑正常 HTTP／生产页面（含窄屏、原件核验和报告）。不以合成 Provider 证明真实 OpenAI 质量，不以共享代码证明真机。

基线为927a2e8。桌面与Android已共享Safety Gate页面和普通/v1桥接，任务进度有Native轮询；这些是代码事实，实际宿主／设备待验。AI PackReference当前只有NHTSA recall，Safety Gate尚无独立引用与冻结字段合同。

选择源专属合同：直接转换为NHTSA recall会改变监管辖区及产品身份，通用自由文本解释不能保证告警原文与未知适用性。模型只在所选告警的同一证据内选字段，不能跨告警／SKU拼接安全结论。外部API的Key或字段许可不作为AI外发同意；沿现有明确单次外发确认、来源与预算策略。

## 实施与验证

1. 新建 `safety_gate_ai_evidence.py` 和 `ai_safety_gate_contract.py`，定义不可变v1字段／边界，精确验证Snapshot、QueryRun、Verification、原件／文档摘要、报告和告警身份；生成完整有序事实，不静默截断。纯冻结校验不依赖未来Parser或当前数据库。
2. 扩展 `ai_evidence.py` 引用与current查询类型。历史按快照／告警选择；current通过SafetyGateService重新在线核验，并保留单次回退同意、来源代次与ai_current受众隔离。最多选择6个明确告警，包容量沿现有上限。
3. 接入网关prompt／输出schema／合同摘要、提交前校验、同步grounding、流式claim／uncertainty校验及执行最终边界。拒绝自由推断、模型补写事实、跨告警拼接、改写边界及引用错绑。OpenAI Responses仍为首个真实Provider。
4. 报告新增冻结schema，创建时重验正式材料，恢复／导出时使用冻结合同；旧schema字节与行为保持。Markdown／HTML／PDF显示固定未评估边界与出处。
5. 扩共享类型与工作台目标，告警条目提供分析入口、包预览、单次外发、同步／流式结果、事实引用恢复及报告。历史材料不能回答“当前”问题；Native仍使用既有传输和轮询。
6. 增加受管后端正常API与篡改反例，覆盖原生负ID、空字段、报告错绑、验证状态、包篡改、跨告警、单次同意、预算、幂等、流式与报告冻结。验证新旧NHTSA／测试／正文AI兼容，运行SDK、三端类型、Web、构建及正常HTTP／生产界面验收。
7. 用已有官方历史材料和明确合成Provider验收工程链，保留原始失败、源码指纹与资源关闭记录。凭据缺失时不声称真实模型语义通过；更新交接、审查提交并推送。完整V1继续开放。

## 边界与回退

原始规格、历史交接尾文和KIT C2封存不变。源材料内指令视为数据，原件／私库／密钥只留Git忽略槽。现有持续回退或外部Key不会自动授权AI；公有CC0来源声明须绑定材料，仍需用户本次外发确认。拒绝路径不能产生模型调用或成功完成记录。

回退时撤下新分析入口及引用类型，保留已存在的冻结包、账本、报告和v1渲染器，不删除历史。原生真实设备、真实Responses质量、正式PG、公网、长周期及其余V1 Gate另行验收。
