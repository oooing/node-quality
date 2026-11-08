param([switch]$Lab, [string]$Output)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $Output) { $Output = Join-Path $root 'resources/backend/clash-select.exe' }
New-Item -ItemType Directory -Force -Path (Split-Path $Output -Parent) | Out-Null
$assemblyRoot = Join-Path $env:WINDIR 'Microsoft.NET/assembly/GAC_MSIL'
$arguments = @('/nologo', '/target:exe', ('/out:' + $Output), '/reference:System.Web.Extensions.dll')
foreach ($name in @('UIAutomationClient', 'UIAutomationTypes', 'WindowsBase')) {
    $arguments += '/reference:' + (Join-Path $assemblyRoot "$name/v4.0_4.0.0.0__31bf3856ad364e35/$name.dll")
}
if ($Lab) { $arguments += '/define:LAB' }
$arguments += Join-Path $root 'windows-helper/ClashSelect.cs'
& (Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe') @arguments
if ($LASTEXITCODE -ne 0) { throw 'Clash selection helper compilation failed' }
