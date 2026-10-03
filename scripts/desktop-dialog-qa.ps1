#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][int]$DesktopProcessId,
    [ValidateSet('inspect','cancel','save')][string]$Action = 'inspect',
    [string]$SavePath
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$expectedExecutable = [IO.Path]::GetFullPath((Join-Path $projectPath 'apps/desktop/src-tauri/target/debug/tire-desktop.exe'))
$targetProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$DesktopProcessId"
if (-not $targetProcess -or [IO.Path]::GetFullPath($targetProcess.ExecutablePath) -ne $expectedExecutable) { throw 'Refuse to automate a process outside this desktop debug build.' }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$processCondition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $DesktopProcessId)
$dialog = $null
for ($attempt = 0; $attempt -lt 25; $attempt++) {
    $windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $processCondition)
    $dialog = @($windows | Where-Object { $_.Current.Name -eq '保存胎迹导出文件' }) | Select-Object -First 1
    if ($dialog) { break }
    Start-Sleep -Milliseconds 200
}
if (-not $dialog) { throw 'Expected application save dialog is not present.' }
$controls = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
if ($Action -eq 'inspect') {
    @($controls | Where-Object { $_.Current.AutomationId -in @('1001','1','2') } | ForEach-Object {
        @{name=$_.Current.Name;automation_id=$_.Current.AutomationId;control=$_.Current.ControlType.ProgrammaticName}
    }) | ConvertTo-Json -Depth 4
    exit 0
}
if ($Action -eq 'save') {
    if (-not $SavePath) { throw 'SavePath is required.' }
    $resolvedSave = [IO.Path]::GetFullPath($SavePath, $projectPath)
    $artifactRoot = [IO.Path]::GetFullPath((Join-Path $projectPath '.artifacts/desktop')) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedSave.StartsWith($artifactRoot,[StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $resolvedSave)) { throw 'Save only a new file inside .artifacts/desktop.' }
    $filenameEdit = @($controls | Where-Object { $_.Current.AutomationId -eq '1001' -and $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit }) | Select-Object -First 1
    if (-not $filenameEdit) { throw 'Native filename edit not found.' }
    $value = $filenameEdit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $value.SetValue($resolvedSave)
}
$buttonId = if ($Action -eq 'save') { '1' } else { '2' }
$button = @($controls | Where-Object { $_.Current.AutomationId -eq $buttonId -and $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button }) | Select-Object -First 1
if (-not $button) { throw 'Expected native save/cancel button not found.' }
$pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
$pattern.Invoke()
@{action=$Action;invoked=$true;process_id=$DesktopProcessId} | ConvertTo-Json
