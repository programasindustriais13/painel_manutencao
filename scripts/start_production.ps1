# ==============================================================================
# SCRIPT DE INICIALIZAÇÃO DE PRODUÇÃO — PAINEL DE MANUTENÇÃO INDUSTRIAL
# Servidor WSGI: Waitress | Bind: 127.0.0.1:8900 (ou configurado no .env)
# ==============================================================================

$ErrorActionPreference = "Stop"

# 1. Resolver a raiz do projeto sem depender do diretório atual
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location -Path $ProjectRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Iniciando verificações prévias para produção..." -ForegroundColor Cyan
Write-Host "Raiz do projeto: $ProjectRoot" -ForegroundColor Gray
Write-Host "==================================================" -ForegroundColor Cyan

# 2. Verificar se .venv\Scripts\python.exe existe
$PythonExec = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExec)) {
    Write-Host "[ERRO] Ambiente virtual '.venv' não encontrado em: $PythonExec" -ForegroundColor Red
    Write-Host "Por favor, crie o ambiente virtual com Python 3.11 antes de prosseguir." -ForegroundColor Red
    exit 1
}

# 3. Confirmar que o Python do .venv é 3.11
$PythonVersion = & $PythonExec --version 2>&1
Write-Host "Versão do Python: $PythonVersion" -ForegroundColor Green
if ($PythonVersion -notmatch "Python 3\.11") {
    Write-Host "[ERRO] O Python do .venv deve ser 3.11. Encontrado: $PythonVersion" -ForegroundColor Red
    exit 1
}

# 4. Confirmar que o arquivo .env existe
$EnvPath = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvPath)) {
    Write-Host "[ERRO] Arquivo de ambiente '.env' não encontrado em: $EnvPath" -ForegroundColor Red
    Write-Host "Crie o arquivo .env com base no .env.example antes de iniciar." -ForegroundColor Red
    exit 1
}

# Carregar variáveis do .env para o escopo deste script
$EnvVars = @{}
Get-Content $EnvPath | Where-Object { $_ -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$" } | ForEach-Object {
    $key = $matches[1].Trim()
    $val = $matches[2].Trim().Trim('"').Trim("'")
    $EnvVars[$key] = $val
}

# Configurações do Waitress com precedência: $env:VAR > .env file > default fallback
$WaitressHost = if ($env:WAITRESS_HOST) { $env:WAITRESS_HOST } elseif ($EnvVars.ContainsKey("WAITRESS_HOST") -and $EnvVars["WAITRESS_HOST"]) { $EnvVars["WAITRESS_HOST"] } else { "127.0.0.1" }
$WaitressPortRaw = if ($env:WAITRESS_PORT) { $env:WAITRESS_PORT } elseif ($EnvVars.ContainsKey("WAITRESS_PORT") -and $EnvVars["WAITRESS_PORT"]) { $EnvVars["WAITRESS_PORT"] } else { "8900" }
$WaitressThreadsRaw = if ($env:WAITRESS_THREADS) { $env:WAITRESS_THREADS } elseif ($EnvVars.ContainsKey("WAITRESS_THREADS") -and $EnvVars["WAITRESS_THREADS"]) { $EnvVars["WAITRESS_THREADS"] } else { "4" }

# Validação dos valores
if ([string]::IsNullOrWhiteSpace($WaitressHost)) {
    Write-Host "[ERRO] WAITRESS_HOST não pode ser vazio." -ForegroundColor Red
    exit 1
}

$WaitressPort = 0
if (-not [int]::TryParse($WaitressPortRaw, [ref]$WaitressPort) -or $WaitressPort -lt 1 -or $WaitressPort -gt 65535) {
    Write-Host "[ERRO] WAITRESS_PORT deve ser um número entre 1 e 65535. Valor recebido: '$WaitressPortRaw'" -ForegroundColor Red
    exit 1
}

$WaitressThreads = 0
if (-not [int]::TryParse($WaitressThreadsRaw, [ref]$WaitressThreads) -or $WaitressThreads -lt 1) {
    Write-Host "[ERRO] WAITRESS_THREADS deve ser um número inteiro positivo. Valor recebido: '$WaitressThreadsRaw'" -ForegroundColor Red
    exit 1
}

# 5. Verificar se a porta configurada está livre
Write-Host "Verificando se a porta $WaitressPort em $WaitressHost está livre..." -ForegroundColor Yellow
$PortOccupied = $false

try {
    $TcpConnection = Get-NetTCPConnection -LocalPort $WaitressPort -ErrorAction SilentlyContinue
    if ($TcpConnection) {
        $PortOccupied = $true
    }
} catch {
    # Fallback via TcpListener se Get-NetTCPConnection falhar ou não estiver disponível
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($WaitressHost), $WaitressPort)
        $listener.Start()
        $listener.Stop()
    } catch {
        $PortOccupied = $true
    }
}

if ($PortOccupied) {
    Write-Host "[ERRO CRÍTICO] A porta $WaitressPort já está ocupada por outro processo!" -ForegroundColor Red
    Write-Host "Verifique se o SST ou outra aplicação está utilizando esta porta antes de iniciar." -ForegroundColor Red
    exit 1
}
Write-Host "Porta $WaitressPort livre com sucesso." -ForegroundColor Green

# 6. Executar manage.py check
Write-Host "Executando checagem de integridade do Django (manage.py check)..." -ForegroundColor Yellow
& $PythonExec manage.py check
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Falha na checagem de integridade do Django." -ForegroundColor Red
    exit 1
}
Write-Host "Checagem do Django concluída sem erros." -ForegroundColor Green

# 7 e 8. Notificação de diretrizes de produção
Write-Host "--------------------------------------------------" -ForegroundColor Gray
Write-Host "Aviso: Migrações e collectstatic NÃO são executados automaticamente." -ForegroundColor Gray
Write-Host "--------------------------------------------------" -ForegroundColor Gray

# 9 e 10. Iniciar o Waitress sem exibir segredos
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Iniciando servidor WSGI Waitress..." -ForegroundColor Cyan
Write-Host "Aplicação WSGI : maintenance_project.wsgi:application" -ForegroundColor Green
Write-Host "Host Bind      : $WaitressHost" -ForegroundColor Green
Write-Host "Porta          : $WaitressPort" -ForegroundColor Green
Write-Host "Threads        : $WaitressThreads" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan

& $PythonExec -m waitress --host=$WaitressHost --port=$WaitressPort --threads=$WaitressThreads maintenance_project.wsgi:application
