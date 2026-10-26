# 第70轮：测试 AI 摘录边界与交接复核实施计划

**目标：**修复真实存在的“引用 ID 有效便接受未建立身份桥的 SKU 测试推断”漏洞；保留逐场事实摘录、原始成绩、独立的同场偏好解读和历史记录。完整性能/AI 推荐及完整 V1 继续未完成。

**架构：**在现有仓库 EvidencePack → Gateway → 同步/流式 grounding → 冻结报告路径复用同一个纯函数合同。含人工 TestEvent 的整包仅允许 fact 选择，展示由服务器生成；模型自由文和跨参测对象拼接不进入已校验结果。此轮不创建 SKU 身份桥，不改变测试或厂商事实，不迁移正常数据库。

**技术：**FastAPI/Pydantic/SQLAlchemy；共享 TypeScript 合同；React 三端共享界面。沿用已应用的 brainstorming、writing-plans、executing-plans 工作流与持续实施授权，不自动提交或推送。

## 1. 复核依据与取舍（实施前冻结）

- R69 `seal-current.py --audit` 现场通过：871 源码、256 展开 dirty、98 本轮证据、15 文档、244 旧证据保持、无 staged/unmerged；HEAD `4d0ef60fa2240146113a3fac172759c665cf339f`。旧证据只读。
- 原规格：精确身份第75行起；TestEvent与同场/跨场第160–180行；权重用于解释第225行；推荐输入输出第658行；禁止跨场成绩直排第796行。
- 独立离线复现：通用 `grounded_answer` 接受同时引用一个 `variant_id` 和一个无桥 `event_id` 的自由推断。另可只引用测试或规格事实，将未经证据支持的 SKU 推荐写入 inference/uncertainty，单条 ID 集合检查无法核验自由文语义。
- 方案 A：只禁止同一 claim 同引 test+SKU。改动小，但单引、跨 claim 和 uncertainty 仍可绕过。
- **采用方案 B：整个含测试包采用服务器事实摘录合同。**仍可分别摘录规格和不同场次事实；同一含测试 claim 只属于一条 evidence，最多一个参测对象。自然语言推荐留待有版本的身份桥和解释合同；已有 R65 同场偏好解读不变。
- 方案 C：立即建立身份桥及完整推荐。需要独立来源身份声明、双侧证据、权限/版本/失效和语义评测，本轮不仓促落地。后续设计卡明确边界。

## 2. 精确合同（实施前冻结）

### 2.1 识别与请求

- 新 `ai_test_contract.py`，当前合同版本 `test-grounding@1`，网关结构 schema 名 `test_evidence_answer`；固定 descriptor/boundary 不含客户端可提升的核验等级。
- 仓库含测试判别至少覆盖 `manual_test_*` 与 `event_id`，不得只依赖客户端/包内 purpose 标签；设备 origin 的既有独立合同不变，现 prepare 仍拒绝设备 test_event。
- 新旧仓库测试包都采用严格合同，无需改写旧包。普通无测试包沿用原网关合同；混合召回包同时满足既有更严格召回规则，不能因测试分支绕过它。
- Gateway 的 Responses/chat/Anthropic、同步/流式均使用同一 schema/prompt，预算按实际选定 prompt/schema 计算；`analysis_contract` 记录版本及测试边界。不调用真实 Provider。

### 2.2 grounding 与流式

- 整个含测试包拒绝任何 `inference` 和非空模型 `uncertainty`，包括只引 SKU 的 claim；允许空 claims+空 uncertainty，由服务器给出证据不足边界。
- fact 的 text 为空后由服务器从冻结字段生成；ID 去重/归属门禁保持。
- 含测试字段的单个 claim 必须只属于一个 evidence、最多一个 participant_key，不能把测试+SKU/车型/召回或多个场次/参测对象拼成一条断言。同一参测对象的多个指标可并列摘录；不同参测对象以独立 claim 表示。
- 服务器固定 `test_boundary` 指明人工转录未核验、参测对象身份未与 SKU 建立、无适配/推荐/跨场排名。不将文字边界描述成来源事实。
- `StructuredDraftProjector` 对完整 claim 复用 grounding，uncertainty 在产生 draft 前校验；`ai_stream_store.append_event` 的直接写入入口同样复用校验，非法文字不能绕过 projector 持久化或先流入 draft 再在终态拒绝。失败仍按既有固定错误码/usage 账本，不重试模型。
- 真实浏览器发现的附加优化：`stream_events` 在执行已终态且当前读取页无剩余事件时结束既有流窗口；终态但仍有分页时必须全部送出。进行中请求保留原25秒窗口、heartbeat、数量上限与reset门禁。原始开发代理终态展示约25秒，优化前后分别保留观察；不以此声称真实模型延迟改善。

### 2.3 报告与历史

- 新含测试报告创建时固定 `test_boundary`，并用当前服务器规则复验已完成分析，不能通过保存/导出绕过。
- 新测试报告使用 `research-report@4`；其他新报告继续 @3，旧 @1/@2/@3 保留原历史导出能力。报告文档版本依冻结正文决定，不能在读取时给旧正文补新等级。
- 新测试报告选择 Renderer @5；旧报告保留原 Renderer @4，缓存查重、文档哈希与三格式正文按冻结文档选择版本，避免仅升级全局常量就改变旧导出字节。新报告 schema @4 必须验证固定合同、原始事实与 claim 作用域，自由推断/uncertainty、跨对象拼接或损坏 boundary 拒绝。MD/HTML/PDF均呈现冻结测试边界。
- 既有完成记录和报告不改写，也不宣称旧结果经本轮重新验收。新增报告尝试遇旧不合规分析时拒绝，历史读仍保留。

### 2.4 前端

- 共享类型增加测试边界；证据预览、结果、保存预览及冻结报告显示同一服务器边界。
- 测试入口文案改为 AI 摘录本场事实，解释仍由既有同场偏好入口提供。不出现完整性能推荐已完成的文案。
- 既有迟到响应/主体生命周期控制保持；共享组件不引入 next/*。
- 修复已登记的窄屏顶栏文字拥挤：移动顶栏用两行稳定布局，保留全部动作和44px触控目标，不截断“API未连接”状态。

## 3. 文件所有权与执行顺序

所有 agent 共用工作树，不撤销未知改动；只修改具名职责文件。

1. 后端 owner：`ai_test_contract.py`、`ai_analysis.py`、`ai_gateway.py`、`ai_stream_parser.py`、`ai_stream_store.py`；必要时 `ai_evidence.py` 仅输出边界，不改变冻结历史 payload。自己的回归测试用独立文件。先复现，再实施，再目标验证。
2. 报告 owner：`reports.py`、`report_rendering.py` 及独立 `test_test_ai_reports.py`；复用步骤1纯函数，不复制规则。必须验证旧导出保持及新三格式。
3. 独立验证 owner：`test_test_ai_grounding_review.py` 及本轮独立 artifact；不得改产品代码，不放宽已有预期来迎合实现。覆盖 Gateway、同步/流式、draft、召回混包与普通包回归。
4. Root：共享 TS 类型、AI/报告界面、测试入口与窄屏 CSS，以及追加的 `ai_stream_routes.py` 终态读页结束判断；SDK/类型、三端前端构建、真实隔离 API/浏览器验证、更新报告/交接/风险和最终封存。独立 owner 为 SSE 优化增加独立目标测试，不覆写前一阶段66项回执。后端/报告产品稳定后再构建和验收。

## 4. 验证与数据边界

- 证据目录：`.artifacts/r70-test-ai-grounding-f94df0c513fd4c05bc9138f955e3d737`；历史失败和新成功分开保存，不覆写 R69。
- 使用 `C:/Program Files (x86)/PowerShell/7/pwsh.exe` 与 `apps/api/.venv/Scripts/python.exe`；Python脚本/测试记录具名文件 SHA 前后。
- 全新 GUID 私有 SQLite/对象/Parser bundle；应用导入前清理宿主配置，关闭真实 AI/Embeddings；合成模型仅替换 fixture adapter。禁止外联/Parser子进程/正常数据库；不启动默认 app。
- 必测反例：无桥SKU+test推断、只引单侧绕过、uncertainty泄漏、跨claim、跨参测胎/跨场fact、非法stream草稿、旧完成结果保存报告、新报告损坏边界；正例：逐场/逐对象fact、普通SKU推断保持、同场偏好解读保持、召回规则保持、旧报告导出保持。
- 目标回归通过后不为数量重复全套。浏览器走真实私有HTTP，合成模型注明；断言数不称业务场景数，前端生产构建不称原生设备验收。
- 所有本轮进程和测试页收尾、生成配置按运行前SHA恢复；正常库/真实来源模型、PG、新原生设备、完整V1 Gate未验。

## 5. 终态（执行后追加）

已完成本轮限定补修与优化。后端核心212、独立66、报告126、SSE追加12分别同次通过；类型及三端前端生产构建exit0，25具名前端源稳定、23制品，7生成文件恢复。最终真实私有API29条、1440桌面16条及390/320各18条浏览器断言通过，使用合成模型adapter；终态展示实测1169/1166/1180ms。两次API实测exit0、Next主动停止exit1，8970/3371无监听、运行3配置恢复，原Chrome空白页保留。

旧红例、raw空白根因、夹具socketpair/路径/硬链接权限、Root QA参数/转义和窗口预期错误均保留，详见[终态报告](../assurance/evidence/round-70-test-ai-grounding.md)。本节及SSE追加范围的后续文档说明不冒充旧测试运行时计划SHA；产品合同未在验证后放宽。

完整性能/AI推荐、真实语义质量与完整V1未完成，Goal继续active。后续先收敛[精确测试身份桥设计卡](2026-10-18-test-sku-evidence-bridge-design.md)的来源材料入口与证据等级，再推进实现。未提交、推送、部署或迁移正常库。
