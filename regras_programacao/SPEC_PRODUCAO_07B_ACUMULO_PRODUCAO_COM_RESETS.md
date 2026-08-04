# 🧠 SPEC_PRODUCAO_07B — ACÚMULO DE PRODUÇÃO DO TURNO COM SUPORTE A RESETS E CICLOS DE PRODUÇÃO

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `SPEC_PRODUCAO_07A_SEPARACAO_LIMITE_BLADDER_E_META.md`
- **URL(s) envolvidas**:
  - `/producao/` (Dashboard de Produção)
  - `/producao/maquinas/<id>/` (Detalhe da Máquina)
  - `/producao/maquinas/<machine_id>/cavidades/<cavity_id>/` (Detalhe da Cavidade)
- **Contexto(s)**: Coletor Scada em Segundo Plano / Engine de Produção / Máquina de Estados
- **Perfil(s) afetados**: Sistema/Coletor, Líder de Produção, PCP, Operadores

---

## ❗ 2. PROBLEMA ATUAL

Atualmente, o coletor `collect_production_scada` lê o valor numérico instantâneo retornado do Scada pelo XID `xid_producao` de cada cavidade e o exibe diretamente como a produção da cavidade.
Entretanto, no processo fabril real de vulcanização de pneus:
1. Quando ocorre a **troca de bladder** ou a **troca de matriz**, o operador ou o CLP físico zera o contador da cavidade (`xid_producao` vai de ex: 1180 para 0 ou 8).
2. Sem um mecanismo de acúmulo incremental por turno, o dashboard do sistema passa a exibir apenas a produção reduzida (ex: 8), "perdendo" os 1180 pneus produzidos antes da troca durante o mesmo turno.
3. Além disso, releituras do coletor ou tentativas de retry não podem duplicar a contagem de pneus já processados, e travamentos do Scada não podem ser confundidos com resets de produção.

---

## 🎯 3. OBJETIVO

Implementar uma engine de acúmulo incremental de produção em nível de cavidade e turno, com suporte a fechamento e abertura automática de ciclos de produção (`ProductionCycle`) e registros acumulados no turno (`ProductionShiftAccumulated`):
1. **Leitura Normal (Crescente)**:
   - Exemplo: Leitura anterior = 430, Leitura atual = 445 -> Incremento = 15 pneus.
   - Adiciona 15 à produção acumulada do turno da cavidade.
2. **Reset de Contador / Troca de Matriz ou Bladder**:
   - Exemplo: Leitura anterior = 1180, Leitura atual = 8.
   - Detecta evento de reset (seja por `leitura_atual < leitura_anterior`, troca de `xid_matriz` ou troca de `xid_lote_bladder`).
   - Fecha o ciclo de produção anterior (`ProductionCycle` encerrado com motivo, contador final 1180 e quantidade produzida).
   - Preserva a produção acumulada anterior no turno (1180 pneus).
   - Abre um novo ciclo de produção (`ProductionCycle` ativo com contador inicial 8, matriz e lote atuais).
   - Adiciona os 8 pneus novos à produção acumulada do turno (Total do turno passa a ser 1180 + 8 = 1188 pneus).
3. **Impedir Valores Negativos e Duplicações**:
   - Falha de comunicação, timout do Scada ou dado `stale` NÃO gera reset nem altera a produção acumulada.
   - Idempotência baseada no `ultimo_timestamp_scada` e trava de concorrência por `scada_collector.lock` e `select_for_update`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/models.py):
  - Criar `ProductionCycle` (rastreamento do ciclo físico do molde/bladder na cavidade).
  - Criar `ProductionShiftAccumulated` (rastreamento do total acumulado por cavidade no turno corrente).
- [services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py):
  - Implementar lógica de processamento incremental e detecção de reset em `ProductionStateService.process_scada_cycle`.
  - Atualizar `build_cavities_data` para ler a produção acumulada do turno de `ProductionShiftAccumulated` em vez do valor bruto instantâneo.
- [management/commands/collect_production_scada.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/management/commands/collect_production_scada.py):
  - Garantir invocação segura dentro de transações atômicas.
- [migrations](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/migrations/):
  - Nova migration `0013_productioncycle_productionshiftaccumulated.py`.

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO fazer consultas pesadas agrupando a tabela `pointvalues` do Scada em cada requisição web HTTP. A view lê exclusivamente do banco default local (`ProductionShiftAccumulated`).
- ❌ NÃO alterar tabelas do banco Scada-LTS (mantido 100% somente leitura).
- ❌ NÃO permitir criação de incrementos negativos sob nenhuma hipótese.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`:
- Reutilizar `ProductionCavityConfig`, `ProductionShift` e a infraestrutura de coletor existente.
- Garantir transações atômicas (`@transaction.atomic`) e compatibilidade entre SQLite e MySQL.
- Travar concorrência com o mecanismo de lock cross-process já existente (`scada_collector.lock`).

---

## ⚙️ 7. REGRAS DE NEGÓCIO DETALHADAS

### 1. Model `ProductionCycle`:
```python
class ProductionCycle(models.Model):
    CLOSE_REASONS = [
        ("RESET_CONTADOR", "Reset de Contador Scada"),
        ("TROCA_MATRIZ", "Troca de Matriz"),
        ("TROCA_BLADDER", "Troca de Bladder"),
        ("FIM_TURNO", "Fechamento de Turno"),
        ("MANUAL", "Encerramento Manual"),
    ]
    cavity_config = models.ForeignKey(ProductionCavityConfig, on_delete=models.CASCADE, related_name="cycles")
    matriz = models.CharField(max_length=100, blank=True, null=True)
    produto = models.CharField(max_length=100, blank=True, null=True)
    lote_bladder = models.CharField(max_length=100, blank=True, null=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    initial_counter = models.PositiveIntegerField(default=0)
    final_counter = models.PositiveIntegerField(null=True, blank=True)
    quantity_produced = models.PositiveIntegerField(default=0)
    close_reason = models.CharField(max_length=30, choices=CLOSE_REASONS, null=True, blank=True)
    last_scada_ts = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 2. Model `ProductionShiftAccumulated`:
```python
class ProductionShiftAccumulated(models.Model):
    date = models.DateField()
    shift = models.ForeignKey(ProductionShift, on_delete=models.CASCADE, related_name="accumulated_records")
    cavity_config = models.ForeignKey(ProductionCavityConfig, on_delete=models.CASCADE, related_name="shift_accumulated")
    matriz = models.CharField(max_length=100, blank=True, null=True)
    produto = models.CharField(max_length=100, blank=True, null=True)
    quantity_accumulated = models.PositiveIntegerField(default=0)
    last_scada_counter = models.PositiveIntegerField(default=0)
    last_scada_ts = models.BigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 3. Regras de Detecção de Reset e Cálculo Incremental:
- **Timestamp duplicado / idêntico**: se `scada_ts <= last_scada_ts`, ignorar o ciclo de cálculo (idempotência contra retries).
- **Leitura Normal (`leitura_atual >= leitura_anterior` e mesmo lote/matriz)**:
  - `incremento = leitura_atual - leitura_anterior`
  - Soma `incremento` ao `ProductionCycle` ativo e ao `ProductionShiftAccumulated` do turno corrente.
- **Reset Detectado (`leitura_atual < leitura_anterior` OU troca de `matriz` OU troca de `lote_bladder`)**:
  1. Identificar o motivo do encerramento (`TROCA_MATRIZ`, `TROCA_BLADDER` ou `RESET_CONTADOR`).
  2. Encerrar o `ProductionCycle` ativo definindo `ended_at = now`, `final_counter = leitura_anterior`, `close_reason = motivo`.
  3. Criar um novo `ProductionCycle` ativo com `started_at = now`, `initial_counter = leitura_atual`, `quantity_produced = 0` (se `leitura_atual` já veio com valor inicial > 0 pós-reset, `quantity_produced = leitura_atual`).
  4. Somar o valor válido pós-reset à `quantity_accumulated` do turno em `ProductionShiftAccumulated`.
- **Transição de Turno (atravessando meia-noite)**:
  - Ao entrar em um novo turno, o sistema obtém/cria o registro `ProductionShiftAccumulated` para `(data_atual, turno_atual, cavidade)` zerado, iniciando a contagem do novo turno sem destruir nem encerrar o `ProductionCycle` físico do molde (que pode continuar rodando no próximo turno).

---

## 🗄️ 8. MIGRATION PREVISTA

- **Arquivo**: `production/migrations/0013_productioncycle_productionshiftaccumulated.py`
- **Operações**: `CreateModel` para `ProductionCycle` e `ProductionShiftAccumulated` com índices em `(cavity_config, started_at)` e `(date, shift, cavity_config)`.

---

## 🧪 9. CRITÉRIOS DE ACEITAÇÃO

- [ ] Quando o contador do Scada cresce normalmente (ex: 430 -> 445), o acumulado do turno aumenta exatamente 15.
- [ ] Quando ocorre um reset no Scada (ex: 1180 -> 8), a produção anterior do turno (1180) é preservada e os 8 novos são adicionados (total 1188).
- [ ] Trocas de matriz ou bladder fecham o `ProductionCycle` anterior e abrem um novo sem perder o histórico do turno.
- [ ] Reinício ou retry do coletor com os mesmos timestamps do Scada não duplica os incrementos.
- [ ] Indisponibilidade do Scada ou dado `stale` não dispara reset de produção.
- [ ] Turnos que atravessam a meia-noite acumulam corretamente sem estouro de data.
- [ ] A view do dashboard web lê os dados acumulados do banco default instantaneamente.

---

## ⚠️ 10. RISCOS E MITIGAÇÕES

- **Risco**: Duas instâncias do coletor rodando em paralelo gerando incrementos duplicados.
  - *Mitigação*: Trava física cross-process `scada_collector.lock` + verificação de timestamp `scada_ts <= last_scada_ts`.
- **Risco**: Queda temporária de rede do Scada ser interpretada como contador zero e resetar o ciclo.
  - *Mitigação*: Leitura nula ou falha de comunicação é tratada como `SEM_COMUNICACAO` / `stale`, congelando o estado sem fechar o ciclo.

---

## 🔍 11. PLANO DE IMPLEMENTAÇÃO

1. Definir os modelos `ProductionCycle` e `ProductionShiftAccumulated` em `production/models.py`.
2. Executar `makemigrations` gerando a migration `0013`.
3. Implementar o método `process_incremental_production` em `ProductionStateService` (`production/services.py`).
4. Atualizar `build_cavities_data` para obter a produção do turno via `ProductionShiftAccumulated`.
5. Desenvolver suíte abrangente de testes automatizados para todos os cenários de reset.

---

## 🧪 12. TESTES AUTOMATIZADOS E MANUAIS

### Testes Automatizados (Obrigatórios):
- `test_normal_counter_increment`: verifica incremento 430 -> 445.
- `test_reset_on_counter_drop`: verifica reset 1180 -> 8 acumulando 1188 no turno.
- `test_reset_on_matrix_change`: verifica fechamento do ciclo ao trocar matriz.
- `test_reset_on_bladder_change`: verifica fechamento do ciclo ao trocar lote do bladder.
- `test_collector_retry_idempotency`: simula duas execuções com mesmo timestamp e garante que o acúmulo não duplica.
- `test_scada_unavailability_does_not_trigger_reset`: simula timeout/nulo do Scada e garante que não há reset.
- `test_shift_transition_across_midnight`: testa virada de turno à 00:00.

---

## 🛑 13. GATE DE SAÍDA E REGRA DE PARADA

- **Gate de Saída**: Testes automatizados de reset e idempotência 100% aprovados (`manage.py test`).
- **Regra de Parada**: Se for detectada concorrência de escritas sem lock de banco/processo, PARAR e aplicar `select_for_update` imediatamente.
