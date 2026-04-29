@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "tools\cloudflared.exe" (
  mkdir tools 2>nul
  echo Скачиваю cloudflared...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'tools\cloudflared.exe'"
)

echo.
echo 1. Убедитесь, что приложение запущено на http://127.0.0.1:8765
echo 2. Ниже появится публичная ссылка https://...trycloudflare.com
echo 3. Пока это окно открыто, ссылка работает.
echo.

tools\cloudflared.exe tunnel --url http://127.0.0.1:8765
pause
