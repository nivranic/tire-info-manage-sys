# 胎迹进度与 Agent 交接卡

更新于 2026-11-14。本次交付包含 Dunlop 欧洲来源、相关 Parser 兼容变更、验证与交接。完整 V1 持续进行。

## 接手先读

- 原始需求按 12 个核心模块、10 项发布 Gate、13 项 SLO、15 项产品决策组织。每组分别跟踪，整体完成率尚缺逐项验收依据。[原始需求](requirements/2026-09-26-tire-intelligence-original.md)
- 当前分支为 `main`，本次收尾基线为 `e4684258331b33923b628901e44a59486fd08564`，Dunlop 与 Parser 功能提交为 `224ade3`。本文随单独的正式文档提交交付，最终本地及远端提交使用下文命令核对。[此前阶段交接](AGENT-HANDOFF-2026-11-14.md)
- 用户已授权持续实施、复核优化、提交、push 全部改动及编写交接文档。专业材料由 agent 自行选择并核对来源与许可。缺少 EPREL Key 时继续独立工作。
- 首个真实 AI 接入采用 **OpenAI Responses API**。原规格列有 Gemini 备选，此前 agent 自行提前排期，在 `d5fded1` 实现可选适配器。现有 Gemini 证据为合成验证，真实调用待验。后续真实模型验收依用户的 OpenAI 选择推进。[Provider 复核](assurance/evidence/provider-handoff-review-2026-11-14.md)
- 需求材料中的模型版本、价格、外部标准和技术建议使用前重新核验。任务授权与优先顺序依据用户消息。

## 12 个模块的当前进度

下表汇总既有实现和已留证范围。逐阶段详细记录见历史交接及对应验收文档。

| 模块 | 已实现或已有阶段验收 | 仍需实施或验收 |
| --- | --- | --- |
| 轮胎查询 | 在线优先、组合筛选、来源状态、显式回退授权，13 个轮胎区域目录、9 个厂商品牌 | 其余 P0 来源及地区、更多型号、长期在线稳定性 |
| 精确版本识别 | 产品代码、GTIN、OE、地区身份、冲突并存、Golden 工作台 | 代表性真实 SKU 独立绑定、人工 Golden、错合并指标 |
| 车型适配 | SU7 前后轴、Garage、SKU 证据桥、官方 PDF 链路 | 更多车型、完整 OE 事实、实际 Native 消费 |
| 比较 | 精确 SKU 比较、保存比较、同场测试及条件偏好 | 专业性能解释、代表性真实推荐质量 |
| 测评数据库 | TestEvent、环境和指标、原件、身份桥、真实原报道隔离验证 | 精确 SKU 正例、正式复用许可、真人审核 |
| 信息监控 | Worker、参数差异、NHTSA、Safety Gate 历史与调度、应用内提醒和任务 SSE | 自然长周期、真实变化通知及 lag、任意网页与 PDF 差异 |
| 传统 CRUD | 来源、规则、偏好、测试、账户、Provider、Key 和费用规划 | 全实体覆盖、生产权限、BYOK、真实账单 |
| 证据浏览 | 快照、哈希、Parser 版本、原件、HTML/PDF 正文、引用恢复 | 实际部署旧库切换、完整许可治理、生产对象存储 |
| 个性化 | Garage、关注、偏好、保存比较、非 SKU 兴趣 | 跨设备、长期运行、真实推荐质量 |
| AI 研究 | grounding、流式报告、正文证据包、FTS/向量/融合检索、离线评估 | 真实 Responses/Embeddings 网络与语义、代表性质量、模型治理 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key、SQLite/PG 受许可读取、许可 CLI 与运行角色 | 公网接收端、生产吞吐和权限、SDK 产品化、完整 WebSocket |
| 管理后台 | Parser 健康、发布回滚、隔离、失败任务、纠错、审计 | 生产 IAM、Tenant/RLS、完整角色治理、发布验收 |

## 最近已完成的阶段

- Safety Gate 已接通周报证据、逐告警历史、持续监控、回退授权、外部受许可读取及 AI 共享类型/SDK/Web/报告消费。历史材料与合成模型的验证范围在对应阶段留证。[此前总表](AGENT-HANDOFF-2026-11-13.md)
- PostgreSQL 已实现许可 CLI、非拥有者治理角色、运行 DML 策略、迁移与 verify 启动分离、旧车型 024 显式维护、独立恢复、HNSW 拥有者维护及 `postgres-runtime-schema@4`。运行角色与权限专项有真实本机 PG/TLS 证据。[数据库及运行阶段](AGENT-HANDOFF-2026-11-14.md)
- 独立 HTTP/Worker、真实来源消费、自然租约、Windows 停机、活动任务取消和 AI 流中断已有阶段验收。实际 Web 长停机手动/刷新恢复及短停机自动恢复已留证，模型端采用合成 Responses。[Web 自动恢复](assurance/evidence/web-ai-short-outage-2026-11-14.md)
- Webhook 通过本机独立 HTTPS/TLS 1.3 接收端验证 HMAC、取消、自然租约与退避恢复。公网 DNS/TLS、接收端部署和生产通知 SLO 继续待验。[Webhook 验收](assurance/evidence/webhook-https-recovery-2026-11-14.md)
- 横滨欧洲 ADVAN Sport V107 已交付，114 条规格、ASGI 13 项与独立 PG/TLS/HTTP 12 项通过。厂商 EPREL 引用、XL/RF 和 OE 原文各自保留来源范围。[横滨验收](assurance/evidence/yokohama-eu-source-2026-11-14.md)

## 本次 Dunlop 交付

### 来源、身份与字段

- 新增 `dunlop-eu` 固定 SPORT MAXX RT2 产品页。已有直连 robots 与目标页 200 记录，robots 允许目标路径。原页指定 Angular transfer-state 响应包含 27 条规格，27 个 Material Code 与 27 个有效 GTIN。[官方产品页](https://www.dunloptyres.com/en/tyres/sport-maxx-rt2)
- 全部行通过型号、slug、语言、季节、尺寸几何、服务描述、载重速度、Material Code/rep_code、GTIN 校验及 EU 标签字段检查后执行查询筛选。字段记录 JSON 路径证据，身份沿 `source_scoped` 合同。
- 27 条中 22 条具有明确 XL，另外 5 条的独立 XL 值为 null。M+S、雪地、冰地及轮辋保护按逐行声明保存。mobility technology 和 OE 品牌/车型原文保留来源范围，独立防爆、静音与 OE 标记继续待证。
- 厂商 EPREL ID、链接及 EU 标签属于厂商声明，独立监管核验继续待验。页面可访问与 robots 允许访问的证据分别保存，开放再分发和专业材料复用许可继续核对。[实施计划](plans/2026-11-14-dunlop-eu.md)

### 代码落点

| 文件或范围 | 本次变更 |
| --- | --- |
| `apps/api/tire_api/adapters/dunlop.py` | 固定页面及指定响应的确定性解析器 |
| `adapters/registry.py`、`adapters/transport.py`、`telemetry.py` | 来源登记、固定主机归属及遥测来源 |
| `parser_runtime.py`、`parser_child.py`、`parser_bundles.py` | 第 17 项可信 Parser、子进程分派、完整封存包合同及历史目录兼容 |
| `apps/api/tests/test_dunlop.py` | 同尺寸不同编码、字段范围、畸形输入、真实隔离子进程与旧 16 项包执行 |
| 已有 Parser、来源和品牌测试 | 更新明确目录断言，保留旧包与旧部署检查 |
| `scripts/regression_children.py`、`scripts/run_api_worker_regression.py` | 更新已审查源码绑定、固定导入参数与正式测试清单 |
| `.gitattributes` | 新解析器及测试文件采用 LF |

### 验证状态

| 范围 | 已观察结果 |
| --- | --- |
| 前序受管回归 | Dunlop、导入边界、来源设置 3 模块 79/79 通过，847 项输入稳定、资源关闭、非自检拒绝 0 |
| 正式在线 canary | `dunlop-eu`、SPORT MAXX RT2、235/55R19 首次与重复读取均 ok，匹配 2 条，隔离 Parser exit 0、reaped=true |
| 正常 ASGI 入口 | 原注册与 live-query 路由 17 项检查通过，两次 live、1 份快照、2 个 variant、2 次 verification，证据重开及哈希核对通过 |
| 后续独立 HTTP/PG/TLS | 12 项通过，两次真实官网查询均 live，两个 SKU 的 ID 和事实版本稳定，相同原文保留原观察时间，历史证据可重开 |
| 精确身份示例 | Material Code `543000` 为 101Y、XL=null，`544985` 为 105Y XL，两个 variant ID 独立，重复读取版本稳定 |
| 条件核验 | 本批服务端未给出 ETag/Last-Modified，重复查询走完整在线读取，回执为 live |
| 本次扩展回归首批 | 13 模块 371 项实际执行，360 通过、11 失败，跳过及不完整为 0，847 项输入稳定、资源关闭、非自检拒绝 0 |
| 失败项对照 | 普通宿主权限、相同源码及正式受管入口复跑 16/16 通过，覆盖首批全部 11 个失败项所属用例族，847 项输入稳定、资源关闭、非自检拒绝 0 |
| 本次静态及交付检查 | 19 个变更 Python 文件语法通过，20 个新增或修改段落的相对链接有效，差异空白及新增内容隐私扫描通过，原始需求和封存尾文核对通过 |

后续已补齐 Dunlop 的独立 uvicorn/非拥有者 PG/TLS 来源消费。12 项通过，847 项输入稳定。原文变化时保留对应新快照且 SKU 事实版本稳定，同原文重复读取保留原始观察时间。三批共 36 个服务记录、43 个进程 ID、19 个端口及临时秘密已核对。前两批分别发现私有脚本换行转换和强制复用快照的校验问题，回执均保留。[Dunlop 完整验收](assurance/evidence/dunlop-eu-source-2026-11-14.md)

扩展回归首批的失败包括原件存储相关断言、封存包硬链接反例及长路径 Parser 执行。硬链接反例明确得到 PermissionError，独立最小 os.link 探针在沙箱内复现 errno13/WinError5。对照批次采用普通宿主权限、相同源码和既有回归护栏，全部 16 项通过。两批回执及最小探针分别保留，首批长路径 Parser 失败的具体错误码尚未采集，历史 Windows 延迟继续待查。

当前 API 包源码 SHA-256 为 `1db34a8b02cc8571b7c76b9c6e1819e54a59cc75d9ccdbde204627769fec1203`。部署使用匹配该源码的批准空参考 @4 合同，按正式流程重新生成、审查并固定摘要。[运行合同说明](POSTGRES-RUNTIME-SCHEMA.md)

### 同机回执

以下回执位于 Git 忽略目录，新 clone 需按正式入口重建验证环境。

| 回执 | SHA-256 |
| --- | --- |
| `.artifacts/dunlop-source-20261114/regression-r1/result.json` | `113beecaff9d6111c29607432e1aec30647672775f7d95eb79ef7e58cefcce6d` |
| `.artifacts/dunlop-source-20261114/http-r1/report.json` | `d3b5154d5e66200f38e04b6c68a495639116636d72881c342125409a74d40cb9` |
| `.artifacts/dunlop-source-20261114/canary-r1.json` | `64f7b6baa3e7f87e8bb4eabd5c087d2b0f8a5572bfff29b457d7f6619bbb50ff` |
| `.artifacts/dunlop-source-20261114/eu-probe.json` | `587196acda0d70c335f13113e27f6ea5622c5a4274c369e87a69a172abc6e7ac` |
| `.artifacts/publish-handoff-20261114/regression-r1/result.json` | `979d3697c54638d46810a0251a13468249ce01afe789df411ebfb5d6435df845` |
| `.artifacts/publish-handoff-20261114/regression-r2/result.json` | `cecc22d6a1a85112f57247909e585ccfa34958446b554cdc970ca66df92fe4cf` |

## 发布仍缺哪些验收

### 10 项发布 Gate

1. P0 来源 provenance 全覆盖，仍缺全部目标来源和代表性字段的闭合验收。
2. 未授权本地回退为零，已有授权门及专项，仍需完整平台与生产矩阵。
3. Golden SKU 错合并为零，仍缺代表性真实材料与人工 Golden。
4. AI 事实回答引用覆盖 100%，仍缺真实 Responses 与代表性语义验收。
5. 高危 AuthZ/SSRF 为零，仍需生产身份、租户及完整安全验收。
6. 未处理 P0/P1 为零，仍有 Parser 间歇超时等待定位项目。
7. WCAG 2.2 AA 核心流程通过，仍需读屏与完整核心流程验收。
8. 六类目标平台核心 E2E 通过，实际 Native 宿主、设备及分发继续待验。
9. Adapter 健康监控与回滚，已有工程和专项，仍需长期真实运行证据。
10. 数据库与 Parser 版本回退，已有本机隔离演练，实际部署旧库与全资产恢复继续验收。

### 13 项 SLO 与 15 项决策

SLO 持续跟踪结构化查询 P95≤300ms、设备检索 P95≤200ms、输入反馈≤100ms、移动 LCP≤2.5s、Adapter 开销≤300ms、权威源正常时 live query P95≤3s、按源 5–10s 超时、通知 lag≤5min、后续可用性 99.9%、RPO≤15min、RTO≤60min、未授权回退 0 次及 Golden 错合并 0 次。生产级证据尚待逐项建立。

15 项产品决策涵盖轮胎范围、首发地区、知识库定义、完全单机、Offline Pack 大小、账户/Tenant、VIN、AI 付费、中国区 Provider、价格库存、专业授权采购、Windows 10 支持期、Native 分发、用户量/SLA、企业私有部署。已明确的用户决定见本文开头，其余沿原规格与后续决策跟踪。

## 下一位 Agent 的执行顺序

1. 核对本地与实时远端、当前工作区及本文绑定的源码。复用既有通过回执，对新失败保存错误码、调用入口、SQLSTATE 和日志。
2. 复用已通过的 Dunlop 独立 HTTP/非拥有者 PG/TLS、同尺寸编码、原件、版本及观察时间验收，继续其他 P0 来源、地区和更多型号。部署使用与实际源码和环境匹配的批准 @4 空参考合同，服务端提供验证器时核对条件读取。
3. 继续其他 P0 来源、代表性精确 SKU 与监管绑定、专业原件许可和人工 Golden。真实 Responses/Embeddings 验收凭据齐备后优先执行，启动时显式指定 `TI_AI_PROVIDER=openai_responses` 并核对 `/v1/ai/status`。
4. 复用 Web 恢复及本机 Webhook HTTPS 证据，继续公网接收端、自然长周期真实变化、通知 lag、多规则、Linux/服务管理器与远端部署。
5. Parser 原间歇超时与 Windows 新文件打开延迟继续从原始证据定位。已观察到 ParserRunError 的批次补具体固定错误码，监督器当前 8 秒限制沿既有配置执行。[性能取证](assurance/evidence/parser-file-open-2026-11-14.md)
6. 收敛生产 IAM/Tenant/RLS、六平台 E2E、WCAG/读屏、真实检索推荐质量、安全、性能、灾备及其余 Gate。

### 正式复跑入口

采用 PowerShell 7，命令在仓库根目录运行，输出使用全新 Git 忽略槽。Python 指向已安装项目依赖的解释器。

```text
git status --short
git log --oneline origin/main..HEAD
git -c http.proxy= -c https.proxy= ls-remote origin refs/heads/main
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/<fresh-regression-slot> --targets apps/api/tests/test_dunlop.py apps/api/tests/test_adapter_import_behavior.py apps/api/tests/test_source_settings.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_parser_releases.py
python -X utf8 -B scripts/canary.py --source dunlop-eu --model "SPORT MAXX RT2" --size 235/55R19 --revalidate
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <postgres-bin-dir> -Suite runtime-process -CliTls
```

canary 运行环境需能导入 `apps/api` 包。PG 入口要求显式提供已安装的 PostgreSQL bin 目录并启用 CliTls，使用空闲环回端口。`runtime-process` 提供通用进程验收，来源专项通过相同正常 API 入口核对，Dunlop 的已观察范围见上述专项验收。

## 资料、授权与封存

- `.artifacts/`、`data/`、本机凭据、依赖、原件及构建产物留在 Git 忽略范围。源码推送后，新 clone 依照入口重建环境与证据。
- 沿既有 `main` 工作，创建分支/worktree 与代理使用遵循用户的明确授权要求。当前推送使用直连。
- KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 继承 `processing_unconfirmed` 封存状态。`stopped_unconfirmed` 保留停止采纳、网络结果未知的含义。接续按历史封存规则处理该材料。[历史交接](AGENT-HANDOFF-2026-11-14.md)
- `docs/HANDOFF.md` 自 2026-10-26 交接标记起的封存尾文已核对原字节，SHA-256 为 `962242b7eeccb652b27f77f07c57ad6e615e23188729b64a46e17f86ab94e4ed`。源码、合成验证、ASGI、实际本机 PG、真实模型、设备与生产验收各自依据相应回执。

## 可复制的接手指令

> 继续实施胎迹完整 V1。先读 docs/AGENT-HANDOFF-2026-11-14-PUBLISH.md、原始需求及 Dunlop 专项验收，核对 main、工作区、本地提交和实时远端。当前有 13 个轮胎区域目录、9 个厂商品牌、17 项可信 Parser。Dunlop 欧洲 SPORT MAXX RT2 原页 27 条规格，保留 Material Code、GTIN、逐行载重速度/XL、厂商 EU 标签和 EPREL 引用。canary、ASGI、受管回归及独立 PG/TLS/HTTP 已有验收，最后进程专项 12 项通过，两次 live，SKU 和事实版本稳定。保留前两批私有验收脚本失败及正文动态变化证据。当前源码使用匹配批准的 @4 空参考合同。首个真实 AI 接入按用户决定采用 OpenAI Responses，缺少凭据期间推进独立工程。继续精确 SKU、监管绑定、人工 Golden、正式许可、其他来源、长期监控、公网 Webhook、Native/无障碍、真实部署与 SLO。保留 Parser 原始失败和 KIT C2 封存，按 12 模块、10 Gate、13 SLO、15 决策逐项推进，提交后核对远端 SHA 及工作区。
