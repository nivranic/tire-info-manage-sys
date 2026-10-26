# R112：同事务内部 owned reader

2026-10-21。v3独立新批次25主测试、41子测试全部通过，Root4e9277与verifier独立终态复核接受合成SQLite工程范围。V1仍active，provider/export=false；完整外部事实API尚未完成。

## 实现与范围

新增external_fact_reader.py；external_fact_governance.py增加内部只读事务/有界加载，identity_contract.py仅增加exact current binding helper。SQLite BEGIN IMMEDIATE后取一次保留微秒的UTC now，同一connection/fresh Session核原Bearer/key seal、当前User、scope/期限/撤销、显式source→单grant、最新可信许可、审批原Q/V/S锚和本次owner→Q/V/S、当前治理，再执行G2a。capture仅收凭据，不是已认证flag；不信旧principal，不补历史owner、不自动换grant。

Q/V精确配对live/ok或live_verified_304/not_modified。审批Q1/V1与owned Q2/V2可复用同一获准Snapshot，owner仍属于Q2；兼容旧FactVersion可被新S复用，不强求fact.snapshot_id=S。当前绑定fingerprint、成员/身份key、事实hash、原文与Parser/query/source重核；缺当前binding直接拒绝，不扫描legacy assessment、目标重定向或全库latest。

按Root接受的窄简化，直接从已核成员提取九facts、UTQG别名与prefix规范显式冲突，复用canonical/known-values和逐值G2a；不调用global-latest候选helper或registry。保留source_scoped及合法null/false/0/冲突；人工raw各取latest后求canonical抑制并集，clear只恢复本S来源值，不导人工after/说明。source pause是采集偏好，不等于历史许可撤回。JSON/正文/历史在ORM物化前SQL字节/max+1预检，超限整项拒绝。

facts:read仅新增枚举/发行容量、共享类型、SDK validator和Web label兼容；旧key不升级，Web创建仍原两项，无facts checkbox、facts HTTP、分页或SDK事实方法。Session commit/rollback、dirty flush及execute/scalar/scalars DML拒绝；原连接transaction identity/active保持到clean末尾唯一commit。静审发现的提前结束与scalar/scalars漏口已补，这是可信实现防误接，不宣称已观察生产写泄漏或同进程恶意隔离。无新schema027，旧025/026与024历史边界不改。

## 受验源身份

前三行为apps/api/tire_api/下reader产品源，其余为scope兼容与测试源：

| 文件 | SHA-256 |
| --- | --- |
| external_fact_reader.py | eb93b0e3a3f43156382ee03502870e80f3e16be838df8cdc377de0e3e2548eff |
| external_fact_governance.py | d7ef3b07595d755c3063243b425d16607c9c5b3d21acb4219328e804a4be6533 |
| identity_contract.py | 29e4486d6c9f387619a9da807e6f9ce6e24b2197b51e5f830c9c5f96ceea7e9d |
| apps/api/tire_api/external_api.py | 40894bea30f10eb85db10a0cd5e7483da0311c3d7f405c3e1fd17a6278e27e16 |
| packages/domain-types/src/external-api.ts | e9757f8e6e4cb193fdfa52ffa4c650dddeaccaf0716e9917f5adfaadefd49a18 |
| packages/api-client/src/external-api.ts | ca085c8d5412756baeca007f38359e6902634a441fc5e6674e9f0b65d821ac04 |
| apps/web/components/api-keys.tsx | 9cc5aaff4f5af9850f8afe07036718fc9a60ceb576a5b2890f08f3790e130463 |
| apps/api/tests/test_external_tire_fact_reader.py | 67a5e658cb52c0549eb4c54f245c952b7087644338debe7fd26e25ac2c9d3341 |
| packages/api-client/tests/external-api.mts | a5b499919291dd76ca37f706fded25b5a4be3ccbb84fe9f9d7663c7d18951367 |
| packages/api-client/tests/api-key-inventory.mts | cb490ced3b1b861ba3056de2b104d6058fc08f2ae1c5e4c9c087bf7559136f93 |

冻结合同f31cdee7…8c89e，产品静态读回v2为777af11e…10cb4f；两个既有产品源before及scope before另存。v1/v2的Python旧测试c09c7959完整保全，v3只改两处fixture，产品不变。

## Python三批分别保留

- v1：[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-reader-verification-20261021/run-89ccfd0429c5434e8fb3775f06c45314/receipt.json) SHA75d5e4c8756cd23b3752dc8085bfb0b272ed89d876c9c4090014e881eaa01c3a。0主/0子/0SQLite/0私库；aiohttp/helpers.py:57在原platform.system恢复前调用受限wrapper，imports1；NUL3预期，其余denied0。1330关键pins unchanged，自然exit1/stderr0，不能证明reader业务。
- v2：[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-reader-verification-20261021/run-60e47fa5f88a4831952e56b8df320e6f/receipt.json) SHA48fd2f7ab1d47769963c66a49c26031bc3c586ab129e4d4e04f692661701be8a。25主完成22成功，fail1/error2（含1suberror）；41sub为40成功/1error。25fresh/0remain，1334pins unchanged，SQLite642；7probe各1/files4预期、其余denied0，自然exit1、无timeout/forced、stdout19851B/stderr0。test10/24 helper向withdraw误传terms；test21第二次真实service.transport_cache SELECT出现OperationalError，未进入reader，SQLite错误码未留，根因未知。
- v3：Root唯一da38a5/session88263→91d78c exit0，[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-reader-verification-20261021/run-cb3bb0c50e2047b7bc06337eab235c15/receipt.json) SHA1807220c5dfd1a6c966a0671bbcf0f6ac98b7f9a16ae49712bef92304ce7a555。仅修approve才传TERMS、其他action传None，以及8MiB-1/8MiB使用不同合法query资源；runner与v2逐字相同，guard不放宽。此批独立通过，不拼接前两批。**缓存OperationalError未定位或修复；v3隔离该cache复用路径，不构成其修复证明。**

## v3实际证明与限制

Root4e9277与verifier独立核25主/41sub全pass，fail/error/skip/issues均0；pins expected与receipt expected/started/completed四序列同序、各25唯一ID。25fresh/0remain，t现场0；自然child0，无timeout/forced，stdout15852B/stderr0。SQLite连接652，19个bootstrap判据真，7个精确probe各1，files4=NUL3+proc1预期拒绝，其余denied0；Winreg预载对象/属性、system和自然SQLAlchemy缓存保持，fixture root为实际核对结果。

[pins-v3](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-reader-verification-20261021/key-pins-v3.json) SHA739e9b2b8477a6621f3982229c496c4247578b58a1b1a95308992aa8e2899056：1342关键输入首尾及Root live匹配，非完整import/Node依赖closure，不含HANDOFF；文档应用另核。未重跑R111旧32/38、旧G1a/治理单测或全仓测试。

真实产品函数在新私库执行credential捕获、facts-only/all3 KeyCreate mutation/create、QueryService.execute/record_success、身份/FactVersion及GovernanceStore authenticate/preview/append，成功包括非空live、304、新S复用旧fact与source_scoped。另含精确双锚损坏、账户/期限/撤销、手工别名/身份clear/lifecycle、8MiB-1/B成功与超限前置SQL、manual4096/4097及Session guard。两真实连接/Session验证读锁内撤销/许可撤回写等待、结束后提交且下一读拒绝。registry为即时合成返回，无真实网络/Parser/pre-parser capture journal；KeyCreate依赖与发行endpoint的直接调用不是HTTP、中间件、cookie或UI验收。

## TS类型与SDK另批记账

scope v1 [receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-query-contract-20261021/scope-compat-v1/verify-run-40bf8663a5484e7884d590d0ee7e84b3/receipt.json) SHA5bc141e2283937cd0cb8d18ab84b9476b2fab76774852f954e02fe79d55e88f9：external-api、inventory、Web三项types各exit0且stdout/stderr0；第4 runtime在测试前因Windows --import盘符URL失败，库存runtime未启动。该批phase_failed，不能称五阶段全绿。

runtime-only v2 [receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-query-contract-20261021/scope-compat-v1/verify-runtime-v2-run-6a0c02e455af48e59a8f7bad8c0be5d1/receipt.json) SHA81dfc9fc779eb461d3e29aae6f3a11bddbe60ca717186de01ca17b3b5f2e1e9a：两SDK脚本分别59/47个合成注入检查成功，各exit0；stdout113/112B、stderr183/183B，不记为stderr空。未重跑前三项types；两批各14关键pins unchanged，非完整closure，manifest SHA2a666b1ed741bcd5f37b29957b3e1d8a69fc13d0fd12035a2b52f00b792afad9。scope_contract_v1.mts保留未运行，不算额外验收；类型检查不能替代UI/后端集成。

## 当前后续与保全

Python hook不是OS sandbox；cached import、hook前native/registry活动未知，合成环境探针、NUL错误翻译、局部SQLite插桩及capture无硬内存限继续保留。不以hook计数声明全部系统资源或native网络已证明关闭。PG仅dialect stub/静态边界，实际PG、正常库、真实法律权利/材料/来源/Parser、HTTP/浏览器、中间件、Provider、设备与完整V1仍未验收；未commit/push。

下一步分别冻结facts路由scope/allowlist、分页/cursor、SDK事实方法及部署mapping，开展独立HTTP端到端验收；另行定位已保留的transport_cache异常。许可链自洽不是法律真实性，provider/export不得因本轮检查启用。

HANDOFF保全基线120241B，SHA42b873032b4cdd79e541cfd90a2dc34bb38328977692a6cc37378366335daf0a完整保留为原字节后缀；before、非空原子backup与文档应用读回分别保全。R111及更旧报告、失败工装/pins/receipts不改，旧“下一步reader”等属于各自历史时点。
