# 🧠 SPEC 05D — HISTÓRICO DE MATRIZES E LINHA DO TEMPO OPERACIONAL

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/` (Dashboard Geral de Produção), `/producao/maquinas/<id>/` (Detalhe da Máquina e Histórico de Operação).
- **Contexto(s):** Dashboard de Gestão de Produção e Telemetria de Prensa/Cavidades em tempo real conectada ao Scada-LTS.
- **Perfil(s) afetados:** Liderança de Produção, Administrador / Superusuário.

---

## ❗ 2. PROBLEMA ATUAL

1. O card da prensa no dashboard geral exibia um total agregado de produção e meta (ex: `Total: 0 / 1200 (0%)`), o que é conceitualmente incorreto porque a produção e a meta são individuais por cavidade (relacionadas à vida útil do bladder de cada cavidade) e não representam a produção consolidada da prensa.
2. Não existia rastreabilidade nem histórico local de trocas de matrizes instaladas nas cavidades ao longo do tempo.
3. Não havia um resumo consolidado das matrizes ativas na planta nem consulta histórica de matrizes por período.
4. A tela de detalhe da máquina possuía apenas o histórico de paradas (`ProductionDowntimeEvent`), sem uma visualização temporal contínua (linha do tempo) integrada dos ciclos **Produzindo**, **Parada** e **Sem comunicação**.

---

## 🎯 3. OBJETIVO

1. Remover o total agregado de produção/meta do card da prensa no dashboard geral, preservando integralmente todas as métricas, metas manuais e barras de progresso individuais de cada cavidade.
2. Criar o modelo local gerenciado `ProductionCavityMatrixHistory` para rastrear o histórico de utilização de matrizes por cavidade utilizando a hora do sistema Django (`timezone.now()`).
3. Exibir o card **Matrizes em Uso** em `/producao/` com resumo agrupado por matriz e histórico filtrável por período.
4. Criar o modelo local gerenciado `ProductionMachineStateInterval` para registrar os intervalos contínuos de operação da prensa (Produzindo, Parada, Sem comunicação).
5. Implementar a **Linha do Tempo Operacional** e KPIs de eficiência industrial na tela individual da máquina (`/producao/maquinas/<id>/`).
6. Atualizar o ciclo do coletor `collect_production_scada` para processar e atualizar todos os modelos de forma atômica e idempotente.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a criar/alterar:
- `production/models.py`: Criação de `ProductionCavityMatrixHistory` e `ProductionMachineStateInterval`.
- `production/routers.py`: Adição dos dois novos modelos em `ScadaRouter.LOCAL_MANAGED_MODELS`.
- `production/admin.py`: Registro dos novos modelos no Django Admin.
- `production/services.py`:
  - Lógica de normalização de matrizes e transição de histórico de matriz por cavidade.
  - Lógica de transição de intervalos de estado da prensa.
  - Agrupamento de resumo atual de matrizes e consulta de histórico filtrado.
  - Lógica da linha do tempo e calculadoras de KPIs do período na view de detalhe.
- `production/templates/production/dashboard.html`:
  - Remoção do total agregado no cabeçalho de cavidades.
  - Inclusão do card "Matrizes em Uso" (Resumo Atual + Histórico Filtrável).
- `production/templates/production/machine_detail.html`:
  - Exibição da Linha do Tempo Operacional (gráfico horizontal colorido).
  - Exibição dos KPIs complementares (tempo produzindo, tempo parado, tempo sem comunicação, % produzindo, % parado, quantidade de ciclos, quantidade de paradas).
- `production/migrations/0007_historico_matrizes_linha_tempo.py`: Migração aditiva sequencial.
- `production/tests.py`: Adição dos testes unitários obrigatórios da SPEC 05D.
- `Instrucoes.txt`, `implementation_plan.md`, `walkthrough.md`: Documentação.

---

## 🚫 5. FORA DE ESCOPO

- Não alterar tabelas do Scada-LTS (manter `managed=False` em modelos Scada).
- Não realizar escritas no banco `scada`.
- Não alterar migrações anteriores (0001 a 0006).
- Não criar novos serviços, threads, coletores ou tarefas de background paralelas.
- Não iniciar a SPEC 06.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Seguir rigorosamente o `constitution.md`.
- Manter 100% de compatibilidade entre SQLite (desenvolvimento/testes) e MySQL (produção).
- Garantir idoneidade, idempotência e atomidade (`transaction.atomic`).
- Utilizar exclusivamente a data/hora do sistema Django (`timezone.now()`) para registros históricos de matrizes e intervalos operacionais.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

### 1. Remoção do Total Agregado
- O total somado de produção/meta no cabeçalho das cavidades no card da prensa em `/producao/` é removido.
- Todas as informações por cavidade permanecem intactas (produção, meta manual, percentual, barra de progresso, matriz, produto/lote, estado, motivo).

### 2. Histórico de Matrizes (`ProductionCavityMatrixHistory`)
- Normalização de valor: `"12"`, `12`, `12.0`, `" 12 "` são interpretados como a mesma matriz (`"12"`).
- O primeiro ciclo em que uma matriz válida for identificada abre um registro (`started_at = timezone.now()`, `ended_at = None`).
- Enquanto o valor normalizado não mudar, nenhum novo registro é criado nem atualizações repetidas são feitas.
- Quando o valor mudar para outra matriz válida: o registro anterior é fechado com `ended_at = timezone.now()`, e um novo é aberto com `started_at = timezone.now()`.
- Se o Scada ficar offline, stale, der timeout ou retornar valor nulo/inválido: o registro atual PERMANECE ABERTO sem alteração.
- Idempotência: máximo 1 registro aberto por cavidade. Operações envelopadas em `transaction.atomic()`.

### 3. Card Geral de Matrizes em `/producao/`
- **Resumo Atual:** Agrupa cavidades ativas por valor de matriz. Exibe quantidade de cavidades Normais (motivo = 0), Paradas (motivo != 0) e Indeterminadas. Cavidades sem matriz válida aparecem agrupadas como "Matriz não informada".
- **Histórico Filtrável:** Permite filtrar por data inicial, data final e períodos predefinidos (Hoje, 7 dias, 30 dias). Registros abertos usam `timezone.now()` apenas para cálculo de duração visual. Ordenação: abertos primeiro, seguidos por `started_at` decrescente.

### 4. Histórico de Estados da Prensa (`ProductionMachineStateInterval`)
- Decisão do Arquiteto: Estados possíveis do intervalo são `PRODUZINDO`, `PARADA` e `SEM_COMUNICACAO`. Dados desatualizados (stale) ou Scada offline são classificados como `SEM_COMUNICACAO`.
- Transições de estado fecham o intervalo anterior e abrem um novo no mesmo instante (`timezone.now()`).
- `SEM_COMUNICACAO` nunca é contabilizado como produção nem como parada industrial.
- Idempotência: máximo 1 intervalo aberto por máquina.
- Os eventos existentes de `ProductionDowntimeEvent` são preservados sem alteração nem exclusão.

### 5. Linha do Tempo e KPIs na Tela da Máquina
- Segmentos horizontais coloridos: Produzindo (Verde), Parada (Vermelho), Sem comunicação (Cinza).
- Tooltips exibem estado, início, fim e duração.
- Segmentos que atravessam os limites do filtro são recortados: `effective_start = max(started_at, filter_start)`, `effective_end = min(ended_at, filter_end)`.
- KPIs industriais do período:
  - Tempo produzindo, tempo parado, tempo sem comunicação.
  - % produzindo = `tempo_produzindo / (tempo_produzindo + tempo_parado) * 100` (tratar divisão por zero).
  - % parado = `tempo_parado / (tempo_produzindo + tempo_parado) * 100`.
  - Quantidade de ciclos de produção e quantidade de paradas.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Card da prensa não exibe total agregado.
- [ ] Model `ProductionCavityMatrixHistory` criado, roteado no `ScadaRouter` e registrado no Admin.
- [ ] Model `ProductionMachineStateInterval` criado, roteado no `ScadaRouter` e registrado no Admin.
- [ ] Troca de matriz fecha o registro antigo e abre o novo atomicamente com `timezone.now()`.
- [ ] Scada offline ou dado stale não fecha nem duplica registros de matriz.
- [ ] Card "Matrizes em Uso" no dashboard exibindo resumo atual agrupado e histórico filtrável por período.
- [ ] Linha do Tempo Operacional exibindo segmentos coloridos e recortados pelo filtro na tela de detalhe da máquina.
- [ ] KPIs de eficiência industrial calculados corretamente sem divisão por zero e excluindo sem comunicação do denominador.
- [ ] Migration `0007_historico_matrizes_linha_tempo` criada e aplicada no banco default.
- [ ] Suíte de testes 100% verde com inclusão de todos os casos de teste da SPEC 05D.

---

## ⚠️ 9. RISCOS

- **Divisão por zero em KPIs:** Tratar cenários em que tempo_produzindo + tempo_parado = 0.
- **Inconsistência de fusos horários:** Utilizar estritamente `timezone.now()` e respeitar a configuração de timezone do Django.
- **Consultas N+1 no histórico:** Utilizar `select_related` nas consultas de histórico de matrizes e intervalos operacionais.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Criar este documento de SPEC 05D em `regras_programacao/`.
2. Atualizar `production/models.py` com `ProductionCavityMatrixHistory` e `ProductionMachineStateInterval`.
3. Atualizar `production/routers.py` adicionando os dois novos modelos em `LOCAL_MANAGED_MODELS`.
4. Atualizar `production/admin.py`.
5. Gerar a migração `0007_historico_matrizes_linha_tempo`.
6. Atualizar `production/services.py`:
   - Método auxiliar de normalização de matrizes.
   - Atualização de `process_scada_cycle` para gerenciar transições de matrizes e intervalos de estado.
   - Métodos para consulta de resumo de matrizes, histórico de matrizes e linha do tempo com KPIs.
7. Atualizar templates `dashboard.html` e `machine_detail.html`.
8. Adicionar os testes unitários completos em `production/tests.py`.
9. Executar verificações de QA, migrations e testes.
10. Atualizar documentação e criar o commit final.

---

## 🧪 11. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

### Arquivos lidos:
- `constitution.md`, `SPEC_TEMPLATE.md`, `implementation_plan.md`, `SPEC_PRODUCAO_05C_MOTIVOS_PARADA_CAVIDADES.md`, `production/models.py`, `production/routers.py`, `production/admin.py`, `production/services.py`, `production/views.py`, `production/urls.py`, `production/tests.py`, `dashboard.html`, `machine_detail.html`, `collect_production_scada.py`, `Instrucoes.txt`.

### Arquivos criados e alterados:
- `regras_programacao/SPEC_PRODUCAO_05D_HISTORICO_MATRIZES_LINHA_TEMPO.md` [NOVO]
- `production/models.py`
- `production/routers.py`
- `production/admin.py`
- `production/services.py`
- `production/templates/production/dashboard.html`
- `production/templates/production/machine_detail.html`
- `production/migrations/0007_historico_matrizes_linha_tempo.py` [NOVO]
- `production/tests.py`
- `Instrucoes.txt`, `implementation_plan.md`, `walkthrough.md`
