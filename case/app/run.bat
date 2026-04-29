@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
echo Запуск Бюджетного конструктора выборок
echo Локально: http://127.0.0.1:8765
echo С другого ПК: http://IP_ЭТОГО_КОМПЬЮТЕРА:8765
echo Подсказка: IP можно посмотреть командой ipconfig, поле IPv4-адрес.
python -m uvicorn main:app --host 0.0.0.0 --port 8765 --log-level info
pause
