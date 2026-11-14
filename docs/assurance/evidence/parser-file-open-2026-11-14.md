# Parser 首次文件打开延迟取证

日期为 2026-11-14，基线为 `0b2ae2a`。本轮对原文件核验及正常进程入口开展分层测量，具体 OS 根因与间歇超时修复继续待验。[此前超时记录](postgres-vector-indexes-2026-11-14.md)

## 已取得的证据

54 组文件系统样本覆盖完整树剖析、缓冲方式、路径表示、文件后缀、目录位置及直接 Win32 打开。比较按不同顺序执行，冷读使用独立新建样本，同树后续读取单独记录。核对文件字节与相应的句柄身份，并清理自建目录。

| 范围 | 观测 |
| --- | --- |
| 完整 196 文件、约 2.9 MB 源码树首次读取 | 系统临时目录 3.247 秒，其中 `_io.open` 3.034 秒，2018 次 `nt.stat` 约 0.023 秒 |
| 同一已读取树的后续读取 | 系统目录约 0.227 秒，项目目录约 0.238–0.251 秒 |
| 12 组独立新建完整树，缓冲／无缓冲交替 | 系统目录约 2.317–2.803 秒，项目目录约 0.141–0.175 秒，两种缓冲方式均出现位置差异 |
| 16 组路径与后缀比较，每组 24 文件 | 普通／扩展 Windows 路径及 py／txt 后缀均在系统目录出现慢打开，项目目录均无超过 10 ms 的样本 |
| 6 组同卷位置比较，每组 32 文件 | 系统临时目录及其同卷父目录约 0.279–0.434 秒，项目私槽约 0.023–0.024 秒 |
| 16 组 Python／CRT／Win32 比较，每组 24 文件 | 直接 CreateFileW 及 OPEN_REPARSE_POINT 方式也出现慢打开，系统目录每组约 0.209–0.352 秒，项目目录约 0.002–0.003 秒 |

这些观测将主要耗时收敛到新文件的 Windows 打开链路。具体文件系统、过滤驱动及存储层的贡献继续待带堆栈的 I/O 跟踪确认。过滤器枚举命令返回 `0x80070005`，当前会话的 OS 权限限制已记录。原始三份超时回执继续保留。

## 原正常入口复验

通过原 `parse_isolated()` 执行 16 次，包含合成 PDF 与 Hankook、当前安装与已封存 bundle、系统与项目私有临时目录，各组合按正反顺序执行。8 秒监督器期限、文件前后核验、Windows Job Object 和输出限制均参与执行。16 次结果逐项匹配原纯 Parser，子进程退出 0 并回收，临时执行目录均已删除。

| 临时目录配置 | 次数 | 监督器回执 elapsed_ms | 整个 parse_isolated 调用 |
| --- | --- | --- | --- |
| 系统默认 | 8 | 3937–4781 ms | 4339–5238 ms |
| 进程级项目私槽 | 8 | 2016–2547 ms | 2420–2912 ms |

计时观察器包装原函数并返回原值，记录父进程文件树阶段。工具宿主缺少 Windows 架构环境变量，诊断进程依据所用 Python 的 `sysconfig.get_platform()` 显式设置架构，沿用原子进程环境白名单。真实服务启动器的环境传播继续验收。

本批全部通过对应上述输入、机器和执行环境，生产尾延迟与原间歇超时继续独立跟踪。

## 复现及可用部署配置

原始剖析脚本、分组数据和汇总位于 Git 忽略的 `.artifacts/parser-performance-20261114/`。汇总文件为 `summary.json`，SHA-256 为 `46057517c83b84958820f6030893a819bf15f22f21d823e987b8fa9e2bd9a9cd`，包含六组原始回执的摘要。全部 842 个受管源码输入与基线一致。

原 Parser 使用标准 TEMP／TMP／TMPDIR 临时目录选择。服务启动进程可以通过现有环境配置选择已准备的自有工作目录，API 与 Worker 按各自启动进程配置，并使用现有临时目录清理流程。

```powershell
$parserTemp = '<existing-private-work-directory>'
if (-not (Test-Path -LiteralPath $parserTemp -PathType Container)) {
    throw 'Prepare the private service work directory before launch.'
}
$env:TEMP = $parserTemp
$env:TMP = $parserTemp
$env:TMPDIR = $parserTemp
# Run the existing API or Worker startup command in this process.
```

下一步取得 OS 打开链路堆栈，验证真实部署进程的工作目录、架构环境、取消与恢复，并继续正常 HTTP／Worker 启动、权限及全资产恢复验收。真实材料、模型、生产容量和完整 V1 继续按对应 Gate 验收。
