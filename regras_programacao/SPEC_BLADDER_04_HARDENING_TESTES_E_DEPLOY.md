# 🧠 SPEC — RASTREABILIDADE DE BLADDERS: PARTE 04 — HARDENING, TESTES ABRANGENTES E DEPLOY

---

## 📌 1. CONTEXTO

- **Contexto(s):** Confiabilidade, Resiliência a Resets e Falhas de Rede, Feature Flags, Documentação e Deploy.
- **Perfil(s) afetados:** Administradores do Sistema, Desenvolvedores, Líder de Produção.

---

## ❗ 2. PROBLEMA ATUAL

- A introdução de novas regras de rastreabilidade de insumos exige garantias de não-regressão, tratamento de reinícios do coletor, concorrência e facilidade de rollback/ativação segura via feature flags.

---

## 🎯 3. OBJETIVO

1. Configurar Feature Flags seguras no projeto:
   - `PRODUCTION_BLADDER_TRACKING_ENABLED`
   - `PRODUCTION_BLADDER_VALIDATION_ENABLED`
2. Adicionar testes exaustivos de:
   - Reinício do coletor e recuperação de estado;
   - Retry e duplicidade de timestamps;
   - Resets sucessivos de contadores;
   - Transições de máquinas e cavidades;
   - Regressão do módulo PCP, metas, paradas de cavidades e TV dashboard.
3. Atualizar a documentação técnica em `Instrucoes.txt` e produzir manual operacional sucinto para o Líder de Produção.
4. Estruturar a estratégia de migration, backup, deploy e rollback.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `maintenance_project/settings.py`
- `.env.example`
- `production/services.py`
- `production/tests.py`
- `Instrucoes.txt`
- `walkthrough.md`

---

## 🚫 5. FORA DE ESCOPO

- Não executar deploy ou migrations automaticamente no servidor de produção.
- Não alterar dependências externas no `requirements.txt` desnecessariamente.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- 100% dos testes do projeto passando.
- Suporte estrito a SQLite e MySQL.
- Sem perda de dados históricos existentes.

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO

- [ ] Todas as feature flags funcionais e com fallback seguro quando desativadas.
- [ ] Testes de robustez, reset, retry e regressão executados com 100% de sucesso.
- [ ] `manage.py check` e `manage.py test` sem nenhum erro.
- [ ] `Instrucoes.txt` devidamente atualizado.
