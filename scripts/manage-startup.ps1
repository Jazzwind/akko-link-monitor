param([Parameter(Mandatory=$true)][string]$Destination,
      [Parameter(Mandatory=$true)][string]$Launcher)
$ErrorActionPreference='Stop'
$parent=Split-Path -Parent $Destination
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$shell=New-Object -ComObject WScript.Shell
$link=$null
try {
    $link=$shell.CreateShortcut($Destination)
    $link.TargetPath=$Launcher
    $link.Arguments='--startup'
    $link.WorkingDirectory=Split-Path -Parent (Split-Path -Parent $Launcher)
    $link.IconLocation=$Launcher+',0'
    $link.Description='AKKO Link Monitor'
    $link.Save()
} finally {
    if ($null -ne $link) {[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($link)}
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
}
