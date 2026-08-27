# 🧠 SPEC — HISTÓRICO DA CALANDRA E AUDITORIA DE PROCESSO E QUALIDADE

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/` (Dashboard de Produção — Card "Relatórios de Máquinas" na home pós-login)
  - `/producao/relatorios/` (Central de Relatórios de Máquinas — Catálogo de relatórios com card da Calandra)
  - `/producao/relatorios/calandra/` (Relatório de Auditoria da Calandra — Filtros, 4 Cards de Processo Efetivo, 6 Gráficos de Linha, Janela de Análise Coordenada e Tabela Sincronizada)
  - `/producao/relatorios/calandra/exportar-excel/` (Exportação do Histórico Sincronizado do filtro principal em `.xlsx`)
- **Contexto(s):** Módulo de Produção Industrial / Auditoria de Processo e Qualidade do Material Emborrachado / Integração SCADA-LTS Somente-Leitura.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Operadores (`Operadores`, `Operador`), PCP (`PCP`), Superusuários e Staff. Manutenção e TV são bloqueados.
- **Predecessoras:** 
  - `SPEC_FUNDACAO_PRODUCAO.md`
  - `SPEC_PRODUCAO_04_INTEGRACAO_SCADA_E_PAINEL.md`
  - `SPEC_CENTRAL_CONFIGURACAO_SCADA_XIDS.md`
  - `SPEC_HISTORICO_CALANDRA_RELATORIOS.md` (v1 inicial)

---

## ❗ 2. PROBLEMA ATUAL & OBJETIVO DA EVOLUÇÃO

### 2.1. Problema Atual
1. A tela `/producao/relatorios/calandra/` já consulta os 20 XIDs e possui forward-fill temporal, porém exibia cards eminentemente técnicos (Pontos Brutos, Linhas Sincronizadas, Variáveis Encontradas), sem foco em auditoria do processo produtivo.
2. Gráficos de temperaturas misturavam variáveis de cilindros e auxiliares (6 séries no mesmo gráfico), sobrecarregando a visualização.
3. Não havia segregação entre períodos de parada e produção efetiva, o que distorcia médias térmicas e mecânicas caso calculadas sobre o tempo total.
4. Faltava ferramenta de **Janela em Análise** coordenada, permitindo selecionar um trecho temporal em qualquer gráfico e recalcular instantaneamente os cards e atualizar todos os gráficos sincronizados.

### 2.2. Objetivo da Evolução
Evoluir a tela de uma visualização técnica para uma **ferramenta de auditoria das condições de processo e qualidade do material emborrachado**, respondendo a:
- Em quais condições térmicas o material foi processado?
- Quais cargas estavam sendo aplicadas durante o processo?
- Qual era o comportamento do processo durante PASSADA 1 (1ª face) e PASSADA 2 (2ª face / face oposta)?
- O que aconteceu exatamente durante um trecho específico selecionado?

---

## 📋 3. INVENTÁRIO DAS 20 VARIÁVEIS DA CALANDRA

| # | Grupo de Auditoria | Nome Amigável (pt-br) | Tag / XID SCADA | Unidade | Tipo SCADA | Destino Principal |
| :-: | :--- | :--- | :--- | :---: | :-: | :--- |
| 1 | Produção / Contexto | `Passada` | `CALANDRA_meta - PASSADA` | — | Multistate | Contexto / Tooltip / Faixas |
| 2 | Produção / Contexto | `Metragem Bobinada` | `CALANDRA - METRAGEM_BOBINADA` | m | Numeric | Gráfico 1 & Regra Processo |
| 3 | Produção / Contexto | `Velocidade da Calandra` | `CALANDRA - VEL_CALANDRA (m/min)` | m/min | Numeric | Gráfico 1 & Regra Processo |
| 4 | Cargas do Processo | `Carga Bobinamento` | `CALANDRA - CARGA_BOBINAMENTO (Kg)` | kg | Numeric | Card 3 & Gráfico 2 |
| 5 | Cargas do Processo | `Carga Desbobinador` | `CALANDRA - CARGA_DESBOBINADOR (Kg)` | kg | Numeric | Card 3 & Gráfico 2 |
| 6 | Cargas do Processo | `Carga Pós-Calandra` | `CALANDRA - CARGA_POS-CALANDRA (Kg)` | kg | Numeric | Card 3 & Gráfico 2 |
| 7 | Cargas do Processo | `Carga Quebra-Trama` | `CALANDRA - CARGA_QUEBRA-TRAMA (Kg)` | kg | Numeric | Card 3 & Gráfico 2 |
| 8 | Espessuras | `Espessura Esq. Superior` | `CALANDRA - ESPESSURA_LADO ESQ SUPERIOR` | mm | Numeric | Gráfico 3 & Tabela/Excel |
| 9 | Espessuras | `Espessura Dir. Superior` | `CALANDRA - ESPESSURA_LADO DIR SUPERIOR` | mm | Numeric | Gráfico 3 & Tabela/Excel |
| 10 | Espessuras | `Espessura Dir. Inferior` | `CALANDRA - ESPESSURA_LADO DIR INFERIOR` | mm | Numeric | Gráfico 3 & Tabela/Excel |
| 11 | Espessuras | `Espessura Esq. Inferior` | `CALANDRA - ESPESSURA_LADO ESQ INFERIOR` | mm | Numeric | Gráfico 3 & Tabela/Excel |
| 12 | Temp. Borracha | `Temp. Borracha Saída Extrusão` | `CALANDRA - TEMPERATURA_BORRACHA_SAIDA_EXTRUSAO (°C)` | °C | Numeric | Card 1 & Gráfico 4 |
| 13 | Temp. Borracha | `Temp. Borracha Entrada Calandra` | `CALANDRA - TEMPERATURA_BORRACHA_ENT_CALANDRA (°C)` | °C | Numeric | Card 1 & Gráfico 4 |
| 14 | Temp. Borracha | `Temp. Borracha Saída Calandra` | `CALANDRA - TEMPERATURA_BORRACHA_SAIDA_CALANDRA (°C)` | °C | Numeric | Card 1 & Gráfico 4 |
| 15 | Temp. Cilindros | `Temp. Cilindro Inferior` | `CALANDRA_TEMPERATURA - CILINDRO_INFERIOR (°C)` | °C | Numeric | Card 2 & Gráfico 5 |
| 16 | Temp. Cilindros | `Temp. Cilindro Intermediário` | `CALANDRA_TEMPERATURA - CILINDRO_INTERMEDIÁRIO (°C)` | °C | Numeric | Card 2 & Gráfico 5 |
| 17 | Temp. Cilindros | `Temp. Cilindro Superior` | `CALANDRA_TEMPERATURA - CILINDRO_SUPERIOR (°C)` | °C | Numeric | Card 2 & Gráfico 5 |
| 18 | Temp. Auxiliares | `Temp. Furador` | `CALANDRA_TEMPERATURA - FURADOR (°C)` | °C | Numeric | Card 4 & Gráfico 6 |
| 19 | Temp. Auxiliares | `Temp. Aquecedor` | `CALANDRA_TEMPERATURA - AQUECEDOR` | °C | Numeric | Card 4 & Gráfico 6 |
| 20 | Temp. Auxiliares | `Temp. TCU Extrusora` | `CALANDRA_TEMPERATURA - TCU_EXTRUSORA (°C)` | °C | Numeric | Card 4 & Gráfico 6 |

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Modificados:
- `production/services_calandra.py`:
  - Implementação da regra matemática de **Processo Efetivo** (`detect_effective_process`, `compute_effective_process_stats`).
  - Atualização da separação dos datasets dos gráficos em 6 grupos (Cilindros e Auxiliares segregados).
  - Preservação intacta da exportação Excel `.xlsx` e da consulta histórica segura forward-fill.
- `production/views.py`:
  - Cálculo das estatísticas iniciais dos 4 cards de processo efetivo no backend e envio ao template no contexto.
  - Envio dos dados enriquecidos da timeline com flag `is_effective` para suporte à seleção coordenada no frontend.
- `production/templates/production/calandra_report.html`:
  - 4 Cards Principais de Processo Efetivo (Temperatura Borracha, Temperatura Cilindros, Cargas, Temperaturas Auxiliares).
  - Banner informativo: "Período consultado: X → Y" | "Estatísticas dos cards: Somente períodos com processo efetivo".
  - Seção "Janela em análise" com exibição do intervalo e botão `[ Limpar seleção ]`.
  - Contexto semântico de Passada: `PASSADA 1 — 1ª face`, `PASSADA 2 — 2ª face / face oposta` ou `PASSADA 1 e PASSADA 2`.
  - 6 Gráficos de Linha (Produção, Cargas, Espessuras, Temp. Borracha, Temp. Cilindros, Temp. Auxiliares).
  - Seleção temporal coordenada com Chart.js: seleção em qualquer gráfico atualiza os 6 gráficos, recalcula cards instantaneamente em memória (zero consultas ao SCADA) e atualiza contexto de passada.
  - Hover sincronizado / tooltips enriquecidos com Data/Hora, Passada e valores do gráfico.
  - Seção de Informações Técnicas recolhida em `<details>` com os indicadores de diagnóstico.
- `production/test_calandra_report.py`:
  - Testes unitários para cálculo de médias, mínimos e máximos dos cards.
  - Testes dos 6 casos de processo efetivo (combinações de velocidade e incremento de metragem, paradas, resets e flutuações).
  - Testes de seleção temporal, Passadas 1 e 2, 6 gráficos, Excel e garantia estrita de banco read-only.
- `Instrucoes.txt`:
  - Registro resumido da entrega.

---

## 🚫 5. FORA DE ESCOPO & REGRAS PROIBIDAS

- ❌ **SCADA SOMENTE LEITURA:** NENHUM `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE` ou migração no banco `scada`.
- ❌ **SEM TOLERÂNCIAS OU JULGAMENTO:** Proibido adicionar limites mín/máx aceitáveis, aprovação/reprovação, cor vermelha por desvio ou alarmes de qualidade automáticos.
- ❌ **SEM ESPESSURA NOS CARDS:** Espessuras permanecem restritas a gráfico, tabela e Excel (sem compor cards principais).
- ❌ **SEM CONSULTAS PESADAS NO ZOOM:** A seleção temporal interativa no frontend opera exclusivamente sobre a timeline já carregada na memória do navegador.
- ❌ **SEM MÚLTIPLOS APPS OU .VENV:** Manter ambiente único e monólito Django existente.

---

## ⚙️ 6. REGRAS DE NEGÓCIO E ALGORITMOS

### 6.1. Regra de Processo Efetivo (Velocidade + Incremento de Metragem)
Para cada ponto $k$ da timeline temporal com velocidade $v_k$ e metragem $m_k$:
1. **Condição de Movimento:** $v_k$ deve ser numérico e estritamente superior a zero ($v_k > 0.05\text{ m/min}$ para eliminar ruídos de sensor analógico). Se $v_k \le 0.05$ ou for nulo $\rightarrow$ `is_effective = False`.
2. **Condição de Incremento de Metragem:**
   - Compara-se $m_k$ com a metragem anterior $m_{k-1}$ e posterior $m_{k+1}$ no contexto da janela:
     - Se $\Delta m = m_k - m_{k-1} > 0$: Metragem em avanço contínuo $\rightarrow$ `is_effective = True`.
     - Se $\Delta m < 0$: Reset de metragem (ex: troca de rolo bobinado) $\rightarrow$ Se $v_k > 0$ e o ponto seguinte apresentar avanço ($m_{k+1} \ge m_k$), o ponto de reset é considerado parte da produção contínua $\rightarrow$ `is_effective = True`.
     - Se $\Delta m == 0$: Verifica-se se o ponto pertence a uma sequência ativa de produção (onde há avanço em $m_{k+1} > m_k$ ou $m_k > m_{k-2}$). Caso a metragem permaneça completamente estagnada em todo o intervalo contíguo com velocidade positiva (teste em vazio ou sensor desconectado), o ponto é marcado como `is_effective = False`.
3. **Isolamento de Paradas:** Todos os pontos com máquina parada ($v \le 0$) ou sem avanço real de metragem são marcados com `is_effective = False`.

### 6.2. Estatísticas dos Cards de Auditoria
- Para cada variável $X$, a média ($\bar{X}$), mínimo ($X_{\min}$) e máximo ($X_{\max}$) são calculados exclusivamente sobre o subconjunto de pontos da janela ativa onde `is_effective == True` e $X$ possui valor numérico válido:
  $$\bar{X} = \frac{1}{N_{\text{efetivo}}} \sum_{i \in \text{Efetivos}} X_i, \quad X_{\min} = \min_{i \in \text{Efetivos}} (X_i), \quad X_{\max} = \max_{i \in \text{Efetivos}} (X_i)$$
- **Caso sem processo efetivo no intervalo:**
  - Se $N_{\text{efetivo}} == 0$: os cards exibem o status informativo *"Sem dados de produção efetiva neste intervalo"*, sem divisão por zero e sem exibir números enganosos de máquina parada.
- **Card 2 (Cilindros) - Diferença Térmica Informativa:**
  - Exibe $\Delta \text{ Cilindros} = \max(\bar{T}_{\text{inf}}, \bar{T}_{\text{inter}}, \bar{T}_{\text{sup}}) - \min(\bar{T}_{\text{inf}}, \bar{T}_{\text{inter}}, \bar{T}_{\text{sup}})$, de forma puramente descritiva.

### 6.3. Organização dos 6 Gráficos de Linha
1. **Gráfico 1 — Produção:** Velocidade da Calandra (m/min) + Metragem Bobinada (m) (eixos Y duplos) + Destaque de Passada.
2. **Gráfico 2 — Cargas do Processo:** Desbobinador, Quebra-Trama, Pós-Calandra, Bobinamento (kg).
3. **Gráfico 3 — Espessuras:** Esq. Superior, Dir. Superior, Esq. Inferior, Dir. Inferior (mm).
4. **Gráfico 4 — Temperatura da Borracha:** Saída Extrusão, Entrada Calandra, Saída Calandra (°C).
5. **Gráfico 5 — Temperatura dos Cilindros:** Cilindro Inferior, Cilindro Intermediário, Cilindro Superior (°C).
6. **Gráfico 6 — Temperaturas Auxiliares:** Furador, Aquecedor, TCU Extrusora (°C).

### 6.4. Janela de Análise & Seleção Coordenada
- Ao selecionar uma região temporal $[t_{\text{start}}, t_{\text{end}}]$ em qualquer um dos 6 gráficos:
  - Os 6 gráficos ajustam seus eixos X para $[t_{\text{start}}, t_{\text{end}}]$.
  - Os 4 cards são recalculados dinamicamente no frontend sobre os pontos no intervalo com `is_effective = True`.
  - O indicador de Passada identifica:
    - Somente Passada 1 $\rightarrow$ `PASSADA 1 — 1ª face`
    - Somente Passada 2 $\rightarrow$ `PASSADA 2 — 2ª face / face oposta`
    - Ambas $\rightarrow$ `Passadas presentes: PASSADA 1 e PASSADA 2`
  - Exibe o badge `"Janela em análise: HH:MM:SS → HH:MM:SS"` com botão `[ Limpar seleção ]`.
- Ao clicar em `[ Limpar seleção ]`:
  - Gráficos e cards retornam ao período completo do filtro principal.

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO & TESTES

- [ ] 4 novos cards principais de auditoria implementados: Temp. Borracha, Temp. Cilindros, Cargas, Temp. Auxiliares.
- [ ] Cards calculados exclusivamente sobre pontos de **processo efetivo**.
- [ ] Regra de processo efetivo valida velocidade $>0$ combinada com incremento de metragem.
- [ ] Tratamento seguro de intervalos sem processo efetivo (sem divisão por zero, exibindo mensagem clara).
- [ ] 6 gráficos de linha temporais renderizam com clareza (Cilindros e Auxiliares separados).
- [ ] Seleção temporal coordenada em qualquer gráfico sincroniza os 6 gráficos, recalcula cards e atualiza contexto de Passada.
- [ ] Botão `[ Limpar seleção ]` restaura a visualização integral sem nova consulta ao SCADA.
- [ ] Contexto semântico de Passada utiliza rótulos `PASSADA 1 — 1ª face` e `PASSADA 2 — 2ª face / face oposta`.
- [ ] Informações técnicas (pontos brutos, linhas sincronizadas, variáveis) alocadas em seção recolhida discreta.
- [ ] Espessuras preservadas em gráfico, tabela e Excel sem participar de cards ou tolerâncias.
- [ ] Exportação Excel (.xlsx) mantém integridade e vinculação ao filtro principal.
- [ ] Banco `scada` estritamente somente-leitura.
- [ ] Suíte de testes automatizados passa com 100% de cobertura nos cenários descritos.
