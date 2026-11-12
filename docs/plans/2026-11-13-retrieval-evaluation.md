# 检索质量评估实施计划

## 目标与依据

原规格要求结构化查询、FTS、向量、融合及权威／版本／地区／时效排序依次进入证据包。现有入口已有功能回归与PG验收，代表性材料上的检索质量继续待验。本次补可重复运行的离线质量评估入口，使用独立标注和正常API返回的冻结结果。

## 设计

复用KnowledgeSearch与现有引用对象，以引用的完整kind和reference识别候选版本。标注包含相关等级、空结果预期和可选先后顺序。实际记录绑定同一查询、入口与集合，初始offset为0，查询limit覆盖全部评估截点。

报告按case保留Precision@k、Recall@k、MRR@k、nDCG@k、已标注覆盖、未标注候选、排序及空结果检查。截点分母保持k，缺失结果按空位处理。未知候选按相关等级0计算并单独计数。重复引用、缺失case、查询错配及非完成响应按输入错误处理。真实／合成材料及标注来源在输入中明确声明。

评估命令只读取给定文件并写入新报告，计算过程中使用本地数据。数据集代表性、人工标注资格与真实模型质量分别依据实际验收结果判断。

## 实施步骤

1. 新增 `apps/api/tire_api/retrieval_evaluation.py`，实现有界标注、捕获记录校验及四项指标，复用现有严格JSON读取与稳定指纹。
2. 新增 `scripts/evaluate_knowledge_retrieval.py`，提供corpus、actuals及output参数，绑定输入字节哈希，使用明确退出码。
3. 新增 `apps/api/tests/test_retrieval_evaluation.py`，覆盖可手算指标、空结果、排序、重复引用、缺失记录、查询错配、无效输入及正常知识检索入口，注册现有受管测试清单。
4. 在新私库中通过正常API录入原报道和论文事件，先按来源独立确定期望，再执行查询并冻结结果。运行评估命令，记录小样本覆盖及身份缺口。
5. 执行相关受管回归与CLI检查，核对资源、源码绑定、文档和Git差异，更新交接并发布。

## 验证入口

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/retrieval-evaluation-tests --targets apps/api/tests/test_retrieval_evaluation.py apps/api/tests/test_knowledge.py apps/api/tests/test_original_text_retrieval.py
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/evaluate_knowledge_retrieval.py --help
```

真实Embeddings及Responses语义、代表性外部真人标注和完整V1继续按原规格推进。

## 使用方法

先准备corpus与actuals两个JSON文件。corpus声明 `schema_version=retrieval-evaluation-corpus@1`、标注来源 `label_provenance`、递增且唯一的 `cutoffs` 及 `cases`。每个case提供 `case_id`、现有KnowledgeSearch格式的 `query`、`material`、`judgments`、`expect_empty`，并可声明 `retrieval_mode`、`collection` 和 `ordering`。

judgments使用API原样返回的kind及完整reference，另加0–3的relevance等级。等级0表示不相关。正例至少包含一个正等级标注，空结果案例使用 `expect_empty=true`。ordering中的before与after各为kind和reference，必须引用已经标注的对象。标注依据来源确定，并在执行待评估查询前冻结。

actuals声明 `schema_version=retrieval-evaluation-actuals@1` 和 `records`。每条记录包含匹配的 `case_id`、实际 `query`、`retrieval_mode` 及正常API的 `result`。普通历史检索直接保存响应，混合检索保存completed回执中的result。original_text集合采用 `collection=original_text`，兼容历史正文集合缺少分页元信息但外层保留offset／limit的记录。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/evaluate_knowledge_retrieval.py --corpus .artifacts/retrieval-review/corpus.json --actuals .artifacts/retrieval-review/actuals.json --output .artifacts/retrieval-review/report.json
```

报告写入新文件，并记录两个输入的原始字节数、SHA256和规范化指纹。退出0表示评估完成且声明的排序／空结果约束通过，退出2表示约束失败且报告已写入，退出1表示输入或文件操作失败。指标值与约束结果分别读取。

Precision@k采用固定分母k。一个相关结果被正确返回时，Precision@1为1、Precision@3为1/3，缺少的展示位置按空位处理。Recall仅针对已标注正例，MRR采用截点内首个正例，nDCG采用等级增益 `2^relevance-1` 与对数位置折扣。空结果案例另计准确率，宏平均使用正例案例。未标注返回项按0计分并在报告中列明数量。

## 执行结果

评估器、CLI、相关回归和正常API样本已实现。最终四模块118／118，799个输入稳定、资源关闭、非自检拒绝0。真实来源的两份转录形成13个独立标注查询，9个相关案例、4个空结果案例。宏平均nDCG@1为0.904762，宽查询中原报道与转述的排序差距按实际结果保留，标注由Agent给出，外部真人复核继续待完成。[实现与实测](../assurance/evidence/retrieval-evaluation-2026-11-13.md)
