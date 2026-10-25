param([switch]$Hardware)
$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH=Join-Path $project 'src'
if ($Hardware) {$env:AKKO_HARDWARE_TESTS='1'} else {Remove-Item Env:AKKO_HARDWARE_TESTS -ErrorAction SilentlyContinue}
$python=& (Join-Path $PSScriptRoot 'find-python.ps1')
& $python -m unittest discover -s (Join-Path $project 'tests') -v
if ($LASTEXITCODE -ne 0) {throw 'Tests failed'}
