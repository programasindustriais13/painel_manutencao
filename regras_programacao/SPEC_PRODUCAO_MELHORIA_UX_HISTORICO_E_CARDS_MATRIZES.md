# 🧠 SPEC — Melhoria de UX no Módulo de Produção (Histórico de Matrizes e Cards de Cavidades)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<id>/` (Dashboard de Produção e Detalhe de Máquina/Prensa).
- **Contexto(s):** Módulo de Produção Industrial (Dashboard de Gestão, Cards de Prensas/Cavidades, Resumo e Histórico de Matrizes).
- **Perfil(s) afetados:** Operador de Produção, Líder, Gerência e Engenharia.

---

## ❗ 2. PROBLEMA ATUAL

1. **Histórico de Matrizes (/producao/):**
   - A coluna "Matriz" na tabela "Histórico de Matrizes" exibe o código numérico bruto (XID) vindo do SCADA-LTS (ex: `29`, `4`).
   - O usuário final/operador não deve visualizar esses códigos numéricos brutos; necessita visualizar o **Nome Canônico da Matriz** (ex: `PNEU READY 100/90-18`, `PNEUS HOPPER 2.75-18`).

2. **Card da Prensa / Cavidade (/producao/ e /producao/maquinas/<id>/):**
   - O card da prensa apresentava o nome da matriz concatenado na mesma linha que o lote do bladder (ex: `Matriz: PNEUS HOPPER 2.75-18 | Lote: 6154 - 161035`).
   - Nomes longos de matriz empurram o lote, geram quebras de linha desalinhadas e dificultam a leitura.

---

## 🎯 3. OBJETIVO

1. **Histórico de Matrizes:**
   - Exibir na coluna "Matriz" o Nome Canônico da Matriz retornado pelo catálogo canônico (`ProductionMatrixCatalog`), omitindo totalmente o código numérico na visualização.
   - Reutilizar obrigatoriamente a Fonte Única de Verdade já existente (`resolve_matrix_product_display`).

2. **Layout do Card da Prensa/Cavidade:**
   - Separar a exibição da Matriz e do Lote em duas linhas/blocos visuais distintos:
     - **Linha 1:** Ícone + "Matriz:" + Nome Completo da Matriz (sem cortar permanentemente, permitindo quebra natural se a tela for muito estreita).
     - **Linha 2:** Ícone + "Lote:" + Lote Completo do Bladder.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos afetados:
- `production/services.py`:
  - `get_dashboard_data()`:
    - Atualizar a montagem de `matrix_history` para resolver o código bruto `rec.matrix_value` usando `resolve_matrix_product_display(rec.matrix_value)["display"]`.
    - Atualizar a montagem de `matrix_summary_map` para utilizar a resolução canônica em `label`.
    - Adicionar os atributos `matriz_nome` e `lote_display` na lista de dicionários `cavities_list` de cada prensa.
- `production/templates/production/dashboard.html`:
  - Atualizar o layout do card da cavidade para renderizar Matriz (Linha 1) e Lote (Linha 2) em blocos separados.
- `production/templates/production/machine_detail.html`:
  - Atualizar o layout do card da cavidade em detalhe da prensa para renderizar Matriz (Linha 1) e Lote (Linha 2) em blocos separados.
- `production/tests.py`:
  - Adicionar testes de unidade e integração cobrindo a exibição do nome canônico no histórico, tratamento de fallback para códigos não cadastrados, layout separado dos cards e prevenção de regressões/N+1.

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar a estrutura de banco de dados (sem migrations).
- NÃO alterar a coleta do SCADA-LTS, nem a lógica de `xid_matriz`, `xid_lote_bladder`, etc.
- NÃO criar novas tabelas, dicionários ou mappings secundários de códigos 1..43.
- NÃO alterar regras de negócio de produção, turno, paradas ou calculo de metas.
- NÃO alterar o banco MySQL do SCADA ou rotas de banco.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ✅ **Fonte Única de Verdade:** `resolve_matrix_product_display(raw_matriz)` em `production/services.py`.
- ✅ Reutilização integral do modelo `ProductionMatrixCatalog` (43 códigos canônicos SCADA).
- ✅ ORM do Django e funções puras em Python.
- ❌ Proibido criar segundo dicionário/tabela de mapeamento.
- ❌ Proibido criar migrations desnecessárias.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Mapeamento de Matriz:**
   - O código SCADA enviado (1..43) é resolvido via `resolve_matrix_product_display`, que consulta `ProductionMatrixCatalog`.
   - Código desconhecido/não cadastrado deve utilizar o fallback padrão retornado pelo service (`"Código não cadastrado: X"` ou `"Não informado"`).
2. **Identificador Interno:**
   - O código numérico bruto continua armazenado no banco (`ProductionCavityMatrixHistory.matrix_value`), mas na interface web é exibido apenas o nome canônico.
3. **Composição do Lote:**
   - A regra de composição do lote do bladder via `compose_bladder_lot` permanece inalterada.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Histórico de Matrizes exibe o nome amigável da matriz e não exibe código numérico.
- [ ] O mapeamento reutiliza `resolve_matrix_product_display` e `ProductionMatrixCatalog`.
- [ ] Não foi criado nenhum segundo mapeamento.
- [ ] Card da prensa exibe Matriz (Linha 1) e Lote (Linha 2) em blocos distintos.
- [ ] Nomes longos de matriz não empurram nem desalinham o campo Lote.
- [ ] O lote completo continua sendo exibido sem perda de informação.
- [ ] Layout responsivo sem truncamento forçado ou quebras arbitrárias no meio de palavras.
- [ ] `python manage.py check` passa sem erros.
- [ ] Todos os testes unitários novos e existentes do módulo `production` passam.

---

## ⚠️ 9. RISCOS

- **Regressão em testes existentes:** Validação do dicionário `matrix_summary` ajustada para manter retrocompatibilidade com a chave `matriz` original contendo o código SCADA.
- **Consultas em loop (N+1):** `ProductionMatrixCatalog` possui apenas 43 registros e é consultado de forma rápida; se necessário, o cache/pre-fetch do catálogo é mantido na camada de serviço.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

### Passo 1: Arquiteto / Análise
- Fonte única de verdade identificada: `resolve_matrix_product_display(raw_matriz)` em `production/services.py`.

### Passo 2: Backend & Services (`production/services.py`)
- Em `get_dashboard_data()`:
  1. Em `cavities_list`: incluir `matriz_nome` (resolvido por `resolve_matrix_product_display`) e `lote_display` (resolvido por `compose_bladder_lot`).
  2. Em `matrix_summary_map`: utilizar `resolve_matrix_product_display(norm_mat)["display"]` para a propriedade `label`.
  3. Em `matrix_history`: utilizar `resolve_matrix_product_display(rec.matrix_value)["display"]` para preencher `matriz_value`.

### Passo 3: Templates (`dashboard.html` e `machine_detail.html`)
- Atualizar a estrutura HTML dos cards de cavidade para colocar Matriz na Linha 1 e Lote na Linha 2 em blocos `<div>` separados.

### Passo 4: Testes Automatizados (`production/tests.py`)
- Criar suíte de testes validando resolução de códigos 4 e 29, códigos desconhecidos, Histórico de Matrizes e regressão de layout dos cards.

---

## 🧪 11. TESTES MANUAIS E QA

1. Acessar `/producao/`.
2. Verificar se o Histórico de Matrizes exibe os nomes canônicos (ex: `PNEU READY 100/90-18`, `PNEUS HOPPER 2.75-18`) e não os números.
3. Verificar se os cards das prensas exibem Matriz na primeira linha e Lote na segunda linha.
4. Alterar os filtros de período do histórico (Hoje, 7d, 30d, personalizado) e validar permanência dos nomes.
5. Testar em tela reduzida/mobile.
