# 第65轮：同场测试驾驶偏好解读（2026-10-18）

本轮落实原规格第213–225行“个人权重用于推荐解释、不得篡改客观测试排序”的一个实际能力：显式选择本场指标与七维偏好的关联，读取本人的已保存权重，显示覆盖、缺口和可核对的原始证据。它不等于完整车型/SKU推荐、跨来源研究、私人映射模板或完整V1完成。未提交、推送或发布。

## 实现与合同

- 新增只读 `POST /v1/test-events/{event_id}/preference-interpretation?mode=history`，精确六字段；事件和本人偏好均按修订及指纹绑定。匿名按会话、登录按同账户会话聚合，不接收客户端actor或weights。
- [冻结合同](E:/Mix/project/tire-info-manage-sys/docs/plans/2026-10-18-test-preference-interpretation.md)末节明确hash精确输入、来源顺序规范化、逐指标证据DTO、稳定证据ID、404/409/422机器码及判定顺序。偏好fingerprint只在research.preference_state生成，包括null状态，不增数据库列。
- Decimal只比较同指标已录数值；保留原文小数、负零、来源名次与全部并列。缺失不补零，方向未知不推导优劣。覆盖按唯一维度计权，不重新归一；全部null合法。
- 共享类型、SDK与三端共用独立面板接入现有同场比较；内联复用偏好编辑器，不自动填默认权重。结果分开呈现个人解释与来源证据，可重开绑定历史并精确聚焦对应参与者/指标。
- AuthProvider统一owner代次；身份动作开始失效，旧authMe/个人请求不得回填。自动前台重核不打断正在进行的账户写入；失联仍立即清空。桌面/Android入口发出失联及恢复通知，恢复后重新核对依据。
- 独立ultra审查发现并补修“引用只开整场、未定位具体成绩”的缺口；补修后静态复核通过。没有放宽Parser预算或改设备AI封存合同/向量。

## 本轮验证及证据边界

| 范围 | 实际结果 | 证据 |
|---|---|---|
| 纯计算 | 20 passed；大数末位精度、负零并列、0/缺失、0条观察、全null、去重计权、输入闭合、顺序不变与稳定证据 | `.artifacts/r65-preference-1792295850729-f354871b2f2898/pure-final.log`、`pure-final.xml`、退出回执 |
| 新只读API | 50 passed；双binding、撤销、错误顺序、shape、actor隔离/同人多会话、无写SQL/no-store、旧compare兼容 | `.artifacts/review-preference-routes-9f8fee2e051b438187404aef4a76d3e7/verification.json`及after日志/XML |
| 既有偏好回归 | 11 passed；保存/清除、权重校验、并发与主体归属 | 同目录regression日志/XML |
| 公共SDK | 192 Host＋34 decoder、原公共合同及新增偏好类型/注入消费通过 | `.artifacts/runtime/test-preference-frontend-3131a2110699471198d2957cdb74bd60/verification.json` |
| 类型与前端 | 工作区web/desktop/mobile/native-client typecheck通过；两端独立Vite生产构建通过，保留大chunk提示 | 同目录`*-frozen.log`、源码及制品SHA |
| Web生产构建 | 独立Next生产构建exit0，编译、TypeScript及5/5静态页面通过；未执行改写public/sw.js的后置流程 | 前端证据目录的web-production-verification.json与独立构建日志 |
| 私有真实API＋Chrome | 浏览器最终23条断言全部通过（含准备检查和两次事件陈旧重试，不是23个独立场景） | `.artifacts/r65-preference-1792295850729-f354871b2f2898/browser-final.json`及`browser-phase1.json`；1440桌面和390手机截图 |
| 独立审查 | 纯计算、API/fixture、主体/迟到响应和逐证据定位均审读通过 | 本轮三路ultra分工及复核记录 |

浏览器使用隔离context，真实FastAPI与专用SQLite、合成场次；原Cookie不按端口隔离，所以没有在普通工作区profile中验收。观察了全null、显式映射覆盖60/40/40/20、原值38.00/40.0/-0、来源名次、缺失与方向未知、恶意指标按文本显示、内联保存/清除、双陈旧409、键盘Enter重载与精确历史聚焦。手机390和桌面1440无整页横向溢出，表格保留滚动容器。

迟到响应测试先取得真实API响应，再在浏览器注入延迟，验证取消、参测变化及真实账户注册切换后不回填；不是后端Mock，也不是物理设备生命周期证明。断连/恢复使用浏览器连接事件分发验证处理器，未做真实网络故障或原生WebView断连。API单元检查计算无写入；浏览器特意修改事件/偏好制造陈旧，最终3条事件修订、6条偏好修订不能误当作计算写入。

私有fixture的最终回执记录Provider调用、外部网络尝试、Parser子进程均0；该计数只覆盖Python API进程，不证明整个浏览器/开发服务器零外联。API以shutdown实际退出0，私有dev会话已终止。正常数据库、对象目录、服务、官网和真实模型未访问。本轮未迁移正常库、未运行完整API/Worker、未构建或运行原生安装包/凭据/物理设备，未做PWA离线资产更新验收。

## 失败、工装修正与保全

新API的修前红灯（偏好fingerprint缺失、路由404）保留。首轮内存库工装在sandbox系统Temp清理遇到WinError5，改为专用workspace临时SQLite后通过；未改系统ACL。初始sandbox私有服务报告ready但loopback不通，具体会话已终止；同范围服务经审查在宿主运行后连通。没有因超时重复启动未确认的服务。

浏览器工装曾用错误select值（工具需要显示文本）、错误原生dialog/无type属性选择器、未绑定window的fetch辅助方法，以及viewport mobile切换导致文档重载；修正工装并保留后续分阶段回执。初始错误截图不作为结果截图，最终两图已目视检查。没有为通过工装而放宽产品校验。HMR和模拟移动设备导致的文档重载不算产品持久恢复验收。

第63轮2705＋77完整回归与第64轮机器清单都保持历史身份；本轮新增代码之后不重新绑定其哈希或宣称全量通过。完整工作树仍有早先未提交变更，必须与本轮新增实现一起保留。本轮机器清单位于`.artifacts/r65-preference-1792295850729-f354871b2f2898/verification-final-v2.json`，绑定当前源码与明确allowlist证据，不包含私有fixture数据库、会话、凭据或正常data，不是恢复归档。初版回执保留；v2明确旧前端回执的Web pending已被独立生产构建exit0取代，避免把过程状态误读为最终状态。Web构建生成的next-env.d.ts已仅恢复本轮已知变化，Git内容与本轮前HEAD一致；没有改写public/sw.js。

## 后续

本切片已实现并取得上述限定证据，后续仍需真实专业测评样本/人工Golden、原生宿主生命周期矩阵及更广UI自动回归。完整推荐、非SKU关注与相关信息流、更多来源/OE、设备与平台、AI质量和全部发布Gate继续保留；下一切片可推进原规格第213/227–237行的主体私有非SKU兴趣关注及相关变化解释。不得把本轮同场解读当作完整推荐关闭。
