# 🧠 SPEC — Correção Semântica do Produto/Matriz e Composição do Lote Completo do Bladder

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/maquinas/<machine_id>/cavidades/<cavity_id>/` (Detalhes da Cavidade)
  - `/producao/maquinas/<machine_id>/` (Detalhes da Prensa)
  - `/producao/` (Dashboard de Produção)
  - `/admin/production/productioncavityconfig/` (Admin Django - Configuração de Cavidades)
- **Contexto:** Módulo de Produção Industrial / SCADA
- **Perfis afetados:** Operador, Líder de Produção, PCP, Manutenção, Administrador.

---

## ❗ 2. PROBLEMA ATUAL

A auditoria operacional e técnica confirmou que o campo `xid_produto` em `ProductionCavityConfig` **NÃO** representa isoladamente o produto fabricado:
1. `xid_produto` é a primeira parte (prefixo) do identificador do lote do bladder (ex: `6154`).
2. `xid_lote_bladder` é a segunda parte (número) do identificador do lote do bladder (ex: `161046`).
3. O lote completo do bladder é a junção das duas partes: `6154 - 161046`. A separação ocorre por limitações de leitura de registradores PLC no SCADA.
4. O produto/modelo fabricado é identificado exclusivamente através do código da matriz (`xid_matriz`), traduzido pelo **Catálogo Canônico dos 43 Modelos de Matrizes do SCADA** (`ProductionMatrixCatalog`).
5. O template `cavity_detail.html` possui o texto hardcoded `"Produto Em Furo"` associado erroneamente apenas ao `xid_produto`.

---

## 🎯 3. OBJETIVO

1. **Remover** o conceito incorreto "Produto Em Furo" da interface e codebase.
2. **Apresentar a Matriz / Produto em Produção** derivado do `xid_matriz` traduzido pelo catálogo canônico dos 43 modelos do SCADA.
3. **Compor o Lote Completo do Bladder** combinando `xid_produto` (prefixo) e `xid_lote_bladder` (número) no formato `6154 - 161046`.
4. **Implementar Fallbacks Seguros** para lotes incompletos (com indicação visual discreta) e matrizes ausentes/não cadastradas.
5. **Atualizar os rótulos e help_texts no Admin Django** sem realizar renames destrutivos de colunas no banco de dados.
6. **Encapsular a regra de composição** em serviço reutilizável no backend (`services.py`).
7. **Garantir compatibilidade** total com SQLite e MySQL, mantendo o banco `scada` como estritamente somente leitura.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos permitidos:
- [production/models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/models.py) (verbose_name e help_text de `xid_produto`, `xid_lote_bladder`, `xid_matriz`)
- [production/services.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/services.py) (funções de composição do lote, tradução de matriz/produto, alteração do contexto da cavidade, dashboard e máquina)
- [production/admin.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/admin.py) (ajuste de fieldsets, list_display e help_texts no admin)
- [production/templates/production/cavity_detail.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/cavity_detail.html) (substituição dos 3 cards pelos 2 cards corretos)
- [production/tests.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/tests.py) (atualização dos testes existentes e novos testes unitários/integrados)
- [production/migrations/](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/migrations/) (nova migration não destrutiva para verbose_name/help_text se necessário)
- [Instrucoes.txt](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/Instrucoes.txt) (documentação do ajuste semântico)

---

## 🚫 5. FORA DE ESCOPO

- Não criar novo projeto, app Django, ambiente virtual ou coletor SCADA.
- Não renomear fisicamente as colunas do banco de dados `xid_produto` ou `xid_lote_bladder`.
- Não alterar a tabela PLC nem realizar escritas no banco `scada`.
- Não utilizar SQL direto.
- Não remover zeros à esquerda das partes do lote.
- Não concatenar dados externos além do hífen separador `" - "`.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION & SECURITY)

- Manter compatibilidade com `default` (SQLite local / MySQL servidor) e `scada` (somente leitura).
- Respeitar o `ScadaRouter` impedindo qualquer migration ou escrita no banco `scada`.
- Respeitar a orquestração dos subagentes: Arquiteto -> Backend -> QA.

---

## ⚙️ 7. REGRAS DE NEGÓCIO E COMPOSIÇÃO

### 7.1. Matriz / Produto em Produção
- **Fontes:** `xid_matriz` -> SCADA -> `ProductionMatrixCatalog` (43 modelos).
- **Formatos de Exibição:**
  - Código no catálogo: Ex: `PNEUS HOPPER 90/90-18`
  - Código ausente / leitura None: `Não informado`
  - Código lido mas não existente no catálogo (ex: 99): `Código não cadastrado: 99`

### 7.2. Lote Completo do Bladder
- **Fontes:** `xid_produto` (Prefixo/Parte 1) + `xid_lote_bladder` (Número/Parte 2).
- **Serviço Helper (`compose_bladder_lot`):**
  ```python
  def compose_bladder_lot(prefix: Optional[str], number: Optional[str]) -> Dict[str, Any]:
      ...
  ```
- **Matriz de Fallbacks do Lote:**
  - Duas partes disponíveis (`"6154"`, `"161046"`): `"6154 - 161046"`, `is_complete=True`, `status="COMPLETO"`
  - Parte 1 disponível, Parte 2 ausente (`"6154"`, `""`): `"6154 - Não informado"`, `is_complete=False`, `status="INCOMPLETO"` + badge visual `Lote incompleto`
  - Parte 1 ausente, Parte 2 disponível (`""`, `"161046"`): `"Não informado - 161046"`, `is_complete=False`, `status="INCOMPLETO"` + badge visual `Lote incompleto`
  - Duas partes ausentes (`""`, `""`): `"Não informado"`, `is_complete=False`, `status="AUSENTE"`

### 7.3. Preservação de Dados
- Não converter partes para `int` de forma a perder zeros à esquerda (ex: `"06154"` deve permanecer `"06154"`).
- Remover apenas espaços nas extremidades (`strip()`).
- Não exibir `None - None`, `-`, ou espaços duplicados.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Texto "Produto Em Furo" removido de 100% da interface e codebase.
- [ ] Card 1 na tela de cavidade exibe "Matriz / Produto em Produção" usando tradução do catálogo dos 43 modelos.
- [ ] Card 2 exibe "Lote Completo do Bladder" unindo as duas partes com fallbacks corretos e badge para lotes incompletos.
- [ ] O Admin de Cavidades exibe rótulos e help_texts explicativos para a 1ª e 2ª parte do lote e para a matriz.
- [ ] Nenhuma migration gerada afeta a tabela `scada` nem realiza alterações destrutivas no banco `default`.
- [ ] Todos os 126+ testes existentes continuam passando e novos testes cobrem a composição e fallbacks.
- [ ] Nenhuma consulta adicional ao SCADA é gerada (desempenho mantido).

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco:** Quebra de testes legados que buscavam "Produto Em Furo" ou utilizavam `produto` isoladamente.
  - **Mitigação:** Atualizar as asserções de teste para validar "Matriz / Produto em Produção" e "Lote Completo do Bladder".
- **Risco:** Perda de zeros à esquerda na composição do lote.
  - **Mitigação:** Tratar as partes estritamente como strings sanitizadas no helper de composição.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

### Subagente 1: Arquiteto
- Mapeamento das estruturas e definição das assinaturas de serviço helper.
- Revisão do impacto no Admin, View da Cavidade, Dashboard e Históricos.

### Subagente 2: Backend
- Atualização do `ProductionCavityConfig` em `models.py` (`verbose_name` e `help_text`).
- Execução de `makemigrations` e `migrate` no banco `default`.
- Implementação de `compose_bladder_lot` e `resolve_matrix_product_display` em `services.py`.
- Atualização de `get_cavity_detail_context`, `get_dashboard_data` e `get_machine_detail_data`.
- Atualização do template `cavity_detail.html` (FASE 3).
- Atualização e criação de suíte de testes unitários e de integração em `tests.py`.

### Subagente 3: QA
- Validação do `manage.py check` e `makemigrations --check`.
- Execução completa da suíte de testes com registro de evidências.
- Verificação de ausência de escritas no banco `scada`.

---

## 🧪 11. TESTES MANUAIS E VERIFICAÇÕES

1. Cadastrar XID Matriz = 3, Prefixo Lote = 6154, Número Lote = 161046.
2. Acessar cavidade e verificar:
   - Card 1: `Matriz / Produto em Produção` -> `PNEUS HOPPER 90/90-18`
   - Card 2: `Lote Completo do Bladder` -> `6154 - 161046`
3. Testar caso de matriz desconhecida (ex: 99) -> `Código não cadastrado: 99`.
4. Testar caso de lote incompleto -> `6154 - Não informado` + badge `Lote incompleto`.
5. Testar preservação de zeros -> `"06154 - 00123"`.
6. Verificar Admin Django em `/admin/production/productioncavityconfig/`.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

- **Arquivos lidos:** `constitution.md`, `regras_programacao/SPEC_TEMPLATE.md`, `production/models.py`, `production/services.py`, `production/admin.py`, `production/forms.py`, `production/templates/production/cavity_detail.html`, `production/management/commands/seed_matrix_catalog.py`, `production/routers.py`, `Instrucoes.txt`.
- **Arquivos a alterar:** `production/models.py`, `production/services.py`, `production/admin.py`, `production/templates/production/cavity_detail.html`, `production/tests.py`, `Instrucoes.txt`.
- **Migrations geradas:** Migration de atualização de `verbose_name` e `help_text`.
