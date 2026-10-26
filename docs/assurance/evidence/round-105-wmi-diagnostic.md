# R105：WMI 有限诊断，导入仍被拒绝

2026-10-21。唯一 fresh run 已结束：Root 工具 `d8ad9c` 实际 exit 2、launcher shell 2、Python child 2，结果 `audit_denied`。checkpoint 仅 FastAPI TestClient 导入前后及 `before_tire_api_main`，三项导入未完成。

自然 OS 查询异常记为 `native_wrapper / stdlib_platform:327 / other_oserror`，精确内置 OSError；`errno=22`、`winerror=258` 均 present。它们只是受界错误字段，权限、WMI 服务、timeout 子类及系统根因均未证；不回填旧 C2/R104，旧 C2 实际触发链仍 unknown。

随后 `subprocess_popen` 请求仍被 Guard 拒绝，未证明子进程创建。首拒 24 帧仅保存 SQLAlchemy/platform/subprocess 片段，可能截断更远调用，不补 main。trace 有回调/时序开销，不称零干预或与原运行等价。

Launcher 报 exact_child_exited=true、forced_stop=false、流计数完整；stdout 0、stderr 276 仅为抑制字符数，原始流仅在内存分块读取/抑制，未向人或日志展开、未持久化。50196 是外层 shell PID，独立 Python PID 身份未观察；退出不证明全部后代/句柄关闭或 OS/native 隔离。

Root 对历史 manifest `26bc0af1d2e08891287a8e5f8337f0bffefd0b71eb26ba3c6816d3acbdb362c5` 前后完整读回 12,704 bindings / 12,495 路径，hash/keysets/shapes 保持；后置 session 66215 / final 0172c6 实际 exit 0。R38/S2 实件 hash 与旧 C2 关键 7 件保持，无新 freeze、capture 或旧 UUID 重跑。

终态独审核对安全字段、候选 7/7 pins、Root 8 件 evidence、R38/S2 纯字节 hash 及旧 C2 7 件一致。工具终态来自 Root 观察；独审仅读安全件，没有重跑 helper 或访问 raw tool 日志。本诊断未改产品/Guard/stdlib/.venv，未调用 API/正常 DB/Provider；provider/export=false，V1 active。诊断不是修复、材料/API/设备或 V1 验收；后续系统原因与恢复方案仍待另证。

证据：

- [安全结果](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-wmi-diagnostic-20261021/wmi-diagnostic-run-01/safe-result.json)
- [Root 终态独核](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-wmi-diagnostic-root-audit-20261021/terminal-readback.json)：8038B，SHA `9ee2844df48a5e1eb6762c6a921d307b7540de931f4e942b52edbe51befe32ce`。
- [终态独审](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-wmi-diagnostic-review-20261021/terminal-review.json)：8423B，SHA `be644e1099de62c54e44993a0fe7a0b3cbe38b95ae67d1682214efccfb406090`。
