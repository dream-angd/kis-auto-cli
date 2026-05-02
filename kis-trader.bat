@echo off
setlocal

cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    set "PY=python"
)

if not "%~1"=="" (
    "%PY%" main.py %*
    exit /b %ERRORLEVEL%
)

:menu
cls
echo ==============================
echo        KIS Trader CLI
echo ==============================
echo.
echo  1. Start auto trading
echo  2. Show account status
echo  3. Analyze stock
echo  4. Show today's history
echo  5. Exit
echo.
choice /c 12345 /n /m "Select [1-5]: "

if errorlevel 5 goto end
if errorlevel 4 goto history
if errorlevel 3 goto analyze
if errorlevel 2 goto status
if errorlevel 1 goto run

:run
echo.
set "INTERVAL=300"
set /p "INTERVAL=Interval seconds [300]: "
if "%INTERVAL%"=="" set "INTERVAL=300"
"%PY%" main.py run --interval %INTERVAL%
echo.
pause
goto menu

:status
echo.
"%PY%" main.py status
echo.
pause
goto menu

:analyze
echo.
set "CODE=005930"
set /p "CODE=Stock code [005930]: "
if "%CODE%"=="" set "CODE=005930"
"%PY%" main.py analyze %CODE%
echo.
pause
goto menu

:history
echo.
"%PY%" main.py history
echo.
pause
goto menu

:end
endlocal
exit /b 0
