# PostgreSQL 运行角色权限专项

日期为 2026-11-14，基线为 `923a61f`。本轮在正式 `runtime-schema` 入口增加真实 catalog 漂移及授权事务检查，接续 [HNSW 维护验收](postgres-vector-indexes-2026-11-14.md)。完整 V1 持续进行。

## 覆盖范围

`scripts/postgres_schema_acceptance.py` 增加 23 项反例。每项先修改一次性数据库的实际权限或函数，再通过独立运行连接调用 `check_runtime_role()`，检查拒绝代码和 SQL 类型，恢复后再次核对有效权限。

- 5 项缺权覆盖列级 UPDATE、表级 SELECT、INSERT、DELETE 和固定锁函数 EXECUTE。
- 18 项漂移覆盖额外列／表 UPDATE、治理表 INSERT、表／列／函数 grant option、PUBLIC CREATE／TEMPORARY、两个方向的角色成员关系、INHERIT、RLS、默认 ACL、未知 SECURITY DEFINER，以及锁函数正文、search_path、SECURITY INVOKER 和同名重载。
- 18 项漂移还执行原始 `runtime_role_sql()` 计划，确认前检查以 P0001 拒绝。读检查观察到 SELECT、SET、WITH，所有场景恢复后 violations 为空。
- 另有一项部分授权场景。安装者可授予 CONNECT／USAGE，并可读取业务表和执行固定函数。缺少表及列的 grant option 时，PG 产生 01007 警告，原计划后检查以 P0001 拒绝。ROLLBACK 后，候选角色在数据库、schema、关系、列和函数上的显式 ACL 与空前态一致。完整授权随后成功，重复应用保留相同 ACL，独立候选角色检查通过。

## 最终结果

| 范围 | 结果 | 回执及 SHA-256 |
| --- | --- | --- |
| 正式 PG／TLS 运行合同专项 | 60 项通过，包含新增 24 项，842 输入稳定 | `.artifacts/postgres/pgverify-44aa38b4a21f43b08352129006f73ffe/report.json`，`9c3b59dfa9c17144191453a0599fb081d162a21cda61e9fa91560aa219751cf8` |
| 治理 CLI 与 schema 启动受管回归 | 45／45 通过，跳过和不完整均为 0，842 输入稳定，资源关闭，非自检拒绝 0 | `.artifacts/runtime-role-permissions/regression-r1/result.json`，`9ce6aa02c816ecc0bf2f7af07411215d6ead2f48275f457985ba1e2f5c7b10bd` |

60 项沿用正式 PowerShell wrapper 和 uv 入口，覆盖原有 API／Worker、旧库升级、结构拒绝、pgvector、拥有者索引维护、后检查回滚及运行连接关闭。运行时使用既有私有 PG 18 与 pgvector 0.8.1，DLL 摘要已与原固定源码构建回执核对。源码修改集中在验收脚本，应用部署继续遵循 @4 合同与已批准权限方案。

## 原始失败与最小复现

- `pgverify-7a585f77f4634bcb9c1d9e0144be83e2` 前 10 项通过。新增观察器遗漏正常 catalog 查询的 WITH 类型，已补正观察器。
- `pgverify-f7adf940a63c454fba05737b1719b6ef` 前 16 项通过。反例中的表级 UPDATE 撤回同时移除了原列级授权，恢复检查失败。独立最小 PG 探针 `pgverify-02f16f6e3003409198240dddf1906877` 记录列权限从 true 变为 false，恢复步骤已复用 `UPDATE_COLUMNS['users']` 重新授予既有列策略。
- `pgverify-db1e2c52b8e544b1835bf8957d038232` 前 33 项通过。部分授权装配在固定函数 EXECUTE 处提前以 42501 拒绝，已给测试安装者授予该执行权限，使场景到达原计划后检查。
- `pgverify-500e3320e34c44e690730ab8150b512a` 前 49 项通过，包含全部新增反例与部分授权回滚。基础 PG 安装缺少 pgvector，在原扩展场景取得 0A000。后续复用既有私有 pgvector 运行时完成 60 项。

本轮 6 个一次性集群的关闭、口令／TLS 私钥缺席及自用端口核对见 `.artifacts/runtime-role-permissions/closure.json`。原始失败、探针、数据库和回执位于 Git 忽略目录。

## 复跑与剩余范围

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_external_fact_governance_cli.py apps/api/tests/test_schema_startup.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <postgres-bin-with-pgvector> -Port <unused-port> -Suite runtime-schema -CliTls
```

验收采用合成材料和隔离数据库。实际终端交互、远端部署角色、生产 IAM／租户／RLS、吞吐及灾备 SLO 继续待验。后续优先推进 Parser 间歇超时取证和真实部署，再继续真实模型、精确 SKU／人工 Golden、长期监控、Native 与其余发布 Gate。
