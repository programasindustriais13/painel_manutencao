@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem O bloco e interpretado antes do pull, inclusive se este arquivo for atualizado.
(
    echo ======================================================================
    echo   PIPELINE DE DEPLOY AUTOMATIZADO - PNEUS FREEDOM
    echo ======================================================================
    echo.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy_servidor.ps1" %*
    if errorlevel 1 (
        echo.
        echo [ERRO] Atualizacao ou deploy falhou. Confira a mensagem acima.
        echo O processo nao foi declarado como concluido.
        pause
        exit /b 1
    )
    echo.
    echo [CONCLUIDO] Operacao finalizada com exito.
    echo Se o codigo do WhatsApp foi atualizado, reinicie o Node manualmente.
    pause
    exit /b 0
)
