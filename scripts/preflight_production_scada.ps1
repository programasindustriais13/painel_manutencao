# ==============================================================================
# SCRIPT DE PREFLIGHT SOMENTE LEITURA — MÓDULO DE PRODUÇÃO E COLETOR SCADA
# Audita o ambiente do Windows Server sem modificar o sistema ou os bancos de dados.
# ==============================================================================

$ErrorActionPreference = "Continue"

# 1. Resolver a raiz do projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location -Path $ProjectRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " RELATORIO DE PREFLIGHT - SCADA E PRODUCAO (SOMENTE LEITURA)" -ForegroundColor Cyan
Write-Host " Data/Hora: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host " Raiz do projeto: $ProjectRoot" -ForegroundColor Gray
Write-Host "==================================================" -ForegroundColor Cyan

$ChecksPassed = $true

# 2. Verificar Python do sistema e da .venv
Write-Host "`n[1/12] Verificando versao do Python e .venv..." -ForegroundColor Yellow
$PythonExec = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $PythonExec) {
    $PyVer = & $PythonExec --version 2>&1
    Write-Host "  [OK] .venv encontrado: $PyVer" -ForegroundColor Green
    if ($PyVer -notmatch "Python 3\.11") {
        Write-Host "  [ALERTA] Esperado Python 3.11 no .venv. Encontrado: $PyVer" -ForegroundColor Red
        $ChecksPassed = $false
    }
} else {
    Write-Host "  [ERRO] .venv nao encontrado em $PythonExec" -ForegroundColor Red
    $ChecksPassed = $false
}

# 3. Verificar estado do Git (branch, commit, status)
Write-Host "`n[2/12] Verificando repositorio Git..." -ForegroundColor Yellow
try {
    $Branch = git branch --show-current 2>&1
    $Commit = git log -n 1 --oneline 2>&1
    $Status = git status --short 2>&1

    Write-Host "  Branch atual : $Branch" -ForegroundColor Green
    Write-Host "  Ultimo commit: $Commit" -ForegroundColor Green

    if ($Status) {
        Write-Host "  [ALERTA] Mudancas locais pendentes no Git:" -ForegroundColor Yellow
        $Status | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    } else {
        Write-Host "  [OK] Workspace limpo sem alteracoes locais pendentes." -ForegroundColor Green
    }
} catch {
    Write-Host "  [ERRO] Falha ao consultar Git: $_" -ForegroundColor Red
    $ChecksPassed = $false
}

# 4. Verificar existencia e variaveis do .env (sem exibir senhas!)
Write-Host "`n[3/12] Auditando arquivo .env..." -ForegroundColor Yellow
$EnvPath = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvPath) {
    Write-Host "  [OK] Arquivo .env presente." -ForegroundColor Green
    $EnvContent = Get-Content $EnvPath
    $RequiredVars = @("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "SCADA_DB_ENGINE", "SCADA_DB_NAME", "SCADA_DB_USER", "SCADA_DB_PASSWORD", "SCADA_DB_HOST", "SCADA_DB_PORT")

    foreach ($varName in $RequiredVars) {
        $found = $EnvContent | Where-Object { $_ -match "^\s*$varName\s*=" }
        if ($found) {
            Write-Host "  [OK] Variavel presente: $varName" -ForegroundColor Green
        } else {
            Write-Host "  [ERRO] Variavel ausente no .env: $varName" -ForegroundColor Red
            $ChecksPassed = $false
        }
    }
} else {
    Write-Host "  [ERRO] Arquivo .env ausente em $EnvPath" -ForegroundColor Red
    $ChecksPassed = $false
}

# 5. Executar check de integridade do Django
Write-Host "`n[4/12] Checagem de integridade do Django (manage.py check)..." -ForegroundColor Yellow
if (Test-Path $PythonExec) {
    $CheckOutput = & $PythonExec manage.py check 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Django check executado com sucesso (0 erros de sistema)." -ForegroundColor Green
    } else {
        Write-Host "  [ERRO] Django check reportou erros:" -ForegroundColor Red
        $CheckOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        $ChecksPassed = $false
    }
}

# 6. Analisar status das migracoes pendentes no banco default
Write-Host "`n[5/12] Verificando migracoes pendentes no banco default..." -ForegroundColor Yellow
if (Test-Path $PythonExec) {
    $PlanOutput = & $PythonExec manage.py migrate --plan --database=default 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Plano de migracao do banco default consultado com sucesso." -ForegroundColor Green
        $PlanOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    } else {
        Write-Host "  [ERRO] Falha ao consultar migracoes do banco default:" -ForegroundColor Red
        $PlanOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        $ChecksPassed = $false
    }
}

# 7. Verificar diretorio e arquivo de logs
Write-Host "`n[6/12] Verificando infraestrutura de logs..." -ForegroundColor Yellow
$LogsDir = Join-Path $ProjectRoot "logs"
if (Test-Path $LogsDir) {
    Write-Host "  [OK] Diretorio de logs presente: $LogsDir" -ForegroundColor Green
} else {
    Write-Host "  [INFO] Diretorio de logs sera criado automaticamente: $LogsDir" -ForegroundColor Yellow
}

# 8. Verificar porta do Waitress WSGI (8900)
Write-Host "`n[7/12] Verificando status da porta 8900 (Waitress)..." -ForegroundColor Yellow
$WaitressConn = Get-NetTCPConnection -LocalPort 8900 -ErrorAction SilentlyContinue
if ($WaitressConn) {
    Write-Host "  [OK] Porta 8900 em uso (Waitress ativo, PID: $($WaitressConn.OwningProcess[0]))." -ForegroundColor Green
} else {
    Write-Host "  [INFO] Porta 8900 livre ou Waitress nao iniciado no momento." -ForegroundColor Yellow
}

# 9. Verificar Cloudflare Tunnel
Write-Host "`n[8/12] Verificando servico Cloudflare Tunnel (cloudflared)..." -ForegroundColor Yellow
$CloudflaredProc = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
if ($CloudflaredProc) {
    Write-Host "  [OK] Cloudflare Tunnel em execucao (PID: $($CloudflaredProc.Id[0]))." -ForegroundColor Green
} else {
    Write-Host "  [ALERTA] Processo cloudflared nao detectado. Confirmar se roda como servico Windows." -ForegroundColor Yellow
}

# 10. Verificar arquivos de backup recentes
Write-Host "`n[9/12] Verificando existencia de backup preventivo..." -ForegroundColor Yellow
$Backups = Get-ChildItem -Path $ProjectRoot -Filter "db.sqlite3*" | Where-Object { $_.Name -like "*.bak*" }
if ($Backups) {
    Write-Host "  [OK] Arquivos de backup encontrados na raiz:" -ForegroundColor Green
    $Backups | ForEach-Object { Write-Host "    $($_.Name) ($([math]::Round($_.Length/1KB, 2)) KB) - $($_.LastWriteTime)" -ForegroundColor Gray }
} else {
    Write-Host "  [ALERTA] Nenhum arquivo .bak encontrado na raiz do projeto. Backup deve ser feito antes do deploy real." -ForegroundColor Yellow
}

# 11. Verificar servico do coletor
Write-Host "`n[10/12] Verificando servico ou processo do coletor Scada..." -ForegroundColor Yellow
$LockFile = Join-Path $ProjectRoot "scada_collector.lock"
if (Test-Path $LockFile) {
    $LockPid = Get-Content $LockFile -ErrorAction SilentlyContinue
    Write-Host "  [OK] Lock de processo detectado (PID registrado: $LockPid)." -ForegroundColor Green
} else {
    Write-Host "  [INFO] Nenhum lock ativo detectado (coletor nao esta em execucao no momento)." -ForegroundColor Yellow
}

# 12. Resumo final do preflight
Write-Host "`n==================================================" -ForegroundColor Cyan
if ($ChecksPassed) {
    Write-Host " PREFLIGHT CONCLUIDO COM SUCESSO - SERVIDORES PRONTOS" -ForegroundColor Green
} else {
    Write-Host " PREFLIGHT FINALIZADO COM PENDENCIAS / AVISOS" -ForegroundColor Yellow
}
Write-Host "==================================================" -ForegroundColor Cyan
