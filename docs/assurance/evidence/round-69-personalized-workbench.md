# 第69轮：交接复核、个人历史信息流与已审轴位候选

复核结论：交接资料整理完成不代表完整需求完成。R68源码及证据回执已现场重新核对；本轮补齐独立研究首页、本人当前兴趣的历史信息流和已审精确轴位候选，修复完整冻结详情校验不足。**完整性能推荐、AI推荐与完整V1仍未完成，Goal保持active。**未提交、推送、发布或迁移正常库。

## 实现与边界

[冻结合同与实施计划](../../plans/2026-10-18-personalized-workbench.md)依据原规格第213、225、227–237、658、826–832行。原文仍是需求资料，不额外授权来源采集、真实模型调用或部署。

- 新增 `POST /v1/personal-feed/preview?mode=history`：按本人当前启用兴趣分别匹配九域原始历史，包含订阅前记录。同事件合并展示全部独立命中/待核对理由，不跨关注、前后侧或来源拼条件；不补发通知、不创建冻结事件或业务审计。无有效关注真实空态。每页1–50条是扫描预算，空匹配页有游标仍可续读。
- 游标HMAC签名，绑定隐藏主体、完整当前兴趣集合及名称/修订、领域、预算、策略与全部候选成员摘要；1小时有效，进程重启失效。兴趣或成员变化（含并列时间插入、迟到回填）明确拒绝旧游标，首尾重新读取核对。不声称持久数据库快照。100条启用关注/50000条候选元数据是明确容量上限，不静默截断完整性。
- 新增 `POST /v1/fitment-candidates/preview?mode=history`：显式选择车型快照、配置、轮毂和轴位，只收仍通过严格当前门禁的人工已审关系。最多检查200条，超限声明truncated；同SKU多关系合并但保留各自原修订、双侧证据和未知检查。前轴不借后轴、代际不混用，恢复SKU、身份clear和目录重入不复活旧审核。同事实的新车型元数据快照可使用旧已审关系，旧关系仍保留原快照，不篡改为新快照。
- 本人偏好绑定服务端修订与指纹，只组织七维研究重点。`performance_score=null`、`ranking=not_computed`、`official_oe=not_established`。没有参测对象到精确SKU的可复核桥，不能依据同名/尺寸移植成绩，不能按覆盖率或缺失补零打分，也不构建跨场总榜。共享车库/保存比较不作为私人画像。
- 三端共用独立 `#/home`，默认首页、保留 `#/query` 与原深链，移动七项短导航。复用既有FrozenEvent/HistoricalEvidence原版本reader；私有树以ownerEpoch重建，所有读取有abort/请求代次/完成时主体检查。兴趣筛选、候选范围和409变化均清除旧结果。
- 实际看图后将宽屏信息流与候选改为1.25:1并排，介绍区跨两列；≤1100px恢复单列。该合成1440页面的候选区顶端由2508px移至450px，未改变任何候选排序或数据合同。

## 发现与修复

确认 **1个实现根因、3个损坏反例**：初版仅校验部分摘要标签，关系行中被冻结的facts、locator或完整vehicle详情被修改时仍可能进入输出。现将双侧冻结详情与从原快照/实际事实重建的canonical完整对象逐项核对，并核验当前车型原文及结构化事实哈希；损坏关系带原因排除，不输出伪造详情，不改写原记录。

坏stored InterestEvent还核对事件ID、domain、schema、行指纹及payload去event_hash后的digest；校验失败整页明确不可用，不作为命中结果。

其他失败与修复没有冒充产品缺陷：独立九域合成用例曾把Verification设在快照观察时间微秒之后，历史freezer正确判indeterminate；目录反例曾因整目录替换触发质量隔离，后改为4成员移除1成员。均只修fixture，保留原规则。Root第一轮API QA额外加入测试机构兴趣，使无机构证据的轮胎成为待核对项，原数量预期错误，移除该无关条件后重跑；旧失败留存。查询深链首次用既有营销h1判断页面名称也产生错误预期，随后实际确认移动查询激活、尺寸预填且首页隐藏，无产品改动。

## 实际验证（各阶段分别计数）

| 阶段 | 实际结果与证据 |
|---|---|
| R68修改前复核 | 860源码、241展开dirty、244证据、13文档、237链接、15风险owner一致；旧证据原字节保留 |
| 后端目标/受影响回归 | 最终195通过、0失败/错误、1 deselected，exit0，27具名文件SHA前后稳定；仅需要子进程的非Web初始化用例未选。见[后端报告](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/backend/REPORT.md)与[最终回执](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/backend/regression-61c66fb51290451397b143aabdbb98a0/verification.json) |
| 独立反例 | 最终同一次69通过、0失败/错误/跳过，源码前后稳定。早期46红、59通过/4失败、68通过/1fixture失败及目录目标1通过分别保留，不累加。见[独立报告](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/review/R69-REVIEW.md)与[机器审查](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/review/R69-AUDIT.json) |
| SDK/类型/导航 | 注入SDK合同、workspace typecheck分别exit0，纯路由6/6；检查后只有CSS改动，19个代码/配置源保持SHA，后续CSS单独构建验证。见[检查回执](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/frontend/verification.json) |
| 最终三端前端生产构建 | 布局优化后Web/Desktop/Mobile分别exit0、20源无运行漂移、23制品哈希，Web静态5/5、PWA18项allowlist，7生成文件恢复；已有大chunk提示保留。首批单列构建按历史身份保留。见[最终构建回执](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/builds-layout/verification.json) |
| 真实私有HTTP | 39条断言通过，未mock请求/响应；订阅前历史、多关注合并、游标篡改/兴趣变化/来源追加失效、候选pending/已审、轴位/偏好门禁、原版本重开、不补发与护栏。见[API回执](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/runtime/api-qa-final.json) |
| 最终真实浏览器 | 1440×1000桌面与390×844手机视口各24条断言通过；实际空扫描页仍可继续、恶意名称按文本、原版本reader、未知不补零、轴位切换清旧值、无候选真空态。真实HTTP响应延迟配合合成session-unavailable事件验证迟到结果不恢复；不等同真实网络/原生生命周期。两视口无整页横向溢出，截图在聊天中目视，未归档截图文件。见[桌面回执](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/runtime/ui-desktop-1440-layout.json)、[手机回执](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/runtime/ui-mobile-390-layout.json)及[布局测量](../../../.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/runtime/layout-review.json) |

断言数不是独立业务场景数，前端生产构建不是原生运行验收。独立运行绑定的计划随后仅增加本终态说明；产品/测试代码未因此变化。第一批源码/构建/窗口1441测量不能替代最终布局1440/390结果。

## 资源、数据与保全

全部执行用新GUID私有SQLite/对象/Parser bundle，导入应用前关闭AI/Embeddings并清理宿主配置；外联、Provider、Parser子进程和正常库尝试计数均0，仅覆盖相应进程。后端回归与浏览器fixture的护栏范围分别记录，不扩大为整个工作站。Parser预算保持8秒/并发2/CPU5秒/384MiB。

首次沙箱启动虽监听但浏览器/宿主HTTP超时，两测试进程停止exit1；以相同隔离配置在宿主模式重启成功，未修改产品网络策略。Chrome MCP的指定输出文件因其工作区根配置不匹配被拒，随后改用内联执行并在当前工作区保存脱敏结果，无放宽权限。首个宿主fixture因QA条件纠正HTTP200正常停机exit0；最终API shutdown HTTP200且实测exit0。两次宿主Next均主动Ctrl+C exit1。宿主已确认8969/3369无监听；关闭测试页14，保留原空白页12；next-env/tsconfig/sw按QA前SHA恢复，构建7文件与运行3文件分别记账。

当前机器清单：`.artifacts/r69-personalized-workbench-dc2120e1121243b99106c8f2e2506b00/verification-final.json`。它绑定当前工作树和明确证据，不是文件归档或私有资料备份；移交仍须携带未提交/未跟踪文件和忽略证据。R68的244份历史证据须逐字节保持。

## 尚未关闭

本轮只关闭“当前本人兴趣的九域本地历史流”和“已审轴位候选”子范围。性能/AI推荐还缺可复核的TestEvent参测对象↔精确SKU证据桥、代表性真实样本、明确比较语义与真实模型质量验收。更广泛信息流/事件、资料归属和跨设备能力仍保留；390顶栏仍有既有文本拥挤折行，完整移动体验/无障碍与自动UI回归继续列入风险。

完整API/Worker、真实PG、正常库迁移、真实来源/模型、原生宿主/物理设备、macOS/iOS、Golden/首代SU7/OE、来源许可、生产安全和全部发布Gate均未由本轮验收。现有同cookie账户聚合政策不等于服务器级账户隔离。下一步先冻结性能推荐所需的精确证据桥与覆盖/缺口合同，再推进推荐解释；不把适配候选改名成完整推荐。
