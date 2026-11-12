# 原文检索与引用式RAG实施计划

## 目标

按原规格的结构化查询、全文、向量、融合、重排、证据包及模型顺序，补齐正文检索与可恢复引用。已有结构化事实、原始凭证及用途许可继续按其现行合同处理。

本计划采用brainstorming与writing-plans流程。用户已授权持续实施，沿既有main开发。

## 实现顺序

1. 为正式HTML／文本快照建立独立、可重建的正文分块与FTS投影，提供显式历史检索和引用恢复API。每条引用绑定快照、原始SHA256、抽取器版本及抽取文本的Unicode字符区间。复用现有词元、正式查询头、原件字节校验及数据库初始化锁。
2. 在历史知识检索的结构化结果不足时接入正文路径，补齐共享类型、SDK与Web引用查看入口。精确SKU条件继续由结构化事实处理，网页摘录保留页面范围。
3. 通过现行受限Parser执行机制补齐PDF逐页抽取、页码定位及扫描件状态，接入有明确用途许可的文档。已有未解析凭证保留原记录。
4. 为正文分块接入向量计划、缓存、融合及权威／地区／时效重排，落实对正文的用途许可核验。
5. 将所选正文引用冻结进证据包，经过既有同意、预算、流式、grounding及报告链，在实际UI验收引用恢复与未知内容处理。

全文RAG的完成验收覆盖上述完整链路、真实来源及实际模型语义。首步API验收记录其独立范围。

## 首步文件与验证

- 新增 `apps/api/tire_api/source_text_models.py` 及 `source_text.py`，保存正文投影并注册历史搜索与引用恢复路由。
- 修改 `apps/api/tire_api/db.py`、`migrations.py` 及 `main.py`，在现行初始化事务内增加033派生索引及SQLite FTS5／PostgreSQL全文索引。
- 新增 `apps/api/tests/test_source_text.py`，覆盖生产API、HTML清理、Unicode区间、相邻块、正式查询头及304、原件／投影损坏、旧引用恢复、事务失败及重启。
- 在 `scripts/run_api_worker_regression.py` 登记新模块，执行该模块及知识检索、原文对象相关回归。

原件哈希和保留对象校验失败时保留原错误。分块及引用恢复使用相同抽取函数，检索命中重新绑定实际原件。既有结构化检索语义纳入兼容回归。

## 首步执行结果

已增加033派生索引迁移、HTML／文本正文抽取、1200字符分块及120字符重叠、SQLite FTS5／PostgreSQL GIN全文检索，以及按原件恢复引用的两个生产API入口。引用记录抽取文本的Unicode码点区间，包含快照、原始SHA256、抽取器版本和确定性的chunk ID。

五模块最终受管批 `.artifacts/srctxt-r5/result.json` 执行204／204通过，778个输入稳定，资源关闭、非自检拒绝0。该批包含41项新模块用例。较早的aria-hidden空属性反例曾出现AttributeError，修正后通过，原始红批在 `.artifacts/srctxt-r2/`。

真实PostgreSQL18.3隔离集群执行49项检查通过，包含正文GIN查询、引用恢复、重启及实际dump／restore，149张模型表指纹一致。报告SHA256为 `db4789c47a314582d2e0e38ad642e1eea45b17b6e5f9fedbf0e2dfff17860d59`。集群已停止，独立pg_ctl状态为exit3及no server running，端口55462无监听。

后续继续本计划第2–5步，接入共享SDK／Web、PDF逐页抽取、向量融合与重排、正文证据包及真实Responses语义。首步执行的是合成原文上的生产API与实际数据库验证。

## 第二步SDK与Web接入

共享协议增加正文请求、摘录、引用和分页响应类型，SDK通过既有HTTP传输消费两个history API并传递AbortSignal。Web沿用历史知识检索入口，关键词及来源范围的结构化结果为空时自动补充正文，已有结构化命中时提供正文检索动作。精确SKU、车型、测试和召回条件由原结构化路径处理，正文保留页面范围。

正文卡显示服务端摘录、来源、快照、SHA256、抽取版本与Unicode码点区间，用户可按原引用重新读取原件。页面显示使用服务端恢复的文本。编辑条件、取消、关闭及重新检索均需终止旧请求采纳，分页使用服务端offset与limit。

验证覆盖SDK请求与引用序列化、分页、错误和取消传播，三端类型、已有Web测试及独立生产构建。隔离浏览器验收覆盖中文与emoji、自动正文路径、精确筛选、分页、旧快照引用、条件切换／取消／关闭后的迟到响应及原文损坏。实际源码、受管API回归和浏览器验证分别记录结果。

## 第二步执行结果

共享类型、两个SDK方法及Web历史检索正文入口已实现。SDK9／9、Web50／50、三端类型及独立生产构建通过。正文／知识两模块受管回归67／67，780个输入稳定、资源关闭、非自检拒绝0。SDK测试入口加入现行聚合测试，经审查同步受管子进程的package.json精确哈希。

生产浏览器在隔离合成原文上完成24项业务检查，包含旧引用恢复、损坏原件、分页及编辑／取消／关闭后的迟到响应。1440、390和320像素视口通过横向溢出检查，窄屏引用恢复通过。400个前端输入仍与构建前字节一致。回执为 `.artifacts/source-text-web-20261112/verification.json`，SHA256 `67baa05c803872de3ea3966a027ddc5eb2c321e79d999948a586588a224f50ae`。

API退出0，Web经SIGINT退出1，验证页面已关闭，8003及18002均无监听。来源、真实Provider、外网和正常数据库使用均为0。当前完成到第2步，后续继续PDF、正文向量与融合／重排、正文证据包及真实Responses语义。

## PDF首批交付停点

已补充受限PDF逐页抽取、034正文索引、逐页／搜索／引用恢复四API、共享SDK及文档面板。新PDF两模块36项在广批通过。广批332项中历史清单断言出现1项失败，修正后完整Parser包模块25／25通过。SDK共16项、Web50项、三端类型及独立生产构建通过，最终报告与源码绑定见[PDF计划](2026-11-12-pdf-page-text.md)。

当前接手先完成PDF知识检索结果及引用卡，再执行034真实PostgreSQL与PDF生产浏览器验收。PDF结果采用无结构化筛选的查询范围。随后继续本计划第4–5步，完成正文向量、融合／重排、证据包和Responses真实语义。[Agent交接卡](../AGENT-HANDOFF-2026-11-12.md)

## PDF知识检索及专项验收完成记录

PDF知识检索与原件引用已接通，生产浏览器PDF35项、HTML／PDF兼容5项及三个视口通过。103项API、SDK16项、Web50项、三端类型与构建通过，真实PostgreSQL51项及152张模型表实际备份恢复通过。资源已关闭，合成材料的工程与验收记录见[PDF计划](2026-11-12-pdf-page-text.md)及[交接卡](../AGENT-HANDOFF-2026-11-12.md)。

后续进入本计划第4–5步，实施正文向量计划、缓存、融合／重排、正文证据包和Responses链路，并继续真实模型及材料质量验收。

## 正文向量接入预查

以下保留正文向量开工前的合同核对。035用途授权、独立文本合同、共享执行链及SDK的后续实现见[正文分块向量计划](2026-11-12-text-embeddings.md)。正文向量的Web入口、检索融合／重排和证据包继续推进。

| 已核对的现状 | 接手实现需覆盖的行为 |
| --- | --- |
| `embedding_text.py` 的 `tire-structured-semantic@1` 从KnowledgeDocument生成语义文本，过滤body、URL及身份等字段 | 明确HTML／PDF正文独立文本合同及原件引用绑定，保留既有结构化缓存读取 |
| 缓存ID绑定Provider、model、dimensions、text_contract、privacy_class与text_hash，`embedding_service.py` 的save_vectors仍写入固定结构化合同 | 贯通正文计划、缓存生成与写入、模型空间及当前投影核验，覆盖旧缓存及损坏绑定 |
| prepare_plan、validate_plan与 `dense.py` 的current_materials从结构化文档读取，外发前check_embedding_dispatch仅接收index／hybrid及严格payload | 明确正文请求合同，通过现行持久计划、同意、预算、幂等、只追加账本和外发前新会话复核完成正常入口 |
| `material_source_policy.py` 的canonical_policy要求provider_use与export均为false，共享类型 `source-materials.ts` 也使用false字面量 | 结合实际许可依据设计明确的正文用途授权，贯通后端、共享类型、SDK及界面，保全旧false权限及冻结凭证 |
| 普通PDF的DocumentMetadata.rights_basis记录原件保存依据，candidate_ai_contract绑定车辆候选dependency及Provider | 继续核对通用HTML／PDF的用途机制，按具体材料及接收方绑定允许用途，旧材料权限保全纳入兼容验证 |
| HTML checked_snapshot及PDF checked_document／checked_projection已核对原件与抽取投影 | 复用原件哈希、抽取版本、Unicode码点区间及PDF页码／元信息指纹，覆盖引用过期、损坏及重建 |

沿用现行每块6000个UTF-8字节、单批32块／100KB的Embeddings输入边界，并在具体设计中核对正文分块的映射。索引与查询分别使用显式外发确认。随后实现融合与权威／地区／时效重排，将所选原件引用冻结进证据包，贯通Responses、流式、grounding及报告。

首个真实生成接口继续采用用户选定的OpenAI Responses API。接手运行时核对进程中的TI_AI_PROVIDER，代码默认值为openai_responses。真实Embeddings／Responses质量、专业材料质量及完整V1继续按各自实际结果验收。

## 第四及第五步工程收尾

正文向量、FTS／RRF融合、来源类别／地区／时间排序、原文引用证据包、独立AI及导出用途、单次同意、预算、Responses同步／流式grounding与报告已贯通。真实检索、排序及模型质量继续待验。语义重排模型属于此前Agent追加的实施选项。第五步工程取得269项API、58项PG及153表恢复、30项生产浏览器、SDK9项、Web50项、三端类型和生产构建通过，输入为合成原文与合成Provider。

现阶段可按[正文AI计划](2026-11-13-original-text-ai.md)及[当前交接卡](../AGENT-HANDOFF-2026-11-13.md)复验工程链路，随后继续代表性真实材料、真实Responses／Embeddings语义及完整V1验收。
