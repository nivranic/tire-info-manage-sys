# PostgreSQL 非拥有者许可操作员

本方案将许可 CLI 的数据库账户与数据库／表拥有者分开。它仅用于已迁移的 PostgreSQL 17+、public 应用 schema 和可信工作站操作员，不是 API／Worker 运行账户方案，也不代表 OIDC、租户或 RLS 已验收。数据库管理员和直接操作数据库的角色仍处于信任边界内。

## 授权范围

| 权限 | 对象 | 用途 |
| --- | --- | --- |
| CONNECT／USAGE | 明确的目标数据库／public schema | 建立连接和解析表 |
| SELECT | users、query_runs、snapshots、verifications、safety_gate_snapshots、safety_gate_verifications、tire_schema_versions、external_fact_license_evidence、external_fact_grant_revisions、audit_events | 管理员认证、观察绑定、完整许可链与审计 |
| INSERT | external_fact_license_evidence、external_fact_grant_revisions、audit_events | 追加条款、许可和审计 |
| UPDATE(display_name) | users | 满足现有 SELECT FOR UPDATE 的数据库权限要求 |

最后一项意味着这个数据库角色**确实可以修改账户显示名**；没有授予 id、username、password_hash 或 is_admin 修改权。选择这一单列权限可保持原管理员行锁和撤销顺序，不新增 SECURITY DEFINER 锁函数。需要完全禁止显示名修改的部署，应先设计和验收另一种锁接口，不能直接删锁或授予整个 users UPDATE。

认证复用现有 User 密码哈希，因此操作员角色可以读取 users，包括密码哈希；它不能被当作不可信终端用户或外部 API Key 的数据库身份。此角色没有 local_sessions 读取权限，也没有证据改写、删除、TRUNCATE、表／schema 创建、触发器禁用或角色创建权限。

## DBA 准备与授权

先由部署拥有者完成并验证现有 schema。在维护窗口确认数据库名称、业务写入者和既有 PUBLIC 权限影响；不要在未知数据库上套用示例。以下名称仅为部署示例。

1. 由 DBA 创建独立的空角色，并用 psql 的 `\password` 隐藏设置口令。不要把密码放进 SQL 文件或 argv。

```sql
CREATE ROLE tire_governance LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
```

```text
\password tire_governance
```

2. 该角色不得拥有任何对象，也不得有授出／授入的角色成员关系。核对共享权限：PUBLIC 的数据库 CREATE／TEMPORARY、schema CREATE 或危险函数权限会传给所有角色，不能通过对单个角色 REVOKE 抵消。下面两条须由 DBA 在评估其他账户影响后显式执行；工具不会自动执行它们。

```sql
REVOKE CREATE, TEMPORARY ON DATABASE tire_app FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

其他工作负载确需这些权限时，应单独授给对应角色。业务 schema 中可由该角色执行的 SECURITY DEFINER 函数也会使检查拒绝，须审查其共享授权。已有超出范围的权限、成员关系或所有权不能靠重新跑授权计划“覆盖”掉。

3. 从已安装 API 的环境生成本地 SQL 计划。生成过程不联网、不读取数据库／密码、不建角色、不执行 GRANT。角色和数据库名称只接受有限 ASCII 标识；输出文件包含部署账户名称，应放在 Git 忽略的私有目录。

```text
python -m tire_api.external_fact_governance_roles --role tire_governance --database tire_app > <private-plan.sql>
```

4. DBA 审查后，在明确的目标数据库执行计划，例如：

```text
psql "host=<host> port=<port> dbname=tire_app user=<deployment-owner> sslmode=verify-full sslrootcert=<absolute-ca-file>" --password --set=ON_ERROR_STOP=1 --file=<private-plan.sql>
```

连接串不含密码。计划含 BEGIN、固定 search_path／超时、既有 ingestion advisory 锁、目标检查、授权前检查、固定 GRANT、授权后检查和 COMMIT。数据库名不匹配、缺表、角色不合适或存在额外有效权限时拒绝。授权者只能授出部分权限时，即使 PostgreSQL 只发警告，后检查也会拒绝；整个事务回滚。重跑计划可补齐缺少的允许权限，不撤销旧权限、不设置 DEFAULT PRIVILEGES，也不迁移 schema。

## 操作员核验

把[许可治理连接配置](EXTERNAL-FACT-GOVERNANCE.md)的 user 指向新角色，随后执行：

```text
python -m tire_api.external_fact_governance_cli role-check --postgres-profile <absolute-profile-file> --username <application-admin>
```

沿用隐藏双密码和真实应用管理员认证。role-check 仅在只读事务中检查当前数据库连接角色，不接受任意 role-ID 代查，不锁定或修改 users。通过返回 `ok: true`／空 violations／退出码 0；不合规返回固定 violations 列表与退出码 1；连接或查询异常沿用脱敏失败码。

检查覆盖角色属性／成员关系、对象拥有权、目标库／schema 创建权限、所需表和列、额外表／列／序列权限、grant option、默认权限、可执行业务 SECURITY DEFINER 函数、系统目录秘密读取／写入、显式函数执行授权和参数 ACL。业务表启用 RLS 时当前方案明确拒绝，防止把被策略隐藏的许可历史当作完整链；RLS 接入须另行设计和验收。

PostgreSQL 原生允许 PUBLIC UPDATE pg_settings，其语义等同于会话 SET，不修改持久服务器配置。检查仅保留这个已核对的原生 UPDATE 权限；危险参数的额外 SET／ALTER SYSTEM ACL 仍拒绝。真实测试确认普通角色不能借 pg_settings 将 session_replication_role 改成 replica。官方依据：[pg_settings](https://www.postgresql.org/docs/18/view-pg-settings.html)。

普通许可命令保留原部署兼容行为，并不自动要求每次先通过 role-check。部署验收须独立运行 role-check，且在角色／ACL／schema／升级变化后重验。它是维护窗口中的权限快照，不是对另一位 DBA 后续修改、恶意扩展或损坏数据库的永久约束，也不证明其他数据库的权限安全。

## 验收与后续

本轮已在合成隔离 PostgreSQL 中验证无拥有者的轮胎／Safety Gate 审批、限制、撤回、旧 UUID 重放、正常 Reader／HTTP 消费、20 条越权 SQL 拒绝，以及授权不足后的原子回滚。目录／函数权限漏检及修正都保留原回执，详见[验收记录](assurance/evidence/postgres-governance-role-2026-11-14.md)。终端隐藏输入仍为模拟，非真实远端部署。

下一步是 API／Worker 的迁移与运行启动分离：当前 Database.initialize 仍执行 create_all、迁移和索引 DDL，不能直接使用本操作员角色，更不能用跳过初始化冒充 schema 验证。此后继续生产 IAM／RLS、吞吐和灾备。停用账户由 DBA 明确撤销登录／权限并处理连接；业务许可撤回应走 withdraw，不能删除账本历史。
