# Production Web Theme Hydration Verification Plan

**Goal:** 在真实 Next 生产 HTTP 页面中验证 R124 的四态 theme-color 同步与现有工作台状态保全，补齐组件文档和静态构建不能证明的 hydration 边界。

**Architecture:** 复用已通过且源仍匹配的 R124 b124 构建、受审 R118 生产监听器与 R122 全新合成私槽 fixture。新 QA 由 R123 稳定生产回归增量派生，在实际主题断言路径中同时检查唯一无 media meta 和对应颜色；原工装及回执保留。

**Tech Stack:** 当前 Next 16.3.6 / React、Playwright 1.63.0 / Chromium headless1243、既有 Python owned-process supervisor。无产品、依赖、迁移或 API 合同修改。

---

## 冻结范围

本轮按持续实施授权直接执行。当前 HANDOFF 160987 B / SHA `5389b723f84d87ca5b80344dbca57e14367e650183ec8227ae4ea853a1095f58` 已原字节备份于 `.artifacts/r125-web-theme-hydration-20261022/before/docs/HANDOFF.md`。使用 R124 build report `2f5d44f67ac12c20779f6a60c0ec435d315776e5f957040ff5fff2adb480beb9`，运行前/后按原 freeze 校验产品、依赖和产物，不以旧构建证明新代码。

产品不计划修改；若出现确认产品问题，先保存具名 before、修正最小差异并重新构建，禁止使用失配旧产物。正常/保留 SQLite、默认 API、真实 Provider 均不打开。fixture 仅新合成私槽；EPREL 无 Key 不再询问。

## 任务与 ownership

1. QA worker 仅新增 `scripts/web_theme_color_web_ui_qa.mjs`，从已审 R123 QA 增量派生。保留稳定业务回归及现有 runtime / 请求 / 侧日志 / 自然关闭边界；槽和 schema 改为 R125。实际主题 helper 同时等待根属性、控件、唯一无 media meta 与颜色一致，记录可核对 observation，不能仅复述静态映射。
2. Host worker 仅新增 `.artifacts/r125-web-theme-hydration-20261022/run-ui-host.py`。复用已审监听器和私槽 fixture，自新16位批次启动/停止，沿用 build SHA、源稳定、精确 owned 进程、自然关闭及停止请求合同。
3. 独立 reviewer 只读核两项增量与执行输入；另只读调查 SW 注册、worker 与现有真实离线证据，给出后续缺口。不读取作者未 STOP 的半成品，不自行运行验证。
4. Root 独占所有正式执行、服务、浏览器、看图、证据及 HANDOFF 应用。所有执行者不是独自在代码库，不覆盖他人 dirty，不 commit/push/reset/stash/clean。使用 PowerShell7 与精确 Node/Python 路径。

## 正式验证

- 区分服务端响应的唯一浅色初始 meta 与客户端完成 hydration 后按保存偏好/系统解析的 meta。实际生产页面通过主题控件与四个命令切换，System真实 media emulation，旧 light/dark、非法值和重载。
- 在新 layout 中保留查询待选、比较、证据 DOM/焦点、未提交价格表单节点/值/焦点；确认没有价格写入或主题触发的新业务 POST。合成数据与真实厂商/真人 Golden 分开。
- 完整保留原失败批，最终仅取同批通过记录；Root查看最终截图。记录 console/page/unexpected/cleanup、source稳定和所有 owned 服务/浏览器关闭。fixture汇总关闭不等于逐DBAPI句柄关闭或私库删除，Job/guard不是OS sandbox。
- 归档 `docs/assurance/evidence/round-125-web-theme-hydration.md` 并前置 HANDOFF，原160987 B尾文完整保留。本轮只需相关集成，不重跑构建、无关 API/SDK/native 全套。

## 剩余边界

本轮 SW 继续按现 QA 显式阻止，不能计为 PWA 离线或安装验收。生产 hydration/DOM meta正确仍不证明真实浏览器栏取色、Android/iOS已安装应用启动或原生系统栏。后续按只读调查结果推进真实 headless SW 控制与离线导航，并继续留账安装态/设备、专业材料/SKU/真人Golden、Provider/Responses、正常库升级、PG和完整无障碍；完整 V1 保持 active。
