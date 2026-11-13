# PostgreSQL 非拥有者许可操作员实施计划

**Goal:** 让许可 CLI 使用不拥有数据库／表／函数的独立登录角色，交付可审查授权 SQL、有效权限检查和真实 PG 反例。

**Architecture:** 不改变 GovernanceStore 的锁、认证或账本规则。固定表／列授权集合由一个模块生成事务 SQL，并由 CLI 的 PG 专用 role-check 检查实际有效权限；不得自动收回 PUBLIC 权限、创建角色、改密码或执行迁移。

**Tech Stack:** PostgreSQL 17+ catalog/ACL、SQLAlchemy、现有 CLI、隔离 PG 验收。

## 发现与方案

API/Worker 的 Database.initialize 会 create_all、迁移及创建搜索索引，当前仍依赖拥有者；它需要后续单独的迁移／运行启动分离，不能简单跳过初始化。本轮先分离已具备独立连接的许可运维账户，这是生产部署权限工作的一部分，不代表应用运行角色或 RLS 已完成。

许可管理需要读取 users、query_runs、snapshots、verifications、Safety Gate 两表、schema 版本、两表许可账本及 audit_events；只向许可两表和 audit_events 追加。管理员事务复查使用 SELECT FOR UPDATE，PostgreSQL 要求至少一列 UPDATE 权限。采用 UPDATE(users.display_name)，不授予 id／username／password_hash／is_admin 修改权限；该角色因此确实能修改显示名，须明确记录。拒绝为了锁而授予整个 users UPDATE。另一选择是 SECURITY DEFINER 锁函数，但会引入新的特权执行合同和迁移，当前不采用。

## 工作项

1. 新增 `external_fact_governance_roles.py`：严格 SQL 标识、固定 ACL、预检／后检 SQL及纯本地 SQL 计划命令。仅接受已存在、无成员关系、无任何对象所有权、无特权、NOINHERIT 的 LOGIN 角色；DB／schema 的 PUBLIC 额外权限或可执行 SECURITY DEFINER 函数导致拒绝，不能静默改动共享权限。
2. `external_fact_governance_cli.py` 增加仅 PG 的 role-check，隐藏双密码和真实管理员认证保持；固定 JSON 诊断，不输出连接地址、凭据或异常。
3. 在既有 CLI 测试模块补输入、参数、输出和 SQL计划反例；旧实现必须出现缺失能力的失败回执。
4. 扩展真实 PG 验收：纯 SELECT 角色的锁拒绝→精确列权限后正常流程；无拥有者的审批／限制／撤回／旧 UUID 重放与 Reader；拒绝改密码／管理员身份／schema／证据、DROP／TRUNCATE／触发器修改、SET ROLE／特权角色创建；ACL 漂移、PUBLIC 授权、成员关系、grant option 和可执行 SECURITY DEFINER 检查；Safety Gate 许可链。
5. 受管测试、真实隔离 PG 和 TLS 验收，关闭集群／密钥／端口。更新治理说明及交接，正式提交推送并核对远端。后续继续 API 迁移／运行分离及生产 IAM/RLS。

## 验收和回退

只在新建的合成 PG 集群应用授权，正常库不动。SQL 整体事务化；前／后检查拒绝时回滚所有本次 GRANT，已有权限不自动删除。无默认权限授权；新表／角色权限改变后重新执行 role-check。有效权限检查是维护窗口中的快照，不是对另一位 DBA 后续变更的永久约束。

撤销角色登录／关闭其连接由管理员显式进行；停用 SQL 权限方案不能删除许可历史，也不能替代业务 withdraw。用户所有原需求和完整 V1 验收范围保持。
