# PostgreSQL 非拥有者许可角色验收

日期：2026-11-14。基线 `e0310f64fa2f9b7e8a7456afb6fce5a2d09010c3`，正式提交 SHA 以 Git 为准。完整 V1 尚未完成。

## 交付及验证结论

新增固定权限的 SQL 计划生成器和 PG 专用 role-check，普通许可 CLI 复用既有 Store，不改账户认证、行锁、许可链、Reader 或业务时间校验。计划只对明确的已有角色授出允许集合，前后检查不通过时整体回滚；不隐式建角色、设置密码、改 PUBLIC 或迁移 schema。部署步骤和单列 UPDATE 的实际代价见[操作员方案](../../POSTGRES-GOVERNANCE-ROLE.md)。

最终受管 CLI／普通许可／Safety Gate 三模块 **43／43 通过**，834 输入稳定、资源关闭、非自检拒绝 0、无真实 Provider 调用。回执 `.artifacts/gr-delivery-reg/result.json`，SHA-256 `0f867bd9442df86874bad6d7fd720e2d7344dfb77c0119d14769eefc4783ca98`。

最终真实隔离 PG 18.3 **9 个场景通过**，409 个 Python 输入稳定。回执 `.artifacts/postgres/pgverify-7a91273e79174a8b90b4144a2f459d8f/report.json`，SHA-256 `2320726b7630b5d94287897f42b9eb2c36e83377ee683427ceb41986c114a43f`。

| 场景 | 已实际验证 |
| --- | --- |
| 原 CLI 生命周期 | 正常批准、限制、撤回、旧 UUID 重放和 Reader 消费 |
| 原 TLS 连接 | 有效 CA／主机名成功，错误 CA／主机名拒绝 |
| 无拥有者生命周期 | 新 LOGIN／NOINHERIT、无成员／所有权的角色通过检查；纯 SELECT 的管理员行锁报 SQLSTATE 42501；补精确列权限后全流程可用，重复授权保持同一集合 |
| 越权拒绝 | **20 条 SQL 均被 42501 拒绝**：账户身份／口令／管理员标记、证据和审计改写、schema／DDL／TRUNCATE／触发器禁用、会话读取、角色创建／切换、危险会话参数等；显示名 UPDATE 明确可用并回滚 |
| ACL 漂移 | 额外列／表、grant option、PUBLIC CREATE／TEMP、SECURITY DEFINER、RLS、默认权限均拒绝，清理漂移后恢复通过 |
| 成员和目标 | 双向角色成员关系、拥有者角色、错误数据库目标均拒绝 |
| 系统权限 | pg_authid SELECT、rolsuper 列 UPDATE、pg_read_file EXECUTE、危险参数 SET、PUBLIC 内建文件函数执行及原生视图 grant option 六项注入全部拒绝；未读取秘密或执行特权函数 |
| 不完整授权回滚 | 安装者有 CONNECT／USAGE grant option 但无表 grant option，部分 GRANT 只警告；后检查 P0001 拒绝，已授出的库／schema ACL 均回滚为 0；完整拥有者随后安装成功 |
| Safety Gate 正常 HTTP | 非拥有者 CLI 批准后外部 HTTP 200，限制／撤回后 404，旧批准 UUID 重放保持 withdrawn |

许可、轮胎和 XML 均为合成材料。CLI main、密码哈希验证、SQL和 TLS 为真实流程，TTY 检测／getpass 输入仍模拟。Reader／HTTP 应用在原拥有者连接上运行，只有许可操作员使用新角色；不得将本轮称为 API 运行角色最小权限验收。

## 原始失败和证伪过程

1. `.artifacts/gr-red/result.json` 保存新增角色能力在旧实现下的失败；随后 `.artifacts/gr-r1/`、`.artifacts/gr-final/` 为各阶段受管通过，不替代最终源码回执。
2. 首轮 PG `.artifacts/postgres/pgverify-89ad48f362f644288f2b875789fcfcc1/` 中轮胎 Reader 拒绝，其他 5 场景通过。独立复现 `pgverify-8ecf4d9350094b10b299a4062d14b3c7` 显示测试 Reader 固定时钟为 `2026-11-13T16:11:33.946888+00:00`，真实 CLI 审批时间为 `2026-11-13T16:11:34Z`，原因明确为 `review_in_future`。修正真实 CLI 场景的测试读取时钟，产品时间规则不变。随后 `pgverify-c0b592d888594fce8ef0b7f4569c8178` 七场景通过。
3. 复核发现审计初稿只检查业务对象；`pgverify-9b2b66dfa3d84386a8d6152b561ea2c1` 实际注入三种系统目录／内建函数权限，三种均漏拒绝。最终新增系统目录、显式函数和危险参数 ACL 检查。没有把初稿通过当作完整安全证明。
4. 扩展目录检查后，`pgverify-3764d52d31db4567b809b693a0031f90` 初始角色被拒绝。两次只加诊断的 `pgverify-90086cd2630d47148e5cb6dc6e192a8d`／`pgverify-057599ef7b84481c8b2add66a612f832` 定位到原生 PUBLIC UPDATE pg_settings；诊断仅含固定权限码和系统对象名称。实际 ACL 与[官方文档](https://www.postgresql.org/docs/18/view-pg-settings.html)确认其语义等同会话 SET。保留这一精确原生行为，并检查额外参数 ACL；真实越权测试证明无法关闭触发器。随后 `pgverify-02783d19eb1a49288ed8446a7a2d0997` 八场景通过。
5. 最终新增部分 GRANT 后检查／回滚反例，取得九场景通过（`pgverify-8b1d3bd8d6824249b42374406a67068c`）。随后补齐 PUBLIC 内建文件函数与原生视图 grant option 两条覆盖，并对待交付源码取得上述九场景最终通过。以上各批不合并成一轮测试；失败、时钟及目录 ACL 诊断全部保留。

## 资源、复跑和边界

本轮十个隔离集群都已关闭。独立检查各目录的 postmaster.pid、init-password.txt 和 TLS server.key 均缺席，测试端口可重新绑定，回执 `.artifacts/gr-deliver/resources.json`。没有连接生产数据库、修改系统信任库或代理；材料、运行库、证书和回执都留在 Git 忽略目录。

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-artifact-slot> --targets apps/api/tests/test_external_fact_governance_cli.py apps/api/tests/test_external_fact_governance.py apps/api/tests/test_safety_gate_external_governance.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite external-reader -CliTls
```

标准 PG 命令运行完整 Reader 套件。本轮 `.artifacts/gr-pg-delivery/verify.ps1` 仅调整仓库定位、使用已安装 Python 并显式选择上述九场景；不宣称本轮重跑历史全部 Reader／core。SQL 生成器无数据库副作用；实际授权由独立连接执行生成的原始事务 SQL，没有换成测试专用权限脚本。

role-check 是目标库有效权限的快照，不能抵御可信 DBA 后续变更或恶意扩展，不证明其他数据库、真实远端部署、实际终端、生产 IAM／RLS、吞吐或灾备完成。API／Worker 启动仍自动执行 DDL，下一步应分离迁移与运行启动，保留完整 schema 验证，不能绕过初始化直接启动。
