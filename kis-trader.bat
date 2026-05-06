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
echo  1. Start swing + scalp
echo  2. Start swing only
echo  3. Start scalp only
echo  4. Show account status
echo  5. Analyze stock
echo  6. Show today's history
echo  7. Exit
echo.
choice /c 1234567 /n /m "Select [1-7]: "

if errorlevel 7 goto end
if errorlevel 6 goto history
if errorlevel 5 goto analyze
if errorlevel 4 goto status
if errorlevel 3 goto scalp
if errorlevel 2 goto run
if errorlevel 1 goto run_all

:run_all
echo.
"%PY%" main.py run-all
echo.
pause
goto menu

:run
echo.
"%PY%" main.py run
echo.
pause
goto menu

:scalp
echo.
"%PY%" main.py scalp
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
