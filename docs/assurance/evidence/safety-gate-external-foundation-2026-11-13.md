# Safety Gate查询归属与许可证据绑定交付点

日期：2026-11-13。起点为已发布的 `d8a42a1146ca2684fcce5c3534eae1e64e8aa059`。这是[外部读取计划](../../plans/2026-11-13-safety-gate-external-api.md)步骤1、2的交付，完整外部读取能力仍待实施。

## 实现与边界

普通登录查询冻结账户归属，原子追加QueryRun、标准审计与不可变owner receipt；匿名旧查询不追认，会话换绑不转移旧归属，单次consent不新增归属。失败请求的归属不能冒充成功核验。

受管许可账本对固定来源eu-safety-gate选择SafetyGateSnapshot／SafetyGateVerification，验证指定周报、原件／文档哈希、URL／查询、Parser身份及成功QueryRun。索引、错误快照／哈希／Parser与破损证据拒绝；304可绑定最近成功核验。保持原receipt形状、管理员预览／确认、只追加审计和明确许可原文，不因CC0声明跳过审批。每份原件最多8MiB，单批总原件最多32MiB。

没有新增表、scope或外部HTTP路由。SQLite归属和外部Reader的后端限制保留；本轮只用合成XML与合成许可进行受管SQLite／ASGI回归。没有真实来源、真实模型、生产Web、真实PostgreSQL或公网客户端验收。

## 原始失败与修正

- `.artifacts/sg-owner-r1/`：归属缺失时的预期红批；随后 `.artifacts/sg-owner-r2/` 三模块56项通过。后者仅对应当时源码。
- `.artifacts/sg-license-r1/`：许可仍读取普通轮胎表时，Safety Gate正常审批预期失败；result SHA256为 `bddcc218beebea596fecc420bb1abe24f6e77eedb5a64dd9f2ca213e9a93dd99`。
- `.artifacts/sg-handoff-final-r1/`：八模块143项，142通过／1失败；新增归属与许可测试通过。失败为既有 `test_023_additive_file_migration_preserves_every_old_row_and_ddl`，完整初始化比旧断言多出正文FTS表。result SHA256为 `a5fe6344a86be163e03ca523732dd92d436bd67d66d2aeb851582316d8fb12ff`。
- `.artifacts/sg-handoff-diag-r1/`：在受管私槽保存合成夹具的原始断言，确认差异为source_text_fts／document_text_fts及各自5张内部表。未修改产品迁移；测试显式声明这12张表的完整初始化增量及空索引，保留023版本INSERT时的精确增量、所有旧行／DDL、幂等、完整性和外键检查。
- `.artifacts/sg-handoff-migration-r2/`：修正后迁移与失败回滚2项通过，result SHA256为 `9ccbf43ab1ed145a787eb8e0130acd76f3c8fbbdc02c020f34289f70146e8782`。

## 最终验证

最终 `.artifacts/sg-handoff-final-r2/result.json`：八模块 **143／143通过**，无跳过或未完成；818个源码输入稳定，自有资源关闭，非自检拒绝0，真实Provider／接收端调用0，普通业务数据库未启动。SHA256为 `db8ea2b8c73c6c8bb6886293848eab8874dfeb4665b998fa39d48e84e9fe5eca`。这是列明八模块的专项回归，不是全量V1验收。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/sg-handoff-final-r2 --targets apps/api/tests/test_safety_gate_query_ownership.py apps/api/tests/test_safety_gate_external_governance.py apps/api/tests/test_safety_gate_fallback.py apps/api/tests/test_query_ownership.py apps/api/tests/test_external_fact_governance.py apps/api/tests/test_external_fact_governance_cli.py apps/api/tests/test_external_tire_fact_reader.py apps/api/tests/test_external_api.py
```

复验使用新输出槽，不覆盖本轮红绿回执。前端未改动，本轮未重跑前端构建与浏览器；上一阶段的PG／Web／真实材料结果继续按各自源码范围解释。

## 下一步

实现源专属外部Reader、固定grant路由、新scope、字段投影、事务内权限复核、绑定游标、容量限制、共享类型／SDK与Web；随后执行真实许可材料、正常HTTP和生产客户端验收。正式PG外部Reader另需锁与物化SQL合同验证。完整V1继续开放，详见[接手卡](../../AGENT-HANDOFF-CURRENT.md)。
