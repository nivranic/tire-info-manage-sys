# 捕获期限与真实滚阻论文验收

2026-11-15，基线7eefe80。本阶段通过正常入口捕获、索引和转录许可论文，保留结构化AI超限的实际失败。[阶段计划](../../plans/2026-11-15-material-capture-deadline.md)

## 工程交付

可信来源策略增加可选capture_timeout_seconds，严格整数1至70，默认45。默认值序列化时省略，历史策略指纹保持兼容。自定义期限同时作用于外层asyncio及HTTP会话，随捕获记录冻结。Web校验并显示期限。70秒上限由agent依据现有75秒客户端期限制定。

## 真实材料及转录范围

论文为Beata Świeczko-Żurek、Grzegorz Ronowski、Jerzy Ejsmont的《Tyre rolling resistance and its influence on fuel consumption》，Combustion Engines 2017,168(1),62–67，DOI 10.19206/CE-2017-110。出版方版权和开放获取页面已观察到CC BY 4.0，保存观察资料并记录作者、出处及许可。[出版页](https://www.combustion-engines.eu/Tyre-rolling-resistance-and-its-influence-on-fuel-consumption,116799,0,2.html) [版权](https://www.combustion-engines.eu/Copyright,6171.html) [开放获取](https://www.combustion-engines.eu/Open-Access-Policy,6168.html)

完整PDF为6页、2,413,872字节，SHA-256为85d6850a21e912d345b9eda8b9ce18564a76a020ed2e4c2a201a15a9bd616a91。两个隔离槽正常捕获均完成，r5约5.3秒。成功耗时小于默认45秒，不能据此把取得原件归因于期限扩展。PDF第4页已渲染并视觉核对。[PDF](https://www.combustion-engines.eu/pdf-116799-46024)

通过正常TestEvent入口保存两胎、11路面、22条成绩，参测胎为MCPR／MICHELIN Primacy HP／225/55R16与BLUECO／CONTINENTAL Blueco／195/50R18。来源原有4胎，记录reported_participants=4、coverage=selected_results、relationship=unknown、publication.role=original_report。根tested_size为null，所有来源名次为null。记录保持manual_transcription／unverified，精确SKU关联及真人Golden审核均为0。

方法为TUG R2 Mk.2 trailer、4000 N、regulated 210 kPa、空气温度20°C修正，测量年份2015–2016。一般80 km/h，Concrete block pavement为50 km/h。每条成绩绑定PDF第4页、印刷页65、表2的冻结码点区间。

| 路面 | MCPR | BLUECO |
| --- | --- | --- |
| SMA11 | 0.0110 | 0.0068 |
| SMA8 COOEE | 0.0108 | 0.0064 |
| SMA6 COOEE | 0.0105 | 0.0059 |
| DAC 12.5 | 0.0113 | 0.0053 |
| SD 0/14 | 0.0160 | 0.0082 |
| SD 8/10 | 0.0141 | 0.0074 |
| Fine Surface Dressing | 0.0088 | 0.0041 |
| Porous HMA | 0.0130 | 0.0058 |
| PCC Conventional Diamond Grind | 0.0109 | 0.0052 |
| ISO Type DAC 0/6 | 0.0081 | 0.0045 |
| Concrete block pavement, 50 km/h | 0.0104 | 0.0050 |

## 实际验证

| 验证 | 结果 |
| --- | --- |
| 最终5模块受管API回归 | 402通过，0跳过、失败或不完整，867输入稳定 |
| 受管子进程 | 60次全部exit 0，已回收 |
| 全工作区类型检查及Web生产构建 | 通过 |
| Web测试及SDK材料合同测试 | 分别68项及16项通过 |
| 独立PG18.3／TLS正常HTTP | 4项通过，非拥有者、捕获、冻结重放及删除当前策略后重启 |
| 正常生产Web浏览器 | 8项通过，尺寸、4胎范围、50 km/h例外、原值、22引用、原件重开及期限校验 |
| 真实材料正常HTTP链路 | 原件、6页索引、22条成绩、同场比较、关联FTS及v1／v2离线共6项通过 |
| Web消费真实离线包 | v1及v2各7项通过，22值、PDF引用、逐胎尺寸分面及品牌／尺寸关联检索 |
| 原文研究及报告 | 3个PDF chunk、12,748字节，证据准备及Markdown／HTML／PDF导出通过 |
| 资源关闭 | 5服务记录、7记录进程、6端口核对关闭，临时会话、PG口令及TLS私钥已清理 |

PG运行合同为postgres-runtime-schema@4，当前隔离合同摘要cb6c1c738e7cbf5f279088da4e7fcd045804b86515b47489dfd55d5620883a3b，180关系，数据库迁移仍为036。实际部署须按目标catalog与当前API源码生成批准合同。

原文报告先通过本地保存，未授用途时导出返回403。隔离管理员依据CC BY 4.0通过正常text-authorizations入口单独授予original_text_report_export@1后，三种导出通过。真实Provider调用为0。

## 原始失败与待验

- 旧45秒路由两次200后约1.6MB超时，另一32MB路由被8MiB上限拒绝，记录保留。
- 真实材料acceptance.json整体passed=false，前6项通过，整场结构化AI证据包61,421字节超过44,000字节上限，正常接口返回422。PDF原文研究通过另有回执。
- 下一步实现显式成绩选择，贯穿API、共享类型、SDK、Web、绑定与报告回查。原成绩序号及manual_test_*.field_(N+7)关系必须保留，旧缺省引用及指纹须兼容。
- 私有原文研究驱动首次错误预期本地报告创建被阻止，已按实际导出门修正并保留首次失败。Web离线驱动首次将精确JSON数字对象与普通整数直接比较，修正为现有exactSafeInteger后通过。
- 54项历史专业Golden用例依赖缺失的R74私有原件，仍待恢复及完整观察器重放。真实精确SKU、真人Golden、真实Responses／Embeddings、EPREL、Android instrumentation／设备、Native宿主及完整V1 Gate继续待验。

## 回执

下列资料位于Git忽略的.artifacts目录。原件、隔离库、会话及截图不进入仓库，接手clone须重新生成本机验收资料。

| 回执 | SHA-256 |
| --- | --- |
| material-deadline-20261115-final/result.json | e0e9857f24630eba551f5829c383112546de5fcf462075b1c6dff3dd1b25fe33 |
| material-deadline-20261115-pg/resource-audit.json | 628de1cfa0fc0e475561ea906f84001d29abac2ca736810885e069242981eda0 |
| PG report.json | 0b03d640de368cd595e42f952fc987b9b9284fb586e7c5fe084b65cd48c424f2 |
| real-crr2017-20261115-r6/acceptance.json，整体失败 | d90c799d47a740825bbef4febad3fcd030faab6c9fa8fbfcb92ad8d3221e6115 |
| real-crr2017-20261115-r6/research-result.json | 5f2b7dd2e4c75916146c65b4a8b157eed6e51741b5b6c5eab34235220e19ef33 |
| real-crr2017-20261115-r6/offline-web-result.json | ec583e4837f99ae5ad3ff3f72b03012e75382ff35efde0630e10dd62147dc8b6 |
| Web report.json | acb963ce6ca18fafb61528f1c76eb6eff328a383410a02bd00f84049b75a52e3 |
