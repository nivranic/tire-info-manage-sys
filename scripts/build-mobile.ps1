#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [ValidateSet('Debug','Release')][string]$Configuration = 'Debug',
    [ValidateRange(1024,65535)][int]$ApiPort = 8000,
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$')][string]$SessionNamespace = 'default',
    [switch]$RunUnitTests
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin/java.exe'))) { throw '请通过 -JavaHome 或 JAVA_HOME 指定 JDK 21。' }
if (-not $AndroidSdk -or -not (Test-Path -LiteralPath (Join-Path $AndroidSdk 'platforms/android-36/android.jar'))) { throw '请通过 -AndroidSdk 或 ANDROID_HOME 指定已安装 API 36 的 Android SDK。' }
$version = (& (Join-Path $JavaHome 'bin/java.exe') -version 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0 -or $version -notmatch 'version "21[.]') { throw '当前构建已验证 JDK 21，请显式指定 JDK 21 路径。' }
$previous = @{ Java = $env:JAVA_HOME; Sdk = $env:ANDROID_HOME; Gradle = $env:GRADLE_USER_HOME; Path = $env:Path; Location = (Get-Location).Path }
try {
    $env:JAVA_HOME = [IO.Path]::GetFullPath($JavaHome)
    $env:ANDROID_HOME = [IO.Path]::GetFullPath($AndroidSdk)
    $env:GRADLE_USER_HOME = Join-Path $projectPath '.artifacts/mobile/gradle'
    $env:Path = (Join-Path $env:JAVA_HOME 'bin') + [IO.Path]::PathSeparator + $env:Path
    Set-Location -LiteralPath $projectPath
    & npm.cmd run mobile:frontend
    if ($LASTEXITCODE -ne 0) { throw '移动前端构建失败。' }
    & npm.cmd run mobile:sync
    if ($LASTEXITCODE -ne 0) { throw 'Capacitor 同步失败。' }
    Set-Location -LiteralPath (Join-Path $projectPath 'apps/mobile/android')
    $tasks = @("assemble$Configuration")
    if ($RunUnitTests) { $tasks += "test${Configuration}UnitTest" }
    & './gradlew.bat' @tasks "-PtireApiPort=$ApiPort" "-PtireSessionNamespace=$SessionNamespace" --no-daemon --max-workers=2 --console=plain
    if ($LASTEXITCODE -ne 0) { throw 'Android 构建或单元测试失败。' }
    Write-Host "Android $Configuration 构建完成；产物位于 apps/mobile/android/app/build/outputs/apk/。"
} finally {
    $env:JAVA_HOME = $previous.Java; $env:ANDROID_HOME = $previous.Sdk
    $env:GRADLE_USER_HOME = $previous.Gradle; $env:Path = $previous.Path
    Set-Location -LiteralPath $previous.Location
}
