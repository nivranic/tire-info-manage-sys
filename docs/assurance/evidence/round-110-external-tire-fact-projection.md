# R110：外部轮胎事实的G2a纯投影

2026-10-21。唯一新run的26主测试、130 subtests通过；Root独核与g2a_code_review_ultra终态独审接受纯投影范围。V1仍active，provider/export=false。

## 改动与覆盖

仅新增标准库[投影模块](E:/Mix/project/tire-info-manage-sys/apps/api/tire_api/external_tire_fact_projection.py)和[直接unittest](E:/Mix/project/tire-info-manage-sys/apps/api/tests/test_external_tire_fact_projection.py)，复用G1a结构适用判断；未注册DB、route、scope、HTTP或SDK。

- 23个必需字段逐项需许可，含补成null的可选identity键；九facts按同一已选policy逐项裁剪，先严格校验全部输入，无许可的坏值也拒绝。
- 精确观察/身份、source_scoped状态保持；不拼笛卡尔覆盖、不升级身份，不混淆missing/null/false/0/conflict，隐藏冲突不外泄。
- 嵌套不可变，to_dict返回独立深复制；普通JSON容器先受限再冻结，拒绝循环及容器/标量子类。64KiB UTF-8、depth4（root=0）、256值节点及字段数值上限是工程v1边界，不是物理或法规认证。

源码SHA256：模块44b61a627fff3e1a402e02d8aefb5f339938eaa0f13e2ec5befb24b524a0997a；测试7c5000ba9126fb15f0879a7abc9342d0d0194dda6a0ea13371701ce100a72316。

## 实际执行与证据

Root唯一工具6ae2bd直接exit0，未重跑。[receipt](E:/Mix/project/tire-info-manage-sys/.artifacts/external-tire-fact-projection-20261021/run-26dfb51107e94e139b6d29f8182daae3/receipt.json) SHA256 890d7506ef8ed9a6bf207e7ae22a77b545103fe81ac61151944d333dd134c346。

Root424e46独核expected/started/completed精确ID逐序相等、唯一26；26成功，fail/error/skip/incomplete及issues均0，130 subtests。child自然exit0，无timeout/forced stop，stdout10105B/stderr0。终态独审只读核回执接受，未重跑或重复全量hash。

denied的child/import/network/read/sqlite/write全0。forbidden_loaded/preloaded=1为ntpath既有_winapi精确对象及LCMap路径角色，identity unchanged；added/unexpected=0，并非新导入豁免。

[91关键输入pins](E:/Mix/project/tire-info-manage-sys/.artifacts/external-tire-fact-projection-20261021/candidate-input-pins-v1.json) SHA256 98c0bc14b4a100c82870d643eb77758d10e483766b17c9cd35a1884735a0a41b：85 runtime、3 sources、2工装、G2A合同；运行首尾及Root live匹配。它不是完整传递依赖闭包，不含HANDOFF或G2B。文档应用后另核91项及HANDOFF原117002B suffix，before、非空File.Replace backup和docs-apply-readback-v1.json保全。

本批26项与[R109](E:/Mix/project/tire-info-manage-sys/docs/assurance/evidence/round-109-legacy024-isolation.md)的独立3项不拼一run。G1a旧22、其他旧22、旧vehicle pytest及其他回归未重跑。

## 限制与下一步

本run无NUL错误翻译窗口、新deps或Pydantic环境，child env为空。Python audit hook不是OS sandbox，有cached import盲点，capture无硬内存限；不证明自然WMI/正常应用已恢复或全部系统资源关闭。

policy仅由G1a判结构适用，不认证G1b受控许可、owner、最新head或法律真实性；无正常DB、实际PG、真实材料/Provider、HTTP、设备或完整V1验收。未commit/push，未改旧auth。

下一步[G2b owner契约](E:/Mix/project/tire-info-manage-sys/.artifacts/fact-query-contract-20261021/G2B-OWNER-IMPLEMENTATION.md) SHA256 9a914b772d3d4a27b94a31aee10b197058870623263651cb6353418a58d30f25已备、尚未实施：仅可信新query原子归属回执，旧历史不补绑。session换绑引起历史归属漂移仅静态可达，未实测跨账户泄漏。后续迁移须守旧024 upgrade(include_vehicle_binary=False)历史边界，显式025/旧vehicle断言审合法增量，禁宽subset或回写旧receipt；SQLite先行，原PG内部查询保持现状，owner外读未启用则拒绝。
