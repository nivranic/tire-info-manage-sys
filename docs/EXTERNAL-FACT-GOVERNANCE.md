# 外部结构化事实许可治理（G1b）

本切片提供本机管理员使用的许可台账和独立 CLI：保存小型条款字节、审批/限制/撤回历史、真实业务观察绑定及同事务审计。不提供外部事实 HTTP 接口，不执行采集、Parser、Provider、导出或 fallback，也不改变材料权限。G2 的字段投影、账户可见性和事实正确性仍需单独实现、审核和验收。

管理员登录、声明文件、摘要和 G1a 的 `applicable` 只说明工程条件符合约定，不能证明真实法律授权。没有真实权利材料时，只能使用合成测试数据，不得种入真实 `approved`。

## 数据与信任边界

- `external_fact_license_evidence`：UTF-8 条款/声明原字节，1–262144 字节，SHA-256 去重；不能存 NUL。不作为文件上传或任意对象归档通道。
- `external_fact_grant_revisions`：完整 G1a 修订、实际账户 ID/用户名快照、原因、预览摘要、观察回执、UUID 幂等和审计映射。密码、密码 hash、输入文件路径不进入新增记录。
- SQLite 两表均为 `WITHOUT ROWID`，以原生触发器禁止 UPDATE/DELETE/冲突替换；PostgreSQL 定义原生 UPDATE/DELETE/TRUNCATE 防护。ORM 另有追加保护。数据库所有者、管理员直接 DDL、文件替换及不受控恢复不在此信任边界内。
- 没有可变 head 表。当前策略由受控库中的完整连续修订链、审计镜像和当前条款字节派生；损坏固定拒绝，不回退到旧批准或备份。`AuditEvent` 是同事务镜像，修订台账是权威审批历史。
- SQLite 使用新连接的 `BEGIN IMMEDIATE`；PostgreSQL 使用事务 advisory lock，并锁定复查的管理员账户行。PG DDL 编译与真实 PostgreSQL 事务验证是两项不同证据。

仅既有真实 `User.is_admin` 账户可管理。CLI 通过 TTY/getpass 读取密码并调用现有密码校验，事务内再次核角色与凭证版本；没有密码参数、环境变量密码、默认数据库或 actor-ID 认证后门。这是受控工作站工具，不是生产 IAM。

## 显式私库初始化

在已安装 API 依赖的受支持 Python 环境中，从 `apps/api` 运行模块。本文命令只用于已经由操作者确定的独立私库；示例路径和账户均为占位，不代表已执行。

普通 `current/preview/approve/restrict/withdraw` 命令只打开显式绝对路径的既有 SQLite 文件，要求已有 `025_external_fact_governance`，不会自动初始化、升级或创建新库。

只有明确运行下列命令才安装 025：

```powershell
python -m tire_api.external_fact_governance_cli init-private --private-database 'E:/private/rehearsal.sqlite' --username 'admin' --backup-file 'E:/private/rehearsal-before-025.sqlite' --offline-confirmed
```

操作者须先停止该私库全部写入者。入口复查管理员、024 版本与真实当前 024 结构，再以 SQLite backup API 写入全新的备份路径；两连接显式关闭，以固定 chunk 计算备份 SHA-256。随后在新事务再次复查账户/结构，只增加两表、保护和 025 版本。备份路径不可覆盖既有文件；备份完成后安装失败会保留备份并回滚本次事务。若备份本身中断，保留的文件不能视为有效备份。此备份不覆盖 object/bundle 等外部资产，也不代表正常库升级验收。

## 请求合同

JSON 须为 UTF-8，文件最多 1 MiB；重复键、NaN/Infinity、未知字段均拒绝。条款文件按原字节读取。不要在原因或条款中放入口令、token、内部地址等无关秘密。

首条 approve，以及从既有 grant 重新 approve，使用完整请求：

```json
{
  "schema": "external-fact-governance-request@1",
  "action": "approve",
  "grant_id": "synthetic-grant-1",
  "reason": "Synthetic engineering rehearsal only",
  "source_id": "fixture-source",
  "coverage": {
    "observations": [{
      "snapshot_id": "existing-synthetic-snapshot",
      "raw_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "parser_version": "fixture@1"
    }],
    "field_keys": ["facts.weight_kg"]
  },
  "rights": {"holder": "Synthetic holder", "basis": "Synthetic fixture basis"},
  "validity": {"not_before": "2026-10-21T00:00:00Z", "not_after": null},
  "license_reference": "https://example.org/license",
  "rights_reviewed": true
}
```

其中观察必须已经真实存在于所选私库：source/hash/parser 精确匹配，`Snapshot.body` UTF-8 摘要一致，并且存在 accepted Verification→QueryRun 回执且 query 摘要、Parser identity 一致。示例中的假 hash 无法通过真实绑定。此处核的是现有文本 body 的 UTF-8 摘要，不代表原始 HTTP 字节摘要。最多 256 个观察，重新核验 body 的总字节量最多 32 MiB；记录最多 128 KiB、整链最多 32 MiB，均不截断放行。

`license_reference` 仅是审查元数据，不联网打开；要求无凭证、query、fragment 的公开域名 HTTPS 地址。reviewer、reviewed_at、revision、previous_digest、state 和 digest 全部由服务生成，客户端不得传入。`rights_reviewed: true` 记录操作者明确审查意图，不能替代其对权利人、用途和附加义务的实际核实。

首条 `restrict` 使用同样完整请求和条款；已有 grant 的 `restrict/withdraw` 只能使用：

```json
{"schema":"external-fact-governance-request@1","action":"withdraw","grant_id":"synthetic-grant-1","reason":"Stop synthetic permission"}
```

停止操作克隆既有覆盖、rights、有效期与绑定，只改变状态和审查记录，不需要联网、重验全部业务 body 或处于当前有效期。不存在的 grant 不能 withdraw。withdrawn 是同 grant 的终态；新独立许可须用新 grant 并完整审查。相同内容与相同原因的再次提交拒绝 `no_changes`；明确不同的完整复核原因可形成新 approve 修订。

## 预览、提交与重放

```powershell
python -m tire_api.external_fact_governance_cli preview --private-database 'E:/private/rehearsal.sqlite' --username 'admin' --request-file 'E:/private/request.json' --terms-file 'E:/private/terms.txt'
```

预览不插入条款、台账、审计或登录 session，不创造权限。它返回当前 revision/head、`fingerprint` 及拟议状态。提交时必须带上该次预览结果及规范 UUID：

```powershell
python -m tire_api.external_fact_governance_cli approve --private-database 'E:/private/rehearsal.sqlite' --username 'admin' --request-file 'E:/private/request.json' --terms-file 'E:/private/terms.txt' --expected-revision 0 --expected-head null --expected-preview-fingerprint '<preview fingerprint>' --idempotency-key '<canonical UUID>'
```

`restrict/withdraw` 提交流程相同，已有 grant 不传 terms-file。服务锁内重算绑定和预览摘要；当前 head 改变返回 `revision_conflict`，输入/绑定改变返回 `preview_stale`。批准还须在提交时符合 G1a 当前生效窗口；限制和撤回没有这项要求。

同账户+同 UUID+相同完整提交输入返回既有历史事件；不同输入返回 `idempotency_conflict`。成功响应同时返回当前状态/head。旧 approve 的 UUID 在撤回后重放仍显示当前 withdrawn，不会重新批准。最多 256 修订，第 256 条保留给 withdraw；非 withdraw 最多写至 255。

```powershell
python -m tire_api.external_fact_governance_cli current --private-database 'E:/private/rehearsal.sqlite' --username 'admin' --grant-id 'synthetic-grant-1'
```

current 返回当前 state/head，以及覆盖范围内的 G1a `applicability/applicability_reason`。过期记录仍保留 approved 历史状态，但显示 not_applicable；任何适用性结果都不能直接作为 G2 事实放行。

未来受控事实投影须在 `GovernanceStore.current_policy_transaction(grant_id)` 自有的新事务和锁内完成，不能接受客户端 head/链，也不能缓存策略跨请求。该上下文只提供经验证的当前策略，不执行事实查询或建立法律真实性。

## 验证范围

独立 unittest 模块为 `test_external_fact_governance.py` 和 `test_external_fact_governance_cli.py`。它们只创建 `.artifacts/external-fact-governance-test-runs/<fresh UUID>/` 下的合成私库，覆盖角色复查、预览不写、绑定拒绝、竞争提交、撤回/重放、审计损坏、原子回滚、原生 SQL 防护、容量保留和显式私库初始化/连接关闭。

测试代码存在不等于已通过。实际结果、受支持运行时、限制入口与 receipt 由独立验收记录给出；不得把合成 SQLite、Mock 输入或 PG DDL 编译称为真实法律授权、正常数据库升级、真实 PG 并发、G2 或端到端产品验收。
