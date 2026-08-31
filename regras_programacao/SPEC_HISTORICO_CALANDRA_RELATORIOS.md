# 🧠 SPEC — HISTÓRICO DA CALANDRA E AUDITORIA DE PROCESSO E QUALIDADE (21 VARIÁVEIS & GRÁFICOS LIMPOS)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/` (Dashboard de Produção — Card "Relatórios de Máquinas" na home pós-login)
  - `/producao/relatorios/` (Central de Relatórios de Máquinas — Catálogo de relatórios com card da Calandra)
  - `/producao/relatorios/calandra/` (Relatório de Auditoria da Calandra — Filtros, 4 Cards de Processo Efetivo, 6 Gráficos de Linha Limpos, Janela de Análise Coordenada e Tabela Sincronizada)
  - `/producao/relatorios/calandra/exportar-excel/` (Exportação do Histórico Sincronizado do filtro principal em `.xlsx`)
  - `/producao/configuracao-scada/calandra/` (Central de Configuração de XIDs da Calandra para Superusuários)
- **Contexto(s):** Módulo de Produção Industrial / Auditoria de Processo e Qualidade do Material Emborrachado / Integração SCADA-LTS Somente-Leitura.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Operadores (`Operadores`, `Operador`), PCP (`PCP`), Superusuários e Staff. Manutenção e TV são bloqueados.
- **Predecessoras:** 
  - `SPEC_FUNDACAO_PRODUCAO.md`
  - `SPEC_PRODUCAO_04_INTEGRACAO_SCADA_E_PAINEL.md`
  - `SPEC_CENTRAL_CONFIGURACAO_SCADA_XIDS.md`
  - `SPEC_HISTORICO_CALANDRA_RELATORIOS.md` (v1/v2)

---

## ❗ 2. PROBLEMA ATUAL & OBJETIVO DA EVOLUÇÃO

### 2.1. Problema Atual
1. A Calandra monitora atualmente 20 variáveis, mas a variável térmica de utilidade crítica **`CALANDRA_TEMPERATURA - GELADEIRA (ºC)`** ainda não estava integrada ao conjunto de telemetria histórica.
2. A nova variável `Geladeira` precisa ser incorporada em toda a cadeia: Card de Temperaturas Auxiliares, Gráfico 6 (Temperaturas Auxiliares), Tabela Sincronizada e Exportação Excel.
3. Os gráficos temporais atuais renderizam círculos/marcadores (`points`) em todos os registros da timeline, gerando poluição visual em períodos com centenas ou milhares de leituras.
4. É necessário manter o comportamento interativo de hover/tooltip com realce pontual apenas sob o cursor do usuário.

### 2.2. Objetivo da Evolução
1. **Adicionar a 21ª variável:** `CALANDRA_TEMPERATURA - GELADEIRA (ºC)` (Tipo 3 / Numeric, Unidade °C, Grupo Temperaturas Auxiliares).
2. **Visual Limpo nos Gráficos:** Configurar o Chart.js para desenhar linhas contínuas e fluidas sem pontos/bolinhas em massa (`pointRadius: 0`, `pointHoverRadius: 5`, `hitRadius: 8`), mantendo tooltips, crosshair e hover sincronizado.
3. **Preservar a Lógica Funcional Aprovada:**
   - 4 Cards de Auditoria calculados exclusivamente sobre pontos de **Processo Efetivo** ($v > 0.05\text{ m/min}$ com avanço de metragem).
   - Janela de análise com seleção temporal coordenada no cliente (zero chamadas adicionais ao SCADA).
   - Tabela histórica sincronizada e exportação Excel horizontal estruturada.
   - Banco `scada` estritamente **Somente Leitura**.

---

## 📋 3. INVENTÁRIO DAS 21 VARIÁVEIS DA CALANDRA

| # | Grupo de Auditoria | Nome Amigável (pt-br) | Tag / XID SCADA | Unidade | Tipo SCADA | Destino Principal |
| :-: | :--- | :--- | :--- | :---: | :-: | :--- |
| 1 | Produção / Contexto | `Passada` | `CALANDRA_meta - PASSADA` | — | Multistate (2) | Contexto / Tooltip / Faixas |
| 2 | Produção / Contexto | `Metragem Bobinada` | `CALANDRA - METRAGEM_BOBINADA` | m | Numeric (3) | Gráfico 1 & Regra Processo |
| 3 | Produção / Contexto | `Velocidade da Calandra` | `CALANDRA - VEL_CALANDRA (m/min)` | m/min | Numeric (3) | Gráfico 1 & Regra Processo |
| 4 | Cargas do Processo | `Carga Bobinamento` | `CALANDRA - CARGA_BOBINAMENTO (Kg)` | kg | Numeric (3) | Card 3 & Gráfico 2 |
| 5 | Cargas do Processo | `Carga Desbobinador` | `CALANDRA - CARGA_DESBOBINADOR (Kg)` | kg | Numeric (3) | Card 3 & Gráfico 2 |
| 6 | Cargas do Processo | `Carga Pós-Calandra` | `CALANDRA - CARGA_POS-CALANDRA (Kg)` | kg | Numeric (3) | Card 3 & Gráfico 2 |
| 7 | Cargas do Processo | `Carga Quebra-Trama` | `CALANDRA - CARGA_QUEBRA-TRAMA (Kg)` | kg | Numeric (3) | Card 3 & Gráfico 2 |
| 8 | Espessuras | `Espessura Esq. Superior` | `CALANDRA - ESPESSURA_LADO ESQ SUPERIOR` | mm | Numeric (3) | Gráfico 3 & Tabela/Excel |
| 9 | Espessuras | `Espessura Dir. Superior` | `CALANDRA - ESPESSURA_LADO DIR SUPERIOR` | mm | Numeric (3) | Gráfico 3 & Tabela/Excel |
| 10 | Espessuras | `Espessura Dir. Inferior` | `CALANDRA - ESPESSURA_LADO DIR INFERIOR` | mm | Numeric (3) | Gráfico 3 & Tabela/Excel |
| 11 | Espessuras | `Espessura Esq. Inferior` | `CALANDRA - ESPESSURA_LADO ESQ INFERIOR` | mm | Numeric (3) | Gráfico 3 & Tabela/Excel |
| 12 | Temp. Borracha | `Temp. Borracha Saída Extrusão` | `CALANDRA - TEMPERATURA_BORRACHA_SAIDA_EXTRUSAO (°C)` | °C | Numeric (3) | Card 1 & Gráfico 4 |
| 13 | Temp. Borracha | `Temp. Borracha Entrada Calandra` | `CALANDRA - TEMPERATURA_BORRACHA_ENT_CALANDRA (°C)` | °C | Numeric (3) | Card 1 & Gráfico 4 |
| 14 | Temp. Borracha | `Temp. Borracha Saída Calandra` | `CALANDRA - TEMPERATURA_BORRACHA_SAIDA_CALANDRA (°C)` | °C | Numeric (3) | Card 1 & Gráfico 4 |
| 15 | Temp. Cilindros | `Temp. Cilindro Inferior` | `CALANDRA_TEMPERATURA - CILINDRO_INFERIOR (°C)` | °C | Numeric (3) | Card 2 & Gráfico 5 |
| 16 | Temp. Cilindros | `Temp. Cilindro Intermediário` | `CALANDRA_TEMPERATURA - CILINDRO_INTERMEDIÁRIO (°C)` | °C | Numeric (3) | Card 2 & Gráfico 5 |
| 17 | Temp. Cilindros | `Temp. Cilindro Superior` | `CALANDRA_TEMPERATURA - CILINDRO_SUPERIOR (°C)` | °C | Numeric (3) | Card 2 & Gráfico 5 |
| 18 | Temp. Auxiliares | `Temp. Furador` | `CALANDRA_TEMPERATURA - FURADOR (°C)` | °C | Numeric (3) | Card 4 & Gráfico 6 |
| 19 | Temp. Auxiliares | `Temp. Aquecedor` | `CALANDRA_TEMPERATURA - AQUECEDOR` | °C | Numeric (3) | Card 4 & Gráfico 6 |
| 20 | Temp. Auxiliares | `Temp. TCU Extrusora` | `CALANDRA_TEMPERATURA - TCU_EXTRUSORA (°C)` | °C | Numeric (3) | Card 4 & Gráfico 6 |
| 21 | Temp. Auxiliares | `Temp. Geladeira` | `CALANDRA_TEMPERATURA - GELADEIRA (ºC)` | °C | Numeric (3) | Card 4, Gráfico 6, Tabela & Excel |

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Modificados:
- `production/services_calandra.py`:
  - Inclusão da 21ª variável `temp_geladeira` no `CALANDRA_VARIABLES_CONFIG`.
  - Tratamento de flexibilidade de matching para variantes do símbolo de grau (`(ºC)` / `(°C)`).
  - Atualização do cálculo de estatísticas dos cards em `compute_effective_process_stats` (inclusão de `geladeira` no Card 4).
  - Atualização dos métodos de datasets gráficos (`_empty_chart_datasets`, `_build_chart_datasets`) para conter a série `geladeira` no Gráfico 6.
- `production/templates/production/calandra_report.html`:
  - Inclusão da linha da `Geladeira` no Card 4 (Temperaturas Auxiliares: Média, Mínimo, Máximo).
  - Inclusão da série `Geladeira (°C)` no Gráfico 6 (Temperaturas Auxiliares) com cor dedicada (ex: `#0284C7` / `#06B6D4`).
  - Ajuste de estilo do Chart.js para linhas limpas sem pontos em massa (`pointRadius: 0`, `pointHoverRadius: 5`, `hitRadius: 8`).
  - Inclusão da coluna `T. Geladeira (°C)` na tabela histórica sincronizada.
  - Atualização do script de recálculo instantâneo em navegador (`recomputeCardsInBrowser`) para atualizar os campos `c4_gel_avg`, `c4_gel_min`, `c4_gel_max`.
  - Atualização da contagem dinâmica de variáveis para refletir 21 variáveis.
- `production/templates/production/xid_calandra_config.html` & `production/templates/production/machine_reports_hub.html`:
  - Atualização das descrições e contadores de variáveis para 21.
- `production/test_calandra_report.py`:
  - Ampliação da suíte de testes unitários para validar a 21ª variável Geladeira, cálculo dos cards, 6 gráficos, exportação Excel (22 colunas) e integridade de banco somente-leitura.
- `Instrucoes.txt`:
  - Registro resumido da entrega técnica.

---

## 🚫 5. FORA DE ESCOPO & REGRAS PROIBIDAS

- ❌ **SCADA SOMENTE LEITURA:** NENHUM `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE` ou migração no banco `scada`.
- ❌ **SEM TROCA DE BIBLIOTECA:** Manter Chart.js já utilizado, apenas ajustando as configurações de renderização de pontos.
- ❌ **SEM ALTERAÇÃO DA REGRA DE PROCESSO EFETIVO:** Preservar a fórmula já aprovada ($v > 0.05$ e avanço na metragem).
- ❌ **SEM MÚLTIPLOS APPS OU .VENV:** Manter ambiente único e monolítico Django.

---

## ⚙️ 6. REGRAS DE NEGÓCIO E ALGORITMOS

### 6.1. Regra de Processo Efetivo
Apenas registros onde a velocidade da máquina seja maior que $0.05\text{ m/min}$ acompanhada de avanço positivo ou reset consistente de metragem bobinada são classificados com `is_effective = True`.

### 6.2. Card 4 — Temperaturas Auxiliares
O Card 4 passa a computar 4 equipamentos:
1. Furador: $\bar{T}_{\text{fur}}, T_{\text{fur, min}}, T_{\text{fur, max}}$
2. Aquecedor: $\bar{T}_{\text{aquec}}, T_{\text{aquec, min}}, T_{\text{aquec, max}}$
3. TCU Extrusora: $\bar{T}_{\text{tcu}}, T_{\text{tcu, min}}, T_{\text{tcu, max}}$
4. Geladeira: $\bar{T}_{\text{gel}}, T_{\text{gel, min}}, T_{\text{gel, max}}$

Calculados estritamente sobre `is_effective == True`.

### 6.3. Gráficos de Linha Limpos (Chart.js)
Configuração global / base dos datasets:
```javascript
elements: {
    point: {
        radius: 0,        // Sem bolinhas por padrão na linha contínua
        hoverRadius: 5,   // Destaque sob interação/hover
        hitRadius: 8      // Área de captura do cursor
    },
    line: {
        borderWidth: 2,
        tension: 0.2
    }
}
```

### 6.4. Exportação Excel (.xlsx)
Estrutura das colunas no `.xlsx`:
1. `DATA/HORA`
2. `PASSADA`
3. `METRAGEM BOBINADA (m)`
4. `VEL. CALANDRA (m/min)`
5. `CARGA BOBINAMENTO (kg)`
6. `CARGA DESBOBINADOR (kg)`
7. `CARGA PÓS-CALANDRA (kg)`
8. `CARGA QUEBRA-TRAMA (kg)`
9. `ESPESSURA ESQ. SUPERIOR (mm)`
10. `ESPESSURA DIR. SUPERIOR (mm)`
11. `ESPESSURA DIR. INFERIOR (mm)`
12. `ESPESSURA ESQ. INFERIOR (mm)`
13. `TEMP. BORRACHA SAÍDA EXTRUSÃO (°C)`
14. `TEMP. BORRACHA ENTRADA CALANDRA (°C)`
15. `TEMP. BORRACHA SAÍDA CALANDRA (°C)`
16. `TEMP. CILINDRO INFERIOR (°C)`
17. `TEMP. CILINDRO INTERMEDIÁRIO (°C)`
18. `TEMP. CILINDRO SUPERIOR (°C)`
19. `TEMP. FURADOR (°C)`
20. `TEMP. AQUECEDOR (°C)`
21. `TEMP. TCU EXTRUSORA (°C)`
22. `TEMP. GELADEIRA (°C)`

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO & TESTES

- [ ] 21 variáveis configuradas canonicamente em `CALANDRA_VARIABLES_CONFIG`.
- [ ] Tag `CALANDRA_TEMPERATURA - GELADEIRA (ºC)` mapeada com tipo `3` (Numeric) e unidade `°C`.
- [ ] Card 4 ("Temperaturas Auxiliares") exibe Furador, Aquecedor, TCU Extrusora e Geladeira (Média, Mínimo, Máximo sob processo efetivo).
- [ ] Gráfico 6 exibe as 4 séries térmicas auxiliares (incluindo Geladeira).
- [ ] Todos os 6 gráficos renderizam linhas limpas sem círculos/marcadores em massa, preservando destaque no hover e tooltips.
- [ ] Tabela histórica exibe a coluna `T. Geladeira (°C)`.
- [ ] Exportação Excel gera as 22 colunas com tipagem numérica e formatação aprovada.
- [ ] Seleção temporal na interface recalcula os 4 cards no frontend incluindo Geladeira.
- [ ] Banco `scada` permanece 100% somente-leitura.
- [ ] Suíte de testes automatizados passa com 100% de sucesso.
