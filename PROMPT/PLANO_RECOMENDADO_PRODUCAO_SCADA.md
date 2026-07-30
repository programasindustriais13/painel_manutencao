# Plano recomendado — Módulo de Produção com Scada-LTS

## Objetivo

Evoluir `/producao/` para consultar dados reais do Scada-LTS e manter histórico confiável de paradas, sem copiar o visual de TV, sem escrever no Scada e sem arriscar os dados existentes do projeto de Manutenção.

## Princípio de dados

- **MySQL Scada-LTS:** fonte somente leitura para valores atuais e séries históricas brutas.
- **Banco default do projeto:** cadastros de XIDs/configurações e eventos derivados de parada.
- **Não replicar todas as leituras:** persistir apenas transições e períodos necessários ao relatório de parada.

## Arquitetura sugerida

1. `ProductionMachineConfig` vinculado 1:1 ao `Machine` existente, se a auditoria comprovar compatibilidade.
2. `ProductionCavityConfig` como tabela filha para 2 ou 4 cavidades e edição por inline no Admin.
3. `ProductionGlobalParameter` e `ProductionGlobalAlarm` para os XIDs globais.
4. Models não gerenciados para `datapoints`, `pointvalues` e `pointvalueannotations`, sempre usando `.using("scada")`.
5. Service de leitura em lote com normalização por `dataType`, cache de XID e cache curto de valor.
6. `ProductionMachineState` 1:1 para o último estado válido e a parada ativa.
7. `ProductionDowntimeEvent` para cada período de parada, com início, fim, duração, motivo e snapshots relevantes.
8. Management command exclusivo para coleta, rodando como serviço separado com lock cross-process.

## Sequência segura (Consolidada em 3 SPECs Finais)

### SPEC 02 — Auditoria e caracterização
Sem código. Confirma o que da fundação já existe, bancos, router, Machine, Admin, Waitress, migrations, permissões e riscos. *(Concluída em 2026-07-29)*.

### SPEC 03 / SPEC 03A — Cadastro de XIDs no Admin e Hardening do Router
Models locais e Admin para máquina, cavidades, parâmetros e alarmes. Roteamento determinístico, bloqueio de escrita em modelos não gerenciados e constraints de unicidade. *(Concluída e Aprovada em 2026-07-30)*.

---

### SPEC 04 — Integração Scada-LTS e Visão Atual do Painel de Produção
*(Consolida as antigas SPECs 04 e 05)*

- Models `managed=False` para as tabelas do Scada (`datapoints`, `pointvalues`, `pointvalueannotations`).
- Leitura exclusivamente pelo alias `scada`.
- Resolução de XID → datapoint ID.
- Leitura em lote dos últimos valores.
- Cache de XID (TTL longo) e de valor (TTL curto).
- Normalização de tipos (`dataType` 1=Binary, 2=Multistate, 3=Numeric, 4=String).
- Identificação de dados desatualizados (`stale_limit_seconds`).
- Resiliência operacional quando o Scada estiver offline.
- Serviço agregador de estado atual de todas as máquinas.
- Dashboard `/producao/` com busca por nome, filtros de status (`Todas`, `Produzindo`, `Paradas`, `Sem Comunicação`), cavidades, produção, meta, motivos, parâmetros globais, alarmes globais e última atualização.
- **Fora do escopo:** Gravação de histórico, coletor persistente, cronômetro salvo no banco, models locais de histórico, deploy no servidor.

### SPEC 05 — Coletor, Histórico e Detalhe das Máquinas
*(Consolida as antigas SPECs 06 e 07)*

- Models locais `ProductionMachineState` e `ProductionDowntimeEvent`.
- **ATUALIZAÇÃO OBRIGATÓRIA:** Incluir `"productionmachinestate"` e `"productiondowntimeevent"` em `ScadaRouter.LOCAL_MANAGED_MODELS` para autorizar gravações no banco `default`.
- Migrations aditivas exclusivamente no banco `default`.
- Management command `collect_production_scada` com lock cross-process, idempotência, persistência de transições e recuperação pós-reinício.
- Cronômetro persistido derivado de `inicio_da_parada`.
- Detalhe `/producao/maquinas/<id>/` com filtros por data, tabela cronológica de paradas, KPIs (tempo total parado, quantidade, maior parada e média de parada), motivos e cavidades.
- **Fora do escopo:** Configuração de serviços no Windows Server, deploy, alteração no banco Scada, gráficos avançados não solicitados.

### SPEC 06 — Hardening, Serviço Windows, Deploy e Rollback
*(Substitui a antiga SPEC 08)*

- Imposição de credencial MySQL com permissão exclusiva de `SELECT` (somente leitura).
- Congelamento e auditoria de variáveis de ambiente (`.env`).
- Serviço Windows do coletor com auto-inicialização e política de restart.
- Logging centralizado e rotação de logs.
- Rotina automatizada/guiada de backup do `db.sqlite3`.
- Deploy incremental no servidor Windows Server com Waitress.
- Bateria de smoke tests em produção.
- Runbook completo de rollback.
- Documentação operacional em `DEPLOY_WINDOWS_SERVER.md` e `Instrucoes.txt`.

## UX inicial

- `/producao/`: busca, quatro filtros de status, contadores gerais e cards compactos.
- `/producao/maquinas/<id>/`: estado atual, cavidades, atualização, período, total parado, quantidade, maior e média, tabela cronológica.
- Termos simples, botões grandes, sem telas densas de configuração fora do Admin.

## Controles essenciais

- Usuário MySQL do Scada com `SELECT` apenas.
- `allow_migrate=False` no alias `scada`.
- Feature flag para ligar leitura/coletor somente após QA.
- Nunca interpretar falha de comunicação como parada.
- Backup do banco default antes de migration/deploy.
- Python 3.11 nos testes locais para paridade com o servidor.
