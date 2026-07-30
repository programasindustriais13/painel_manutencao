# 🧠 Implementation Plan — SPEC 05B: Enriquecimento dos Cards de Produção e Alerta de Parada [STATUS: CONCLUÍDO]

## 📌 Objetivo
Adicionar aos cards do painel de produção (`/producao/`) e à tela de detalhe da máquina (`/producao/maquinas/<id>/`) informações operacionais detalhadas por cavidade (matriz, produto, lote do bladder, meta manual), suporte a estado independente por cavidade, cronômetro contínuo para o estado **Produzindo**, e alerta visual destacado para prensas paradas há mais de 5 minutos (300s). Implementado com 100% de sucesso.

---

## 📋 Mapeamento da SPEC 05B

| SPEC | Componentes Afetados | Foco Principal |
| :--- | :--- | :--- |
| **SPEC 05B** | `ProductionCavityConfig`, `ScadaReaderService`, `ProductionStateService`, `dashboard.html`, `machine_detail.html` | Adiciona novos XIDs operacionais por cavidade, meta manual, produto/lote combinados, status de cavidade independente, alerta de prensa parada >= 5min e cronômetros de Produzindo e Parada. |

---

## 📌 Estado Atual do Projeto

- **Branch Ativa:** `feature/producao-scada`
- **Tabelas e Models:** `ProductionMachineConfig`, `ProductionCavityConfig`, `ProductionMachineState`, `ProductionDowntimeEvent`, `ScadaDataPoint`, `ScadaPointValue`, `ScadaPointValueAnnotation`.
- **Testes Legados:** 67 testes executados com sucesso (44 em `production`, 23 em `maintenance`).
- **Novo Arquivo de SPEC:** Criado em `regras_programacao/SPEC_PRODUCAO_05B_DADOS_OPERACIONAIS_ALERTA_PARADA.md`.

---

## 📐 Detalhamento Completo da SPEC 05B

### 🟢 1. Alterações de Banco e Admin (`ProductionCavityConfig`)
- Adicionar campos opcionais em `ProductionCavityConfig`:
  - `xid_status_cavidade` (CharField max_length=100, null=True, blank=True)
  - `valor_cavidade_produzindo` (CharField max_length=50, default="1")
  - `xid_matriz` (CharField max_length=100, null=True, blank=True)
  - `xid_produto` (CharField max_length=100, null=True, blank=True)
  - `xid_lote_bladder` (CharField max_length=100, null=True, blank=True)
  - `meta_producao_manual` (PositiveIntegerField, default=0)
- Gerar migration aditiva `0005` no banco `default`.
- Atualizar `ProductionCavityConfigInline` em `production/admin.py`.

### 🟡 2. Atualização dos Serviços (`ScadaReaderService` e `ProductionStateService`)
- Leitura em lote de todos os novos XIDs das cavidades.
- Concatenação de Produto e Lote (`"Produto - Lote"`, `"Produto"`, `"Lote: X"`, `"Não informado"`).
- Interpretação do status individual da cavidade sem alterar o estado da prensa.
- Cálculo da meta manual e limite de largura da barra em 100%.
- Flag e banner para prensa parada há >= 5 minutos (300 segundos).
- Cronômetro contínuo para `Produzindo há ...` e `Parada há ...`.

### 🔵 3. Interface Visual e Testes
- Atualizar `dashboard.html` e `machine_detail.html`.
- Expandir `production/tests.py` com novos testes para a SPEC 05B.
- Executar todas as verificações de QA.
