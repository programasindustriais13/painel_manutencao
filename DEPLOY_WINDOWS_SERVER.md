# 📘 Manual de Implantação no Windows Server 2019 — Subdomínio Manutenção e Módulo Produção / Scada

Este manual descreve o procedimento passo a passo e seguro para realizar a implantação, hardening, serviços Windows e rollback do **Painel de Manutenção Industrial** e do **Módulo de Produção / Scada** no Windows Server 2019 sob o subdomínio `manutencao.freedom.dev.br`.

> [!IMPORTANT]
> **ISOLAMENTO TOTAL DO SISTEMA SST E SCADA-LTS:**
> - O sistema SST (`sst.freedom.dev.br`) já se encontra em produção no mesmo servidor. Este procedimento **NÃO PODE** alterar ou impactar o SST.
> - O banco MySQL do Scada-LTS é uma fonte externa de telemetria **SOMENTE LEITURA**. Nenhuma operação de escrita, criação ou alteração de tabela deve ser executada no MySQL do Scada.

---

## 📋 Pré-requisitos do Servidor

- **Sistema Operacional:** Windows Server 2019.
- **Python Oficial:** 3.11.3 (instalado e atrelado à `.venv` na raiz do projeto).
- **Node.js:** v20.x ou superior (para o microserviço de WhatsApp).
- **Cloudflare Tunnel (`cloudflared`):** Operacional no servidor.
- **Portas Isoladas:**
  - `Waitress WSGI (Manutenção/Produção)`: `127.0.0.1:8900`
  - `WhatsApp Microservice`: `127.0.0.1:3000`
  - `Scada-LTS MySQL`: `127.0.0.1:3306`

---

## 🔐 1. Hardening do Usuário MySQL Scada-LTS (Somente Leitura)

O administrador do banco de dados (DBA) do Scada-LTS deve executar no MySQL os seguintes comandos para criar um usuário exclusivo de leitura:

```sql
-- 1. Criar usuário exclusivo (substitua 'SENHA_FORTE_LEITURA_AQUI' por uma senha segura)
CREATE USER 'scada_monitor_ro'@'127.0.0.1' IDENTIFIED BY 'SENHA_FORTE_LEITURA_AQUI';

-- 2. Conceder permissão EXCLUSIVA de SELECT no banco scadalts
GRANT SELECT ON scadalts.* TO 'scada_monitor_ro'@'127.0.0.1';

-- 3. Atualizar privilégios
FLUSH PRIVILEGES;

-- 4. Verificar se a permissão foi concedida corretamente (DEVE conter APENAS 'GRANT SELECT')
SHOW GRANTS FOR 'scada_monitor_ro'@'127.0.0.1';
```

> [!WARNING]
> **REGRAS DE SEGURANÇA:**
> - NÃO conceder permissões `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, `DROP`, `EXECUTE` ou `GRANT OPTION`.
> - NÃO conectar como `root` no alias `scada`.
> - NENHUMA senha real deve ser commitada no repositório Git ou exposta em documentos versionados.

---

## 🛠️ 2. Auditoria e Script de Preflight (Fase A/B)

Antes de qualquer alteração no servidor, execute o script PowerShell de auditoria **somente leitura**:

```powershell
.\scripts\preflight_production_scada.ps1
```

O preflight verifica sem alterar nada no servidor:
- Versão do Python 3.11 no `.venv`.
- Status do Git (branch `feature/producao-scada` / commit atual).
- Presença das variáveis obrigatórias no `.env`.
- Conectividade com o banco default e Scada.
- Status da porta 8900 (Waitress) e Cloudflare Tunnel.
- Existência de backup preventivo.
- Existência ou ausência do serviço do coletor.

---

## 💾 3. Procedimento de Backup Preventivo

Antes de executar migrações ou atualizar o código em produção:

1. **Parar temporariamente o serviço Waitress (se ativo):**
   ```powershell
   nssm stop PainelManutencaoWSGI
   ```

2. **Criar pasta de backup com timestamp:**
   ```powershell
   $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
   $BackupDir = "C:\Backups_Painel_Manutencao\backup_$Timestamp"
   New-Item -ItemType Directory -Path $BackupDir -Force
   ```

3. **Copiar arquivos críticos (banco default, .env, mídia, sessões WhatsApp):**
   ```powershell
   Copy-Item -Path "db.sqlite3" -Destination "$BackupDir\db.sqlite3"
   Copy-Item -Path ".env" -Destination "$BackupDir\.env"
   Copy-Item -Path "media" -Destination "$BackupDir\media" -Recurse
   Copy-Item -Path "whatsapp_service\auth_info_baileys" -Destination "$BackupDir\auth_info_baileys" -Recurse -ErrorAction SilentlyContinue
   ```

4. **Validar a integridade da cópia:**
   Confirmar que os tamanhos dos arquivos conferem antes de prosseguir.

---

## 🔄 4. Atualização de Código e Migrações (Somente no Banco Default)

1. **Obter atualização do Git:**
   ```powershell
   git fetch origin
   git checkout feature/producao-scada
   git pull origin feature/producao-scada
   ```

2. **Instalar dependências no `.venv` existente:**
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. **Verificar integridade do Django:**
   ```powershell
   .\.venv\Scripts\python.exe manage.py check
   ```

4. **Simular plano de migração no banco `default`:**
   ```powershell
   .\.venv\Scripts\python.exe manage.py migrate --plan --database=default
   ```

5. **Aplicar migrações EXCLUSIVAMENTE no banco `default`:**
   ```powershell
   .\.venv\Scripts\python.exe manage.py migrate --database=default
   ```
   > [!CAUTION]
   > NUNCA executar `python manage.py migrate --database=scada`.

6. **Coletar arquivos estáticos:**
   ```powershell
   .\.venv\Scripts\python.exe manage.py collectstatic --noinput
   ```

---

## ⚙️ 5. Configuração dos Serviços do Windows (Waitress e Coletor Scada)

Utilizar o **NSSM (Non-Sucking Service Manager)** para registrar os dois serviços independentes:

### 5.1 Serviço Web WSGI (Waitress)
```powershell
nssm install PainelManutencaoWSGI "C:\Caminho\Do\Projeto\.venv\Scripts\python.exe" "-m waitress --host=127.0.0.1 --port=8900 --threads=4 maintenance_project.wsgi:application"
nssm set PainelManutencaoWSGI AppDirectory "C:\Caminho\Do\Projeto"
nssm set PainelManutencaoWSGI Start SERVICE_AUTO_START
nssm start PainelManutencaoWSGI
```

### 5.2 Serviço do Coletor Scada Background (Intervalo de 60s em Produção)
```powershell
nssm install ScadaCollectorService "C:\Caminho\Do\Projeto\.venv\Scripts\python.exe" "manage.py collect_production_scada --interval 60"
nssm set ScadaCollectorService AppDirectory "C:\Caminho\Do\Projeto"
nssm set ScadaCollectorService Start SERVICE_AUTO_START
nssm set ScadaCollectorService AppExit Default Restart
nssm start ScadaCollectorService
```

> [!NOTE]
> **PARÂMETROS DO COLETOR EM PRODUÇÃO:**
> - O intervalo recomendado e homologado em produção é `--interval 60` (60 segundos por ciclo).
> - NENHUMA requisição web HTTP consulta a tabela `pointvalues` do Scada MySQL. Apenas o coletor background acessa a telemetria do Scada e salva agregados no banco `default`.

### Comandos de Gestão dos Serviços:
- **Verificar status:** `nssm status ScadaCollectorService`
- **Parar serviço:** `nssm stop ScadaCollectorService`
- **Iniciar serviço:** `nssm start ScadaCollectorService`
- **Remover serviço:** `nssm remove ScadaCollectorService confirm`

---

## 📑 6. Logging e Rotação de Logs

O coletor Scada registra seus logs de forma dedicada em UTF-8 fora do Git:
- **Caminho padrão:** `logs/scada_collector.log` (ou configurado em `SCADA_COLLECTOR_LOG_FILE`).
- **Política de Rotação:** `RotatingFileHandler` com 5 MB por arquivo e máximo de 5 arquivos de backup.
- **Nível:** `INFO` em produção.
- **Informações registradas:** Início do serviço, contagem de máquinas processadas por ciclo, falhas de conexão sem credenciais, retorno de comunicação e encerramento limpo.

---

## 🧪 7. Smoke Tests Pós-Deploy

Após a inicialização dos serviços, executar as seguintes verificações em produção:

1. **Acesso à Manutenção:**
   - `http://127.0.0.1:8900/login/` → HTTP 200.
   - `http://127.0.0.1:8900/management/` → HTTP 302/200.
2. **Acesso ao Módulo de Produção:**
   - Login com usuário `Liderança de Produção`.
   - `/producao/` → Carrega cards de máquinas, cavidades, parâmetros e alarmes globais.
   - `/producao/maquinas/<id>/` → Carrega cronômetro persistido e histórico de paradas.
3. **Leitura e Coleta do Scada:**
   - Verificar se as máquinas atualizam seus valores do Scada.
   - Verificar logs em `logs/scada_collector.log`.
   - Garantir que NENHUMA operação de escrita foi tentada no banco `scada`.
4. **Verificação de Concorrência:**
   - Executar `python manage.py collect_production_scada --once` em um terminal paralelo e confirmar a mensagem de bloqueio por segunda instância.

---

## ↺ 8. Plano de Rollback de Emergência

Caso ocorra falha crítica em produção:

1. **Parar o serviço do coletor Scada:**
   ```powershell
   nssm stop ScadaCollectorService
   ```

2. **Parar o serviço do Waitress:**
   ```powershell
   nssm stop PainelManutencaoWSGI
   ```

3. **Reverter o código ao commit anterior estável:**
   ```powershell
   git checkout <HASH_DO_COMMIT_ANTERIOR>
   ```

4. **Restaurar o Banco Default (se necessário):**
   ```powershell
   Copy-Item -Path "$BackupDir\db.sqlite3" -Destination "db.sqlite3" -Force
   ```

5. **Reiniciar o serviço do Waitress:**
   ```powershell
   nssm start PainelManutencaoWSGI
   ```

6. **Validar acesso ao sistema de Manutenção:**
   Confirmar que o painel de manutenção `/management/` funciona normalmente.

7. **Documentar a ocorrência em `Instrucoes.txt`.**
