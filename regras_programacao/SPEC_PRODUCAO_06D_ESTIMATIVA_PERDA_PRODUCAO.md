# 🧠 SPEC 06D — ESTIMATIVA DE PERDA DE PRODUÇÃO POR PERÍODO E CAVIDADE

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<id>/`, `/producao/maquinas/<id>/cavidades/<id>/`
- **Contexto(s):** Módulo de Produção — Cálculo probabilístico de taxa de produção (pneus/hora) por cavidade e estimativa de pneus não fabricados durante paradas operacionais.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras Obrigatórias:** `SPEC_PRODUCAO_06C_RESPONSAVEIS_E_ATUALIZACOES_MANUTENCAO.md`.

---

## ❗ 2. PROBLEMA ATUAL

- Quando uma cavidade fica parada por um determinado tempo, a gestão de Produção precisa saber a estimativa de quantos pneus deixaram de ser fabricados naquele intervalo.
- É estritamente PROIBIDO realizar consultas pesadas na tabela histórica `pointvalues` do Scada-LTS dentro das views web HTTP a cada acesso de usuário.
- O sistema precisa acumular amostras compactas e confiáveis de produção em tempo de execução via coletor background (`collect_production_scada`) e salvá-las no banco `default`.
- É necessário definir formalmente a estrutura de agregados de taxa de produção, fallbacks progressivos para médias, critérios de amostra mínima, tratamento de reset de contadores e limites de retenção.

---

## 🎯 3. OBJETIVO

1. **Model `ProductionRateAggregate`:** Criar modelo local gerenciado em `production/models.py` para armazenar agregados compactos de taxa de produção no banco `default`.
2. **Inclusão no Router:** Adicionar `"productionrateaggregate"` em `ScadaRouter.LOCAL_MANAGED_MODELS`.
3. **Agregação no Coletor:** Evoluir o coletor background para consolidar janelas válidas de produção (ex: janelas de 15 minutos) onde a cavidade estava operando normalmente e o contador de produção evoluiu validamente.
4. **Hierarquia de Fallback Progressivo:**
   - 1º Nível: Média de (Cavidade + Produto + Matriz)
   - 2º Nível: Média de (Cavidade + Produto)
   - 3º Nível: Média de (Cavidade)
   - 4º Nível: Média da (Máquina)
5. **Apresentação Clara na Interface:**
   - Se dados suficientes: `"Perda estimada: aproximadamente 52 pneus (Base: média de 36,4 pneus/hora em 18 intervalos válidos)"`
   - Se dados insuficientes: `"Estimativa indisponível — ainda não existem dados suficientes para uma média confiável."`
6. **Command de Backfill (Opcional):** Criar `python manage.py backfill_production_aggregates` para pré-popular agregados históricos apenas via CLI offline.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Permitidos:
- `production/models.py`: Criar `ProductionRateAggregate`.
- `production/routers.py`: Adicionar modelo em `LOCAL_MANAGED_MODELS`.
- `production/admin.py`: Registrar `ProductionRateAggregate`.
- `production/migrations/0010_estimativa_perda_producao.py` [NOVA]: Migration aditiva em `default`.
- `production/services.py`: Lógica de consolidação de agregados no coletor e calculadora de estimativa de perda com fallback progressivo.
- `production/management/commands/collect_production_scada.py`: Atualizar para gerar agregados periódicos.
- `production/management/commands/backfill_production_aggregates.py` [NOVO]: CLI de backfill histórico offline.
- `production/templates/production/machine_detail.html`: Exibir bloco de estimativa de perda.
- `production/tests.py`: Adicionar testes automatizados `Spec06DLossEstimationTestCase`.
- `Instrucoes.txt`: Registrar execução da SPEC 06D.

### Arquivos Proibidos:
- Realizar queries pesadas ao Scada MySQL dentro de views HTTP.
- Modificar o app `maintenance`.

---

## 🔐 5. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ NUNCA consultar `pointvalues` em requisições de página web.
- ✅ Escrita e agregação puramente no banco `default`.
- ✅ Resiliência: reset de contador ou rollover no CLP é tratado sem gerar taxas negativas ou absurdas.

---

## ⚙️ 6. REGRAS DE NEGÓCIO E MODELAGEM

1. **Model `ProductionRateAggregate`:**
   - `cavity_config`: ForeignKey(`ProductionCavityConfig`, on_delete=CASCADE).
   - `produto`: CharField(max_length=100, null=True, blank=True).
   - `matriz`: CharField(max_length=100, null=True, blank=True).
   - `inicio_intervalo`: DateTimeField().
   - `fim_intervalo`: DateTimeField().
   - `minutos_produzindo`: PositiveIntegerField().
   - `quantidade_produzida`: PositiveIntegerField().
   - `taxa_pneus_hora`: DecimalField(max_digits=7, decimal_places=2).
   - `quantidade_amostras`: PositiveIntegerField(default=1).

   *Índices:* `["cavity_config", "produto", "matriz"]`, `["inicio_intervalo"]`.

2. **Filtros de Validade de Amostra:**
   - Um intervalo é considerado válido somente se:
     1. A cavidade estava em estado NORMAL / Produzindo durante todo o intervalo;
     2. O dado do Scada estava atualizado (não stale);
     3. A duração do intervalo é >= 15 minutos (900 segundos);
     4. A quantidade produzida no intervalo é > 0 e o contador evoluiu de forma estritamente crescente;
     5. Se `contador_atual < contador_anterior`, ocorreu reset/rollover: o intervalo é DESCARTADO do cálculo da taxa.

3. **Confiança Mínima:**
   - Mínimo de 3 intervalos válidos (ou 45 minutos totais de produção comprovada) no nível de fallback avaliado para considerar a média confiável.
   - Caso não atinja 3 amostras no nível 1 (Cavidade+Produto+Matriz), tenta o nível 2 (Cavidade+Produto), depois nível 3 (Cavidade), e por fim nível 4 (Máquina).
   - Se nenhum nível atingir o mínimo: exibe `"Estimativa indisponível — ainda não existem dados suficientes para uma média confiável."`.

4. **Fórmula da Estimativa de Perda:**
   - `perda_pneus = int(round((duracao_parada_minutos / 60.0) * taxa_pneus_hora_media))`

5. **Limite de Retenção de Agregados:**
   - Agregados antigos em `ProductionRateAggregate` são mantidos por até 90 dias no banco `default`. A purga automática dos registros com mais de 90 dias é executada 1x por dia pelo coletor.

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO

- [ ] Model `ProductionRateAggregate` gerado e migration `0010` aplicada no `default`.
- [ ] Coletor background gera agregados válidos de 15 minutos sem travar ciclos.
- [ ] Zero consultas na tabela `pointvalues` durante requisições de views web.
- [ ] Reset de contador do CLP descartado sem gerar erro ou valor negativo.
- [ ] Fallback progressivo de 4 níveis funcionando corretamente.
- [ ] Texto de estimativa exibido com precisão ou mensagem de indisponibilidade tratada.
- [ ] Suíte de testes 100% verde.

---

## ⚠️ 8. RISCOS

- **Acúmulo de dados locais:** Purga automática limita a retenção a 90 dias.
- **Divisão por zero:** Proteção explícita na conversão de taxa `minutos_produzindo > 0`.

---

## 🔍 9. PLANO DE IMPLEMENTAÇÃO

1. Criar `ProductionRateAggregate` em `models.py` e adicionar em `LOCAL_MANAGED_MODELS` do router.
2. Registrar em `admin.py`.
3. Gerar e aplicar migration `0010`.
4. Implementar gerador de agregados e calculadora de estimativa em `services.py`.
5. Atualizar coletor `collect_production_scada.py`.
6. Atualizar templates da Produção (`machine_detail.html`).
7. Escrever e executar testes unitários.

---

## 🧪 10. TESTES AUTOMATIZADOS E MANUAIS

- **Automatizados:** Testar geração de agregados, descarte de contadores resetados, fallback progressivo em 4 níveis e formatação de texto de perda estimada.
- **Manuais:** Simular parada de cavidade por 2 horas com taxa histórica cadastrada de 20 pneus/h e validar se a perda estimada exibe aproximadamente 40 pneus.

---

## 🛡️ 11. ROLLBACK E GATE DE SAÍDA

- **Rollback:** `python manage.py migrate production 0009` reverte a migração `0010`.
- **Gate de Saída:** Suíte de testes globais 100% aprovada.
- **Regra de Parada:** Interromper se for detectada qualquer query a `pointvalues` em requisição de view HTTP.
