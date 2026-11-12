# 正文证据包与Responses链路实施计划

## 目标与架构

按原文RAG总计划第5步，将选中的HTML／PDF正文引用接入现有证据准备、用途授权、单次同意、预算、同步／流式grounding和报告链路。生成主线沿用OpenAI Responses API，实际模型质量继续以真实调用验收。

本轮使用brainstorming与writing-plans流程，沿既有main实施。技术栈沿用FastAPI、Pydantic、SQLAlchemy、现行受限PDF Parser、共享TypeScript协议及React界面。

现有 `text_embedding_authorizations` 通过scope_hash绑定用途、具体引用和完整接收端，修订记录受SQLite／PostgreSQL原生只追加保护。保留表名及035历史，新增用途 `original_text_ai@1` 与 `original_text_report_export@1`，分别形成独立scope和管理员声明。向量用途仍沿用原合同，端点在撤销时核对用途命名空间。新增用途与向量权限各自按具体范围读取。

正文证据采用已有SourceSelection／DocumentSelection。准备只恢复选中的原件范围，将正文作为来源摘录冻结进现行facts，并保留原始哈希、抽取版本、Unicode区间和PDF页码。正文来源的陈述、SKU适用性及发布时间按现有材料元信息表达，报告及模型请求保留其范围说明。

本地证据准备和冻结报告使用现行读取权限。生成与导出在各自实际入口读取当前用途修订。生成准备、预算预留、最终外发以及结果采纳核对原件和许可，调用后拒绝保留实际用量。同步与流式共用同一校验，历史完成记录和冻结报告仍按其原内容读取。

## 实施任务

1. 在 `apps/api/tire_api/ai_original_text.py` 实现具体用途范围、原件绑定、纯合同校验、原件恢复、授权预览及只追加修订。复用正文引用模型、原件恢复和现行授权表／指纹。为向量撤销入口补用途范围核对。
2. 扩展 `ai_evidence.py` 的历史引用类型与PackBuilder，支持混合选择最多6份结构化／正文证据。通过现行44KB包及48KB请求边界拒绝超量，保留旧请求序列化和所有历史分支。
3. 接入 `ai_analysis.py`、`ai_execution.py`、`ai_streaming.py` 和 `ai_gateway.py`。为正文合同加入固定范围提示和安全错误代码，外发前新会话核对持久请求、包、实际请求体和原件用途。完成采纳前再次核对用途并保留实际usage。
4. 在 `reports.py` 与 `report_rendering.py` 核对并保留原文事实、引用定位和来源范围。生成、重新读取导出和并发渲染后发布均执行当前导出用途校验，保持已保存报告的历史读取合同。
5. 增补共享类型、SDK、正文用途面板与知识检索到AI的选择入口。AI包内提供原件引用恢复，沿用现行操作和账户生命周期仲裁。设备离线引用入口继续使用现行结构化引用类型。
6. 在 `apps/api/tests/test_ai_original_text.py` 增补HTML／PDF、混合包、缺失／撤销／过期／跨用途、端点变化、原件损坏、最终外发和调用期间变化、grounding／流式／历史／报告导出反例，并登记受管runner。执行相关旧合同回归、三端类型、SDK及生产Web验收。

## 验证与证据

先运行新模块取得当前不支持正文引用的失败，再实现并验证对应链路。API使用受管runner新槽，执行期间固定受管输入。真实PostgreSQL核对用途修订、原生写保护、正文包／报告和备份恢复。浏览器通过生产构建检查正文选择、同意、引用恢复、错误／迟到响应及320、390、1440像素布局。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/otai-r1 --targets apps/api/tests/test_ai_original_text.py apps/api/tests/test_ai.py apps/api/tests/test_text_embeddings.py apps/api/tests/test_reports.py
```

本轮工程验收采用合成材料及Provider。真实Responses语义、专业材料与完整V1发布Gate继续按原规格推进，执行结果补入当前交接卡和续作记录。

## 执行结果

六项实施任务已贯通正常API、SDK及生产Web入口。受管十模块最终269／269，796个输入稳定、资源关闭、非自检拒绝0。真实PG执行58项检查，153表备份恢复指纹一致，包含恢复后正文报告及当前导出许可读取。三端类型、SDK9项、Web50项和末次生产构建通过。

生产浏览器30项检查通过，覆盖HTML＋PDF选择、三用途窗口、许可修订、单次外发同意、Responses SSE、grounding、原件恢复、600 tokens、报告HTML下载校验、撤销导出后拒绝已有文件复用、冻结报告读取、关闭后迟到响应及320／390／1440像素报告布局。浏览器仅发生1次合成模型调用，真实Provider及外网尝试0。API、Web、四个本轮隔离PG集群及端口关闭已独立核对。

原始失败、中断和测试驱动修正保留在本机 `.artifacts/otai-r1` 至 `otai-r6` 及 `.artifacts/original-text-ai-20261113/`。交付范围、具体回执和继续顺序见[当前交接卡](../AGENT-HANDOFF-2026-11-13.md)。真实模型语义、语义reranker、代表性专业材料和完整V1 Gate继续开放。

末次交付统一PG验收脚本换行为LF并固定本轮源码Git属性，按最终字节执行r6与PG r3全批复验，结果分别为269／269和58项通过。
