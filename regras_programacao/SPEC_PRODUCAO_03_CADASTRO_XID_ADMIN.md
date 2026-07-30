# 🧠 SPEC 03 — CADASTRO LOCAL DE XIDs, CAVIDADES, PARÂMETROS E ALARMES NO DJANGO ADMIN

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/admin/production/`
- **Contexto(s):** Módulo de Produção — Estrutura de cadastros e mapeamento de data points do Scada-LTS.
- **Perfil(s) afetados:** Administradores e Operadores com acesso ao Django Admin.
- **Predecessora:** SPEC 02 (Etapa 0 — Auditoria de Estado Atual)

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, não há modelos cadastrais no app `production` para mapear os XIDs do Scada-LTS para máquinas, cavidades ou parâmetros globais.
- O `ScadaRouter` atual (`production/routers.py`) impede qualquer migração do app `production` e roteia todos os seus models para a base `scada`. Isso impede a criação de tabelas locais de cadastro e histórico no banco `default`.

---

## 🎯 3. OBJETIVO

1. Ajustar o `ScadaRouter` para que modelos gerenciados (`managed=True`) do app `production` gravem no banco `default` e permitam migrações apenas no `default`.
2. Criar no app `production` a estrutura de modelos locais para armazenar configurações de XID no banco `default`:
   - `ProductionMachineConfig`: Vínculo 1:1 com `maintenance.Machine`, tempo limite para dado stale, ordem de exibição e XIDs de status da prensa, abertura, motivo de parada e cavidades.
   - `ProductionCavityConfig`: Tabela filha (inline no Admin) para 2 a 4 cavidades por prensa, com nome da cavidade, ordem, XID de produção, XID de meta e XID de motivo.
   - `ProductionGlobalParameter`: Cadastro de XIDs para medições globais (ex: pressão de vácuo, vapor lado 1-7, vapor lado 8-12, ar pneumático).
   - `ProductionGlobalAlarm`: Cadastro de XIDs para alarmes globais (ex: falha de ar, vapor ou vácuo).
3. Registrar todos os modelos no Django Admin com interfaces amigáveis e `StackedInline` / `TabularInline` para cavidades.
4. Executar migration aditiva e reversível no banco `default`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a alterar/criar:
- `production/routers.py` (Ajustar roteamento de modelos `managed=True` para `default`)
- `production/models.py` (Criar os 4 modelos cadastrais acima)
- `production/admin.py` (Registrar os modelos no Django Admin)
- `production/migrations/0001_initial.py` (Nova migration aditiva para o banco `default`)
- `production/tests.py` (Testes unitários dos novos modelos e admin)
- `Instrucoes.txt` (Registro da execução da SPEC 03)

---

## 🚫 5. FORA DE ESCOPO

- NÃO criar models não gerenciados para o Scada-LTS (escopo da SPEC 04).
- NÃO alterar tabelas ou views do app `maintenance`.
- NÃO implementar a visualização em `/producao/` nem a coleta contínua.
- NÃO escrever nada no banco `scada`.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ✅ Manter a compatibilidade SQLite (dev) e MySQL (prod) no banco `default`.
- ✅ Roteamento estrito: Conexão `scada` tem `allow_migrate = False`.
- ✅ Toda alteração no banco `default` é aditiva e reversível.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. Cada `ProductionMachineConfig` refere-se a exatamente uma `Machine` existente (OneToOneField com `on_delete=models.CASCADE`).
2. O cadastro de cavidades deve aceitar de 1 a N cavidades por máquina via `ProductionCavityConfig` (ForeignKey para `ProductionMachineConfig`).
3. XIDs podem ser nulos ou em branco durante o rascunho de cadastro.
4. O `ScadaRouter` verifica `getattr(model._meta, 'managed', True)`: se `False`, redireciona para `scada` e proíbe escrita/migration; se `True`, utiliza `default`.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] `python manage.py makemigrations production` gera a migration apenas para `default`.
- [ ] `python manage.py migrate` aplica as alterações no banco `default` sem interagir com `scada`.
- [ ] É possível cadastrar uma máquina com suas cavidades, parâmetros e alarmes via `/admin/`.
- [ ] Todos os 23 testes existentes + novos testes da SPEC 03 passam sem erros.

---

## ⚠️ 9. RISCOS

- **Router Bypass:** Garantir que o `ScadaRouter` trate corretamente a flag `managed` para não enviar comandos DDL para o Scada MySQL.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Atualizar `production/routers.py`.
2. Criar `production/models.py`.
3. Criar `production/admin.py`.
4. Gerar e aplicar migration aditiva.
5. Adicionar testes unitários em `production/tests.py`.
6. Validar suíte completa de testes e atualizar `Instrucoes.txt`.
