# 🧠 SPEC_PRODUCAO_07F — NOVO GRÁFICO OPERACIONAL DE ESTADOS EM DEGRAUS (STEP-LINE CHART)

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `SPEC_PRODUCAO_07E_HISTORICO_MANUTENCAO_NA_MAQUINA.md`
- **URL(s) envolvidas**:
  - `/producao/maquinas/<id>/` (Detalhe da Máquina no Módulo de Produção)
- **Contexto(s)**: Dashboard de Detalhes da Prensa / Visualização de Estados Operacionais
- **Perfil(s) afetados**: Líder de Produção, PCP, Engenharia de Processos, Operadores

---

## ❗ 2. PROBLEMA ATUAL

A tela atual de detalhes da máquina (`/producao/maquinas/<id>/`) utiliza um componente simplificado de barra horizontal fragmentada ("Linha do Tempo Operacional") renderizado via divisões HTML/CSS com `width_pct`.
Esta visualização possui limitações operacionais para o chão de fábrica:
1. Não fornece uma curva contínua e temporal de alternância entre os estados da prensa.
2. Não possui presets de tempo rápidos (8h, 12h, 24h, 7 dias) nem seletor de período personalizado com recorte dinâmico.
3. Não permite visualizar a transição instantânea em formato de degrau (Step-line chart) com tooltip interativo contendo horário exato de início, fim, duração, motivo de parada e técnico responsável alocado no momento.

---

## 🎯 3. OBJETIVO

Substituir o componente atual da Linha do Tempo Operacional por um **Gráfico Interativo de Estados em Degraus (Step-Line Chart)** baseado na biblioteca **Chart.js** (já utilizada no projeto):
1. **Eixo X**:
   - Escala temporal dinâmica (data e hora formatadas).
2. **Eixo Y (Legendas Semânticas Explicitas)**:
   - `Produzindo` (Valor Y = 2) -> Linha em tom verde (`#22c55e`).
   - `Parada` (Valor Y = 1) -> Linha em tom vermelho (`#ef4444`).
   - `Sem comunicação` (Valor Y = 0) -> Linha em tom cinza (`#9ca3af`).
   - PROIBIDO apresentar apenas os numéricos 0 e 1 sem os rótulos semânticos na legenda e no eixo Y.
3. **Comportamento em Degraus (`steppedLine / stepped: true`)**:
   - A transição entre os estados deve ocorrer verticalmente no instante exato da mudança (degrau), sem rampa de interpolação diagonal.
4. **Presets de Janela Temporal**:
   - Botões de seleção rápida no topo do gráfico: **8h**, **12h**, **24h**, **7 dias** e **Personalizado** (Data Inicial / Data Final).
5. **Tooltips Ricos e Interativos**:
   - Ao passar o cursor ou tocar na linha, o tooltip deve exibir:
     - Estado legível ("Produzindo", "Parada", "Sem comunicação").
     - Data/Hora exata de Início e Término do intervalo.
     - Duração formatada (ex: `02h 15min`).
     - Motivo de parada registrado (se em estado Parada).
     - Técnico(s) da manutenção alocado(s) no momento do evento (se houver atendimento).
6. **Otimização para Grande Volume de Dados**:
   - Downsampling / agregação inteligente no backend para janelas longas (ex: 7 dias), limitando o payload JSON transmitido a no máximo 500 a 1000 pontos por requisição.
7. **Responsividade**:
   - Totalmente adaptável para telas de smartphones, tablets, computadores e monitores de TV industrial.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py):
  - Criar o método `get_machine_stepline_chart_data` em `ProductionStateService` para processar e compactar os intervalos de `ProductionMachineStateInterval` com cruzamento de alocações da Manutenção.
- [templates/production/machine_detail.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/machine_detail.html):
  - Atualizar o container do gráfico substituindo a barra HTML pelo `<canvas id="steplineChart">` e adicionando a barra de botões de preset temporal (8h, 12h, 24h, 7d, custom).
  - Incluir script de inicialização do Chart.js com configuração `stepped: true` e callback customizado de tooltip.

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO adicionar novas bibliotecas gráficas pesadas (reutilizar a biblioteca Chart.js já presente na aplicação).
- ❌ NÃO criar novas tabelas no banco de dados.
- ❌ NÃO travar o navegador transmitindo dezenas de milhares de pontos brutos sem amostragem.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`:
- Interface 100% em Português Brasileiro (pt-br).
- Preservar responsividade e visual moderno (WOW factor).
- Sem SQL puro.

---

## ⚙️ 7. REGRAS DE NEGÓCIO DETALHADAS

1. **Mapeamento de Valores Y do Chart**:
   - Index 2 = "Produzindo"
   - Index 1 = "Parada"
   - Index 0 = "Sem comunicação"
2. **Preset Temporal Padrão**:
   - Ao carregar a tela da máquina sem parâmetros na URL, o preset padrão é de **24 horas**.
3. **Cruzamento com Atendimentos da Manutenção**:
   - Para intervalos com estado "Parada", o backend consulta se havia alguma `Allocation` em aberto para a mesma máquina no período e anexa os nomes dos técnicos no payload do ponto para exibição no tooltip.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] O gráfico de estados é renderizado com linha em degraus (stepped line) em Chart.js.
- [ ] O eixo Y exibe explicitamente os rótulos "Produzindo", "Parada" e "Sem comunicação".
- [ ] As cores correspondem ao padrão industrial: Verde (`#22c55e`) para Produzindo, Vermelho (`#ef4444`) para Parada e Cinza (`#9ca3af`) para Sem Comunicação.
- [ ] Os botões de preset 8h, 12h, 24h, 7d e Personalizado filtram dinamicamente o gráfico.
- [ ] O tooltip ao passar o mouse exibe estado, horário início/fim, duração, motivo de parada e técnico alocado.
- [ ] Suíte de testes automatizados passa 100%.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Renderização lenta no navegador ao selecionar o período de 7 dias com milhares de oscilações.
  - *Mitigação*: Algoritmo de descarte de redundâncias consecutivas em `services.py` (mantém apenas os pontos de transição de estado de/para).

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Desenvolver `get_machine_stepline_chart_data` em `ProductionStateService` (`production/services.py`).
2. Implementar compressão de pontos idênticos consecutivos (preservando apenas instantes de transição).
3. Atualizar `machine_detail.html` com o `<canvas>` Chart.js e presets temporais.
4. Configurar callbacks do Chart.js para escala semântica no Eixo Y e tooltips ricos.
5. Criar testes automatizados para verificação da estrutura de dados do gráfico.

---

## 🧪 11. TESTES AUTOMATIZADOS E MANUAIS

### Testes Automatizados:
- `test_stepline_chart_data_structure`: valida se a estrutura JSON gerada contém os pontos X (timestamp), Y (0, 1, 2) e metadados de tooltip.
- `test_stepline_chart_preset_filtering`: testa a filtragem por 8h, 12h, 24h e 7d.
- `test_stepline_chart_reduces_consecutive_duplicates`: garante que estados idênticos seguidos são unificados sem inflar o payload.

---

## 🛑 12. GATE DE SAÍDA E REGRA DE PARADA

- **Gate de Saída**: Testes do gráfico de degraus 100% aprovados.
- **Regra de Parada**: Se o gráfico apresentar degradação de performance (> 500ms para renderizar no frontend), PARAR e refinar a amostragem de dados.
