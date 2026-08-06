# 🧠 SPEC — CORREÇÃO DO SCHEMA DE CICLOS E ACUMULADOS

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `regras_programacao/SPEC_PRODUCAO_07B_ACUMULO_PRODUCAO_COM_RESETS.md`
- **URL(s) envolvidas**:
  - `/admin/production/productioncycle/`
  - `/admin/production/productionshiftaccumulated/`
- **Contexto(s)**: Reconciliação DDL do schema do app `production` e integridade física de tabelas no banco `default`.
- **Perfil(s) afetados**: Administrador, Sistema, Desenvolvedor.

---

## ❗ 2. PROBLEMA ATUAL

As migrations `0013` e `0014` constavam registradas na tabela `django_migrations` no banco `db.sqlite3`, contudo as tabelas físicas `production_productioncycle` e `production_productionshiftaccumulated` não estavam fisicamente presentes no arquivo SQLite, resultando em erros de runtime `OperationalError: no such table`.

---

## 🎯 3. OBJETIVO

Reconciliar com segurança o schema físico do banco local `default` sem alterar registros em `django_migrations`, sem utilizar `--fake`, sem executar SQL direto arbitrário e sem excluir o banco SQLite.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [production/management/commands/repair_production_schema.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/management/commands/repair_production_schema.py)
- [production/routers.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/routers.py)
- [production/admin.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/admin.py)

---

## 🚫 5. FORA DE ESCOPO

- ❌ Não utilizar `--fake` ou `--fake-initial`.
- ❌ Não excluir o banco `db.sqlite3`.
- ❌ Não apagar nem alterar migrations já aplicadas.
- ❌ Não realizar nenhuma alteração no alias `scada` (MySQL).

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Utilizar a API oficial do Django ORM `connection.schema_editor()`.
- Garantir isolamento do banco Scada.
- Respeitar 100% de aprovação na suíte de testes.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. `ProductionCycle` e `ProductionShiftAccumulated` são modelos gerenciados no banco `default`.
2. As tabelas físicas devem existir para que o Django Admin e as views de acúmulo consultem dados sem exceção.
3. As operações DDL devem ser idempotentes.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [x] As tabelas `production_productioncycle` e `production_productionshiftaccumulated` existem no SQLite local.
- [x] O Django Admin `/admin/production/productioncycle/` abre com HTTP 200.
- [x] O Django Admin `/admin/production/productionshiftaccumulated/` abre com HTTP 200.
- [x] `manage.py check` passa sem alertas.
- [x] `makemigrations production --check --dry-run` não detecta alterações pendentes.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco**: Incompatibilidade entre os campos do model e a tabela gerada.
- **Mitigação**: O `SchemaEditor` lê os campos exatos da classe do model Django, garantindo 100% de alinhamento com a migration.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Executar inspeção via `connection.introspection.table_names()`.
2. Disparar `schema_editor.create_model` para models fisicamente ausentes.
3. Validar acesso aos Admins e execução de testes.

---

## 🧪 11. TESTES AUTOMATIZADOS E MANUAIS

- `manage.py test production`
- Acesso HTTP via Client de Teste a ambas as URLs do Admin.

---

## 🛑 12. GATE DE SAÍDA E REGRA DE PARADA

- Gate: HTTP 200 nas duas rotas Admin e 100% de testes verdes.
