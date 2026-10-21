# Admin: clear leftover ETW sessions + old processes, then start Orbit fresh.
foreach ($s in 'CMFDialHold','OrbitDialBT','OrbitDiag','OrbitDiagA','OrbitDiagB','OrbitDiagC') { logman stop $s -ets 2>$null | Out-Null }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'hold_detector|-m orbit|bt_diag|dial_logger' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 1
logman query -ets | Select-String 'Orbit|CMF' | Out-File "$PSScriptRoot\reset_bt.txt"
"cleared at $(Get-Date -Format HH:mm:ss)" | Out-File "$PSScriptRoot\reset_bt.txt" -Append
Start-Process python -ArgumentList '-m','orbit','--debug' -WorkingDirectory (Split-Path $PSScriptRoot) -WindowStyle Hidden
