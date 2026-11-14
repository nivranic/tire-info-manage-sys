# 专业测试PDF成绩字面量

real-crr2017-original-measurements.json保存两胎、11路面、22条独立转录值，使用test_event_http模式核对场次。原始4胎范围、逐胎尺寸、50 km/h例外、出版物角色及PDF页码／码点区间均保留。精确SKU和真人Golden继续待核对。

来源为Beata Świeczko-Żurek、Grzegorz Ronowski、Jerzy Ejsmont，《Tyre rolling resistance and its influence on fuel consumption》，Combustion Engines 2017,168(1),62–67，DOI 10.19206/CE-2017-110。数值取自PDF第4页、印刷页65、表2，按CC BY 4.0保留署名和出处。[出版页](https://www.combustion-engines.eu/Tyre-rolling-resistance-and-its-influence-on-fuel-consumption,116799,0,2.html) [版权](https://www.combustion-engines.eu/Copyright,6171.html) [许可](https://creativecommons.org/licenses/by/4.0/)

PDF原件位于Git忽略目录，6页、2,413,872字节，SHA-256为85d6850a21e912d345b9eda8b9ce18564a76a020ed2e4c2a201a15a9bd616a91。clone需通过正常许可捕获取得相同字节，再放入字面量指定的相对路径。原件缺失时对应HTTP用例条件跳过，摘要不符时失败。

pdf_reference字面量以material_label绑定原件，保留extractor_version、page、start及end。正常HTTP上传生成document_id及元信息摘要，独立比较器按冻结引用散列格式解析运行时标识。缺省引用和出版物角色沿旧字面量形状序列化。该文件字节摘要固定在合同回归中。

在项目根目录使用PowerShell 7运行正常隔离验收入口。

```powershell
apps/api/.venv/Scripts/python.exe -X utf8 -B scripts/run_api_worker_regression.py --phase run --output-root ('.artifacts/golden-pdf-' + [guid]::NewGuid().ToString('N')) --targets apps/api/tests/test_professional_golden_checks.py::test_real_crr2017_normal_http_golden_event_with_saved_original
```

结果、输入、实际HTTP场次及离线比较报告保存在该次隔离目录。比较器的evaluation_mode为offline_bound_snapshot，当前HTTP执行的证据另由受管回归及actual.execution记录。发布Gate继续要求代表性SKU和真人Golden。
