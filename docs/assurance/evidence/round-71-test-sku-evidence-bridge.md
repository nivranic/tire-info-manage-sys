# 第71轮：测试参测对象与精确 SKU 人工证据桥

**结论：有限人工证据桥的后端、SDK、三端共享界面与私有HTTP/浏览器工作流已实现并取得限定验证。来源真实性、代表性专业Golden、性能/AI推荐与完整V1仍未完成。未提交、推送或发布。**

精确合同见[实施计划](../../plans/2026-10-18-test-sku-evidence-bridge.md)。修改前现场复核R70清单880源、18文档、179证据一致；原R70封存不改写，不绑定本轮修改后的树。

## 实际交付

- 独立Link和追加Revision，固定事件/participant范围；不向Participant直接写variant_id，不修改来源成绩、厂商事实或R65偏好解读。新增019仅在GUID私有库验证。
- 既有PDF原件→双侧原证据→逐身份字段声明/页/区域/短引文→预览→待审→不同管理员账户复核→修订/撤销/恢复与精确历史。原件、元数据、引文、完整事件/SKU成员/FactVersion均校验并冻结。
- 材料固定`operator_supplied/unverified/local_workspace`，原事件仍为人工转录未核验；等级`source_explicit_identifiers_in_supplied_material`仅指供审材料所载，最高适用性`conditional_reviewed_transcription`。双账户不证明两个真人独立，下载不证明阅读或出版物真伪；不向模型发送材料、不新增导出授权。
- review按稳定user.id拒绝同账户异session自审，必须引用当前声明；恢复不能换掉原声明者或复活旧审核。UUID按账户幂等，响应丢失后保留原payload和UUID核对；前端按稳定账户/事件/participant找回跨修订的悬而未决请求。
- 当前适用性与原历史分开。事件/身份/生命周期/目录ABA均失效；participant被移除后旧证据仍能重开。元数据刷新及无关性能事实改变不冒充身份变化。原件/事实/冻结记录损坏明确拒绝，不能改读当前版本。
- 材料原值不从SKU预填，布尔值三态；未知/冲突、共享未核验边界、来源版本和当前失效原因显式呈现。R70测试AI仍只允许服务器事实摘录。

## 实际验证（分阶段，不相加为全量）

证据根：`.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df`。

| 范围 | 实际观察与入口 |
|---|---|
| 最终后端相关回归 | **110 passed / 1具名deselected**，exit0，27源SHA稳定；含35新桥、旧兴趣迁移原5项、TestEvent/fitment/R70目标。[后端报告](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/backend/REPORT.md)、[源码冻结](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/backend/source-freeze.json)。未选旧非Web subprocess用例，另以fresh进程直接初始化验证，无main import，19版本幂等/旧marker保留 |
| 独立对抗 | 兼容修补前119项通过；最终改动相关13项另行通过，26具名输入稳定。不是同次132项全量。[独立报告](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/review/REVIEW.md)、[审计](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/review/AUDIT.json) |
| SDK / 公共类型 | 12项注入transport合同、公开类型及专用UI noEmit分别通过，8源稳定；listing不含history、read有精确history的DTO差异已核。[前端交付](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/frontend/FRONTEND-DELIVERY.md) |
| 工作区与构建 | workspace typecheck、Web/Desktop/Mobile前端生产构建分别exit0，291相关源运行前后及运行时结束后均一致；7生成文件按字节恢复。[构建回执](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/frontend-build/verification.json) |
| 真实私有HTTP | **34条断言**通过：原件上传/下载SHA与大小、完整预览、双账户/权限、自审拒绝、幂等、精确历史、事件ABA失效、不改厂商事实和护栏零尝试。[API终态](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/runtime-final/api-qa-final.json) |
| 桌面实际React | **34条断言**通过，实测1441×934。全身份字段照录→改动清预览→真实HTTP已提交后注入丢响应→原UUID找回且仅新增一修订→实际界面换管理员→下载校验后另行人工确认→复核→历史→真实事件变化失效。[UI终态](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/runtime-final/ui-qa-final.json) |
| 窄屏实际React | 390×844及320×740分别**11条布局/读取断言**通过；现存关系和完整13字段编辑器、双locator、原false、失效/来源边界、历史、无整页溢出及可见表单按钮≥44px。没有在各手机视口重复创建/审核全流程。[390](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/runtime-final/mobile-390-result.json)、[320](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/runtime-final/mobile-320-result.json) |

真实的是生产HTTP端点和React工作流；PDF与身份/事件都是项目编写的合成材料，未调用来源或模型。断言数不是独立业务场景数；前端构建/手机视口不等于原生设备验收。截图由浏览器原生返回并目视检查，没有落盘截图文件。

## 发现与修复、失败保留

- 原实现没有新工作流路由的3个红例保留。合法participant移除后，当前binding须允许缺失并给出失效原因，历史冻结体仍严格验证；已补修。
- 旧pre016迁移测试发现当前Base.metadata建了新表但无触发器，019补入导致旧schema原样断言失败。仅在新表after_create幂等安装相同保护，019继续幂等安装；旧测试和预期未改，最终原5项通过。PG仅有DDL编译验证，未运行PG。
- owner一次移除participant夹具遗漏孤立metric，正确被EventPayload拒绝；只修合法夹具。独立runner首次Popen函数替换破坏Windows asyncio子类定义，只修runner并保留bootstrap失败。
- 独立首次119项均在PDF上传setup因沙盒os.link WinError5失败，尚未执行产品断言。保留probe/119errors/JUnit；相同私库/网络/进程护栏在宿主运行通过，没有更改产品原件写入校验。
- Next从仓根带project参数首启MODULE_NOT_FOUND；换Web工作目录后沙盒实例监听但HTTP超时，确认原进程退出后同配置宿主启动可达。没有修改产品Next配置。浏览器工具的本地文件路径权限拒绝，改由工作区工具读取脚本后内联执行并保存原生工具结果。
- UI首脚本误选值为`|`的占位option，尚未提交写入；仅修QA为精确匹配snapshot+fact两个ID。窄屏首次脚本未重新定位详情节点，重新打开既有记录后通过。上述失败与最终结果均保留，不计作额外通过。

## 资源、保全与后续

两次私有API均HTTP shutdown且观察exit0；初次只启动，兼容修补前停止且未跑QA。最终API15具名源前后稳定，外联/子进程/正常库尝试0。沙盒Next与宿主Next均主动停止并观察exit1；宿主确认8971/3372无监听，测试页16关闭、原空白页12保留，运行3配置按字节恢复。[完成回执](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/completion.json)、[端口](../../../.artifacts/r71-test-sku-bridge-7624690bfc8e4cf6b490ef19559734df/runtime-final/host-ports-stopped.json)。GUID私有SQLite/对象/bundle继续保留取证，未清理正常数据。

当前机器清单入口为本轮根`verification-final.json`，由实际生成及独立核对决定；它记录SHA而不是文件归档或私有数据备份。历史R70及更早证据保持原字节。

**下一步：**接入有许可、固定来源策略的专业测试原件捕获，保存真实来源实体字节和来源策略记录；建立代表性测试对象↔精确SKU人工Golden。在证据支持下再冻结同场条件化解释B与专用AI推荐C，保留原成绩名次、未知、场次条件及权重解释边界。不得凭本轮人工桥解除R70事实摘录限制。

完整API/Worker全量、PG运行、真实来源/Provider、正常库019保全/迁移、新原生设备及其余V1发布Gate本轮均未验收；原Goal保持active。
