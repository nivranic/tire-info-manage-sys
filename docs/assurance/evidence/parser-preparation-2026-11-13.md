# Parser 准备阶段与 PostgreSQL 综合验收（2026-11-13）

基线 `d7696ca5c57b9dca6d64a8a448d9fba0a6cc786a`。本轮继续处理上一阶段综合 PG 验收中的间歇失败；外部 Reader 的 41 场景与 SQLite 248 项回执仍独立保留。

## 已定位的失败

未修改生产代码，使用私有观察脚本重跑完整 PG 验收，在第 35 个检查（NHTSA Parser A/B/A）捕获到 `parser_timeout`：

- 8 秒预算，实际监督回执 8,140 ms；子进程退出码 125、`reaped=true`、stdout／stderr 均为 0 字节。
- 封存包核对约 312 ms，复制约 4,344 ms；复制包含新执行目录文件树校验约 3,250 ms。该校验后续通常约 0.2 秒。
- 当轮记录 18 次真实 Parser 子进程执行，1 次失败，18 个子进程均已回收；406 输入稳定，集群已关闭。
- 回执 `.artifacts/postgres/pgverify-bb800eee9efd4fa09ef78b099dfcfe69/report.json`，SHA256 `da213426664e22cdd019fa489ff813f5f26069f42cb7bb91ca4bd9e9607f9245`；细分事件 `.artifacts/pg-core-observed-r1/parser-events.jsonl`。

这次证据确认了执行超时及准备阶段的显著开销，不证明具体杀毒软件、磁盘或操作系统组件导致延迟；没有据此修改系统安全软件、代理或超时配置。

## 对照与修改

在隔离临时目录交替进行 3 组原实现／候选实现对照，均为相同 188 个源码文件，文件字节与清单一致。完整复制的 `Path.stat` 调用计数从 12,599 降至 5,355（候选另外使用打开句柄的 `fstat`）；耗时中位数从 4,620.756 ms 降至 4,018.659 ms。原始 6 个样本见 `.artifacts/parser-tree-benchmark/result.json`，SHA256 `74182fdda003f58105ddb718d725bf800d2141097fa3b4dedad1059bce0897a9`。这是本机工程对照，不是 P95／生产 SLA 或六平台性能验收。

`parser_bundles.py` 现在保留一次完整路径检查返回的叶节点元数据，供文件类型、硬链接数与大小判断复用，减少重复遍历祖先路径。每个条目仍检查所有祖先及叶节点的 symlink／Windows reparse 标志，不跨遍历或请求缓存元数据。读取前用实际打开的文件句柄核对常规文件、单链接及 device／inode 身份，拒绝检查后被替换的对象。

文件数／单文件／总字节预算、复制前后源清单一致性、执行副本逐字节清单、持久化 fsync、8 秒预算、并发数 2、Windows Job 和子进程回收机制保持原合同。

## 反例与验证

新增 10 个文件树边界用例：实际 NTFS 硬链接、打开瞬间增加硬链接、相同字节但不同 inode 替换、祖先 symlink／reparse 分支、源目录排除规则、单文件／总大小／数量上限及复制期间源文件变化。祖先重定向分支使用受控元数据模拟，不冒充真实 junction 的现场验证。

旧实现 8／10 通过，打开瞬间替换的两个反例未拒绝；原始失败 `.artifacts/parser-tree-red/result.json`，SHA256 `57babe4e234090a89cf9b35b25b21524f8414cda4a6660917e743d44878adab5`。

修正后 4 模块 **84／84 通过**，无跳过；832 输入稳定、资源关闭、非自检意外拒绝 0、真实 Provider／接收端调用 0。覆盖文件树专项、运行时预算／取消／Windows Job、篡改包拒绝、旧包执行和运行环境合同。回执 `.artifacts/parser-tree-green/result.json`，SHA256 `1569a5cceec1d828a2eaa09dba782aade2201fbf4a3089dedffcf77197e30633`。

常规 `scripts/postgres_acceptance.py` 已增加固定 Parser 失败回执收集：保留异常码、执行身份、PID／退出／回收、字节数和限制，不记录原文、stderr、环境或任意异常字符串；原异常继续抛出，不增加重试。后续 agent 可从常规回执定位同类失败，无需依赖本机私有观察脚本。

## 综合回归仍未通过

优化后完整 PG 重跑在 Hankook A/B/A 的回滚校验再次遇到 `parser_timeout`，此前 32 个检查通过。10 次 Parser 观测中 1 次失败，407 输入稳定。失败回执 8,421 ms，副本复制 4,031 ms、其中新目录校验 3,203 ms；子进程退出 125、已回收、stdout／stderr 为空。回执 `.artifacts/postgres/pgverify-28f1650dd8314f44a7a9e953c11ebc39/report.json`，SHA256 `7c373718ac2e927923a355049eb568e8aea4eebeda79f13687d19090e9bd10c9`。不能声称本轮已经修复全部间歇超时。

进一步在私有 Bootstrap 副本加入固定阶段标记，6 次独立解析均通过，入口标记至 `response_ready` 约 1.05–1.75 秒；该范围不含进程创建和标记前导入，不能据此排除启动或调度延迟。回执 `.artifacts/parser-child-phases-r2/result.json`，SHA256 `fb25aba9cbbfcb58fbc633a00c0f4560200b1c0815a5360f6e4613f720832c5b`。初版私有观测脚本因插入缩进错误造成 6 次 `parser_crashed`，只属于观测装配失败；原样保留，后续增加 AST 校验。生产 Bootstrap 没有加入这些标记。

## 独立完整数据恢复

综合链路未走到备份阶段，因此另取已关闭的受控失败验收快照制作全新副本，独立执行 `pg_dump`／`pg_restore`，没有把综合流程改成忽略 Parser 失败。原快照 3,738 个文件的哈希保持不变。

副本只在 loopback 上初始化随机凭据，随后验证 SCRAM 和错误口令拒绝；导出、导入和业务读取使用非 superuser 应用角色。恢复后共 **167 张实际 PostgreSQL 表、963 行**，含 **19 条查询归属收据、10 份原件、4 份报告导出、3 个 Parser 包**。逐表行哈希、列、主键、外键、唯一约束保持一致；CHECK 的 13 处等价类型表达差异见下文。应用初始化保持恢复数据，正常 HTTP 读取 3 份原始证据并核对哈希；4 份报告由原归属会话读取并逐字节校验，管理员跨归属访问仍返回 404。所有注册 Parser 包从复制的归档验证，不依赖原目录读取。

最终 **10／10 检查通过**：`.artifacts/postgres/pgverify-71b8d3e107eb4286a8dc79b732b328a3/report.json`，SHA256 `2e1eeaee8763223f0d52758f04f7b12a55c17caf253e10258cf3a0d20597c1d3`。逻辑归档 SHA256 `f03109a38e56996b0747e26465348239903db0a3e6fedd466f6d959984c6a508`。本轮 7 个 PG 实例已关闭，PID／初始化口令文件均消失、55487 无监听。

恢复核验的前序失败全部保留，均未改变生产数据或权限：

| 私有 slot | 观察与处理 |
| --- | --- |
| `pgverify-a89c4b5f8bcc4fe5872264c33bc552fe` | 错把其他 SQLite 验收的表数下限套到 PG；改为发现实际表清单并全量比较，而非假定跨方言物理表数相同。 |
| `pgverify-9f76ad2a527e4242bc4131c7de884822` | 导出／导入成功，新增的完整结构比较发现差异。 |
| `pgverify-fdcbd40929c2448fa86a3d3a157d7538` | 保存原始前后指纹，确认仅 13 处 CHECK 的常量数组转换表达不同，行、列、键及其他约束一致。 |
| `pgverify-492b04c3ad4548c1adf2f1a7780e2da6` | 数据和原件恢复通过；管理员读取匿名会话报告被正确拒绝，验收改用原归属会话，并额外要求跨归属拒绝。 |

PG 18 将 `ARRAY['x'::character varying]::text[]` 反解析为 `ARRAY['x'::character varying::text]`。仅对这种明确的同类型常量数组转换进行等价比较，不移除任意转换或忽略 CHECK；原始两份结构指纹仍保留。离线比较回执 `.artifacts/pg-backup-isolated-r3/semantic-comparison.json`，SHA256 `a2fc8ff2205edd308889d04208310bf9da50bb1d125cd7276f022493300b0e59`。

这是该受控应用数据快照的恢复证据，不等于完整综合流程通过、生产角色／ACL／RLS 恢复、远程对象存储灾备或 RTO／RPO 验收。其他未到达的向量、查询筛选、身份并发等综合阶段也不能补记为通过。

## 复跑与接续

```sh
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root .artifacts/parser-tree-recheck-001 --targets apps/api/tests/test_parser_tree.py apps/api/tests/test_parser_runtime.py apps/api/tests/test_parser_bundles.py apps/api/tests/test_parser_runtime_environment.py
```

完整 PG 入口仍为 `pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin '<PostgreSQL bin directory>' -Port 55487 -Suite core`。独立恢复私槽未纳入 Git，新 clone 必须重建受控数据并复验。

下一步补进程创建、首次入口、输入写完与管道 EOF 的统一时间线，继续定位混合流程超时；已有准备开销优化不能替代这一工作。完整 V1、生产部署／吞吐、实际 Native、自然长周期监控与真实模型质量继续开放。
