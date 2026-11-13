# ADR-2026-064：PostgreSQL 受归属与许可约束的外部读取

状态：已实现；真实 PostgreSQL 并发与外部读取验收通过，生产部署与吞吐待验。结果见[验收记录](../evidence/postgres-owned-reader-2026-11-13.md)。

## 问题与证据

原规格指定 PostgreSQL 为主数据库。现有轮胎单事实、轮胎分页、Safety Gate 外部读取仅支持 SQLite；普通 PG 业务验收不能替代这些读取器的验收。

2026-11-13 在独立 PostgreSQL 18.3、非 superuser 应用角色上复现：Reader 返回 `reader_backend_unsupported`，分页 schema 字节预算 SQL 返回 SQLSTATE `42704`（PG 无 BLOB 类型），查询 actor 捕获直接返回空。原始回执位于 `.artifacts/postgres/pgverify-5de720c6ba23440e80538cb1d854611f/report.json`，实例已关闭。空表长度查询没有失败，不能据此认定文本转 bytea 的字节计量正确。

## 决策

1. 共用现有 Reader、许可链、归属收据与投影；保持未知数据库拒绝，不复制整套 PG Reader。
2. PG Reader 新建 READ COMMITTED 事务，先取现有 ingestion advisory 排他锁，再按固定顺序对读取依赖表取 SHARE 锁；最后才读取时钟、凭据、归属、许可、预算与内容。锁表名单在代码中固定，不接收请求 SQL 标识。
3. SHARE 阻止未遵守 advisory 协议的直接 DML、DDL 和 TRUNCATE。全部锁取得后的首次读取定义本次操作顺序；此前已提交的撤销必须可见，此后撤销等待当前投影结束。预检与物化不能来自不同内容版本。
4. 不在 REPEATABLE READ 中先等待 advisory 锁：等待语句可能提前取得撤销前快照。单靠协作锁也不充分，因为账户删除等既有写路径未全部使用该锁。
5. SHARE 无法用于 PG READ ONLY 事务，因此使用内部 read-write 事务和既有只允许 SELECT 的 Reader Session。它约束可信 helper 的意外写入，不声称抵御恶意 Python 或数据库管理员。
6. Reader 与归属写入的 PG 边界使用事务局部 `lock_timeout=2s`、`statement_timeout=5s`、`idle_in_transaction_session_timeout=15s`。超时回滚、返回固定错误，不重试、不降级读取；连接归还后设置不得污染池。总请求耗时仍需性能验收，单条 SQL 上限不代表端到端 SLO。
7. 归属创建先重新开启受管事务，再获取同一 advisory 锁及会话／账户 SHARE 锁，重验最初 actor；QueryRun、审计、收据仍原子写入。不追认历史匿名记录，不随会话重新登录迁移归属。
8. 长度预检对 PG 文本／JSON 使用 `octet_length(convert_to(text, 'UTF8'))`，二进制使用 `octet_length`。JSON 数组长度以类型 CASE 保护，保留逐字段、累计字节、行数、节点、深度与最终响应限制。

## 代价与失败模式

固定表 SHARE 锁会短暂阻塞相关表全部写入，advisory 排他锁也使 Reader 串行；这是当前 ingestion 串行模型上的正确性基线，不代表已满足生产吞吐。后续优化必须保留撤销顺序及物化一致性并重新压测。

与不协作写入可能出现锁等待或死锁，按 PostgreSQL 错误回滚并拒绝，禁止返回部分投影。数据库不可用、缺表、锁权限不足与错误 schema 都不能静默退回 SQLite。增加读取依赖模型时必须同时更新固定表集合并补并发测试。

## 必须验收

- 非 superuser 真 PG：轮胎单事实、分页、Safety Gate 分页、正常归属三元组。
- Key／许可／账户撤销在读取前后两种顺序；直接写入与预算预检之间不能改变内容。
- 外层事务独占完成，helper 不能写入或换事务；SQL 超时、锁超时及池设置恢复。
- Unicode、反斜杠、二进制、非数组 JSON、大 JSON／文本在物化前的预算拒绝。
- 错误 schema、跨账户、旧匿名查询、会话重绑、actor 失效与创建失败的原子性。
- 相关 SQLite 回归不变；独立 PG 实例关闭、随机凭据文件清除；不得连接未知服务。

回滚：回退本轮代码后 PG 外部读取恢复明确拒绝；保留已生成的不可变归属收据，无 schema 迁移和历史追认。
