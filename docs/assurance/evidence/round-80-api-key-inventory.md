# 第80轮：有效密钥全集与签发历史分页

日期：2026-10-19，Asia/Hong_Kong。原完整V1目标仍active；本轮为凭据库存管理补修，未提交、推送或部署。

## 结论与变化

R79管理列表只返回最近100条。实际复现：先签发一把有效Key，再签发并撤销101把，旧Key从旧列表消失，用户无法在原界面撤销它。R80保留旧wire兼容，新增完整有效全集和独立完整历史分页；旧有效Key可见、可经原撤销写合同撤销。

- `GET /v1/api-keys/active?mode=history`：完整最多16把有效Key，17条探异常，超限409且不截断。
- `GET /v1/api-key-history?mode=history&limit=20&cursor=…`：全部签发记录倒序keyset，单页1–100、无total、末页cursor=null。首把不可变Key作为签名anchor，固定900秒窗口；anchor撤销／到期不使翻页中断。
- 两端点都要求有效登录Cookie和单个 `X-Tire-Expected-Account`；账户不符409，头缺失／非法／重复422，匿名／会话失效401。头是提示而非凭据。无新模型、迁移或配置秘密。
- 每页单SQL outer join读取Key和撤销投影，渲染时不重读可变状态。历史是有上界窗口，撤销metadata按每页实际读取，不宣称跨请求数据库快照。
- SDK闭合校验DTO、ID唯一、页尺寸和微秒级时间／倒序。共享界面分开显示有效全集与历史单页，历史失败不隐藏有效列表；刷新／写成功重开窗口，abort和owner epoch隔离迟到结果。保留一次token和未知写操作的GET恢复。
- TS桥、桌面Rust和Android Java只在两个精确canonical GET路径允许该账户头，值限1–64安全ASCII；其他路由及凭据／任意头继续拒绝。未扩大Java三头预算。

合同：[冻结计划及原生补充](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-api-key-inventory.md)。使用：[EXTERNAL-API.md](E:/Mix/project/tire-info-manage-sys/docs/EXTERNAL-API.md)。

## 实际验证与边界

各组独立，不相加为全量或完整产品验收。

| 验证 | 结果 | 证据范围 |
|---|---|---|
| 后端自有 | 17通过 | GUID私库ASGI；101遮旧、102条遍历、17active异常、joined并发投影等 |
| 后端独立 | 72通过 | 独立改签cursor、固定TTL、微秒排序、anchor撤销／到期、账户／会话与单SQL状态反例 |
| R79相关回归 | 102通过 | 原自有与独立Key／鉴权模块 |
| SDK | 新47、旧43分别通过 | 合成注入transport；微秒有效期、倒序、闭合DTO、非法头／参数等 |
| 真loopback HTTP | 14检查、8份metadata响应 | 102条唯一记录／6页完整历史，旧Key可见、header非凭据、错误码及全部有效Key清理 |
| 实际wire回放SDK | 8响应＋4反例，12通过 | 保存响应逐份注入SDK，核实际请求路径／账户头／cursor／limit；SDK直接联网0 |
| 实际React | 1440×900：45；390×844：50；320×740：55通过 | 均实际HTTP／React事件；含每页断言，因同私库追加历史，页数不同；单次只展示20条 |
| Native策略 | TS9、Java5、Rust10分别通过 | TS IPC注入、JDK21纯JUnit、offline隔离Rust安全harness；不等于应用／设备运行 |
| 最终构建 | workspace类型、三端前端build通过 | 在三个Native生产文件静止后重新验证；早期build仅阶段记录 |

React实际覆盖旧有效Key可见并撤销、到最早历史、窗口过期提示和显式重读、历史失败保留active、刷新时旧页迟到、真实账户换绑时旧页迟到、一次token只在内存、写响应失落只GET恢复、迟到写不恢复旧账户界面，以及三个宽度无横溢出。过期UI故障由测试包装在真实HTTP返回后注入409；真正900秒期限由后端受控时钟测试验证，未等待15分钟。

API运行273项输入首尾稳定，禁止外网／子进程／正常库访问尝试0；真实Provider、真实receiver、受控receiver调用均0。此处子进程0只指API护栏；Node、JVM和Rust验证本身是工具启动的进程。SQL并发测试是在同进程WAL另一连接事件注入，不能称真多进程并发。

自有API／Next已关闭，18881／18882监听0；浏览器回blank，emulation清除。Next声明仅在完整受控目录前缀替换后全字节等于原件时恢复，295B，SHA `1b59d4c6b83807db275d43f3cf2cc8e9323f465fab764eea091cc5becd5bad37`。首次恢复检查假设了原dev目录，严格比较拒绝；读取原件后纠正为`.next/`再恢复，没有盲覆盖。

浏览器MCP首次本地filePath被其workspace映射拒绝，未执行QA；改用内联执行并由工具保存无凭据返回。首个桌面通过未保存回执，因此另执行最终桌面验证留档；不把两次相加。Native初始TS loader循环exit13、红测6过3失败、Rust未选默认工具链exit1均保留为阶段回执；修复测试加载后及选择已安装1.95.0工具链通过，无下载或持久工具链配置。

## 机器入口与复核

- 本轮基线／测试／HTTP／浏览器／构建／封存：`.artifacts/r80-key-inventory-7fb3f0a9041e49b98c66012addff488a/`，最终入口`verification-final.json`，生成后必须独立审计，不预认成功。
- 后端独立回执：上述目录`review-728db9b6ee234c85badd2014ce69944e/REVIEW.json`。
- Native独立分组回执：`.artifacts/r80-native-2b63376f017c4a5ba149544250b2337d/verification.json`及`REVIEW.md`。
- 私有HTTP运行首尾：`.artifacts/r80-web-runtime-9eb0bf188f4b4ae395580263061c720c/started.json`、`stopped.json`。
- R79旧清单与证据保持原字节，不要求它等于新增R80后的全工作区。R80以新基线记录授权变化，无基线文件删除；清单不能代替完整工作区／私库／原件备份。

## 未完成项及后续

旧最近100条API仍保留兼容，外部调用方应改用新库存接口；新界面和清理脚本已切换。历史上界窗口不提供精确数据库快照，且不提供total。原生运行和完整无障碍仍各自验收。

完整V1仍未完成：真实专业精确SKU／外部真人Golden、完整专业性能C／真实OpenAI Responses、P0来源覆盖／EPREL、完整外部事实查询／CRUD／AI、生产PG／TLS／IAM和六平台／WCAG等。正常数据库未启动迁移023，不因本轮无迁移而宣称原正常库已更新。用户已授权自主选公开合法来源，不再等待用户指定URL。

接手先核本轮清单与当前dirty，继续逐项关闭原规格Gate；优先自主核验有合法原件和完整精确身份的专业测试材料，建立外部人工审核证据，再按许可／预算开展真实Responses验收。不要重做R72捕获、R75 B连接层、R76评估器、R77规格域C、R78 Webhook或R79/80凭据库存。所有未知dirty保留，不reset／clean／stash，不自动提交推送。
