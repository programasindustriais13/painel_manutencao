# 🧠 SPEC_PRODUCAO_07D — RESUMO DE PRODUÇÃO AGRUPADA POR TIPO DE MATRIZ

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `SPEC_PRODUCAO_07C_PLANEJAMENTO_METAS_PRODUCAO.md`
- **URL(s) envolvidas**:
  - `/producao/` (Dashboard de Produção)
- **Contexto(s)**: Dashboard Consolidado / Gestão de Vulcanização por Matriz
- **Perfil(s) afetados**: Líder de Produção, PCP, Gestão Industrial

---

## ❗ 2. PROBLEMA ATUAL

No processo industrial, uma mesma matriz ou tipo de matriz (ex: `"Matriz X"`) pode estar instalada simultaneamente em múltiplas máquinas e cavidades (ex: Prensa 1 Cavidade 1, Prensa 3 Cavidade 2, Prensa 7 Cavidade 1).
Atualmente, o operador ou líder precisa somar manualmente no dashboard os valores de cada prensa para saber o total produzido de uma determinada matriz.
Além disso:
1. Aliases textuais vindos do Scada como `"MATRIZ X"`, `"Matriz X"`, `"X"` correm o risco de serem contabilizados como itens separados se não houver normalização.
2. Se uma matriz for desinstalada de uma cavidade no meio do turno e substituída por outra, a produção realizada por ela no início do turno corria o risco de sumir do total agrupado do turno daquela matriz.

---

## 🎯 3. OBJETIVO

Adicionar um Card Resumido no Dashboard do Módulo de Produção (`/producao/`) que agrupa analiticamente a produção por tipo de matriz no turno:
- **Resumo por Tipo de Matriz**:
  - Código Canônico da Matriz / Descrição / Produto.
  - Quantidade de matrizes atualmente instaladas (ex: 3 matrizes ativas).
  - Produção total acumulada no turno (soma de todos os incrementos válidos daquela matriz no turno, inclusive de cavidades onde ela já foi retirada).
  - Meta alocada do turno para a matriz.
  - Diferença (Produção - Meta).
  - Percentual de cumprimento da meta (com barra de progresso visual).
  - Relação de prensas e cavidades participantes (ex: `"Prensa 01 / Cav 1, Prensa 03 / Cav 2, Prensa 07 / Cav 1"`).
- **Normalização de Aliases**:
  - Utilizar o serviço `normalize_matrix_value` e o catálogo `ProductionMatrixCatalog` para mapear variações de caixa ou aliases (`"MATRIZ X"`, `"Matriz X"`) para um único código canônico.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py):
  - Expandir o método `get_dashboard_state` para montar a estrutura `matrix_grouped_summary`.
  - Consultar `ProductionShiftAccumulated` e `ProductionTarget` filtrando por turno e matriz normalizada.
- [templates/production/dashboard.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/dashboard.html):
  - Adicionar o Card "Resumo de Produção por Matriz (Turno)" com tabela responsiva e indicadores de atingimento.

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO criar novas tabelas no banco de dados para esta SPEC (utiliza as tabelas criadas nas SPECs 07B e 07C).
- ❌ NÃO realizar requisições N+1 ao Scada nem reprocessar a série histórica completa de `pointvalues`.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`:
- Agregação em memória e ORM Django otimizado no backend.
- Resposta rápida do dashboard (< 100ms no backend).

---

## ⚙️ 7. REGRAS DE NEGÓCIO DETALHADAS

1. **Preservação de Produção de Matriz Substituída**:
   - Se a Matriz X produziu 500 unidades na Cavidade 1 e depois foi retirada no meio do turno para entrar a Matriz Y, a Matriz X mantém 500 no seu acumulado do turno, e a Matriz Y acumula o que for produzido a partir do momento da sua instalação.
2. **Cálculo do Percentual de Atingimento**:
   - `percentual = round((producao_total_matriz / meta_total_matriz) * 100)` se `meta_total_matriz > 0`, senão `0%`.
3. **Formatação de Diferença**:
   - Se `producao > meta`, exibir com sinal positivo (ex: `"+45"` em verde).
   - Se `producao < meta`, exibir com sinal negativo (ex: `"-30"` em vermelho).

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Matrizes idênticas em prensas diferentes (ex: Prensa 1 Cav 1 e Prensa 3 Cav 2) aparecem agrupadas sob a mesma matriz no resumo.
- [ ] Variações de digitação ("MATRIZ X", "Matriz X") são unificadas para a mesma chave.
- [ ] A remoção de uma matriz durante o turno não apaga a produção realizada por ela no início do turno.
- [ ] O card exibe quantidade de matrizes instaladas, produção do turno, meta, diferença, percentual e lista de máquinas.
- [ ] Suíte de testes automatizados passa 100%.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Código de matriz ser nulo ou vazio no Scada.
  - *Mitigação*: Agrupar valores vazios ou nulos sob o rótulo `"Matriz não informada"` sem quebrar o agrupamento dos demais.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Criar helper `get_grouped_matrix_production_summary` em `ProductionStateService` (`production/services.py`).
2. Consultar `ProductionShiftAccumulated` agregando por `matriz` normalizada.
3. Integrar com as metas de `ProductionTarget`.
4. Atualizar `production/templates/production/dashboard.html` renderizando o novo card de resumo.
5. Criar testes automatizados cobrindo agrupamento de matrizes em múltiplas máquinas e trocas no turno.

---

## 🧪 11. TESTES AUTOMATIZADOS E MANUAIS

### Testes Automatizados:
- `test_matrix_grouping_across_multiple_presses`: simula Matriz X na Prensa 1 Cav 1 e Prensa 3 Cav 2 e valida soma total.
- `test_matrix_alias_normalization`: envia "MATRIZ X" e "Matriz X" e verifica se caem no mesmo grupo.
- `test_replaced_matrix_preserves_accumulated_production`: instala Matriz X, acumula 100, substitui por Matriz Y, acumula 50, e valida que Matriz X mantêm 100 e Matriz Y tem 50 no resumo.

---

## 🛑 12. GATE DE SAÍDA E REGRA DE PARADA

- **Gate de Saída**: Testes de agrupamento por matriz 100% aprovados.
- **Regra de Parada**: Se a consulta de agrupamento gerar consultas redundantes N+1, PARAR e aplicar `select_related`/`prefetch_related` ou agregações com `values().annotate()`.
