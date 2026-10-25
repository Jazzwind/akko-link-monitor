param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
if (-not $OutputDirectory) {$OutputDirectory=Join-Path (Split-Path -Parent $PSScriptRoot) 'bin'}
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) {throw '.NET Framework C# compiler is required for the named launcher.'}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$output=Join-Path $OutputDirectory 'AkkoLinkMonitor.exe'
& $compiler /nologo /warn:4 /warnaserror+ /target:winexe /r:System.Windows.Forms.dll "/out:$output" (Join-Path $PSScriptRoot 'AkkoLinkMonitor.cs')
if ($LASTEXITCODE -ne 0) {throw 'Named launcher compilation failed.'}
Write-Output $output
