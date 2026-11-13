@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_agendamento_bladder.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"
if not "%INSTALL_RESULT%"=="0" (
    echo Nao foi possivel instalar. Confira a mensagem acima e logs\instalacao_agendamento_bladder.log.
) else (
    echo Instalacao concluida. O WhatsApp continua sendo iniciado manualmente.
)
pause
exit /b %INSTALL_RESULT%
