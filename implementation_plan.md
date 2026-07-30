# 🧠 Implementation Plan — Consolidação e Reorganização Documental das SPECs (04, 05 e 06)

## 🎯 Objetivo
Registrar o planejamento consolidado e a reorganização documental das etapas restantes do módulo de Produção / Scada-LTS, reduzindo as antigas cinco SPECs (04 a 08) para três SPECs consolidadas e autuficientes (SPEC 04, SPEC 05 e SPEC 06), garantindo segurança de dados, clareza arquitetural, isolamento de bancos e capacidade de rollback sem implementar nenhum código nesta execução.

---

## 📋 Mapeamento de Transição (SPECs Antigas → SPECs Consolidadas)

| Antiga SPEC | Conteúdo / Foco Original | Nova SPEC Consolidada | Escopo Consolidado |
| :--- | :--- | :--- | :--- |
| **SPEC 04** | Leitura somente leitura do Scada (Models `managed=False` + Services) | **SPEC 04** | **INTEGRAÇÃO SCADA-LTS E VISÃO ATUAL DO PAINEL DE PRODUÇÃO**<br>Consolida a camada de leitura Scada + Dashboard visual `/producao/`. |
| **SPEC 05** | Visão atual em `/producao/` (Dashboard, Filtros e Alarmes) | **SPEC 04** | Incorporada inteiramente à SPEC 04. |
| **SPEC 06** | Coletor background e histórico de paradas no banco `default` | **SPEC 05** | **COLETOR, HISTÓRICO E DETALHE DAS MÁQUINAS**<br>Consolida o coletor idempotente + modelos locais + tela de detalhes e KPIs. |
| **SPEC 07** | Detalhe da máquina `/producao/maquinas/<id>/` e filtros por data | **SPEC 05** | Incorporada inteiramente à SPEC 05. |
| **SPEC 08** | Hardening, Serviço Windows, Deploy e Rollback | **SPEC 06** | **HARDENING, SERVIÇO WINDOWS, DEPLOY E ROLLBACK**<br>Substitui a antiga SPEC 08 com foco em produção. |

---

## 📌 Novo Índice Sequencial Obrigatório

### 1. SPECs Concluídas e Aprovadas (Imutáveis)
- **SPEC 02:** Auditoria de Estado Atual e Fundamentos do Módulo de Produção *(Aprovada em 2026-07-29)*.
- **SPEC 03:** Cadastro Local de XIDs, Cavidades, Parâmetros e Alarmes no Admin *(Reprovada na auditoria / Substituída)*.
- **SPEC 03A:** Correção do Router, Testes e Integridade de Configuração *(Concluída, auditada e aprovada em 2026-07-30)*.
- **SPEC 04:** Integração Scada-LTS e Visão Atual do Painel de Produção *(Concluída, auditada e aprovada em 2026-07-30)*.
- **SPEC 05:** Coletor, Histórico e Detalhe das Máquinas *(Concluída, auditada e aprovada em 2026-07-30)*.

### 2. Novas SPECs Consolidadas Restantes
- **SPEC 06:** Hardening, Serviço Windows, Deploy e Rollback.


---

## 📐 Detalhamento Completo das Novas SPECs

---

### 🟢 SPEC 04 — INTEGRAÇÃO SCADA-LTS E VISÃO ATUAL DO PAINEL DE PRODUÇÃO

**Objetivo:** Implementar os modelos não gerenciados de leitura do Scada-LTS, o serviço de consulta em lote com normalização e cache, e a interface web do Painel de Produção (`/producao/`) exibindo a situação atualizada das máquinas, cavidades, parâmetros e alarmes globais.

#### Escopo Incluído:
- Models Django não gerenciados (`managed=False`) para as tabelas do Scada-LTS: `datapoints`, `pointvalues` e `pointvalueannotations`.
- Leitura de dados executada exclusivamente através do alias `scada` no ORM.
- Resolução e cache de mapeamento `XID → dataPointId`.
- Leitura otimizada em lote (single query por subquery `MAX(ts)`) dos últimos valores.
- Cache em memória com TTL curto para valores e TTL longo para XIDs.
- Normalização robusta de tipos (`dataType` 1=Binary, 2=Multistate, 3=Numeric, 4=String).
- Identificação visual e lógica de dados desatualizados (comparação com `stale_limit_seconds`).
- Resiliência operacional e fallback amigável quando a conexão com o Scada estiver offline.
- Serviço agregador (`ProductionStateService`) responsável por montar o estado atual de todas as máquinas cadastradas.
- View e Template do Dashboard Principal `/producao/`.
- Busca dinâmica por nome da máquina.
- Filtros rápidos por estado: `Todas`, `Produzindo`, `Paradas` e `Sem Comunicação`.
- Exibição das cavidades, produção atual, meta de produção e motivos de parada.
- Exibição dos parâmetros globais (pressão de vácuo, vapor lado 1-7, vapor lado 8-12, ar pneumático).
- Exibição dos alarmes globais (ar, vapor, vácuo).
- Timestamp e indicador visual da última atualização.

#### Fora do Escopo da SPEC 04:
- Gravação de histórico de paradas no banco local.
- Coletor persistente em segundo plano.
- Cronômetro salvo no banco `default`.
- Models locais de estado ou histórico (`ProductionMachineState`, `ProductionDowntimeEvent`).
- Deploy ou alterações no servidor de produção.

#### Fases Internas da SPEC 04:
- **Fase 4.1:** Models Scada não gerenciados e Repositórios/Services de leitura em lote + testes com mocks.
- **Fase 4.2:** Controller/View `/producao/`, filtros de busca, cards das máquinas, parâmetros e alarmes globais.

---

### 🟡 SPEC 05 — COLETOR, HISTÓRICO E DETALHE DAS MÁQUINAS

**Objetivo:** Criar a estrutura de persistência de eventos de parada no banco `default`, o serviço de coleta idempotente em background e a tela detalhada de cada máquina (`/producao/maquinas/<id>/`) com filtros de período e KPIs de parada.

#### Escopo Incluído:
- Criação do model `ProductionMachineState` (1:1 com `ProductionMachineConfig`) no banco `default` para persistir a última transição e o estado ativo.
- Criação do model `ProductionDowntimeEvent` no banco `default` para registrar cada período de parada (início, fim, duração em segundos, motivo geral e por cavidade, snapshots de produção).
- **ATUALIZAÇÃO OBRIGATÓRIA DE `ScadaRouter.LOCAL_MANAGED_MODELS`:** Incluir explicitamente `"productionmachinestate"` e `"productiondowntimeevent"` na constante do router em `production/routers.py`.
- Migrations puramente aditivas e reversíveis geradas exclusivamente no banco `default`.
- Management command `python manage.py collect_production_scada`.
- Garantia de instância única via lock cross-process (`scada_collector.lock`).
- Idempotência na coleta: evitar duplicar eventos de parada em caso de retries ou reinícios.
- Persistência imediata das transições de estado (`Produzindo → Parada` e `Parada → Produzindo`).
- Recuperação automática de estado após reinício do processo do coletor.
- Cronômetro de tempo parado derivado do timestamp persistido no banco `default`.
- View e Template do Detalhe da Máquina `/producao/maquinas/<id>/`.
- Filtros por intervalo de datas (`data_inicio` e `data_final`).
- Tabela cronológica de paradas da máquina (início, fim, duração formatada e motivo).
- KPIs resumidos do período: tempo total parado, quantidade de paradas, maior parada e média de parada.
- Exibição detalhada por cavidade e motivos associados.

#### Fora do Escopo da SPEC 05:
- Configuração de serviços de sistema no Windows Server (NSSM/Task Scheduler).
- Deploy ou publicação no servidor.
- Alteração ou gravação de qualquer dado no banco MySQL Scada-LTS.
- Gráficos avançados não solicitados.

#### Fases Internas da SPEC 05:
- **Fase 5.1:** Modelos `ProductionMachineState` e `ProductionDowntimeEvent`, inclusão no `LOCAL_MANAGED_MODELS`, migration aditiva no `default` e suíte de testes unitários dos modelos.
- **Fase 5.2:** Management Command `collect_production_scada`, lock de processo, máquina de estados de transição e recuperação pós-crash.
- **Fase 5.3:** View `/producao/maquinas/<id>/`, filtros por data, tabela de histórico de paradas e cálculo de KPIs.

---

### 🔵 SPEC 06 — HARDENING, SERVIÇO WINDOWS, DEPLOY E ROLLBACK

**Objetivo:** Executar o endurecimento de segurança, configurar o serviço Windows do coletor em produção, realizar o deploy incremental com backup e disponibilizar o plano operacional de rollback e validação.

#### Escopo Incluído:
- Validação e imposição de credencial MySQL do Scada com privilégios exclusivos de `SELECT` (somente leitura).
- Auditoria e congelamento das variáveis de ambiente (`.env`) em produção.
- Configuração do coletor como Serviço do Windows Server (via NSSM ou utilitário equivalente).
- Configuração de auto-inicialização e política de reinicialização automática do serviço em caso de falha.
- Logging centralizado e rotação de logs para o coletor.
- Procedimentos automatizados/orientados de backup preventivo do `db.sqlite3` de produção.
- Checklist de deploy incremental e migração controlada no banco `default`.
- Bateria de Smoke Tests em ambiente real de produção.
- Plano de Rollback passo a passo (restauração de banco e reversão de código).
- Validação de aceitação final de produção.
- Documentação operacional em `DEPLOY_WINDOWS_SERVER.md` e `Instrucoes.txt`.

#### Fora do Escopo da SPEC 06:
- Novas funcionalidades visuais ou alterações de modelos.
- Qualquer alteração estrutural no banco Scada-LTS.

#### Fases Internas da SPEC 06:
- **Fase 6.1:** Hardening de credenciais, permissões do banco e variáveis de ambiente.
- **Fase 6.2:** Criação dos scripts de serviço do Windows, logging e rotina de backup.
- **Fase 6.3:** Roteiro de deploy incremental, smoke tests e runbook de rollback.

---

## 🔒 Regras de Governança da Consolidação

1. **Formato Padrão:** Cada SPEC consolidada utilizará obrigatoriamente o formato estruturado do `regras_programacao/SPEC_TEMPLATE.md`.
2. **Critérios de Aceitação Verificáveis:** Cada SPEC conterá uma checklist explícita de testes e validações automatizadas e manuais.
3. **Fases Internas Sem Bloqueio Humano Intermediário:** Cada SPEC é dividida em fases internas lógicas para organização, executadas sequencialmente sem a necessidade de paradas para aprovação humana entre as subfases de uma mesma SPEC.
4. **Resolução Interna de Correções:** Correções e ajustes encontrados durante o desenvolvimento de uma SPEC deverão ser corrigidos dentro da própria SPEC, desde que pertençam ao escopo aprovado e não tragam risco aos dados.
5. **Critérios para SPEC Corretiva Separada:** Uma SPEC corretiva individual só será aberta se ocorrer:
   - Risco de perda ou corrupção de dados;
   - Mudança estrutural fora do escopo aprovado;
   - Vulnerabilidade de segurança;
   - Necessidade de alterar ou reescrever migrações já aplicadas no banco.
6. **Portais de Aprovação Humana:** A aprovação humana explícita do usuário é exigida SOMENTE:
   - **Antes do início** de cada uma das três SPECs consolidadas (04, 05 e 06);
   - Diante de qualquer bloqueio crítico imprevisto;
   - **Antes do deploy** em produção.
7. **Isolamento de Conversas:** Cada SPEC consolidada deverá ser executada em um chat/sessão do Codex novo e dedicado.
8. **Não-Início Automático:** É terminantemente proibido iniciar a SPEC seguinte sem autorização prévia e explícita do usuário.

---

## 🛡️ Regras Arquiteturais e Proteção dos Bancos de Dados

1. **`ScadaRouter.LOCAL_MANAGED_MODELS` (OBRIGATÓRIO NA SPEC 05):**
   - Atualmente contém: `productionmachineconfig`, `productioncavityconfig`, `productionglobalparameter`, `productionglobalalarm`.
   - **Regra de Ouro:** Ao criar `ProductionMachineState` e `ProductionDowntimeEvent` na SPEC 05, seus nomes em minúsculas (`productionmachinestate` e `productiondowntimeevent`) DEVERÃO ser obrigatoriamente adicionados à constante `LOCAL_MANAGED_MODELS` em `production/routers.py`. Sem isso, o router bloqueará categoricamente a gravação desses modelos no banco `default`.
2. **Isolamento Absoluto do Banco Scada:**
   - O alias `scada` é estritamente somente leitura.
   - Qualquer operação de escrita (`create`, `update`, `delete`, `save`) em modelos não gerenciados dispara `PermissionError`.
   - `allow_migrate` no alias `scada` retorna categoricamente `False`.
   - O comando `python manage.py migrate --database=scada` JAMAIS deve ser executado.
3. **Compatibilidade de Migrações:**
   - Toda migration gerada no banco `default` deve ser aditiva e reversível.

---

## 📝 Declaração Obrigatória de Execução

1. **Código Implementado:** NENHUM código Python/Django foi implementado ou modificado nesta etapa de planejamento.
2. **Status da SPEC 04:** A SPEC 04 NÃO foi iniciada e aguarda a autorização do usuário.
3. **Acesso ao Banco Scada:** O banco Scada NÃO foi acessado nesta etapa.
4. **Migrations:** Nenhuma migration foi criada ou executada.
5. **Git Commit / Push:** Nenhum commit ou push foi realizado antes da apresentação e aprovação deste plano.

---
**Status Atual:** Aguardando aprovação humana explícita do usuário para iniciar a SPEC 04.
