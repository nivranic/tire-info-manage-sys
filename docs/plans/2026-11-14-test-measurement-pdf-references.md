# 测试成绩 PDF 原件引用实施计划

目标是把人工成绩中的短摘录绑定到保存的PDF、文档元信息、页码、抽取版本与Unicode码点区间，并贯通正常录入、比较、AI、报告和导出。基线为 `8f5a604`，按原规格的测评数据库与字段证据追溯要求执行。

架构采用现有 `DocumentTextReference`、隔离PDF抽取、正文用途授权和引用恢复组件。为避免 `test_events → document_text → knowledge_index → test_events` 循环，将引用DTO移入无业务依赖的合同模块，原模块继续导出原名称。数据保存在现有JSON修订中，既有省略字段的指纹保持兼容。沿既有main实施，创建新分支与工作树按用户授权边界执行。

## 合同与保存

1. 新建 `apps/api/tire_api/document_text_contract.py`，承载现有 `DocumentTextReference`，`document_text.py`继续导入导出该类型。
2. `test_events.py`的Measurement增加可选 `pdf_reference`。空值序列化时省略，继续保留原始小数、自由文本定位、参测身份及旧记录。单场引用数量采用现有正文批次32段上限，短摘录总量继续按8000字符检查。
3. 新建 `test_measurement_originals.py`复用现有原件抽取及引用恢复，按文档缓存单批解析，核对短摘录为所选原件区间内的精确子串。创建和修订在取得写锁前完成解析，取得锁后重新核对原件绑定及修订代次，再追加JSON修订。
4. 现有 `test_test_events.py`增加正常保存、旧指纹、错误摘要／文档／页码／码点／引文、原件损坏、修订竞争和历史保留的回归。

## AI 与报告

1. `ai_original_text.py`增加 `test-pdf-original@1`冻结标记及纯合同验证，从所选测试成绩提取PDF引用与原始短摘录，复用既有正文用途scope、接收端与撤回检查。
2. `ai_evidence.py`准备证据时核对所选测试原件并冻结标记。`ai_analysis.py`在已受理合同中保存该标记。实际派发、流式草稿／终态采纳继续通过现有 `require_originals` 与 `require_dispatch`统一核验，覆盖标记删除的反例。
3. `reports.py`在保存和导出时核对原件与具体用途，在现有报告schema中冻结独立 `test_pdf_policy` 标记。渲染保留逐成绩原件引用，既有schema继续读取。
4. 在现有测试AI、流式、报告文件中增加许可拒绝、授权后同步／流式、派发前撤回、原件篡改、报告三格式和旧报告兼容回归。

## 正常 Web 与 SDK

1. 共享 `TestMeasurement`增加可选PDF引用，SDK沿既有保存、读取与比较接口传递完整合同。
2. `source-text-search.tsx`支持用途说明参数，编辑器复用现有PDF正文检索选择引用，明确短摘录与所选区间的关系。
3. `test-event-editor.tsx`提供引用选择与移除，`test-events.tsx`在全部成绩与同场比较中提供原件核对。AI及报告组件展示对应的引用与用途核对入口，复用现有 `OriginalTextCitation` 和正文用途对话框。
4. 正常生产浏览器验证录入、错误引文拒绝、追加修订、历史重开、比较、原件恢复、授权与三格式导出，核对1440／390／320布局和账户切换。

## 验证与交付

按实际修改范围从以下入口选择正式受管回归，使用全新Git忽略槽。执行期间冻结所绑定源码、测试和共享合同。

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/<fresh-slot> --targets apps/api/tests/test_test_events.py apps/api/tests/test_test_ai_contract.py apps/api/tests/test_test_ai_grounding_review.py apps/api/tests/test_test_ai_stream_terminal.py apps/api/tests/test_test_ai_reports.py apps/api/tests/test_document_text.py
npm run typecheck
npm run test --workspace @tire/web
npm run build
```

另核对受影响的SKU桥、Golden、偏好解读和既有原文AI合同。API变动后重建、审查@4合同，完成非拥有者PG／TLS正常HTTP专项。真实研究PDF用于原件引用核验，成绩链路采用可核对原值的材料或明确合成夹具。真人审核、精确SKU和真实Provider按实际证据继续验收。

完成后更新阶段证据和交接，核对临时进程、端口、秘密及原始失败，审查正式提交并发布，最后重读远端SHA。完整V1目标继续执行。
