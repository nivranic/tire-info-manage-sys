#requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'apps/api/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw '先运行 uv sync --project apps/api --extra dev 安装 API 依赖。'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'node_modules/next'))) {
    throw '先在项目根目录运行 npm install 安装 Web 依赖。'
}
foreach ($port in @(8000, 3000)) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($listener) { throw "端口 $port 已占用。请先处理已有服务，再启动本项目。" }
}
$logDirectory = Join-Path $projectRoot '.artifacts/runtime'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$previousLocation = Get-Location
$apiProcess = $null
try {
    Set-Location -LiteralPath $projectRoot
    $apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @(
        '-m', 'uvicorn', 'tire_api.main:app', '--host', '127.0.0.1', '--port', '8000'
    ) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $logDirectory 'api.stdout.log') `
      -RedirectStandardError (Join-Path $logDirectory 'api.stderr.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($apiProcess.HasExited) { throw 'API 启动失败，请检查 .artifacts/runtime/api.stderr.log。' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 1
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $ready) { throw 'API 健康检查超时。' }
    Write-Host '本地工作台：http://127.0.0.1:3000；Ctrl+C 停止。'
    & npm.cmd run dev
} finally {
    if ($apiProcess -and -not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id }
    Set-Location -LiteralPath $previousLocation.Path
}

