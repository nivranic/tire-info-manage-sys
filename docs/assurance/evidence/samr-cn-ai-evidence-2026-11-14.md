# 中国召回 AI 证据与引用验收

更新于 2026-11-14，基线为 `d61d3b2`。本阶段接通中国官方公告的当前／历史 AI 证据、同步与流式分析、报告及正常工作台入口。完整 V1 持续进行。[实施计划](../../plans/2026-11-14-samr-cn-ai-evidence.md)

## 已实现

- 历史引用固定 `kind=samr_recall`、`snapshot_id` 和原生 `article_id`。当前准备使用 `samr_recall_notice`，通过现有来源服务再次在线核验，保留精确 QueryRun／Verification，audience 为 `ai_current`。
- `samr-recall-fact-selection@1` 冻结完整 11 个字段，保存独立日期、观察与核验时间、原件／文档／内容摘要、Parser 身份及访问依据。来源原文和问题按数据处理。
- 模型仅选择事实 ID，`text` 与 `uncertainty` 严格为空字符串，事实文字由服务端重建。单条中国公告 claim 绑定同一份证据，实物适用性为 `not_assessed`。整包保持既有 44000 字节上限，超限时完整来源继续保存。
- 准备、受理、实际外发、流式草稿、完成采纳、保存报告分别检查。外发绑定账户、问题、Provider、模型、已受理合同和请求体摘要，重新读取精确原件与核验。包标记被删除时，已受理合同继续承担识别依据。
- 混合 Safety Gate、NHTSA 和测试材料保留各自合同及主要提示词版本，另存 SAMR 提示词标识。报告采用 `research-report@6`，导出采用 `frozen-research-export@7`，旧 schema 的回归继续执行。
- 共享类型与 SDK 支持新引用及当前准备。工作台公告和逐观察历史入口沿现有 AI 对话框分析，显示全部日期、访问依据、适用性及冻结事实。原件核对快照、来源路径、文章 ID 与 SHA-256 后以纯文本呈现，账户代次变化和卸载会取消读取。

## 最终验证

| 范围 | 实际结果 |
| --- | --- |
| 中国公告与既有 Safety Gate AI 专项 | r4 共 116 项通过，865 输入稳定，资源关闭 |
| 最终相关受管回归 | r6 共 519 项通过，0 跳过，865 输入稳定，资源关闭 |
| SDK | 14 项通过，含当前原生路径、历史精确引用与取消信号 |
| Web | 66 项通过，含原件匹配／篡改与引用去重 |
| 类型与构建 | 全工作区类型检查和 Web 生产构建通过 |
| 生产 Web 正常入口 | 专用 CDP 浏览器 15 项通过，2 次合成 Provider 调用、0 次外部请求 |
| 布局 | 1440／390／320 宽度均无横向溢出，390 截图已查看 |
| 独立非拥有者 PG／TLS | 最终 14 条通过记录、13 个不同检查名称，包含正常 HTTP、Worker、合同拒绝、备份恢复及本阶段 AI 专项 |

最终受管入口覆盖中国公告、Safety Gate AI、共享分析／流式／正文证据、旧报告渲染、测试材料合同和中国召回既有查询／历史／监控。7 种混合材料组合均经过同步、流式与 Markdown／HTML／PDF 导出。

浏览器覆盖逐包外发确认、错误原件拒绝、纯文本 canary、保存后的报告库与下载、精确历史观察、当前查询失败的单次历史授权，以及自由文字输出拒绝。再次打开分析窗口沿既有调用恢复及重新准备入口操作。

PG 专项通过直连真实官方检索和公告取得 `live`，所选原生文章为 `41a7504f497246c9908ccd5d61cefb69`，原件 SHA-256 为 `d4d0f34f0d3625e0c10b1298df443503a0ca16a53d2dc53338d4bc7731f347bb`。当前准备绑定本次核验，历史准备、同步与流式事实、幂等重放、三种报告文件摘要及跨会话 404 均通过。Provider 为明确合成适配器，调用 2 次，真实模型调用为 0。

## 原始失败与纠正

1. r1 在入口实施前记录 5 项中的 3 项失败，保留为原始缺口证据。r2 当时的 58 项通过，后续范围以 r6 为准。
2. r3 共 108 项，106 通过、2 失败。新增测试漏传保存报告的幂等标识，并读取归属回执中不存在的 audience 字段。测试改用正式幂等头，在服务执行入口观察 audience，r4 全部通过。
3. r5 共 403 项，396 通过、7 失败。纯流式生命周期夹具使用占位数据库，未隔离新 SAMR 派发接口。按该夹具既有接口方式补齐隔离，实际数据库篡改／标记删除反例继续由中国公告专项覆盖，r6 全部通过。
4. 首次私有浏览器脚本对下载正文执行 JSON 解码，报告导出已返回 201，脚本未完成下载验收。脚本限制为 JSON 响应后复跑。第二次脚本未操作既有调用恢复后的重新准备按钮，修正后最终 15 项通过。
5. 首次 PG 专项已完成真实来源、生成和三种导出，最后跨会话读取检查漏传必需的 `mode=history`，返回参数校验错误。补齐私有脚本参数，最终整批通过。前后集群与失败回执均保留。

## 源码与部署合同

当前 API 源码指纹为 `381b584a40a803fe98b5df649c6bcca2e0f233c9f899b4aa2119edbb928eed3e`。独立空参考 `postgres-runtime-schema@4` 合同为 `f5f8296fad7a5ae465e5665ac2af0e663b2b80687b99fb83f21a748fd4456a5e`，包含 180 个 relation，对应现有 179 张模型表及迁移记录。已审查其 catalog 与向量索引声明均与监控阶段合同一致，源码绑定已更新，非拥有者只读 verify 通过。实际部署按目标环境重建、审查并批准合同。[运行合同流程](../../POSTGRES-RUNTIME-SCHEMA.md)

## 私有回执

回执、原件、数据库、验收脚本和截图位于 Git 忽略目录。接手时先核对文件摘要，使用正式入口重建所需环境。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/samr-ai-20261114/r3/result.json` | `171d6135c969a56dec3fd63e6436cb4623e80ae504ffd6ee1a321a7783ef2238` |
| `.artifacts/samr-ai-20261114/r4/result.json` | `8c6a49296865a4517b381cf5d36625385a12b6550aa53f04553aee99498e8102` |
| `.artifacts/samr-ai-20261114/r5/result.json` | `5025838ccb9d815198f3ef3020ebd849a3269087513e3ffbcc4aca5f64dd1a29` |
| `.artifacts/samr-ai-20261114/r6/result.json` | `dbeccedd353bbeca64300f45eba15447acc76fc092b8275cd1d97590609fc521` |
| `.artifacts/samr-ai-20261114/web/run-2a686b36-71e9-489d-895a-c56391976daa/report.json` | `649b5a7a27ef2400639d3700aca0b1f27b1d7271145618a6d00a41aa445a5c75` |
| `.artifacts/samr-ai-20261114/resource-audit.json` | `606f99b177deb19256ce2610660294aa7bfa607bb17c2faa323a60b350431432` |
| `.artifacts/postgres/pgverify-6a47411cb9184ab8bb04f65d86595c06/report.json` | `858087b07d0c28190c31f781ad1a503f621bbded315ae883942dbba1bf227ac5` |
| `.artifacts/postgres/pgverify-4bef0b1f082f49b790dfe9a62e35370c/report.json` | `175a4b8b38d236f6cd66ea8be43df43c8fbe9b90dfe68cf41162b5c058318b21` |

PG 原始失败与最终回执分别为 `.artifacts/postgres/pgverify-6a47411cb9184ab8bb04f65d86595c06/report.json` 和 `.artifacts/postgres/pgverify-4bef0b1f082f49b790dfe9a62e35370c/report.json`。

## 资源关闭与待验范围

三次浏览器运行与两个 PG 集群累计 33 个直接进程记录、33 个不同进程 ID、18 个端口均已核对关闭。两个集群的临时口令、TLS 私钥与 postmaster 文件均已移除，受管运行器另有独立资源关闭回执。

当前宿主进程未配置 OpenAI 专用 Key、模型或 EPREL Key。真实 OpenAI Responses／Embeddings、EPREL 正式接口、自然长周期、专业材料许可、人工 Golden、具体 SKU／批次、Native 宿主／设备、生产环境和完整 V1 Gate 继续待验。[需求与剩余项](../../AGENT-HANDOFF-2026-11-14-PUBLISH.md)
