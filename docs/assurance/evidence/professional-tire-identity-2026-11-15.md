# 真实Dunlop精确SKU身份案例验收

2026-11-15，基线e886a70。本阶段建立首个绑定真实厂商目录页原件的精确SKU身份字面量与验证合同，推进"代表性真实SKU正例"覆盖。[前序来源验收](dunlop-eu-source-2026-11-14.md)

## 材料与绑定

规范原件取自前序验收隔离工作区`.artifacts/dunlop-source-20261114/http-r1/workspace.db`的raw_captures行：正文520,023字节，SHA-256为70deacb4f9c1f89023c8d7348888aaf272a18f14d88b6176f25d4e6b4f517fed，与2026-11-14T08:20:08Z正常live查询回执的raw_hash逐字一致。原件导出至`.artifacts/professional-tire-source-20261115/dunlop-sportmaxx-rt2-page.html`（write_bytes保真）。

[字面量](../../../packages/domain-types/fixtures/professional-tire-source-v1/real-dunlop-sportmaxx-rt2-identity.json)按独立schema professional-tire-source-identity@1冻结该绑定与两条真实SKU身份：Material Code 543000（GTIN 5452000703941、EPREL 612625、235/55R19 101Y、XL=null、燃料C、湿滑A）与544985（GTIN 5452000725776、EPREL 612638、105Y XL、燃料B）。两条GTIN校验位合法。同尺寸下两SKU仅以载重指数、XL、代码、GTIN、EPREL及标签URL区分，构成错合并陷阱。

权利沿用前序验收的保守边界：厂商公开目录页、robots允许、正常HTTPS取得；再分发与专业复用许可未确认，provider_use与export为false。转录状态agent_transcription_unverified，真人Golden复核pending_external_review。

## 验证

| 验证 | 结果 |
| --- | --- |
| 新模块test_professional_tire_identity | 6项通过（绑定、解析、身份互异、篡改、字面量漂移、范围与权利） |
| 生产解析器对绑定原件 | 恰好2条variant，字面量全部身份字段逐项相等，21/22个证据区间覆盖必查身份事实 |
| 身份键 | 互异且source_scoped，差异字段集与冻结预期完全一致 |
| 篡改与漂移反例 | 改1字节→sha256_mismatch；截1字节→byte_count_mismatch；改字面量GTIN/载重/XL→逐项失配检出 |
| 原件缺失分支 | 按冻结摘要条件跳过（复现PDF材料政策） |
| 相邻回归 | test_dunlop 21项+test_professional_golden_corpus 80项中100项通过；test_fixed_source_and_actual_isolated_child批内1次失败，同源码单跑10.58秒通过，符合[已确认的环境性解析墙钟模式](first-batch-pdf-failures-and-browser-409-2026-11-15.md) |

该字面量不进入7案例冻结观察器，不改变观察器real_positive_case_count=0与human_truth_qualification=inconclusive的冻结论述。代表性真实SKU正例的发布Gate仍要求人工复核；本案例提供可复核的第一手真实SKU正例材料。EPREL监管绑定维持前序"按厂商声明保存、待验"状态。

未重跑完整6模块受管回归：本阶段未修改任何tire_api产品源码，仅新增测试模块与fixture。生产PG部署、跨设备E2E及真人Golden继续待验。

## 重放

同机可在项目根目录运行`apps/api/.venv/Scripts/python.exe -X utf8 -m pytest apps/api/tests/test_professional_tire_identity.py -q`。新clone需按字面量路径与摘要从原工作区取得归档正文（页面含时变社交组件，重新抓取通常得不到相同字节），缺失时条件跳过、摘要不符时失败。[数据说明](../../../packages/domain-types/fixtures/professional-tire-source-v1/README.md)
