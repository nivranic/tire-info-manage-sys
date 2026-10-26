# R109：旧024迁移的模型版本隔离

2026-10-21。唯一受限run的3个主unittest全部通过、0subtests；Root与独立终态审阅接受限定范围。固定023是静态schema和合成历史数据，不是正常库备份。

## 改动与覆盖

024此前从全局metadata排除四目标表，可能提前创建无025版本记录的025/未来表。现固定截至023的134个模型表名，注册后核完整性，仅创建其中130张非目标表；产品不读fixture，旧附加迁移、事务与四表重建流程保持。

新test_legacy024_isolation的三个精确ID见原receipt，实际覆盖：

- 预注册真实025及future表；纯固定023迁移严格仅024差异。另加一张外部自定义表和一行，核原对象/行保持、024幂等；显式025再仅加两表/版本及14个原生schema对象，继续幂等。
- 强核fixture后，声明删除原为空且无入/出FK的source_setting_revisions及006 marker；观察真实CREATE TABLE，核合法旧表恢复、其余旧schema/行保留及025/future不创建。006/024新时间戳单独检查。
- 真实after_replace故障使完整schema/行/版本回到固定023，资产保持。

四个全新私库均核145份合成资产。旧vehicle两处正常initialize兼容断言已改并静审，未执行；本run不导main/Database.initialize。上一轮22项未重跑，旧20份回归文件不称全绿。

## 实际执行与证据

入口（历史记录，本文未重跑）：

    pwsh -NoProfile -File .artifacts/legacy024-isolation-20261021/launch_legacy024_tests_v1.ps1 -ExpectedPinsSha256 8991a17380136c68913ceed8ab966eed3685cee85c8b714146537d9a6189e4be

Root唯一工具74e166/session21299，终态2c01ae exit0。[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/legacy024-isolation-20261021/run-22976fd4690c49c09ffb5348a2b0abaf/receipt.json) SHA 7ba4ff1dc072521383e02c5cfdf970dd4f07ceeb647c381cc24abede4cc73964。Root07cef6独核1001关键输入、五份固定fixture及3组精确ID：expected/started/completed均同一3唯一值，3成功，fail/error/skip等0、issues=[]。

files3=expected NUL拒绝3，其他审计拒绝0，导入窗口关闭；hostname查询1、SQLite审计连接事件15，fresh4/remain0，Root现场t目录0。child自然exit0，无timeout/forced stop，stdout2615B/stderr0。15是事件次数，不额外称每次均成功初始化。

[pins](E:/Mix/project/tire-info-manage-sys/.artifacts/legacy024-isolation-20261021/key-pins-v1.json) SHA同入口参数。1001项运行首尾及Root文档应用前匹配；本轮pins不含HANDOFF，文档应用后1001项亦独核匹配。关键输入不是完整import closure。原115837B HANDOFF逐字节保留为suffix，before、非空原子backup与docs-apply-readback-v1.json保全。

独立[依赖manifest](E:/Mix/project/tire-info-manage-sys/.artifacts/legacy024-isolation-20261021/dependency-preparation-v1/package-manifest.json)记录871文件：691个基线文件加8个官方wheel包的静态准备，不改旧deps、不用pip/执行包安装器。manifest的prepared_not_executed是准备时点；本次随后仅在受审目标导入内使用。

## 限制与下一步

本run用官方独立CPython3.14.8、局部SQLite连接插桩、精确NUL拒绝转PermissionError，以及AMD64/SYSTEMROOT/PYDANTIC_DISABLE_PLUGINS三项受控环境。实际拒绝保持；它不证明OS隔离、自然WMI/正常应用恢复、全部句柄关闭或内存硬上限。

正常库/生产历史库升级、PG、实材料/许可、HTTP、设备和完整V1均未验收；provider/export=false，无commit/push。下一步[G2a短合同](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-query-contract-20261021/G2A-IMPLEMENTATION.md)初稿SHA90a4bf08…已短审无阻断；纯投影模块与直接unittest已启动实施，尚未验证、未注册路由。session重绑可能将旧查询联接到新账户只属静态可达，未做跨账户泄漏实测；未来reader须可信新query归属，不能猜补历史owner。
