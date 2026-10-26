# R107：外部结构化事实许可纯核 G1a

2026-10-21。交付限定为 **G1a 合成结构与适用范围纯核**：新增标准库产品模块和直接 unittest，附短 plan；尚未接入产品数据库、API、外部事实路由或 SDK。v1 正式运行失败保留；只替换两份工装、独立封定的 v2 单次运行通过，终态独核接受范围相同。provider/export=false，完整 V1 active。

产品 `external_fact_policy.py` 为 13631B/SHA `f473bfc5f83379802a1d6493ec48d6bd778fb038622b4a2c8a46e95b5965721d`；测试 `test_external_fact_policy.py` 为 22716B/SHA `f6aa417bfea8f14159d3c82dffe01da0fd35a3b98225b4de38c4c9997971933d`。两文件在 v1/v2 之间未变。原候选合同的九 facts、owner/账户作用域、HTTP/DTO 和 SDK 仍未冻结，不因本轮测试通过而自动成立。

纯核固定 schema `external-fact-policy@1`、purpose `external_structured_fact_read`；只接受精确内置类型与封闭字段，不隐式转换，严格限制文本、记录和集合容量。完整修订链为1–256条，revision从1连续、grant/source身份一致、previous_digest相接、审阅时间不倒退，最终摘要必须匹配显式 expected_head。全部嵌套形状先校验，再以规范 JSON/SHA-256 检查自洽。

适用性核对 source 与完整观察三元组 `snapshot_id/raw_hash/parser_version`，避免将多个三元组拆成笛卡尔积误授权；请求字段必须逐项精确覆盖，不作前缀或模糊匹配。时间采用规范 UTC 秒 Z；显式 now 仅接受标准库 timezone 零偏移的精确 datetime，不读取时钟或调用自定义 tzinfo。返回冻结的最新修订/head与不可变嵌套值，无调用方可变别名；再次评价时重核受损/伪造对象的形状和摘要。结果固定为 `applicable/not_applicable/invalid` 及固定内部原因码，不是 HTTP 或法律批准状态。

**无密钥 SHA-256 自洽不等于真实许可。** 调用者重造完整链和 head 仍可自洽；expected_head不是认证、真实当前head或审阅者身份凭据。rights/evidence字段只做结构核验，opaque evidence_reference 不打开、不联网、不核真实材料字节。可信权利依据、受控最新head、持久审计、并发与撤回治理属于 G1b；G2查询路由/账户/字段投影/SDK未做，不能直接透传内部facts或注册事实路由。

v1 唯一正式工具 `7b2ebe` 实际 exit1，原回执 status=failed/child1。22个主 test、39个 subtests 完成，测试 failures/errors/skip/incomplete均0，但 `forbidden_loaded=1` 令整体失败；不能写成一次全绿。原 receipt 2031B/SHA `68e009f88dbcc857b8ffdc30b381d44267633cd92789fa81f4c97a1619cb8dd3` 保留，没有模块身份记录。os→ntpath→_winapi 是已读源码支持的静态解释，不能回填 v1 唯一项的运行时身份。

v2只替换新路径下 audit_harness.py、launch_audit.ps1；84项关键输入中82项与v1同路径/同大小/hash，产品与测试不变。新独立 manifest SHA为 `f687942cc3e0da9ac1c0b4d8bee04dc8d211fae95a809fc3b427929d22786625`。Root唯一正式工具 `5f0b7c` 实际 exit0、child0；新run `run-4bc4490348664bc68fe38180855be966` 的回执 completed/passed。22主/39sub分别计数；failures/errors/skipped/incomplete/expected_failures/unexpected_successes全部0，denied child/import/network/sqlite/write全部0。

v2实际 `forbidden_loaded=1`、preloaded_forbidden=1，固定预载 native 路径大小写映射角色核验通过，记录的module/function身份首尾相同；added/unexpected均0。总数1保持可见，不写成“从未加载”，也不扩大为整个native模块能力批准。84关键输入首尾匹配；stdout1238B/stderr0完成收集，child自然退出、forced_stop=false、timed_out=false。终态独审核对新receipt/Root汇总、84项输入和v2实际baseline，无差异，没有重跑；v1回执、旧manifest和旧审查保持，不倒填旧身份。

验证只覆盖固定纯核合成向量。Python hook不是OS隔离；cached import可无import审计事件，启动前/native/全部瞬时行为未完整观察。denied全0不等于逐个实测拒绝分支；84项不是完整transitive closure，首尾hash不证明原子加载字节。流在内存读取并抑制，没有独立捕获内存硬上限；执行期限外另有有界清理等待，自然退出不证明全部句柄关闭。没有真实法律许可、Provider/export用途、正常DB、真实后端/UI/设备、六端或完整V1验收。该入口按精确源码加载纯核，不能证明应用包导入；WMI应用导入阻塞仍未恢复。

下一步先收敛 **G1b可信许可治理合同**，复用既有受控head/审计/撤回模式，再建立受支持的独立应用测试入口；G2路由/SDK排在这些前置之后。保留现有Guard和用途边界，不重跑v1/v2旧run，不以纯核成功替代应用恢复或真实许可证据。

交付与证据：

- [短 plan](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-21-external-fact-policy-core.md)、[产品模块](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/external_fact_policy.py)、[直接测试](E:/Mix/project/tire-info-manage-sys/apps/api/tests/test_external_fact_policy.py)。
- [v1原失败回执](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-policy-core-20261021/run-a84d6989a4a14a1991f756606c49a08f/receipt.json)；[v2 manifest](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-policy-core-20261021-v2/candidate-input-pins.json)。
- [v2实际回执](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-policy-core-20261021-v2/run-4bc4490348664bc68fe38180855be966/receipt.json)：2218B，SHA `ea3951df65de57aaddf9295a5f989acc27ad5fb153e057590ea17127bfeb1d51`。
- [Root终态回读](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-policy-root-audit-20261021-v2/terminal-readback.json)：1317B，SHA `ad23c019206b24cba42285a97fc19b4afdf5ba6fcc71aed27cbf0b980daeb477`。
- [终态独审](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-policy-review-20261021/TERMINAL-REVIEW.md)：4524B，SHA `fafc9ab1443548948adae67908d2580c2d09ef3bedb7751dabb6002832b85199`；[独审JSON](E:/Mix/project/tire-info-manage-sys/.artifacts/external-fact-policy-review-20261021/terminal-review.json)：3574B，SHA `df989ac33018805a1c90c355d015ef8e01951c61a1459a7b75d3fe52eb7ac8eb`。

R105/106文档应用首次工具36e4b7 exit1、独立恢复899a0a exit0分别保留；[当前正确入口](E:/Mix/project/tire-info-manage-sys/.artifacts/round-105-106-progress-20261021/root-terminal-readback.json)确认完整旧尾与备份一致。该文档恢复账不改写R107测试账或任何旧失败。本报告由安全文件读取与hash核对整理，没有另跑QA或运行时。
