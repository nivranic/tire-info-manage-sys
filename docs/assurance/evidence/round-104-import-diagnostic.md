# R104 独立导入诊断：平台回退请求仍被拒绝

2026-10-21。**本次实观 SQLAlchemy 平台回退链片段；未修复产品，旧 C2 实际根因仍 unknown，V1 active。** 这不是材料重跑或验收。

唯一新 run 为 `.artifacts/material-c2-import-diagnostic-20261021/import-diagnostic-run-01`。Root 工具 `6d05af`、launcher shell/Python child均exit2，状态 `audit_denied`。[安全结果](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-import-diagnostic-20261021/import-diagnostic-run-01/safe-result.json)记录 FastAPI TestClient 导入前后 checkpoint 完成，随后停在 `before_tire_api_main`；首次拒绝为 `child_process/subprocess_popen`。

实际24帧包含外到内片段：`sqlalchemy_compat:45 → platform:1024/922/450/414/283 → subprocess:466/548/1026/1534 → diagnostic:163`。帧数达到上限，没有 main 帧，不补截断调用者。只证明本次审计请求被拒绝，不证明该请求的子进程创建；exe/argv未采集。当前源码控制流与本次栈支持 WMI OS 查询的 OSError 回退路径，具体异常字段、错误码与底层原因仍未知，不回填旧 C2。

launcher记录exact owned child退出、forced=false、streams complete；stdout0/stderr276字符只计数，原始流仅在内存抑制，未展开或持久化。没有构造TestClient/调用API、重跑旧capture/UUID或新freeze；SQLite、显式网络和child审计继续拒绝，Guard未放宽。owned child退出不证明独立PID缺席、全部句柄关闭或OS/native完整隔离。

[Root终态](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-import-diagnostic-root-audit-20261021/terminal-readback.json)记录：前后各完整读回历史C2合同12,704 bindings/12,495路径及keysets/shapes均保持，非新freeze；R38/S2前后hash、旧C2关键七件保持。after工具终结 `b0b1e4` exit0。[终态独审](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-import-diagnostic-review-20261021/terminal-review.md)确认八件安全记录一致；未重复全量rehash、重开保护文件或做现场进程查询，未把Root摘要当raw工具日志。Provider/export=false，无材料、真实Provider、Native设备或V1验收。

原边界见[执行卡](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-import-diagnostic-20261021/EXECUTION-CARD.md)。[恢复可行性静核](E:/Mix/project/tire-info-manage-sys/.artifacts/material-c2-import-analysis-20261021/recovery-options.md)未找到当前安装源码的受支持公开配置可直接避开回退；已有AMD64字段晚于OS探测。下一步仅审不记录主机信息的本机WMI异常分类/有界错误码诊断，或另审受支持解释器；不改stdlib/.venv、不monkeypatch、不放行子进程，诊断和解释器方案均尚未执行或证明修复。
