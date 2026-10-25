@echo off
setlocal
set "SAMPLES=%~dp0"
if not exist "%SAMPLES%CE000001.MI3" set "SAMPLES=%~dp0..\"
if not exist "%SAMPLES%CE000001.MI3" (
  echo Put CE000001.MI3 and CE000001.SD3 next to this launcher, or open start_player.cmd.
  pause
  exit /b 1
)
call "%~dp0start_player.cmd" --mi3 "%SAMPLES%CE000001.MI3" --sd3 "%SAMPLES%CE000001.SD3"
