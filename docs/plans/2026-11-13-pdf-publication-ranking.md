# PDF正文出版日期与时效排序计划

## 目标与依据

原规格第667行起要求在证据包前完成权威、版本、地区及时间排序。当前PDF正文候选统一使用 `publication_unknown`，但成功材料捕获请求的冻结策略已包含可选ISO出版日期 `published_at`。`checked_projection` 已校验原件、请求、策略指纹与捕获回执，此日期可作为有明确出处的配置声明。

另一个已观察到的问题是，两份人工测试转录在同尺寸宽查询中按录入时间排序，原报道与论文转述尚缺已登记的来源角色。该问题继续记录在检索质量报告，来源角色需要结合可核对的分类依据处理。

## 方案

复用成功捕获的冻结策略日期。完整来源元数据治理需要贯穿文档版本和许可流程，单靠PDF文本推断日期则缺少现有可验证绑定。本轮选择冻结策略已有日期，保持现有原件与正文引用指纹。

正文候选校验成功后，读取对应捕获请求并复核请求指纹。存在出版日期时，时间依据使用 `policy_publication_date`，按UTC日开始时刻形成排序值，并返回ISO日期、原材料请求ID与策略指纹。日期精度保持到日。当前策略目录的变化通过新捕获产生后续记录。

HTML继续使用原件观察时间。PDF缺少成功捕获的策略日期时，时间依据为 `publication_unknown`。排序沿用来源类别、地区偏好、RRF、时间与稳定ID的顺序。历史完成回执继续返回保存结果。

Web展示策略声明日期和可核对的请求、策略指纹。共享类型增加可选出版声明及新的时间依据值，历史结果继续通过可选字段读取。

## 文件与步骤

1. 在 `apps/api/tests/test_original_text_retrieval.py` 补正常捕获、正文索引、独立向量授权与混合查询的回归。先记录缺少日期的失败，再覆盖同分排序、未知日期、策略目录变更、旧回执及原文恢复。
2. 修改 `apps/api/tire_api/original_text_retrieval.py`，从已校验捕获读取日期与指纹，接入既有排序并输出声明出处。
3. 修改 `packages/domain-types/src/index.ts` 与 `apps/web/components/source-text-search.tsx`，展示声明日期及凭证信息。
4. 执行正文检索、正文索引、材料捕获与检索评估相关回归，核对三端类型、Web测试及受影响组件的页面表现，更新报告和交接卡。

## 验收与复验

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/pdf-publication-tests --targets apps/api/tests/test_original_text_retrieval.py apps/api/tests/test_document_text.py apps/api/tests/test_source_materials.py apps/api/tests/test_retrieval_evaluation.py
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
npm run test --workspace @tire/web
```

日期必须来自当前原件对应的冻结成功捕获，目录中的更新日期不能回写历史捕获。坏凭证沿用完整性拒绝路径。两个同层级、同地区、同RRF候选按已有日期完成排序，输出保留配置声明身份。未知日期、旧正文引用及完成账本保持可读。执行使用新隔离资源和新回执目录，保留失败结果。

## 交付与回退

本轮沿既有main实施。回退可恢复本轮检索、类型及展示改动，数据及历史引用使用既有表示。真实Responses、代表性检索质量、专业精确SKU、真人审核及完整发布Gate继续按原规格验收。

## 执行结果

已完成API、共享类型和Web展示。四模块156项回归、三端类型、Web55项及三种宽度30项实际React组件检查通过。隔离PG综合58项和日期专项7项分别通过，153张模型表的真实备份恢复指纹一致。源码和运行资源已核对，红批与两轮临时PG驱动失败保留。[完整验收记录](../assurance/evidence/pdf-publication-ranking-2026-11-13.md)
