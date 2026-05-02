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
set "SWING_INTERVAL=300"
set /p "SWING_INTERVAL=Swing interval seconds [300]: "
if "%SWING_INTERVAL%"=="" set "SWING_INTERVAL=300"
set "SCALP_CODE="
set /p "SCALP_CODE=Scalp stock code [env/default]: "
set "SCALP_INTERVAL="
set /p "SCALP_INTERVAL=Scalp interval seconds [env/default]: "
if "%SCALP_CODE%"=="" (
    if "%SCALP_INTERVAL%"=="" (
        "%PY%" main.py run-all --swing-interval %SWING_INTERVAL%
    ) else (
        "%PY%" main.py run-all --swing-interval %SWING_INTERVAL% --scalp-interval %SCALP_INTERVAL%
    )
) else (
    if "%SCALP_INTERVAL%"=="" (
        "%PY%" main.py run-all --swing-interval %SWING_INTERVAL% --scalp-code %SCALP_CODE%
    ) else (
        "%PY%" main.py run-all --swing-interval %SWING_INTERVAL% --scalp-code %SCALP_CODE% --scalp-interval %SCALP_INTERVAL%
    )
)
echo.
pause
goto menu

:run
echo.
set "INTERVAL=300"
set /p "INTERVAL=Swing interval seconds [300]: "
if "%INTERVAL%"=="" set "INTERVAL=300"
"%PY%" main.py run --interval %INTERVAL%
echo.
pause
goto menu

:scalp
echo.
set "CODE="
set /p "CODE=Scalp stock code [env/default]: "
set "INTERVAL="
set /p "INTERVAL=Scalp interval seconds [env/default]: "
if "%CODE%"=="" (
    if "%INTERVAL%"=="" (
        "%PY%" main.py scalp
    ) else (
        "%PY%" main.py scalp --interval %INTERVAL%
    )
) else (
    if "%INTERVAL%"=="" (
        "%PY%" main.py scalp %CODE%
    ) else (
        "%PY%" main.py scalp %CODE% --interval %INTERVAL%
    )
)
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
