@echo off
setlocal
cd /d "%~dp0"

echo ======================================================================
echo   PIPELINE DE DEPLOY AUTOMATIZADO - PNEUS FREEDOM
echo ======================================================================
echo.
echo Executando deploy seguro apos o git pull...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy_production.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ======================================================================
    echo [ERRO] O processo de deploy falhou com codigo de saida %ERRORLEVEL%.
    echo Verifique as mensagens de erro acima.
    echo ======================================================================
    echo.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ======================================================================
echo [CONCLUIDO] Processo de deploy no servidor finalizado com exito!
echo ======================================================================
echo.
pause
exit /b 0

