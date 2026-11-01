@echo off
setlocal
chcp 65001 >nul
title Liquidation Lab 0.5
cd /d "%~dp0"
if not exist "qa-output" mkdir "qa-output"
echo Liquidation Lab 0.5
echo.
echo Подготовка запуска. При первом запуске нужен интернет.
echo Окно приложения откроется автоматически. Подождите.
echo.
if exist ".venv\Scripts\python.exe" goto check_venv
py -3.11 -c "import sys,struct; assert sys.version_info[:2] == (3,11) and struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 goto use_py311
py -3.12 -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 goto use_py312
python -c "import sys,struct; assert sys.version_info[:2] in ((3,11),(3,12)) and struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 goto use_python
echo Не найден Python 3.11 или 3.12 для Windows 64-bit.
echo Пришлите снимок этого окна в наш чат — помогу установить.
goto failed

:use_py311
py -3.11 -m venv ".venv" >"qa-output\setup.log" 2>&1
if errorlevel 1 goto setup_failed
goto check_venv

:use_py312
py -3.12 -m venv ".venv" >"qa-output\setup.log" 2>&1
if errorlevel 1 goto setup_failed
goto check_venv

:use_python
python -m venv ".venv" >"qa-output\setup.log" 2>&1
if errorlevel 1 goto setup_failed

:check_venv
".venv\Scripts\python.exe" -c "import sys,struct; assert sys.version_info[:2] in ((3,11),(3,12)) and struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 goto setup_failed
".venv\Scripts\python.exe" -c "import importlib.metadata as m; assert m.version('Kivy') == '2.3.1'" >nul 2>&1
if not errorlevel 1 goto launch
echo Устанавливаю компоненты. Это может занять несколько минут...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.txt "kivy==2.3.1" >>"qa-output\setup.log" 2>&1
if errorlevel 1 goto setup_failed

:launch
set "PYTHONIOENCODING=utf-8"
".venv\Scripts\python.exe" -u -m qa.manual_windows_launch %1
if errorlevel 1 goto failed
if /I "%~1"=="--check" exit /b 0
echo.
echo Приложение закрыто. Для продолжения проверки вернитесь в чат.
pause
exit /b 0

:setup_failed
echo Не удалось подготовить запуск. Подробности:
if exist "qa-output\setup.log" type "qa-output\setup.log"
echo.
echo Пришлите снимок этого окна. Лог: qa-output\setup.log

:failed
if /I "%~1"=="--check" exit /b 1
echo.
pause
exit /b 1
