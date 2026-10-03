# Requires PowerShell 7 and an existing PostgreSQL binary distribution.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PostgresBin,
    [ValidateRange(1024, 65535)][int]$Port = 55432
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Run this script with PowerShell 7.' }
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bin = (Resolve-Path -LiteralPath $PostgresBin).Path
foreach ($program in @('initdb.exe', 'pg_ctl.exe', 'pg_dump.exe', 'pg_restore.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $bin $program))) { throw "Missing PostgreSQL program: $program" }
}
# Refuse an occupied port; no existing service is stopped or reconfigured.
$probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } finally { $probe.Stop() }
$artifactRoot = [IO.Path]::GetFullPath((Join-Path $workspace '.artifacts/postgres'))
$runDir = Join-Path $artifactRoot ('pgverify-' + [guid]::NewGuid().ToString('N'))
$dataDir = Join-Path $runDir 'data'
if (-not ([IO.Path]::GetFullPath($dataDir).StartsWith($artifactRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) {
    throw 'The verification cluster must stay in the project artifact directory.'
}
$null = New-Item -ItemType Directory -Path $runDir
$passwordFile = Join-Path $runDir 'init-password.txt'
$secret = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
[IO.File]::WriteAllText($passwordFile, $secret, [Text.UTF8Encoding]::new($false))
$started = $false
$startAttempted = $false
$stopped = $false
$pgStartProcess = $null
$reportPath = Join-Path $runDir 'report.json'
$envNames = @('TIRE_PG_TEST_PASSWORD', 'TIRE_PG_TEST_PORT', 'TIRE_PG_TEST_DATA', 'TIRE_PG_BIN', 'TIRE_PG_TEST_REPORT', 'TI_OBJECT_STORE_BACKEND', 'TI_OBJECT_STORE_ROOT')
$previousEnvironment = @{}
foreach ($name in $envNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    & (Join-Path $bin 'initdb.exe') -D $dataDir --username=tire_verify_admin --auth=scram-sha-256 --encoding=UTF8 --locale=C --pwfile=$passwordFile *> (Join-Path $runDir 'initdb.log')
    if ($LASTEXITCODE -ne 0) { throw 'Isolated initdb failed; see the artifact initdb.log.' }
    # A daemon may inherit a PowerShell pipeline handle and keep its native
    # output reader open after pg_ctl exits. Wait for pg_ctl itself, not its
    # descendants, and keep startup streams outside the caller's pipeline.
    $startAttempted = $true
    $pgStartProcess = Start-Process -FilePath (Join-Path $bin 'pg_ctl.exe') -ArgumentList @(
        '-D', ('"{0}"' -f $dataDir), '-l', ('"{0}"' -f (Join-Path $runDir 'postgres.log')),
        '-o', ('"-h 127.0.0.1 -p {0}"' -f $Port), '-w', '-t', '30', 'start'
    ) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir 'pg-start.stdout.log') `
      -RedirectStandardError (Join-Path $runDir 'pg-start.stderr.log')
    # Cache the native handle before exit; otherwise PowerShell's returned
    # Process can finish successfully yet expose a null ExitCode on Windows.
    $null = $pgStartProcess.Handle
    if (-not $pgStartProcess.WaitForExit(35000)) {
        $pgStartProcess.Kill()
        $null = $pgStartProcess.WaitForExit(5000)
        throw 'Isolated pg_ctl startup did not finish within 35 seconds.'
    }
    if ($pgStartProcess.ExitCode -ne 0) { throw 'The isolated PostgreSQL instance did not start; see pg-start logs.' }
    $started = $true
    Write-Output "Isolated PostgreSQL ready on 127.0.0.1:$Port"
    $env:TIRE_PG_TEST_PASSWORD = $secret
    $env:TIRE_PG_TEST_PORT = [string]$Port
    $env:TIRE_PG_TEST_DATA = $dataDir
    $env:TIRE_PG_BIN = $bin
    $env:TIRE_PG_TEST_REPORT = $reportPath
    $env:TI_OBJECT_STORE_BACKEND = 'filesystem'
    $env:TI_OBJECT_STORE_ROOT = Join-Path $runDir 'objects'
    Push-Location $workspace
    try {
        & uv run --project apps/api --extra dev python scripts/postgres_acceptance.py
        if ($LASTEXITCODE -ne 0) { throw "PostgreSQL verification failed; sanitized report: $reportPath" }
    } finally { Pop-Location }
} finally {
    if ($startAttempted) {
        & (Join-Path $bin 'pg_ctl.exe') -D $dataDir -m fast -w -t 30 stop
        $stopped = $LASTEXITCODE -eq 0 -or -not (Test-Path -LiteralPath (Join-Path $dataDir 'postmaster.pid'))
    }
    if ($null -ne $pgStartProcess) { $pgStartProcess.Dispose() }
    foreach ($name in $envNames) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
    Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
    $secret = $null
    @{ run_directory = $runDir; report = $reportPath; server_started = $started; server_stopped = $stopped; port = $Port } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $artifactRoot 'latest-run.json') -Encoding utf8
    Write-Output "PostgreSQL artifacts: $runDir"
    if ($startAttempted -and -not $stopped) { Write-Warning 'The isolated server still needs to be stopped using pg_ctl and this run data directory.' }
}
