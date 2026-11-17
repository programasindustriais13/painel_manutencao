# Executar uma vez no servidor, em PowerShell como administrador, após o deploy.
# Não aplica migrations nem envia dados durante a instalação.
[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot
$PythonExec = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExec)) { throw 'Ambiente .venv não encontrado.' }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'credentials.json'))) { throw 'credentials.json não encontrado.' }
& $PythonExec manage.py check
if ($LASTEXITCODE -ne 0) { throw 'Falha na verificação do Django.' }
& $PythonExec manage.py migrate --check --noinput --database default
if ($LASTEXITCODE -ne 0) { throw 'Aplique as migrations pelo deploy normal antes de instalar a tarefa.' }
& $PythonExec manage.py sincronizar_producao_drs --verificar-instalacao
if ($LASTEXITCODE -ne 0) { throw 'A tarefa deve ser instalada no servidor de produção com DEBUG=False.' }
if ($CheckOnly) { Write-Host 'Pré-verificação concluída. Nenhuma tarefa foi instalada.'; exit 0 }
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Execute este script em PowerShell como administrador para cadastrar a tarefa.'
}
$Runner = Join-Path $ProjectRoot 'scripts\executar_sincronizacao_drs_bladder.ps1'
$Action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -WorkingDirectory $ProjectRoot -Argument (
    '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $Runner + '"'
)
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$TaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 8) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Painel Manutencao - DRs Producao Bladder' -Action $Action -Trigger $Trigger -Principal $TaskPrincipal -Settings $TaskSettings -Description 'Sincroniza a fila persistente DR.114/115 a cada minuto, sem alterar as colunas das planilhas.' -Force | Out-Null
Write-Host 'Tarefa instalada. Primeira execução em um minuto; não é necessário usuário conectado.'
Write-Host 'A conta de serviço de credentials.json precisa de acesso de edição às duas DRs.'
