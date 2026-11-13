# PostgreSQL 迁移与运行启动分离验收

日期：2026-11-14。基线 `19d0cf02d04de4b4bb73bd1fe57f4e9ff1108212`；本轮正式提交 SHA 以 Git 为准。完整 V1 保持未完成。

## 实现

Database 模型注册和迁移执行分开复用，既有事务和 schema advisory 锁保持。显式 verify 只比对已批准的源码绑定参考合同，API lifespan 和 Worker 入口沿用统一分派；不运行 create_all、upgrade 或索引 DDL。参考构建只允许空的明确 PG 数据库，不能从运行库自动签发合同。操作及限制见[运行部署说明](../../POSTGRES-RUNTIME-SCHEMA.md)。

## 最终证据

| 范围 | 实际结果 | 回执与 SHA-256 |
| --- | --- | --- |
| 启动、车型迁移、许可 CLI、Worker 四模块 | **141／141 通过**，837 输入稳定、资源关闭、非自检拒绝 0 | `.artifacts/rs-reg-final/result.json`；`4f0fa9c848ee322c2c4eda5112af76e52d60f00773719e012c4a3d97b93f94dc` |
| 真 PG 18.3、TLS、独立迁移／无拥有者运行 | **22 项通过**，837 输入稳定 | `.artifacts/postgres/pgverify-3b07b6caa6514b34ae16d1cdbbe2f1f9/report.json`；`c5acba7908d6eee6d30049ee204ad7187731e94cf837d3a83ec736b5cb432069` |

参考库实际包含 **166 个模型表、167 个普通关系**（包括版本表），API factory 没有再补注册额外模型。可选 vector 参考多一张派生表，独立完成构建和无拥有者校验。参考合同正文、数据库和私有连接配置均不进入 Git。

真实 PG 22 项覆盖：参考 CLI 构建；拒绝已有库签发及覆盖文件；独立新库迁移后精确匹配；非拥有者 API 启动、管理员注册、合成查询和证据读取；Worker 正常 `--once` 入口；五种拥有者 DDL 拒绝；缺表／列、列类型、约束、索引、用户触发器、函数、版本、FK 内部触发器、额外视图、扩展变化的拒绝；RLS／自定义类型拒绝；可选 pgvector 正例；错误文件摘要／源码摘要／PG major 拒绝；运行连接关闭。

API 启动观测到的 SQL 类别仅 SELECT／SET；Worker 单次入口仅 INSERT／SELECT／SET，没有 DDL。API 请求通过 ASGI TestClient 走实际 lifespan、认证与业务路由，PG 为真实服务器；不是浏览器／公网网络部署验收。Worker 本次为空队列，不能证明长期监控和真实变化通知。运行角色非拥有者、非 superuser，但测试授予较宽 DML，不作为生产 DML 最小权限方案。

## 失败与定位

1. `.artifacts/rs-red/` 保存新增能力的红批；`.artifacts/rs-r1/` 为早期 8 项启动检查通过。后续增加参考 CLI 配置反例，最终以四模块结果为准。
2. `pgverify-968f2eaefece4a709020ba0c92232f0a` 在参考建表时报 pg_catalog 权限拒绝。原日志证明固定 pg_catalog 优先路径被用于未限定 schema 的 CREATE TABLE；只对已检查为空的参考迁移改为事务局部 public 优先，捕获／运行恢复原固定路径，没有扩大权限。
3. `pgverify-71537162351b4506a941eaa2d6800a85` 前三项通过，验收代码错误读取不存在的 provenance.evidence_path。改用已有 snapshot_id 对应证据路由，不改 API 返回合同。
4. `pgverify-6037549e3ab840f08c0cab805ee3d37d` 前 15 项通过，额外视图由测试管理员创建，随后由原拥有者统一 GRANT 时被拒绝，尚未进入结构校验。将夹具授权移到破坏操作前，保留真实权限拒绝，未让运行账户拥有新对象。
5. `.artifacts/rs-reg1/` 为 139／141，两项旧迁移断言未列入此前已发布的 13 张 Safety Gate 表。只读清单差异明确指出这 13 张表。临时使用 HEAD 原始 db.py 的 `.artifacts/rs-baseline-test/` 仍在相同两项／相同行失败，随后原字节恢复本轮文件。只补明确的 Safety Gate 表名集合，冻结 023 五文件及旧数据／列／索引／约束逐项检查保持，不从当前 metadata 自动推导期望。
6. `pgverify-bc0eea131ba445739d2e6c613b238669` 已取得 22 项通过；最后追加 Worker SQL 类别观测后得到上述最终 PG 结果。各轮独立留证，不把它们合并为一轮测试。

## 复跑与资源

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_vehicle_binary_migration.py apps/api/tests/test_external_fact_governance_cli.py apps/worker/test_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-schema -CliTls
```

本轮 `.artifacts/rs-pg-final/verify.ps1` 仅调整仓库定位并使用已经安装的 Python，运行原 runtime-schema 全套入口。五个隔离 PG 集群都已停止；各目录 postmaster.pid、init-password.txt、TLS server.key 缺席，端口可重新绑定，见 `.artifacts/rs-deliver/resources.json`。没有连接正常业务库、调用真实材料来源或模型、使用代理或修改系统信任库。

保留边界：参考基于当前完整新库结构；旧 PG 升级库物理兼容、RLS／策略、完整 DML 权限、真实终端／远端、吞吐与灾备未验。源码摘要覆盖包内 Python，不是整个镜像或依赖二进制证明。schema 校验不等于业务数据完整性，也不能抵御可信管理员之后的修改。下一步继续旧库兼容和应用 DML 权限方案，完整发布 Gate 仍开放。

## 交付静态复核

收尾先核对两份最终回执 SHA-256 及全部 837 个受测输入，均匹配。随后仅删除 postgres_schema.py 第 72 行一个行尾空格；修改前后 Python AST 完全一致，原受测字节与对比回执保存在 `.artifacts/rs-deliver/whitespace-audit.json`，未重复运行上述功能测试。此空白修改仍改变源码摘要，部署必须依据最终提交重新生成参考合同，不复用测试私槽合同。文档历史尾文曾被编辑统一换行，已从既有备份恢复并核对原始及 Git LF 摘要；失败副本保留在私槽。Python AST、文档本地链接、敏感模式、原规格和封存历史尾文检查通过。
