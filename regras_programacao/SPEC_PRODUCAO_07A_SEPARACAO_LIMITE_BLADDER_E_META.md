# 🧠 SPEC_PRODUCAO_07A — SEPARAÇÃO ENTRE LIMITE DE PRODUÇÃO DO BLADDER E META DE PRODUÇÃO

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `SPEC_PRODUCAO_06F_INTEGRACAO_UX_PERFORMANCE_DEPLOY.md`
- **URL(s) envolvidas**:
  - `/producao/` (Dashboard de Produção)
  - `/producao/maquinas/<id>/` (Detalhe da Máquina)
  - `/producao/maquinas/<machine_id>/cavidades/<cavity_id>/` (Detalhe da Cavidade)
  - `/admin/production/productioncavityconfig/` (Django Admin)
- **Contexto(s)**: Módulo de Produção Industrial / Painel Sinóptico / Cadastros
- **Perfil(s) afetados**: Líder de Produção, PCP, Operador de Vulcanização, Administrador

---

## ❗ 2. PROBLEMA ATUAL

Hoje o campo vindo do Scada via `xid_meta` em `ProductionCavityConfig` está documentado como "XID Meta de Produção (Reservado Futuro)".
No entanto, foi esclarecido que o valor numérico que trafega neste XID do Scada **NÃO É** a meta diária nem a meta do turno. Trata-se do **limite de vida produtiva do ciclo do bladder** (ex: 2000 vulcanizações máximas por bladder).
Quando o bladder ou a matriz são trocados no chão de fábrica, esse limite pode ser resetado no Scada.
Por outro lado, o valor `meta_producao_manual` é cadastrado pelo usuário como a meta diária/turno.
A falta de separação clara entre esses 4 conceitos gera confusão para os operadores e supervisores no chão de fábrica:
1. *Limite de Produção do Bladder* (Vem do Scada, pertence ao ciclo atual do bladder, pode zerar/reiniciar após troca).
2. *Contador do Ciclo Atual* (Vem do Scada, representa a produção física da cavidade desde a última zeragem/reset).
3. *Produção Acumulada do Turno* (Calculada pelo sistema, soma os incrementos válidos, imune a resets).
4. *Meta de Produção do Turno* (Inserida manualmente / PCP, não vem do Scada, vinculada a data/turno/matriz).

---

## 🎯 3. OBJETIVO

Separar formalmente os 4 conceitos no backend, nas estruturas de dados, no Django Admin e na interface web:
- Ajustar os metadados (`verbose_name`, `help_text`, labels de formulários) do model `ProductionCavityConfig`:
  - `xid_meta`: alterar verbose_name para `"XID Limite de Produção do Bladder (Scada)"` e help_text para `"Código XID no Scada que fornece o limite de vida produtiva do ciclo do bladder."`.
  - `meta_producao_manual`: alterar verbose_name para `"Meta Manual de Produção"` e help_text para `"Meta diária de produção cadastrada manualmente pelo PCP / Líder de Produção."`.
- Atualizar o dicionário de contexto montado em `services.py` (`build_cavities_data` / `get_cavity_detail`):
  - `limite_bladder_scada`: valor numérico lido do XID `xid_meta` (ou None / 0 se ausente).
  - `contador_ciclo_scada`: valor bruto instantâneo lido de `xid_producao`.
  - `producao_acumulada_turno`: total calculado de produção no turno corrente.
  - `meta_turno`: meta do turno calculada a partir da meta manual.
- Atualizar os templates web e cards de cavidade para exibir separadamente "Limite do Bladder: X" e "Meta do Turno: Y".

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/models.py): atualização de `verbose_name` e `help_text` em `ProductionCavityConfig`.
- [admin.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/admin.py): atualização de fieldsets e rótulos no `ProductionCavityConfigAdmin`.
- [services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py): ajuste na extração de `scada_values` para mapear `limite_bladder_scada`, `contador_ciclo_scada`, `producao_acumulada_turno` e `meta_turno`.
- [templates](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/):
  - `dashboard.html`
  - `machine_detail.html`
  - `cavity_detail.html`
- [migrations](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/migrations/): nova migration de alteração de metadados (`0012_separacao_limite_bladder_meta.py`).

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO realizar renomeação destrutiva de colunas no banco de dados (`xid_meta` e `meta_producao_manual` mantêm seus nomes de coluna no schema por compatibilidade retroativa).
- ❌ NÃO alterar a tabela MySQL do Scada-LTS (0% de escrita ou alteração de DDL no Scada).
- ❌ NÃO remover o suporte às metas diárias e por turno existentes.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`:
- Reutilizar a estrutura existente de `ProductionCavityConfig`.
- Garantir compatibilidade SQLite e MySQL.
- Sem SQL puro (usar Django ORM).
- Manter permissões restritas a `@lider_producao_required`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Limite do Bladder (Scada)**:
   - Lido do XID `xid_meta`.
   - Se o XID não estiver configurado ou o Scada estiver offline, exibir `"N/A"` ou `"Não configurado"`.
   - Pode zerar ou mudar quando ocorrer troca de bladder no Scada. NÃO afeta o valor da Meta do Turno.
2. **Contador do Ciclo Atual (Scada)**:
   - Lido do XID `xid_producao`.
   - Representa os pneus vulcanizados desde a última zeragem do PLC/Scada.
3. **Produção Acumulada do Turno**:
   - Total acumulado válido durante o turno (desenvolvido e integrado na SPEC 07B).
4. **Meta de Produção (Manual)**:
   - Definida em `meta_producao_manual` ou cadastrada no módulo de metas (SPEC 07C).
   - Distribuída proporcionalmente entre os turnos ativos (`ProductionShift`).

---

## 🗄️ 8. MIGRATION PREVISTA

- **Arquivo**: `production/migrations/0012_separacao_limite_bladder_meta.py`
- **Operação**: `AlterField` em `xid_meta` e `meta_producao_manual` alterando apenas `verbose_name` e `help_text`.
- **Estratégia de Rollback**: A migration é 100% não-destrutiva (apenas metadados do ORM). O rollback reverte os metadados para os valores anteriores sem afetar tabelas.

---

## 🧪 9. CRITÉRIOS DE ACEITAÇÃO

- [ ] O Django Admin exibe `"XID Limite de Produção do Bladder (Scada)"` no lugar de `"XID Meta de Produção (Reservado Futuro)"`.
- [ ] No card da cavidade do dashboard e nas telas de detalhe, os valores de "Limite do Bladder" e "Meta do Turno" são exibidos em campos distintos e rotulados.
- [ ] Trocas de valores em `xid_meta` não alteram o cálculo da Meta do Turno.
- [ ] Nenhuma alteração destrutiva é feita no schema de banco de dados.
- [ ] Todos os 135 testes automatizados passam sem falha ou regressão.

---

## ⚠️ 10. RISCOS E MITIGAÇÕES

- **Risco**: Confusão por parte do usuário com templates legados.
  - *Mitigação*: Atualizar todos os 3 templates (`dashboard.html`, `machine_detail.html`, `cavity_detail.html`) simultaneamente e validar via testes de template.
- **Risco**: Quebra de variáveis de contexto consumidas por JavaScript no frontend.
  - *Mitigação*: Manter compatibilidade mantendo os atributos legados no dicionário e adicionando as novas chaves explícitas.

---

## 🔍 11. PLANO DE IMPLEMENTAÇÃO

1. Atualizar `verbose_name` e `help_text` no model `ProductionCavityConfig` em `production/models.py`.
2. Gerar e verificar a migration `0012_separacao_limite_bladder_meta.py` via `makemigrations`.
3. Ajustar `ProductionCavityConfigAdmin` em `production/admin.py`.
4. Atualizar os métodos `build_cavities_data` e `get_cavity_detail` em `production/services.py` para fornecer `limite_bladder_scada`, `contador_ciclo_scada`, `producao_acumulada_turno` e `meta_turno`.
5. Atualizar os templates HTML com rótulos semânticos e badges explicativos.
6. Criar e rodar testes automatizados em `production/tests.py`.

---

## 🧪 12. TESTES AUTOMATIZADOS E MANUAIS

### Testes Automatizados:
- `test_cavity_config_verbose_names`: valida se os novos `verbose_name` e `help_text` estão configurados no model.
- `test_cavity_context_separates_bladder_limit_and_shift_target`: valida se o contexto de `build_cavities_data` inclui `limite_bladder_scada` e `meta_turno` como chaves independentes.
- `test_template_renders_distinct_bladder_limit_and_shift_target`: simula GET nas views e verifica se os textos "Limite do Bladder" e "Meta do Turno" são renderizados separadamente.

### Testes Manuais:
1. Acessar `/admin/production/productioncavityconfig/` e verificar o novo título da seção de XIDs.
2. Acessar `/producao/` e verificar o card da prensa e cavidades.
3. Alterar o valor do XID `xid_meta` via simulador e confirmar que o card exibe o limite do bladder sem alterar a meta do turno.

---

## 🛑 13. GATE DE SAÍDA E REGRA DE PARADA

- **Gate de Saída**: Migrações aplicadas sem erro, suíte de testes 100% verde (`manage.py test`).
- **Regra de Parada**: Se for detectada a necessidade de renomear a coluna no banco (`ALTER TABLE RENAME COLUMN`), PARAR imediatamente e reavaliar a estratégia para preservar compatibilidade retroativa.
