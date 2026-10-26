# R79 外部 API 凭据、游标与独立复核

用户要求复核接手成果并继续补充优化。本轮先静态核R78清单通过，再对原规格REST P0、API Key、cursor缺口实现首批只读外部能力。完整Goal仍active，不把本轮当V1完成。

合同：[计划](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-external-api.md)、[审查补充](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-external-api-addendum.md)。使用与端点见[EXTERNAL-API.md](E:/Mix/project/tire-info-manage-sys/docs/EXTERNAL-API.md)。

## 交付与补修

- 固定账户所有Key、两项读取scope、首次一次token、16把／1–90天上限、追加签发／撤销／无秘密操作回执、UUID恢复；HTTP和CLI密码重置同事务撤销。023只追加迁移，在私库核原DDL和全部旧行保全、故障回滚。
- 独立Bearer namespace，不创建／续期Cookie；Cookie和Bearer不可相互借权。逐Key持久分钟计数、签名15分钟cursor、目录摘要变更拒绝、本人冻结owner投递历史及详情。沿用本机访问边界，不开放公网。
- DTO／独立SDK／三端共享管理面板。界面单次显示、原始token不进存储、未知写只读恢复、owner epoch隔离迟到响应。主动关闭显示不会误报密钥失落；真正失落才提示撤销重建。
- 两位复用ultra agent分别负责后端与独立反例，Root负责SDK／UI／真实HTTP和浏览器。独立审查促成cursor改用owner HMAC承诺值、合法80字符来源ID及500字符上限对齐；Root另修SDK按Unicode码点计数，80／500个emoji正例通过。

## 验证（分组有重叠，不相加为全量）

证据根：`.artifacts/r79-external-api-e713553f97c5473f99f030e6b6d9d3aa/`。

| 实际执行 | 结果与回执 |
|---|---|
| 后端自有 | 29P，`targets-eb32cf0aa43949ebbc503726b79aa25c/`；并发同UUID只一次token、重置事务、023保全／回滚等 |
| 独立反例 | 73P，`targets-ea279d0d6a254257825f07b8898b8ade/`；scope／Cookie／未知路由、cursor跨Key／route／limit／过滤／TTL／隐私、60限额及16并发上限、换绑／删户／迁移 |
| 后端相关回归 | 51P，`targets-3f69b5df50fc4e69b767065f271b7594/` |
| Root补充 | 170P，`targets-db74f5da657e4503b8938c1aecb0e162/`；core、旧R78独立反例与账户生命周期非CLI项。没有运行账户CLI子进程 |
| SDK | 新43项及旧Webhook77项，`sdk-final.log`／`sdk-webhooks-final.log`；纯合成注入传输 |
| 真HTTP＋SDK回放 | `wire-fbd49530/wire.json`为真实loopback HTTP 11检查／9份无凭据响应；`sdk-wire-final.log`读取9响应及4派生损坏反例，13通过。SDK回放是离线注入，不是再次HTTP |
| 类型与构建 | workspace typecheck、Web／桌面／移动前端build全部exit0；最终UI提示补修后使用`typecheck-v2.log`和`build-*-v2.log`，旧阶段日志保留。Vite大chunk警告仍在，不作性能Gate通过证明 |
| React实际操作 | `browser-desktop-v2.json`实际1440×900、`browser-390-v2.json`实际390×844、`browser-320-v2.json`实际320×740，各22项；真实创建／撤销、2页实际通知、未知响应GET恢复、迟到响应隔离、存储无token与无横向溢出 |

所有目标pytest回执均源码首尾稳定、外网／子进程／正常DB禁止尝试0。最终浏览器服务根 `.artifacts/r79-web-runtime-v2-0a13df280b194db18b7b5d0aa2672b03/` 的started／stopped记录运行输入及审计；真实Provider／公网receiver／受控receiver调用均0，所有浏览器测试Key已撤销，API以HTTP正常关闭exit0；Next主动Ctrl+C exit1，不是构建失败。

自有29项回执捕获过当时尚在编写的独立review测试库存，该未执行文件在自有运行之后继续变化；它与当前的唯一绑定差异为`test_external_api_review.py`，不是生产源码或自有执行目标。独立73项、相关51项和Root170项的全部绑定均匹配当前；最终review文件另由独立73项实际执行验证。新清单逐阶段记录这项差异，没有把阶段库存称当前完整源码验收。

## 保留的失败与证据边界

首轮SDK测试误把Headers当普通对象；后端自有首轮helper把空scope替换成默认scope；浏览器脚本使用`#watch`而非`#/watch`、未聚焦的泛型input事件未更新React、身份刷新未等待新一轮ready。修正工装后验证通过，不把这些称产品修复。后端首轮失败repr含本轮随机测试口令，已对该本轮日志精确脱敏并加安全repr，失败栈与redaction说明保留；不保全秘密原文。

`sdk-wire-stage-failure.log`保留负例把格式合法opaque游标误当SDK必须拒绝的失败；改为格式非法游标后通过，服务端HMAC验证未放宽。首批各21项浏览器报告和首个运行根保留为UI提示补修前阶段；首个运行根另有SDK／UI源码变化，不能当最终稳定输入。其后第一个final运行根源码稳定但仍绑定提示补修前UI；当前终态使用v2运行根和各22项。

初始R78 v2为330445B，SHA `53c1e49dbaceb8fae904ab3038170d92177313e3fd81eaf91ab7da3eeef3f468`，静态audit确认1014源码／440dirty／52文档／68证据。R79基线`baseline.json`覆盖1074个非忽略文件，SHA `950675a479a980e7f8189f0bcb920f7ee253121bf9901426507a3a4110a0a672`。后续变化按R79所有权比较，不能要求R78旧清单仍等于新dirty集合。最终机器入口为本根`verification-final.json`，SHA索引不是工作区／私库／原件备份。

未验证：PG执行、生产TLS／代理／IAM／RLS、真多进程崩溃与长期lag、真实Responses、专业精确SKU／真人Golden、六平台原生／WCAG／完整性能发布Gate。Key限额不代替网关，首批外部只读端点不代替完整公共CRUD／查询／AI。正常库未启动迁移023；未提交、推送或部署。下一步按原规格继续真实数据和其余公共域／发布缺口，不重新制造已交付捕获、B、评估器、C规格域或本轮Key基础设施。
