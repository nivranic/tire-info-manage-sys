# Web核心流程无障碍复核与修复计划

## 目标与依据

推进原规格WCAG 2.2 AA核心流程Gate，先覆盖Web的首页、轮胎查询、知识检索、AI分析、报告和账户窗口。复用现有生产构建、主题设置和隔离合成API，以实际页面失败记录定位修改，验证使用Lighthouse snapshot和键盘操作。

方案采用brainstorming与writing-plans流程，沿既有main实施。技术栈为现有React、Next.js及共享CSS，前端主题规则与自动测试沿用当前目录。

基线Lighthouse首页浅色和深色均为96。浅色报告35个对比度节点，涉及次要文字、导航透明度和强调色。深色报告装饰序号对比度1.66。两种主题均报告品牌链接可访问名称与可见文字不匹配。原报告保留于本机 `.artifacts/web-a11y-20261113/`。

## 实施与验证顺序

1. 新增 `apps/web/tests/theme-contrast.test.ts`，按实际使用的主题文字／背景组合及导航小字透明度计算WCAG对比度，先取得基线失败。
2. 在 `apps/web/app/globals.css` 调整有失败证据的浅色文字色值、导航小字和输入提示文字透明度，复用已有主题变量。在 `apps/web/components/workbench.tsx` 对齐品牌链接名称，移除视图标题旁的装饰序号及对应样式。随后实际账户审计发现按钮组使用tablist却没有tab子角色，已按现有aria-pressed按钮行为改为group。键盘复现发现跳过导航会改写Hash路由，已沿用主区域ID实现保留路由的焦点跳转。
3. 运行Web测试、Web／Desktop／Mobile类型检查和独立生产构建。通过生产浏览器复验三个显式主题、320／390／1440像素、知识检索与账户表单、AI证据与报告，以及键盘跳过导航、命令面板和模态焦点。
4. 根据后续实际报告修正所覆盖流程中的语义、对比度和焦点缺陷，记录最终结果与未执行范围，更新当前交接卡及续作记录。

```powershell
npm run test --workspace @tire/web
npm run typecheck --workspace @tire/web
npm run typecheck --workspace @tire/desktop
npm run typecheck --workspace @tire/mobile
```

Lighthouse评分和上述限定流程结果各自留档。完整读屏、全部业务状态、原生平台及完整V1 Gate继续按其实际范围验收。

## 原规格重排范围核对

原规格检索顺序包含Authority／Variant／Region／Freshness重排，语义重排模型属于此前Agent追加的实施选项。当前已有字段权威、精确条件、地区偏好及时间排序，模型语义质量仍需代表性真实材料和实际Provider验证。交接卡中的必做排期按原规格更正。

## 执行结果

已调整浅色文字及强调色、导航与输入提示透明度，补齐品牌名称、账户按钮组语义、保留Hash路由的跳过导航和AI完成态来源标题层级。新增5项对比度回归，最终Web55／55、Web／Desktop／Mobile类型和生产构建均通过。PWA白名单19项，构建生成导入已恢复。

14份Lighthouse快照无障碍100分。r2覆盖三主题首页及查询／回退，r4覆盖账户、查询结果、知识、用途、AI准备、保存及报告。末次标题修正后的r5完成三端类型、Web测试、生产构建及历史AI完成态快照。22项r4功能与键盘检查覆盖七主视图跳过导航、车库深链接刷新、命令面板、账户、HTML／PDF正文选择、合成流式、保存焦点归还与冻结报告。320／390／1440像素报告均无横向溢出。

原始失败保留。首页浅／深色96、账户88及AI完成态98均有原报告。跳过导航首版误用回调ref造成TS2339，已按现有主区域ID修正，r4／r5通过。浏览器探针观察问题及复验说明见 `browser-r4.json`。

最终夹具为真实隔离PG、合成来源及合成Responses Provider。1次合成调用、600 tokens及1份报告，真实Provider和外网尝试0。两个隔离PG、API／Web、相关进程和端口已关闭，浏览器测试页已关闭。回执位于 `.artifacts/web-a11y-20261113/summary-final.json` 和 `closure-final.json`。

读屏、全部业务状态、跨浏览器、原生平台及完整WCAG 2.2 AA Gate继续开放。正文后端269项API、58项PG及153表恢复属于此前 `b2d433a` 阶段，本轮新增验证范围见上述记录。
