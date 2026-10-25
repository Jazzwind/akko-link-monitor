param([string]$Address, [switch]$Once, [int]$ParentPid=0)
# Read ConnectionStatus only. No discovery, GATT read/write, or MaintainConnection.
$parentProcess=if ($ParentPid) {[Diagnostics.Process]::GetProcessById($ParentPid)} else {$null}
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Devices.Bluetooth.BluetoothLEDevice,Windows.Devices.Bluetooth,ContentType=WindowsRuntime]
$awaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
try {
    $operation = [Windows.Devices.Bluetooth.BluetoothLEDevice]::FromBluetoothAddressAsync([Convert]::ToUInt64($Address,16))
    $task = $awaitMethod.MakeGenericMethod([Windows.Devices.Bluetooth.BluetoothLEDevice]).Invoke($null,@($operation))
    if (-not $task.Wait(10000)) { throw 'Bluetooth identity lookup timed out' }
    $device = $task.Result
    if ($null -eq $device) { throw 'Bluetooth device unavailable' }
    do {
        @{connected=($device.ConnectionStatus.ToString() -eq 'Connected');name=$device.Name;address=$Address} | ConvertTo-Json -Compress
        if (-not $Once) { Start-Sleep -Milliseconds 1000 }
    } while (-not $Once -and ($null -eq $parentProcess -or -not $parentProcess.HasExited))
} catch {
    @{connected=$null;error=$_.Exception.Message;address=$Address} | ConvertTo-Json -Compress
} finally {
    if ($null -ne $device) { try {$device.Dispose()} catch {} }
}
