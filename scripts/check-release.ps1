$ErrorActionPreference='Stop'
$python=& (Join-Path $PSScriptRoot 'find-python.ps1')
& $python (Join-Path $PSScriptRoot 'check-release.py')
exit $LASTEXITCODE
