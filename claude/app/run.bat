@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
echo Stopping old server on port 8765, if it exists...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul
echo.
echo Budget Constructor is starting
echo Local address: http://127.0.0.1:8765
echo Network addresses for another PC:
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*' } | ForEach-Object { '  http://' + $_.IPAddress + ':8765  (' + $_.InterfaceAlias + ')' }"
echo.
echo If another PC cannot open the address, run allow_port_8765_admin.bat as administrator.
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8765 --log-level info
pause
