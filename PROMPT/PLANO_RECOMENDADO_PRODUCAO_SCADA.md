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

## Sequência segura

### SPEC 02 — Auditoria e caracterização

Sem código. Confirma o que da fundação já existe, bancos, router, Machine, Admin, Waitress, migrations, permissões e riscos.

### SPEC 03 — Cadastro de XIDs no Admin

Models locais e Admin para máquina, cavidades, parâmetros e alarmes. Migration apenas aditiva. Sem conexão real obrigatória ainda.

### SPEC 04 — Leitura somente leitura do Scada

Models `managed=False`, serviços de leitura em lote, normalização, cache, comando de diagnóstico e testes com mocks. Nenhuma tela complexa.

### SPEC 05 — Visão atual em `/producao/`

Busca e filtros rápidos, status atual, parâmetros globais, cavidades, produção/meta e indicação de dados desatualizados.

### SPEC 06 — Coletor e histórico de paradas

Processo único, idempotência, transições, estado persistido, eventos de parada e proteção contra falha/stale.
*(Obrigatório: Incluir novos modelos locais gerenciados em `ScadaRouter.LOCAL_MANAGED_MODELS` para autorizar gravações no banco `default`)*.


### SPEC 07 — Detalhe e filtros históricos

Tela por máquina, período, tabela de paradas e KPIs simples. Sem excesso de gráficos.

### SPEC 08 — Hardening e deploy

Carga, falhas de rede, backup, restauração, observabilidade, serviço Windows, rollback e regressões.

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
