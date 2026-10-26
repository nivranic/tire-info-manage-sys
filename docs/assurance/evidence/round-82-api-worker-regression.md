# 第82轮：API/Worker 回归与精确修复

日期：2026-10-19，Asia/Hong_Kong。**正式 148 模块已终态：4063 主项中 4058 通过、5 失败，另 77 子测试通过；原全套红保留。四迁移测试及 runtime 测试/pin 已精确整合，严格 delta 为六文件变更/654 不变；五模块目标复验 89/89 通过。阶段分别记录，不声明最新源码全 148 绿色；机器封存以最终生成及 Root 复核为准。**完整 V1 未完成。

当前正式入口 `.artifacts/r82-f-916e8b2d45ac/result.json`，SHA256 `d572948ab8b290d6c1a0f2f8ac3a3069b38b6d2707833c2355c5bc6790c0ed4c`；七模块历史阶段入口 `.artifacts/r82-t-4a38d671c90e/result.json`。正常数据库、真实 Provider/receiver 未新启动。

[首代 PDF 可执行合同](../../plans/2026-10-19-official-vehicle-pdf-contract.md)已完成独立读者审，仍待实现；没有完成二进制捕获、迁移、Parser、下载或 Native 验收。许可仍待核，`provider_use/export=false`、`requires_source_verification` 不变。

## 实际结果分账

所有 `.artifacts` 路径相对于 `E:/Mix/project/tire-info-manage-sys`；本机证据不随普通 Git clone 自动移交。不同阶段不得相加为全量通过数。

| 阶段 | 显式证据根 | 实际结果及边界 |
| --- | --- | --- |
| 历史整合 | `.artifacts/r82-t-72e6a0d94bc1/` | 18 项通过、659 输入稳定；绑定当时工装，不是最终源码全套 |
| 第一次正式运行 | `.artifacts/r82-f-5d29c8e7b614/` | 收集 4063；中断前 call 1883 通过/9 失败，子测试 77 通过；GuardDenied/exit 4 中断，无最终 result |
| 原中断用例最终工装整合 | `.artifacts/r82-t-c04e6d82a913/` | 1 项通过，三阶段各 1；pytest 0、报告失败 0、659 稳定、资源关闭/R38 未变；raw exit 3 仅已知 IPv6 拒绝 1、其他 0 |
| 七模块统一验证 | `.artifacts/r82-t-4a38d671c90e/` | 收集/执行 81，81 通过，0 失败/跳过/未完成；660 稳定，runner/pytest 0、报告失败 0 |
| 正式 148 模块终态 | `.artifacts/r82-f-916e8b2d45ac/` | 4063=4058 通过/5 失败，0 跳过/未完成；77 子测试通过；pytest 1、raw runner 3，保留原红 |
| 精确修复后五模块 | `.artifacts/r82-t-389d12e5c7a4/` | 收集/执行 89，89 通过，0 失败/跳过/未完成；三阶段各 89，subtest 0；runner/pytest 0，660 稳定 |

七模块回执的 `target_module_manifest_count=148` 是完整目标清单长度，实际执行仅 7 模块。正式终态则实际收集/执行 148 模块、4063 唯一主 nodeid，setup/teardown 各 4063 通过，call 4058 通过/5 失败，subtest 77 通过。JUnit 同样记 4063、failures=5、errors/skipped=0；与子测试分开统计。

正式运行 `source-before.json == source-after.json`，660 输入完全一致，报告失败 0。护栏自检 12/12、11 次刻意拒绝，privacy 通过；非自检 raw 拒绝 1 为已知 urllib3 导入 IPv6 探测，其他意外拒绝 0。`classification.json` 保留 `raw_verdict_preserved`，绝不将五失败派生为全套通过。166 个受管子进程当前 live 0，metrics 活跃监听/保留端点 0，`resources_closed=true`，R38 固定只读备份前后一致；不扩大为任意 native 后代或 OS syscall 隔离证明。

正式显式 `--actual-dir` 为 `.artifacts/r82-regression-a8ad637b725f4f59bad7b2f4a44f4924/r76-fresh-b5c44f8aa2414cd8b602f8cfb0bf2f9e/`：七案在新私库通过实际 ASGI 捕获，未暗选旧 latest。`human_truth_status=pending_external_review`、`release_gate=inconclusive`、`wrong_merge_count=null`；不是外部真人 Golden、真实 Provider 或精确 SKU 验收。

## 正式五项失败与修复范围

以下完整列出该正式运行的五项 call 失败，类型如实保留安全 reporter 的 `Failure`，不改称 `AssertionError`；原失败正文与捕获内容未持久化。

| case | 安全节点 | 安全 source_file:line / type |
| --- | --- | --- |
| 1914 | `test_offline_migration::test_only_two_additive_tables_and_010_preserve_old_rows_and_schema` | `apps/api/tests/test_offline_migration.py:46` / `Failure` |
| 2207 | `test_parser_runtime::test_domain_dependency_change_invalidates_frozen_digest` | `apps/api/tire_api/parser_runtime.py:125` / `Failure` |
| 2612 | `test_query_fallback_migration49::test_three_additive_tables_and_011_preserve_every_predecessor_schema_and_row` | `apps/api/tests/test_query_fallback_migration49.py:55` / `Failure` |
| 2779 | `test_recall_discovery_migration::test_nine_additive_tables_preserve_all_old_schema_rows_and_cursors` | `apps/api/tests/test_recall_discovery_migration.py:101` / `Failure` |
| 3841 | `test_test_sku_links::test_019_additive_upgrade_preserves_all_predecessor_rows_and_repeats` | `apps/api/tests/test_test_sku_links.py:380` / `Failure` |

008/010/011 的旧断言只从 after 去掉 trigger、before 保留 current after_create trigger；019 把完整链后来新增的 021 trigger 当作 019 旧表漂移。四 fixture 都是 current shape 加 historical ledger。修复分别观察真实 008/010/011/019 INSERT 时点，严格核目标新增表/一个版本和全部旧 schema/行，再核独立固定最终 57 trigger；不截断生产 upgrade、不从 after 学 expected、不改 shared support 或产品。

008/010/011 原字节/草稿见 `.artifacts/r82-migration-followup-f5c77a6cd5e24eb4aeec9b12f8c3893a/`，独立审 `.artifacts/r82-migration-independent-dd3ec9cd0bb54b1e9eca1f55f1ab220d/REVIEW.md`；精确整合回执 `.artifacts/r82-migration-integrated-e2996d4cf2574c51b05f870debb60bfd/integration.json`。原 rollback、recall cursor/history/CHECK/FK/offset 和 PG 编译断言保留。

019 原字节/草稿 `.artifacts/r82-migration019-followup-a392126a2d314311a395dd8676462490/`，独立审 `.artifacts/r82-migration019-independent-3da1d01b5c754885aad31e30943d4441/REVIEW.md`；整合回执 `.artifacts/r82-migration019-integrated-0ee35e8e84cd4355908523bf6f69aad4/integration.json`。before 缺两目标表及六 trigger，因此只在真实 stage019 核 `device=True,candidate=False` 的 48 trigger；`assert_target_delta` 保全 before 原 42 trigger，最终仍固定 57。原 idempotence/FK/integrity/rollback/PG 断言全部保留。

Parser 精确草稿 `.artifacts/r82-runtime-digest-followup-5063183900294e02a7589ae9ed1477a7/`，独立审 `.artifacts/r82-runtime-digest-independent-d394596e15bf4dcb9aa2ac3b04239b7b/REVIEW.md`。仅将测试副本置于兄弟 `mutated_source` 并更新对应 ChildPolicy pin；原 domain 注释、digest 不等/旧 digest 拒绝及全部非目标 AST 保留。正式 safe 回执只记 `Failure`、runtime:125，没有保存具体 Bundle code。

事后只读观察原保留目录，见 `.artifacts/r82-runtime-digest-observation-cda5645b2c1441caadeb48b6d23096e3/observation.json`（SHA256 `7d401788f9742788776b4796237feca3f0b9a0d808bea219181969e1161cc1f7`）：原部署树/副本各 139 个，合计 278；138 个逐字相同，只有预期 domain 注释变更。未修改的 `_tree(parent)` 返回固定码 `parser_bundle_too_large`，`_tree(deployed)` 正常返回 139；总 4076363B/最大单文件 100827B 未触字节预算，原 278 文件前后未变、拒绝 0，无 pytest/DB/网络/子进程。**归因资格是事后保留目录观察加源码链，不是原 runner 当时记录的错误码或 pytest 重放。**没有放宽 `MAX_FILES=256`、执行预算或护栏。

正式终态后经 Root 授权才解除旧冻结并精确整合，所有 live=before SHA 先核。严格 delta `.artifacts/r82-regression-a8ad637b725f4f59bad7b2f4a44f4924/final-runtime-delta.json` 为 4712B、SHA256 `47dcf02775f7c689b7a784823faadd4f9df5b26e0cbcd6956b9587cacd6d6fe9`：660→660，恰四迁移测试、runtime 测试及 ChildPolicy pin 六文件变更，654 不变、无增删；五测试非目标 definition AST 不变，pin 仅一个 SHA 字面量替换，shared support/产品/guard 不变。最终输入快照为同根 `final-runtime-source.json`（119185B，SHA256 `aba65518dd09ed85de281db22e06fef96ed62ec57b471d4170fa29552f06f057`）。五模块已在显式短根完成目标复验；其 before/after 均与严格 delta 的最终 660 快照相等，原全套红不改，不改 `test_interest_migration.py`，不自动重复全套或宣称最新全 148 绿色。

五模块最终 `result.json` 为 21409B、SHA256 `5f6c60f802e5cdeb34b9b52fd88dd5ffa92a1b9e93a8644720d6b4da58a529d7`。实际目标恰为四迁移模块和 `test_parser_runtime.py`，89 唯一主项、setup/call/teardown 各 89 通过，0 skipped/incomplete/subtest，JUnit failures/errors/skipped 均 0；tool/runner/pytest 0、报告失败 0。660 输入首尾一致且等于 `final-runtime-source.json`；自检/隐私通过，非自检 raw/known/other 拒绝均 0。37 个受管子进程 live 0、metrics 0、`resources_closed=true`，R38 备份未变。该结果证明精确修复后的五模块回归，不把它与原正式 4058/5 或旧 81 相加为一次完整绿色全套。

## 第一次正式中断与原红保留

原根七份文件保持原字节；没有 `result`、最终 test-reports、source-after 或最终资源回执。安全 progress 为 setup 1893 通过、call 1883 通过/9 失败、teardown 1892 通过、subtest 77 通过；最后为第 1893 项对象存储用例 setup 通过。原 runner 没有保存 GuardDenied category/stack，不能给原根补造原因或终态。

外部 post-exit observer 对 659 项输入与原 before 完全一致，其资格是**进程退出后的外部观察**，不能替代原进程最终 receipt。后续未观察到匹配模板进程/归属监听，不据此声称原进程历史 reap=0 或所有 native 后代均已证明关闭。

诊断入口：`.artifacts/r82-regression-a8ad637b725f4f59bad7b2f4a44f4924/formal-diagnostic-31c08a5d7be4/` 中 `interrupted.json`、`observed-source-after.json`、`observed-source-verification.json`；残留观察另见 `.artifacts/r82-child-diag-3b6f9990551e40448d9fb7bfc6aca6fa/observation.json`。

九项原失败均保留，后续修复回执不覆盖旧红：

| 原 case | 模块与用例 |
| --- | --- |
| 118 | `test_ai_chat_provider::test_resolver_loopback_exception_matches_config_layer_promise` |
| 197 | `test_ai_stream_migration::test_only_two_new_tables_and_one_version_preserve_every_old_schema_and_row` |
| 349 | `test_auth_governance::test_cli_reset_password_is_the_local_recovery_path` |
| 784 | `test_device_ai_migration012::test_two_additive_tables_and_012_preserve_every_predecessor_schema_and_row` |
| 790 | `test_device_ai_migration013::test_013_adds_only_six_ledger_triggers_and_one_version_row` |
| 792 | `test_device_ai_migration013::test_013_ddl_and_version_rollback_together` |
| 795 | `test_device_ai_migration013::test_two_engines_initialize_the_same_pre013_file_concurrently_without_duplicate_versions` |
| 1565 | `test_interest_applicability_review::test_review_018_preserves_all_predecessor_rows_schema_and_does_not_backfill_or_repeat` |
| 1593 | `test_interest_governance_review::test_review_017_preserves_predecessor_schema_rows_and_has_no_notification_backfill` |

## 修复及其证据资格

**路径解析与报告。**对象存储用例全局 monkeypatch `Path.resolve`，旧 guard 因而将合法私根写误拒；有界前后复现根 `.artifacts/r82-resolve-f0a4708391744fd0b2a18318796a3712/`。guard 在导入时保存可信 resolver，并用于根、frame、FD/path containment 及 IPv6/metrics 来源识别；测试的全局 patch 仍有效，私根写允许，根外写仍拒绝且未生成文件。没有添加用例豁免或放宽私根。

该根 `fixed.json` 原 `passed=false` 保留：probe 错误要求总拒绝恰为 1，实际有一次刻意根外拒绝及一次已知 urllib3 IPv6 探测；另存严格分类，不覆写原红。该 probe 的固定 runner 副本是中间收口版本，不能冒称第一次正式运行的原 runner。最早相对 target 导致零收集的失败根 `.artifacts/r82-resolve-361c232eec6e4b2998a0f4d6fc762d96/` 同样保留。

最终 runner 同步使用可信 resolver，安全异常只记固定类型/category、阶段及最多 64 个安全 frame。报告写失败总计数及最多 16 个安全样本进入 raw/derived 失败门，保留实际 pytest exit；外层失败仅写安全 `runner-failure.json`，不将中断写成成功。未持久化原始失败正文、参数化 nodeid、stdout/stderr、argv/env 或秘密及其 hash。

**DNS。**Provider 原例仅替换当前 loop 的 `getaddrinfo` 为异步 loopback stub，保留原断言，新增快速路径不调用 DNS/总 mock DNS 一次的断言；不为测试开放真实 DNS。

**历史迁移测试。**新增 `historical_migration_support.py`，通过 SQLAlchemy `after_cursor_execute` 观察真实目标版本 INSERT，在同连接/活动事务中只读快照并在 finally 摘钩；重入标记先于内部读取设置。既不截断生产 upgrade，也不伪造未来版本或新增生产 cutoff；生产链仍完整到 023。

009/012/017/018 的历史阶段分别精确核新增表、原有完整 schema/行及一个真实版本；013 核六个 trigger 与一个版本。最终完整链另以独立固定 SQL 合同核 19 表/57 trigger，保留 owner/action/conflict predicate/RAISE reason，单引号 literal 的大小写与空格不规范化。未知 DDL/trigger 拒绝；原回滚/重建/并发/FK/幂等/行保全仍保留。fixture 如实标为 current shape 加 historical ledger，不当作精确旧库备份。

**CLI。**密码生成仍随机，仅改为等号形式传递 `--new-password`，ChildPolicy 收为精确七项模板并更新 pin。公共固定前导 `-` 探针中，分离形式 exit 2，等号形式 exit 0 且重启登录通过；入口 `.artifacts/r82-cli-02ac0f67dcbc/verification.json` 与 `delta-verification.json`。原 case349 的随机值不可恢复，前导 `-` 只能是原失败的候选原因，不能宣称已确证。

上述改动限工装和测试；R82 未修改生产 `db.py/migrations.py`。没有放宽 Parser 的 8 秒墙钟/5 秒 CPU 预算，也不将这些确定性问题归为机器负载。

## 绑定与独立审查范围

七模块历史阶段结果 `result.json` 为 20371B，SHA256 `a8b002780ab1ad02d08ff20da045e4342cf36cbc8837c48e8c08571eb2527b09`。完整输入绑定以各阶段 source manifests 为准；正式与目标 before/after 已分别核相等，六文件变更以严格 delta 单独绑定。

| 原正式与七模块关键输入（后续精确变更另核 delta） | SHA256 |
| --- | --- |
| `scripts/run_api_worker_regression.py`（42225B） | `1e869ed5e61976535550ca240a5e5173d7d6ba63a96ad27b6e99707a8e17a977` |
| `scripts/regression_guard.py`（26536B） | `23f34b2e58bd5fdc200e6c812df43632c96b1fff5d538ff307ef84cf9b592629` |
| `scripts/regression_children.py` | `6517a5986f73562d1dfcad34613536a7d222a49f7472c044ac313f0350ef98ce` |
| `apps/api/tests/historical_migration_support.py`（9691B） | `eb2647ae0dddf1bd45fd292521a9ff6a425cffb2ce69e8d1b6f3484fb284fa09` |

guard 与迁移 support/test 的作者自审不算独立审；迁移关键面另经 runner 作者和 backend 独立审查。runner 的安全报告/可信路径增量由未编写该 runner 的 reviewer 独立核读并结合 81 项回执检查。较早四工装/R38 独立审 `.artifacts/r82-review-20c96a7e53cf46e8b3d827c73aad8cba/` 明确排除 reviewer 自写 guard，不覆盖后来全部增量。

护栏覆盖 Python/JS API 与 audit 边界，**不是 OS sandbox 或 native syscall 保证**；不将受管模板进程退出扩大为任意 native 后代关闭证明。七模块结果没有真实 Provider/receiver 或正常数据库启动，也不是浏览器/原生设备/生产集成验收。

## PDF 合同与下一精确入口

合同 `docs/plans/2026-10-19-official-vehicle-pdf-contract.md` 为 44119B、SHA256 `accf4158542ca31b6b40eb5b06890e081603ca26bfc277725328089d59137e40`。作者回执 `.artifacts/r82-pdf-contract-ee90f18fddca4ae79053e1d0a8083180/verification-final-v3.json`；独立读者审 `.artifacts/r82-pdf-reader-03943576569540c2ac84acb8c8525a99/REVIEW.md`、`review.json`、`seal.json`。

合同明确纯 Parser 只核 vehicle/bytes/size/magic/SHA，可信 context 核 URL/MIME/source/purpose；server-only 六键 `payload.parse_provenance` 必须来自实际 pinned selection/receipt/sealed source，不能用当前映射 SHA 倒填旧 V2/审批。nullable 文本＋capture、历史复用与当前验证捕获、审批新在线一次消费、未知 SHA 拒绝、SQLite 重建/FK/逻辑引用/回滚、独立 023 expected、V2 下载及 Native online/offline 边界均为**待实现验收合同**。

六文件精确 delta 与五模块目标复验已完成；下一步仅收齐机器封存与 Root 复核，原正式全套红、第一次中断及全部旧红保留。PDF 后续按合同在单独切片实施；当前不重做 R81 原件发现/视觉/联网研究，不把合同封存当功能交付。

正常数据库、真实 Provider/receiver 本轮未新启动；未提交推送。EPREL 正式 schema/许可生命周期、真实专业精确 SKU/外部真人 Golden、完整专业性能 C/真实 Responses、生产 IAM/PG/TLS、六平台/WCAG 及完整 V1 各 Gate 继续未关。
