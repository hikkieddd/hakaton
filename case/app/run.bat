@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
echo Запуск Бюджетного конструктора выборок на http://127.0.0.1:8765
python -m uvicorn main:app --host 127.0.0.1 --port 8765 --log-level info
pause
