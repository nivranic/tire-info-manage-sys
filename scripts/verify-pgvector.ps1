# Build a pinned official pgvector release against a private copy of PostgreSQL.
# No existing cluster, installation, Docker daemon, or global environment is changed.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PostgresRoot,
    [string]$VisualStudioRoot,
    [ValidateRange(1024, 65535)][int]$Port = 55433,
    [switch]$BusinessChecks
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Run this script with PowerShell 7.' }
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$artifactRoot = [IO.Path]::GetFullPath((Join-Path $workspace '.artifacts/pgvector'))
$runDir = Join-Path $artifactRoot ('vectorverify-' + [guid]::NewGuid().ToString('N'))
$runtime = Join-Path $runDir 'postgres'
$dataDir = Join-Path $runDir 'data'
$sourceRoot = (Resolve-Path -LiteralPath $PostgresRoot).Path
foreach ($path in @($runDir, $runtime, $dataDir)) {
    if (-not ([IO.Path]::GetFullPath($path).StartsWith($artifactRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) {
        throw 'Every output must remain in the workspace pgvector artifact directory.'
    }
}
foreach ($item in @('bin/initdb.exe', 'bin/pg_ctl.exe', 'bin/pg_dump.exe', 'bin/pg_restore.exe', 'include/server/postgres.h', 'lib/postgres.lib')) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $item))) { throw "Missing PostgreSQL build/runtime input: $item" }
}
if (-not $VisualStudioRoot) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Supply an existing Visual Studio C++ toolchain with -VisualStudioRoot.' }
    $VisualStudioRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}
$devcmd = Join-Path $VisualStudioRoot 'Common7/Tools/VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $devcmd)) { throw 'The existing Visual Studio developer command script is unavailable.' }
# Only this trusted path is included in cmd.exe command text. File operations stay in PowerShell.
if ($devcmd -match '[%"\r\n]') { throw 'Unsupported characters in Visual Studio path.' }
$probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } finally { $probe.Stop() }
$null = New-Item -ItemType Directory -Path $runtime
$pin = '778dacf20c07caf904557a88705142631818d8cb'
$version = '0.8.1'
$archiveSha256 = '5badef2cdfed828d93b7f70ae6ad38236e36954420bb24001aa5508e61bf2d7c'
$sourceUrl = "https://github.com/pgvector/pgvector/archive/$pin.zip"
$archive = Join-Path $runDir 'pgvector-source.zip'
$bin = Join-Path $runtime 'bin'
$passwordFile = Join-Path $runDir 'init-password.txt'
$reportPath = Join-Path $runDir 'report.json'
$secret = $null
$started = $false
$stopped = $false
$envNames = @('PGROOT', 'TIRE_VECTOR_TEST_PASSWORD', 'TIRE_VECTOR_TEST_PORT', 'TIRE_VECTOR_TEST_DATA', 'TIRE_VECTOR_TEST_BIN', 'TIRE_VECTOR_TEST_REPORT', 'TIRE_VECTOR_BUSINESS_CHECKS')
$previousEnvironment = @{}
foreach ($name in $envNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    foreach ($part in @('bin', 'lib', 'share', 'include')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $part) -Destination (Join-Path $runtime $part) -Recurse
    }
    Invoke-WebRequest -Uri $sourceUrl -OutFile $archive -TimeoutSec 90
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $archiveSha256) {
        throw 'Official pinned source archive checksum mismatch; do not build unverified input.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $runDir 'source')
    $source = Join-Path $runDir "source/pgvector-$pin"
    $control = Get-Content -LiteralPath (Join-Path $source 'vector.control') -Raw
    if ($control -notmatch "default_version = '$([regex]::Escape($version))'") { throw 'Pinned source version does not match expected pgvector release.' }
    $env:PGROOT = $runtime
    Push-Location $source
    try {
        & $env:ComSpec /d /s /c "call `"$devcmd`" -arch=x64 -host_arch=x64 >nul && nmake /F Makefile.win && nmake /F Makefile.win install" *> (Join-Path $runDir 'build.log')
        if ($LASTEXITCODE -ne 0) { throw 'Isolated pgvector build failed; see build.log.' }
    } finally { Pop-Location }
    @{
        source_url = $sourceUrl; source_commit = $pin; pgvector_version = $version
        source_archive_sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        built_dll_sha256 = (Get-FileHash -LiteralPath (Join-Path $runtime 'lib/vector.dll') -Algorithm SHA256).Hash.ToLowerInvariant()
        postgres_source = $sourceRoot; postgres_runtime = $runtime; visual_studio_root = $VisualStudioRoot
        source_installation_modified = $false
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'provenance.json') -Encoding utf8
    $secret = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    [IO.File]::WriteAllText($passwordFile, $secret, [Text.UTF8Encoding]::new($false))
    & (Join-Path $bin 'initdb.exe') -D $dataDir --username=tire_vector_admin --auth=scram-sha-256 --encoding=UTF8 --locale=C --pwfile=$passwordFile *> (Join-Path $runDir 'initdb.log')
    if ($LASTEXITCODE -ne 0) { throw 'Isolated initdb failed; see initdb.log.' }
    & (Join-Path $bin 'pg_ctl.exe') -D $dataDir -l (Join-Path $runDir 'postgres.log') -o "-h 127.0.0.1 -p $Port" -w -t 30 start
    if ($LASTEXITCODE -ne 0) { throw 'The isolated PostgreSQL instance did not start.' }
    $started = $true
    $env:TIRE_VECTOR_TEST_PASSWORD = $secret
    $env:TIRE_VECTOR_TEST_PORT = [string]$Port
    $env:TIRE_VECTOR_TEST_DATA = $dataDir
    $env:TIRE_VECTOR_TEST_BIN = $bin
    $env:TIRE_VECTOR_TEST_REPORT = $reportPath
    $env:TIRE_VECTOR_BUSINESS_CHECKS = if ($BusinessChecks) { '1' } else { '0' }
    Push-Location $workspace
    try {
        & uv run --project apps/api --extra dev python scripts/pgvector_acceptance.py
        if ($LASTEXITCODE -ne 0) { throw "pgvector verification failed; sanitized report: $reportPath" }
    } finally { Pop-Location }
} finally {
    if ($started) {
        & (Join-Path $bin 'pg_ctl.exe') -D $dataDir status *> $null
        if ($LASTEXITCODE -eq 3) {
            $stopped = $true
        } else {
            & (Join-Path $bin 'pg_ctl.exe') -D $dataDir -m fast -w -t 30 stop
            $stopped = $LASTEXITCODE -eq 0
        }
    }
    foreach ($name in $envNames) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
    if (Test-Path -LiteralPath $passwordFile) { Remove-Item -LiteralPath $passwordFile -Force }
    $secret = $null
    @{ run_directory = $runDir; report = $reportPath; server_started = $started; server_stopped = $stopped; port = $Port } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $artifactRoot 'latest-run.json') -Encoding utf8
    Write-Output "pgvector artifacts: $runDir"
    if ($started -and -not $stopped) { Write-Warning 'Inspect the isolated cluster using its pg_ctl and data directory; do not start a second instance.' }
}
