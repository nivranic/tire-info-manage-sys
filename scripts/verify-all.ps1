#requires -Version 7.0
# verify-all.ps1 — 无 CI 的聚合验证入口（一次性脚本，与"不做正式 CI"决策不冲突）。
# 串联全量验证：全工作区 typecheck → 五端单测（web/api-client/native-client/desktop/mobile）
#   → Web 生产构建（含 PWA 白名单构建期校验）→ API 全量 pytest → Worker 两套测试。
# 前置：根目录 npm install；apps/api 已执行 uv sync --project apps/api --extra dev（.venv 存在）。
# 运行前请停止 next dev，避免与生产构建共用 .next 写入。每步失败即停，结束打印各步骤汇总。
# Worker 测试口径：两个测试文件（test_monitor.py / test_telemetry_monitor.py）顶部均确认仅私有
# SQLite 与合成来源、从不真实外联；从 apps/api 目录用项目 .venv 的 python -m pytest 运行与
# README 根目录 uv run 口径等价（-m 将 cwd 置于 sys.path，tire_api 可导入），无需特殊准备。
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw '请用 PowerShell 7（pwsh）运行本脚本，不得使用 Windows PowerShell 5.1。'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'apps/api/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw '未找到 apps/api/.venv/Scripts/python.exe；请先运行 uv sync --project apps/api --extra dev 安装 API 依赖。'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'node_modules/next'))) {
    throw '未找到 node_modules/next；请先在项目根目录运行 npm install 安装依赖。'
}

$script:steps = [System.Collections.Generic.List[string]]::new()
$script:stepIndex = 0
$script:totalSteps = 9

function Invoke-Step {
    param([string]$Title, [scriptblock]$Body)
    $script:stepIndex++
    $started = Get-Date
    Write-Host ""
    Write-Host "===== 步骤 $($script:stepIndex)/$($script:totalSteps)：$Title =====" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        throw "步骤 $($script:stepIndex)（$Title）失败，exit=$LASTEXITCODE，已停止后续步骤。"
    }
    $script:steps.Add(("[OK]   步骤 {0}/{1}：{2}（{3:n1}s）" -f $script:stepIndex, $script:totalSteps, $Title, ((Get-Date) - $started).TotalSeconds))
}

try {
    Invoke-Step '全工作区 TypeScript 类型检查' {
        npm run typecheck --workspaces --if-present
    }
    Invoke-Step '单测 @tire/web（route-hash 纯函数）' {
        npm run test --workspace @tire/web
    }
    Invoke-Step '单测 @tire/api-client（含 decoder-fixtures 34 用例）' {
        npm run test --workspace @tire/api-client
    }
    Invoke-Step '单测 @tire/native-client（Node 传输）' {
        npm run test --workspace @tire/native-client
    }
    Invoke-Step '单测 @tire/desktop（Node 传输；非 Android 仪器或真实来源验收）' {
        npm run test --workspace @tire/desktop
    }
    Invoke-Step '单测 @tire/mobile（Node 传输；非 Android 仪器或真实来源验收）' {
        npm run test --workspace @tire/mobile
    }
    Invoke-Step 'Web 生产构建（build-pwa 白名单构建期校验 + next build）' {
        npm run build --workspace @tire/web
    }
    Invoke-Step 'API 全量 pytest（apps/api/tests/）' {
        Push-Location (Join-Path $projectRoot 'apps/api')
        try {
            & $pythonExe -m pytest tests/ -q
        } finally {
            Pop-Location
        }
    }
    Invoke-Step 'Worker pytest（test_monitor.py + test_telemetry_monitor.py）' {
        Push-Location (Join-Path $projectRoot 'apps/api')
        try {
            & $pythonExe -m pytest ..\worker\test_monitor.py ..\worker\test_telemetry_monitor.py -q
        } finally {
            Pop-Location
        }
    }
} catch {
    Write-Host ""
    Write-Host "===== 全量验证汇总（失败终止）=====" -ForegroundColor Red
    $script:steps | ForEach-Object { Write-Host $_ }
    Write-Host "[FAIL] 步骤 $($script:stepIndex)/$($script:totalSteps)：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "===== 全量验证汇总 =====" -ForegroundColor Green
$script:steps | ForEach-Object { Write-Host $_ }
Write-Host "全部 $($script:totalSteps) 步通过。" -ForegroundColor Green
exit 0
