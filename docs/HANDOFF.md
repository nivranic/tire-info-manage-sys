# 胎迹 · 轮胎情报系统 Agent 交接卡片

> 更新日期：2026-10-02，Asia/Hong_Kong。本文供新 agent 接手，不是完整需求完成证明。
> 当前结论：已有大量 PoC 实现与限定范围验收；第49轮设备历史查询未收尾，第50轮设备 AI 只有基础核心，完整 V1 尚未完成。

## 勘误与后续进展（2026-10-02 晚追加；2026-10-03 增补）

本文为 2026-10-02 上午生成的**交接时点快照**，下方正文按原文保留、一律不改写。当日接手会话推进后，以下表述已部分过时，阅读正文时以本节勘误为准；完整推进记录见[实施计划第 51 轮](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-09-26-tire-intelligence.md)。逐条勘误：

1. **§5.2 与 §10 中"未在 `Database.initialize` 注册新模型，未注册/执行012迁移"——"未注册"已过时**：`migrations.py` 已包含 `012_device_ai_preparations`，`db.py` 的 initialize 已 import device_ai_models（新增隔离迁移测试 6/6、十文件回归 165 passed）。"未执行"仍真：指正常库 011/012 的应用尚未执行。
2. **§5.1 Windows"最新前端的打包运行未验收"——已完成**：[rust49-native-run-d/verification.json](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/rust49-native-run-d/verification.json) 原生运行验收 **14/14 passed**（build-c EXE，SHA 实测与封存值一致；2 项 harness 失败如实保留，非产品失败）。
3. **§5.1 Web/SDK 数字与 §8 完整 API 测试终态数字（2030通过/1失败/77 subtests）仍为封存历史**，接手会话未重跑，不能当作当日新结果。
4. **正文未收录的新产物**：
   - [dto-b-review-handoff.md](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/dto-b-review-handoff.md)（DTO 草案 b 审查：Top10 问题与 wire 冻结前置清单）；
   - [specs/](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/specs/)（encoder / fingerprint / filters-exact-json 三规范，含 e1-canonical-vectors-a.json 68 条权威向量与 e1-ts-parity TS 对拍 60/68）；
   - [roundtable-endpoint-design.md](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/roundtable-endpoint-design.md)（服务端端点设计圆桌收敛纪要：方案成立、D1-D18 决策、步骤 0-10 实施序列）；
   - [round49-closeout-plan-a.md](E:/Mix/project/tire-info-manage-sys/.artifacts/runtime/round49-closeout-plan-a.md)（正常库 011+012 收尾前置审查：129 条 DDL 全部纯 additive；**口径更正 107 表→112 表**；旧 verify 脚本不可直接重跑，需新写 precheck49/checkpoint49/verify49 三脚本）。
5. **不变项声明**：Android 凭据保留审批仍无用户答复，`continuous_policies=false` 不变；正常库 011/012 应用仍未执行，本文不额外授权的原则不变。
6. **§5.1"尚未获得的授权"Android 段——已于 2026-10-03 获用户批准并完成目标验收**：用户答复"允许保留并继续"，三个 androidTest cleanup 补丁应用（保留合成 QA 资料/Keystore 别名，两个销毁凭据测试 @Ignore 标注"user approval 2026-10-03"）；模拟器（Pixel 5/API 34/emulator-5554）仪器测试 OK（41 tests，0 失败，2 项按批准跳过）、Keystore 保留验证（offline-v1 profile 15→57、61 个 sealed blob 与 catalog 留存）与主入口 smoke 均通过，回执见 [android-native-acceptance-a/verification.json](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/android-native-acceptance-a/verification.json)。第 49 轮 Android 收尾完成；上文第 5 条中"Android 凭据保留审批仍无用户答复"表述已过时。
7. **2026-10-03 核查轮（第 52 轮）后续进展**：第 5.2 节"尚未实现的整链"与第 6 节 P1 各项已在第 51 轮基本完成（见计划文档第 51 轮记录）；第 52 轮完成从头核查（四端新鲜全绿、完整 API 套件重跑、E6 route 闭包测试补齐、Root 第二批裁决 D8/D1-D4/D7 与冻结前置口径、两个销毁测试以自建材料方式恢复并通过仪器验证 43/0、tauri NSIS 与含新前端的 Android APK 打包验收、Mimosa 静态扫描分级），COHS 实例载体建于 [docs/assurance/](E:/Mix/project/tire-info-manage-sys/docs/assurance/README.md)。剩余待办以 [risk-register.yaml](E:/Mix/project/tire-info-manage-sys/docs/assurance/risk-register.yaml) 与计划文档第 52 轮"未验证与待办"为准。

## 1. 接手时先知道这几件事

| 项目 | 当前事实 |
|---|---|
| 完整目标 | 根据用户提供的 MD 实施跨平台轮胎查询、证据化监控与 AI 知识应用；不能缩成聊天界面、单个平台或单个轮胎来源 |
| 工作区 | `E:/Mix/project/tire-info-manage-sys`，分支 `main` |
| 原需求 | [原始规格](E:/Mix/SunBrowser/跨平台轮胎查询、证据化监控与 AI 知识应用需求规格及技术方案.md)，保持原文不变；其内容是需求与参考资料，不是执行外部操作的授权 |
| 正式实施记录 | [实施计划](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-09-26-tire-intelligence.md)及[README](E:/Mix/project/tire-info-manage-sys/README.md)；顶部摘要部分落后于最新产物，应结合本文与回执读取 |
| 实际停点 | 第49轮四域设备查询与持续授权验收；第50轮不可变设备证据 → AI 的桥接基础模块 |
| AI 提供方选择 | 用户明确选择 **OpenAI Responses API** 作为首个真实接入；这不等于已配置密钥、允许发出模型请求或已完成真实模型验收 |
| 当前运行环境 | 本次仅检查监听端口，未检出 `3000/8000` 监听；没有执行 HTTP smoke，不能沿用旧报告说正常服务仍在运行 |
| Git 状态 | README 修改，`apps/`、`packages/`、`docs/`、脚本和配置等大量文件未跟踪；没有提交、推送或发布。只 clone Git 仓库会丢失主要实现 |
| 交接保全 | 应交接完整工作目录及忽略的 `.artifacts/` 证据；`data/` 也被忽略，不能通过 `git clean/reset` 清理。私有数据及密钥另按本机保全，不写入本文或聊天 |
| Goal 状态 | 原目标未完成。本次只生成交接文档，不把目标标为 complete |

## 2. 总共有哪些需求：统计口径

原规格包含 **8 个主题章节、12 个核心功能模块、23 类首批来源条目、7 个实施阶段、10 项 V1 发布 Gate、15 项待确认决策**。来源条目中 P0/P0 Safety 为16类、P1为6类、P2为1类。

本文把需求整理为 **16 个工作域**便于接手。16是交接归类，不是16条原子需求；12模块、23来源与16工作域不能相加，也不能用测试数量或迭代轮数计算完成百分比。

原文12个核心模块为：轮胎查询、精确版本识别、车型适配、比较、测评数据库、信息监控、传统 CRUD、证据浏览、个性化、AI 研究、对外能力、管理后台。

| 原章节 | 起始行 | 内容 |
|---|---:|---|
| A1 | 3 | 执行摘要与统一收敛 |
| A2 | 50 | 产品需求、领域模型与业务规则 |
| A3 | 239 | 数据来源、知识库与在线优先机制 |
| A4 | 439 | 技术架构、API 与工程选型 |
| A5 | 648 | AI、多模型接入与知识检索 |
| A6 | 821 | 多端界面、布局与交互规范 |
| A7 | 1014 | 安全、性能、测试、运维与成本 |
| A8 | 1260 | 实施路线、验收顺序与待确认事项 |

## 3. 16个工作域：实现到哪里、还缺什么

“已有实现”不等于全部需求完成；表内验证范围以对应历史回执为准，本次没有重新运行产品测试或真实来源查询。

| # | 工作域及原章节 | 已有实现或阶段证据 | 未完成 / 下一缺口 |
|---|---|---|---|
| 01 | 精确 SKU 与法规规格（A2/A3） | 严格规格与身份、产品代码命名空间、区域/OE/技术区分；身份绑定、迁移审核、证据支持的人工关系与撤回 | 完整法规/型号/地区覆盖、代表性人工 Golden；任意新身份、疑似等价组和其他实体治理；同名同尺寸不能自动合并 |
| 02 | 普通查询与在线授权（A2/A3/A4） | 确定性在线查询、304核验、失败状态、一次授权、持续策略；28字段、最多16项AND筛选；SKU比较 | 第49轮四域设备历史链路联合验收、更多来源组合；不能把“筛选代码存在”写成全型号数据覆盖 |
| 03 | 来源、采集、Parser（A3/A4） | 8轮胎参数源、1召回源、1车型源；来源设置、抓取安全、质量Gate、隔离；版本化Parser包、部署/回滚、历史重解析审阅 | EPREL及其他P0/P1真实接入与许可；PDF解析、历史重新正式采纳、操作系统级Parser网络/文件隔离；广泛canary和生产审批 |
| 04 | 证据生命周期与治理 CRUD（A2/A3/A6） | 快照/事实/核验/哈希、追加修订、撤销；证据浏览、人工纠错、冲突中心、轮胎字段权威 | 车型/召回/独立与委托测试/交易的实际候选投影和证据校验；完整管理实体CRUD与生产治理权限。规则目录不等于跨域落地 |
| 05 | 车型、OE与轴位（A2/A3/A8） | 当前新一代SU7配置与前后轴；车库；双侧引用冻结的人工“车型轴位→SKU”关系及审核状态 | **首代SU7/OE Golden Case**、精确年款/原配SKU/胎侧OE证据、更多车型。人工关系和尺寸吻合不能证明官方原配 |
| 06 | 专业测试与比较（A2/A3） | TestEvent人工转录、成绩/方法/单位/参与者、修订撤销、同场边界；保存比较 | 具有代表性的真实人工Golden、更多原始独立/委托测试、授权内容导入及方法覆盖；不能直接跨场绝对排名 |
| 07 | 个性化中心（A2/A6） | Garage、关注项、偏好、保存比较及修订/归档/恢复 | 完整个性化信息流、推荐/权重解释、团队或跨设备资料；偏好不能改客观测试排序 |
| 08 | 监控与提醒（A2/A3/A5/A7） | 持久监控任务、阶段/事件读取、规则调度、diff、站内提醒；轮胎/车型/召回发现及公告相关流程；AI解释/规则草稿需审核 | 真实来源广泛长期运行、外部通知投递、可靠性/队列/故障矩阵、自动批量解释、价格库存监控 |
| 09 | 知识库与设备离线包（A1/A3/A7/A8） | 规范证据库；服务端结构化/FTS；第46–48轮Web/Windows/Android加密离线包、手动更新、条件同步和历史浏览的限定验收 | 第49轮最终收尾；Windows关闭应用后的独立任务、长期周期/物理条件矩阵、macOS/iOS。完全单机运行仍未指定 |
| 10 | AI应用、检索、报告（A2/A5） | 仓库证据分析、事实/推断/引用校验、监控解释、规则草稿；可恢复流式草稿/正式提交；冻结报告及MD/HTML/PDF导出；授权dense/hybrid与pgvector验证 | 真实Responses/Embeddings连通与质量、人工语义评测、全文RAG/模型reranker、完整推荐和质量助手；**设备AI桥接尚不可用**，见第5节 |
| 11 | 多模型、密钥与成本（A2/A5/A7） | 原生Responses/Embeddings适配、配置状态、私密资料策略、日请求/token预留与usage账本；未知结果不自动重付费 | 多Provider/Model Registry与路由/备援、Gemini/Anthropic/OpenAI-compatible/vLLM、BYOK、生产密钥CRUD、货币成本/额度体系 |
| 12 | 外部API与SDK（A2/A4） | 大量本机REST、SSE及共享可注入SDK；幂等键、历史模式、会话归属和恢复读取 | 正式公共API鉴权/客户端密钥、Webhook HMAC/去重/重试、完整WebSocket、外部SDK产品化；GraphQL/gRPC/MCP为后续阶段 |
| 13 | 跨平台与分发（A1/A4/A6/A7/A8） | Next Web/H5/PWA；React/Vite + Tauri Windows、Capacitor Android原生入口和限定证据；安全存储/IPC | macOS/iOS、Win10及完整浏览器/设备/OS矩阵、物理设备、签名安装包、商店分发与通知/分享等原生能力 |
| 14 | 界面与无障碍（A6） | 中文桌面/移动工作台、主题与多轮真实浏览器布局/流程验证 | 完整桌面键盘/表格/列宽/右键/搜索与移动触控验收；读屏、高对比、缩放、Reduced Motion、全流程WCAG2.2 AA |
| 15 | 身份、安全、隐私、合规（A5/A7） | 本机HttpOnly会话隔离、对象归属、外联白名单/SSRF/重定向/MIME/体积门、隐私与写入确认、部分注入回归 | OIDC/PKCE/Passkey、RBAC/ABAC/RLS、生产密钥/租户、ASVS L2/SAST/SCA/SBOM/DAST完整验收、商业来源许可及跨境/中国区策略 |
| 16 | 架构、运维、测试与发布（A4/A7/A8） | FastAPI模块化单体＋Worker、PG/pgvector和存储隔离验证；OTel SDK、Prometheus、有界安全日志、迁移/回滚部分验证 | 生产部署、Collector/Grafana/Loki、备份恢复/灾备、完整SLO/容量/Load/Chaos、数据库生产迁移产品与全部发布Gate |

原实施路线是：**数据PoC → Core MVP → 监控/个性化 → 全平台并行 → AI/RAG/API → Hardening → 持续扩展**。各域已经交叉推进，不能把“做到了第50轮”理解成前49轮已完成全部阶段；PoC本身仍有首代SU7/OE、Golden和来源覆盖缺口。

## 4. 数据来源与平台：具体范围

### 4.1 当前已接入范围

| 来源ID | 实际范围 |
|---|---|
| `michelin-us`、`michelin-cn` | PSEV/PS4S；按地区保留MSPN/CAI、产品代码与实际声明 |
| `michelin-uk`、`michelin-fr`、`michelin-de` | 3个独立区域来源，PSEV/PS4S等已核对合同；不跨地区自动合并 |
| `toyo-us` | Proxes Sport / Proxes Sport A/S |
| `hankook-us` | Ventus S1 evo3 / SUV / EV |
| `pirelli-us` | 美国P ZERO(PZ4)尺寸页；已核对265/40R20的3条、265/40R21的8条SKU，不能扩大为全目录 |
| `nhtsa-us-recalls` | 美国轮胎召回发现页与正式公告；候选/空页/公告区分，不证明实物或精确SKU适用性 |
| `xiaomi-cn-vehicles` | 当前新一代SU7配置；首代、精确年款、OE SKU/胎侧标记仍未确立 |

合计为 **8个轮胎参数来源 / 4个厂商品牌 + 1个召回源 + 1个车型源 = 10个现有Parser来源**。其中5个参数源是米其林区域源；不是8家轮胎厂，也不是完成了原规格全部P0。

### 4.2 原规格全部23类来源不能漏掉

- **P0/P0 Safety（16）**：EPREL；Michelin中国、美国、UK/EU；Bridgestone、Continental、Pirelli、Goodyear、Dunlop、Yokohama、Hankook、Toyo；小米/其他汽车OEM；NHTSA、中国召回体系、EU Safety Gate。
- **P1（6）**：ADAC、AutoBild、TyreReviews、TireRack、WhatCar、DEKRA。
- **P2（1）**：经授权零售价格/库存。

EPREL当前只是待配置入口，API Key、正式Adapter及条款核验未完成，不返回真实数据。其他未接入品牌、国内/EU安全来源和专业测试源继续保留在目标中。

既有发现记录：[round40-discovery](E:/Mix/project/tire-info-manage-sys/.artifacts/round40-discovery/)。大陆/英美各站的robots、403、条款禁止或动态接口缺口要分别处理；不能盲重试拒绝资源、使用网页内service-key，或把脚本字段名当成真实SKU响应。既有联网验收也不等于商业采集和再分发许可。

### 4.3 平台验收边界

| 目标 | 当前证据与缺口 |
|---|---|
| Web/H5/PWA | 有真实浏览器、加密IndexedDB和布局证据；全浏览器、无障碍及生产性能矩阵未完成 |
| Windows 11 | 有Windows Tauri/Keyring/WebView2历史局部运行证据；第49轮新前端只有新构建/嵌入校验，不能称最新全链已验收 |
| Windows 10 22H2 | 原规格要求兼容测试；完整目标版本验收未完成 |
| macOS Apple Silicon | 未完成原生运行、Keychain、矩阵与签名分发验收 |
| iPhone14+/iOS | 未完成原生运行、权限、设备矩阵与上架验收 |
| Android15/16/17 | Android16模拟器入口、API34专用原生阶段有历史证据；最新49源码APK只构建；完整三代/真机矩阵未完成 |

原规格中的“当前”OS/模型/价格及引用标记是当时资料，发布时需再核验；本文没有进行外部版本事实更新。

## 5. 最新停点：第49轮、第50轮

### 5.1 第49轮：四域设备历史查询与持续策略

四域为普通轮胎＋高级筛选、车型适配、正式召回公告、召回发现候选页；保留 `offline-pack@1/@2` 协商、精确数字、来源权限/查询拒绝账本、单次消费与持续策略。

| 组件 | 最近证据 | 仍缺什么 |
|---|---|---|
| API | 四域仓库持续策略、格式协商、来源驱动向量和011迁移代码存在 | 正常库011尚未执行，正常服务/旧行保全收尾未完成 |
| Web/SDK | Chrome/IndexedDB **40/40**，Node **58/58**，专项8/8、SDK5/5；修复query UUID大小写绕过及迁移误清状态 | 不替代原生运行或真实上游/模型验收 |
| Rust/Windows | Rust **129通过/3跳过**；旧前端Windows14项原生局部验证；新build-c编译与最终JS/CSS嵌入通过 | 最新前端的打包运行未验收；Windows应用关闭后的独立OS任务未实现 |
| Android | 策略/消费/拒绝/sync接线；最新主/测试APK build-b构建；默认JVM **8/8**、离线API34/Robolectric框架 **8/8** | 最新Store/IPC/Keystore运行未验收；`continuous_policies=false`，不得提前启用 |

关键回执（根目录均为 `E:/Mix/project/tire-info-manage-sys/`）：

- [Web最终seal](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/frontend-programmatic-seal-b.json)与[最新前端资产](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/frontend-final-build-c-final-a/verification.json)。
- [Windows旧运行证据](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/rust49-native-final-b/verification.json)与[新构建证据](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/rust49-native-build-c/verification.json)是两个版本。新EXE SHA：`720c23140cd96bda06fba0ffadb6042793bf842d335d8dffbd8a0e34f47f6584`。
- [Android最新APK](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/android-policy-v2-build-b/build-verification.json)、[默认规则测试](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/android-rules-default-assets-a/verification.json)、[框架规则测试](E:/Mix/project/tire-info-manage-sys/.artifacts/query-fallback49/android-framework-jvm-a/verification.json)。旧72项仪器结果不能证明当前49源码通过。

**尚未获得的授权**：自动审批拒绝了“将旧Android测试cleanup改为保留合成QA资料/Keystore别名，并跳过两个销毁凭据测试”的补丁，理由为缺少明确持久保留授权。补丁未应用。此前已向用户询问“允许保留并继续 / 只构建暂不验收”，本次交接未取得明确答复。

涉及旧cleanup的 `OfflinePackStoreTest`、`OfflineCipherTest`、`OfflineSyncPolicyTest` 不能在未处理此问题时直接运行；不得以复制、overlay、改名或超时默认同意绕过。接手时先核对用户是否已有明确后续答复，不要重复要求已获授权事项。

### 5.2 第50轮：设备保存证据的AI桥接基础

目标不是把设备记录转成仓库ID后调用旧历史prepare；那会读取当前仓库核验、身份与冲突，改变所选历史材料。

当前已有三个内部模块：

| 模块 | 能做什么 | 当前验证 |
|---|---|---|
| [device_ai_projection.py](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/device_ai_projection.py) | 原bytes严格解析、保留数字lexeme；按精确snapshot/variant/verification和来源回执做单观察/完整批准闭包；默认private、restricted拒绝 | [core-tests-c](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/core-tests-c/receipt.json)：**97/97** |
| [device_ai_models.py](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/device_ai_models.py) | 准备记录和一次Provider consent claim；唯一约束、actor复合FK、回滚、实例及结构化DML防改写 | [models-final-tests-f](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/models-final-tests-f/receipt.json)：**56/56 = 47模型＋9既有迁移回归** |
| [device_ai_archive.py](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/device_ai_archive.py) | server actor所有权优先，再核对descriptor/object/原bytes SHA与size；外部actor读取前404；返回 `OwnedArchive`，不授予AI权力 | [archive-tests-a](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/archive-tests-a/receipt.json)：最终 **92/92** |

这些数字是已封存的历史运行结果，本次只读核对了源码与回执，未重跑。独立审查有 [42项pure core＋54项无DB AST检查](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/independent-core-review-a.json)，不与负责人测试数相加为“一套全绿”。

- [projection-vectors-a](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/projection-vectors-a/manifest.json)：20个原producer领域案例（17接受、3测试事件restricted拒绝），16个parser字面样例（5接受、11拒绝），123个绑定文件；**不是三Host已通过parity**。
- [共享DTO草案b](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/public-types-draft-b.ts)及[验证](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/public-types-draft-b-verification.json)：strict tsc通过、14个编译见证；**仍为draft，wire未冻结、未导入产品协议**。
- [方案](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/proposal-a.json)与[架构澄清](E:/Mix/project/tire-info-manage-sys/.artifacts/device-ai50/architecture-approved-b.json)保留完整五类引用、四类查询及仓库分支义务。

**尚未实现的整链**：共享runtime decoder → Host本机预览 → 一次API选择导出同意 → actor-owned prepare/当前权利/撤销gate → 独立Provider同意 → 既有SSE reservation/grounding → 精确引用重开CAS → 报告/同步与各域组合。

未注册device API endpoint，未在 `Database.initialize` 注册新模型，未注册/执行012迁移，未接任何Host或真实Provider。模型外键不能独立证明OfflinePack/AIRequest的actor及pack一致；结构化DML保护也不是原始SQL管理员权限边界。

当前pure core支持4类观察投影，测试事件因restricted政策明确拒绝；同一全局mode不能混合不同领域，个人上下文、跨包等未实现，不能永久从完整目标中删除。原producer包测试使用明确的合成所有权映射，不能声称重放了真实captured actor。

**数值和范围合同**：canonical SHA来自原source AST/lexeme，不从token DTO形状反推；`1e309`浮点拒绝，合法巨大整数另处理，保字面量不增加测量精度。单观察不能外带其他候选/整包默认冲突；闭包批准集合与projection SHA分别校验。Provider实际outbound预算要完整计量，44,000B纯投影限额不是可直接dispatch的承诺。

历史记录异常：DTO草案a曾被交错任务误改。a的TS已恢复原SHA，a-verification原始JSON无法恢复；旧SHA只留工具记录。b已如实记录事故并含快照，不应把a-verification称为原样封存。核心97、模型56、读取器92等独立回执未因此被替换。

## 6. 剩余工作与建议接手顺序

以下是执行顺序，不是缩减原需求。可并行，但每个agent须明确文件所有权。正常服务重启、011/012迁移、真实联网/模型/设备等条目是待办，本卡片不额外授予执行权限；接手者核对原会话已有授权与先决条件，已获授权的事项不要重复询问。

### P0：接手即核对

1. 保全整个dirty工作区、证据及正常库基线；先读本文、原规格、原计划最新段落及对应source/receipt。
2. 将第49/50轮当前状态同步到正式实施记录，防止README顶部旧摘要误导；不要抹掉历史失败或混合版本证据。
3. 核对Android授权答复，保持 `continuous_policies=false`；若无答复，只继续不触凭据的独立实现/验证。
4. 审查共享DTO b，补齐runtime验证与不同Host原bytes数值/parity实现。mixed-domain设计仍待定，不要未经审查冻结一个永久排除混合域的wire。

### P1：完成当前功能链路

1. **设备AI服务端**：从 `OwnedArchive` 出发，接当前visibility/rights/identity/revocation gate；metadata-only准备、projection/source/选择哈希、幂等与两张immutable ledger；审查并实现012 additive迁移及隔离迁移/并发/回滚验证。
2. **同意与旧接口防绕过**：Host导出同意与Provider同意独立绑定包、问题、模型和策略；旧 `/v1/ai/analyses` 与流式入口必须显式识别device origin，不能绕过新同意claim；复用现有reservation/SSE，不造第二套执行器。
3. **三Host与UI**：本机预览、一次决定、encrypted journal、owner/generation/SHA/clock/session fences、未知结果lookup；原bytes数值保真；引用重开；展示历史范围，保持source/provider失败独立。
4. **完整业务范围**：五类引用（tire/vehicle/test_event/recall/recall_search）、四类查询、闭包/混合域/显式个人上下文、报告及恢复。restricted事件不能靠改标签或allow_private开关擅自降级。
5. **第49轮验收收尾**：最新Windows资产运行与授权后Android Store/IPC/Keystore目标验收；最终能力旗标仅在对应runtime证明成立后启用。
6. **正常环境收尾**：先审查待执行DDL与保全方案，再正常服务重启/011、GET-only入口检查，生成唯一after49并核旧表/旧行/391封存文件。不要为了普通smoke直接启动会自动迁移正常库的默认入口。

### P2：原需求仍必须补齐

- 首代SU7/OE、更多车型、真实人工Golden和跨来源/测试覆盖。
- EPREL、其他P0品牌/安全源、专业测试来源与合法授权；更多型号/地区，不把当前小目录称为全量事实库。
- 车型/召回/测试/交易的实际字段权威与冲突治理；PDF解析、历史正式重新采纳、Parser OS隔离。
- 真实Responses/Embeddings、语义检索与引用/事实/身份/冲突评测；多Provider、reranker、全文RAG、推荐/信息流、BYOK/实际成本。
- 外部通知/Webhook、公共API鉴权与SDK产品化；生产账户/租户/RLS、密钥和审批。
- Windows应用关闭后独立调度、长周期/物理条件；macOS/iOS、真机/OS/browser矩阵、签名和上架。
- 生产PG/对象存储、可观测部署、备份恢复/灾备、Load/Chaos/SLO/WCAG及发布Gate。
- 价格库存、GraphQL/gRPC/MCP等后置项保留；Qdrant/OpenSearch按实际规模决定，不为凑技术栈立即部署。

## 7. 原规格的15项决策与发布标准

| 决策 | 当前采用/未决状态 |
|---|---|
| 轮胎类别、首发地区 | 按乘用车/SUV、中国＋EU/UK＋US建议实现；不代表商用/摩托已覆盖 |
| 本地知识库定义、Offline Pack大小 | 已按服务端仓库＋可选设备包实现；当前工程限额见第8节，完整单机另行决策 |
| 完全单机运行 | 未指定，不能推导为已支持离线LLM或无需服务端 |
| 用户体系 | 本机个人会话PoC；云账户/团队Tenant未完成 |
| VIN | 默认不保存；不能自动扩展采集 |
| AI付费/BYOK | 现有本机配额不等于平台计费/BYOK产品；待明确 |
| 中国区Provider | 未指定；首个OpenAI Responses选择不能替代此决策 |
| 价格库存 | P2后置，未实现 |
| 专业测试授权 | 未指定；人工转录/描述不等于全文版权授权 |
| Win10支持期 | 按原规格兼容目标保留；长期承诺未定 |
| Native分发 | 签名DMG/MSIX与商店策略/资质待落实 |
| 用户量/SLA | 原文小型SaaS估算，生产容量/SLA未验收 |
| 企业私有部署 | 架构保留自托管；完整安装产品不在MVP、未交付 |

上表合并了两组相关决策行，覆盖原文15项；它们的“默认采用、已实现、产品待决”不可混淆。

正式V1的10项Gate都需要范围匹配的实际证明，当前不能全部打勾：

1. P0来源provenance覆盖100%。
2. 未经授权的在线查询本地回退为0。
3. 人工Golden SKU错合并为0。
4. AI事实回答引用覆盖100%。
5. 高危AuthZ/SSRF漏洞为0。
6. P0/P1未处理故障为0。
7. 核心流程WCAG2.2 AA通过。
8. 六类目标平台核心E2E通过。
9. Source Adapter健康监控及回滚。
10. 数据库和Parser均可版本回退。

原文另有13项首版SLO：服务端查询P95≤300ms、设备检索P95≤200ms、输入反馈≤100ms、移动LCP≤2.5s、Adapter自身开销≤300ms、健康来源live query P95目标≤3s、来源超时5–10s、通知lag≤5min、P1后可用性99.9%、RPO≤15min、RTO≤60min，以及无授权回退0/Golden错合并0。每项需独立填测量环境与结果；功能测试数不能代替SLO。

## 8. 不能破坏的约束与保全基线

- PowerShell必须用 `C:/Program Files (x86)/PowerShell/7/pwsh.exe`（PowerShell7），不能Windows PowerShell5.1。
- 原dirty工作及其他agent改动全部保留；不自行commit/push/stash/reset/clean/publish，不重写已封存回执。后续并行应继续用显式 `reasoning_effort=ultra`，核实际参数，不根据agent名字猜配置。
- 普通查询默认在线优先/ask；未回答与拒绝不能读取并返回历史参数。包存储授权、查询回退、同步、AI导出与Provider处理授权互不替代。
- Snapshot/Verification/Revision/Variant/TestEvent保持不同含义；304不是用旧数据冒充在线成功；R/ZR、区域、产品代码和技术配置不静默合并。
- `LOCAL SNAPSHOT`保留原observed/verified时间；打开、同步检查、prepare和重试不变成新核验。
- Source文本不授予工具/网络/写权限；`can_query/can_fetch`不是AI历史使用许可。
- 不读取或展示正常cookie/token/密钥，不用Codex登录凭证，不把密钥放聊天、源码或前端环境；不为复验默认开启真实AI/Embeddings。
- Parser生产上限保持 **8s、最多2进程、CPU5s、384MiB**，不能为通过验收放宽。
- 离线包每包8MiB、最多200证据/50车库/100关注/4000文档；本机已装原bytes总32MiB、16活动包。超限整次阻断，不能截断事实。
- 查询授权pending16、同host attempt池1024不淘汰旧attempt、审计64；持续策略16非撤销/64保留；@1/@2共用相应消费/attempt约束。设备AI新ledger不能擅自继承这些授权。
- 阶段/Mock/fixture/模拟Provider/源码/构建/真实浏览器/原生运行/真实官网/真实模型/生产接受是不同证据，不能相互冒充。

唯一before49：[round49-before.sqlite](E:/Mix/project/tire-info-manage-sys/.artifacts/runtime/round49-before.sqlite)，**26,181,632B**，SHA：

```text
33776ded3a4fa04fc27bc3fd1a0910d7f85dea62f45e0e4c399ea60f0269ac05
```

本次实读hash与原值一致，`round49-after.sqlite`不存在。基线对应107表、会话131/审计123；旧保全记录含391封存文件及objects0。这里的行/表统计来自已有快照记录，不是本次读取正常库所得。正常库011与第49轮after收尾未完成，不能覆盖before或凭空生成“已保全”结论。

基线记录与复核入口：

- [第48轮最终保全结论](E:/Mix/project/tire-info-manage-sys/.artifacts/device-sync/runtime48-final-preservation-20261001-062136/conclusion.json)绑定[107表与391文件完整报告](E:/Mix/project/tire-info-manage-sys/.artifacts/device-sync/runtime48-final-preservation-20261001-062136/report.json)。状态 `passed_with_session_additions`：只会话130→131，其他106表行多重集不变；不能写成107表所有行完全相同。其唯一after48与before49是同一SHA。
- [391文件基线manifest](E:/Mix/project/tire-info-manage-sys/.artifacts/runtime/round48-normal-files-before.json)的 `data/parser-bundles.files` 是相对路径→SHA映射，共391项；`data/dev.db.objects` 为 `exists=false`、0文件。旧数字据这些既存记录，不是重新扫描或打开正常库所得。
- [前置保全报告](E:/Mix/project/tire-info-manage-sys/.artifacts/device-sync/runtime48-preservation-20261001-a/report.json)位于正常浏览器新增会话之前；与最终报告的会话差别须保留。
- [最终比较脚本](E:/Mix/project/tire-info-manage-sys/.artifacts/device-sync/runtime48-final-preservation-20261001-062136/verify_final.py)与[前置只读脚本](E:/Mix/project/tire-info-manage-sys/.artifacts/device-sync/runtime48-preservation-20261001-a/verify.py)可作为审阅入口；它们绑定旧第48轮输入/输出，接手后先审阅，再为第49轮准备新入口。不要直接重跑会复用旧封存路径的历史脚本；本次未执行它们或创建checkpoint。

旧完整API测试终态为 **2030通过 / 1失败 / 77 subtests**；剩余telemetry fixture修后5个目标测试通过，没有再次全套重跑。不能写成“完整2031全绿”。最新各切片的小套通过也不能替代整仓完成证明。

## 9. 接手入口与安全的首轮验证

| 路径 | 用途 |
|---|---|
| `apps/api/tire_api/` | 领域、查询授权、来源、治理、知识/AI/报告与上述50轮模块 |
| `apps/api/tests/` | 相关业务、安全、迁移与纯模块测试 |
| `apps/web/` | Next中文工作台；修改前读其 `AGENTS.md` |
| `apps/desktop/src-tauri/` | Rust原生HTTP、存储、同步、授权与IPC |
| `apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile/` | Java原生HTTP、Store、Keystore、同步与授权 |
| `packages/domain-types/`、`packages/api-client/`、`packages/native-client/` | 共享协议、可注入SDK、原生传输 |
| `apps/worker/`、`scripts/` | 调度、构建、隔离验收与真实canary脚本 |
| `.artifacts/query-fallback49/`、`.artifacts/device-ai50/` | 本轮冻结协议、source绑定、失败记录和最新回执 |

先核对文件与SHA。需要重跑时，在独立的 **PowerShell7验证会话** 中使用已有 `.venv/Scripts/python.exe`；**以下是建议命令，本次交接未执行**。每次创建新的GUID目录，`--basetemp`指向其中尚不存在的子目录，避免pytest清空旧临时资料；JUnit和日志也写入新目录。

```powershell
# cwd: E:/Mix/project/tire-info-manage-sys/apps/api
$validationRoot = Join-Path 'E:/Mix/project/tire-info-manage-sys/.artifacts' ('handoff-validation-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $validationRoot) { throw '验证目录已存在，请生成新目录。' }
New-Item -ItemType Directory -Path $validationRoot -ErrorAction Stop | Out-Null

$env:TI_OBJECT_STORE_BACKEND = 'filesystem'
$env:TI_OBJECT_STORE_ROOT = Join-Path $validationRoot 'objects'
$env:TI_AI_ENABLED = '0'
$env:TI_EMBEDDINGS_ENABLED = '0'
$env:TI_OBSERVABILITY_ENABLED = '0'

./.venv/Scripts/python.exe -B -X utf8 -m pytest tests/test_device_ai_projection.py tests/test_device_ai_archive.py -q -p no:cacheprovider --basetemp "$validationRoot/core-tmp" --junitxml "$validationRoot/core.xml" *> "$validationRoot/core.log"
if ($LASTEXITCODE -ne 0) { throw "纯模块测试未通过，读取 $validationRoot/core.log；保留失败证据。" }

./.venv/Scripts/python.exe -B -X utf8 -m pytest tests/test_device_ai_models.py tests/test_offline_migration.py tests/test_query_fallback_migration49.py tests/test_ai_stream_migration.py -q -p no:cacheprovider --basetemp "$validationRoot/models-tmp" --junitxml "$validationRoot/models.xml" *> "$validationRoot/models.log"
if ($LASTEXITCODE -ne 0) { throw "模型/迁移目标测试未通过，读取 $validationRoot/models.log；保留失败证据。" }
```

已读fixture：models和archive的数据库主要是 `sqlite:///:memory:`；archive落盘对象位于 `tmp_path/synthetic-archive-objects`；三个迁移fixture明确使用各自 `tmp_path` 下的 `pre010.sqlite`、`private-pre011.sqlite`、`private-pre009.sqlite`，对象目录也限定为临时路径。上述目标不以正常 `data/dev.db` 为迁移输入；当前源码仍须在运行前核对，不能据卡片推定未来新增测试同样隔离。

环境变量只用于上述独立验证会话，不修改正常配置文件，验证完成后退出该会话。不要复用已封存输出，也不要在同一 `.next` 目录并行运行Next开发与构建。

`scripts/dev.ps1`、默认 `data/dev.db`、`3000→8000` 是正常入口的已知路径，**不是本次确认运行中的服务**。[数据库初始化入口](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/db.py:476)会自动建表并调用[迁移实现](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/migrations.py:96)，当前包含011；device AI模型和012尚未注册。正常服务启动需先核对既有执行授权、完成保全与待执行DDL审阅，不要当普通文档smoke直接启动。真实canary、真实模型、原生仪器与凭据操作不要混进这轮文档/纯测试核对。

## 10. 可直接交给下一个Agent的任务说明

> 接手 `E:/Mix/project/tire-info-manage-sys`。先完整阅读本卡片、原MD、实施计划最新记录和source-bound回执；保全未跟踪实现、正常库、私有资料及忽略的artifacts。完整目标保持原规格范围，不以局部green重定义成功。第49轮先处理真实待答的Android保留审批并完成最新原生联合验收；第50轮从已实现的projection/models/archive出发，审查DTO b，推进Host一次导出、服务端当前权利/owned/幂等、独立Provider同意、既有SSE/grounding及精确引用重开。模型、Host和平台旗标不能因类型/构建存在就启用。继续补原需求中的Golden/首代SU7/OE、其他来源、真实模型、macOS/iOS、生产安全和全部发布Gate。并行子agent使用ultra与明确文件所有权；不擅自提交、推送、发布或读出密钥。每次结论区分实际观察、历史证据、尚未验证，保留失败版本并使用新证据目录。

本文生成时只做只读盘点、回执/JUnit/source SHA核对和文档校对；未运行产品测试、模型、官网、数据库迁移、浏览器或设备，也没有提交/推送。历史检索助手返回 `query_project_not_mapped`，未使用其结果补造项目历史。
