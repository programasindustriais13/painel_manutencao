# 🧠 SPEC — Carga Inicial Idempotente do Catálogo Canônico de Matrizes SCADA (Migration 0018)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/catalogos/matrizes/`, `/producao/plano-turno/`, dashboards de produção.
- **Contexto(s):** Módulo de Produção / PCP / Integração SCADA.
- **Perfil(s) afetados:** Operador/Líder, PCP, Sistema (Coletor SCADA).

---

## ❗ 2. PROBLEMA ATUAL

Em ambiente de produção, ao executar `python manage.py migrate`, as migrações `0014` e `0015` criam a tabela `production_productionmatrixcatalog`, mas a tabela permanece completamente vazia (`ProductionMatrixCatalog.objects.count() == 0`).

Não havia uma data migration (`RunPython`) encadeada nas migrações do aplicativo `production`, fazendo com que a inicialização do catálogo dependesse da execução manual de um management command CLI (`seed_matrix_catalog`), o que causa falha de integridade em deployments automatizados.

---

## 🎯 3. OBJETIVO

Garantir que a execução de `python manage.py migrate` popule automaticamente e de forma idempotente o modelo `ProductionMatrixCatalog` com exatamente os 43 códigos e nomes canônicos das matrizes oficiais do SCADA.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos criados / modificados:
- `regras_programacao/SPEC_CARGA_INICIAL_CATALOGO_MATRIZES.md` [NEW]
- `production/migrations/0018_seed_matrix_catalog.py` [NEW]
- `production/tests.py` [MODIFY]
- `Instrucoes.txt` [MODIFY]

---

## 🚫 5. FORA DE ESCOPO

- Não alterar as migrações `0014`, `0015`, `0016` ou `0017` já aplicadas.
- Não apagar nem sobrescrever registros preexistentes ou nomes de exibição personalizados por administradores.
- Não realizar qualquer operação de escrita no banco de dados do SCADA-LTS.
- Não alterar a estrutura das tabelas existentes.
- Não realizar git commit, push ou deploy.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Usar ORM do Django.
- Manter compatibilidade obrigatória com SQLite e MySQL.
- Roteamento seguro de multi-bancos (`schema_editor.connection.alias` operando exclusivamente no banco `default`).
- Idempotência: rodar a migração 1 ou N vezes produz o mesmo resultado no banco.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. O código do SCADA (`codigo_scada`, inteiro de 1 a 43) é a chave primária/identidade canônica da matriz.
2. Mapeamento oficial dos 43 modelos:
   - 1: PNEUS WINGS 90/90-18
   - 2: PNEUS WINGS 2.75-18
   - 3: PNEUS HOPPER 90/90-18
   - 4: PNEUS HOPPER 2.75-18
   - 5: PNEUS READY 110/90-18
   - 6: PNEUS HOPPER 4.10-18
   - 7: PNEUS HOPPER 110/90-17
   - 8: PNEU HOPPER 90/90-19
   - 9: PNEUS WINGS 80/100-14
   - 10: PNEUS WINGS 60/100-17
   - 11: PNEUS READY 90/90-18
   - 12: PNEU READY 2.75-17
   - 13: PNEU READY 110/80-14
   - 14: PNEU OPTION 90/90-18
   - 15: PNEU HOPPER 4.80/4.00-08
   - 16: PNEU HOPPER 80/100-14
   - 17: PNEU HOPPER 2.50-17
   - 18: PNEU SPEEDY 90/90-18
   - 19: PNEU SPEEDY 2.75-18
   - 20: PNEU ROBOT 3.25-08
   - 21: PNEU HOPPER 2.75-17
   - 22: PNEU HOPPER 120/80-18
   - 23: PNEU HOPPER 90/90-21
   - 24: PNEU WINTER 100/100-18
   - 25: PNEU WINTER 90/90-21
   - 26: PNEU HOPPER 100/90-18
   - 27: PNEU HOPPER 80/100-18
   - 28: PNEU SPEEDY 100/90-18
   - 29: PNEU READY 100/90-18
   - 30: PNEU READY 80/100-18
   - 31: PNEU HOPPER 100/80-18
   - 32: PNEU HOPPER 100/90-18 S/C
   - 33: PNEU HOPPER 80/100-18 S/C
   - 34: PNEU SPEEDY 100/90-18 S/C
   - 35: PNEU READY 100/90-18 S/C
   - 36: PNEU READY 80/100-18 S/C
   - 37: PNEU HOPPER 90/90-18 S/C
   - 38: PNEU HOPPER 2.75-18 S/C
   - 39: PNEU READY 90/90-18 S/C
   - 40: PNEU WINGS 90/90-18 S/C
   - 41: PNEU WINGS 2.75-18 S/C
   - 42: PNEU SPEEDY 90/90-18 S/C
   - 43: PNEU SPEEDY 2.75-18 S/C
3. Modelos com "S/C" (Sem Câmara) são registros distintos dos modelos sem "S/C" (ex: Código 3 vs Código 37).
4. Se o registro já existir, seus valores personalizados em `nome_exibicao` devem ser preservados.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] `ProductionMatrixCatalog.objects.count() == 43` em banco limpo pós-migrate.
- [ ] Idempotência confirmada sem duplicação de registros.
- [ ] Código 1 e 43 populados corretamente.
- [ ] Códigos únicos de 1 a 43.
- [ ] `nome_exibicao` personalizado não é apagado ou sobrescrito.
- [ ] Sem escritas no banco `scada`.
- [ ] `manage.py check` sem erros.
- [ ] `makemigrations --check` sem migrações pendentes.
- [ ] Suíte de testes do app `production` 100% aprovada.
