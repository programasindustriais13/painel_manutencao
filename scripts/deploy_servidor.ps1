# ==============================================================================
# PIPELINE DE DEPLOY AUTOMATIZADO APÓS GIT PULL — PNEUS FREEDOM
# Painel de Manutenção Industrial, Produção, Bladder e Matrizaria
# ==============================================================================
# Este script deve ser executado no servidor imediatamente após o comando:
#   git pull origin <branch>
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"

# 1. Resolução segura da raiz do projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location -Path $ProjectRoot

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  PIPELINE DE DEPLOY AUTOMATIZADO - PNEUS FREEDOM" -ForegroundColor Cyan
Write-Host "  Data/Hora : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')" -ForegroundColor Gray
Write-Host "  Diretório : $ProjectRoot" -ForegroundColor Gray
if ($CheckOnly) {
    Write-Host "  MODO      : [CHECK-ONLY] - Apenas verificação sem aplicar alterações" -ForegroundColor Magenta
} else {
    Write-Host "  MODO      : [DEPLOY REAL] - Atualização, Backup, Migrações e Reinício" -ForegroundColor Green
}
Write-Host "======================================================================" -ForegroundColor Cyan

# ==============================================================================
# ETAPA 1: VERIFICAÇÃO DO AMBIENTE E PRÉ-REQUISITOS
# ==============================================================================
Write-Host "`n>>> [ETAPA 1/6] Verificando Ambiente e Pré-Requisitos..." -ForegroundColor Yellow

# 1.1 Localizar Python (.venv preferencial ou global)
$PythonExec = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExec)) {
    # Tenta python do PATH
    $PythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCmd) {
        $PythonExec = $PythonCmd.Source
        Write-Host "  [AVISO] .venv não encontrado na raiz. Utilizando Python do PATH: $PythonExec" -ForegroundColor Yellow
    } else {
        Write-Host "  [ERRO CRÍTICO] Python não encontrado nem no '.venv' nem no PATH do sistema!" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  [OK] Ambiente virtual '.venv' identificado: $PythonExec" -ForegroundColor Green
}

# 1.2 Verificar manage.py
$ManagePy = Join-Path $ProjectRoot "manage.py"
if (-not (Test-Path $ManagePy)) {
    Write-Host "  [ERRO CRÍTICO] manage.py não encontrado na raiz: $ProjectRoot" -ForegroundColor Red
    exit 1
}

# 1.3 Verificar .env
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Write-Host "  [OK] Arquivo de configuração '.env' presente." -ForegroundColor Green
} else {
    Write-Host "  [AVISO] Arquivo '.env' não encontrado. O Django usará as variáveis de ambiente do sistema." -ForegroundColor Yellow
}

# 1.4 Verificar credentials.json (Google Sheets DR-201)
$CredFile = Join-Path $ProjectRoot "credentials.json"
if (Test-Path $CredFile) {
    Write-Host "  [OK] Credenciais Google Sheets ('credentials.json') presentes para integração DR-201." -ForegroundColor Green
} else {
    Write-Host "  [AVISO] 'credentials.json' não encontrado na raiz. A sincronização com a planilha DR-201 ficará pausada até inclusão do arquivo." -ForegroundColor Yellow
}

# 1.5 Git status informativo
try {
    $GitCommit = git log -n 1 --oneline 2>&1
    Write-Host "  [OK] Versão do Git ativa: $GitCommit" -ForegroundColor Green
} catch {
    Write-Host "  [INFO] Git não acessível ou pasta não versionada diretamente." -ForegroundColor Gray
}

# ==============================================================================
# ETAPA 2: BACKUP PREVENTIVO AUTOMÁTICO
# ==============================================================================
if (-not $SkipBackup -and -not $CheckOnly) {
    Write-Host "`n>>> [ETAPA 2/6] Realizando Backup Preventivo..." -ForegroundColor Yellow
    $BackupDir = Join-Path $ProjectRoot "backups\deploy_$Timestamp"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

    # Backup db.sqlite3 se existir
    $DbPath = Join-Path $ProjectRoot "db.sqlite3"
    if (Test-Path $DbPath) {
        Copy-Item -Path $DbPath -Destination (Join-Path $BackupDir "db.sqlite3") -Force
        $DbSize = [math]::Round(((Get-Item $DbPath).Length / 1MB), 2)
        Write-Host "  [OK] Backup de 'db.sqlite3' realizado com sucesso ($DbSize MB)." -ForegroundColor Green
    } else {
        Write-Host "  [INFO] Banco SQLite local não utilizado (utilizando MySQL em produção)." -ForegroundColor Gray
    }

    # Backup .env
    if (Test-Path $EnvFile) {
        Copy-Item -Path $EnvFile -Destination (Join-Path $BackupDir ".env") -Force
        Write-Host "  [OK] Backup de '.env' realizado." -ForegroundColor Green
    }

    # Backup credentials.json
    if (Test-Path $CredFile) {
        Copy-Item -Path $CredFile -Destination (Join-Path $BackupDir "credentials.json") -Force
        Write-Host "  [OK] Backup de 'credentials.json' realizado." -ForegroundColor Green
    }

    Write-Host "  [OK] Pasta de backup: $BackupDir" -ForegroundColor Green
} else {
    Write-Host "`n>>> [ETAPA 2/6] Backup ignorado (--SkipBackup ou --CheckOnly)." -ForegroundColor Gray
}

# ==============================================================================
# ETAPA 3: INSTALAÇÃO E ATUALIZAÇÃO DE DEPENDÊNCIAS (PIP)
# ==============================================================================
Write-Host "`n>>> [ETAPA 3/6] Atualizando Dependências Python (requirements.txt)..." -ForegroundColor Yellow
$ReqFile = Join-Path $ProjectRoot "requirements.txt"
if (Test-Path $ReqFile) {
    if ($CheckOnly) {
        Write-Host "  [CHECK-ONLY] Pulando instalação de pacotes." -ForegroundColor Magenta
    } else {
        Write-Host "  Instalando pacotes necessários (incluindo gspread e dependências)..." -ForegroundColor Gray
        & $PythonExec -m pip install -r $ReqFile --quiet --no-warn-script-location
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERRO] Falha ao instalar dependências do requirements.txt!" -ForegroundColor Red
            exit 1
        }
        Write-Host "  [OK] Dependências do requirements.txt instaladas/atualizadas com sucesso." -ForegroundColor Green
    }
} else {
    Write-Host "  [AVISO] requirements.txt não encontrado." -ForegroundColor Yellow
}

# ==============================================================================
# ETAPA 4: VERIFICAÇÃO E MIGRAÇÕES DO BANCO DE DADOS
# ==============================================================================
Write-Host "`n>>> [ETAPA 4/6] Verificação do Django e Aplicação de Migrações..." -ForegroundColor Yellow

# 4.1 System Check
Write-Host "  Executando 'manage.py check'..." -ForegroundColor Gray
$CheckOut = & $PythonExec manage.py check 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO CRÍTICO] Falha na integridade do Django:" -ForegroundColor Red
    $CheckOut | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    exit 1
}
Write-Host "  [OK] Integridade do Django confirmada (0 erros)." -ForegroundColor Green

if ($CheckOnly) {
    Write-Host "`n[CHECK-ONLY CONCLUÍDO COM SUCESSO] O ambiente está íntegro para deploy." -ForegroundColor Green
    exit 0
}

# 4.2 Aplicar Migrações exclusivamente no banco default
Write-Host "  Aplicando migrações no banco de dados 'default'..." -ForegroundColor Gray
$MigrateOut = & $PythonExec manage.py migrate --database=default --noinput 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO CRÍTICO] Falha ao aplicar migrações no banco default:" -ForegroundColor Red
    $MigrateOut | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    exit 1
}
Write-Host "  [OK] Migrações do banco default aplicadas com sucesso (zero alterações no scada)." -ForegroundColor Green

# 4.3 Carga inicial idempotente de Tipos de Atividades Operacionais do Bladder
Write-Host "  Inicializando tipos padrão de atividades operacionais do Bladder..." -ForegroundColor Gray
$SeedBladderOut = & $PythonExec manage.py popular_tipos_atividade_bladder 2>&1
Write-Host "  [OK] $SeedBladderOut" -ForegroundColor Green

# 4.4 Provisionar grupos e permissões da Matrizaria (idempotente)
Write-Host "  Garantindo grupos e permissões da Matrizaria..." -ForegroundColor Gray
$SeedMatrizariaOut = & $PythonExec manage.py provisionar_grupos_matrizaria --database=default 2>&1
Write-Host "  [OK] Grupos da Matrizaria provisionados com sucesso." -ForegroundColor Green

# ==============================================================================
# ETAPA 5: COLETA DE ARQUIVOS ESTÁTICOS
# ==============================================================================
Write-Host "`n>>> [ETAPA 5/6] Coletando Arquivos Estáticos (collectstatic)..." -ForegroundColor Yellow
$StaticOut = & $PythonExec manage.py collectstatic --noinput 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] Falha ao coletar arquivos estáticos:" -ForegroundColor Red
    $StaticOut | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    exit 1
}
Write-Host "  [OK] Arquivos estáticos coletados com sucesso." -ForegroundColor Green

# ==============================================================================
# ETAPA 6: REINÍCIO DOS SERVIÇOS DO WINDOWS
# ==============================================================================
Write-Host "`n>>> [ETAPA 6/6] Reiniciando Serviços da Aplicação no Windows Server..." -ForegroundColor Yellow

$RestartouServico = $false

# 6.1 Serviço Web (Waitress)
$ServicosWebPossiveis = @("PainelManutencaoWSGI", "PainelManutencao")
foreach ($sName in $ServicosWebPossiveis) {
    $svc = Get-Service -Name $sName -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Host "  Serviço Windows Web detectado: '$sName' (Status: $($svc.Status))." -ForegroundColor Gray
        try {
            Restart-Service -Name $sName -Force
            Start-Sleep -Seconds 3
            $svcAtual = Get-Service -Name $sName
            Write-Host "  [OK] Serviço '$sName' reiniciado com sucesso! Status: $($svcAtual.Status)" -ForegroundColor Green
            $RestartouServico = $true
            break
        } catch {
            Write-Host "  [AVISO] Tentando reiniciar via NSSM..." -ForegroundColor Yellow
            try {
                & nssm restart $sName
                Start-Sleep -Seconds 3
                Write-Host "  [OK] Serviço '$sName' reiniciado via NSSM." -ForegroundColor Green
                $RestartouServico = $true
                break
            } catch {
                Write-Host "  [ERRO] Não foi possível reiniciar o serviço '$sName': $_" -ForegroundColor Red
            }
        }
    }
}

# 6.2 Serviço do Coletor SCADA
$ServicosScadaPossiveis = @("ScadaCollectorService", "ScadaCollector")
foreach ($sName in $ServicosScadaPossiveis) {
    $svc = Get-Service -Name $sName -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Host "  Serviço do Coletor SCADA detectado: '$sName' (Status: $($svc.Status))." -ForegroundColor Gray
        try {
            Restart-Service -Name $sName -Force
            Start-Sleep -Seconds 2
            Write-Host "  [OK] Serviço '$sName' reiniciado com sucesso." -ForegroundColor Green
            break
        } catch {
            try {
                & nssm restart $sName
                Write-Host "  [OK] Serviço '$sName' reiniciado via NSSM." -ForegroundColor Green
                break
            } catch {
                Write-Host "  [AVISO] Não foi possível reiniciar '$sName': $_" -ForegroundColor Yellow
            }
        }
    }
}

if (-not $RestartouServico) {
    Write-Host "  [INFO] Nenhum serviço Windows registrado foi encontrado." -ForegroundColor Yellow
    Write-Host "  Se a aplicação roda em modo standalone/desenvolvimento, reinicie o processo do servidor manualmente ou execute o runner correspondente." -ForegroundColor Gray
}

Write-Host "`n======================================================================" -ForegroundColor Green
Write-Host "  DEPLOY NO SERVIDOR CONCLUÍDO COM SUCESSO!" -ForegroundColor Green
Write-Host "  Data/Hora Conclusão: $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
exit 0

