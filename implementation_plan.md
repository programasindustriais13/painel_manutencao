# 🧠 Implementation Plan — Fechamento e Checkpoint das SPECs 03 e 03A

## 🎯 Objetivo
Registrar o fechamento documental e a auditoria técnica do módulo de Produção / Scada-LTS referente às SPECs 03 e 03A, consolidando a criação do checkpoint Git seguro sem implementar funcionalidades da SPEC 04.

---

## 📌 Pendências Arquiteturais

### 1. Atualização do `LOCAL_MANAGED_MODELS` em SPECs Futuras
- O `ScadaRouter` (`production/routers.py`) mantém a constante de classe `LOCAL_MANAGED_MODELS` contendo a lista estrita dos modelos gerenciados locais do app `production`:
  - `productionmachineconfig`
  - `productioncavityconfig`
  - `productionglobalparameter`
  - `productionglobalalarm`
- **Regra Obrigatória:** Toda SPEC futura que criar um novo model local gerenciado (`managed=True`) dentro do app `production` DEVERÁ incluir explicitamente o nome desse modelo (em minúsculas) no conjunto `LOCAL_MANAGED_MODELS`.
- **SPEC 06:** Essa atualização será estritamente obrigatória na futura SPEC 06, quando forem criados os modelos locais para estado atual e histórico de paradas. Sem essa inclusão em `LOCAL_MANAGED_MODELS`, o router tratará o novo modelo como pertencente ao banco Scada e bloqueará categoricamente sua escrita no banco `default`.
- NENHUM modelo da SPEC 04 ou SPEC 06 foi criado nesta execução.

---

## 🔐 Esclarecimento sobre Isolamento do Banco Scada

1. A tentativa de conexão ao alias `scada` no ambiente de desenvolvimento falhou por conta de autenticação/credenciais (erro MySQL 1045). Essa falha de conexão não é prova arquitetural de isolamento.
2. O isolamento e a impossibilidade de escrita em modelos não gerenciados foram validados via suíte de testes unitários do router (`production/tests.py`), na qual chamadas de escrita para modelos Scada disparam categoricamente `PermissionError`.
3. Nenhuma operação DDL ou DML foi realizada no banco Scada durante os testes ou migrações.
4. A proteção definitiva em produção dependerá da criação de um usuário MySQL com privilégios exclusivos de `SELECT`.
5. Chamadas explícitas usando `.using("scada")` jamais devem ser utilizadas para escrita.
6. O comando `migrate --database=scada` não deve ser executado sob nenhuma hipótese.

---

## 📦 Estrutura dos Commits de Checkpoint

### Commit 1 (Implementação):
`feat(production): adiciona cadastros Scada e protege roteamento de bancos`
- `production/__init__.py`
- `production/models.py`
- `production/admin.py`
- `production/routers.py`
- `production/tests.py`
- `production/migrations/__init__.py`
- `production/migrations/0001_initial.py`
- `production/migrations/0002_alter_productionmachineconfig_stale_limit_seconds_and_more.py`
- `.gitignore` (regra `db.sqlite3.bak*`)

### Commit 2 (Documentação):
`docs(production): registra SPECs e arquitetura da integração Scada`
- `regras_programacao/SPEC_PRODUCAO_03_CADASTRO_XID_ADMIN.md`
- `regras_programacao/SPEC_PRODUCAO_03A_CORRECAO_ROUTER_TESTES_INTEGRIDADE.md`
- `PROMPT/DOCUMENTACAO_MYSQL_SCADALTS_PAINEL_SINOTICO(1).md`
- `PROMPT/PLANO_RECOMENDADO_PRODUCAO_SCADA.md`
- `PROMPT/PROMPT_EVOLUCAO_MODULO_PRODUCAO_SCADA.md`
- `resumo_gemini.md`
- `Instrucoes.txt`
- `implementation_plan.md`

---

## 🧪 Plano de Validação
- `python manage.py check`: 0 erros
- `python manage.py makemigrations --check --dry-run`: 0 migrações pendentes
- `python manage.py showmigrations production`: `0001` e `0002` aplicadas no `default`
- `python manage.py migrate --plan --database=default`: Nenhuma operação pendente
- `python manage.py test`: 47 testes aprovados (23 maintenance + 24 production)
