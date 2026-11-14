# PostgreSQL 运行角色阶段验收

日期为 2026-11-14，基线为 `08e40ffd6c8568fb3a240f165e3bbffe3e514185`。完整 V1 持续进行，完整运行角色业务验收尚未完成。接手范围见[交接卡](../../AGENT-HANDOFF-2026-11-14.md)。

## 本轮变更

运行角色策略固定当前 166 张模型表，授予读取、按实际可变列 UPDATE、有限 DELETE，并可选处理 pgvector 派生表。两张许可治理表只授予读取，审批与许可证据追加由原治理操作员执行。SQL plan 以事务、前后有效 ACL 检查及固定标识符生成，角色检查通过只读事务执行。

此前实际 SHARE 表锁被逐列权限拒绝。本轮由迁移账户安装两个固定无参数 SECURITY DEFINER 锁函数，public 限定表名、固定 search_path、撤去 PUBLIC EXECUTE。角色检查核对函数正文、签名、语言、返回值、definer、volatility、parallel、leakproof 与配置，并拒绝其他可执行 definer 和 grant option。函数定义参与 @3 schema 合同，升级须重新生成并批准空参考合同。

新增正式 `runtime-role` 综合验收模式，维护步骤使用拥有者，API／Worker 业务使用运行账户与 verify 合同。原拥有者模式保留。历史保护反例分别断言拥有者 P0001 和运行角色 42501。

## 最终结果

各批分别留证，以下检查数量对应各自的执行范围。

| 范围 | 结果 | 本机回执 | SHA-256 |
| --- | --- | --- | --- |
| 七模块受管回归 | 124／124 通过，841 输入稳定、资源关闭、非自检拒绝 0 | `.artifacts/runtime-role-reg-complete/result.json` | `303a8be2d8d26dadc6288477582d59221da70ef17fefeb835682de71f773513c` |
| 真实 PG／TLS 运行合同与 DML 拒绝 | 31 项通过，841 输入稳定 | `.artifacts/postgres/pgverify-733dfca8a99e40669b228b6b4971141b/report.json` | `73ac169e58351fced82f4ddfc46ae552ef0237260d984da0d1d6e00a76feb3b1` |
| 真实 PG 拥有者核心兼容 | 58 项通过，166 张模型表及备份恢复核对通过 | `.artifacts/postgres/pgverify-a30b7512741a4d0c8103e3e7a07a9a47/report.json` | `c25840bebadf25217c6c8dc2f3451ae00c91f2e12ff58fdd511f4c59078dff79` |
| 真实 PG 运行角色综合业务 | 前 37 项通过，随后在 HNSW 权限入口失败 | `.artifacts/postgres/pgverify-6254c39ec2724fd684db7c30b3083f76/report.json` | `e9cba09866785cde7439b5d72069904789703a9be906388110f7d66e73226bf1` |
| 原治理操作员 PG／TLS 兼容 | 9 场景通过，414 Python 输入稳定 | `.artifacts/postgres/pgverify-173f227a0a334a0c99f73884cbedf51c/report.json` | `c2b51b1a9ae4538b5c8c899114d06dd2cdc5ac382ee58f5d4970ace554344797` |

受管回归覆盖许可 CLI、旧许可治理、Safety Gate 许可、启动、正文向量、结构化向量和 Worker。setup／call／teardown 均通过，跳过及不完整均为 0。收尾逐文件核对最终 841 个输入。

31 项合同验收使用实际生成的运行角色 GRANT。API 正常查询与证据读取、Worker 单次入口及可选 vector 已通过，启动 SQL 仅 SELECT／SET。新增八条越权 DML 均返回 42501，覆盖证据 UPDATE／DELETE、TRUNCATE、审计删除、账户 ID 改写、版本表写入及两张治理表追加。原五条 DDL 拒绝及结构篡改反例继续通过。

58 项拥有者核心兼容包含正常查询、并发、车型、车库、比较、偏好、调度、隔离审批、TestEvent、AI、报告、FTS、PDF、Parser 发布回滚、召回、向量和备份恢复，Parser 失败回执为空。core 与 runtime 两份报告保存流程结果，随后仅 Reader 验收脚本补装锁函数；其间195个包内Python源文件保持，最终受管回归绑定全部交付输入。

9 场景复核非拥有者生命周期、20 条越权 SQL 拒绝、额外 ACL、成员与目标、目录权限、部分 GRANT 回滚、Safety Gate、TLS 及旧 CLI／Reader 正常消费。测试库通过正式安装器安装新锁函数。

## 尚未解决的正常入口失败

步骤 `original_text_embedding_pgvector_permissions_and_accounting` 在 `test_text_embeddings.py` 的正常 build 请求失败。服务调用 `embedding_api.py` 中的 `dense.ensure_hnsw()`，实际 PG 日志为以下错误与语句形状。

```text
ERROR: must be owner of table embedding_vectors
CREATE INDEX IF NOT EXISTS ix_embedding_hnsw_<space-prefix>
ON embedding_vectors USING hnsw ((embedding::vector(<dimensions>)) vector_cosine_ops)
WHERE model_space = '<space>' AND dimensions = <dimensions>
```

运行角色缺少表拥有权，完整运行角色业务验收因此保持未完成。还需要设计拥有者索引维护与模型空间、空参考合同、版本发布和恢复的衔接。动态新增索引会改变当前 schema 合同比较结果，接手时同时覆盖。

当前策略的完整权限反例、部分授权回滚、实际终端、远端部署、生产 IAM／RLS、吞吐与灾备继续待验。本轮共享审计的旧治理角色回归及已列出的运行角色拒绝检查各自留证。

## 原始失败与修正

- `.artifacts/runtime-role-reg-final/` 最初 96 项中94项通过，PDF 原件与召回 Worker 两项失败。独立项目内硬链接探针取得 PermissionError、WinError 5。保持受管入口及代码，在允许项目内硬链接的执行环境复跑，`.artifacts/runtime-role-reg-authorized/` 取得96项通过。最终补齐全部相关模块后的124项另行留证。
- `.artifacts/postgres/pgverify-574ffb529d304f6ba21a783d5c82bf80/` 取得31项通过，属于补齐Reader验收装配前的输入，最终31项使用上表新批。
- 原治理兼容批 `.artifacts/postgres/pgverify-8bd2e33ed80a4668aeddfe110757ff6b/` 的9场景均失败。日志明确为 `function public.tire_lock_external_owner() does not exist`。测试显式安装服务表，漏掉新锁函数。已在PG测试库拥有者装配中调用正式安装器，原9场景复跑通过。
- 两次治理wrapper在建库前由 TcpListener.Start 返回访问拒绝。保留原启动错误，后续使用新分配端口完成验收。已观察到旧端口可单独bind，原访问拒绝的完整OS原因继续保持未确认。
- 运行角色前期私有综合批的导入遮蔽、历史保护预期P0001／实得42501，以及最新HNSW失败分别保留。正式runtime-role入口已整理到Git，后续直接通过该入口复现。

## 复跑与资源

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_external_fact_governance_cli.py apps/api/tests/test_external_fact_governance.py apps/api/tests/test_safety_gate_external_governance.py apps/api/tests/test_schema_startup.py apps/api/tests/test_text_embeddings.py apps/api/tests/test_embeddings.py apps/worker/test_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-schema -CliTls
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite core
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-role
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite external-reader -CliTls
```

标准 external-reader 命令运行完整套件。本轮私有wrapper仅调整仓库定位、使用已安装Python，并显式选择上述9项治理场景。其他三种套件使用完整正式入口。PowerShell使用7，受测源码在执行期间保持稳定。

六个本轮隔离集群均已停止，逐项确认postmaster.pid、初始化密码和TLS私钥缺席，六个自用端口可重新bind，回执为 `.artifacts/runtime-role-delivery/resources.json`。原始材料、回执、私库和证书保持Git忽略。

本轮采用合成输入、ASGI TestClient及隔离PG18.3，未调用真实OpenAI或Google。真实模型、设备、生产外部端点及完整V1仍待对应验收。原规格与历史封存尾文已核对。
