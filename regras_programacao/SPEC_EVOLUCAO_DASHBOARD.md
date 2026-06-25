# 🧠 SPEC — EVOLUÇÃO DO DASHBOARD COM KPIs AVANÇADOS E FILTRO UNIFICADO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/dashboard/`
- **Contexto(s):** Dashboard de Gestão da Manutenção
- **Perfil(s) afetados:** Técnico Líder e Operador/Administrador

---

## ❗ 2. PROBLEMA ATUAL

- O dashboard atual possui métricas simples e instantâneas (total de técnicos, em atendimento, em pausa) que não representam indicadores industriais analíticos profundos.
- Dados ricos como múltiplas pausas, criticidade e tempos de atendimento já existem no banco de dados, mas não são processados para gerar inteligência sobre eficiência, gargalos reais de pausa e identificação de equipamentos ofensores (Bad Actors).
- Os cálculos devem respeitar rigorosamente o filtro unificado de período (Data Inicial e Data Final).

---

## 🎯 3. OBJETIVO

- Transformar a tela `/dashboard/` em uma central de inteligência analítica com os seguintes indicadores:
  1. **Índice de Eficiência Operacional (Card)**: Razão entre tempo líquido de atendimento e tempo bruto de atendimento no período (em %).
  2. **Taxa de Utilização da Equipe (Card)**: Proporção de horas líquidas trabalhadas versus capacidade estimada da equipe no período (em %).
- Preparar a estrutura de dados e injetá-los no HTML de forma segura (JSON) para renderizar os seguintes gráficos via Chart.js (respeitando o filtro unificado e excluindo dados de "projeto" e "fábrica"):
  1. **Pareto de Pausas (Gráfico 1)**: Motivos de pausa ordenados por duração total decrescente (em horas).
  2. **Top 5 Máquinas Ofensoras (Gráfico 2)**: Equipamentos com maior tempo bruto total acumulado de manutenção no período (em horas), excluindo registros de "projeto" e "fábrica".
  3. **Distribuição por Criticidade (Gráfico 3)**: Horas de manutenção gastas por criticidade de máquina (Rosca/Donut).
  4. **MTTR por Equipamento (Gráfico 4)**: Média do tempo líquido (em minutos) para o reparo das alocações concluídas de cada máquina, ordenados de forma decrescente, excluindo registros de "projeto" e "fábrica".

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Lógica de processamento e agregação dos KPIs e gráficos)
- [dashboard.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/dashboard.html) (Apresentação dos cards de KPI e inicialização dos gráficos Chart.js com os novos dados)

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar modelos ou tabelas do banco de dados (apenas leitura de `Allocation`, `HistoricoPausa` e `Machine`).
- NÃO alterar outras telas como `/management/`, `/tv/` ou CRUDs.
- NÃO alterar a rota de exportação para Excel (ela deve permanecer alinhada ao mesmo filtro unificado).

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ❌ Não duplicar código ou criar views paralelas.
- ❌ Não quebrar o filtro de período unificado existente.
- ✅ Validar permissões no backend (restrito a `Operadores` e `Tecnicos_Lideres`).
- ✅ Utilizar prefetch_related/select_related para consultas performáticas e evitar lentidão.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Filtro de Projetos e Fábrica:**
   - No cálculo de estatísticas por máquina (Tanto no Top 5 Máquinas Ofensoras quanto no MTTR por Equipamento), devem ser ignoradas as alocações vinculadas a máquinas cujos nomes contenham "projeto", "fabrica" ou "fábrica" (case-insensitive), pois tratam-se de projetos de melhorias e não indicam máquina parada de produção real.

2. **Índice de Eficiência Operacional (Card):**
   - Para todas as alocações iniciadas no período:
     - `Soma dos Tempos Líquidos / Soma dos Tempos Brutos * 100`
     - Para alocações não concluídas, o tempo bruto é considerado até `timezone.now()`, e a pausa sem data de retorno é considerada até `timezone.now()`.
   - Tratar divisão por zero.

3. **Taxa de Utilização da Equipe (Simplificada - Card):**
   - Proporção entre a soma das horas líquidas trabalhadas pela equipe no período e a capacidade estimada.
   - `Capacidade Estimada = dias_no_periodo * 8.0 * total_de_tecnicos` (horas).
   - `dias_no_periodo = (data_final - data_inicio).days + 1`.
   - `total_de_tecnicos = Technician.objects.count()`.
   - Tratar divisão por zero.

4. **Gráfico 1 (Pareto de Pausas):**
   - Filtrar registros de `HistoricoPausa` iniciados no período (`data_pausa__date__range=[data_inicio, data_final]`).
   - Somar a duração de cada pausa (em horas), agrupar por `motivo_pausa`, ordenar decrescente.

5. **Gráfico 2 (Top 5 Máquinas Ofensoras):**
   - Agrupar alocações do período por máquina (excluindo projetos/fábrica).
   - Somar o tempo bruto de manutenção (em horas) por máquina, ordenar decrescente, selecionar as top 5.

6. **Gráfico 3 (Distribuição por Criticidade):**
   - Somar o tempo bruto de manutenção (em horas) agrupando por `Machine.criticidade` (`BAIXA`, `MEDIA`, `ALTA`).

7. **Gráfico 4 (MTTR por Equipamento):**
   - Para cada máquina (excluindo projetos/fábrica), obter suas alocações com status `CONCLUIDO` no período:
     - `MTTR da Máquina = Média(Tempo Líquido de Atendimento em minutos)`.
     - `Tempo Líquido = (data_fim - data_inicio) - soma(pausas)`.
   - Ordenar as máquinas de forma decrescente pelo valor do MTTR. Exibir em gráfico de barras.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Os cards de KPI exibem valores reais do banco filtrados por data.
- [ ] Alteração de filtro recalculado instantaneamente.
- [ ] Tratamento elegante de períodos sem dados (exibição de `0` ou `N/A`, sem quebrar com divisão por zero).
- [ ] Dados estruturados injetados de forma segura como JSON no template.
- [ ] Layout responsivo e bonito dos gráficos Pareto, Top Máquinas e Rosca de Criticidade.

---

## ⚠️ 9. RISCOS

- **Divisão por Zero:** Lógica robusta na view para garantir tratamento quando o número de alocações ou técnicos for zero.
- **Performance:** Evitar consultas N+1 carregando as pausas, máquinas e técnicos com `prefetch_related` e `select_related`.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. Ler código da view `dashboard` e template `dashboard.html`.
2. Refatorar a query de alocações do período em `dashboard` para fazer prefetch das pausas e select_related de máquina/técnico.
3. Calcular MTTR Líquido, Eficiência Operacional, e Taxa de Utilização em Python.
4. Processar e agrupar dados para os três gráficos (Pareto, Top Máquinas, Rosca de Criticidade).
5. Injetar todas as variáveis no contexto e renderizar os cards e scripts dos gráficos no frontend.
6. Testar com dados reais e períodos vazios.

---

## 🧪 11. TESTES MANUAIS

1. Acessar `/dashboard/` com perfil permitido.
2. Filtrar período com dados, validar cálculos.
3. Filtrar período sem dados, validar exibição segura (zero / N/A).
4. Conferir responsividade da tela.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

- Arquivos lidos e alterados.
- Resumo e justificativas das alterações.
