# 🧠 SPEC 06 — HARDENING, SERVIÇO WINDOWS, DEPLOY E ROLLBACK

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<id>/`, `/management/`, `/dashboard/`
- **Contexto(s):** Módulo de Produção — Preparação final de infraestrutura, serviço de coleta Scada em segundo plano, endurecimento de segurança (hardening), scripts de automação/preflight, rotação de logs, backup e roteiro de deploy/rollback no Windows Server 2019.
- **Perfil(s) afetados:** Administradores, DevOps / Infraestrutura, Liderança de Produção.
- **Predecessoras:** SPEC 02 (Auditoria), SPEC 03/03A (Cadastros locais e Hardening do Router), SPEC 04 (Integração Scada e Painel), SPEC 05 (Coletor, Histórico e Detalhe das Máquinas).

---

## ❗ 2. PROBLEMA ATUAL

- O coletor background `collect_production_scada` necessita de automação como Serviço do Windows Server (isolado do Waitress WSGI).
- Faltam variáveis de ambiente explícitas para timeout de conexão do Scada (`SCADA_DB_CONNECT_TIMEOUT`) e caminho configurável de logs do coletor (`SCADA_COLLECTOR_LOG_FILE`).
- Faltam scripts de automação PowerShell para inicialização limpa do coletor (`scripts/start_scada_collector.ps1`) e preflight de auditoria somente leitura em produção (`scripts/preflight_production_scada.ps1`).
- Faltam instruções explícitas de SQL para criação do usuário MySQL do Scada com permissões exclusivas de `SELECT` (somente leitura), sem permissões administrativas.
- O manual `DEPLOY_WINDOWS_SERVER.md` precisa ser atualizado com as orientações do serviço Windows do coletor, rotação de logs, backup e plano de rollback minucioso.

---

## 🎯 3. OBJETIVO

1. **Hardening de Configuração e Credenciais:**
   - Garantir que `maintenance_project/settings.py` utilize variáveis de ambiente com defaults seguros e sem exposição de senhas.
   - Adicionar suporte a `SCADA_DB_CONNECT_TIMEOUT` no `settings.py`.
   - Atualizar `.env.example` com valores ilustrativos/fictícios para o alias `scada`.
   - Documentar os comandos SQL para criação de usuário MySQL com permissão estrita `SELECT`.
2. **Serviço Windows do Coletor:**
   - Criar `scripts/start_scada_collector.ps1` para executar o coletor atrelado exclusivamente à `.venv` com Python 3.11, sem abrir Waitress nem criar novo venv.
   - Documentar a instalação e gerenciamento do serviço via NSSM e Agendador de Tarefas do Windows.
3. **Logging e Rotação de Logs:**
   - Configurar o logging do coletor com `RotatingFileHandler` (UTF-8, nível INFO em produção, stacktrace restrito a falhas técnicas, sem segredos).
   - Permitir configuração via `SCADA_COLLECTOR_LOG_FILE`.
4. **Preflight e Deploy Seguro:**
   - Criar `scripts/preflight_production_scada.ps1` para auditoria 100% somente leitura antes do deploy (Python 3.11, .venv, git status, env vars, conectividade DB default e Scada SELECT, porta Waitress, backup, etc.).
   - Atualizar `DEPLOY_WINDOWS_SERVER.md` cobrindo pré-requisitos, backup preventivo, migrações no default, collectstatic, serviços e rollback.
5. **Testes Automatizados:**
   - Expandir a suíte de testes em `production/tests.py` para validar a ausência de credenciais, logging seguro, execução `--once`, lock cross-process, falha de conexão sem crash, scripts presentes e ausência de inicialização web do coletor.
   - Garantir que a suíte global passe 100% (67+ testes).

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a alterar/criar:
- `maintenance_project/settings.py`: Suporte a `SCADA_DB_CONNECT_TIMEOUT`, diretório/arquivo de logs configurável.
- `production/management/commands/collect_production_scada.py`: Ajustes de logs com registrador dedicado, mensagem clara em falhas de conexão, release do lock e resiliência.
- `.env.example`: Incluir comentários e variáveis ilustrativas do Scada e coletor.
- `scripts/start_scada_collector.ps1` [NOVO]: Script PowerShell para iniciar o coletor no servidor Windows.
- `scripts/preflight_production_scada.ps1` [NOVO]: Script PowerShell de preflight (somente leitura) para produção.
- `DEPLOY_WINDOWS_SERVER.md`: Atualizar manual de implantação, usuário MySQL read-only, serviço NSSM, backup e rollback.
- `production/tests.py`: Adicionar testes unitários para a infraestrutura da SPEC 06.
- `Instrucoes.txt`: Registrar as etapas concluídas da SPEC 06.

---

## 🚫 5. FORA DE ESCOPO

- NÃO executar `migrate --database=scada` nem alterar o esquema do Scada-LTS.
- NÃO conectar nem alterar o servidor de produção na Fase A (a Fase A é estritamente local e de preparação).
- NÃO fazer merge automático na branch `main` ou push sem autorização.
- NÃO criar novos modelos ou alterar regras visuais das SPECs 04 e 05.
- NÃO alterar a porta do Waitress (`8900`) nem do microserviço de WhatsApp (`3000`).

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ Não criar múltiplos ambientes virtuais (`.venv2`, etc) ou duplicar o projeto.
- ✅ Usar estritamente o Python 3.11 da `.venv` existente.
- ✅ Manter a porta 8900 dedicada ao Waitress da Manutenção sem interferir no SST ou Scada.
- ✅ Usuário do Scada MySQL deve possuir APENAS a permissão `SELECT`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO E DEPLOY

1. **Preflight Somente Leitura:**
   - O script `preflight_production_scada.ps1` JAMAIS deve executar escritas, migrações, `git pull`, `collectstatic` ou criar usuários.
2. **Serviço Windows do Coletor:**
   - Deve rodar em segundo plano de forma independente do processo WSGI (Waitress).
   - Deve respeitar o lock de arquivo `scada_collector.lock` para prevenir múltiplas instâncias.
3. **Isolamento de Credenciais:**
   - Nenhuma senha real deve ser commitada no Git ou exibida em logs/telas de erro.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO (FASE A)

- [ ] `regras_programacao/SPEC_PRODUCAO_06_HARDENING_DEPLOY_ROLLBACK.md` criado seguindo o `SPEC_TEMPLATE.md`.
- [ ] `maintenance_project/settings.py` e `.env.example` atualizados com variáveis do Scada sem credenciais hardcoded.
- [ ] Documentação SQL do usuário MySQL somente leitura criada em `DEPLOY_WINDOWS_SERVER.md`.
- [ ] `collect_production_scada.py` auditado, com logs estruturados e encerramento limpo com liberação de lock.
- [ ] `scripts/start_scada_collector.ps1` criado para execução no Windows com `.venv` local e Python 3.11.
- [ ] `scripts/preflight_production_scada.ps1` criado para auditoria 100% somente leitura.
- [ ] `DEPLOY_WINDOWS_SERVER.md` atualizado com o guia de implantação, backup, serviço NSSM e plano de rollback.
- [ ] Suíte de testes automatizados executada e aprovada 100% (mínimo 67 testes globais mantidos/expandidos).
- [ ] Commit único criado na branch `feature/producao-scada`: `chore(production): prepara serviço e deploy seguro do Scada`.
- [ ] Apresentar os 15 itens do Gate Humano da Fase A e aguardar autorização antes da Fase B.

---

## ⚠️ 9. RISCOS E MITIGAÇÃO

- **Concorrência de Coleta:** Protegida pelo lock cross-process `scada_collector.lock`.
- **Falha de Conexão com Scada:** Coletor e Views capturam exceções e marcam `sem_comunicacao=True` sem travar a aplicação web ou quebrar o sistema de Manutenção.
- **Rollback em Produção:** Procedimento de restauração de código e banco documentado em `DEPLOY_WINDOWS_SERVER.md`.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (FASE A)

1. **Arquiteto:** Mapear arquivos de configuração, scripts PowerShell, logging e roteiro de deploy/rollback.
2. **Backend/Infraestrutura:**
   - Atualizar `maintenance_project/settings.py` e `.env.example`.
   - Ajustar `collect_production_scada.py` com suporte a logging aprimorado.
   - Criar `scripts/start_scada_collector.ps1`.
   - Criar `scripts/preflight_production_scada.ps1`.
   - Atualizar `DEPLOY_WINDOWS_SERVER.md`.
   - Adicionar testes de infraestrutura e hardening em `production/tests.py`.
3. **QA:**
   - Executar suíte de testes globais e verificações do Django check / makemigrations / migrate plan.
   - Executar análise sintática dos scripts PowerShell sem alterar o servidor.
   - Atualizar `Instrucoes.txt`.
   - Criar o commit da Fase A.
   - Apresentar o relatório dos 15 pontos e aguardar o Gate Humano.

---

## 🤖 REGISTRO DOS SUBAGENTES

### 1. Arquiteto
- Mapeou e estruturou os requisitos de hardening, logging, serviços Windows, preflight e rollback.

### 2. Backend/Infraestrutura
- Implementou ajustes de settings, scripts PowerShell de inicialização e preflight, documentação de deploy/rollback e bateria de testes.

### 3. QA
- Validou testes unitários (67+), integridade de migrações, scripts PowerShell e gerou o relatório do Gate Humano da Fase A.
