# 🧠 SPEC 03A — CORREÇÃO DO ROUTER, TESTES E INTEGRIDADE DE CONFIGURAÇÃO DO MÓDULO DE PRODUÇÃO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/admin/production/` e execução de testes automatizados (`manage.py test`).
- **Contexto(s):** Módulo de Produção — Infraestrutura de roteamento de banco de dados (`ScadaRouter`), integridade de modelos locais e suíte de testes unitários.
- **Perfil(s) afetados:** Administradores, Desenvolvedores e Equipe de QA/SRE.
- **Predecessora:** SPEC 03 (Reprovada na Auditoria / Substituída pela SPEC 03A).

---

## ❗ 2. PROBLEMA ATUAL

1. **ScadaRouter inconsistente e não-determinístico:**
   - Depende de `hints["model"]` em `allow_migrate`, falhando em chamadas históricas ou operações de migration que fornecem apenas `app_label` e `model_name`.
   - `db_for_write` para modelos não gerenciados de `production` retorna `"scada"`, direcionando escritas indevidamente para a base Scada-LTS em vez de bloqueá-las explicitamente.
   - Não valida explicitamente a lista de modelos gerenciados locais por `model_name`.
2. **Suíte de testes com chamadas incorretas do Router e falha de descoberta:**
   - O teste do router envia `hints={"model": Modelo}` de forma incorreta para `allow_migrate`.
   - A descoberta global de testes (`manage.py test`) pode omitir testes do app `production` se as importações não forem absolutas ou o runner não encontrar o módulo.
3. **Falta de constraints de integridade nos modelos locais:**
   - `ProductionCavityConfig` permite nome ou ordem duplicados para a mesma máquina.
   - `ProductionMachineConfig.stale_limit_seconds` aceita valores <= 0 sem validação no banco ou modelo.
4. **Documentação inconsistente em `Instrucoes.txt`:**
   - `Instrucoes.txt` registrou a SPEC 03 como "100% aprovada", omitindo as falhas de auditoria e testes.

---

## 🎯 3. OBJETIVO

1. Refatorar o `ScadaRouter` para utilizar uma lista explícita de `model_name`s gerenciados locais e bloquear categoricamente escritas em modelos não gerenciados com exceção explícita.
2. Corrigir as assinaturas de teste do router e assegurar a descoberta 100% determinística de todos os testes em `production/tests.py` via `python manage.py test`.
3. Adicionar `UniqueConstraint`s para cavidades (`machine_config` + `nome` e `machine_config` + `ordem`) e `CheckConstraint` + `MinValueValidator` (gte=1) para `stale_limit_seconds`.
4. Auditar a base local quanto a registros duplicados antes de aplicar a migration `0002_...`.
5. Gerar e aplicar a migration `0002` exclusivamente no banco `default`.
6. Atualizar a documentação em `Instrucoes.txt` corrigindo o histórico e os status da SPEC 03 e SPEC 03A.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a alterar/criar:
- `production/routers.py`: Refatorar `db_for_read`, `db_for_write`, `allow_migrate` e `allow_relation`.
- `production/models.py`: Adicionar `UniqueConstraint`s em `ProductionCavityConfig` e `MinValueValidator(1)` + `CheckConstraint` em `ProductionMachineConfig`.
- `production/admin.py`: Garantir tratamento adequado das mensagens de erro das novas constraints.
- `production/migrations/0002_cavity_constraints_and_stale_limit.py`: Nova migration exclusivamente aditiva.
- `production/tests.py`: Ajustar importações, corrigir chamadas de `allow_migrate` e expandir testes unitários do router e modelos.
- `Instrucoes.txt`: Atualizar histórico de auditoria e status.
- `regras_programacao/SPEC_PRODUCAO_03A_CORRECAO_ROUTER_TESTES_INTEGRIDADE.md`: Esta SPEC.

---

## 🚫 5. FORA DE ESCOPO

- NÃO iniciar a SPEC 04.
- NÃO criar models de leitura das tabelas do Scada-LTS (`datapoints`, `pointvalues`, `pointvalueannotations`).
- NÃO criar dashboard de dados atuais ou coletor/histórico de paradas.
- NÃO fazer commit nem push no Git.
- NÃO alterar configurações de produção ou `.env`.
- NÃO conectar ao MySQL real do Scada-LTS.
- NÃO editar nem recriar a migration `0001_initial.py`.
- NÃO apagar nem recriar o `db.sqlite3`.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente as diretrizes do `constitution.md`.
- ❌ Não duplicar ambientes virtuais ou apps Django.
- ✅ Manter isolamento completo do banco `scada` (somente leitura / sem migração).
- ✅ Apenas alterações aditivas e reversíveis na base `default`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

### 1. ScadaRouter
- **Modelos locais gerenciados:**
  - `productionmachineconfig`
  - `productioncavityconfig`
  - `productionglobalparameter`
  - `productionglobalalarm`
- **`db_for_read`:**
  - Modelo local gerenciado do app `production` -> `"default"`
  - Modelo não gerenciado de `production` -> `"scada"`
  - Outros apps -> `None`
- **`db_for_write`:**
  - Modelo local gerenciado do app `production` -> `"default"`
  - Modelo não gerenciado de `production` -> Lança exceção `PermissionError("Os modelos do Scada-LTS são estritamente somente-leitura.")`
  - Outros apps -> `None`
- **`allow_migrate`:**
  - `db == "scada"` -> `False`
  - Modelo local gerenciado de `production` -> `True` se `db == "default"` senão `False`
  - Modelo não gerenciado / desconhecido do app `production` -> `False` no banco `default`
  - Outros apps -> `None`
- **`allow_relation`:**
  - `Machine` (maintenance) <-> `ProductionMachineConfig` (production) no banco `default` -> `True`
  - Qualquer relação envolvendo modelo não gerenciado do Scada -> `False`
  - Outros casos -> `None`

### 2. Integridade de Cavidades e Limite Stale
- `ProductionCavityConfig`:
  - `UniqueConstraint(fields=['machine_config', 'nome'], name='uniq_prod_cavity_machine_nome')`
  - `UniqueConstraint(fields=['machine_config', 'ordem'], name='uniq_prod_cavity_machine_ordem')`
- `ProductionMachineConfig`:
  - `stale_limit_seconds`: `MinValueValidator(1)`
  - `CheckConstraint(check=models.Q(stale_limit_seconds__gte=1), name='chk_prod_machine_stale_limit_gte_1')`

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Auditoria de duplicidades no banco local executada sem apontar inconsistências.
- [ ] Migration `0002` gerada e aplicada exclusivamente no banco `default`.
- [ ] `manage.py showmigrations production` indica `0001_initial` e `0002_...` aplicadas em `default`.
- [ ] `manage.py makemigrations --check --dry-run` retorna 0 alterações pendentes.
- [ ] `manage.py check` retorna 0 erros.
- [ ] Todos os testes executados com sucesso em todas as 4 variações de comando (`production.tests`, `production`, `maintenance production`, suíte completa).
- [ ] Nenhuma escrita ou migração enviada ao banco `scada`.
- [ ] Documentação em `Instrucoes.txt` devidamente atualizada com a reprovação da SPEC 03 e aprovação da SPEC 03A.

---

## ⚠️ 9. RISCOS

- **Duplicidades existentes no DB:** Caso o banco local contenha cavidades com mesmo nome/ordem na mesma máquina, o `migrate` falhará. Prevenido pela auditoria prévia obrigatória.
- **Roteamento de migrations em lote:** `allow_migrate` sem `model_name` ou sem `hints` deve tratar graciosamente operações globais como `RunPython` ou `RunSQL`.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. **Auditoria de Duplicidades:** Rodar script/consulta no ORM para checar registros em `ProductionCavityConfig` e `ProductionMachineConfig`.
2. **Refatoração do Router (`production/routers.py`):** Implementar comportamento determinístico por lista de `model_name` e bloqueio de escrita com exceção.
3. **Atualização dos Models (`production/models.py`):** Adicionar validators e constraints.
4. **Geração e Aplicação da Migration `0002`:**
   - `makemigrations --check --dry-run`
   - `makemigrations production`
   - `sqlmigrate production 0002`
   - `migrate --plan --database=default`
   - Backup local de `db.sqlite3`
   - `migrate --database=default`
5. **Atualização da Suíte de Testes (`production/tests.py`):** Ajustar importações absolutas e adicionar novos casos de teste para router e constraints.
6. **Execução de QA e Validação:** Executar os 4 comandos de teste e checagens de integridade.
7. **Atualização do `Instrucoes.txt`:** Registrar a SPEC 03A e ajustar o histórico da SPEC 03.

---

## 🧪 11. TESTES MANUAIS

1. Tentativa de cadastro no Admin de cavidade duplicada na mesma máquina por nome.
2. Tentativa de cadastro no Admin de cavidade duplicada na mesma máquina por ordem.
3. Cadastro de cavidades com mesmo nome/ordem em máquinas diferentes (deve permitir).
4. Cadastro de `stale_limit_seconds = 0` no Admin (deve ser bloqueado pelo validator/constraint).
5. Tentar salvar modelo não gerenciado do Scada diretamente via shell/ORM (deve lançar `PermissionError`).

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

### Arquivos lidos:
- `constitution.md`
- `regras_programacao/SPEC_TEMPLATE.md`
- `PROMPT/PROMPT_EVOLUCAO_MODULO_PRODUCAO_SCADA.md`
- `regras_programacao/SPEC_PRODUCAO_03_CADASTRO_XID_ADMIN.md`
- `production/models.py`
- `production/admin.py`
- `production/routers.py`
- `production/tests.py`
- `production/migrations/0001_initial.py`
- `maintenance/models.py`
- `maintenance_project/settings.py`
- `Instrucoes.txt`

### Arquivos alterados / criados:
- `regras_programacao/SPEC_PRODUCAO_03A_CORRECAO_ROUTER_TESTES_INTEGRIDADE.md` [NOVO]
- `production/routers.py` [MODIFICADO]
- `production/models.py` [MODIFICADO]
- `production/admin.py` [MODIFICADO]
- `production/migrations/0002_...py` [NOVO]
- `production/tests.py` [MODIFICADO]
- `Instrucoes.txt` [MODIFICADO]

---

## 📌 13. PENDÊNCIA ARQUITETURAL E ESCLARECIMENTO SOBRE O ISOLAMENTO DO BANCO SCADA

### 1. Pendência Arquitetural — `LOCAL_MANAGED_MODELS`
- O `ScadaRouter` (`production/routers.py`) mantém a constante de conjunto `LOCAL_MANAGED_MODELS` contendo os modelos locais gerenciados (`productionmachineconfig`, `productioncavityconfig`, `productionglobalparameter`, `productionglobalalarm`).
- **Obrigatoriedade para SPECs Futuras:** Toda SPEC futura que criar um novo modelo local gerenciado (`managed=True`) dentro do app `production` deverá incluir explicitamente o nome desse modelo (em minúsculo) em `LOCAL_MANAGED_MODELS`.
- **SPEC 06:** Esta inclusão será obrigatória principalmente na futura SPEC 06, que criará modelos locais para estado atual e histórico de paradas. Sem essa atualização, o `ScadaRouter` tratará o novo modelo como pertencente ao Scada e bloqueará sua escrita no banco `default`.
- NENHUM desses modelos futuros foi implementado nesta execução.

### 2. Esclarecimento Técnico — Isolamento do Banco Scada
- A tentativa de conexão ao alias `scada` no ambiente de desenvolvimento falhou por razões de autenticação/credenciais (erro MySQL 1045). Essa falha de conexão NÃO constitui prova arquitetural de isolamento.
- **Validação Efetiva:** O isolamento e a impossibilidade de escrita em modelos não gerenciados do Scada foram validados via testes unitários automatizados do `ScadaRouter` (`production/tests.py`), onde escritas em modelos Scada disparam categoricamente `PermissionError`.
- Nenhuma operação de DDL ou DML foi realizada no banco Scada durante esta execução.
- A proteção definitiva contra escrita no banco Scada em ambiente de produção dependerá de um usuário MySQL com permissão estrita de `SELECT` (somente leitura).
- Chamadas explícitas usando `.using("scada")` NÃO devem ser utilizadas para operações de escrita.
- O comando `migrate --database=scada` NÃO deve ser executado sob nenhuma hipótese.

