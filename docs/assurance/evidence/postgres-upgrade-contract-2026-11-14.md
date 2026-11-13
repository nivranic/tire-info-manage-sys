# PostgreSQL 升级库运行合同兼容验收

日期：2026-11-14。基线 `6d5f4e0746983a74895727864016f5159312be43`。完整 V1 尚未完成；本轮修复已支持增量迁移路径的列顺序误拒绝，并查明更早版本的显式迁移缺口。

## 原始失败与修正

隔离 PG 重建现有 core 已覆盖的合成 001–004 缺列结构，再执行现有迁移。空参考与升级库唯一不同的 catalog 项为 columns；按表名／列名排序后内容完全一致，原 verify 仍报 schema_contract_mismatch。诊断回执为 `.artifacts/postgres/pgverify-ee52f85a17ad4022b7b016a7e38bbb06/report.json`，逐项原差异在同目录 catalog-diff.json。

把旧行保留、历史新增字段 NULL、版本时间和非拥有者启动加入正式 runtime-schema 验收后，原实现前 5 项通过，在旧库匹配处再次失败。原红批 `.artifacts/postgres/pgverify-dfa47e6216cd45f9932a5a10f7969b4a/report.json` 的 SHA-256 为 `fd3c55bd5f2fff06155485cdb42935313a7f0f17a16d11660f07eac46674aee0`。没有因失败删除数据或放宽约束。

修正仅将列捕获顺序由物理 attnum 改为表名／列名，合同提升到 `postgres-runtime-schema@2`。应用 ORM 和业务 SQL 使用具名列；查询中现有 SELECT * 仅用于 pg_roles CTE，与业务表物理顺序无关。类型、可空性、默认值、identity／generated、collation 及其他 catalog 项继续完整比较；不修改业务表，不重签运行库。

@1 合同不再被接受。部署必须使用最终源码，从受控空参考库重新构建、审查并固定新合同及 SHA-256；不能仅编辑旧合同版本或摘要。详见[运行启动说明](../../POSTGRES-RUNTIME-SCHEMA.md)。

## 最终测试

| 范围 | 结果 | 回执 SHA-256 |
| --- | --- | --- |
| 四模块受管回归 | 141／141 通过，无失败、跳过或不完整；837 输入稳定，资源关闭，意外拒绝 0 | `.artifacts/upgrade-contract-reg/result.json`：`d9df75100628d719f176ab0fd947a373b5bbe5d0936da190cdae2882c068c0be` |
| 真 PG 18.3 runtime-schema／TLS | 29 项通过，837 输入稳定 | `.artifacts/postgres/pgverify-19ad0ab0f0964831b84cb611559efb75/report.json`：`905179d4018f1d82d8f324b487c72d088036d945ff7e693125b18c860583b7df` |

PG 新增 3 项旧结构升级检查：所有既有业务行保持，新增历史字段为 SQL NULL，旧版本时间不改写，重复迁移稳定；非拥有者 API 读取旧证据并执行新合成查询。另新增默认值、可空性、列改名和多余列 4 项拒绝反例。既有表／约束／索引／触发器／函数／版本／扩展／RLS／类型／摘要拒绝和可选 vector 正例均保留。

本批 API 是 ASGI TestClient，Worker 为空队列，运行角色采用较宽 DML。合成历史结构不是任意部署旧库，真实模型、远端和生产最小权限均不在这批通过范围内。

## 正式历史源码的独立实验

使用本地 Git 对象导出两个正式提交的 apps/api/tire_api，逐文件绑定 SHA-256，在独立子进程运行原始代码。数据库、对象存储和凭据仅指向新建的隔离回环 PG；只插入合成账户、会话和查询。历史源码未经改写，没有复制生产数据库。

| 历史基线 | 实测结果 |
| --- | --- |
| `81e18e734330c43dfa8c20545aa70b6f78e6e97b`，迁移 015 | 原代码成功创建 106 张模型表；当前 initialize 在 preflight 返回 vehicle_binary_migration_required，尚未进入合同比较。当前代码只有 SQLite 的显式旧车型二进制迁移，PG 旧形态需要继续实现显式 024 迁移。不能跳过 preflight 或直接记版本来绕过。 |
| `985338f7bf89c6d0b5222f8c804c62332f07ea2a`，迁移 035 | 原代码成功创建 153 张模型表。当前升级后合同完全匹配；154 张旧表（含版本表）共 38 行及版本时间不变，重复迁移保持；新增 13 张 Safety Gate 表为空。 |

015 原失败保存于 `.artifacts/postgres/pgverify-5634127f59334a3cac2b546793072000/report.json`，SHA-256 为 `4d163852d9c4181ca3b949b1c44133cd23d344d30e54eb5aaa566aca2767518e`。

035 首轮仅检查 schema，回执为 pgverify-1e16d3154d5c44a78aa3d8fad1a7530c；追加全旧表行／版本时间与重复迁移核对后的最终回执为 `.artifacts/postgres/pgverify-8a9d916c965246408053ffe8a9272f01/report.json`。最终报告 SHA-256 为 `101c5bb044062ed501aaa02e47068fcaec597610373f620ce5b669055286f0ed`。历史 176 个源文件和当前 837 个受管输入均稳定。该独立实验以数据库拥有者执行迁移／比对，没有单独声称此历史库的所有业务端点或非拥有者消费已验。

## 复跑与保留

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_vehicle_binary_migration.py apps/api/tests/test_external_fact_governance_cli.py apps/worker/test_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-schema -CliTls
```

正式 29 项入口已纳入 Git。本机 wrapper 仅把仓库定位改为实际脚本相对位置并使用已安装 Python。历史独立诊断脚本、源码清单和原报告留在 `.artifacts/upgrade-contract-history/` 与 `.artifacts/upgrade-contract-history-035/`；新 clone 不含这些私槽，复验须用上述固定提交重新导出、确认隔离数据库及隐藏凭据输入后重建，不可直接连接部署库。

六个独立集群均关闭，postmaster.pid、初始化密码和 TLS server.key 已缺席，两个使用端口可重新绑定，见 `.artifacts/upgrade-contract-delivery/resources.json`。收尾核对全部 837 个当前源文件与最终受管回执一致。没有真实来源／模型调用、代理或系统信任库修改。

下一步推进旧 PG 024 显式迁移与备份／回退演练、完整业务 DML 最小权限，随后继续真实部署、IAM／RLS、吞吐／灾备及其余完整 V1 Gate。
