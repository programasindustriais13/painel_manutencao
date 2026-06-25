# 🧠 SPEC — ATUALIZAÇÃO E BLINDAGEM DO ARQUIVO .GITIGNORE

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** N/A (Configuração de Repositório)
- **Contexto(s):** Controle de Versão e Segurança do Código
- **Perfil(s) afetados:** Desenvolvedor / Arquiteto

---

## ❗ 2. PROBLEMA ATUAL

- Durante a implementação do microserviço Node.js (Fase 2 do WhatsApp), a pasta `whatsapp_service/node_modules/` foi acidentalmente rastreada pelo Git, causando alertas de segurança no GitHub e deixando o repositório extremamente pesado.
- Precisamos garantir que o arquivo `.gitignore` esteja configurado corretamente para bloquear essa pasta e outros arquivos sensíveis que não devem ir para produção.

---

## 🎯 3. OBJETIVO

- Atualizar (ou criar, se não existir) o arquivo `.gitignore` na raiz do projeto, adicionando bloqueios explícitos para as dependências do Node.js do nosso novo microserviço, além de garantir as boas práticas do ecossistema Django/Python.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [.gitignore](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/.gitignore)

### Possíveis módulos:
- N/A

---

## 🚫 5. FORA DE ESCOPO

- NÃO apagar a pasta `node_modules` fisicamente do disco local (ela é necessária para rodar o projeto).
- NÃO alterar código Python, HTML ou JavaScript.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Trabalhar apenas no arquivo existente `.gitignore`.
- ❌ Não duplicar projetos ou criar novos ambientes virtuais.
- ❌ Alterar o mínimo possível para resolver o problema com segurança.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

Adicionar (ou verificar se já existem) as seguintes linhas no `.gitignore`:

1. **Microserviço WhatsApp:**
   - `whatsapp_service/node_modules/`
   - `whatsapp_service/package-lock.json`
2. **Ambiente Python/Django (Boas Práticas):**
   - `__pycache__/`
   - `*.pyc`
   - `.venv/` ou `venv/`
   - `.env`
   - `db.sqlite3` (Apenas se a regra do projeto ditar que o banco de dados de desenvolvimento não deve subir, caso contrário, manter comentado).

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

A tarefa só é considerada concluída se:
- [ ] O arquivo `.gitignore` contém a regra explícita para ignorar o `node_modules` dentro do `whatsapp_service`.
- [ ] O arquivo `.gitignore` contém a regra para ignorar o `package-lock.json` dentro do `whatsapp_service`.
- [ ] Os padrões básicos de Django/Python estão mantidos e protegidos.

---

## ⚠️ 9. RISCOS

- Risco mínimo. Apenas garantir que caminhos de arquivos válidos e necessários ao projeto não sejam ignorados erroneamente.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Ler o arquivo `.gitignore` atual na raiz.
2. Adicionar as linhas referentes ao ecossistema Node.js e garantir a proteção do Python.
3. Salvar o arquivo `.gitignore`.
4. Registrar as alterações no arquivo `Instrucoes.txt`.

---

## 🧪 11. TESTES MANUAIS

1. Executar `git status` para verificar se os arquivos de `whatsapp_service/node_modules/` não estão mais sendo rastreados ou exibidos como novos arquivos não rastreados.
2. Garantir que o próprio `.gitignore` é listado como modificado no Git.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar no final do processo:
- Arquivos lidos
- Arquivos alterados
- Alterações feitas
- Justificativa
