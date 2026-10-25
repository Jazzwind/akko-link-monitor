$ErrorActionPreference='Stop'
$candidates=New-Object System.Collections.Generic.List[string]
$launcher=Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) {
    $resolved=& $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -eq 0 -and $resolved) {$candidates.Add([string]$resolved)}
}
foreach ($name in @('python.exe','python3.exe')) {
    $command=Get-Command $name -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps') {$candidates.Add($command.Source)}
}
foreach ($base in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore')) {
    if (Test-Path $base -ErrorAction SilentlyContinue) {
        foreach ($version in Get-ChildItem $base -ErrorAction SilentlyContinue) {
            $install=Join-Path $version.PSPath 'InstallPath'
            if (Test-Path $install) {
                $values=Get-ItemProperty $install
                if ($values.ExecutablePath) {$candidates.Add($values.ExecutablePath)}
                elseif ($values.'(default)') {$candidates.Add((Join-Path $values.'(default)' 'python.exe'))}
            }
        }
    }
}
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate)) {continue}
    & $candidate -c "import sys,struct,tkinter; sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize('P')==8 else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {Write-Output $candidate;return}
}
throw '需要安装带 tkinter 的 64 位 Python 3.10 或更高版本（已验证 Python 3.13）。'
