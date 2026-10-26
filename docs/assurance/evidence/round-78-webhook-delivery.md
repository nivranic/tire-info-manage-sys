# 第78轮：Webhook 引用通知与独立复核

2026-10-18；`main`，HEAD `4d0ef60fa2240146113a3fac172759c665cf339f`；未提交／推送。完整原需求和 Goal 保持未完成。

## 实现与边界

原规格第561、597、646行要求对外变化通知、创建 API、HMAC、重试与事件去重。本轮交付受管理 HTTPS 目标、账户所有的订阅追加修订、通知同事务 outbox、签名派送、持久租约和跨进程槽、有限重试、人工重试／取消、不可变尝试／动作回执、UUID只读恢复及三端共享管理面板。

[冻结合同](../../plans/2026-10-18-webhook-delivery.md) SHA `9b835406c1c29adb806ea17f30d74efb1040791b8d75bb64b0f2da293fbf3e93`；[操作者及接收方说明](../../WEBHOOKS.md)、[配置示例](../../webhook-targets.example.json)。默认无目标、订阅暂停，不补旧通知，不隐式发测试消息。仅通知引用外发，来源事实、数值、名称、私人条件、账户ID、原件、URL与凭据不外发。

三个hook为 `monitoring.py`、`recall_monitoring.py`、`interest_events.py`，不在hook内再lock／commit／新Session／联网。轮胎通知为本机共享；召回／兴趣在创建事务冻结未过期账户，后续不按session换绑改投。召回发现候选只有candidate_id，本轮不伪造RecallEvent或纳入该channel。

密钥只取环境变量，指纹绑定配置与密钥承诺。禁止IP及legacy numeric目标，真实connector逐次校验公网解析、TLS、不跟跳转／用代理／解压响应；8秒、64KiB。attempt起点和唯一completion追加，30秒lease fence；旧claim不能覆盖新claim。预算／终态／HTTP状态与账本对账。取消后迟到2xx可记事实，不能复活cancelled。5次自动／人工每次+5总20／TTL7天；正文和编号不重置，接收方按delivery ID去重。

16个未归档订阅／账户、1000未终态投递／订阅，overflow聚合而非逐条制造blocked。历史仍增长。新修订取消旧队列，pause/resume ABA不复活。所有写回冻结 `webhook-operation@1`，`GET /v1/webhook-operations?mode=history&key=...` 只读恢复原动作。修复未知写入A被旧操作B恢复误解锁；owner及选择变化取消旧读取、清数据、拒绝迟到响应。

## 实际验证（分组，不相加为全量）

本轮根：`.artifacts/r78-webhooks-07dbe04ea45042c0bf98f0175fe5dbad/`。

| 证据 | 实际结果与位置 |
|---|---|
| 后端自有最终 | 15 passed／6.41秒／首尾稳定；`targets-9bd3388f4113463894165f10bbda5122/`，含真pre022旧DDL／行保全与故障回滚两例、进程内standalone CLI真队列一例 |
| 独立反例最终 | 125 passed／51.23秒／首尾稳定；`targets-c486858c40ed44bf87d002a9b7b4184e/`；独立简报 `.artifacts/review-r78-e8ebcf926b204e9d87257838a3a62b8d/REVIEW.json` |
| 八模块综合阶段 | 232 passed／95.78秒；`targets-bbcd78771e10467f9f6357f1511d6fce/`；运行中唯一变化为Root runner，阶段bindings不稳定如实保留，不称全仓最终运行 |
| Root补充回归 | 144 passed／87.85秒／首尾稳定；`targets-0f591a441ad7496187d173d7cf98898a/`；core、R77独立反例、召回发现API／执行及账户删除／过期四指定用例；账户CLI子进程未跑 |
| 前端静态 | SDK77、workspace typecheck、三端前端build、R77 SDK59和兴趣SDK回归exit0；`frontend-3d3bafcbaf194811a5971dc2889d3ff7/`；chunk警告保留，非新原生构建 |
| 真ASGI wire | `wire-bec2ab0d53a047c19f25d92f346f2fcd/` 11份响应；受控400→人工重试→204，第二cycle使用now+2秒合成时钟，不证明真实等待／公网连接 |
| SDK核真wire | 上述11份响应通过真实SDK的封闭字段、关联及WebCrypto正文SHA；另7个派生损坏反例拒绝；`frontend-.../wire-validation-b8267626e38f4fc1929ec455fb99a053/`，无新增HTTP |
| 文档签名例 | `receiver-example-validation.json`：UTF-8原字节正例、正文变异、时间过期、attempt变更四项；测试密钥只在内存 |

最终浏览器根：`.artifacts/r78-web-runtime-final-24f848bfe59e4d9f91ecb2e6bd4243c9/`。

| 真实React／HTTP | 实际结果 |
|---|---|
| 桌面1448×904 | `desktop-ui.json` 21项，原脚本字节另存 `ui-scenario-before-revalidation-fix.mjs` |
| 390×844／320×740 | `mobile390-ui.json`／`mobile320-ui.json` 各21项，读取实际device emulation宽度 |
| owner失效及迟到实际GET | `owner-ui.json` 5项 |
| Worker 400→人工重试→204 | `delivery-ui.json` 320视口9项；原delivery ID／body及连续attempt保留，两次生产签名由独立算法核验 |

生产页面、ASGI、SQL、三通知hook与Worker均真实执行，只替换最后接收端边界。`stopped.json` 记录生产／界面输入首尾稳定，受控receiver2次／验签2次，真实receiver及Provider为0，外网／子进程／正常库禁止尝试0。

## 失败记录与保全

保留独立首轮2F／2E：无账本扩张预算、外账户畸形资源请求未先404、过长pytest参数ID使PYTEST_CURRENT_TEST超过Windows环境变量32767字符上限（setup／teardown各1E）；修复后125项稳定重验。第二轮122项及自有初始12项保留。Root首次补充回归因缺R77独立测试专用私根在collection中止，未执行测试；修runner后144项通过；原 `targets-04c170331aae436dab6d48b93e0e5819/` 不覆盖。

初始浏览器根 `.artifacts/r78-web-runtime-46c91c8f51674eb5a60dedaf1197bc24/` 的21项仅502视口阶段。最终根 `mobile390-harness-race.json` 为脚本未等待身份重校验新树的竞态，未提交编辑；修为等待新DOM。窗口resize最小501结果仅 `auxiliary-501-ui.json`，未冒充390。正式390／320均使用实际device emulation。

导入main前绑定双DB、objects／bundles和GUID短私根；护栏拒绝真实网络、子进程、正常DB，Windows精确内部socketpair单列。022仅私库迁移。API HTTP shutdown exit0，Next主动Ctrl+C exit1；`services-closed.json` 核18787／18788监听0。Next生成文件首次严格比较拒写后，确认仅两处完整开发输出路径变化，恢复原295B、SHA `1b59d4c6b83807db275d43f3cf2cc8e9323f465fab764eea091cc5becd5bad37`，等于封存基线及filtered HEAD。

`verify_prior.py` 核R77清单原字节、414既有dirty存在及非本轮范围字节不变、1286历史证据不变。本轮机器清单 `verification-final-v2.json` 以实际封存／终审为准，只是哈希索引，不替代工作区／私库／原件备份。R77及更早不绑定本轮树。

## 未完成与接续

- Webhook真实公网接收端、正式外部API鉴权／注册及cursor、邮件／Push、真实多进程崩溃／TLS／重放防护、长周期lag≤5分钟、PG及原生设备另验。固定受管理目标及offset历史列表不代表完整公开API生产交付。
- 真实专业精确SKU／真人Golden／专业性能C／真实OpenAI Responses／完整V1各Gate未关。R-017仍open-roadmap；R76 release_gate仍inconclusive、wrong_merge_count=null。专业材料provider_use/export=false及R70／R71合同不变。
- 自主选源授权持续，不再索要URL。本轮EPREL正式申请／文档访问／副本删除义务、商业API合同、NHTSA及校准材料身份限制见 `source-research.md`；没有新增capture／许可grant／Golden。
- 接手读本报告、最新清单和原规格，保留全部dirty；不要正常API／Worker smoke触发迁移。继续合法真实材料／模型／平台及发布Gate，不重做捕获、B、评估器、C规格切片或Webhook本机工程。

> 封存补充：独立终审纠正上述Windows环境变量错误说明；首份verification-final.json原字节保留为历史，新v2纳入它及本次事实更正。产品源码与验证结果未改变。
