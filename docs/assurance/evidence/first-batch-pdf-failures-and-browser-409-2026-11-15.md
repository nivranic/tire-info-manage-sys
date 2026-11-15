# 前阶段首批PDF失败与浏览器409根因确认

2026-11-15，基线b6b1923。本文件确认前阶段（[AI成绩选择验收](ai-test-measurement-selection-2026-11-15.md)）首批6项API失败与浏览器首次409的根因。此前两者状态为"根因待确认，已有复跑通过证据"。本文件基于保留在忽略目录中的原始回执、失败用例的测试SQLite及解析器审计记录，给出直接证据。

## 结论

六项失败与浏览器409共享同一根因：**受管回归首批与多个重型工作负载并行，机器负载使隔离子进程解析器的固定8.0秒墙钟预算被超出**。解析器预算（`parser_runtime.TIMEOUT_SECONDS=8.0`）覆盖信号量排队、bundle拷贝、子进程启动与输出校验全程；超时以`parser_timeout`失败并被上层按合同转换为503或409。产品代码在两次运行间逐字节一致，边界行为（超时即失败、不静默重试）符合冻结合同；失败为环境性，非产品缺陷。

## 直接证据

### 失败用例数据库中的parser_timeout回执

首批失败用例的测试SQLite保留在`ai-measurement-selection-20261115-regression/private/pytest-tmp/`。四个`changes_after_dispatch`用例库中均有`document_text_extraction_failed`审计，错误码`parser_timeout`：

| 用例目录 | error_code | elapsed_ms | exit_code | stdout_bytes |
| --- | --- | --- | --- | --- |
| test_test_pdf_changes_after_di0 | parser_timeout | 8,860 | 125 | 0 |
| test_test_pdf_changes_after_di1 | parser_timeout | 8,844 | 125 | 0 |
| test_test_pdf_changes_after_di2 | parser_timeout | 9,328 | 125 | 0 |
| test_test_pdf_changes_after_di3 | parser_timeout | 8,703 | 0 | 899 |

预算为`wall_seconds: 8.0`。exit 125为期限终止；di3子进程在期限后完成（exit 0）但协作检查点仍按期限判负。

### 同窗口成功解析的耗时对比

各批`document_text_indexes.parser_receipt.elapsed_ms`分布：

| 批次 | n | min | 中位 | max |
| --- | --- | --- | --- | --- |
| 首批（失败窗口，全部tmp库） | 12 | 3,094 | 4,445 | 7,875 |
| 诊断批（11用例，通过） | 11 | 2,812 | 3,062 | 3,500 |
| 最终批（239用例，通过） | 16 | 2,688 | 3,273 | 3,703 |

失败窗口内成功运行的中位耗时约为通过窗口的1.4倍、最大值7,875ms已贴近8,000ms预算；超预算即失败。浏览器工作区更早的单次成功索引（03:08本地）也达6,828ms，表明该机整晚负载偏高。

### 时间线重叠（本地时间）

| 时间 | 事件 | 来源 |
| --- | --- | --- |
| 03:35–03:48 | 首批受管回归5模块239用例（单进程pytest.main顺序执行） | regression/bootstrap.json、result.json |
| 03:37–03:41 | 真实材料验收accept.py（隔离SQLite+TestClient） | -real/accept.py、accept.log |
| 03:41:56–03:43:14+ | PG18.3实例+TLS API验证pgverify | -pg/pg-run-pointer.json、pgverify目录 |
| 03:45:27–约03:51 | 生产浏览器首跑（Next.js+uvicorn API+Chrome） | -real/web/run-86db1bee目录时间 |

诊断批（03:48–03:57）与最终批（03:57–04:08）不在上述重叠窗口内，全部通过，源码输入稳定一致。

## 六项失败的逐项机制

失败断言位置以运行时源码快照（source-before.json，SHA与b6b1923一致）定位：

| 案例 | 用例参数 | 失败点 | 机制 |
| --- | --- | --- | --- |
| case-52 | stream_freezes revoke=True | test_ai_original_text.py:207（usage断言） | dispatch前PDF恢复走`excerpt_for`→`original_excerpt`→`parse_isolated`超时→`ai_original_text_original_invalid`（ai_request_finished审计直接记录该错误码，state=failed），usage未达600 |
| case-53..56 | changes ×4参数 | test_document_text.py:44（`/text-index`断言） | `extract_original`→`parse_isolated`直接`parser_timeout`→503，审计含上表回执 |
| case-58 | frozen damage='reference' | test_ai_original_text.py:71（prepare断言） | index与建场均成功（库中有indexed与revision审计），prepare的`require_originals`→`excerpt_for`重提取超时→409；参数无关的准备阶段瞬时失败 |

## 浏览器首次409

首跑report.json记录`measurement_numbers:[21,22]`的prepare返回409（此前[1,10]等组成功）。该端点对PDF原件重校验走同一条`require_originals`→`original_excerpt`路径；`original_excerpt`将`ParserRunError`直接转为409且不写`document_text_extraction_failed`审计（浏览器工作区SQLite中无失败审计，与此一致）。409响应体未被首跑脚本记录，精确子码（`ai_original_text_original_invalid`或`ai_original_text_binding_failed`）未留存；两码同属原件重校验失败族，机制一致。复跑（03:51后，回归已结束）同请求200，11项全通过。

## 观察与后续

- 根因状态从"待确认"改为"已确认（环境性，机制如上）"。产品8秒解析墙钟预算、超时即失败、不静默重试的行为保持不变；无需产品代码修改。
- 可观测性缺口（记录，不擅自改动）：prepare/dispatch路径的解析失败经`original_excerpt`/`excerpt_for`转换为409时不留`document_text_extraction_failed`审计，仅analyze路径经ai_request_finished间接可见。若需生产可诊断性，应按产品决策补审计。
- 运行纪律（沿用现有做法）：受管回归与真实材料验收、PG/TLS验证、浏览器生产跑不应并行执行；后续批次已按串行执行并全部通过。
- 本文件仅基于历史回执与保留数据库的离线核对；未重新执行回归或浏览器跑，未改动产品源码。
