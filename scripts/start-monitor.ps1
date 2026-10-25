param([switch]$Startup,[switch]$Desktop)
$ErrorActionPreference='Stop'
try {
    if (-not $Desktop) {
        # Delegate to the existing desktop Shell to avoid inherited MSIX AppData redirection.
        $shell=New-Object -ComObject Shell.Application
        $desktopWindow=$null
        for ($attempt=0;$attempt -lt 10 -and $null -eq $desktopWindow;$attempt++) {
            $desktopHandle=0
            $desktopWindow=$shell.Windows().FindWindowSW(0,0,8,[ref]$desktopHandle,1)
            if ($null -eq $desktopWindow) {Start-Sleep -Milliseconds 200}
        }
        if ($null -eq $desktopWindow) {throw 'Windows desktop Shell is not ready; start again after signing in.'}
        $arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$PSCommandPath+'" -Desktop'
        if ($Startup) {$arguments+=' -Startup'}
        $desktopWindow.Document.Application.ShellExecute('powershell.exe',$arguments,(Split-Path -Parent $PSScriptRoot),'open',0)
        return
    }
    $python=& (Join-Path $PSScriptRoot 'find-python.ps1')
    $pythonw=Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) {throw '找不到 pythonw.exe，请修复 Python 安装。'}
    $project=Split-Path -Parent $PSScriptRoot
    $arguments='"'+(Join-Path $project 'app.py')+'" --record'
    if ($Startup) {$arguments+=' --startup'}
    Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $project -WindowStyle Hidden
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message,'AKKO Link Monitor') | Out-Null
    exit 1
}
