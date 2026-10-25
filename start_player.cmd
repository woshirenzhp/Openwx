@echo off
setlocal
set "PLAYER=%~dp0app.py"
set "BUNDLED=%~dp0runtime\python.exe"
if exist "%BUNDLED%" (
  "%BUNDLED%" "%PLAYER%" %*
) else (
  echo Portable runtime is missing. Please extract the complete portable ZIP first.
  echo For source development, use: python app.py
  pause
  exit /b 1
)
if errorlevel 1 pause
