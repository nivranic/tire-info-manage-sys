# PostgreSQL 许可治理 CLI 实施计划

**Goal:** 让管理员通过已有许可 CLI 管理已迁移的 PostgreSQL 数据库，保持审批、限制、撤回、幂等和审计合同。

**Architecture:** 普通命令在显式 SQLite 文件和 PG JSON 配置间二选一，复用 GovernanceStore。连接配置独立校验；数据库与应用管理员分别隐藏认证。PG 不提供隐式建库、迁移或 SQLite 回退。

**Tech Stack:** Python、SQLAlchemy、psycopg/libpq、受管回归和隔离 PostgreSQL。

## 决策与边界

- 选择不含密码的闭合 JSON 配置和隐藏密码输入。带密码 DSN 会进入进程参数；复用服务环境默认库可能选错数据库；这两种方案不采用。
- 配置明确 schema 版本、host、port、database、user、sslmode、sslrootcert。只支持 public 应用 schema。远端要求 verify-full 和显式 CA 文件；disable 仅接受规范 loopback IP。
- 拒绝非空 PG* 环境覆盖、多主机、Unix socket、连接 URL、任意 options 和配置中的密码。认证要求 SCRAM；关闭 GSS 和客户端证书自动选择，所需 libpq 选项不存在时明确拒绝。
- 专用 CLI engine 使用 NullPool、READ COMMITTED、固定 search_path、连接 5 秒、锁 2 秒、语句 5 秒、事务空闲 15 秒。超时失败不自动重试；共享 Store 和 Reader 锁合同不变。
- 交互读取失败不降级到回显密码；释放连接失败不得输出原始异常或先报告成功。提交回执未知时沿原 UUID 核对／重放，不换 UUID。
- 这是工作站运维能力，不替代生产 IAM、ACL、RLS、吞吐或法律许可审查。先实现数据库密码 SCRAM 认证，其他部署认证方式另行设计。

## 执行步骤

1. 扩展 `apps/api/tests/test_external_fact_governance_cli.py`：参数互斥、禁止 PG init、闭合配置、TLS／环境／密码输入拒绝、错误脱敏和连接关闭反例。先通过受管入口记录旧实现失败。
2. 新建 `apps/api/tire_api/external_fact_governance_postgres.py`，实现明确配置和专用连接；修改 `external_fact_governance_cli.py`，复用既有 Store，无新许可规则。
3. 扩展 `scripts/postgres_external_reader_acceptance.py` 的独立场景：真实非 superuser PG 连接、审批／限制／撤回／重放、冲突、认证／schema／权限拒绝、锁与语句超时及 Reader 权限变化。TTY 自动输入与真实终端验收分别记录。
4. 运行受管 CLI／许可／Safety Gate 回归；以新隔离集群运行新增 PG 场景，保留全部失败和源码指纹；关闭集群、移除临时口令并确认端口释放。
5. 更新 `docs/EXTERNAL-FACT-GOVERNANCE.md`、验收证据和当前接手卡，记录未验 TLS／终端／生产边界。审查差异和未推送提交，正式提交并直连推送，独立核对远端。

## 验证入口

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/pg-cli-regression --targets apps/api/tests/test_external_fact_governance_cli.py apps/api/tests/test_external_fact_governance.py apps/api/tests/test_safety_gate_external_governance.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite external-reader
```

每轮使用新输出槽，验收期间不改输入。不运行裸 pytest 替代门禁，不创建分支／worktree。失败不得通过放宽许可、删除锁或自动重试变绿。

## 回退

本变更没有数据库迁移。退回 CLI 源码可停止 PG 管理入口，已经追加的许可事件仍由既有 Store 读取；撤销权限必须追加 restrict／withdraw，不删除账本历史。
