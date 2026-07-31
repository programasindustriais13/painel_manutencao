# 🏛️ Walkthrough — SPEC 05D: Histórico de Matrizes e Linha do Tempo Operacional

## 📌 Visão Geral

A **SPEC 05D** implementou com sucesso a rastreabilidade completa das matrizes utilizadas em cada cavidade (`ProductionCavityMatrixHistory`) e dos intervalos operacionais das prensas (`ProductionMachineStateInterval`), removeu a informação incorreta de total agregado de produção/meta no card da prensa, adicionou o card geral **Matrizes em Uso** no dashboard e a **Linha do Tempo Operacional** com KPIs industriais na tela de detalhe da máquina.

---

## 🚀 Principais Modificações Realizadas

### 1. Modelos de Dados e Roteamento Multibanco
- **`ProductionCavityMatrixHistory`**: Registra `cavity_config`, `matrix_value`, `started_at`, `ended_at`. Indexado por cavidade e datas.
- **`ProductionMachineStateInterval`**: Registra `machine_config`, `state` (PRODUZINDO, PARADA, SEM_COMUNICACAO), `started_at`, `ended_at`, `status_raw_value`. Indexado por máquina e datas.
- **`ScadaRouter`**: Adicionados `"productioncavitymatrixhistory"` e `"productionmachinestateinterval"` em `LOCAL_MANAGED_MODELS`.
- **Migration `0007_productionmachinestateinterval_and_more.py`**: Gerada e aplicada no banco default.

### 2. Lógica de Serviços (`ProductionStateService`)
- **Normalização de Matrizes (`normalize_matrix_value`)**: Valores equivalentes (`"12"`, `12`, `12.0`, `" 12 "`) são convertidos para a mesma string `"12"`.
- **Transição Atômica de Matrizes**:
  - Primeira leitura abre histórico (`started_at = timezone.now()`, `ended_at = None`).
  - Troca de matriz fecha histórico anterior (`ended_at = timezone.now()`) e abre novo.
  - Scada offline/stale/nulo preserva o histórico aberto sem fechar ou criar duplicatas.
- **Transição Atômica de Estados**:
  - Registra intervalos contínuos de estado da prensa (`PRODUZINDO`, `PARADA`, `SEM_COMUNICACAO`).
  - Scada offline ou dado stale é classificado como `SEM_COMUNICACAO`.
- **Resumo e Histórico de Matrizes (`get_dashboard_state`)**:
  - Resumo atual agrupado por matriz com contagens de cavidades Normais, Paradas e Indeterminadas.
  - Histórico de matrizes filtrável por período (Hoje, 7d, 30d, custom) com ordenação de registros em uso no topo.
- **Linha do Tempo Operacional (`get_machine_detail`)**:
  - Segmentos recortados pelo período selecionado.
  - KPIs do período: Tempo Produzindo (% Produzindo), Tempo Parado (% Parado), Sem Comunicação, Ciclos de Produção e Quantidade de Paradas.
  - Exclusão de Sem Comunicação do denominador de eficiência industrial e tratamento de divisão por zero.

### 3. Interfaces visuais (`dashboard.html` e `machine_detail.html`)
- **Remoção do Total Agregado**: Removida a string `Total: X / Y (Z%)` do cabeçalho de cavidades no card da prensa em `/producao/`.
- **Card Matrizes em Uso**: Inserido abaixo dos parâmetros globais com seções A (Resumo Atual) e B (Histórico Filtrável).
- **Linha do Tempo Operacional**: Barra horizontal colorida (Verde: Produzindo, Vermelho: Parada, Cinza: Sem comunicação) com tooltips Bootstrap e KPIs industriais.

---

## 🧪 Validação e Qualidade

- **`python manage.py check`**: 0 problemas identificados.
- **`python manage.py makemigrations --check --dry-run`**: Nenhuma alteração pendente.
- **`python manage.py showmigrations production`**: Migração 0007 `[X]` aplicada.
- **Suíte de Testes Unitários**: 101/101 testes passando (78 em `production`, 23 em `maintenance`).

---

## 📸 Componentes visuais

- **Card Geral das Matrizes**: `/producao/` (Resumo agrupado + Histórico filtrável)
- **Linha do Tempo Operacional**: `/producao/maquinas/<id>/` (Barra horizontal de ciclos + KPIs de eficiência)
