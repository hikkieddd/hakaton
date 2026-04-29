@echo off
chcp 65001 >nul
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Run this file as administrator.
  echo Right click: Run as administrator.
  pause
  exit /b 1
)

echo Opening TCP port 8765 for the Budget Constructor...
netsh advfirewall firewall add rule name="Budget Constructor 8765" dir=in action=allow protocol=TCP localport=8765 profile=any

echo.
echo Done. If the network is marked Public, switch it to Private in Windows network settings.
echo Current network profiles:
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory,IPv4Connectivity | Format-Table -AutoSize"
pause
