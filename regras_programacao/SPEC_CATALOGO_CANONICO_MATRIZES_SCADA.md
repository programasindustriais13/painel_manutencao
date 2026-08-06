# 🧠 SPEC — CATÁLOGO CANÔNICO DE MATRIZES SCADA

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `regras_programacao/SPEC_CORRECAO_SCHEMA_CICLOS_E_ACUMULADOS.md`
- **URL(s) envolvidas**:
  - `/admin/production/productionmatrixcatalog/`
- **Contexto(s)**: Catálogo oficial dos 43 modelos de matrizes/produtos enviados pelo SCADA.
- **Perfil(s) afetados**: PCP, Líder de Produção, Sistema.

---

## ❗ 2. PROBLEMA ATUAL

O SCADA envia códigos inteiros (1 a 43) identificando matrizes/produtos. Se o agrupamento for feito por string/nome textual ("PNEU..." vs "PNEUS..."), ocorrem inconsistências de agrupamento e fragmentação da produção.

---

## 🎯 3. OBJETIVO

Garantir um catálogo canônico de matrizes no model `ProductionMatrixCatalog` (ou equivalente no app `production`), indexado por `codigo_scada` único ( PositiveSmallIntegerField ), alimentado via carga inicial idempotente com exatamente os 43 códigos oficiais enviados pelo SCADA.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [production/models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/models.py): `ProductionMatrixCatalog`
- [production/migrations/0014_productionmatrixcatalog_productiontarget.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/migrations/0014_productionmatrixcatalog_productiontarget.py)
- Data migration / Command de carga inicial idempotente.

---

## 🚫 5. FORA DE ESCOPO

- ❌ Não agrupar por texto ou nome descritivo.
- ❌ Não mesclar códigos normais com variações `S/C` (ex: código 3 vs 37).
- ❌ Não escrever no banco Scada.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Utilizar Django ORM.
- Carga idempotente (não duplicar nem sobrescrever edições personalizadas válidas de `nome_exibicao`).
- Compatível com SQLite e MySQL.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. `codigo_scada` é a identidade canônica (1 a 43).
2. Produtos com sufixo `S/C` são produtos distintos e possuem seu próprio `codigo_scada`.
3. Códigos desconhecidos (fora de 1..43) preservam o código bruto recebido sem gerar erro nem perder a produção contabilizada, exibindo aviso claro de pendência de classificação.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Exatamente 43 registros cadastrados no banco `default`.
- [ ] `codigo_scada` é único de 1 a 43.
- [ ] Código 3 (HOPPER 90/90-18) é distinto do código 37 (HOPPER 90/90-18 S/C).
- [ ] Carga inicial idempotente.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Sobrescrita de `nome_exibicao` customizado pelo usuário.
- **Mitigação**: Usar `get_or_create` ou `update_or_create` preservando `nome_exibicao` se preenchido.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Verificar se `ProductionMatrixCatalog` atende aos campos requeridos (`codigo_scada`, `nome_scada`, `nome_exibicao`, `ativo`).
2. Criar script/data migration de seed com o dicionário oficial `MATRIZES_SCADA`.
3. Adicionar testes unitários de catálogo e unicidade.

---

## 🧪 11. TESTES AUTOMATIZADOS E MANUAIS

- `test_matrix_catalog_canonical_seed_and_uniqueness`
- `test_unknown_matrix_code_handling`
