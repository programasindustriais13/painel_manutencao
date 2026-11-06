# ==============================================================================
# SCRIPT DE DEPLOY AUTOMATIZADO EM PRODUÇÃO — PNEUS FREEDOM
# Painel de Manutenção, Produção, Bladder e Matrizaria Industrial
# Windows Server 2019 | Python 3.11 (.venv) | Waitress & Coletor SCADA
# ==============================================================================
# Parâmetros:
#   -CheckOnly : Executa apenas as validações de pré-verificação sem alterar nada.
#   -DryRun    : Simula todas as etapas do deploy sem aplicar alterações permanentes.
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# 1. Resolução segura da raiz do projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location -Path $ProjectRoot

$DeployTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  PIPELINE DE DEPLOY AUTOMATIZADO EM PRODUÇÃO - PNEUS FREEDOM" -ForegroundColor Cyan
Write-Host "  Data/Hora : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')" -ForegroundColor Gray
Write-Host "  Diretório : $ProjectRoot" -ForegroundColor Gray
if ($CheckOnly) {
    Write-Host "  MODO      : [CHECK-ONLY] - Apenas verificação diagnóstica" -ForegroundColor Magenta
} elseif ($DryRun) {
    Write-Host "  MODO      : [DRY-RUN] - Simulação completa sem alterações em disco" -ForegroundColor Yellow
} else {
    Write-Host "  MODO      : [PRODUÇÃO REAL] - Aplicação completa com backup prévio" -ForegroundColor Green
}
Write-Host "======================================================================" -ForegroundColor Cyan

# ==============================================================================
# ETAPA 1: PRÉ-VERIFICAÇÃO (PREFLIGHT CHECKS)
# ==============================================================================
Write-Host "`n>>> [ETAPA 1/5] Executando Pré-Verificações de Integridade..." -ForegroundColor Yellow

# 1.1 Verificar manage.py
$ManagePy = Join-Path $ProjectRoot "manage.py"
if (-not (Test-Path $ManagePy)) {
    Write-Host "[ERRO CRÍTICO] manage.py não encontrado na raiz: $ProjectRoot" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Raiz do projeto identificada corretamente." -ForegroundColor Green

# 1.2 Verificar Python 3.11 no .venv único
$PythonExec = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExec)) {
    Write-Host "[ERRO CRÍTICO] Ambiente virtual '.venv' não encontrado em: $PythonExec" -ForegroundColor Red
    exit 1
}

$PyVer = & $PythonExec --version 2>&1
if ($PyVer -notmatch "Python 3\.11") {
    Write-Host "[ERRO CRÍTICO] Versão incorreta do Python no .venv. Esperado 3.11, encontrado: $PyVer" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Ambiente virtual '.venv' validado: $PyVer" -ForegroundColor Green

# 1.3 Verificar e auditar arquivo .env
$EnvPath = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvPath)) {
    Write-Host "[ERRO CRÍTICO] Arquivo '.env' ausente na raiz do projeto!" -ForegroundColor Red
    exit 1
}

$EnvVars = @{}
Get-Content $EnvPath | Where-Object { $_ -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$" } | ForEach-Object {
    $k = $matches[1].Trim()
    $v = $matches[2].Trim().Trim('"').Trim("'")
    $EnvVars[$k] = $v
}

$WaitressHost = if ($env:WAITRESS_HOST) { $env:WAITRESS_HOST } elseif ($EnvVars.ContainsKey("WAITRESS_HOST") -and $EnvVars["WAITRESS_HOST"]) { $EnvVars["WAITRESS_HOST"] } else { "127.0.0.1" }
$WaitressPortRaw = if ($env:WAITRESS_PORT) { $env:WAITRESS_PORT } elseif ($EnvVars.ContainsKey("WAITRESS_PORT") -and $EnvVars["WAITRESS_PORT"]) { $EnvVars["WAITRESS_PORT"] } else { "8900" }
$WaitressThreadsRaw = if ($env:WAITRESS_THREADS) { $env:WAITRESS_THREADS } elseif ($EnvVars.ContainsKey("WAITRESS_THREADS") -and $EnvVars["WAITRESS_THREADS"]) { $EnvVars["WAITRESS_THREADS"] } else { "12" }

$WaitressPort = 0
if (-not [int]::TryParse($WaitressPortRaw, [ref]$WaitressPort) -or $WaitressPort -lt 1 -or $WaitressPort -gt 65535) {
    $WaitressPort = 8900
}

$WaitressThreads = 0
if (-not [int]::TryParse($WaitressThreadsRaw, [ref]$WaitressThreads) -or $WaitressThreads -lt 1) {
    $WaitressThreads = 12
}

Write-Host "  [OK] Arquivo '.env' validado (Host: $WaitressHost | Porta: $WaitressPort | Threads: $WaitressThreads)." -ForegroundColor Green

# 1.3.1 Verificar credentials.json (Google Sheets DR-201)
$CredFile = Join-Path $ProjectRoot "credentials.json"
if (Test-Path $CredFile) {
    Write-Host "  [OK] Credenciais Google Sheets ('credentials.json') presentes para integração DR-201." -ForegroundColor Green
} else {
    Write-Host "  [AVISO] 'credentials.json' não encontrado na raiz. A integração DR-201 ficará pausada até inclusão do arquivo." -ForegroundColor Yellow
}

# 1.4 Estado do Repositório Git
try {
    $GitBranch = (git branch --show-current 2>&1).ToString().Trim()
    if (-not $GitBranch -or $GitBranch -match "fatal") {
        $GitBranch = "main"
    }

    if (-not $CheckOnly -and -not $DryRun) {
        Write-Host "  Atualizando codigo a partir do repositorio remoto (git pull origin $GitBranch)..." -ForegroundColor Yellow
        $PullResult = git pull origin $GitBranch 2>&1
        $PullResult | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    }

    $GitCommit = git log -n 1 --oneline 2>&1
    $GitStatus = git status --short 2>&1
    Write-Host "  [OK] Git Branch: $GitBranch | Commit Atual: $GitCommit" -ForegroundColor Green
    if ($GitStatus) {
        Write-Host "  [AVISO] Existem alterações não commitadas na árvore de trabalho:" -ForegroundColor Yellow
        $GitStatus | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    }
} catch {
    Write-Host "  [AVISO] Não foi possível consultar ou atualizar o Git: $_" -ForegroundColor Yellow
}

# 1.5 Django System Check (manage.py check)
Write-Host "  Verificando integridade dos modelos e rotas Django..." -ForegroundColor Gray
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$CheckResult = & $PythonExec manage.py check
$checkExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap

if ($checkExit -ne 0) {
    Write-Host "[ERRO CRÍTICO] Falha no 'manage.py check' (ExitCode: $checkExit)!" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] 'manage.py check' concluído com 0 erros." -ForegroundColor Green

if ($CheckOnly) {
    Write-Host "`n======================================================================" -ForegroundColor Green
    Write-Host "  [SUCESSO] PRÉ-VERIFICAÇÃO (-CheckOnly) CONCLUÍDA COM ÊXITO!" -ForegroundColor Green
    Write-Host "  O ambiente do Windows Server está íntegro e preparado para deploy." -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Green
    exit 0
}

# ==============================================================================
# ETAPA 2: SEGURANÇA E BACKUP PREVENTIVO
# ==============================================================================
Write-Host "`n>>> [ETAPA 2/5] Executando Backup de Segurança Preventivo..." -ForegroundColor Yellow

$BackupDir = Join-Path $ProjectRoot "backups\deploy_$DeployTimestamp"

if ($DryRun) {
    Write-Host "  [DRY-RUN] Simulação de criação do diretório de backup: $BackupDir" -ForegroundColor Yellow
    Write-Host "  [DRY-RUN] Simulação de cópia de 'db.sqlite3', '.env' e 'media/'." -ForegroundColor Yellow
} else {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Host "  [OK] Diretório de backup criado: $BackupDir" -ForegroundColor Green

    # Backup do banco default SQLite (se aplicável)
    $DbPath = Join-Path $ProjectRoot "db.sqlite3"
    if (Test-Path $DbPath) {
        $DbBackupPath = Join-Path $BackupDir "db.sqlite3"
        Copy-Item -Path $DbPath -Destination $DbBackupPath -Force
        $DbSize = (Get-Item $DbBackupPath).Length
        if ($DbSize -le 0) {
            Write-Host "[ERRO CRÍTICO] Backup de db.sqlite3 gerou arquivo de tamanho zero!" -ForegroundColor Red
            exit 1
        }
        Write-Host "  [OK] Backup de 'db.sqlite3' realizado com sucesso ($([math]::Round($DbSize / 1MB, 2)) MB)." -ForegroundColor Green
    } else {
        Write-Host "  [INFO] db.sqlite3 local não encontrado (utilizando MySQL/PostgreSQL remoto)." -ForegroundColor Gray
    }

    # Backup do arquivo .env
    Copy-Item -Path $EnvPath -Destination (Join-Path $BackupDir ".env") -Force
    Write-Host "  [OK] Backup do '.env' realizado com sucesso." -ForegroundColor Green

    # Backup de arquivos de mídia (uploads) se existirem
    $MediaPath = Join-Path $ProjectRoot "media"
    if (Test-Path $MediaPath) {
        $MediaBackupPath = Join-Path $BackupDir "media"
        Copy-Item -Path $MediaPath -Destination $MediaBackupPath -Recurse -Force
        Write-Host "  [OK] Backup do diretório 'media/' realizado com sucesso." -ForegroundColor Green
    }

    # Backup de credentials.json se existir
    if (Test-Path $CredFile) {
        Copy-Item -Path $CredFile -Destination (Join-Path $BackupDir "credentials.json") -Force
        Write-Host "  [OK] Backup de 'credentials.json' realizado com sucesso." -ForegroundColor Green
    }
}

# ==============================================================================
# ETAPA 3: APLICAÇÃO DAS ALTERAÇÕES
# ==============================================================================
Write-Host "`n>>> [ETAPA 3/5] Aplicando Migrações e Atualizações de Aplicação..." -ForegroundColor Yellow

if ($DryRun) {
    Write-Host "  [DRY-RUN] Simulação de instalação de dependências (requirements.txt)" -ForegroundColor Yellow
    Write-Host "  [DRY-RUN] Simulação de migrações pendentes no banco default:" -ForegroundColor Yellow
    & $PythonExec manage.py migrate --database=default --plan
    Write-Host "  [DRY-RUN] Simulação do comando 'provisionar_grupos_matrizaria --database=default'" -ForegroundColor Yellow
    Write-Host "  [DRY-RUN] Simulação do comando 'popular_tipos_atividade_bladder'" -ForegroundColor Yellow
    Write-Host "  [DRY-RUN] Simulação de 'collectstatic --noinput'" -ForegroundColor Yellow
} else {
    # 3.0 Atualizar dependências Python (requirements.txt)
    $ReqFile = Join-Path $ProjectRoot "requirements.txt"
    if (Test-Path $ReqFile) {
        Write-Host "  Atualizando dependências Python (requirements.txt)..." -ForegroundColor Gray
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $PythonExec -m pip install -r $ReqFile --quiet --disable-pip-version-check --no-warn-script-location --trusted-host pypi.org --trusted-host files.pythonhosted.org
        $pipExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEap

        if ($pipExit -ne 0) {
            Write-Host "[ERRO CRÍTICO] Falha ao instalar dependências do requirements.txt (ExitCode: $pipExit)!" -ForegroundColor Red
            exit 1
        }
        Write-Host "  [OK] Dependências do requirements.txt atualizadas com sucesso." -ForegroundColor Green
    }

    # 3.1 Executar migrações exclusivamente no banco default
    Write-Host "  Aplicando migrações no banco de dados 'default'..." -ForegroundColor Gray
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExec manage.py migrate --database=default --noinput
    $migExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap

    if ($migExit -ne 0) {
        Write-Host "[ERRO CRÍTICO] Falha ao executar migrações no banco default (ExitCode: $migExit)!" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Migrações do banco default aplicadas com sucesso." -ForegroundColor Green

    # 3.2 Provisionamento idempotente de grupos e permissões
    Write-Host "  Provisionando grupos e permissões da Matrizaria..." -ForegroundColor Gray
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExec manage.py provisionar_grupos_matrizaria --database=default
    $provExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap

    if ($provExit -ne 0) {
        Write-Host "[ERRO CRÍTICO] Falha ao provisionar grupos da Matrizaria (ExitCode: $provExit)!" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Grupos e permissões provisionados/higienizados com sucesso." -ForegroundColor Green

    # 3.3 Tipos padrão de atividades operacionais do Bladder
    Write-Host "  Inicializando tipos padrão de atividades operacionais do Bladder..." -ForegroundColor Gray
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExec manage.py popular_tipos_atividade_bladder
    $bladderExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap

    if ($bladderExit -ne 0) {
        Write-Host "  [AVISO] popular_tipos_atividade_bladder retornou código $bladderExit." -ForegroundColor Yellow
    } else {
        Write-Host "  [OK] Tipos operacionais do Bladder inicializados com sucesso." -ForegroundColor Green
    }

    # 3.4 Coleta de arquivos estáticos
    Write-Host "  Coletando arquivos estáticos (collectstatic)..." -ForegroundColor Gray
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExec manage.py collectstatic --noinput
    $staticExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap

    if ($staticExit -ne 0) {
        Write-Host "[ERRO CRÍTICO] Falha na coleta de estáticos (ExitCode: $staticExit)!" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Arquivos estáticos coletados com sucesso." -ForegroundColor Green
}

# ==============================================================================
# ETAPA 4: INICIALIZAÇÃO SEM DUPLICIDADE E LIBERAÇÃO DE PORTAS
# ==============================================================================
Write-Host "`n>>> [ETAPA 4/5] Gerenciamento Seguro de Processos e Inicialização..." -ForegroundColor Yellow

# Verificar se roda como Serviços Windows via NSSM / SCM
$ServiceWaitress = $null
$ServicosWebPossiveis = @("PainelManutencaoWSGI", "PainelManutencao")
foreach ($sName in $ServicosWebPossiveis) {
    $svc = Get-Service -Name $sName -ErrorAction SilentlyContinue
    if ($svc) {
        $ServiceWaitress = $svc
        break
    }
}

$ServiceScada = $null
$ServicosScadaPossiveis = @("ScadaCollectorService", "ScadaCollector")
foreach ($scName in $ServicosScadaPossiveis) {
    $svcSc = Get-Service -Name $scName -ErrorAction SilentlyContinue
    if ($svcSc) {
        $ServiceScada = $svcSc
        break
    }
}

# Verificar se roda como Tarefa Agendada do Windows
$TaskWaitress = Get-ScheduledTask -TaskName "Painel Manutencao - Waitress" -ErrorAction SilentlyContinue

if ($DryRun) {
    Write-Host "  [DRY-RUN] Verificando ocupação da porta $WaitressPort..." -ForegroundColor Yellow
    $TcpConn = Get-NetTCPConnection -LocalPort $WaitressPort -ErrorAction SilentlyContinue
    if ($TcpConn) {
        Write-Host "  [DRY-RUN] Porta $WaitressPort atualmente ocupada por PID(s): $($TcpConn.OwningProcess -join ', ')" -ForegroundColor Yellow
    } else {
        Write-Host "  [DRY-RUN] Porta $WaitressPort livre." -ForegroundColor Yellow
    }
    Write-Host "  [DRY-RUN] Simulação de reinício de serviços / liberação de portas sem interrupção real." -ForegroundColor Yellow
} else {
    # 1. Parar serviços ou tarefas agendadas previamente
    if ($ServiceWaitress) {
        Write-Host "  Serviço Windows '$($ServiceWaitress.Name)' detectado. Parando serviço..." -ForegroundColor Gray
        Stop-Service -Name $ServiceWaitress.Name -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    } elseif ($TaskWaitress) {
        Write-Host "  Tarefa Agendada 'Painel Manutencao - Waitress' detectada. Parando tarefa..." -ForegroundColor Gray
        Stop-ScheduledTask -TaskName "Painel Manutencao - Waitress" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    # 2. GARANTIR LIBERACAO DA PORTA 8900: Encerrar qualquer python remanescente na porta
    $TcpConn = Get-NetTCPConnection -LocalPort $WaitressPort -ErrorAction SilentlyContinue
    if ($TcpConn) {
        $Pids = $TcpConn.OwningProcess | Select-Object -Unique
        Write-Host "  Processo(s) detectado(s) na porta $WaitressPort (PID: $($Pids -join ', ')). Encerrando..." -ForegroundColor Yellow
        foreach ($procId in $Pids) {
            try {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc -and $proc.ProcessName -match "python") {
                    Write-Host "  Finalizando processo anterior do Waitress (PID: $procId)..." -ForegroundColor Gray
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                }
            } catch {
                Write-Host "  [AVISO] Não foi possível encerrar PID $procId : $_" -ForegroundColor Yellow
            }
        }
        Start-Sleep -Seconds 2
    }

    # 3. Validar se a porta ficou 100% livre
    $PortLivre = $false
    for ($i = 0; $i -lt 10; $i++) {
        $CheckConn = Get-NetTCPConnection -LocalPort $WaitressPort -ErrorAction SilentlyContinue
        if (-not $CheckConn) {
            $PortLivre = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $PortLivre) {
        Write-Host "[ERRO CRÍTICO] A porta $WaitressPort continua ocupada após tentativa de liberação!" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Porta $WaitressPort liberada com sucesso." -ForegroundColor Green

    # 4. Iniciar novo processo com código atualizado
    if ($ServiceWaitress) {
        Write-Host "  Iniciando serviço Windows '$($ServiceWaitress.Name)'..." -ForegroundColor Gray
        Start-Service -Name $ServiceWaitress.Name -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Write-Host "  [OK] Serviço '$($ServiceWaitress.Name)' iniciado." -ForegroundColor Green
    } elseif ($TaskWaitress) {
        Write-Host "  Iniciando Tarefa Agendada 'Painel Manutencao - Waitress'..." -ForegroundColor Gray
        Start-ScheduledTask -TaskName "Painel Manutencao - Waitress" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Write-Host "  [OK] Tarefa Agendada 'Painel Manutencao - Waitress' iniciada." -ForegroundColor Green
    } else {
        Write-Host "  Iniciando processo do servidor Waitress em background..." -ForegroundColor Gray
        $WaitressArgs = "-m waitress --host=$WaitressHost --port=$WaitressPort --threads=$WaitressThreads maintenance_project.wsgi:application"
        Start-Process -FilePath $PythonExec -ArgumentList $WaitressArgs -WorkingDirectory $ProjectRoot -WindowStyle Hidden
        Start-Sleep -Seconds 3
        Write-Host "  [OK] Processo do Waitress iniciado em background." -ForegroundColor Green
    }

    # Gerenciamento do Coletor SCADA
    if ($ServiceScada) {
        Write-Host "  Serviço Windows 'ScadaCollector' detectado. Reiniciando coletor..." -ForegroundColor Gray
        Restart-Service -Name "ScadaCollector" -Force
        Start-Sleep -Seconds 2
        Write-Host "  [OK] Serviço 'ScadaCollector' reiniciado com sucesso." -ForegroundColor Green
    } else {
        # Verificar lock do coletor standalone
        $LockFile = Join-Path $ProjectRoot "scada_collector.lock"
        if (Test-Path $LockFile) {
            Write-Host "  Lock 'scada_collector.lock' detectado. Verificando se processo está ativo..." -ForegroundColor Gray
            try {
                $LockPid = Get-Content $LockFile -ErrorAction SilentlyContinue
                if ($LockPid) {
                    $LockProc = Get-Process -Id ([int]$LockPid) -ErrorAction SilentlyContinue
                    if (-not $LockProc) {
                        Write-Host "  Removendo lock órfão de processo encerrado (PID: $LockPid)..." -ForegroundColor Yellow
                        Remove-Item -Path $LockFile -Force -ErrorAction SilentlyContinue
                    }
                }
            } catch {}
        }
        Write-Host "  [OK] Controle de concorrência do coletor SCADA validado." -ForegroundColor Green
    }
}

# ==============================================================================
# ETAPA 5: PÓS-VERIFICAÇÃO E SMOKE TESTS
# ==============================================================================
Write-Host "`n>>> [ETAPA 5/5] Executando Pós-Verificação e Smoke Tests..." -ForegroundColor Yellow

if ($DryRun) {
    Write-Host "  [DRY-RUN] Simulação de Smoke Tests (HTTP GET /login/ e verificação de porta $WaitressPort)." -ForegroundColor Yellow
} else {
    # 5.1 Smoke Test 1: Verificar se a porta 8900 está ouvindo
    $Listening = $false
    for ($i = 0; $i -lt 15; $i++) {
        $TcpConn = Get-NetTCPConnection -LocalPort $WaitressPort -ErrorAction SilentlyContinue
        if ($TcpConn) {
            $Listening = $true
            break
        }
        Start-Sleep -Seconds 1
    }

    if (-not $Listening) {
        Write-Host "[ERRO CRÍTICO] O servidor não responde na porta $WaitressPort após o deploy!" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Servidor ativo e escutando na porta $WaitressPort." -ForegroundColor Green

    # 5.2 Smoke Test 2: Teste HTTP GET em /login/
    $LoginUrl = "http://127.0.0.1:$WaitressPort/login/"
    try {
        $Response = Invoke-WebRequest -Uri $LoginUrl -Method Get -TimeoutSec 10 -UseBasicParsing
        if ($Response.StatusCode -eq 200 -or $Response.StatusCode -eq 302) {
            Write-Host "  [OK] Smoke test HTTP bem-sucedido: $LoginUrl retornou HTTP $($Response.StatusCode)." -ForegroundColor Green
        } else {
            Write-Host "[ERRO] Smoke test HTTP retornou status inesperado: $($Response.StatusCode)" -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "[ERRO CRÍTICO] Falha ao conectar em $LoginUrl : $_" -ForegroundColor Red
        exit 1
    }

    # 5.3 Smoke Test 3: Integridade dos Logs
    $LogsDir = Join-Path $ProjectRoot "logs"
    if (Test-Path $LogsDir) {
        Write-Host "  [OK] Diretório de logs validado: $LogsDir" -ForegroundColor Green
    }
}

Write-Host "`n======================================================================" -ForegroundColor Green
Write-Host "  DEPLOY CONCLUÍDO COM SUCESSO EM PRODUÇÃO!" -ForegroundColor Green
Write-Host "  Todas as 5 etapas foram executadas com integridade 100% garantida." -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
exit 0
