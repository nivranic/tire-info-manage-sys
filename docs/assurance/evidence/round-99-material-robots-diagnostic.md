# Round 99：robots Accept 与有限失败诊断修正

2026-10-21（Asia/Hong_Kong）。本轮已正式应用受审的2个产品文件、2个直接测试文件及1个独立入口登记修正，并完成**唯一一次 `--phase run` 的两个模块离线受管验证：212项全部通过，30项source_materials + 182项review**。Root已独立回读每项setup/call/teardown、700项实际source绑定与完整keyset，结果一致。

这不是163模块全套通过，也不是一次新的在线材料捕获。旧aging与UTQG的失败状态、UUID和回执保持原样；本轮没有重试旧捕获、取得PDF原件或证明实际站点问题已解决。

## 问题、修正与合同

先前两次正式尝试都以 `source_material_robots_unavailable` 结束。冻结实现可将它们定位到robots响应状态不属于200/404/410的分支，但具体数字没有保存，仍然未知，不能补写成403或其他状态。只读分析见 [ROBOT-DIAGNOSTIC-REVIEW.md](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-review-20261021/ROBOT-DIAGNOSTIC-REVIEW.md)。

本次修正：

- robots GET显式设置 `Accept: text/plain`；PDF GET继续继承application/pdf。UA、identity、DNS/公网解析、TLS、pacing、deadline、禁未知跳转/隐式重试和失败关闭保留。此前Accept不一致属可证配置问题，尚不能证明是两次现场失败根因。
- 只在已知robots状态拒绝分支保留内部phase/status。清洗只接受精确MaterialTransportError、单一白名单code/phase、精确int且100至599并排除200/404/410；子类、bool、错类型、多args及额外URL/headers/body/notes等字段不入审计。公开failure_code和Exception字符串不变。
- 首个failed outcome与有限 `source_material_failed` 审计在同一次既有commit中写入，继续使用原 `actor_session_id`。不新增鉴权、commit、恢复或重采入口；同UUID回放不重复fetch/audit。审计调用/INSERT失败及提交确认丢失继续沿用既有不确定reservation合同。
- 成功receipt、Outcome模型/指纹、schema、API DTO与migration均未改变。内部诊断不进入公开capture/history响应，也不是原件/transport凭证。

独立入口修正仅在显式TEST_MODULES的原排序位置登记现有R97 boundary测试模块，并将计数注释/help从160 API+2 Worker/162改为161+2/163。完整集合相等门、Guard、ChildPolicy及其他行为保持；没有删除真实模块或绕过登记门。

## 五文件 before / after，分别记账

完整before与候选正文保存在 [candidate目录](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-candidate-20261021/README.md)，[REVIEW-MANIFEST.json](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-candidate-20261021/REVIEW-MANIFEST.json) SHA为 `f1b86aee27865e3823ddf964a2faabfb483c93cc563264c4052752fbc8231bb5`。应用前已核5个live等于before，应用后及执行后均等于批准candidate；候选目录未改。

产品与直接测试4文件的完整差异见 [candidate.diff](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-candidate-20261021/candidate.diff)，SHA `35b22e8ae967e0ef400c4fb3b2e5327a1de4f07cf0c1a3d95fed5a267668fabc`。

| 文件 | before SHA-256 | after SHA-256 |
|---|---|---|
| [material_source_transport.py](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/material_source_transport.py) | `38d91c4911b80410ca0eb0cda73783886cb8acda1762b765daee44835b6b98ca` | `80b238c6ce0fd63eb07ab0df0fc1603e39b715792aee911b6f89f89bf6514285` |
| [source_materials.py](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/source_materials.py) | `eb76c6226d26a488f90fa8b142dbf9d4ccf6a17df9b12d01d46947356720276a` | `b08fb82d2fe693d5dd150c6681793557dcd7b3b44cba4083e1a01515779c5b23` |
| [test_source_materials.py](E:/Mix/project/tire-info-manage-sys/apps/api/tests/test_source_materials.py) | `6ade94c557b360ae65d3645f65e9ea795b8943b5fa849a91b82ec349c716487f` | `b56a020988296ff998db103ad01fa59ad9b3fe038aed80ce52235229c2720ab9` |
| [test_source_materials_review.py](E:/Mix/project/tire-info-manage-sys/apps/api/tests/test_source_materials_review.py) | `5beda7084e5cb483600da87373177efc9e0d26681307483cb2f20444d4e3fc28` | `8c99bc1a90fd579eead066be7e22ae4bc91949aac28bb023ec955a5a654fa8f6` |

独立登记修正见 [registration.diff](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-candidate-20261021/registration.diff) 与 [registration静态回执](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-candidate-20261021/registration-static-receipt.json)。

| 文件 | before SHA-256 | after SHA-256 |
|---|---|---|
| [run_api_worker_regression.py](E:/Mix/project/tire-info-manage-sys/scripts/run_api_worker_regression.py) | `0e98b461872099851f39a509ded61fa6e60c82f8b24331b6fba42d50c54594a9` | `191ff235ed3c897e4098afbdd5b390945568fd85f09fa734a77a119642abd7d7` |

该登记候选三处literal逆向还原后逐字节等于before；163项无重复、Ordinal有序，161项API完整keyset等于实际目录，2项Worker未变。未运行新登记的R97模块来扩大本次验证范围。

## 唯一正式执行与实际证据

应用账见 [apply-manifest.json](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-execution-20261021/apply-manifest.json)，SHA `0cb5b9ad4d5a61718a5f1dcf211bbe2bb90363bcce29dbef51fbc1cda5d4de1e`。实际argv见 [execution-intent.json](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-execution-20261021/execution-intent.json)，包含Root明确要求的 `-I`，以此实际记录为准，未改冻结候选README中的旧示例。

```text
E:/Mix/project/tire-info-manage-sys/apps/api/.venv/Scripts/python.exe -I -X utf8 -B E:/Mix/project/tire-info-manage-sys/scripts/run_api_worker_regression.py --phase run --output-root E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-targeted-20261021-659c89ba --targets apps/api/tests/test_source_materials.py apps/api/tests/test_source_materials_review.py
```

执行采用PowerShell7、login=false、require_escalated上下文；未传actual-dir或旧actual。只执行一次run，run自身包含selfcheck与pytest收集，没有额外独立selfcheck/collect或重跑。

| 项目 | 实际结果 |
|---|---|
| tool session / 终态chunk | `17745` / `03fac2` |
| 外层工具 / runner / pytest退出码 | 均为0 |
| 正式phase / runner | run；passed=true；classification=raw_verdict_preserved |
| 模块与用例 | 2模块；收集212、protocol启动212、执行212；passed212，failed/skipped/incomplete均0 |
| 分模块 | source_materials 30；review 182；Root确认每项setup/call/teardown均pass |
| 内置selfcheck | all_passed=true |
| 输入 | 700项source绑定首尾stable；Root重新哈希并核完整keyset；5个live仍等批准candidate |
| 拒绝 | 非selfcheck拒绝0、已知IPv6探针0、其他意外拒绝0 |
| 保护材料 | Root独核R38/S2保持 |
| 资源 | runner resources_closed=true；受管孩子创建0/live0；metrics active0 |
| 正常库 / Provider / receiver | normal_database_started=false；真实Provider/receiver调用0 |

主证据：

- [正式result.json](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-targeted-20261021-659c89ba/result.json)，SHA `7888d08fad00dc97afcc0af102bc7970774a12d031b66dd0b7f52f894d15a89d`；[classification.json](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-targeted-20261021-659c89ba/classification.json) 明确 `not_a_full_suite_pass=true`。
- [安全tool-terminal.json](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-execution-20261021/tool-terminal.json)，SHA `4dd39694236459f1d29b5a282e051f906485254340c27a6dd8f2332436e88393`。只保存工具返回的一条结构化安全JSON；combined337字符，不声称工具提供了独立stderr计数，无原始非结构化stdout/stderr落盘。
- [execution-readback.json](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-fix-execution-20261021/execution-readback.json)，SHA `643ffa057e7183caebc67e9db781396a7432d114061824ceb881800d5209d650`。
- [Root候选独审回读](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-root-audit-20261021/candidate-static-readback.json)；[Root正式结果独立回读](E:/Mix/project/tire-info-manage-sys/.artifacts/material-robots-root-audit-20261021/targeted-result-readback.json)，后者SHA `c6a0a48e24422c24f70ea990260cf868e3adcd6fdd3d7918af10f7406adeed82`。

**resources_closed仅覆盖runner受管孩子与metrics口径。** 本轮没有逐SQLite handle的独立关闭ledger，不据此声称已逐句柄核验数据库关闭或全部系统资源，也不借旧轮证据补全。

## 保留限制与下一步

212项是合成/私有离线目标验证，包含真实aiohttp最终headers合并路径及失败诊断清洗、actor/回放、并发、审计回滚和提交不确定性；不能证明真实robots已经可用、Accept变更已解决现场问题、PDF可取或具体原件许可已核。

旧aging UUID `14f5ddc6-6cd9-4905-ae39-4f3fb7a71c60` 与UTQG UUID `369c54c6-1e28-4b63-bb69-9a096537725b` 均继续保留原 failed/robots_unavailable身份。具体历史HTTP数字仍未知；本次不回填、不重试旧UUID，不生成原件hash或成功receipt。Provider/export继续false。UTQG评级不能作为专业独立试验原始数据、成绩排名或精确SKU桥。

R98的两次Rust红停点仍未seal；本轮目标通过不覆盖它们。完整V1继续active，UI/设备、真实材料、人工Golden和用途边界分别验收。

下一步是另立新UUID、新manifest及fresh私目录的单次实网捕获候选，继续自主核具体官方材料与许可依据，不以EPREL Key或用户再给URL为前置条件。独审后才可正式执行一次robots/允许后的GET，并核具体状态、实际字节/hash/原document receipt与原件署名、版本、第三方权利和页码引用；未知跳转、robots拒绝或不可用仍失败关闭。本文不授权或启动该后续尝试。
