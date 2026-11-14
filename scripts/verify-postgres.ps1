# Requires PowerShell 7 and an existing PostgreSQL binary distribution.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PostgresBin,
    [ValidateRange(1024, 65535)][int]$Port = 55432,
    [ValidateSet('core', 'runtime-role', 'external-reader', 'runtime-schema', 'runtime-process', 'vehicle-migration')][string]$Suite = 'core',
    [switch]$CliTls,
    [switch]$LiveSource,
    [switch]$NaturalLease
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Run this script with PowerShell 7.' }
if ($CliTls -and $Suite -in @('core', 'runtime-role')) { throw 'CliTls requires an external-reader, runtime-schema or vehicle-migration suite.' }
if ($Suite -eq 'runtime-process' -and -not $CliTls) { throw 'The runtime-process suite requires CliTls.' }
if (($LiveSource -or $NaturalLease) -and $Suite -ne 'runtime-process') { throw 'LiveSource and NaturalLease apply to the runtime-process suite.' }
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
$envNames = @('TIRE_PG_TEST_PASSWORD', 'TIRE_PG_TEST_PORT', 'TIRE_PG_TEST_DATA', 'TIRE_PG_BIN', 'TIRE_PG_TEST_REPORT', 'TIRE_PG_TEST_TLS_ROOT', 'TIRE_PG_TEST_TLS_WRONG_ROOT', 'TI_OBJECT_STORE_BACKEND', 'TI_OBJECT_STORE_ROOT', 'TEMP', 'TMP', 'TMPDIR')
$previousEnvironment = @{}
foreach ($name in $envNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    & (Join-Path $bin 'initdb.exe') -D $dataDir --username=tire_verify_admin --auth=scram-sha-256 --encoding=UTF8 --locale=C --pwfile=$passwordFile *> (Join-Path $runDir 'initdb.log')
    if ($LASTEXITCODE -ne 0) { throw 'Isolated initdb failed; see the artifact initdb.log.' }
    $env:TIRE_PG_TEST_TLS_ROOT = $null
    $env:TIRE_PG_TEST_TLS_WRONG_ROOT = $null
    if ($CliTls) {
        # Disposable certificate chain for this isolated loopback cluster only.
        # No OS trust-store modification and no external CA/key dependency.
        $caKey = [Security.Cryptography.RSA]::Create(2048)
        $leafKey = [Security.Cryptography.RSA]::Create(2048)
        $wrongKey = [Security.Cryptography.RSA]::Create(2048)
        $ca = $leaf = $wrong = $null
        try {
            $now = [DateTimeOffset]::UtcNow
            $caRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Synthetic PG CLI CA', $caKey,
                [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
            $caRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $false, 0, $true))
            $caRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
                [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign, $true))
            $ca = $caRequest.CreateSelfSigned($now.AddMinutes(-5), $now.AddDays(1))
            $leafRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Synthetic PG CLI Server', $leafKey,
                [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
            $san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
            $san.AddIpAddress([Net.IPAddress]::Loopback)
            $leafRequest.CertificateExtensions.Add($san.Build())
            $leaf = $leafRequest.Create($ca, $now.AddMinutes(-4), $now.AddHours(12), [Security.Cryptography.RandomNumberGenerator]::GetBytes(16))
            $wrongRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Synthetic Untrusted CA', $wrongKey,
                [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
            $wrong = $wrongRequest.CreateSelfSigned($now.AddMinutes(-5), $now.AddDays(1))
            [IO.File]::WriteAllText((Join-Path $dataDir 'server.crt'), $leaf.ExportCertificatePem(), [Text.UTF8Encoding]::new($false))
            [IO.File]::WriteAllText((Join-Path $dataDir 'server.key'), $leafKey.ExportPkcs8PrivateKeyPem(), [Text.UTF8Encoding]::new($false))
            $env:TIRE_PG_TEST_TLS_ROOT = Join-Path $runDir 'synthetic-ca.pem'
            $env:TIRE_PG_TEST_TLS_WRONG_ROOT = Join-Path $runDir 'synthetic-wrong-ca.pem'
            [IO.File]::WriteAllText($env:TIRE_PG_TEST_TLS_ROOT, $ca.ExportCertificatePem(), [Text.UTF8Encoding]::new($false))
            [IO.File]::WriteAllText($env:TIRE_PG_TEST_TLS_WRONG_ROOT, $wrong.ExportCertificatePem(), [Text.UTF8Encoding]::new($false))
            [IO.File]::AppendAllText((Join-Path $dataDir 'postgresql.conf'), "`nssl=on`n", [Text.UTF8Encoding]::new($false))
        } finally {
            foreach ($value in @($ca, $leaf, $wrong, $caKey, $leafKey, $wrongKey)) {
                if ($null -ne $value) { $value.Dispose() }
            }
        }
    }
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
    # Keep parser copies and all other temporary test files in this private run.
    $temporaryRoot = Join-Path $runDir 'tmp'
    $null = New-Item -ItemType Directory -Path $temporaryRoot
    $env:TEMP = $temporaryRoot
    $env:TMP = $temporaryRoot
    $env:TMPDIR = $temporaryRoot
    Push-Location $workspace
    try {
        $acceptanceScript = switch ($Suite) {
            'external-reader' { 'scripts/postgres_external_reader_acceptance.py' }
            'runtime-schema' { 'scripts/postgres_schema_acceptance.py' }
            'runtime-process' { 'scripts/postgres_process_acceptance.py' }
            'vehicle-migration' { 'scripts/postgres_vehicle_migration_acceptance.py' }
            default { 'scripts/postgres_acceptance.py' }
        }
        $acceptanceArguments = @($acceptanceScript)
        if ($Suite -eq 'runtime-role') { $acceptanceArguments += '--runtime-role' }
        if ($LiveSource) { $acceptanceArguments += '--live-source' }
        if ($NaturalLease) { $acceptanceArguments += '--natural-lease' }
        & uv run --project apps/api --extra dev python @acceptanceArguments
        if ($LASTEXITCODE -ne 0) { throw "PostgreSQL verification failed; sanitized report: $reportPath" }
    } finally { Pop-Location }
} finally {
    if ($startAttempted) {
        & (Join-Path $bin 'pg_ctl.exe') -D $dataDir -m fast -w -t 30 stop
        $stopped = $LASTEXITCODE -eq 0 -or -not (Test-Path -LiteralPath (Join-Path $dataDir 'postmaster.pid'))
    }
    if ($null -ne $pgStartProcess) { $pgStartProcess.Dispose() }
    foreach ($name in $envNames) {
        $restoredEnvironmentValue = $previousEnvironment[$name]
        if ($null -eq $restoredEnvironmentValue) { $restoredEnvironmentValue = [NullString]::Value }
        [Environment]::SetEnvironmentVariable($name, $restoredEnvironmentValue, 'Process')
    }
    Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
    if ($CliTls -and (-not $startAttempted -or $stopped)) {
        Remove-Item -LiteralPath (Join-Path $dataDir 'server.key') -Force -ErrorAction SilentlyContinue
    }
    $secret = $null
    @{ run_directory = $runDir; report = $reportPath; server_started = $started; server_stopped = $stopped; port = $Port } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $artifactRoot 'latest-run.json') -Encoding utf8
    Write-Output "PostgreSQL artifacts: $runDir"
    if ($startAttempted -and -not $stopped) { Write-Warning 'The isolated server still needs to be stopped using pg_ctl and this run data directory.' }
}
