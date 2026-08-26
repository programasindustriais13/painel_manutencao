# 🧠 SPEC — HISTÓRICO DA CALANDRA E CENTRAL DE RELATÓRIOS DE MÁQUINAS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/` (Dashboard de Produção — Inclusão do card "Relatórios de Máquinas" na tela pós-login)
  - `/producao/relatorios/` (Central de Relatórios de Máquinas — Catálogo de relatórios com card da Calandra)
  - `/producao/relatorios/calandra/` (Relatório Histórico da Calandra — Filtros, Gráficos por Grupo e Tabela)
  - `/producao/relatorios/calandra/exportar-excel/` (Exportação do Histórico Sincronizado em formato `.xlsx`)
- **Contexto(s):** Módulo de Produção Industrial / Integração SCADA-LTS / Histórico de Variáveis de Processo.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Operadores (`Operadores`, `Operador`), PCP (`PCP`), Superusuários e Staff. Usuários da Manutenção pura e Visualizadores TV são bloqueados.
- **Predecessoras:** 
  - `SPEC_FUNDACAO_PRODUCAO.md`
  - `SPEC_PRODUCAO_04_INTEGRACAO_SCADA_E_PAINEL.md`
  - `SPEC_CENTRAL_CONFIGURACAO_SCADA_XIDS.md`
  - `SPEC_RESTRICAO_ACESSO_DASHBOARD.md`

---

## ❗ 2. PROBLEMA ATUAL

1. **Ausência de Análise Histórica para a Calandra:** A máquina CALANDRA (utilizada para emborrachamento de tecido nas 1ª e 2ª faces / face oposta) possui 20 variáveis críticas registradas no Scada-LTS, mas não há funcionalidade no sistema para consulta histórica, visualização gráfica agrupada e exportação tabular sincronizada.
2. **Navegação Fragmentada para Relatórios:** Não existe um ponto de entrada claro e amigável na tela inicial da Produção após o login para relatórios analíticos de máquinas, exigindo rotas diretas ou menus técnicos.
3. **Dessincronização Temporal dos Datapoints SCADA:** As 20 variáveis industriais possuem registros com timestamps independentes na tabela `pointvalues` do Scada-LTS. Uma visualização crua geraria linhas esparsas com células vazias ou N+1 queries ineficientes.
4. **Volume Excessivo de Leituras para Gráficos:** Intervalos longos (7 dias, 30 dias) podem gerar dezenas de milhares de pontos, comprometendo o desempenho do navegador se enviados de forma bruta, enquanto a exportação Excel deve preservar com fidelidade o histórico bruto sincronizado.

---

## 🎯 3. OBJETIVO

1. **Card na Página Inicial da Produção:** Adicionar na tela inicial pós-login (`/producao/`) o card genérico **"Relatórios de Máquinas"** (sem acoplar o nome à Calandra, preparando para futuras máquinas), com link para a Central de Relatórios.
2. **Central de Relatórios de Máquinas (`/producao/relatorios/`):** Criar uma página intermediária limpa com o catálogo de relatórios disponíveis, exibindo inicialmente o card ativo da **Calandra**.
3. **Relatório Histórico da Calandra (`/producao/relatorios/calandra/`):** Permitir selecionar períodos rápidos (Hoje, Ontem, Últimos 7 dias, Últimos 30 dias) ou Intervalo Personalizado (Data/Hora Inicial e Final), consultando o histórico das 20 variáveis da Calandra.
4. **5 Gráficos Agrupados por Contexto de Processo:**
   - **Gráfico A — Produção:** Velocidade da Calandra (`m/min`), Metragem Bobinada (`m`) e contexto temporal da `PASSADA` (destacando a transição PASSADA 1 [1ª face] → PASSADA 2 [2ª face / face oposta]).
   - **Gráfico B — Cargas:** Carga Bobinamento, Desbobinador, Pós-Calandra e Quebra-Trama (unidade `kg`).
   - **Gráfico C — Espessuras:** Esquerda Superior, Direita Superior, Direita Inferior, Esquerda Inferior.
   - **Gráfico D — Temperatura da Borracha:** Saída Extrusão → Entrada Calandra → Saída Calandra (unidade `°C`).
   - **Gráfico E — Temperaturas do Processo/Equipamento:** Cilindro Inferior, Cilindro Intermediário, Cilindro Superior, Furador, Aquecedor e TCU Extrusora (unidade `°C`).
5. **Tabela Histórica Horizontal Sincronizada:** Tabela responsiva com primeira coluna `Data/Hora`, segunda coluna `Passada` (contexto do processo) e as demais variáveis preenchidas pelo estado conhecido naquele instante (técnica de forward-fill temporal).
6. **Exportação Excel Profissional (`.xlsx`):** Gerar arquivo `.xlsx` com cabeçalho amigável + unidades, autofiltro, primeira linha congelada, valores numéricos como números nativos e datas formatadas.
7. **Segurança e Desempenho:** Banco `scada` estritamente somente-leitura (zero writes, zero migrations), sem consultas históricas desnecessárias ao carregar a home ou a central de relatórios, e proteção contra períodos excessivos.

---

## 📋 4. INVENTÁRIO DAS 20 VARIÁVEIS DA CALANDRA

| # | Grupo de Processo | Nome Amigável (pt-br) | Tag / XID SCADA | Unidade | Tipo SCADA |
| :-: | :--- | :--- | :--- | :-: | :-: |
| 1 | Produção / Contexto | `Passada` | `CALANDRA_meta - PASSADA` | — | Multistate / Contexto |
| 2 | Produção / Contexto | `Metragem Bobinada` | `CALANDRA - METRAGEM_BOBINADA` | m | Numeric |
| 3 | Produção / Contexto | `Velocidade da Calandra` | `CALANDRA - VEL_CALANDRA (m/min)` | m/min | Numeric |
| 4 | Cargas / Tensões | `Carga Bobinamento` | `CALANDRA - CARGA_BOBINAMENTO (Kg)` | kg | Numeric |
| 5 | Cargas / Tensões | `Carga Desbobinador` | `CALANDRA - CARGA_DESBOBINADOR (Kg)` | kg | Numeric |
| 6 | Cargas / Tensões | `Carga Pós-Calandra` | `CALANDRA - CARGA_POS-CALANDRA (Kg)` | kg | Numeric |
| 7 | Cargas / Tensões | `Carga Quebra-Trama` | `CALANDRA - CARGA_QUEBRA-TRAMA (Kg)` | kg | Numeric |
| 8 | Espessuras | `Espessura Esq. Superior` | `CALANDRA - ESPESSURA_LADO ESQ SUPERIOR` | mm | Numeric |
| 9 | Espessuras | `Espessura Dir. Superior` | `CALANDRA - ESPESSURA_LADO DIR SUPERIOR` | mm | Numeric |
| 10 | Espessuras | `Espessura Dir. Inferior` | `CALANDRA - ESPESSURA_LADO DIR INFERIOR` | mm | Numeric |
| 11 | Espessuras | `Espessura Esq. Inferior` | `CALANDRA - ESPESSURA_LADO ESQ INFERIOR` | mm | Numeric |
| 12 | Temp. Borracha | `Temp. Borracha Saída Extrusão` | `CALANDRA - TEMPERATURA_BORRACHA_SAIDA_EXTRUSAO (°C)` | °C | Numeric |
| 13 | Temp. Borracha | `Temp. Borracha Entrada Calandra` | `CALANDRA - TEMPERATURA_BORRACHA_ENT_CALANDRA (°C)` | °C | Numeric |
| 14 | Temp. Borracha | `Temp. Borracha Saída Calandra` | `CALANDRA - TEMPERATURA_BORRACHA_SAIDA_CALANDRA (°C)` | °C | Numeric |
| 15 | Temp. Processo | `Temp. Cilindro Inferior` | `CALANDRA_TEMPERATURA - CILINDRO_INFERIOR (°C)` | °C | Numeric |
| 16 | Temp. Processo | `Temp. Cilindro Intermediário` | `CALANDRA_TEMPERATURA - CILINDRO_INTERMEDIÁRIO (°C)` | °C | Numeric |
| 17 | Temp. Processo | `Temp. Cilindro Superior` | `CALANDRA_TEMPERATURA - CILINDRO_SUPERIOR (°C)` | °C | Numeric |
| 18 | Temp. Processo | `Temp. Furador` | `CALANDRA_TEMPERATURA - FURADOR (°C)` | °C | Numeric |
| 19 | Temp. Processo | `Temp. Aquecedor` | `CALANDRA_TEMPERATURA - AQUECEDOR` | °C | Numeric |
| 20 | Temp. Processo | `Temp. TCU Extrusora` | `CALANDRA_TEMPERATURA - TCU_EXTRUSORA (°C)` | °C | Numeric |

---

## 🧩 5. ESCOPO DA ALTERAÇÃO

### Novos Arquivos:
- `regras_programacao/SPEC_HISTORICO_CALANDRA_RELATORIOS.md` (Esta especificação)
- `production/services_calandra.py` (Módulo de serviço dedicado: catálogo de variáveis da Calandra, consultas históricas indexadas em lote no SCADA, motor de sincronização temporal forward-fill, amostragem otimizada para gráficos e gerador de Excel)
- `production/templates/production/machine_reports_hub.html` (Tela: Central de Relatórios de Máquinas)
- `production/templates/production/calandra_report.html` (Tela: Relatório Histórico da Calandra — Filtros, 5 Gráficos e Tabela)
- `production/test_calandra_report.py` (Suíte completa de testes automatizados: permissões, filtros, histórico, forward-fill, Excel e ausência de escrita no SCADA)

### Arquivos a Modificar:
- `production/urls.py` (Registro das rotas: `relatorios/`, `relatorios/calandra/`, `relatorios/calandra/exportar-excel/`)
- `production/views.py` (Views: `machine_reports_hub`, `calandra_report`, `calandra_export_excel`)
- `production/templates/production/dashboard.html` (Inclusão do card "Relatórios de Máquinas" na home pós-login)
- `production/templates/production/base_production.html` (Inclusão do item "Relatórios de Máquinas" na sidebar/menu de navegação)
- `Instrucoes.txt` (Registro da entrega da funcionalidade)

---

## 🚫 6. FORA DE ESCOPO

- ❌ NENHUMA escrita no banco `scada` (zero `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE` ou `ALTER TABLE`).
- ❌ NÃO executar migrações no banco `scada` (`allow_migrate` retorna `False`).
- ❌ NÃO implementar limites de processo nesta fase (sem valores mín/máx, faixas de tolerância ou alarmes de qualidade automáticos).
- ❌ NÃO criar relatórios fictícios para outras máquinas nesta demanda.
- ❌ NÃO criar novo app Django ou segundo ambiente virtual.
- ❌ NÃO consultar o histórico do SCADA ao carregar a página inicial (`/producao/`) ou a Central de Relatórios (`/producao/relatorios/`).
- ❌ NÃO alterar regras do módulo de Manutenção ou quebrar redirecionamentos de login existentes.

---

## 🔐 7. REGRAS OBRIGATÓRIAS (CONSTITUTION & SEGURANÇA)

1. **Ambiente Único:** 1 monólito Django, 1 `.venv`, sem duplicação de pastas.
2. **Controle Estrito de Acesso no Backend:**
   - As views da Central e do Relatório da Calandra são decoradas com `@lider_producao_required`.
   - Perfis sem acesso ao módulo `production` (Manutenção comum, TV) são bloqueados e redirecionados para sua página inicial correspondente.
3. **Isolamento e Segurança do SCADA:**
   - Consultas históricas utilizam os models não gerenciados `ScadaDataPoint`, `ScadaPointValue`, `ScadaPointValueAnnotation` via `.using("scada")`.
   - Filtros obrigatórios por período (`ts >= start_ms AND ts <= end_ms`) e por lista restrita de IDs de datapoints.
   - Proteção de limite máximo de período (ex: máximo 31 dias por consulta).
4. **Timezone:** Todas as conversões de timestamp utilizam o timezone configurado no Django (`America/Sao_Paulo`).

---

## ⚙️ 8. REGRAS DE NEGÓCIO E ARQUITETURA TÉCNICA

### 8.1. Motor de Sincronização Temporal (Forward-Fill de Estado)
Como os 20 datapoints são registrados de forma assíncrona pelo Scada-LTS:
1. Resolução em lote dos IDs internos dos 20 DataPoints no SCADA (buscando por `xid` ou `pointName`).
2. Consulta dos registros históricos de `ScadaPointValue` no intervalo `[start_ms, end_ms]`, ordenados por `ts ASC`.
3. Consulta do último valor anterior a `start_ms` para cada variável para inicializar o estado no início da janela (`initial_state`).
4. Agrupamento por timestamp: a cada leitura em `ts`, atualiza o valor da respectiva variável no dicionário de estado corrente `current_state`.
5. Emissão de linha de estado consolidado: cada instante temporal contém o snapshot completo das 20 variáveis.
6. Contexto da `PASSADA`:
   - Se valor == 1 ou "1": `PASSADA 1 (1ª face)`
   - Se valor == 2 ou "2": `PASSADA 2 (2ª face / face oposta)`
   - Outro: preserva valor bruto formatado.

### 8.2. Otimização de Performance para Gráficos
- O dataset tabular e o arquivo Excel utilizam 100% dos dados sincronizados brutos.
- Para a renderização dos 5 gráficos interativos (Chart.js), se a série temporal exceder 1.500 pontos, é aplicada amostragem temporal preservando os pontos de transição e valores de pico/mínimo, garantindo renderização instantânea no navegador.

### 8.3. Estrutura do Arquivo Excel (`.xlsx`)
- **Biblioteca:** `openpyxl`.
- **Formato:** Horizontal (1 linha por timestamp, 1 coluna por variável).
- **Ordem das Colunas:**
  1. `DATA/HORA` (Excel Datetime)
  2. `PASSADA` (Texto com contexto: "PASSADA 1 (1ª face)", etc.)
  3. `METRAGEM BOBINADA (m)`
  4. `VEL. CALANDRA (m/min)`
  5. `CARGA BOBINAMENTO (kg)`
  6. `CARGA DESBOBINADOR (kg)`
  7. `CARGA PÓS-CALANDRA (kg)`
  8. `CARGA QUEBRA-TRAMA (kg)`
  9. `ESPESSURA ESQ. SUPERIOR`
  10. `ESPESSURA DIR. SUPERIOR`
  11. `ESPESSURA DIR. INFERIOR`
  12. `ESPESSURA ESQ. INFERIOR`
  13. `TEMP. BORRACHA SAÍDA EXTRUSÃO (°C)`
  14. `TEMP. BORRACHA ENTRADA CALANDRA (°C)`
  15. `TEMP. BORRACHA SAÍDA CALANDRA (°C)`
  16. `TEMP. CILINDRO INFERIOR (°C)`
  17. `TEMP. CILINDRO INTERMEDIÁRIO (°C)`
  18. `TEMP. CILINDRO SUPERIOR (°C)`
  19. `TEMP. FURADOR (°C)`
  20. `TEMP. AQUECEDOR (°C)`
  21. `TEMP. TCU EXTRUSORA (°C)`
- **Estilo:** Cabeçalho estilizado em tom ouro/escuro Freedom, fonte Inter/Segoe UI, bordas finas, primeira linha congelada, autofiltro ativo e larguras de coluna ajustadas.

---

## 🎨 9. NAVEGAÇÃO E DESENHO DAS TELAS

### 9.1. Fluxo de Navegação:
```text
Login
  ↓
Página Inicial de Produção (/producao/)
  ↓ [Card: "Relatórios de Máquinas"]
Central de Relatórios de Máquinas (/producao/relatorios/)
  ↓ [Card: "Calandra"]
Relatório Histórico da Calandra (/producao/relatorios/calandra/)
  ↓ [Botão: "Exportar Excel"]
Download: CALANDRA_HISTORICO_YYYY-MM-DD_YYYY-MM-DD.xlsx
```

### 9.2. Card na Página Inicial (`/producao/`):
- Localizado em seção destacada no Dashboard de Produção.
- Título: **Relatórios de Máquinas**
- Descrição: *Consulte históricos, gráficos e exportações por equipamento.*
- Ação: `[Acessar relatórios]` → `/producao/relatorios/`

### 9.3. Central de Relatórios (`/producao/relatorios/`):
- Header com breadcrumbs: `Produção > Relatórios de Máquinas`
- Grid de cards de equipamentos.
- Card ativo: **Calandra** com descrição, badge de status operacional e botão `[Abrir relatório]`.

### 9.4. Tela do Relatório da Calandra (`/producao/relatorios/calandra/`):
- Filtros no topo:
  - Botões rápidos: `[Hoje]`, `[Ontem]`, `[Últimos 7 dias]`, `[Últimos 30 dias]`
  - Inputs de Data/Hora: `[Data/Hora Inicial]` e `[Data/Hora Final]`
  - Ações: `[Filtrar Histórico]` e `[Exportar Excel]`
- Seções de Gráficos (5 cards com abas ou layout em grade):
  1. Produção (Velocidade, Metragem, Passada)
  2. Cargas (Bobinamento, Desbobinador, Pós-Calandra, Quebra-Trama)
  3. Espessuras (Esq/Dir Superior, Esq/Dir Inferior)
  4. Temperatura da Borracha (Saída Extrusão, Entrada Calandra, Saída Calandra)
  5. Temperaturas do Processo (Cilindros, Furador, Aquecedor, TCU)
- Seção da Tabela Histórica:
  - Tabela horizontal sincronizada com paginação e badge visual de passada.

---

## 🧪 10. CRITÉRIOS DE ACEITAÇÃO

- [ ] Card "Relatórios de Máquinas" visível na página inicial de Produção para usuários autorizados.
- [ ] Card abre a Central de Relatórios de Máquinas (`/producao/relatorios/`).
- [ ] Central exibe o card da Calandra direcionando para `/producao/relatorios/calandra/`.
- [ ] Carregamento da página inicial e da Central de Relatórios NÃO executa consultas ao banco `scada`.
- [ ] Relatório da Calandra consulta o histórico das 20 variáveis no período selecionado.
- [ ] Gráficos organizados nos 5 grupos contextuais renderizam com clareza.
- [ ] Transição PASSADA 1 (1ª face) → PASSADA 2 (2ª face / face oposta) é evidenciada no gráfico e na tabela.
- [ ] Tabela histórica apresenta sincronização temporal por forward-fill sem colunas dispersas vazias.
- [ ] Exportação Excel gera `.xlsx` formatado profissionalmente, com primeira coluna Data/Hora, segunda Passada, números como numéricos e colunas corretas.
- [ ] Usuários sem permissão são bloqueados no backend em todas as rotas (Central, Calandra e Exportar Excel).
- [ ] Nenhuma escrita (`INSERT`/`UPDATE`/`DELETE`) é realizada no banco `scada`.
- [ ] Suíte completa de testes automatizados passa com 100% de sucesso.

---

## 🔍 11. PLANO DE IMPLEMENTAÇÃO

1. **Camada de Serviço (`production/services_calandra.py`):**
   - Definir inventário canônico das 20 variáveis.
   - Implementar resolução flexível de DataPoints (`xid` ou `pointName`).
   - Implementar consulta histórica indexada no `ScadaPointValue` com filtro temporal.
   - Implementar algoritmo de sincronização temporal (forward-fill).
   - Implementar amostragem para gráficos e gerador de planilha Excel `.xlsx`.
2. **Camada de Views e URLs (`production/views.py`, `production/urls.py`):**
   - Adicionar rotas `relatorios/`, `relatorios/calandra/`, `relatorios/calandra/exportar-excel/`.
   - Implementar views protegidas com `@lider_producao_required`.
3. **Camada de Templates:**
   - Criar `production/templates/production/machine_reports_hub.html`.
   - Criar `production/templates/production/calandra_report.html` com Chart.js.
   - Atualizar `production/templates/production/dashboard.html` adicionando o card "Relatórios de Máquinas".
   - Atualizar `production/templates/production/base_production.html` adicionando o link de navegação.
4. **Camada de Testes Automatizados (`production/test_calandra_report.py`):**
   - Testar matriz de permissões.
   - Testar filtros de data/hora e atalhos de período.
   - Testar consulta histórica com variáveis numéricas e textuais/multistate.
   - Testar forward-fill temporal de datapoints com timestamps dessincronizados.
   - Testar transição PASSADA 1 → PASSADA 2.
   - Testar geração de Excel `.xlsx` (formato, colunas, tipos, integridade).
   - Validar estritamente que nenhuma escrita ocorre no alias `scada`.
5. **Execução e Validação:**
   - Rodar suíte de testes do Django (`python manage.py test`).
   - Validar inexistência de regressões no módulo de Produção e Manutenção.
   - Atualizar `Instrucoes.txt` e gerar evidências completas.
