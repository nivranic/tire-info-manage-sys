# 胎迹 Agent 交接卡

> 当前入口为[2026-11-13交接卡](AGENT-HANDOFF-2026-11-13.md)，正文证据包、OpenAI Responses同步／流式、独立用途与报告导出已接通。最终269项API、58项PG及153表备份恢复、30项浏览器、SDK9项、Web50项和生产构建通过，材料与Provider采用合成夹具。真实模型语义及完整V1继续待验。本卡保留此前阶段的详细记录。

更新于2026-11-13。汇总原规格完整V1的当前实现、验证、剩余需求与接手顺序。完整V1目标持续开放。

## 当前停点

完整需求共12个核心模块、10项发布Gate、13项SLO和15项产品／技术决策。各模块已有工程实现，10项发布Gate均保留待验收项，当前仍在补齐完整V1。

原文RAG第1步后端由 `675f968` 交付，第2步共享类型、SDK及Web正文检索／引用查看由 `54e749d` 交付。PDF基础工程为 `21d00a7`，后续 `5a29f39` 接通知识检索中的PDF结果和页码引用，已有合成材料、生产浏览器及真实PostgreSQL验收。正文向量用途授权、035迁移、独立文本合同、计划／共享执行链、SDK与Web入口已实现。当前首项为正文向量召回／融合／重排，再贯通正文证据包与Responses链路。[实施计划](plans/2026-11-12-original-text-rag.md)

用户选定OpenAI Responses API作为首个真实AI接入，默认Provider为 `openai_responses`。本机OpenAI配置及EPREL Key此前核对缺失，独立工程可继续执行。Gemini适配属于此前Agent依据规格自行提前安排的工程，详细来源见下文AI接入决策。

前次交接复核起点为 `a1c6da619a0172b97761517c8d44e68261a9e570`，当时本地HEAD、跟踪引用与实时远端main一致，工作区干净。正文向量工程自 `7a64b23` 继续，原件、用途与缓存的具体设计及执行记录见[正文向量计划](plans/2026-11-12-text-embeddings.md)。当前完整V1及真实模型、材料、平台验收继续开放。

## 已交付工程与验证摘要

- 需求依据为仓库内[原始规格](requirements/2026-09-26-tire-intelligence-original.md)，包括12个核心功能模块、10项发布Gate、13项SLO目标和15项产品／技术决策。现有报告没有支持整体完成百分比的统一验收口径。
- 迁移029–032及来源地址迁移的后端、共享协议、SDK和Web界面已交付。此前完成pgvector直连参数、开发库演练及原规格中的多模型适配。本轮继续Responses生产Web终态额度及流式验收，提交序列见下文与Git历史。
- 来源地址迁移提醒的损坏历史读取已修复。四模块受管批127／127通过，包含六个端点损坏反例及两个异常传播反例。
- 此前真实PostgreSQL运行47项检查通过，新增029–032对应业务的事务回滚、历史冻结、并发停止、原生写保护及恢复验证，覆盖实际dump／restore和147张模型表恢复指纹。七模块受管回归204／204通过。前次45项及11项兼容回归保留各自历史范围。隔离集群已停止，验证端口55452复核为空闲。
- 随后独立构建pgvector 0.8.1并在PostgreSQL 18.3上完成10项运行检查及12项业务检查，149张业务表备份恢复指纹一致。Embeddings／知识检索受管回归55／55通过。固定合成向量场景的Recall@2为1.0，真实模型语义质量继续待验。
- 既有开发库经只读备份后，在副本完成015→032升级，113张原表的历史列和值保全。四个迁移故障点完整回滚，升级副本与恢复副本均通过15份原文及97条历史检索结果读取，整库备份回退恢复015。原开发库SHA保持一致。
- 数据库引用的归档旧后端也已在还原的015副本启动，15份原文及历史检索读取通过。迁移相关五模块受管回归154／154通过，限定证据及部署剩余项见下文。
- 多模型网关适配及共享授权／价格／遥测已交付。首个真实接入优先OpenAI Responses。后续15模块受管回归376／376通过，三端类型检查与前端生产构建均通过，详见下文。
- 首个真实AI接入已选OpenAI Responses API。EPREL Key当前缺失，其他工作继续独立推进。专业材料由Agent自主选取。
- Responses终态额度自动刷新及旧响应仲裁已修复。8种流式模式与关闭恢复通过生产Web合成验收，9次合成调用落账4个completed、4个failed、1个outcome_unknown。本轮50项Web测试、三端类型及Web生产构建通过，私有服务已关闭。
- 后续额度故障浏览器验收通过，覆盖终态503、手动刷新恢复、过期错误、关闭取消及迟到成功／错误。4次明确提交对应4次合成调用，最终2400 tokens。生产构建复用，402个前端及775个后端回归输入保持原字节，私有服务已关闭。
- 后端基线 `675f968` 新增033正文派生索引及正式HTML／文本快照的FTS搜索、哈希绑定引用恢复API。五模块204／204及真实PostgreSQL49项检查通过，149张模型表实际备份恢复指纹一致。后续正文SDK／Web已接通，当前执行结果见下文。
- 前次材料研究核对四份候选，后续新增JRC及PERS论文线索。PERS许可已定位至原件的CC BY 3.0，生产捕获明确落账timeout，直连15秒诊断仍在TCP连接前超时。新增保存成功的原件、TestEvent、精确SKU关联和外部真人Golden均为0。旧KIT C2继续封存。
- 发布级旧库迁移、真实模型语义、生产来源覆盖、原生平台矩阵和完整无障碍仍待验收。

## AI接入决策与排期

- 用户已明确选择OpenAI Responses API作为首个真实接入。`apps/api/tire_api/ai_gateway.py` 的配置读取及配置对象默认值均为 `openai_responses`。
- `TI_AI_PROVIDER` 可以覆盖代码默认值。接手启动本次Responses验收进程时，在该进程环境显式选择 `openai_responses`，再核对AI状态接口返回的Provider。模型与专用Key由服务端环境提供，凭据齐备及实际调用结果分别记录。
- Gemini来自原规格第710行的多模型接入表，用途为大上下文／多模态备选。此前Agent自行决定提前开发，正式提交为 `d5fded1`。该排期属于Agent的实施选择。已有适配器及合成回归，真实Google调用仍待验证。[原始规格](requirements/2026-09-26-tire-intelligence-original.md)
- 后续优先推进Responses真实语义与API→Provider→Web链路，额度读取故障的合成浏览器验收已完成。真实调用需要本机配置及符合材料用途的输入。材料选择已授权Agent自主决定，可继续核对公开出版许可并记录实际允许的用途。

## 正文向量后端与SDK

工程提交为 `985338f7bf89c6d0b5222f8c804c62332f07ea2a`。

新增035及 `text_embedding_authorizations`，以只追加修订记录具体引用、接收端、声明用途依据、公开性和到期时间。用途声明由管理员提交，建立向量仍需个人单次外发确认。撤销支持保存的scope_hash，覆盖原件损坏、配置移除及过期许可元数据。接收端scope可随授权提交确认，正文缓存绑定完整端点与模型空间。

| 入口 | 当前交付 |
| --- | --- |
| `POST /v1/knowledge/text-embedding-authorizations/preview` | 本地恢复HTML／PDF原件引用，返回摘录、接收端与许可修订 |
| `POST /v1/knowledge/text-embedding-authorizations` | 管理员声明授权或撤销，按expected_revision执行乐观修订 |
| `POST /v1/knowledge/text-embedding-plans` | 选择最多32条不同原件引用，本地准备original-text-semantic@1计划 |
| `POST /v1/knowledge/embedding-runs` | 复用既有同意、幂等、共享预算、只追加账本、缓存及恢复入口 |

准备、受理、外发前及回写均核对原件和当前授权。PDF通过受限Parser恢复逐页文字，外发前同步持久化核对在工作线程完成。Provider等待结束后再次核对用途，调用期间撤销时保留实际用量并拒绝回写向量。

六模块r4为239／239，包含正文28项、Embeddings29项、HTML正文41项、PDF正文24项、初始化5项及旧库升级112项。后续增加三项边界反例并修正，r6两模块60／60，包含正文31项及Embeddings29项。两批各有792个执行期间稳定的输入，资源关闭、非自检拒绝0。r6为本次正文执行链的最新绑定，SHA256 `913f1842bdc1a38db9c2dc5c00ddcf6c104d04ecb00f08883728fdc9737e1943`。

SDK三个专项5／9／7分别通过，三端最终类型检查及现有Web50项通过。向量历史结果补充正文合同提示。正文授权／索引Web面板的后续交付见下节，正文向量召回／融合重排、证据包与真实模型语义继续推进。具体文件、原始失败及执行顺序见[正文向量计划](plans/2026-11-12-text-embeddings.md)。

真实PostgreSQL18.3与pgvector完成54项检查，153张模型表实际dump／restore指纹一致。新增HTML／PDF正文向量、原件引用、真实余弦及撤销检查，恢复后从备份对象读取PDF、复用向量缓存、重读账本，并实际拒绝授权表UPDATE／DELETE／TRUNCATE。1072项归档目录中的2项扩展元数据由管理员恢复，1070项业务对象由非超级用户应用角色恢复。模型采用固定合成向量，真实语义继续待验。

最终报告为 `.artifacts/postgres/pgverify-0569be10ddbf4accb2421ff0628798e5/report.json`，SHA256 `c06d174362eb8aaa1aa515760d3bba994df3cc3467d540a8c6c212b01d7fefe0`。集群已停止，独立pg_ctl状态exit3、55466无监听。完整验证汇总与关闭证据在 `.artifacts/text-embeddings-20261112/`。前三次恢复失败分别为扩展创建权限、扩展注释所有权和新增源数据晚于身份指纹冻结，原报告及日志保留，处理与范围见续作记录。

## 正文向量Web与合成验收

HTML／PDF正文卡已提供引用选择、选中样式、用途预览和管理员授权／撤销。每批最多32段，分页保留选择，编辑知识检索条件或重新提交查询时清除。用途窗口显示恢复原文、原件绑定、完整接收端、正文哈希及修订，管理员明确填写依据、公开性及可选到期时间。撤销使用已读scope，配置移除后仍可提交。失败或停止等待后通过显式读取核对最新结果。

正文索引复用现行向量工具，单次外发确认、固定幂等标识、预算、缓存计划和调用历史共用既有入口。账户重验证会重建用途／向量窗口，迟到的旧请求按原操作和账户状态裁决。管理员用途授权与个人外发确认分别执行。

本轮四模块受管回归125／125，792个输入稳定，资源关闭、非自检拒绝0。生产浏览器完成42项交互／布局检查，末次补充选择说明、可访问名称和选中样式后，独立生产构建及6项界面复核通过。三端最终类型、Web50项与SDK正文向量5项通过。320、390及1440像素用途窗口均无横向溢出。

浏览器验证覆盖HTML与PDF、匿名／管理员／研究员、32段上限、全部引用用途核对、配置缺失后的撤销、并发修订冲突、过期时间、单次同意、回执丢失后同标识恢复、缓存／历史，以及取消／关闭／账户切换后的迟到响应。两次已完成合成模型调用对应两条请求及30 tokens，缓存共3块。首轮PDF完成观察超时后核对同一原请求取得完成结果，执行次数保持2。

本轮浏览器采用隔离SQLite、自有合成原文、合成Provider和模拟向量存储能力。真实PostgreSQL／pgvector沿用上一节独立54项报告，正文召回、真实语义及完整V1继续验收。回执入口为 `.artifacts/text-embedding-web-20261113/` 与 `.artifacts/txweb-r1/result.json`。API退出0，Web经SIGINT退出1，验收页面已关闭，服务端口的独立复核见本轮关闭回执。[续作记录](assurance/evidence/continuation-2026-11-12.md)

## 最新正文检索工程

`675f968` 完成本地原文RAG的首步后端。现行两个入口为 `POST /v1/knowledge/source-text/search` 和 `POST /v1/knowledge/source-text/resolve`，请求显式指定 `mode=history`。搜索支持文本、source_id及分页，范围为轮胎查询中各查询最新正式核验的HTML／文本快照。引用恢复支持旧正式快照，按原始SHA256、抽取版本和Unicode码点区间重新读取原文，即使派生投影已清空，也能恢复原摘录。

- 033新增两张派生模型表，SQLite采用FTS5，PostgreSQL采用GIN／tsvector。部分分块或FTS行丢失后可从原文重建。
- 1200字符分块、120字符重叠。抽取排除脚本、样式、模板、注释及显式hidden／aria-hidden内容，正文文本以来源摘录表达。
- 引用字段为 `snapshot_id`、`raw_hash`、`extractor_version`、`start`、`end`、`chunk_id`，当前抽取版本为 `source-html-text@1`。返回的 `offset_unit` 为 `unicode_codepoints`，区间采用左闭右开。Web接入需按Unicode码点处理，JS字符串索引使用UTF-16代码单元，显示摘录可直接采用服务端恢复的 `text`。
- 引用核对正式快照、查询核验、原件哈希及已保留的对象引用。原件或对象损坏明确报错，派生命中的文本再次与原件绑定。
- 最终五模块受管批204／204，包含41项新模块用例，778个输入稳定、资源关闭、非自检拒绝0。真实PostgreSQL18.3的49项检查包括正文全文检索、重启、引用恢复及实际dump／restore，149张模型表指纹一致。

本机回归回执为 `.artifacts/srctxt-r5/result.json`，SHA256 `421915de17394261a562a3b02d477bc960b9729f7262d8397adf6072f513f5db`。PostgreSQL报告为 `.artifacts/postgres/pgverify-6d362e0ab1fb475698d0f237c2608f4b/report.json`，SHA256 `db4789c47a314582d2e0e38ad642e1eea45b17b6e5f9fedbf0e2dfff17860d59`。集群已停止，pg_ctl独立状态exit3，55462无监听，关闭回执在 `.artifacts/source-text-pg-20261112/`。

首步执行范围为合成原文上的生产API、SQLite及真实PostgreSQL。后续SDK／Web的新增结果见下一节。完整实施顺序见[原文RAG计划](plans/2026-11-12-original-text-rag.md)。

## 正文SDK与Web第二步

历史知识检索已接通正文路径。关键词及来源范围的结构化结果为空时自动查询正文，已有结构化命中时可手动补充。精确SKU及其他实体条件继续由结构化路径处理。正文卡显示来源、快照、哈希、抽取版本及Unicode码点区间，并支持按保存引用重新读取原件。显示使用服务端摘录，编辑、取消和关闭均有旧请求仲裁。

本轮SDK合同9／9、Web测试50／50、三端类型及独立Web生产构建通过。正文／知识检索两模块受管回归67／67，780个输入稳定、资源关闭、非自检拒绝0。生产浏览器在合成原文上完成24项业务及请求仲裁检查，覆盖分页、旧引用、原件损坏、显式来源和精确筛选。1440、390及320像素视口均无横向溢出，窄屏引用恢复通过。400个前端输入与构建前逐字节一致。

本机回执为 `.artifacts/source-text-web-20261112/verification.json`，SHA256 `67baa05c803872de3ea3966a027ddc5eb2c321e79d999948a586588a224f50ae`。API回归为 `.artifacts/stweb-r2/result.json`，SHA256 `77c589c0c49cda6a653b26cd16fcf1a27db222624087a0c0abe768962ab805b4`。私有API退出0，Web经SIGINT退出1，浏览器页已关闭，8003及18002均无监听。来源调用、真实Provider、外网尝试和正常数据库使用均为0。该批范围为HTML／文本正文。PDF当前交付及剩余项见下节，正文向量／融合／重排、证据包、真实模型与原生平台继续推进各自实施和验收。

## PDF逐页正文当前交付

本次新增固定内部Parser能力 `workspace-pdf-text@1`，复用现行GO握手、8秒超时、CPU／内存边界、并发限制和进程回收。pypdf移入生产依赖并同步锁文件，当前锁定6.19.0。034迁移新增文档索引、逐页文字和正文分块三张派生表，SQLite使用FTS5，PostgreSQL使用GIN。八、九、十来源历史Parser清单继续按各自能力运行，当前完整清单含十一项能力。

| 入口 | 交付内容 |
| --- | --- |
| `POST /v1/documents/{id}/text-index` | 显式history索引，在发布前后核对原件、文档及材料捕获凭证 |
| `GET /v1/documents/{id}/text?mode=history&page=1` | 状态与逐页正文，区分全部有字、部分有字、无可抽取文字及加密 |
| `POST /v1/knowledge/document-text/search` | 搜索已明确建立的PDF正文索引，支持文档过滤及分页 |
| `POST /v1/knowledge/document-text/resolve` | 按文档、元信息指纹、原件哈希、抽取版本、页码、页内Unicode码点区间及chunk ID重新抽取并恢复引用 |

共享SDK已提供四个方法。原始文档卡新增提取／索引、状态重读和逐页查看，关闭、停止等待与卸载会取消前端请求采纳。索引已提交后停止等待，界面提示重新读取状态核对结果。原始凭证保留既有 `unparsed_receipt` 合同，正文索引与事实核验分别记录。

### PDF首批验证结果

| 范围 | 已观察结果 |
| --- | --- |
| 九模块API广批 | 332项执行，331通过、1失败，PDF两模块36项全部通过。失败处为历史十来源清单仍与当前十一项清单整体比较 |
| 最终Parser包专项 | 修正旧清单比较断言并同步受审哈希后，完整模块25／25通过，覆盖旧包实际重放及进程回收 |
| 共享SDK | 新PDF合同7／7、既有HTML正文合同9／9通过，覆盖四入口、页码／引用、错误及取消 |
| Web与构建 | Web50／50、Web／桌面／移动三端类型检查、独立Web生产构建通过，629个前端输入逐字节匹配 |
| 检出字节 | 固定20个受管文件各自现行换行格式，`core.autocrlf=true` 和false共40项暂存内容过滤检查通过 |
| 源码与资源 | 最终专项787个输入稳定，两个API批次资源关闭、非自检拒绝0。广批后变更范围为Parser包测试及其受审哈希清单两文件 |

广批保存在 `.artifacts/pdfh-r1/result.json`，SHA256为 `af5c872bba51431c05f35541fc097ceb6374a08ee7595a2ea1520efd311340f8`。该批结论为失败，原回执继续保留。最终专项在 `.artifacts/pdfh-r2/result.json`，SHA256为 `c15b715ffd6a4cb858a2d4a613317f414bcfebb33f96f5696a6d30e57ada5d2a`。最终受管输入核对、前端构建、SDK日志、检出检查及配置存在性记录位于 `.artifacts/pdf-handoff-20261112/`。

本次复核补齐生产依赖锁文件、SDK合同测试和20个受管文件的换行约束。Windows自动CRLF转换此前会改变18个受审文件的哈希，现按已审查字节固定LF或CRLF。OpenAI模型／Key、EPREL Key与Gemini Key在Process／User／Machine三个作用域均复核为空。PDF输入为合成材料，真实专业材料、模型语义、原生平台及本节后续验收各自继续推进。

### PDF知识检索与专项验收续作

知识检索沿用现有正文组件，分别处理HTML快照和PDF文档的结果与引用。无结构化筛选的关键词查询可自动补充PDF，结构化有命中时提供手动PDF搜索。结果保留文档名称、留存时间、元信息指纹、页码、哈希及页内Unicode码点区间，点击引用重新读取保存原件。来源、实体类型及精确SKU条件继续使用对应范围。

- 四模块API回归103／103通过，787个输入稳定、资源关闭、非自检拒绝0。新批回执为 `.artifacts/pdfs-r1/result.json`，SHA256 `ce74e243c01c01830cd98ecb2cbeaa434fb37a6a83f953a291339cdbe6de46db`。
- SDK16项、Web50项、三端类型及独立生产构建通过，629个前端输入逐字节匹配。
- 真实PostgreSQL18.3完成51项检查，152张模型表实际备份／恢复指纹一致。新增034、GIN查询、应用重启、第二页读取及备份对象目录中的原件引用恢复。报告为 `.artifacts/postgres/pgverify-fc411efb49894fee8a72dffaaf3ff0c1/report.json`，SHA256 `18e86f2b4443944f38ed4cc4f686acaba0eeb867015c2ac70b553bc26c8531f1`。
- PDF生产浏览器35项业务检查及HTML／PDF兼容5项检查通过，覆盖真实上传、索引、翻页、自动／手动检索、15条摘录分页、旧引用、原件损坏及修复、派生行清空、筛选、取消／关闭及迟到响应、无字／加密／损坏状态。1440、390、320像素视口均通过横向溢出检查，两个窄屏引用恢复通过。
- 首批夹具的结构化样本使用原文哈希占位值，产生12次HTML正文503。补齐合成原件绑定后，5项HTML／PDF兼容检查、相关请求和控制台检查通过。原错误及恢复后的回执分别保存，夹具启动顺序及浏览器断言中的details／异步按钮时序修正记录见续作报告。
- 两个私有API均退出0，两次Web经SIGINT退出1，两个隔离页面已关闭。PG集群已停止，独立pg_ctl状态exit3，8003、18002、55464均无监听。外网尝试、在线来源和真实Provider调用均为0。

本机汇总入口为 `.artifacts/pdf-search-20261112/verification.json`，浏览器原始尝试、最终检查、兼容结果及三个视口截图保存在同目录。PDF输入为合成材料，现有专业材料、真实模型及原生平台各自继续验收。

### 接手继续

先按原文RAG计划第4–5步为正文分块接入向量计划／缓存、融合与重排，再将所选正文引用冻结进证据包，贯通同意、预算、流式、grounding及报告。完整真实RAG质量、专业材料用途与精确SKU、实际部署、平台和无障碍继续按原规格验收。

## 最新额度故障验收

复用独立生产构建，通过新私有API／数据库和隔离浏览器上下文验证。浏览器只对额度读取注入503或控制返回时序，Provider继续输出合成Responses字节，解析器、应用服务、账本、HTTP／SSE及React界面均走现行实现。

| 场景 | 实际结果 |
| --- | --- |
| 终态额度读取503 | 已完成分析、引用及600 tokens用量保留，额度错误可见 |
| 手动刷新 | 正确恢复600 tokens，错误清除，Provider次数保持1 |
| 过期错误仲裁 | 第二次调用终态先读取成功，较早的受理额度错误迟到后，1200 tokens及无错误状态保持 |
| 关闭及迟到成功 | 第三次调用的终态额度读取仍等待时关闭面板，AbortSignal取消。显式释放迟到成功后面板保持关闭，重开恢复同一分析及1800 tokens |
| 关闭及迟到错误 | 第四次调用的终态读取等待时关闭，再重开至2400 tokens，随后释放旧503，当前结果、额度及无错误状态保持 |
| 调用与数据 | 4次明确提交、4个completed、24条流事件，合成Provider4次、来源1次、总用量2400 tokens，封存来源证据指纹保持 |
| 资源及输入 | API退出0，Web经SIGINT退出1，端口与私有临时存储复核关闭，checkpoint完整性ok。402个前端及775个后端回归输入逐字节匹配 |

本机核对入口为 `.artifacts/responses-status-fault-20261112/verification.json`，SHA256 `6567b3c633a2287ac6ee14de2f4e300ec6765a1a577f959d3e7ea72b8a1f24e3`。本轮取得浏览器故障验收新证据，类型、单元测试及构建沿用已绑定的历史结果。真实OpenAI、外网尝试、Parser子进程及正常数据库使用均为0。

首次私有API启动缺少既有 `TIRE_CORS_ORIGINS` 配置，查询返回403。按原响应补齐本次loopback origin后，在新槽完成验收。浏览器断言曾将1200 tokens的显示误写为紧凑格式，实际界面显示分组数字1,200，修正断言后通过。两项中间失败保留在本机记录中。产品源码沿用b1c3acb。

## 前次交付记录（aadc48d）

- 代码基线为 `b1c3acb2715d7c6adf6d01dd0f121ead952aff27`。本次补充交接说明、现场关闭记录和静态复核，应用源码沿用该基线。
- 已核对最新Responses终态验收的本机回执，原范围为8种合成流式模式、9次调用、50项Web测试、三端类型检查及Web生产构建。真实Responses语义和额度读取失败注入继续待验。
- 额度读取故障夹具曾启动私有API，浏览器故障验收尚未执行，Web尚未启动。现经夹具shutdown退出0，私有临时存储已清理，checkpoint完整性为ok，8003及18002均无监听。该槽的来源／Provider调用及分析请求均为0。关闭回执为本机 `.artifacts/responses-status-fault-20261112/closure.json`。
- Process／User／Machine三个作用域的OpenAI模型／Key、Gemini模型／Key及EPREL Key均为空。接手可继续完成独立工程和合成验收，外部真实验收按所需凭据推进。
- 下一项可直接执行的验证为终态额度读取失败后的结果保留及错误展示、手动刷新恢复、过期错误仲裁，以及终态读取期间关闭面板的取消行为。可复用现有生产构建，先核对产品SHA `6ac582fc0c299704a425fb7990e320961594395411eda6ee621b1308aa55993d`，为API创建新的隔离输出槽。
- 前序研究新增JRC作者论文候选《Wear of Passenger Car C1 Tyres Under Regulatory On-Road Testing Conditions》，DOI为 `10.3390/vehicles7030091`。研究记录提到CC BY 4.0，需继续复核原件、许可及试验条件。样本采用匿名代号，代号与品牌型号的映射尚待确认。当前处于研究线索阶段，捕获／TestEvent／SKU关联均为0。[出版页](https://www.mdpi.com/2624-8921/7/3/91)

本次静态复核确认最新终态回执及其9项关联文件哈希匹配，775个后端回归输入保持一致，15个本地文档链接有效。HANDOFF历史尾文保持216248字节及原SHA256。新增行个人路径／高置信度凭据模式检查零命中，差异检查通过。本机复核回执为 `.artifacts/handoff-review-20261112/validation.json`。本次新执行范围为文档、回执及资源关闭复核，测试与构建沿用上述历史执行范围。

## 需求覆盖

下表汇总实现及已有报告范围。各模块的正式验收仍需覆盖真实来源、身份、权限及目标平台。

| 核心模块 | 当前已交付范围 | 主要剩余工作 |
| --- | --- | --- |
| 1 轮胎查询 | 在线优先、单次授权后历史回退、组合筛选、来源与状态展示 | 更多P0来源、地区覆盖与长期在线稳定性 |
| 2 精确版本识别 | 产品代码／GTIN／OE／技术／地区身份、冲突修订及Golden工程 | 代表性真实精确SKU、外部真人审核与错合并指标 |
| 3 车型适配 | SU7前后轴、车库、轴位与SKU证据桥、官方PDF解析工程 | 首代官方来源online-ready、完整OE事实、更多车型及Native消费 |
| 4 比较 | 精确SKU比较、保存、同场测试候选及条件化偏好解读 | 真实专业性能解释与推荐、完整性能候选AI辅助 |
| 5 测评数据库 | TestEvent、参与者、指标、环境、原件捕获、身份桥及Golden工作台 | 真实精确SKU正例、合法原件与外部真人Golden |
| 6 信息监控 | Worker、参数变化、召回、兴趣提醒、原文变化、质量隔离、地址迁移事件与通知 | 任意网页／PDF差异、更多事件、真实长周期与交付可靠性 |
| 7 传统CRUD | 来源、规则、偏好、测试、修订、账户、Provider、外部Key及费用规划切片 | 全实体覆盖、生产权限、BYOK与真实账单 |
| 8 证据浏览 | 快照、哈希、解析版本、冲突、文本与二进制原文、PDF索引及逐页面板、未确认请求停止采纳，开发库副本升级／恢复 | 实际部署旧库切换、全域许可治理、正式再采纳及生产对象存储 |
| 9 个性化 | 车库、关注、七维偏好、保存比较、非SKU兴趣与账户生命周期处理 | 真实推荐质量、跨设备与长期运行 |
| 10 AI研究 | grounding、引用、流式解释与报告、多模型适配及向量检索工程，HTML／文本正文FTS和Web引用，PDF逐页抽取／检索／引用API、SDK与Web接入 | 正文向量／融合／重排及证据包，Responses真实语义与Embeddings质量、专业性能解释及模型治理 |
| 11 对外能力 | REST、SSE、共享SDK、Webhook签名与有限重试、Key及字段许可治理 | 真实接收端、公网生产验收、SDK产品化与完整WebSocket，后期GraphQL／gRPC／MCP |
| 12 管理后台 | Parser健康、发布回滚、隔离、失败任务、冲突、纠错、授权与审计 | 生产身份／租户／RLS、完整角色治理、灾备及发布验收 |

来源的既有交接记录为10个Parser来源，其中8个轮胎参数来源覆盖4个厂商品牌，另有NHTSA召回及小米车型来源。EPREL正式API接通待Key与官方协议资料。

平台采用Next.js Web／H5／PWA、Tauri桌面和Capacitor移动端。Windows／Android有历史局部运行记录，PWA有Service Worker断网重载记录。macOS／iOS、完整Native E2E、安装分发及全设备矩阵仍待验收。架构与历史细节见[前次交接卡](AGENT-HANDOFF-2026-10-26.md)。

## 最近完成及验证

### 来源地址迁移切片

迁移032、模型／守卫／监控／通知路由、client／domain-types与共享UI已落地。历史Web测试50／50、交互补测20／20及真实HTTP浏览器流程分别有报告。浏览器记录覆盖提醒面板、规则类型切换和创建地址迁移规则。详见[URL迁移报告](assurance/evidence/url-move-032-2026-10-26.md)。

历史默认清单全量批 `u032ful5` 为4947通过、13失败、54跳过，零守卫拒绝。原报告将13个解析器族失败归因于负载／时限轮转，并记录单测复跑结果。安静机器窗口下的完整全绿全量回执仍待取得。

旧R136 Parser两红及扩展批IPv6导入探针已在后续P2报告闭环，扩展批 `fvr-ex2` 为468／468、runner退出0、零拒绝。接手应结合后续报告解释旧失败。详见[P2闭环报告](assurance/evidence/p2-closeout-2026-10-26.md)。

### 2026-11-12损坏历史修复

根因是SQLAlchemy在ORM行装载阶段提前解码JSON和时间值，原有引用完整性校验尚未执行即抛异常。新增共同读取边界，将解码 `ValueError` 转为固定503 `source_page_history_invalid`，并验证DBAPIError及RuntimeError继续向上传播。

| 检查 | 结果与证据 |
| --- | --- |
| 四模块受管回归 | `test_source_page_url_moves`、`test_source_page_monitoring`、`test_monitoring`、`test_monitor_conditions`，127／127，runner退出0，失败／跳过／incomplete均为0 |
| 回归资源与副作用 | source稳定、资源关闭、非自检拒绝0，正常数据库启动false，真实Provider／接收端调用0 |
| 当前字节核对 | 产品文件和测试文件均匹配绿色批 `source-after.json` |
| 三个改动Python文件 | AST解析3／3通过 |
| PostgreSQL诊断函数 | 本地构造响应的成功分支及三种失败形式通过，原失败断言继续生效 |
| 差异检查 | 工程提交前 `git diff --check`通过，新增行的机器路径／凭据模式检查零命中 |
| PostgreSQL续作兼容回归 | 四个既有工作流用例及Windows架构环境模块11／11通过，runner退出0，25个managed_parser子进程均exit0、live为0 |
| 续作源码核对 | 六个改动Python文件AST通过，均匹配上述受管批的source-after绑定 |

绿色回执为本机 `.artifacts/urlbad-r2/result.json`，SHA256 `f745d81c5bb44ad4331c951686d8b4e533aea4fb4ec324dbfbaea387a7270471`。首个红批 `.artifacts/urlbad-r1/` 和独立诊断 `.artifacts/urldiag/` 已保留。

本次交付复核沿用已绑定源码的127项回归结果，额外执行哈希、AST与诊断函数检查。浏览器、前端构建、全量API／Worker、真实模型和设备的本轮结果仍待取得。完整续作证据见[2026-11-12记录](assurance/evidence/continuation-2026-11-12.md)。

### 真实PostgreSQL验收结果

使用既有验证脚本、PostgreSQL 18.3和全新loopback隔离集群，输入为合成夹具。最新单次完整运行47项命名检查通过，进程退出0。实测包括147张模型表逐行指纹和schema版本列表、10个证据对象、4个报告导出对象、3个不同Parser归档及恢复后的真实代码执行。该批 `vector_available=false`，后续pgvector独立实测见下节。

前期事实修订403 `admin_required` 已通过真实注册／登录修正。后续还修正了共享辅助入口的重复注册、验证进程缺少Windows架构元数据、旧查询全对象相等断言，以及合成身份数据缺少产品代码命名空间。四个持久化辅助入口保留独立注册默认路径，共享库由可选回调执行真实登录。身份辅助入口另已验证独立默认注册流程。

- 第一份失败回执位于 `.artifacts/postgres/pgverify-43ae2a889f7443d797df1bcd2691a5e7/report.json`。
- 第二份失败回执位于 `.artifacts/postgres/pgverify-ea650fde00f445f18ae44796ea654c1d/report.json`，SHA256 `ba4b39343292daf26780628b855df63e350980feaf23a8d23edf7489a6356c1f`。
- 最新绿色回执位于 `.artifacts/postgres/pgverify-1f9e174e87674047aaaf2bba4cf12723/report.json`，47项通过，SHA256 `34c54da3ce3cc26b06428ce49579eae966ec1f30fc44c54746b68f1bb48ebc7c`。实际备份684790字节。资源独立核对见同目录 `closure.json`，`pg_ctl status`返回exit3及 `no server running`，55452监听数0。
- 前次45项绿色回执位于 `.artifacts/postgres/pgverify-fb6bd9e0260748df87ae81e5d08cd691/report.json`，SHA256 `c21e5a1a1d31a01644181c3a43bb2294aa27e1abc7979b0abafe963c22eb1026`。前次兼容回归位于 `.artifacts/pghelp-r1/result.json`，11／11，25个Parser子进程均exit0，SHA256 `6d8d7078baea6b8a11eae91079d3cbf63135978808190c5d34dd1343b83a7d7a`。
- 本次七模块受管回归位于 `.artifacts/pghist-r1/result.json`，204／204通过，runner退出0，失败／跳过／incomplete均为0，SHA256 `ddb3f302310faf13e80d6d7307925a9713161be9a7eed8274038bd92a4d17546`。该批源码稳定、资源关闭，非自检拒绝、已知探针拒绝及其他拒绝均为0，正常数据库启动false、真实Provider／接收端调用0、子进程0。两个改动脚本均匹配该批source-after绑定，AST通过。
- 其余中间失败目录及根因链见[续作记录](assurance/evidence/continuation-2026-11-12.md)。正常部署旧库029–032迁移、真实模型检索质量和真实来源长期运行继续待验。

### 029–032业务专项

新增 `scripts/recent_history_acceptance.py`，通过现行API、应用工厂和既有合成夹具，在主PostgreSQL验收中固定执行，并在恢复库中重新核对checkpoint。

| 范围 | 已验证行为 |
| --- | --- |
| 029原文变化 | 冻结前后证据、已读幂等、晚建规则不补发，通知插入失败时采纳事务回滚 |
| 030质量兴趣 | 默认false及显式true、仅通知订阅者、质量隔离保留已采纳事实，退订后历史匹配条件冻结，通知插入失败时事务回滚 |
| 031停止采纳 | 合成捕获在物理put之后等待，两个独立应用／PG连接并发停止，分别得到stopped与already_stopped。迟到捕获保持stopped_unconfirmed，新增outcome／document／EvidenceObject均为0，原UUID重放读取既有结果 |
| 032地址迁移 | 同正文A→B→A迁移与原文变化分别记录，事件重入去重、晚建规则不补发，通知插入失败时事务回滚 |
| 原生历史保护 | 五张历史表的UPDATE／DELETE／TRUNCATE／重复INSERT拒绝，加上兴趣通知唯一约束，每个checkpoint共21次。应用重启及实际恢复库各执行一次，共42次 |
| 恢复历史 | 完整通知、兴趣修订、停止决定及原UUID停止／捕获幂等重放均保持 |

031场景的物理put执行1次，可能留下无引用对象。该结果沿用停止后续采纳且网络结果未知的合同。部署旧库升级、真实外部捕获及长期运行仍需各自验收。

### pgvector独立运行与业务验收

复用 `scripts/verify-pgvector.ps1 -BusinessChecks`，在本机忽略目录内复制已有PostgreSQL并编译固定官方源码。源码提交为 `778dacf20c07caf904557a88705142631818d8cb`，归档SHA256为 `5badef2cdfed828d93b7f70ae6ad38236e36954420bb24001aa5508e61bf2d7c`。下载显式直连。

- 10项运行检查通过，包含真实扩展创建、非超级用户写入1006个向量、维度／非有限值拒绝、余弦距离／硬过滤、HNSW实际执行计划、重启及pg_dump／pg_restore。合成语料在ef_search=100、strict_order下的Recall@2为1.0。
- 12项业务检查通过，包含计划／同意／幂等、并发请求与预算预留、cosine＋RRF、FTS与向量相同筛选、304及同事实缓存复用、模型／维度／隐私空间隔离、撤回排除、增量更新、失败固化、共享预算及应用重启。
- 业务库149张表逐行恢复指纹一致，保留3条向量和1个HNSW索引。业务查询使用筛选后的精确cosine扫描，HNSW执行计划由独立合成向量场景验证。
- 回执为 `.artifacts/pgvector/vectorverify-a7627452e5e649b7902891f21f8843a7/report.json`，SHA256 `a7fcc09f9d06109f2544f32919ef23929774ae022389229adc8aa38a713e6f13`。运行退出0，同目录 `closure.json` 确认pg_ctl status为exit3、端口55453监听数0。
- 相关回归为 `.artifacts/vector-r1/result.json`，55／55通过，runner退出0，失败／跳过／incomplete及非自检拒绝均为0，源码稳定、资源关闭，正常数据库启动false，真实Provider／接收端调用0，子进程0。SHA256 `0be2e2f88c0a7c9b31fc437a8bc01b6c2e1387453ef07e681bcd853c57a63c89`。

真实Embeddings检索质量、语义reranker、正常部署环境的扩展安装及旧库升级继续开放。上述检查使用固定合成模型输入。

### 既有开发库副本升级与恢复演练

使用既有 `scripts/backup_dev.py` 只读备份 `data/dev.db` 及Parser归档，随后在独立副本执行 `vehicle_binary_migration.private_rehearsal` 和当前 `Database.initialize`。初始库为15个迁移版本、113张SQLite物理表，完整性及外键检查通过。备份27996160字节、Parser归档1179个文件，对象目录文件与证据对象引用均为0。

- 显式024迁移后初始化到032，共154张SQLite物理表，113张原表的既有列和值保持。升级回执为 `.artifacts/upgrade-rehearsal-20261112/rehearsal-r1/report.json`，SHA256 `27261c8ade9ec60d68494dfda183d2e3b1b70401f3a517d0d9cd487048b15041`。
- after_copy、after_replace、before_version、before_commit四个故障注入点全部回滚，完整schema、行数据和版本列表均与原备份一致。
- 升级后和完整备份恢复后，分别经真实应用路由核对13份轮胎原文、2份车型原文、97条历史检索结果及三个空通知列表。Parser引用归档1个验证通过，来源fetch调用0。
- 完整原始备份在新的恢复目录还原为015，schema、数据和1179个资产文件的哈希映射一致。文本回退屏障通过。原开发库在全过程结束后SHA仍与备份前一致。
- 最终恢复回执为 `.artifacts/upgrade-rehearsal-20261112/recovery-result-r3.json`，SHA256 `db558fb47658a7176f8dc763de7b3323726da21d0fa0c75b9bbc823a207fad45`，进程退出0。
- 额外从数据库引用的可信归档加载旧后端，校验105个源码文件，并在新的015恢复副本经TestClient实际启动。13份轮胎原文、2份车型原文及30条历史检索首页读取通过，版本列表保持015，来源fetch调用0。回执为 `.artifacts/upgrade-rehearsal-20261112/rollback-runtime-result.json`，SHA256 `32d2bc74c0a7a96a185fe24fc481ef89a9af3afd797c756163cbe06b9a87f78b`。
- 相关回归为 `.artifacts/umig-r1/result.json`，五模块154／154通过，runner退出0，失败／跳过／incomplete及非自检拒绝均为0，源码稳定、资源关闭，正常数据库启动false、真实Provider／接收端调用0、子进程0。SHA256 `81bede3fbc32e0ac5d5e86661f91da969c008c54658fbc7588d775987818764a`。该批使用合成私库，开发库副本运行另行记录。

前两份恢复回执按原状态保留。r1定位到归档记录machine=amd64、验证进程machine为空，Python及依赖均一致。工装按当前Python的sysconfig架构设置进程环境后通过原校验。r2的知识检索请求limit=100触发原协议上限30的422，工装已改为kind=tire及30条分页。实际部署切换、对应发布包完整回退、存在二进制对象的部署副本及生产PostgreSQL升级仍需验收。

### Gemini原生适配收尾

根据原规格实现Google原生generateContent及streamGenerateContent SSE，模型名使用裸标识。配置为 `TI_AI_ENABLED=1`、`TI_AI_PROVIDER=gemini`、`TI_GEMINI_MODEL` 和 `TI_GEMINI_API_KEY`。官方端点固定为generativelanguage.googleapis.com，Key通过x-goog-api-key请求头传递。用户选定的首个真实接入为OpenAI Responses。

共享证据、同意、预算、引用恢复、候选许可与请求账本已贯通。Gemini输入Token包含prompt及tool-use prompt，输出Token包含candidate及thought，缺失或非法usage沿用预算预留。响应和流式投影过滤thought正文与签名。车型最后外发检查可读取原生contents信封，普通／设备材料、同步／流式、许可拒绝及正文篡改反例均覆盖。

最终 `.artifacts/gem-r5/result.json` 为366／366、runner退出0，失败／跳过／incomplete均为0，SHA256 `e17aeda2e5dfda4fce9a50d3b0e73a259f9643fb7588c1f0204fa36a4c4e211b`。14模块覆盖新增58项、既有Responses／Chat／Anthropic、流式、候选授权、价格及遥测。774个源码输入稳定，资源关闭，非自检拒绝0，正常数据库启动false，真实Provider／接收端调用0，子进程0。

上述366项中的车型验证使用合成capsule边界。随后已恢复可信S2原件并补验实际二进制capsule，见下节。真实Google／Responses／Embeddings语义、浏览器及原生端集成仍需各自验收。失败回执 `gem-r1`、`gem-r3`、`gem-r4` 及 `gemdiag-r1` 保留，根因和最终命令见[续作记录](assurance/evidence/continuation-2026-11-12.md)。

### 本次交付环境复核

八份既有PostgreSQL、pgvector及开发库演练权威回执均在本机存在，SHA256与本文引用一致。HANDOFF历史尾文216248字节及SHA保持一致。

既有数据库回执沿用各批当时的源码绑定。本次Gemini修改共享AI文件，当前源码另由 `gem-r5` 绑定，通用PostgreSQL、pgvector和开发库演练沿用前述已执行范围。

SDK价格规划与候选合同类型检查均exit0。Web／SDK合并Node运行56／56通过，候选客户端脚本另执行59项wire／transport断言。交接时三端完整类型检查的依赖缺失失败记录保留，后续恢复结果如下。

### 依赖、构建及真实S2恢复

按锁文件核对44份安装归档，完整性哈希全部匹配。39个包实际缺少文件，补回9520个文件，1226个既有文件与归档逐字节一致，既有差异0。其余5个包的入口省略扩展名，归档内容完整。三端完整类型检查均exit0，安装包内Next指南已恢复并阅读。

通过既有npm构建入口完成Web／Desktop／Mobile前端生产构建，三者均exit0。Web使用独立Next构建目录，PWA白名单19项。Desktop／Mobile输出到本机忽略目录，保留大chunk告警。构建后恢复Next自动修改的next-env.d.ts，623个受管前端输入与构建前逐字节一致。本机回执为 `.artifacts/frontend-repair-20261112/` 内的归档、恢复、构建及输入核对记录。

从小米官方URL直连取得S2 PDF，3240150字节、SHA256 `0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f` 均与历史值一致，已恢复既有忽略路径。新增8个实际二进制capsule下的原生外发用例，并复跑2个同长度原文损坏用例及此前14模块。15模块376／376通过，runner退出0，失败／跳过／incomplete及非自检拒绝均为0，774个输入稳定、资源关闭，10个受管Parser子进程均exit0且live为0。正常数据库启动false，真实Provider／接收端调用0。

回执为 `.artifacts/gems2-r1/result.json`，SHA256 `ba2b7d128fee9233f32a6e8e246e31c2e93bdb82a825a3bebff4bf28b27568df`。该批证明S2原文／Parser／capsule与外发拒绝链，生产者仍使用合成或禁止调用的模型适配器。前端浏览器、原生端、真实模型语义及性能SLO继续待验。

### Responses冒烟验收修复

独立合成探针确认既有 `scripts/ai_real_provider_smoke.py` 可接受未知引用、自由文本事实及缺失usage。现已复用应用的 `grounded_answer` 和 `safe_usage`，补齐合成输入信封，要求每次调用至少产生一条已绑定事实及合法用量，流式分片与最终正文一致。错误输出使用固定码。脚本沿用环境配置入口，默认Provider为OpenAI Responses。

新模块26项与既有AI／流解析／Chat／Anthropic五模块共122／122通过，runner退出0，零失败／跳过／incomplete，775个输入稳定、资源关闭、非自检拒绝0，正常数据库启动false、真实Provider／接收端调用0、子进程0。回执为 `.artifacts/rsp-r3/result.json`，SHA256 `099eac3593628081ca4f72db79b214a461237d64837f40634192ecf6f2d352b1`。优化模式Python的四种独立反例／正例判定也通过。

本机Process／User／Machine三个作用域的TI_OPENAI_MODEL及TI_OPENAI_API_KEY均缺失。禁用状态CLI实际返回ai_disabled及exit2，配置失败发生在创建适配器之前。真实OpenAI Responses语义和API→Provider→Web验收继续待凭据及用途条件。该脚本仅验证Provider回执和现行grounding，API同意、持久化、幂等与账本由既有入口分别验证。

### Responses生产Web合成链收尾

使用独立生产构建、私有loopback API和新SQLite夹具，经实际Web入口验证。Provider输出采用合成Responses事件字节，经过生产 `parse_response_stream`。本轮真实OpenAI调用为0。

| 范围 | 当前结果 |
| --- | --- |
| 外发同意 | 准备历史证据时Provider调用0，未勾选同意时发送按钮禁用 |
| SSE草稿／终态 | held阶段可见待校验草稿，终态前完成账本0行。释放后得到completed及600 tokens，草稿移除，脚本文本安全显示 |
| 引用及恢复 | 核对f1展开并聚焦对应字段，进度重读、页面刷新及AI面板恢复均保持同一调用，Provider次数1 |
| 无效引用 | 第二次合成调用落账failed，错误为 `ai_grounding_validation_failed`，answer和usage为空，草稿作废，含分析报告按钮缺席。重读保持Provider次数2 |
| 证据与副作用 | 最后封存后的来源证据指纹保持。外网尝试、Parser子进程、真实Provider及正常数据库使用均为0 |
| 相关回归 | 五模块122／122，runner退出0，775个输入稳定、资源关闭，失败／跳过／incomplete及非自检拒绝均为0 |
| 关闭及生成文件 | API经shutdown退出0，私有存储清理。Web经SIGINT退出1，复核两个验证端口监听0、相关进程0。402个前端输入逐字节恢复 |

本机回归回执为 `.artifacts/rspweb-r1/result.json`，SHA256 `41c187b0d5c1674f7114aa2a1c04384dc97f1c613a8cfa421e7ad6df8c70d8b6`。浏览器、只读checkpoint核对、失败记录及关闭信息在 `.artifacts/responses-web-20261112/`，最终核对入口为 `verification.json`。该122项为本轮独立批次，沿用各历史批次的独立范围。

本轮修复 `scripts/ai_stream_acceptance.py` 的Windows元数据初始化，沿用既有runner的原生版本／架构读取，子进程审计保持启用。首次失败、沙箱内服务不可达及中断记录均保留，详见[续作记录](assurance/evidence/continuation-2026-11-12.md)。

该阶段观察到分析终态后顶部额度保持先前预留展示，手动刷新后读到实际600 tokens。后续终态自动刷新修复及8种模式验收见下节。

### Responses终态额度及8种模式验收

`AIAnalysisDialog` 原先仅在受理后读取额度。现复用 `tireApi.aiStatus`，在分析ID／state进入终态后自动读取，并以序号仲裁初次、受理、手动及终态读取。延迟返回的旧状态和过期错误按序号过滤，读取沿用AbortSignal生命周期。

- 实际页面在held调用完成后自动从预留更新至600 tokens。刻意延迟的26008 tokens旧响应随后返回，界面继续显示600。
- complete、held、grounding_failure、incomplete、truncated、terminal_mismatch、uncertainty_only和refusal均已验证。每种终态额度均匹配实际API账本，失败草稿清理、报告保存门及输出转义通过。
- 额外held场景中关闭窗口，受理额度读取signal已取消。原调用继续完成，重开面板经原标识恢复，累计Provider保持9次、来源保持1次。
- 只读checkpoint完整性ok，9条请求及完成账本、45条流事件。最终额度81586 tokens，包含已知用量和保守预留。外网尝试、Parser子进程、真实OpenAI及正常数据库使用均为0。
- 本轮Web测试50／50、三端类型检查及Web生产构建通过。402个前端输入在构建后逐字节恢复，API退出0，Web经SIGINT退出1，验证端口及相关进程均为0。浏览器控制台error／warn记录0。

本机核对入口为 `.artifacts/responses-terminal-20261112/verification.json`，SHA256 `56f12e06b351eacf5be979457ba6c86fe71b7d6ba9cc148283157b45168bff42`。此前122项后端回归的775个输入仍逐字节匹配。本轮结果与历史批次分别保留。实现计划见[终态额度计划](plans/2026-11-12-responses-terminal-status.md)，详细证据见[续作记录](assurance/evidence/continuation-2026-11-12.md)。

该阶段的额度读取失败注入已由本卡最新验收补齐。真实Responses语义、原生运行及完整V1 Gate继续开放。

## 下一步执行顺序

1. 核对HEAD、工作区、远端及本机证据是否可用，阅读本卡、原规格和拟修改模块的后续报告。依赖和S2已在本机恢复，新clone仍需安装依赖并取得可信原件。
2. 继续原文RAG第4–5步，正文用途授权、035、向量计划／执行、SDK和Web入口已实现。先实现正文向量召回、融合及权威／地区／时效重排，再冻结正文引用进入AI证据包，贯通同意、预算、流式、grounding与报告。真实Embeddings质量、真实Responses语义及完整RAG仍待验收。[正文向量计划](plans/2026-11-12-text-embeddings.md)
3. 沿用用户选定的OpenAI Responses主线。冒烟grounding／用量修复、8种流式模式、终态额度、额度读取故障及关闭恢复已通过合成验收。继续真实Provider接入准备，凭据和用途条件具备后完成API→Provider→引用恢复→Web真实语义链及预算／同意验证。
4. 继续实际部署目标的升级切换及对应发布包完整回退验收，覆盖二进制对象和部署向量扩展。已有开发库015→032副本演练及归档旧后端启动通过，生产PostgreSQL旧库升级继续开放。
5. 继续自主追溯真实专业测试材料的原始出版物、许可、试验场次和完整SKU身份，通过既有捕获／TestEvent／身份桥导入，随后进行外部真人Golden审核。此前四个候选及新增JRC／PERS研究线索、PERS真实捕获timeout均在续作记录中。匿名样本需先取得可核对的型号映射再建立SKU关联。
6. 扩充P0来源、SU7官方OE／精确SKU、监控长周期、全文RAG／reranker与专业性能解释。继续实现原规格剩余能力，并逐项形成可复核证据。
7. 收敛安静窗口全量回归、六类平台、生产身份／租户权限、无障碍、安全、性能、灾备与分发，逐项验收下列10个Gate。

## V1发布Gate

| 原规格Gate | 当前交接状态 |
| --- | --- |
| P0来源provenance 100% | 来源及地区覆盖待补齐 |
| 未授权本地回退0次 | 局部合同与验证已有，全平台核心流程待验 |
| Golden SKU错合并0次 | 代表性真实人工Golden待建立 |
| AI事实回答引用覆盖100% | 真实语义链及质量验收待完成 |
| 高危AuthZ／SSRF漏洞0 | 目标防护／回归已有，生产完整安全验收待完成 |
| P0／P1未处理故障0 | 开放风险及全量验收待收敛，通用PostgreSQL验收已闭环 |
| WCAG 2.2 AA核心流程通过 | 完整无障碍及读屏验收待完成 |
| 六类平台核心E2E通过 | 完整Native／macOS／iOS等矩阵待完成 |
| Adapter健康监控及回滚 | 全P0来源、长期生产验收待完成 |
| 数据库／Parser版本回退 | 开发库015→032副本及归档旧后端运行通过，实际部署切换与完整发布包回退待完成 |

13项SLO和15项决策的原始范围见[规格末两章](requirements/2026-09-26-tire-intelligence-original.md)。用户已经确认的Responses选型与EPREL现状应继续沿用。

## 关键代码与验收入口

| 范围 | 入口 |
| --- | --- |
| 本次产品与回归 | `apps/api/tire_api/source_page_url_monitoring.py`、`apps/api/tests/test_source_page_url_moves.py` |
| PostgreSQL验证 | `scripts/verify-postgres.ps1`、`scripts/postgres_acceptance.py`、`scripts/recent_history_acceptance.py`、`scripts/verify-pgvector.ps1`、`scripts/pgvector_acceptance.py`、`apps/api/tests/test_embeddings.py`及既有持久化辅助入口 |
| API与迁移 | `apps/api/tire_api/main.py`、`service.py`、`migrations.py`、`source_page_url_models.py` |
| 材料／Golden | `apps/api/tire_api/source_materials.py`、`test_events.py`、`test_event_golden*.py`、`professional_golden*.py` |
| AI／界面／共享协议 | `apps/api/tire_api/ai*.py`、`apps/web/components/`、`packages/api-client/src/`、`packages/domain-types/src/` |
| Gemini实现及回归 | `apps/api/tire_api/ai_gemini.py`、`apps/api/tests/test_ai_gemini_provider.py`、`docs/plans/2026-11-12-gemini-native-provider.md` |
| Responses冒烟及回归 | `scripts/ai_real_provider_smoke.py`、`apps/api/tests/test_ai_provider_smoke.py`、`docs/plans/2026-11-12-responses-smoke-grounding.md` |
| Responses生产Web夹具 | `scripts/ai_stream_acceptance.py`，私有API与独立Web使用显式隔离端口及本机忽略目录 |
| 正文检索与引用 | `apps/api/tire_api/source_text.py`、`source_text_models.py`、`apps/api/tests/test_source_text.py`及原文RAG计划，迁移033 |
| PDF正文与页码 | `apps/api/tire_api/document_pdf.py`、`document_text.py`、`document_text_models.py`、`apps/api/tests/test_document_pdf.py`、`test_document_text.py`、`apps/web/components/document-text-panel.tsx`及[PDF计划](plans/2026-11-12-pdf-page-text.md)，迁移034 |
| 受管回归 | `scripts/run_api_worker_regression.py`及对应阶段报告 |
| 正文向量及用途 | `apps/api/tire_api/text_embeddings.py`、`text_embedding_models.py`、`apps/api/tests/test_text_embeddings.py`及[正文向量计划](plans/2026-11-12-text-embeddings.md)，迁移035 |

表中省略目录的后端文件名均相对于 `apps/api/tire_api/`。

## 操作边界与交付检查

初次交接的工程提交 `95fefcd`、文档提交 `ac854dc` 及通用PostgreSQL修正提交 `7ae3967` 已通过GitHub官方SSH 443直连快进推送至原仓库 `main`。HTTPS Git直连先后遇到连接重置和连接失败，API HTTPS直连及SSH 443查询成功。本次业务验收与交接更新沿同一SSH通道交付，最终提交SHA与远端一致性见交付消息及下述接手核对。

`bce22a4`交付之前的基线为 `a6d2d07`，该序列覆盖pgvector直连下载、Gemini原生适配及回归、旧库副本演练结果与交接更新。后续恢复与Responses修复使用既有main继续实施，接手通过下列命令及即时远端查询核对最终HEAD。

- `4ea023f` 包含pgvector验证下载的显式直连参数。
- `d5fded1` 包含Gemini原生适配、共享协议／界面、58项新增回归及实施计划。
- `243d72b` 包含恢复可信S2后的实际二进制外发回归。
- `0e2eb3f` 包含Responses冒烟引用／用量校验修复、新增26项测试及实施记录。
- `70fa218` 汇总依赖与构建恢复、S2及Responses冒烟进度。本卡最近提交追加Responses Web夹具兼容修复、合成浏览器结果及接手顺序，可用 `git log -1 --format=%H -- docs/AGENT-HANDOFF-2026-11-12.md` 定位。
- `fcb2d2a` 包含Windows下Responses生产Web夹具兼容修复及实际合成浏览器验收记录。
- `b1c3acb` 包含Responses终态额度自动刷新、过期响应仲裁及8种流式模式验收记录。本次交接补充作为后续正式文档提交交付，最终SHA以即时远端核对为准。
- `675f968` 包含033正文索引、HTML／文本FTS及可恢复引用API，41项新增用例、旧库兼容及PostgreSQL原文恢复检查，完整RAG的后续步骤见本卡最新工程段。
- `54e749d` 包含HTML／文本正文检索的共享SDK、Web结果及引用恢复入口。
- `21d00a7` 包含本次034、PDF逐页抽取／索引／引用API、SDK与文档面板、依赖锁及受管检出换行约束。本卡及续作记录通过其后续文档提交交付，最终远端SHA由交付消息及即时查询核对。
- `5a29f39` 包含PDF知识检索卡、页码原件引用、共享正文组件接入和PostgreSQL恢复检查，103项API、51项PG、PDF浏览器35项及兼容5项的执行范围见本卡续作章节。

`bce22a4`交付的静态复核为 `.artifacts/handoff-final-20261112/validation.json`，当时774个回归输入逐字节匹配，14个本地链接有效，历史尾文SHA保持。后续恢复与Responses修复按各自新回执绑定，交付核对见 `.artifacts/responses-smoke-20261112/delivery-validation.json`。

033后端交付复核核对了204项回归与49项PostgreSQL报告的SHA256，778个受管输入逐字节匹配，10个改动Python文件AST通过，18个本地文档链接有效。HANDOFF历史尾文为216248字节及原SHA256，待推送新增行个人路径／高置信度凭据模式零命中，差异检查通过。该次本机复核入口为 `.artifacts/source-text-delivery-20261112/validation.json`，产品测试、构建与数据库运行结果沿用各自已执行批次。

PDF首批交付复核入口为 `.artifacts/pdf-handoff-20261112/delivery-validation.json`，最终787个受管输入及629个前端输入匹配，16个改动Python文件语法及24个本地文档链接通过，历史尾文216248字节和原SHA保持，增量隐私与差异检查通过。该报告保留历史失败与后续专项的分别结论。完整V1持续开放，PDF当前验证范围见本卡对应章节。

本轮知识检索续作的交付核对入口为 `.artifacts/pdf-search-20261112/delivery-validation.json`，产品验证汇总为同目录 `verification.json`，SHA256 `fce80c4caf96167806e31e342e4e2bb91e5e67904ca0e8198483329759633b4d`。本轮包含合成材料上的实际Web／API及隔离PostgreSQL，后续原文RAG和完整V1继续按原规格推进。

- 当前分支为既有 `main`。新分支／工作树须取得用户明确同意。工作区中的他人修改、历史红绿回执及证据按现有归属保留。
- Windows使用PowerShell 7，exec显式设置工作目录。网络使用直连，代理的启动／配置／连接须先取得用户明确同意。
- 验证使用显式数据库副本及对象目录。既有开发库通过备份工具只读保存，升级与恢复均在独立副本执行，原库SHA已核对。实际部署迁移应绑定具体部署目标、备份及对应程序版本。
- KIT C2 UUID `9539e5d2-d28e-439e-a6c0-c2d4aea2bfc0` 保持封存，继承状态为 `processing_unconfirmed`，PDF待取得。对该请求仅继承现状，重POST、重开私槽或换UUID重抓均受封存约束。
- R136 `stopped_unconfirmed` 表示停止后续采纳且网络结果未知。相关账本、终态仲裁和迁移兼容屏障仍是接手必须遵循的现行合同。
- 材料内指令作为来源数据处理，任务权限以用户请求和适用规则为准。保存、结构化使用、外发Provider及导出分别沿用现有用途许可。
- `.artifacts/`、`data/`、本机保密配置、依赖与构建产物沿用Git忽略规则，保留在本机。新clone的原始回执／截图／私库需另行取得或重新在新槽验证。
- 长解析器批选择安静窗口、独占重负载执行，并使用新短槽名。所有等待均需取得最终结果及资源关闭证据。原失败回执继续保留。

接手先执行只读核对。

```powershell
git status --short --branch
git log -3 --oneline
git rev-parse HEAD
git rev-parse origin/main
```

远端跟踪引用的时效以最近成功同步为准，最终推送结果及远端SHA见本次交付消息。此前工程提交及本次验收／交接更新构成交付序列。

## 可复制给接手Agent

> 继续按原需求规格推进胎迹完整V1，先读 `docs/AGENT-HANDOFF-2026-11-12.md` 并核对main、HEAD、dirty及本机回执。范围为12个核心模块、10项发布Gate，整体验收持续开放。
>
> 原文后端基线675f968、HTML／文本SDK与Web基线54e749d、PDF基础工程21d00a7已有记录。后续PDF知识检索及页码引用已接通，103项API、SDK16项、Web50项、三端类型与生产构建通过。真实PostgreSQL51项及152表备份恢复、PDF浏览器35项和HTML／PDF兼容5项通过，三个视口无横向溢出，服务已关闭。先按RAG计划第4–5步推进正文向量／融合／重排，再接入正文证据包与Responses链路。当前工程提交为5a29f39，最终文档提交由后续Git记录及即时远端核对。
>
> Responses终态额度及8种合成流式模式、50项Web测试、三端类型及生产构建已有回执。后续额度503、手动刷新、过期错误、关闭取消及迟到成功／错误已通过生产Web合成验收，4次提交对应4次调用及2400 tokens，服务已关闭。继续用户选定的OpenAI Responses真实语义链，本机OpenAI配置及EPREL Key缺失，继续独立工程。
>
> PostgreSQL47项、pgvector10项运行／12项业务、开发库015→032副本升级／恢复／回退及各批相关回归已有独立范围的回执。继续实际部署、全文RAG／reranker、真实Embeddings质量、合法专业材料、精确SKU／外部真人Golden、生产权限、平台及无障碍验收。
>
> Gemini适配由此前Agent依据原规格提前排期，当前默认Provider为openai_responses。材料由Agent自主选择，JRC匿名样本映射待核对，PERS原件CC BY 3.0已定位但直连TCP超时，新增保存成功原件及TestEvent均为0。旧KIT C2封存约束继续有效。保留失败记录、他人改动及现有证据／许可合同，完成声明绑定实际执行范围。
>
> 正文后端工程为985338f，正文向量后端与SDK已实现，迁移035记录独立用途声明，original-text-semantic@1绑定HTML／PDF原件引用与完整接收端，执行复用embedding-runs。六模块239项及后续正文／Embeddings60项、SDK5／9／7、Web50项与三端类型检查分别通过。真实PostgreSQL54项及153表备份恢复通过，恢复后正文缓存、引用、权限和写保护通过，集群已关闭。原始失败保留，模型为合成Provider。Web续作及后续执行顺序见下一段。启动Responses验收进程时显式核对TI_AI_PROVIDER，环境值可以覆盖代码默认值。

> 2026-11-13后续Web已接通正文选择、用途预览、管理员授权／撤销和共享索引执行／恢复。125项相关API、42项浏览器检查及末次构建6项复核、Web50项、SDK5项与三端类型分别通过。浏览器使用隔离SQLite和模拟向量存储，真实PG沿用独立54项。下一步从正文向量召回／融合／权威地区时效重排开始，再冻结正文引用进入Responses证据包。完整V1目标保持开放，首个真实生成接口沿用OpenAI Responses API。
