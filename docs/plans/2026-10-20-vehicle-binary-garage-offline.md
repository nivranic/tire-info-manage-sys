# R94 车型二进制车库与离线用途闭包实施计划

**Goal:** 在复制、读取及续写个人车库资料，以及离线准备、预览、确认和下载时，沿保存的车型来源引用核完整性与本次用途。

**Architecture:** 只复用既有 consumer capsule 与用途策略，在车库引用入口、离线 context 冻结前和既有冻结产物再次使用处加窄门。冻结身份与当前 Snapshot 元数据联合判别；个人 profile 可编辑，但 `basis=user_entry` 不清除仍保留的来源引用。

**Tech Stack:** Python、FastAPI、SQLAlchemy；仅既有受管 runner 下的私有 SQLite 与真实历史 S2 隔离 Parser child。

2026-10-20 实施 Gate 已由 Root 放行；运行 Gate 独立，静态候选完成前不执行产品 import、SQL、pytest、Node、服务或正常数据库。合同为私有提案 `.artifacts/vehicle-binary-garage-offline-4a8127c9df65/proposal.md`（9300B，`459605a7deaee26308a243d3c2da9540e9dd0d5c616c193c02faf855ee93263a`）和独审 addendum `.artifacts/r94-garage-offline-review-sol-7d31b0a9e6f2/review.md`（5759B，`a1d714fb6cd4b92ad11c45079f121209a921e114513989ffca9ad62745b1f5c7`）。

## 1. 基线和修改范围

四既有源原字节已保存在 `.artifacts/r94-impl-fbf06d45f62c/original/`；`baseline.json` 绑定 R93 的 `.artifacts/r93-f-7c4e8a2d1b60/source-after.json`，四文件大小/SHA 逐项匹配，新增测试及本计划原先不存在。保留所有既有 dirty 修改，不提交、不推送。

- 修改 `apps/api/tire_api/garage.py`：来源引用核验及所有读写门。
- 修改 `apps/api/tire_api/offline_evidence.py`：context 预冻结门、vehicle member receipt、固定 omission code 与冻结材料用途检查。
- 修改 `apps/api/tire_api/offline_packs.py`：旧 preview、首次 confirm 和 download 的薄调用，以及 base 对象/指纹完整性校验。
- 新建 `apps/api/tests/test_vehicle_binary_garage_offline.py`：由独立测试 agent 独占编写。
- `scripts/run_api_worker_regression.py` 仅登记新模块并把清单计数更新为 159 API＋2 Worker＝161；不改 Guard、ChildPolicy 或 runner 行为。

`vehicle_raw.py`、SDK、Native、模型、迁移、固定 REVIEWED SHA 和所有旧合同不变；无新的许可环境变量或用户授权勾选。

## 2. 车库入口与不变量

首次 `from-fitment` 在读取业务 payload、选 fitment 和写 revision/audit 之前调用 `checked_vehicle_consumer_capsule`，再独立要求 `local_structured`。从已核 capsule 选标准或选配项，不推断年份、OE 或精确 SKU；新 binary reference 保存选定 `verification_id`、`verified_at`、`fact_hash`。真 legacy text reference 不增加字段。

按实际 reference 与当前 Snapshot 判别来源。保存的 provenance、fitment id/availability/constraints/source_description 必须绑定；旧 reference 缺 receipt 时只核当前可用链，不回填或宣称重建历史 receipt。list 所选行、detail 返回的每个 history revision、PUT、set_tire、state 及 no-op 都在返回 profile 或 append/audit 前核验。后续个人编辑可改 profile；保留 reference，不能借新 `basis=user_entry` 降级。纯手工 create 不推断来源。

完整性失败固定 HTTP503 `vehicle_raw_integrity_failed`；用途失败 HTTP403 `vehicle_structured_fact_use_not_allowed`。真正 HTTP 拒绝不新建车库 revision/audit。版本冲突、归档及旧 wire 保持。

## 3. 离线准备与投影

`resolve_scope` 在创建 garage context、选择其 tire/vehicle member 及生成搜索 documents 之前要求同引用的 `export`。拒绝整个候选 context 和派生成员/文本；显式 garage ids 或显式 refs 为 blocking omission，默认范围可非 blocking 省略并保留其他合法内容。omission 的 reason 使用固定 code，不能 `str(dict)`。

prepare 保持现有 HTTP201＋omission/can_confirm 语义，允许原有 plan 元数据和 planning 审计；blocking 计划不保存内容对象或发布包。默认非 blocking 范围仅冻结无关合法内容。独立 binary/fixed-first-generation vehicle member 先核完整 capsule 与精确 receipt，再核 export。

保持 source 恰八键：source_id/source_url/raw_hash/parser_version/parser_identity/observed_at/verified_at/verification_id。vehicle payload 仍仅 vehicle/trims/fitments/footnotes、fact_hash/fact_version 和 excluded_document_count；不加入原件、documents 全文、raw/capture 或新源字段；`raw_included=false`。

## 4. 两项 P1 与冻结材料再用

**身份不能以 capsule=None 当 legacy。** 冻结 PDF_URL、S2 raw_hash、member.payload.vehicle.id 等正向身份，与轻量当前 Snapshot 的 binary 或固定 source＋首代身份联合判别。任何一侧指受限来源，都必须取得非 None 的完整 capsule 并绑定冻结 snapshot/raw/parser/provenance；缺 row、伪 UTF8/JSON、None 或冲突为 HTTP503 `vehicle_raw_integrity_failed`，通过后才检查 export。旧 context-only 包即使 vehicle member 已 omission、没有新标记且 basis 已改，也经过同门。

真正 legacy 冻结分支只核元数据身份/冻结绑定，不重读原始 body、不选新 receipt。完整 vehicle member 可用自身 vehicle id 与 source 八键证明 legacy；garage-only 缺当前 row 且无法证明身份时属于未知，503，不能承诺全部缺源旧包可分发。当前真实 legacy row 尚在但 body 晚损坏仍可用；旧轮胎冻结包也不重读源 body。

旧 base 只用于内部 schema、diff/semantic digest 比较，不重新返回或合并其 payload；因此 `create_plan(base_pack_id)` 与 `update_base_envelope` 仅保留 owner、对象/hash/fingerprint/结构完整性检查，不核旧 base 当前 export。允许新 scope 完全排除受限资料后生成合法替代包；新 contexts/members/documents 仍逐项经过预冻结门，返回的原 descriptor/digest/diff keys 属历史元数据。

**blocked preview 无对象也有事实。** `get_plan` 无条件检查 preview.contexts/documents/resolved；有 content_hash 时先核对象字节、冻结结构及其中身份，再核 preview。无对象的旧 blocked preview 不重建、不删改；可证明的真 legacy 保留原 blocked shape。首次 confirm 与每次 download 同门；同 key 已有 descriptor 重放、descriptor 列表/详情保持历史元数据边界。

冻结对象/结构损坏沿 HTTP503 `offline_frozen_object_unavailable`；来源身份/绑定失败为503 `vehicle_raw_integrity_failed`；export 为403 `vehicle_export_use_not_allowed`。始终保留旧 bytes、receipt、hash、preview 和历史行，不重解析/选最新事实或改写产物。

本地结构用途与 `local_original_read` 独立。车库不要求原件下载许可；原件可读也不授结构用途。Provider/export 继续由既有 helper 永久拒绝，私有 local-only fixture 不能放开二者。同步及重新下载共用这些路由；服务器拒绝新分发不代表撤销已落设备副本。

## 5. 验证预算与执行 Gate

设计预算18个新展开 case、最多18个真实 Parser child；最终按测试 AST 与实际 fixture 图重核，不预填通过数。核心覆盖：本地/原件许可独立、四损坏（object/execution/provenance/UTF8）、精确及旧无 receipt 引用、basis/no-op/history、explicit/recent/garage omission、context-only 与 blocked preview、旧冻结 preview/confirm/download、纯手工及 legacy 晚 body 损坏。损坏只经私库 `__table__.update`，保持 append-only 生产保护。

九个旧 exact 单例（无参数化，预期零 Parser child）：

```text
apps/api/tests/test_garage.py::test_garage_create_edit_archive_restore_is_append_only_and_does_not_fetch
apps/api/tests/test_garage.py::test_local_workspace_garage_survives_session_change_and_restart
apps/api/tests/test_garage.py::test_copy_fitment_retains_source_and_never_infers_oe_sku_or_year
apps/api/tests/test_garage.py::test_copy_preserves_selected_trim_year_instead_of_guessing_from_generation
apps/api/tests/test_offline_packs.py::test_confirm_freezes_exact_reviewed_bytes_and_receipt_no_latest_reresolution
apps/api/tests/test_offline_packs.py::test_default_keeps_workspace_garage_but_watch_and_recent_are_session_scoped
apps/api/tests/test_offline_packs.py::test_plan_and_package_are_append_only_and_confirmation_survives_later_source_corruption
apps/api/tests/test_offline_packs.py::test_missing_explicit_evidence_and_unknown_fields_block
apps/api/tests/test_offline_packs.py::test_all_domains_exact_revision_origin_empty_recall_and_per_record_search
```

静态候选和独审通过、Root 明确运行 Gate 后，只通过以下受管入口运行一次目标集合；`<fresh-output>` 必须为不存在的 `.artifacts/r94-*`，`<actual-dir>` 为 Root 指定实际历史 bootstrap。命令中的九 exact 为上述原名，不能替换为全模块：

```text
python scripts/run_api_worker_regression.py --phase run --output-root <fresh-output> --actual-dir <actual-dir> --targets apps/api/tests/test_vehicle_binary_garage_offline.py <nine-exact-nodeids>
```

候选为新 whole1＋旧 exact9＝10 targets/3 modules，设计27唯一 case；161只是 manifest 总数。实际 nodeids、三阶段、JUnit、资源/child 及 before/after source pins由真实回执确认。没有直接 pytest、collect、产品 import 或其他提前运行。正常库、实网、真实 Provider/receiver、PG、SDK/Native运行和完整 PDF/V1 验收均不由本切片推导。

## 6. 交付与回退

交付三个生产文件、新测试、runner 的最小登记差异、静态 AST/预算和最终 source pins，交独审及 Root；文档/seal 由其他 agent 负责。任何运行红项保留原回执，先判根因再决定受管复验，不倒填通过计数。

若候选须回退，只能在确认当前文件仍等于该候选 pin 后，从本轮 `original/` 恢复本轮四既有文件，并移除经确认仅属本轮的新文件；不得覆盖他人修改，不操作正常数据库或删除历史产物。当前未实施回退。
