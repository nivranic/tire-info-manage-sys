# 混合检索分页修复计划

## 目标与依据

原规格要求结构化、FTS、向量和融合排序依次进入证据包。现有KnowledgeSearch合同包含offset和limit，普通历史入口已支持分页。核对发现dense.hybrid_result与original_text_retrieval.hybrid_result仅取排序后的前limit项，后续页请求仍得到第一页。

## 实现范围

复用当前候选集合、权威／地区／RRF／观察时间排序，以及现有请求指纹、同意、预算和只追加结果账本。结构化与正文集合各自在全局排序后按同一请求的offset与limit取片，has_more根据分页终点计算。响应提供offset和limit，正文共享类型按可选字段兼容历史已保存结果。

## 实施顺序

1. 在 `apps/api/tests/test_original_text_retrieval.py` 通过正常混合检索API复现结构化／正文第二页重复，覆盖边界空页、排序顺序、独立集合、幂等重放和分页参数冲突。保留失败回执。
2. 修正 `apps/api/tire_api/dense.py` 与 `original_text_retrieval.py` 的分页终点、切片与元信息。在 `packages/domain-types/src/index.ts` 声明正文分页可选字段。
3. 为真实PG验收中的结构化和正文混合入口补跨页、排序及恢复后历史读取检查。保留现有合成Provider，使用真实FTS、cosine及持久存储。
4. 执行受管相关API回归、SDK与三端类型检查，以及隔离PG备份恢复验收。核对服务关闭、文档链接、敏感信息和源码字节，更新当前交接卡。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/hybrid-page-red --targets apps/api/tests/test_original_text_retrieval.py
npm run test:text-embeddings --workspace @tire/api-client
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
```

真实模型语义、代表性专业材料及完整V1 Gate继续按实际证据验收。

## 执行结果

两个正常结果入口已按全局排序后的offset／limit分页，并返回分页元信息。新增API回归覆盖结构化、HTML＋PDF、后续页、集合边界和offset2000、幂等重放、参数冲突及历史读取。首批失败定位于分页元信息缺失，调整断言顺序后，两例在第二页内容比对处失败。两批原始红回执均保留。

修复后的正文专项33／33，最终六模块API161／161，796输入稳定、资源关闭、非自检拒绝0。SDK9／9、Web55／55和三端类型通过。综合PG58项及153模型表备份恢复一致，包含正文分页和恢复后的分页账本读取。独立pgvector业务14项及155实际表备份恢复一致，包含结构化融合分页、空页和重启幂等重放。两套表统计分别遵循各自验证器的范围。

本轮回执根目录为 `.artifacts/hybrid-pagination-20261113/`，API红／绿槽为 `.artifacts/hybrid-page-red`、`hybrid-page-red-r2`、`hybrid-page-green-r1` 和 `hybrid-page-green-r2`。两个隔离集群的pg_ctl均为3，对应端口无监听。现有Web生产构建与浏览器结果见[无障碍阶段计划](2026-11-13-web-accessibility.md)，本轮Provider和材料采用合成夹具，真实语义质量继续待验。
