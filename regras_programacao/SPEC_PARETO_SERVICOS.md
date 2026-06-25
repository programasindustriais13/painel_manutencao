# 🧠 SPEC — ALTERAÇÃO DA BASE DE DADOS DO GRÁFICO DE PARETO (DE PAUSAS PARA SERVIÇOS)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/dashboard/`
- **Contexto(s):** Dashboard de Gestão da Manutenção
- **Perfil(s) afetados:** Técnico Líder e Operador/Administrador

---

## ❗ 2. PROBLEMA ATUAL

- O gráfico de Pareto atual (Gráfico 1) está configurado para mostrar os "Motivos de Pausa", baseado na tabela `HistoricoPausa`.
- A gestão decidiu que o foco principal desse gráfico deve ser **quais tipos de serviços/atendimentos estão consumindo mais tempo da equipe**, e não onde o tempo é perdido em pausas.
- O título e a base de dados do gráfico precisam ser alterados para refletir essa decisão.

---

## 🎯 3. OBJETIVO

- Alterar a fonte de dados do "Gráfico 1" (Pareto) no backend de `HistoricoPausa` para `Allocation`.
- A query deve consultar as alocações concluídas (`status='CONCLUIDO'`) no período e agrupá-las pelo campo de descrição/observação do serviço (`atividade_observacao`).
- Calcular a duração líquida total (tempo bruto menos pausas) consumida por cada tipo de serviço e exibir as top 15 descrições ordenadas por tempo decrescente.
- Alterar o título do gráfico no frontend para "Pareto de Serviços Executados".

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Alteração da query e agrupamento do Gráfico 1)
- [dashboard.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/dashboard.html) (Alteração de títulos e labels do Chart.js correspondente)

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar as outras métricas globais ou individuais do dashboard.
- NÃO deletar ou alterar a tabela `HistoricoPausa` (ela continua sendo essencial para o cálculo do MTTR).
- NÃO alterar a estrutura de tabelas do banco de dados.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Reutilizar a query principal de alocações do período para otimizar queries e evitar N+1.
- ✅ Manter a obediência ao filtro unificado de período (Data Inicial e Data Final).
- ✅ Tratamento de divisões por zero e fallbacks para períodos sem dados.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Filtro de Dados:** Considerar apenas instâncias de `Allocation` com `status='CONCLUIDO'` dentro do período selecionado (`data_inicio__date__range=[data_inicio, data_final]`).
2. **Agrupamento:** O agrupamento deve ser feito pelo campo `atividade_observacao` (que armazena a descrição da atividade do serviço executado).
3. **Cálculo da Duração (Eixo X):**
   - Para cada alocação concluída, calcular o tempo líquido de atendimento:
     - `Tempo Líquido = (data_fim - data_inicio) - soma(pausas)`.
   - Somar os tempos líquidos agrupados por descrição (`atividade_observacao`).
4. **Tratamento de Texto e Limitação:**
   - Normalizar textos (remover espaços extras nas pontas e padronizar maiúsculas/minúsculas se necessário) para evitar fragmentação excessiva.
   - Ordenar de forma decrescente pelo tempo total.
   - Limitar o resultado aos **Top 15** maiores serviços para evitar quebra de layout.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] O gráfico de Pareto exibe no Eixo Y os textos das observações das atividades dos serviços (`atividade_observacao`) em vez dos motivos de pausa.
- [ ] O Eixo X do Pareto exibe a duração líquida total acumulada em horas de forma decrescente.
- [ ] O título do card/gráfico foi atualizado para "Pareto de Serviços Executados".
- [ ] O filtro de período continua atualizando o gráfico normalmente.

---

## ⚠️ 9. RISCOS

- **Fragmentação de Textos Livres:** Se os técnicos digitarem descrições ligeiramente diferentes, o gráfico pode conter barras adicionais para o mesmo serviço. A ordenação decrescente e o limite de 15 resultados evitam poluição visual extrema.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. Mapear o processamento do gráfico 1 (Pareto) em `views.py`.
2. Alterar o loop ou a agregação para agrupar as alocações concluídas pelo campo `atividade_observacao`, somando o tempo líquido delas.
3. Ordenar a lista resultante por duração decrescente e aplicar o limite dos Top 15.
4. Passar os novos arrays JSON `pausa_labels` e `pausa_values` (ou correspondentes a serviços) para o context.
5. Atualizar o frontend (`dashboard.html`) para mudar o título e eixos do gráfico correspondente.

---

## 🧪 11. TESTES MANUAIS

1. Acessar `/dashboard/`.
2. Verificar se o primeiro gráfico exibe "Pareto de Serviços Executados" com as atividades no Eixo Y.
3. Testar a alteração do filtro unificado e atestar o recarregamento.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

- Arquivos lidos e alterados.
- Resumo e justificativas das alterações.
