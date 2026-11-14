# PostgreSQL HNSW维护与@4运行合同验收

日期为2026-11-14，基线为 `4425509b33e2e5c45896684f0b30e834fc1ef976`。本轮解决运行角色动态HNSW DDL的拥有权失败，完整V1继续进行。操作见[HNSW维护说明](../../POSTGRES-VECTOR-INDEXES.md)。

## 实现与正常入口

新增 `postgres_vector_indexes.py`，显式清单仅包含完整模型空间和维度，最多32项，拒绝非法维度、重复、额外字段和截断索引名碰撞。空参考生成器接受同一清单创建HNSW，@4保存完整声明并核对catalog对应关系。旧合同需从受控空参考库重新生成和批准。

拥有者CLI复用隐藏密码、明确目标、TLS／SCRAM及固定超时。维护事务核对拥有权、声明、完整前驱结构，仅补齐清单声明且批准合同期待的缺失索引，完整后检查通过才提交。错误定义和额外漂移拒绝，部分DDL在失败时回滚。已有正确索引幂等。

Database把verify核对后的声明与目录传给Session。正常计划和构建在外发及预算预留前检查完整空间、维度、实际索引和有效状态，构建后再次只读核对。运行账户的DDL权限继续由原策略拒绝，默认migrate保留原本地建索引流程。过滤pgvector cosine与RRF逻辑沿用。

## 最终结果

| 范围 | 实际结果 | 回执及SHA-256 |
| --- | --- | --- |
| 最终@4七模块受管回归 | 141／141通过，842输入稳定、资源关闭、非自检拒绝0 | `.artifacts/vector-index-reg-r2/result.json`，`33f94a098165aaf661397db051740215c4ebc930b9b876dc97f8d15bcabe26f5` |
| @4真实PG／TLS合同及维护 | 36项通过，842输入稳定 | `.artifacts/postgres/pgverify-d5f62f56375747a68933acb8b4ef5391/report.json`，`dcd678ab43e0ffcb8beb90dc25703b7ee1e1bf3af5fa1c5da4e12eb3384d63e8` |
| @4完整运行角色正常业务及恢复 | 59项通过，Parser失败回执为空 | `.artifacts/postgres/pgverify-cc22ab87470f472685421485fd573b54/report.json`，`3bcdc774e6f789dbae932b6a101f80d48202a6fcec5d7ea980b86b3ce817518f` |

受管回归覆盖启动、正文向量、结构化向量、许可CLI、旧治理、Safety Gate治理及Worker。setup／call／teardown全部通过，跳过及不完整为0，收尾逐文件核对842输入。

36项专项覆盖空参考、实际运行角色权限、正常API与Worker、结构反例、声明索引、拥有者CLI幂等、两个CREATE INDEX执行后的后检查回滚、错误现存定义拒绝、运行时SELECT检查，以及运行账户维护和CREATE INDEX拒绝。

59项流程使用原正式 `--runtime-role` 入口，覆盖查询、并发、车型、车库、比较、偏好、监控调度、隔离审批、TestEvent、AI账本、报告、FTS／PDF、Parser发布回滚、召回、实际pgvector、数据库与原件／报告／Parser备份恢复，以及恢复后正常消费。维护步骤由拥有者执行，业务继续使用审查过的运行DML策略。

最终综合批使用私有wrapper和轻量计时观察器。wrapper仅调整仓库定位、使用已安装Python；观察器包装原Parser入口和阶段函数记录时间，保留原数据、返回值、异常、8秒期限及全部校验。48次Parser运行全部通过，最大观测耗时约3.844秒，原始阶段记录为 `.artifacts/vector-index-maintenance/runtime-parser-phases.json`。此结果对应该隔离执行环境。

## 原始失败与诊断

- 最初共享运行角色批在动态HNSW处取得拥有权拒绝，原回执见[此前阶段](postgres-runtime-role-2026-11-14.md)。本轮通过显式拥有者维护和verify只读检查处理该依赖。
- `pgverify-2cb988912180446e92af19d80f34dc98` 前29项通过，新的拥有者测试装配在pg_catalog优先查询路径下执行未限定CREATE TABLE，被拒绝。已在该维护装配明确使用public优先路径，后续36项通过。
- 第一轮候选仍使用@3，八模块182／182通过，综合59项通过，回执分别为 `.artifacts/vector-index-reg-r1/` 和 `pgverify-88df330b61214e3893514197dae53b43`。随后私有反例证明截断名称相同的未批准完整空间被接受，因此合同升级@4并增加完整声明核对；此前结果按原候选留存。
- 最终@4的 `pgverify-86502bb0701340828a1545d873a590e0` 前45项通过，在召回恢复检查触发 `parser_timeout`，耗时8344ms，退出125，进程已回收。该批已通过向量构建及恢复后向量／融合消费。
- 单独复跑 `pgverify-92f7ae9eee00404a9de47abded3c249b` 前37项通过，在PDF场景触发期限，进程退出0、有输出、已回收，回执耗时9282ms。保留该失败，继续按准备、执行、结果复核及清理阶段区分证据。
- 私有TMP批 `pgverify-035a76d9ff4543919839600b0fc3602c` 前33项通过，在Hankook封存Parser场景触发期限。私有TMP配置与通过批不构成默认目录间歇超时的根因证明。

## 临时目录与环境恢复

正常PDF诊断在两个目录各执行3次原入口。系统默认目录观测4.125–4.719秒，项目私有目录2.125–2.437秒，文件树核验占主要耗时，fsync合计61–157ms。封存入口再以相反顺序测量，各2次，私有目录2.515–2.687秒，系统目录4.500–4.578秒。所有测量保留原限制，记录位于 `.artifacts/vector-index-maintenance/parser-phase-profile.json` 和 `parser-sealed-phase-profile.json`。

正式PG wrapper现将TEMP／TMP／TMPDIR放在每批 `.artifacts/postgres/<run>/tmp`，与现有受管回归的私有临时目录方式一致。系统默认目录中的间歇超时、调度及低层OS原因仍待确认，生产性能与SLO继续独立验收。

恢复核验发现PowerShell把原本未定义的环境变量通过普通空值参数恢复为空字符串。最小探针重现before_null为true、after_null为false；显式NullString恢复后重新为未定义。已修正wrapper，直接执行其实际恢复循环验证未定义、空字符串和非空字符串三种状态均保持。最终完整批还核对TEMP／TMP／TMPDIR恢复为原值，回执为 `.artifacts/vector-index-maintenance/env-restore-three-states.json` 和 `temp-restoration-fixed.json`。

## 复跑及范围

```text
python -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root <fresh-private-slot> --targets apps/api/tests/test_schema_startup.py apps/api/tests/test_text_embeddings.py apps/api/tests/test_embeddings.py apps/api/tests/test_external_fact_governance_cli.py apps/api/tests/test_external_fact_governance.py apps/api/tests/test_safety_gate_external_governance.py apps/worker/test_monitor.py
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-schema -CliTls
pwsh -NoProfile -File scripts/verify-postgres.ps1 -PostgresBin <existing-postgres-bin> -Port <unused-port> -Suite runtime-role
```

本轮7个PG集群均已停止，逐项核对postmaster.pid、初始化口令及TLS私钥缺席，7个自用端口可重新bind，842输入与最终文件匹配。回执为 `.artifacts/vector-index-maintenance/delivery-checks.json`。原始回执、诊断、私库和材料保留于Git忽略目录。受管输入不含PowerShell脚本，wrapper另外执行语法、三态环境恢复及实际完整PG流程验证。

本轮采用合成材料、ASGI TestClient及隔离PG18.3，Provider为合成固定向量。真实模型、实际终端、远端部署、生产IAM／RLS、完整角色权限反例、生产吞吐及完整V1继续待验。
