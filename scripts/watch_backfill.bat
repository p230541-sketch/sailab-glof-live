@echo off
rem Shows the newest SailAb run log live: one line per scene as it is downloaded or skipped.
rem Double-click this file, or run it from cmd. Close the window or press Ctrl+C to stop WATCHING;
rem the download itself keeps running.
title SailAb download progress
cd /d "%~dp0.."
powershell -NoProfile -Command ^
  "$log = Get-ChildItem logs\runs\*.log | Sort-Object LastWriteTime | Select-Object -Last 1;" ^
  "Write-Host ('Watching ' + $log.Name + '  (Ctrl+C to stop watching)') -ForegroundColor Cyan;" ^
  "Get-Content $log.FullName -Wait -Tail 15 | ForEach-Object {" ^
  "  if ($_ -match 'rasterio') { return }" ^
  "  if ($_ -cmatch ' ERROR | run [0-9]+ failed|run FAILED') { Write-Host $_ -ForegroundColor Red }" ^
  "  elseif ($_ -match 'scenes listed') { Write-Host $_ -ForegroundColor Yellow }" ^
  "  elseif ($_ -match ': downloaded') { Write-Host $_ -ForegroundColor Green }" ^
  "  elseif ($_ -match ' ok [0-9]') { Write-Host $_ -ForegroundColor White }" ^
  "  else { Write-Host $_ -ForegroundColor DarkGray } }"
