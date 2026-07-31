# ==============================================================================
# SCRIPT DE INICIALIZAÇÃO DO SERVIÇO DE COLETA SCADA — MÓDULO DE PRODUÇÃO
# Executa exclusivamente o coletor background (collect_production_scada)
# ==============================================================================

$ErrorActionPreference = "Stop"

# 1. Resolver a raiz do projeto sem depender do diretório atual
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location -Path $ProjectRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Iniciando Coletor Scada Produção (Serviço Windows)..." -ForegroundColor Cyan
Write-Host "Raiz do projeto: $ProjectRoot" -ForegroundColor Gray
Write-Host "==================================================" -ForegroundColor Cyan

# 2. Verificar se .venv\Scripts\python.exe existe
$PythonExec = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExec)) {
    Write-Host "[ERRO] Ambiente virtual '.venv' não encontrado em: $PythonExec" -ForegroundColor Red
    Write-Host "Por favor, utilize o ambiente virtual existente com Python 3.11." -ForegroundColor Red
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

# 5. Executar o coletor Scada
Write-Host "Executando o comando manage.py collect_production_scada..." -ForegroundColor Yellow
& $PythonExec manage.py collect_production_scada @args

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] O coletor Scada foi encerrado com código de falha: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Coletor Scada finalizado com sucesso." -ForegroundColor Green
