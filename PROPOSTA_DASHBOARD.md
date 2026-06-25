# 🧠 CONSULTORIA DE DADOS — PROPOSTA DE INTELIGÊNCIA PARA O /DASHBOARD/

Este documento apresenta uma análise técnica e consultiva da base de dados atual do sistema de monitoramento de manutenção industrial, mapeando as informações disponíveis e propondo KPIs e gráficos analíticos que podem ser extraídos para apoiar a tomada de decisão gerencial.

---

## 📌 1. INVENTÁRIO DE DADOS (O QUE TEMOS HOJE)

Com base no mapeamento dos modelos em [models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py), dispomos de uma rica estrutura de dados relacionais que permite analisar a manutenção sob três principais perspectivas: **Técnicos (Mão de Obra)**, **Ativos (Máquinas e Setores)** e **Processos (Alocações e Pausas)**.

Abaixo está o detalhamento dos dados estruturados disponíveis para análise:

### A. Perspectiva dos Técnicos (`Technician` & `HistoricoEscala`)
*   **Status Atual:** Rastreamento em tempo real do estado de cada profissional (`OCIOSO`, `EM_ATENDIMENTO`, `EM_PAUSA`, `AUSENTE_FOLGA`, etc.).
*   **Histórico de Escala/Disponibilidade:** A tabela [HistoricoEscala](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py#L222-L259) audita e armazena todas as mudanças de disponibilidade promovidas pelos operadores, guardando o carimbo de data/hora (`data_alteracao`) e quem executou a mudança. Isso permite medir o tempo exato em que os técnicos estiveram ausentes por motivo de férias, folga, licença médica ou plantão externo.

### B. Perspectiva dos Ativos (`Machine` & `Sector`)
*   **Hierarquia Física:** Vinculação direta de máquinas a setores produtivos (`Sector`).
*   **Matriz de Criticidade:** Classificação dos equipamentos (`BAIXA`, `MEDIA`, `ALTA`). Essa segmentação é crucial para priorizar análises de impacto e eficiência de reparo.

### C. Perspectiva dos Processos (`Allocation` & `HistoricoPausa`)
*   **Rastreabilidade do Atendimento:** A tabela [Allocation](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py#L128-L200) registra o início (`data_inicio`) e o fim (`data_fim`) de cada manutenção, associando o técnico encarregado, a máquina afetada, o operador responsável e as observações textuais de abertura e encerramento.
*   **Histórico Granular de Pausas:** A tabela relacional [HistoricoPausa](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py#L201-L220) registra cada interrupção de um atendimento com data/hora de parada (`data_pausa`), data/hora de retorno (`data_retorno`) e o respectivo motivo textual (`motivo_pausa`). Isso possibilita expurgar o tempo em que o técnico ficou inativo (ex: aguardando peças) do cálculo de tempo de trabalho real da manutenção.

---

## 🎯 2. SUGESTÕES DE KPIs (CARDS DE DESTAQUE)

Abaixo estão 4 KPIs industriais de alto impacto para o Gestor de Manutenção que podem ser calculados **exclusivamente** com a estrutura de dados existente hoje:

### 1. MTTR (Mean Time to Repair / Tempo Médio de Atendimento Efetivo)
*   **O que mede:** O tempo médio gasto pela equipe para efetivamente diagnosticar e reparar uma falha.
*   **Como calcular:** Filtrando alocações concluídas (`status='CONCLUIDO'`), somamos o tempo total decorrido (`data_fim - data_inicio`) e subtraímos o somatório de todos os tempos de pausa associados àquela alocação (`data_retorno - data_pausa`). Dividimos esse tempo líquido de trabalho pelo número de alocações concluídas.
*   **Fórmula:**
    $$\text{Tempo Líquido} = (\text{data\_fim} - \text{data\_inicio}) - \sum (\text{data\_retorno} - \text{data\_pausa})$$
    $$\text{MTTR} = \frac{\sum \text{Tempo Líquido}}{\text{Total de Alocações Concluídas}}$$
*   **Por que o chefe quer ver:** É a métrica padrão-ouro de eficiência de execução. Um MTTR alto ou crescente aponta para gargalos técnicos, necessidade de treinamentos ou problemas de complexidade dos equipamentos.

### 2. Taxa de Utilização da Equipe (Ocupação Eficiente)
*   **O que mede:** O percentual de tempo em que a força de trabalho ativa esteve de fato alocada em atendimentos no chão de fábrica, em contraste com períodos ociosos.
*   **Como calcular:** A partir das horas de trabalho disponíveis (calculadas descontando-se os tempos de ausência registrados no `HistoricoEscala`), divide-se a soma de todas as horas em que os técnicos estiveram com status `EM_ATENDIMENTO` pelas horas de plantão/presença total.
*   **Fórmula:**
    $$\text{Taxa de Utilização} = \frac{\sum \text{Tempo Líquido em Atendimento}}{\text{Tempo Total de Disponibilidade na Fábrica}} \times 100$$
*   **Por que o chefe quer ver:** Ajuda a dimensionar o tamanho da equipe (headcount). Revela se há subutilização da mão de obra (excesso de técnicos) ou sobrecarga (equipe constantemente em 100% de alocação, gerando filas de espera).

### 3. Índice de Eficiência Operacional (Tempo de Pausa vs. Atendimento)
*   **O que mede:** A proporção de tempo gasto resolvendo o problema versus o tempo em que a atividade ficou paralisada (aguardando peças, autorização, etc.).
*   **Como calcular:**
    $$\text{Eficiência} = \frac{\sum \text{Tempo Líquido em Atendimento}}{\sum (\text{data\_fim} - \text{data\_inicio})} \times 100$$
*   **Por que o chefe quer ver:** Mede o nível de desperdício burocrático ou logístico. Se esse indicador estiver baixo, significa que o técnico passa mais tempo esperando processos de apoio (peças, ferramentas, liberação de segurança) do que de fato consertando a máquina.

### 4. Backlog de Manutenção Industrial (Atendimentos Pendentes / Pausados)
*   **O que mede:** A carga de trabalho pendente acumulada em tempo real.
*   **Como calcular:** Contagem absoluta de registros na tabela `Allocation` onde `status = 'EM_PAUSA'` ou `data_fim` é nulo.
*   **Por que o chefe quer ver:** Funciona como um termômetro de gargalo instantâneo na fábrica, indicando se a demanda de quebras está superando a capacidade de atendimento imediato da equipe.

---

## 📊 3. SUGESTÕES DE GRÁFICOS INTELIGENTES

Para ilustrar e apoiar a gestão visual rápida, propomos 3 layouts de gráficos interativos para a nova tela de Dashboard:

```mermaid
graph TD
    A[Dashboard de Gestão] --> B[Gráfico 1: Pareto de Indisponibilidade por Motivo de Pausa]
    A --> C[Gráfico 2: Top 5 Máquinas "Ofensoras" de Carga de Manutenção]
    A --> D[Gráfico 3: Histórico de Distribuição de Carga Horária por Criticidade]
```

### Gráfico 1: Pareto de Indisponibilidade por Motivo de Pausa
*   **Tipo de Gráfico:** Barras Horizontais (ordenadas do maior para o menor) ou Gráfico de Pareto.
*   **Eixo X:** Somatório de Horas em Pausa.
*   **Eixo Y:** Motivos de Pausa (extraídos do agrupamento de `HistoricoPausa.motivo_pausa`).
*   **Por que é útil:** Permite aplicar o Princípio de Pareto (80/20). O gestor visualiza de imediato quais motivos de interrupção (ex: "Falta de Peça Sobressalente", "Aguardando Operador de Produção para teste", "Falta de Ferramental Específico") são responsáveis pela maior fatia de atraso nos atendimentos, permitindo ações corretivas focadas nos maiores gargalos.

### Gráfico 2: Top 5 Máquinas "Ofensoras" de Carga de Manutenção
*   **Tipo de Gráfico:** Barras Verticais.
*   **Eixo X:** Nome da Máquina (`Machine.nome`).
*   **Eixo Y:** Número de Alocações (Volume de falhas) e Tempo Total Acumulado (Duração total).
*   **Por que é útil:** Identifica os equipamentos mais problemáticos (chamados de *Bad Actors*). O gestor pode identificar se um ativo está quebrando em excesso e requer uma substituição completa (CAPEX) ou uma revisão profunda no seu plano de manutenção preventiva.

### Gráfico 3: Histórico de Distribuição de Carga Horária por Criticidade
*   **Tipo de Gráfico:** Linhas com preenchimento (Áreas Empilhadas), agrupado semanalmente ou mensalmente.
*   **Eixo X:** Linha do tempo (Semanas do período filtrado).
*   **Eixo Y:** Horas líquidas totais despendidas em manutenção.
*   **Séries (Cores):** Criticidade da Máquina (`BAIXA`, `MEDIA`, `ALTA`).
*   **Por que é útil:** Mostra a evolução qualitativa da manutenção. Se o volume de horas gastas em máquinas de criticidade **ALTA (Vermelha)** estiver reduzindo ao longo das semanas, significa que a planta está se tornando mais estável e previsível. Aumento súbito de horas em criticidade ALTA sinaliza risco iminente de perda de produção e necessidade de intervenção urgente de engenharia de confiabilidade.

---

## 🔬 4. ANÁLISE DE VIABILIDADE E PRÓXIMOS PASSOS (ESTRUTURA DE BANCO DE DADOS)

Abaixo avaliamos o que é viável calcular imediatamente, o que **não** é viável sob as premissas atuais, e sugerimos melhorias de modelagem para o futuro.

### ✅ O que é 100% Viável com os dados atuais:
1.  **MTTR Geral, por Setor, por Máquina ou por Técnico:** Todas as relações e carimbos de data/hora necessários já existem nas tabelas `Allocation` e `HistoricoPausa`.
2.  **Pareto de Motivos de Pausa:** O modelo `HistoricoPausa` armazena de forma consistente o par (data/hora, motivo), viabilizando plenamente esse cruzamento.
3.  **Matriz de Criticidade:** O campo `Machine.criticidade` permite segmentar qualquer indicador temporal.
4.  **MTBF Aproximado (Mean Time Between Failures):**
    *   *Como:* É possível calcular o tempo médio decorrido entre o término de uma alocação (`data_fim`) e o início da próxima alocação (`data_inicio`) na **mesma máquina**.
    *   *Premissa:* Isso assume o tempo corrido de calendário como tempo de operação da máquina.

### ⚠️ O que NÃO é possível calcular hoje (Limitações de Dados):
1.  **OEE (Overall Equipment Effectiveness / Eficiência Global do Equipamento):**
    *   *Motivo:* O OEE exige três pilares: **Disponibilidade** (tempo operando / tempo planejado), **Performance** (produção real / produção nominal) e **Qualidade** (peças boas / total produzido). A nossa base de dados atual armazena apenas dados de paradas de manutenção, não possuindo registros de produção, refugo ou velocidade nominal de produção das máquinas.
2.  **MTBF Exato (Confiabilidade Pura):**
    *   *Motivo:* Para calcular o MTBF de forma exata, precisaríamos saber o tempo real em que a máquina esteve ligada e produzindo (horas de marcha). Se a máquina ficou desligada por falta de programação de produção, esse período não deveria contar como "tempo sem falhas". Sem dados de telemetria ou integração com sistema produtivo (MES), o cálculo de MTBF será sempre uma estimativa baseada em tempo de calendário.
3.  **Custos de Manutenção (R$ / Hora-Homem e Peças):**
    *   *Motivo:* O sistema não possui cadastro de taxas horárias dos técnicos nem controle/custo de peças sobressalentes aplicadas.

### 💡 Recomendações de Evolução de Modelagem (Roadmap Futuro):
Se o gestor desejar elevar a inteligência do dashboard para um nível de Gestão de Custos e Confiabilidade Avançada, sugerimos as seguintes implementações futuras:

1.  **Campo `tipo_manutencao` na `Allocation`:**
    *   Adicionar uma escolha (*Choice*) entre: `CORRETIVA` (quebra-conserta), `PREVENTIVA` (inspeção programada) e `PREDITIVA/MELHORIA`. Isso permitirá calcular a relação Preventiva/Corretiva da fábrica.
2.  **Modelo de Peças Utilizadas (`AllocationSparePart`):**
    *   Criar uma tabela associativa para registrar quais peças foram substituídas em cada alocação e o custo unitário delas, gerando um KPI de **Custo Total de Manutenção**.
3.  **Campo `duracao_estimada` ou `tempo_padrao` na `Machine`:**
    *   Cadastrar o tempo estimado padrão para intervenções em cada máquina para gerar o indicador de **Aderência ao Cronograma de Manutenção** (planejado vs. realizado).
