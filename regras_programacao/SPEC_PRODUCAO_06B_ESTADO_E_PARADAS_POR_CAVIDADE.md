# 🧠 SPEC 06B — ESTADO E EVENTOS DE PARADA POR CAVIDADE

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<id>/`
- **Contexto(s):** Módulo de Produção — Monitoramento individualizado por cavidade e rastreamento de histórico relacional de paradas por cavidade.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras Obrigatórias:** `SPEC_PRODUCAO_06A_METAS_DIARIAS_E_TURNOS.md`.

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, apenas a prensa possui rastreamento histórico de eventos de parada via `ProductionDowntimeEvent`.
- Uma prensa de vulcanização pode continuar operando normalmente mesmo que 1 ou mais de suas cavidades/moldes estejam parados ou isolados por defeito.
- Não existem modelos para registrar o estado atual ativo da cavidade (`ProductionCavityState`) nem o histórico de eventos de parada de cavidade (`ProductionCavityDowntimeEvent`).
- Falta um indicador global destacado no topo do dashboard `/producao/` exibindo a quantidade total de cavidades paradas no momento na fábrica, com suporte a clique/filtro.

---

## 3. OBJETIVO

1. **Novos Models Locais:** Criar `ProductionCavityState` e `ProductionCavityDowntimeEvent` no banco `default` em `production/models.py`.
2. **Registro no Router:** Adicionar `"productioncavitystate"` e `"productioncavitydowntimeevent"` em `ScadaRouter.LOCAL_MANAGED_MODELS`.
3. **Máquina de Estados por Cavidade:** Evoluir o coletor `collect_production_scada` (`ProductionStateService.process_scada_cycle`) para:
   - Abrir evento em `ProductionCavityDowntimeEvent` quando a cavidade transitar para parada (`xid_motivo_parada` de 1 a 11 ou motivo de parada ativo);
   - Fechar o evento quando a cavidade retornar ao estado normal (`xid_motivo_parada == 0`);
   - Garantir idempotência: não duplicar eventos em retries, reinícios de serviço ou coletas simultâneas;
   - Ignorar transições quando os dados estiverem desatualizados (stale) ou sem comunicação.
4. **Indicador de Cavidades Paradas:** Adicionar no banner superior de `/producao/` o indicador com a quantidade atual de cavidades paradas, permitindo filtragem rápida das prensas que possuem cavidades paradas.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Permitidos:
- `production/models.py`: Criar `ProductionCavityState` e `ProductionCavityDowntimeEvent`.
- `production/routers.py`: Adicionar novos models em `LOCAL_MANAGED_MODELS`.
- `production/admin.py`: Registrar os novos models no Django Admin.
- `production/migrations/0009_estado_e_paradas_por_cavidade.py` [NOVA]: Migration aditiva exclusiva no `default`.
- `production/services.py`: Atualizar ciclo do coletor para gerenciar transições idempotentes de cavidades.
- `production/templates/production/dashboard.html`: Adicionar card KPI "Cavidades Paradas" e filtro.
- `production/templates/production/machine_detail.html`: Exibir histórico de paradas por cavidade.
- `production/tests.py`: Adicionar suíte `Spec06BCavityDowntimeTestCase`.
- `Instrucoes.txt`: Registrar execução da SPEC 06B.

### Arquivos Proibidos:
- Módulo `maintenance`.
- Tabelas não gerenciadas do Scada.

---

## 🔐 5. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ Não duplicar cadastros de cavidades ou máquinas.
- ✅ Manter idoneidade e idempotência nas transições.
- ✅ Escrita restrita ao banco `default`.

---

## ⚙️ 6. REGRAS DE NEGÓCIO

1. **Model `ProductionCavityState`:**
   - `cavity_config`: OneToOneField(`ProductionCavityConfig`).
   - `estado_atual`: CharField (NORMAL, PARADA, INDETERMINADO).
   - `inicio_estado_atual`: DateTimeField.
   - `ultimo_motivo`: CharField.

2. **Model `ProductionCavityDowntimeEvent`:**
   - `cavity_config`: ForeignKey(`ProductionCavityConfig`).
   - `inicio`: DateTimeField.
   - `fim`: DateTimeField (null=True, blank=True).
   - `duracao_segundos`: PositiveIntegerField (null=True, blank=True).
   - `motivo_parada`: CharField.
   - `snapshot_valor_motivo`: CharField.
   - `timestamp_inicial_scada`: BigIntegerField.
   - `timestamp_final_scada`: BigIntegerField.

3. **Lógica de Transição no Coletor:**
   - Se `xid_motivo_parada` transita de `0` para `1..11`: abre 1 registro em `ProductionCavityDowntimeEvent` com `fim=None`.
   - Se continua parada: não duplica evento. Atualiza motivo se tiver mudado.
   - Se transita de `1..11` para `0`: fecha evento aberto setando `fim=now` e calcula `duracao_segundos`.
   - Se dado stale ou sem comunicação: não abre nem fecha eventos.

4. **Indicador Visual no Dashboard:**
   - Exibe contagem de cavidades paradas (estado == PARADA).
   - Clicar no KPI filtra no frontend apenas os cards de máquinas com ao menos 1 cavidade parada.

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO

- [ ] Models de cavidade criados e roteados no banco `default`.
- [ ] Migration `0009` gerada e aplicada com sucesso.
- [ ] Coletor abre e fecha eventos de parada por cavidade de forma 100% idempotente.
- [ ] Dados stale ou offline não geram nem fecham eventos falsos.
- [ ] KPI de cavidades paradas exibido no dashboard com filtro funcional.
- [ ] Suíte de testes automatizados 100% verde.

---

## ⚠️ 8. RISCOS

- **Concorrência entre coletor e web view:** Operações de transição protegidas por `transaction.atomic()` no `default`.

---

## 🔍 9. PLANO DE IMPLEMENTAÇÃO

1. Adicionar `ProductionCavityState` e `ProductionCavityDowntimeEvent` em `models.py` e `routers.py`.
2. Registrar em `admin.py`.
3. Gerar e aplicar migration `0009`.
4. Atualizar `ProductionStateService.process_scada_cycle()` em `services.py`.
5. Atualizar templates `dashboard.html` e `machine_detail.html`.
6. Adicionar testes unitários em `tests.py`.

---

## 🧪 10. TESTES AUTOMATIZADOS E MANUAIS

- **Automatizados:** Testar transição Normal -> Parada -> Normal em cavidades, garantia de não duplicação em reinício do coletor, e preservação de estado em falha de conexão.
- **Manuais:** Simular motivo de cavidade = 1 no Scada/Mock, verificar abertura de evento e incremento do KPI de cavidades paradas.

---

## 🛡️ 11. DEPLOY, ESTRATÉGIA DE ROLLBACK E GATE DE SAÍDA

- **Rollback:** `python manage.py migrate production 0008` reverte a migração `0009`.
- **Gate de Saída:** Suíte de testes 100% verde.
- **Regra de Parada:** Interromper se houver tentativa de gravação no Scada MySQL.
