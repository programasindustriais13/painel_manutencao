# 🧠 SPEC — GRÁFICO DE DESEMPENHO INDIVIDUAL POR TÉCNICO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/dashboard/`
- **Contexto(s):** Dashboard de Gestão da Manutenção
- **Perfil(s) afetados:** Técnico Líder e Operador/Administrador

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, o dashboard exibe métricas globais da fábrica e da criticidade dos equipamentos.
- O gestor não tem visibilidade sobre a produtividade individual de cada técnico (quantidade de atendimentos realizados e tempo médio líquido de atendimento - MTTR).
- É necessário um indicador visual que cruze o volume de serviços concluídos com o MTTR de cada técnico no período para melhor avaliação de desempenho e carga de trabalho.

---

## 🎯 3. OBJETIVO

- Criar um novo gráfico combinado (Mixed Chart) no `/dashboard/` focado no **Desempenho por Técnico**.
- O gráfico deve cruzar:
  - **Volume de Atendimentos Concluídos** (Eixo Y Principal, representado por Barras).
  - **MTTR Individual em minutos** (Eixo Y Secundário, representado por uma Linha).
- Todos os cálculos devem respeitar rigorosamente o período do filtro unificado e descontar os períodos de pausa das alocações.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Agrupamento e cálculo por técnico no backend)
- [dashboard.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/dashboard.html) (Adição de canvas para o novo gráfico e configuração do Chart.js)

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar modelos ou banco de dados.
- NÃO alterar as métricas globais de eficiência operacionais ou de criticidade já existentes.
- NÃO alterar outras telas além do dashboard analítico `/dashboard/`.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ❌ Não duplicar código ou criar views paralelas.
- ❌ Não quebrar o filtro de período unificado.
- ✅ Validar permissões no backend (decorators existentes).
- ✅ Utilizar prefetch das pausas para evitar consultas N+1.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Filtro de Período:** Considerar somente alocações com `status='CONCLUIDO'` e com `data_inicio__date__range=[data_inicio, data_final]`.
2. **Agrupamento:** Agrupar resultados por técnico (`tecnico__nome`).
3. **Cálculo de Volume:** Quantidade total de alocações concluídas por técnico no período.
4. **Cálculo de MTTR Líquido Individual:**
   - Para cada técnico, somar o tempo líquido de suas alocações concluídas no período:
     - `Tempo Líquido = (data_fim - data_inicio) - soma(pausas da alocação)`.
     - `MTTR Individual (minutos) = tempo_liquido_total_do_tecnico / quantidade_concluidas_do_tecnico`.
   - Se `quantidade_concluidas` for 0, o MTTR do técnico é 0.
5. **Estrutura para o Gráfico (Mixed Chart):**
   - Eixo X: Nomes dos Técnicos.
   - Barras (Volume): Quantidade de alocações concluídas.
   - Linha (MTTR): MTTR médio do técnico (em minutos).
6. **Ordenação:** Ordenar do técnico que mais concluiu alocações para o que menos concluiu.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] O novo gráfico "Desempenho por Técnico" aparece no dashboard com o layout correto.
- [ ] O gráfico responde corretamente e instantaneamente a mudanças no filtro de datas.
- [ ] O cálculo de MTTR desconta os tempos de pausa das alocações.
- [ ] Períodos sem alocações concluídas são tratados sem erros de divisão por zero.
- [ ] Visualização responsiva para equipes com muitos técnicos.

---

## ⚠️ 9. RISCOS

- **Divisão por Zero:** Tratado no backend com verificação preventiva de quantidade.
- **Poluição do Eixo X:** Gráfico com altura adequada para exibir nomes dos técnicos de forma legível.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. Mapear onde são gerados os dados dos gráficos em `maintenance/views.py`.
2. Adicionar o agrupamento e ordenação por técnico para obter a quantidade de alocações concluídas e o MTTR individual no período filtrado.
3. Passar os arrays `tech_desempenho_labels`, `tech_desempenho_volumes` e `tech_desempenho_mttrs` serializados em JSON para o template.
4. Inserir o contêiner do novo gráfico em `dashboard.html`.
5. Configurar o Chart.js com tipo `bar` e dataset de linha secundário (`type: 'line'`) com eixos Y independentes (`yAxes`).
6. Executar testes de integridade.

---

## 🧪 11. TESTES MANUAIS

1. Acessar `/dashboard/`.
2. Alterar o filtro unificado de datas e verificar o comportamento do gráfico por técnico.
3. Forçar um período sem dados e atestar o carregamento correto sem erros.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

- Arquivos lidos e alterados.
- Resumo e justificativas das alterações.
