# 🧠 SPEC 06A — METAS DIÁRIAS E TURNOS DE PRODUÇÃO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<id>/`, `/admin/production/productionshift/`
- **Contexto(s):** Módulo de Produção — Distribuição dinâmica de metas de produção por turno e cadastro administrável de turnos industriais.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras Obrigatórias:** `SPEC_PRODUCAO_05D_HISTORICO_MATRIZES_LINHA_TEMPO.md`, `SPEC_PRODUCAO_06_HARDENING_DEPLOY_ROLLBACK.md`.

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, as metas de produção são cadastradas por cavidade de forma estática via `meta_producao_manual` em `ProductionCavityConfig`, sem suporte a divisão por turnos operacionais.
- Os turnos de trabalho na fábrica não podem ser hardcoded no código Python, pois sofrem alterações de horário e percentual de distribuição ao longo do ano.
- Falta uma estrutura administrável via Django Admin para gerenciar turnos, incluindo nome, horário inicial, horário final, suporte a travessia de meia-noite (ex: 22:00 às 06:00), ordem de exibição, flag ativo/inativo e percentual/peso de distribuição da meta diária.
- Faltam indicadores no dashboard para apresentar: Meta Diária, Meta do Turno Atual, Produção Realizada no Turno, Diferença para a Meta do Turno e Percentual de Conclusão.

---

## 🎯 3. OBJETIVO

1. **Model `ProductionShift`:** Criar modelo local gerenciado no banco `default` em `production/models.py` para cadastrar turnos operacionais.
2. **Registro no Router:** Adicionar `"productionshift"` em `ScadaRouter.LOCAL_MANAGED_MODELS`.
3. **Validação de Soma de Percentuais:** Implementar validação em `clean()` no model/admin para garantir que a soma dos percentuais dos turnos ativos seja exatamente 100.0% (quando customizados) ou aplicar fallback de divisão igualitária quando percentuais não forem informados.
4. **Calculadora de Turno Ativo com Meia-Noite:** Implementar helper em `services.py` que identifique qual turno está ativo para um determinado timestamp (suportando viradas de dia como 22:00 às 06:00).
5. **Evolução de `ProductionCavityConfig`:** Preservar `meta_producao_manual` por compatibilidade e vincular conceitualmente como a Meta Diária da Cavidade.
6. **Cálculo da Produção e Meta do Turno:** Calcular a meta proporcional do turno atual (`meta_diaria * (percentual_turno / 100)`) e a produção realizada no turno ativo.
7. **Exibição na Interface:** Apresentar Meta Diária, Meta do Turno, Produção do Turno, Diferença e % Conclusão nos cards do dashboard e detalhe da máquina.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Permitidos:
- `production/models.py`: Criar `ProductionShift` e métodos auxiliares.
- `production/routers.py`: Adicionar `"productionshift"` em `LOCAL_MANAGED_MODELS`.
- `production/admin.py`: Registrar `ProductionShift` com `list_display`, `list_editable` e validação `clean()`.
- `production/migrations/0008_metas_diarias_e_turnos.py` [NOVA]: Migration aditiva exclusiva no `default`.
- `production/services.py`: Adicionar funções para resolução de turno ativo, cálculo de meta de turno e produção realizada no turno.
- `production/views.py`: Repassar métricas de turno no contexto.
- `production/templates/production/dashboard.html`: Exibir bloco de métricas do turno nos cards.
- `production/templates/production/machine_detail.html`: Exibir bloco de métricas do turno no detalhe.
- `production/tests.py`: Adicionar suíte de testes `Spec06AShiftsAndTargetsTestCase`.
- `Instrucoes.txt`: Registrar execução da SPEC 06A.

### Arquivos Proibidos:
- Todos os arquivos do app `maintenance`.
- Modificar tabelas ou models `managed=False` do Scada.
- Modificar migrations `0001` a `0007`.

---

## 🔐 5. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ Não criar múltiplos ambientes virtuais ou duplicar apps Django.
- ✅ Manter escrita restrita ao banco `default`.
- ✅ Acesso exclusivo para `Liderança de Produção` e Superusuários.
- ✅ Resiliência offline: Scada indisponível não deve zerar ou quebrar os cadastros de turnos.

---

## ⚙️ 6. REGRAS DE NEGÓCIO

1. **Estrutura do Model `ProductionShift`:**
   - `nome`: CharField(max_length=50) — Ex: "1º Turno", "Turno Manhã".
   - `horario_inicial`: TimeField() — Ex: 06:00.
   - `horario_final`: TimeField() — Ex: 14:00.
   - `atravessa_meia_noite`: BooleanField(default=False) — Calculado/indicado se `horario_final <= horario_inicial`.
   - `percentual_meta`: DecimalField(max_digits=5, decimal_places=2, default=0.00) — Peso % do turno (0 a 100).
   - `ordem_exibicao`: PositiveIntegerField(default=1).
   - `ativo`: BooleanField(default=True).

2. **Detecção de Turno Ativo:**
   - Se `not atravessa_meia_noite`: ativo se `inicio <= hora_atual < fim`.
   - Se `atravessa_meia_noite`: ativo se `hora_atual >= inicio OR hora_atual < fim`.

3. **Validação de Percentuais:**
   - Se houver N turnos ativos com `percentual_meta > 0`, a soma deve ser exatamente `100.00`. Caso contrário, o Admin deve lançar `ValidationError`.
   - Se todos os turnos ativos estiverem com `percentual_meta == 0`, a distribuição será idêntica: `percentual = 100.0 / N_turnos_ativos`.

4. **Cálculo da Meta do Turno:**
   - `meta_turno = round(meta_diaria * (percentual_meta / 100.0))`

5. **Diferença para a Meta:**
   - `diferenca_meta = producao_realizada_turno - meta_turno_atual` (ex: +5 se ultrapassou, -12 se pendente).

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO

- [ ] Model `ProductionShift` registrado no Admin e incluído no `LOCAL_MANAGED_MODELS`.
- [ ] Migration `0008` gerada e aplicada aditivamente no banco `default`.
- [ ] Turnos atravessando a meia-noite (ex: 22:00 às 06:00) detectados corretamente.
- [ ] Soma de percentuais validada em 100% no Admin com fallback para divisão igualitária.
- [ ] Dashboard e Detalhe da Máquina exibindo Meta Diária, Meta Turno, Realizado Turno, Diferença e % Conclusão.
- [ ] Todos os testes da suíte global passando 100%.

---

## ⚠️ 8. RISCOS

- **Turno não encontrado em horário de transição:** Tratar caso de fuso horário ou janela não coberta garantindo fallback limpo para "Fora de Turno".
- **Divisão por zero:** Garantir tratamento quando `meta_turno == 0`.

---

## 🔍 9. PLANO DE IMPLEMENTAÇÃO

1. Criar `ProductionShift` em `models.py` e atualizar `LOCAL_MANAGED_MODELS` em `routers.py`.
2. Registrar em `admin.py` com validação de soma de percentuais.
3. Gerar e aplicar migration `0008` no banco `default`.
4. Implementar helpers de resolução de turno em `services.py`.
5. Atualizar views e templates (`dashboard.html`, `machine_detail.html`).
6. Adicionar testes unitários em `tests.py` e validar suíte.

---

## 🧪 10. TESTES AUTOMATIZADOS E MANUAIS

- **Automatizados:** Testar detecção de turno diurno e noturno (meia-noite), validação de soma de percentuais, fallback igualitário e cálculo de diferença de meta.
- **Manuais:** Criar 3 turnos no Admin (06-14, 14-22, 22-06), alterar horário do sistema/mock e verificar se o turno ativo muda corretamente no dashboard.

---

## 🛡️ 11. DEPLOY, ESTRATÉGIA DE ROLLBACK E GATE DE SAÍDA

- **Rollback:** `python manage.py migrate production 0007` restaura o esquema de banco original.
- **Gate de Saída:** 100% dos testes da suíte globais verdes.
- **Regra de Parada:** Interromper imediatamente em caso de falha no isolamento do banco `scada`.
