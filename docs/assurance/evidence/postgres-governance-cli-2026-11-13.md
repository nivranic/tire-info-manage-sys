# PostgreSQL 许可治理 CLI 验收

日期：2026-11-13。代码基线 `3878f8c7c8faadfd944279cfdd3bc1d5a8ffd8ea`，本次正式提交 SHA 以 Git 为准。完整 V1 保持未完成。

## 交付行为

普通许可命令新增互斥的 `--postgres-profile`；沿用 GovernanceStore 的管理员校验、事务内角色复查、预览摘要、版本 CAS、UUID 幂等、原生追加保护和同事务审计。没有数据库迁移，也没有更改 Reader 锁或许可规则。SQLite 原入口保留；`init-private` 不接受 PG。

闭合配置固定目标、SCRAM 认证与 public schema。远端使用 verify-full、显式 CA 及 channel binding；关闭客户端证书自动发送和 GSS。disable 仅允许规范 loopback IP。拒绝非空 PG* 环境和不支持所需选项的 libpq。密码分别隐藏输入；不支持隐藏输入时拒绝。输出延后至连接释放完成，清理异常不会泄露原始异常或提前报告成功。

依据：[PostgreSQL 18 连接参数](https://www.postgresql.org/docs/18/libpq-connect.html)。本轮实际读取并核对 sslcertmode、require_auth、gssencmode、channel_binding 与 connect_timeout 的官方说明。固定超时是连接／锁／单语句边界，不是整个 CLI 的硬期限。

## 原始失败与修正

- `.artifacts/gc-red/result.json`：新增反例在旧实现下失败，包含释放异常外泄及尚无 PG 参数／配置能力。此批为红批，不当作通过。
- `.artifacts/gc-r1/result.json`：CLI 与普通许可 26 项通过，Safety Gate 13 项失败。只读私库显示 query 原因为 `safety_gate_fetch_failed`。
- `.artifacts/gc-diag/`、`.artifacts/gc-diag2/`：临时诊断捕获原始调用链：FileObjectStore.put 的 `os.link` 抛 PermissionError，经 ObjectStoreError、CaptureWriteError 转为通用查询失败。诊断记录只含类型／文件／函数／行；未记录密码、SQL 参数或原件。诊断代码随后移除。
- 保持产品源码不变，在允许隔离对象库硬链接的执行环境运行原受管入口，`.artifacts/gc-r2/result.json` **39／39 通过**。没有修改对象存储、增加绕行或豁免测试门禁。

## 最终验证

| 验证 | 实际结果 | 私有回执与 SHA-256 |
| --- | --- | --- |
| CLI、许可、Safety Gate 三模块受管回归 | **40／40 通过**；833 输入稳定，资源关闭，非自检拒绝 0，真实 Provider 调用 0 | `.artifacts/gc-final/result.json`；`39df878a14433494ff3c7c65e65adfa33fdd3f635ae4aed4eff16b21ee939521` |
| 首轮真实 PG CLI | 5 场景通过，408 Python 输入稳定 | `.artifacts/postgres/pgverify-36513dc75cb64270b3837d08a496e606/report.json`；`77665825841684d2d573ee52d722a64fdcc3253ad8baddd7d7294dd380df4820` |
| 最终真实 PG CLI＋TLS | **6 场景通过**，408 Python 输入稳定 | `.artifacts/postgres/pgverify-13a03288a01e452ea9c05b92c823c8e5/report.json`；`38d2050175982be0470372113177630e9cc0450f7e8a74c92fcc2cead0f49e87` |

6 个 PG 场景逐项覆盖：

1. preview 不写台账／条款／审计；approve 可被 Reader 消费；restrict、withdraw 后 Reader 拒绝；旧批准 UUID 返回历史事件和当前 withdrawn，不恢复许可。
2. 改输入触发 preview_stale，旧 head 触发 revision_conflict；错误 DB／应用密码、非管理员均拒绝；认证后撤掉管理员角色，在事务内拒绝且无新增账本。
3. 缺 025 schema 拒绝；独立 SELECT-only 数据库角色不能锁定／更新管理账户，也不能改变账本。
4. 实际连接为 NullPool／READ COMMITTED／固定 search_path；锁竞争约 2 秒拒绝；pg_sleep 被 5 秒语句超时取消；后续命令可重新正常连接；pg_stat_activity 未留下 CLI 连接。
5. 两个真实独立连接用同一预览竞争提交，恰好一个批准、一个 revision_conflict。
6. 临时 CA／服务器证书下 verify-full 成功，pg_stat_ssl 确认 TLS；主机名不匹配及不受信 CA 均失败；恢复有效配置后成功。SCRAM／channel binding 使用真实 libpq 协商。

数据库为隔离 PG 18.3，非 superuser 应用角色；许可和材料均为合成。普通场景从实际 CLI main 调用，只模拟 TTY 检测与两次 getpass 输入；并发场景使用相同专用 engine 和共享 Store。不是操作系统终端隐藏输入的现场验收，也不是完整 HTTP／Native E2E。

## 资源与复跑

两轮集群都已停止，postmaster.pid 与 init-password.txt 均缺席；TLS server.key 已删除，临时 CA 私钥只在内存中使用并释放。独立绑定检查确认测试端口已释放。证书未导入系统信任库。私库、证书、公钥、日志与原回执留在 Git 忽略的 `.artifacts/`。

受管回归使用[实施计划](../../plans/2026-11-13-postgres-governance-cli.md)中的三模块命令，每次换新输出槽。真实 PG 可运行：

```text
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite external-reader -CliTls
```

标准命令运行整套 Reader 场景及新增 CLI 场景。本轮使用 `.artifacts/gc-pg2/verify.ps1`，只调整仓库定位和调用已安装 Python，显式选取新增 6 场景；没有把本轮结果称为整套 Reader 重跑。来源输入在各轮前后独立绑定，不与历史 41 场景或 58 项 core 合并成一轮全绿。

## 保留边界

远端真实部署、外部 CA 运维、真实终端、生产最小权限／IAM／租户／RLS、吞吐、灾备和法律权利均未验收。客户端证书／GSS 等认证方式当前明确不支持。失败响应不能证明事务未提交，未知结果必须按原 UUID 核对；本轮没有改变这一合同。后续应完善生产部署角色及运维验收，继续其他 V1 Gate。
