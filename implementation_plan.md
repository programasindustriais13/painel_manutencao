# 🧠 Implementation Plan — Melhoria de UX no Módulo de Produção (Histórico de Matrizes e Cards de Cavidades)

Melhoria de UX no módulo de Produção (`/producao/`) para apresentar o **Nome Canônico da Matriz** (em vez do código numérico do SCADA) na seção "HISTÓRICO DE MATRIZES" e reformular a apresentação visual nos **Cards das Prensas/Cavidades**, separando a Matriz (Linha 1) do Lote (Linha 2).

---

## 📌 Fonte Única de Verdade (Single Source of Truth)

- **Arquivo:** [services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py#L221-L271)
- **Função:** `resolve_matrix_product_display(raw_matriz)`
- **Modelo:** `ProductionMatrixCatalog` (tabela de 43 códigos canônicos SCADA 1..43)
- **Regra:** Reutilizar estritamente o helper `resolve_matrix_product_display`. NENHUMA segunda tabela ou dicionário de mapeamento será criado.

---

## 🧩 Proposed Changes

### Módulo Production (`production/`)

#### [MODIFY] [services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py)
- Em `get_dashboard_data()`:
  - **Histórico de Matrizes (`matrix_history`):** Passar a utilizar `resolve_matrix_product_display(rec.matrix_value)["display"]` para preencher o campo `matriz_value` enviado ao template.
  - **Resumo por Matriz (`matrix_summary_map`):** Utilizar `resolve_matrix_product_display(norm_mat)["display"]` na chave `label` do resumo atual.
  - **Cards de Cavidade (`cavities_list`):** Adicionar no dicionário de cada cavidade os campos pre-computados `matriz_nome` (`resolve_matrix_product_display(matriz_val)["display"]`) e `lote_display` (`compose_bladder_lot(prod_val, lote_val)["display"]`).

#### [MODIFY] [dashboard.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/dashboard.html)
- Reformular o bloco de Matriz e Lote do card da prensa (linhas 578-581):
  - **Linha 1 (Bloco 1):** Ícone `<i class="bi bi-bounding-box me-1"></i>` + `Matriz: <strong class="text-dark">{{ cav.matriz_nome }}</strong>`.
  - **Linha 2 (Bloco 2):** Ícone `<i class="bi bi-box-seam me-1"></i>` + `Lote: <strong class="text-dark">{{ cav.lote_display }}</strong>`.

#### [MODIFY] [machine_detail.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/machine_detail.html)
- Reformular o bloco de Matriz e Lote do card da prensa na tela de detalhe da máquina (linhas 182-185):
  - **Linha 1 (Bloco 1):** Ícone `<i class="bi bi-bounding-box me-1"></i>` + `Matriz: <strong class="text-dark">{{ cav.matriz_nome }}</strong>`.
  - **Linha 2 (Bloco 2):** Ícone `<i class="bi bi-box-seam me-1"></i>` + `Lote: <strong class="text-dark">{{ cav.lote_display }}</strong>`.

#### [MODIFY] [tests.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/tests.py)
- Adicionar testes de unidade e integração focados em:
  - Resolução do código 4 e código 29 para seus nomes canônicos no Histórico de Matrizes (sem exibir o código numérico no template/view).
  - Tratamento de fallback para códigos desconhecidos (ex: código `99`).
  - Validação da estrutura dos cards (presença de `matriz_nome` e `lote_display` em linhas separadas).
  - Garantia de não introdução de consultas N+1.

---

## 🧪 Verification Plan

### Automated Tests
- Executar a suíte de testes do módulo de produção:
  ```powershell
  python manage.py test production.tests
  ```
- Executar a verificação geral do Django:
  ```powershell
  python manage.py check
  ```

### Manual Verification
1. Acessar `/producao/`.
2. Verificar a tabela "HISTÓRICO DE MATRIZES" para garantir que a coluna "Matriz" exibe os nomes canônicos (ex: `PNEU READY 100/90-18`, `PNEUS HOPPER 2.75-18`) e não os números `29` ou `4`.
3. Verificar os cards das prensas e cavidades no Dashboard e no Detalhe da Máquina para garantir que a Matriz está na Linha 1 e o Lote do Bladder está na Linha 2.
4. Testar a filtragem por período no Histórico (Hoje, 7d, 30d, personalizado).
