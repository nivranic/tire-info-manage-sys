# 测试成绩 PDF 原件引用 Agent 接手卡

更新于2026-11-14。本阶段从已发布 `8f5a604` 继续，将人工成绩的短摘录绑定到保存PDF的页码、Unicode码点区间、原件摘要与文档元信息，并贯通录入、修订、比较、AI及研究报告。完整V1持续实施。最终验证和发布状态见[阶段验收](assurance/evidence/test-measurement-pdf-2026-11-14.md)。

## 需求总览

原规格按12个核心模块、10项发布Gate、13项SLO和15项待确认决策组织，各维度分别跟踪。当前覆盖13个轮胎区域目录、9个厂商品牌、18项可信Parser和179张模型表。12模块均有工程实现，完整发布验收继续进行。[原规格](requirements/2026-09-26-tire-intelligence-original.md) [需求、Gate、SLO和决策总表](AGENT-HANDOFF-2026-11-14-PUBLISH.md)

| 模块 | 当前已有能力与主要剩余项 |
| --- | --- |
| 轮胎查询 | 在线优先、组合筛选、来源状态和授权回退已有工程，继续补其余P0来源、地区与长期稳定性 |
| 精确版本识别 | 产品代码、GTIN、OE、地区、冲突与Golden工作台已有工程，代表性真实SKU／批次与真人Golden待验 |
| 车型适配 | SU7前后轴、车库及SKU证据桥已有工程，更多车型、完整OE事实和真实Native消费待验 |
| 比较 | 精确SKU、保存比较、同场成绩与条件偏好已有工程，本阶段补齐成绩PDF引用，专业解释与真实推荐质量待验 |
| 测评数据库 | TestEvent、环境／指标、身份桥和追加历史已有工程，本阶段补齐原件区间核对，精确SKU正例及真人复核待验 |
| 信息监控 | Worker、参数变化、NHTSA、Safety Gate、中国召回、通知与任务SSE已有工程，自然长周期、通知lag和任意网页／PDF差异待验 |
| 传统CRUD | 来源、规则、偏好、测试、账户、Provider、Key和费用规划已有工程，全实体覆盖、BYOK、真实账单与生产权限待验 |
| 证据浏览 | 快照、摘要、Parser、HTML／PDF正文与可恢复引用已有工程，完整用途治理与生产对象存储待验 |
| 个性化 | 车库、关注、偏好、保存比较和非SKU兴趣已有工程，跨设备、长期运行与真实质量待验 |
| AI研究 | grounding、同步／流式、报告、FTS／向量／融合检索已有工程，本阶段补齐成绩原件用途核验，真实Responses／Embeddings和语义质量待验 |
| 对外能力 | REST、SSE、SDK、Webhook、API Key、SQLite／PG受许可读取已有工程，公网接收端、吞吐、SDK产品化与完整WebSocket待验 |
| 管理后台 | Parser健康／发布回滚、隔离、纠错和审计已有工程，生产IAM／Tenant／RLS、完整角色治理与灾备待验 |

## 本阶段改动

1. `Measurement.pdf_reference`复用 `DocumentTextReference`，记录文档ID、文档指纹、完整SHA、抽取版本、页码、码点区间与chunk摘要。单场最多32段不同引用，短摘录仍按每项300字、总计8000字检查。
2. 创建和修订先从保存原件恢复对应区间，确认短摘录为区间内的原文子串。隔离解析后取得写锁，再检查原件绑定及修订代次。
3. 空引用在序列化时省略，旧事件指纹保持兼容。引用保存在既有JSON修订中，历史和比较保留完整值。
4. 新增独立 `test_pdf_policy = test-pdf-original@1` 冻结标记，AI准备、受理、实际派发、流式终态及报告导出复用正文原件和具体用途检查。撤回、过期、接收端变化及原件失配沿既有权限链处理。
5. Web可搜索并选择已保存PDF，移除或更换引用，在比较、历史、AI字段与报告中恢复原件，并进入既有用途对话框。SDK通过既有接口传递完整引用。

核对范围是短摘录与保存原件区间的对应关系。成绩数值解释、测试关系、参测身份和精确SKU关联继续遵循人工转录、身份桥与人工复核流程。现有报告schema与渲染版本继续承载结构化引用。

## 代码入口

- 后端合同与原件检查在 `apps/api/tire_api/document_text_contract.py`、`test_measurement_originals.py`和`test_events.py`。DTO从原模块移出以解除实际循环依赖，`document_text.py`继续导出原名称。
- AI与报告在 `ai_original_text.py`、`ai_evidence.py`、`ai_gateway.py`、`ai_analysis.py`、`reports.py`和`report_rendering.py`。
- Web在 `test-pdf-values.ts`、`test-pdf-citation.tsx`、`test-pdf-picker.tsx`，以及既有成绩编辑器、比较、AI和报告组件。
- 共享合同在 `packages/domain-types/src/index.ts`。实施顺序和回归入口见[计划](plans/2026-11-14-test-measurement-pdf-references.md)。

## 真实材料与验收范围

前阶段捕获的《Ultra Low Noise Poroelastic Road Surfaces》仍为当前1份专业研究PDF，DOI为 `10.3390/coatings6020018`，15页，第15页声明CC BY 4.0。原件SHA为 `00e7c08c6fe2dddee4444f22db86fcacb7b726b7aa69073f02291aac75a64be4`。来源、原表疑点、许可与保存范围见[材料交接](AGENT-HANDOFF-2026-11-14-MATERIAL.md)。

第9页图8／9提供柱形与刻度，逐胎精确值仍需可核对的原始数值材料。本阶段成绩验收使用项目生成的合成PDF和明确合成成绩，模型采用合成Responses。真实SKU、真人Golden与实际OpenAI模型网络继续待验。

## 已验证与待验

扩展账户切换复现已有P1候选归属缺陷。同一浏览器退出后注册第二账户，前账户报告仍出现在列表，原会话行已被重绑给第二账户。该批整体失败，报告持久归属隔离待修。原始页面、数据库核对与代码路径见阶段验收，相关发布Gate保持开放。

最终受管两批315／315与122／122通过，867输入稳定。Web68项、正文SDK7项、成绩引用SDK5项、既有偏好合同、全工作区类型与生产构建通过。非拥有者PG／TLS9项及首批完整生产浏览器15项通过，三种宽度均无横向溢出。19条服务记录、30个进程ID、11个端口与临时秘密已核对关闭。部署合同、失败与完整回执见阶段验收。首轮失败及其原因保留，接手时先核对最终回执和工作区状态。

API源码变动后，部署须重新生成并审查与目标PostgreSQL主版本、catalog和向量索引匹配的 `postgres-runtime-schema@4` 合同。当前专项已有独立非拥有者PG／TLS验收，生产远端部署继续待验。

## 接下来做什么

优先修复上述账户归属缺陷，联合验证匿名资料、退出失效、过期回收、同账户多会话及报告／AI等私有数据的归属。

1. 从可核对的专业材料推进真实参测对象、条件与原始数值转录，开展真人审核和代表性Golden。保留研究编号、原文疑点及精确SKU待核对状态。
2. 根据实际复用范围登记AI、Embeddings和导出用途，继续材料授权治理与真实质量验收。
3. 继续自然长周期监控、真实变化、通知lag及恢复，收集原规格通知≤5分钟的证据。
4. 真实AI优先采用用户选择的OpenAI Responses API。此前缺少模型／Embeddings凭据及EPREL Key，继续推进可独立完成的工程。
5. 继续Parser间歇超时和Windows文件打开耗时取证、公网Webhook、生产部署与权限、Native／设备、六平台E2E、读屏、性能及灾备。

## 接手边界

用户已授权持续实施、自行选材、验证、提交、push和更新交接。沿既有main工作，PowerShell使用7，分支／worktree与代理另按明确授权处理。原件、数据库、截图、私有脚本和凭据保存在Git忽略目录，新clone需重建运行环境与验收材料。旧KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 保持既有封存操作边界。

```text
git status --short --branch
git log -8 --oneline --decorate
git log --oneline origin/main..HEAD
git ls-remote origin refs/heads/main
```

> 继续实施胎迹完整V1。先读本卡、阶段验收、PUBLISH需求总表与原规格，核对当前源码、工作区和实时远端。复用已保存PDF及本阶段成绩原件引用链，推进真实原始数值、身份桥、真人Golden、材料用途与发布Gate。首个真实Provider使用OpenAI Responses，缺凭据时继续独立工程。保留合成验证、真实原件和生产验收各自范围，交付时核对提交、远端与全部临时资源。
