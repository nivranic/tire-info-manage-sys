# PDF来源类别与地区声明计划

## 目标与依据

原规格要求独立性能测试优先采用原始机构和专业媒体的证据，并在证据包前进行来源权威、版本、地区和时效排序。HTML正文已有来源目录类别及地区，PDF正文的来源类别和地区目前固定为未知。

材料捕获已具有可信启动配置、冻结策略、原件及请求凭证。本轮复用该链路，让管理员配置有依据的来源类别和地区，并在查询时恢复声明及其出处。人工测试转录的来源角色需要进一步关联到可核对的出版物依据，继续在交接中跟踪。

## 设计

材料策略增加可选 `source_attribution`，包含受限的 `source_class`、可空的 `region` 和有界 `basis`。类别使用现有正文排序词表，依据为操作者配置声明。此对象随策略指纹冻结到每次成功捕获。

采用既有材料策略承载声明。独立登记表需要另建生命周期，按出版者名称推断则缺少当前可验证绑定。本方案复用已校验的请求与策略，将分类及地区声明明确显示给使用者。

序列化缺省和null的可选声明时省略该字段，以现有冻结策略和捕获回执验证旧指纹。新声明参与策略指纹、预览和捕获的并发约束。

PDF正文从对应成功捕获恢复声明，来源类别进入现有层级排序，地区进入既有偏好排序及独立region硬筛选。地区未知的PDF在明确region筛选时排除。排序中的具体SKU适用性依据结构化证据。查询响应携带声明依据、原材料请求ID和策略指纹。

捕获与正文结果页面展示配置声明。向量用途、AI和导出仍依据各自权限及显式同意处理。历史完成回执按保存内容读取。

## 文件与步骤

1. 更新 `apps/api/tests/test_source_materials.py`，覆盖旧策略指纹、缺省声明、有效类别与有界输入、策略预览及请求字段约束。
2. 更新 `apps/api/tests/test_original_text_retrieval.py`，经正常捕获、索引、向量授权及混合检索验证来源类别、地区、出处、策略变更与历史恢复，并记录修改前失败。
3. 更新 `apps/api/tire_api/material_source_policy.py` 和 `original_text_retrieval.py`，复用既有校验与排序链。
4. 更新 `packages/domain-types/src/source-materials.ts`、`index.ts` 和两个Web组件，处理声明展示及响应校验。
5. 执行受管API回归、三端类型、Web测试、实际组件及隔离PG验证。更新验收记录和交接卡，提交并推送。

## 复验与验收

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/pdf-source-attribution-tests --targets apps/api/tests/test_source_materials.py apps/api/tests/test_original_text_retrieval.py apps/api/tests/test_document_text.py apps/api/tests/test_text_embeddings.py apps/api/tests/test_retrieval_evaluation.py
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
npm run test --workspace @tire/web
```

旧策略指纹须与当前基线一致。声明及其依据须绑定成功捕获，配置目录的后续修改通过新捕获形成记录。回归覆盖类别先后、地区偏好、地区硬筛选、未知类别与地区、精确实体约束、坏凭证拒绝、授权准入和历史恢复。当前声明可追溯到请求及策略指纹。

执行使用新隔离资源和回执槽。真实模型语义、代表性材料、人工测试来源角色、精确SKU、真人Golden和完整发布Gate继续按原规格验收。
