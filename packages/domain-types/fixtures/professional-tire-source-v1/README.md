# 专业轮胎来源真实SKU身份字面量

real-dunlop-sportmaxx-rt2-identity.json保存Dunlop SPORT MAXX RT2欧洲规格页在235/55R19下的两条真实精确SKU身份记录。原件为厂商公开目录页，2026-11-14经robots允许的正常HTTPS观察取得，正文520,023字节，SHA-256为70deacb4f9c1f89023c8d7348888aaf272a18f14d88b6176f25d4e6b4f517fed，与当时live查询回执的raw_hash一致。[官方规格页](https://www.dunloptyres.com/en/tyres/sport-maxx-rt2) [官方robots](https://www.dunloptyres.com/robots.txt)

两条SKU仅以载重指数与XL区分：Material Code 543000（GTIN 5452000703941、EPREL 612625、101Y、XL=null、燃料C）与544985（GTIN 5452000725776、EPREL 612638、105Y XL、燃料B），构成同尺寸错合并陷阱。生产dunlop-eu解析器从绑定原件字节解析必须得到这两条身份，身份键互异且为source_scoped。

数值为agent转录，状态agent_transcription_unverified，真人Golden复核pending_external_review。开放再分发与专业材料复用许可未确认，原件仅工程核验留存。[来源验收](../../../docs/assurance/evidence/dunlop-eu-source-2026-11-14.md)

原件位于Git忽略目录。页面含随时间变化的社交组件，重新抓取通常不会得到相同字节；新clone需从具备访问权限的原工作区按字节取得归档正文（或从归档workspace.db的raw_captures行导出），校验冻结摘要后放入字面量指定路径。原件缺失时对应用例条件跳过，摘要不符时失败。

在项目根目录使用PowerShell 7运行验证。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -m pytest apps/api/tests/test_professional_tire_identity.py -q
```

该字面量不加入7案例冻结观察器；观察器的real_positive_case_count与human_truth_qualification保持各自冻结论述，代表性真实SKU正例与真人Golden的发布Gate状态不变。
