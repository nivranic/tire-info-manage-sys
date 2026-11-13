# PostgreSQL 车型 024 迁移与恢复验收

日期为 2026-11-14，基线为 `3bf187f84139315416ef3fef08c68a4a855b0d67`。本轮实现旧 PG 文本车型结构的显式维护入口，完整 V1 继续进行。

## 实现与入口

新增 `vehicle_binary_postgres.py` 和 `vehicle_binary_postgres_cli.py`。CLI 复用显式 PG profile、SCRAM／TLS 与隐藏密码输入，在同一维护事务取得 schema／ingestion advisory 锁与既有表写锁。导出快照生成独占创建的 pg_dump custom 备份后，完成 016–023 和四表 024 迁移，核对旧列行指纹、版本时间和已有结构，最后提交。

四表变更通过 ALTER TABLE 完成，PG 外键持续有效。旧 body 保留，body_encoding 为 utf-8，raw_capture_id 保持 NULL。结果中的 preserved_original_rows 统计业务行，版本表旧行及 applied_at 另行核对。操作步骤见[PG 车型维护说明](../../POSTGRES-VEHICLE-MIGRATION.md)。

## 最终 PG 结果

| 范围 | 实际结果 | 回执与 SHA-256 |
| --- | --- | --- |
| 历史 015 源码建库、正常 CLI 备份／迁移／恢复 | 17 项通过，840 输入稳定 | `.artifacts/postgres/pgverify-07501bc6d29c4a2c88d699c716d52ba1/report.json`，`40301eb0dd4d64451f49cac16640fdfcf384b49c55f63ca5ca4deeeceb88052d` |
| @3 运行合同、非拥有者 API／Worker 与结构反例 | 30 项通过，840 输入稳定 | `.artifacts/postgres/pgverify-85ac86c3e2eb4f248754e2bd10029a87/report.json`，`784f6bf7adfb0a25cdb826fec84c7e97a847600ebbf2406caccfa9455943ea76` |

正式历史源码来自 `81e18e734330c43dfa8c20545aa70b6f78e6e97b`，验收入口通过本地 Git 导出固定包与历史车型夹具，逐文件核对哈希。原代码通过正常 API 生成合成车型快照，再补充一条合法的旧 RawCapture。共 107 张旧表，16 条业务行及旧版本时间经升级核对。维护账户为非 superuser 的对象拥有者。

实际 CLI 生成 309954 字节备份，SHA-256 为 `eac1723c4370eed5e1796a8d52a8615a865ef18aba2ea358fdc633a115ea0f9b`。独立数据库恢复后，原 015 结构和全部旧行匹配。恢复演练显式使用 no-owner／no-acl，角色和 ACL 部署继续由 DBA 验收。

17 项覆盖普通启动的迁移要求、快照备份、显式迁移、旧行保留、幂等、当前版本升级与空参考合同匹配、verify API 读取原车型正文及原 SHA、独立恢复、四阶段回滚、坏原件哈希、部分结构、提前版本、备份失败／禁止覆盖、锁等待和已有视图／索引保留。

30 项运行合同另覆盖可选 vector、DDL 权限拒绝及表／列／默认值／可空性／约束／索引／触发器／函数／版本／扩展等反例。本轮新增枚举成员变更拒绝。该批之后仅维护验收脚本补充 RawCapture 及 API 消费检查，包内 Python 源码摘要与该批参考合同仍匹配。最终受管回归绑定完整交付输入。

## 受管回归

最终受管四模块 **142／142 通过**，setup／call／teardown 均通过，无跳过或不完整，840 输入稳定，资源关闭，非自检拒绝 0。回执为 `.artifacts/pg024-reg-final/result.json`，SHA-256 为 `952483c46271e80cfb90d4318dcfc8e66d45acc081af43ea56fdbb6f45f39b10`。收尾逐文件核对 840 个输入与最终文件一致。Python AST、本地 Markdown 链接、敏感模式、原规格及封存历史尾文检查通过。

## 恢复表达式差异

首轮独立恢复的全部旧行一致，仅 10 个文本枚举 CHECK 的表达形式变化。原式把 varchar 数组整体转为 text 数组，恢复式逐元素转为 text。原始差异位于 `.artifacts/postgres/pgverify-ee650b65408d4842a662fc29e4a58f4c/restore-diff.json`。

合同提升为 `postgres-runtime-schema@3`。已核对 text／varchar 列上的可解析字符串成员关系按列名与成员值生成确定表达，其他约束继续按原合同处理。枚举成员改动仍被拒绝。部署需要按最终源码重新生成并批准 @3 合同。

## 原始失败保留

- `pgverify-2439472fe91b4545ac5d37c58ab5d21f` 的私有 DDL 探针在 Path 表达式括号处失败，修正后 `pgverify-45a01c8edbd7442b99bb50d08a7027ea` 完成最小 DDL 及当前合同实验。
- `pgverify-816ab716f05343a3accd7c71838909f9` 在 Git ZIP 的 apps 父目录判断处结束，尚未执行迁移。
- `pgverify-85a1941831484a0493d42561c2cb0816` 前 2 项通过，原日志确认验收连接池使 CREATE DATABASE TEMPLATE 被拒绝。验收引擎改为 NullPool 后继续。
- `pgverify-381b2fc61e9f476ba01d4dd02c758664` 前 5 项通过，在独立恢复结构比对处失败。下一轮 ee650b 保留逐项 CHECK 差异，随后按实测结果实现 @3。
- `pgverify-4c3eb6cc4d954b1996396f44f1d803e6` 前 10 项通过，坏哈希反例未拒绝。原始行清单确认 RawCapture 为零，补入合法旧接收记录并明确断言其数量后，最终 17 项通过。
- `.artifacts/pg024-reg/` 为前一验收脚本绑定的受管通过批，最终完整输入使用 pg024-reg-final 单独留证。

## 复跑与资源

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_vehicle_binary_migration.py apps/api/tests/test_external_fact_governance_cli.py apps/worker/test_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite vehicle-migration -CliTls
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-schema -CliTls
```

历史专项需要本地 Git 包含固定历史提交。实际 wrapper 仅调整仓库定位并使用已安装 Python。九个隔离集群均关闭，postmaster.pid、初始化密码与 TLS server.key 已缺席，两个使用端口可重新绑定，见 `.artifacts/pg024-delivery/resources.json`。

API 使用 ASGI TestClient，终端密码输入由测试模拟。材料和请求均为合成内容，来源请求由历史夹具响应。真实终端、远端部署、对象／Parser 全资产恢复、完整 DML 最小权限、IAM／RLS、吞吐／灾备和其他 V1 Gate 继续待验。
