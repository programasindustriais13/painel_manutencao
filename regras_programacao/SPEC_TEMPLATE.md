# 🧠 SPEC — [NOME DA FEATURE OU CORREÇÃO]

---

## 📌 1. CONTEXTO

Descreva rapidamente onde isso acontece no sistema:

- URL(s) envolvidas:
- Contexto(s): (Painel TV, Controle de Técnicos, Dashboard de Gestão, Cadastros/CRUDs)
- Perfil(s) afetados: (Técnico, Técnico Líder, Operador/Líder, Visualizador/TV)

---

## ❗ 2. PROBLEMA ATUAL

Descreva claramente o problema:

- O que está acontecendo hoje?
- O que está incorreto ou incompleto?
- Existe impacto em produção?

---

## 🎯 3. OBJETIVO

Descreva o resultado esperado de forma direta:

- O que deve passar a acontecer?
- Qual comportamento novo deve existir?

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

Liste o que PODE ser alterado:

### Possíveis arquivos:
- models.py
- views.py
- forms.py
- templates
- utils/services
- URLs

### Possíveis módulos:
- maintenance (views, models, templates, forms, etc.)
- maintenance_project (configuração global)

---

## 🚫 5. FORA DE ESCOPO

O que NÃO pode ser alterado:

- Não alterar outras funcionalidades não relacionadas
- Não refatorar o sistema inteiro
- Não criar novos apps sem necessidade
- Não alterar estrutura de banco sem justificativa

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md` :contentReference[oaicite:0]{index=0}

### Regras críticas:

- ❌ Não criar múltiplos ambientes (.venv2, etc)
- ❌ Não duplicar projeto ou apps
- ❌ Não duplicar lógica existente
- ✅ Reutilizar código existente
- ✅ Validar permissões no backend
- ✅ Usar ORM do Django
- ❌ Não usar SQL direto

---

## ⚙️ 7. REGRAS DE NEGÓCIO

Descrever regras específicas da feature:

Exemplo:
- Vínculo só é válido se existir relação com terapeuta
- Frequência só pode ser registrada com vínculo ativo
- Turno deve respeitar cadastro prévio

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

A tarefa só é considerada concluída se:

- [ ] Funcionalidade funciona conforme esperado
- [ ] Não quebrou funcionalidades existentes
- [ ] Permissões respeitadas
- [ ] Interface compreensível para usuário não técnico
- [ ] Compatível com SQLite e MySQL
- [ ] Sem duplicação de dados

---

## ⚠️ 9. RISCOS

Identifique possíveis riscos:

- Impacto em agendamentos existentes
- Quebra de relatórios
- Problemas com permissões
- Inconsistência entre SQLite e MySQL
- Duplicação de registros

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

⚠️ Deve ser definido ANTES de codar

### Passos:

1. Ler código atual relacionado
2. Identificar onde alterar
3. Definir mudanças mínimas
4. Implementar incrementalmente
5. Validar

---

## 🧪 11. TESTES MANUAIS

Descreva passo a passo:

Exemplo:

1. Criar vínculo
2. Editar vínculo
3. Verificar agenda
4. Testar usuário sem permissão
5. Testar dados antigos

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar:

### Arquivos lidos:
- lista de arquivos analisados

### Arquivos alterados:
- lista objetiva

### Alterações feitas:
- o que mudou em cada arquivo

### Justificativa:
- por que cada alteração foi necessária

---

# 🤖 USO COM SUBAGENTES

## Ordem obrigatória:

### 1. Arquiteto
Deve:
- Ler código atual
- Mapear impacto
- Definir plano mínimo

---

### 2. Backend
Deve:
- Implementar apenas o plano
- Alterar somente o necessário

---

### 3. QA
Deve:
- Validar:
  - duplicações
  - permissões
  - consistência
  - regressões

---

## 🚨 REGRA DE PARADA

Se detectar:

- duplicação de código
- múltiplos ambientes
- múltiplos projetos
- implementação paralela

➡️ PARAR imediatamente e corrigir

---

# 🧠 PRINCÍPIO FINAL

> "Alterar o mínimo possível para resolver o problema com segurança."

- Segurança > velocidade  
- Clareza > complexidade  
- Consistência > criatividade  