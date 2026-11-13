param([switch]$Elevated)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ExpectedRoot = 'C:\03_PYTHON\11_Painel Manutencao\painel_manutencao'

try {
    if ($ProjectRoot.TrimEnd('\') -ine $ExpectedRoot) {
        throw "Execute este instalador apenas no servidor, na pasta $ExpectedRoot. Nenhuma tarefa foi criada."
    }
    $LogDirectory = Join-Path $ProjectRoot 'logs'
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $InstallLog = Join-Path $LogDirectory 'instalacao_agendamento_bladder.log'
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        if ($Elevated) { throw 'Execute com uma conta administradora do servidor.' }
        Write-Host 'O Windows solicitara permissao para cadastrar a tarefa automatica.'
        $Child = Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'), '-Elevated'
        )
        if (Test-Path -LiteralPath $InstallLog) { Get-Content -LiteralPath $InstallLog }
        exit $Child.ExitCode
    }

    Start-Transcript -Path $InstallLog -Force | Out-Null
    Set-Location -LiteralPath $ProjectRoot
    $PythonExec = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $PythonExec)) { throw 'Ambiente .venv nao encontrado. Execute o deploy normal primeiro.' }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.env'))) { throw 'Arquivo .env nao encontrado.' }
    & $PythonExec manage.py check
    if ($LASTEXITCODE -ne 0) { throw 'Falha na verificacao do Django.' }
    & $PythonExec manage.py migrate --check --noinput
    if ($LASTEXITCODE -ne 0) { throw 'Existem migracoes pendentes. Execute o deploy normal e abra o instalador novamente.' }
    & $PythonExec manage.py enviar_resumo_estoque_bladder --verificar-instalacao
    if ($LASTEXITCODE -ne 0) { throw 'O servidor deve usar DEBUG=False e WHATSAPP_DRY_RUN=False. Confira o .env.' }

    $TaskName = 'Painel Manutencao - WhatsApp Bladder'
    $Runner = Join-Path $ProjectRoot 'scripts\executar_agendamento_bladder.ps1'
    $Action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -WorkingDirectory $ProjectRoot -Argument (
        '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $Runner + '"'
    )
    # Sem duracao: a repeticao continua apos reiniciar o Windows.
    $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $TaskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $TaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $TaskPrincipal -Settings $TaskSettings -Description 'Verifica o resumo Bladder a cada minuto. Nao inicia nem reinicia o WhatsApp.' -Force | Out-Null
    Write-Host "Tarefa cadastrada: $TaskName"
    Write-Host 'Executa a cada minuto, mesmo sem usuario conectado. Dias e horario sao definidos no administrador.'
    Write-Host 'O WhatsApp deve continuar sendo iniciado e conferido manualmente.'
    Write-Host 'Logs diarios: logs\whatsapp_bladder_YYYY-MM-DD.log'
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host ('ERRO: ' + $_.Exception.Message)
    if ($Elevated) { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null }
    exit 1
}
