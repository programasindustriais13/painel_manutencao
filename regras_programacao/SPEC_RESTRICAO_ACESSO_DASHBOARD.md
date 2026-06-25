# 🧠 SPEC — RESTRIÇÃO DE ACESSO AO DASHBOARD PARA TÉCNICO LÍDER

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/dashboard/` e `/dashboard/exportar-excel/`
- **Contexto(s):** Dashboard de Gestão da Manutenção e Menu de Navegação.
- **Perfil(s) afetados:** Técnico Líder.

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, o perfil "Técnico Líder" possui permissão para visualizar e acessar a tela de Dashboard. 
- A gestão decidiu alterar a regra de negócios: dados analíticos e KPIs de toda a fábrica agora são de acesso exclusivo do nível gerencial/administrativo (Operador/Administrador).

---

## 🎯 3. OBJETIVO

- Revogar o acesso do Técnico Líder às rotas do dashboard: `/dashboard/` e `/dashboard/exportar-excel/`. 
- Ocultar o botão/link do Dashboard no menu de navegação lateral ou superior caso o usuário logado seja um Técnico Líder.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Nas views `dashboard` e `exportar_relatorio_excel`).
- [base.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/base.html) (No menu principal/navbar).
- [tests.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/tests.py) (Para ajustar e validar testes de permissão).
- [Instrucoes.txt](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/Instrucoes.txt) (Para registrar as alterações).

### Possíveis módulos:
- `maintenance`

---

## 🚫 5. FORA DE ESCOPO

- NÃO alterar as permissões do Técnico Líder em outras telas (ele continua acessando o painel de gerenciamento de técnicos normalmente).
- NÃO alterar a lógica interna de cálculos do Dashboard.
- NÃO duplicar lógica de permissões existente.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ Utilizar o sistema de grupos e permissões nativo do Django (`request.user.groups.filter` ou decorators de permissão).
- ✅ Bloquear a rota no backend (não confiar apenas em esconder o botão no HTML).
- ❌ Não criar novos projetos ou ambientes virtuais.
- ❌ Não duplicar código.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Backend:** As views `dashboard` e `exportar_relatorio_excel` devem utilizar o decorator `@operador_required`. Se um Técnico Líder (ou técnico comum) tentar acessar `/dashboard/` diretamente, deve ser redirecionado para a tela de gerenciamento de técnicos com uma mensagem de erro adequada (comportamento padrão do `@operador_required`).
2. **Frontend:** No template `base.html`, o link `<a>` do dashboard deve ser exibido apenas se o usuário for superusuário, staff, ou pertencer aos grupos `Operadores` ou `Operador`. O grupo `Tecnicos_Lideres` deve ser removido dessa condicional.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Entrar com login de Técnico Líder: o botão "Dashboard" não aparece no menu.
- [ ] Entrar com login de Técnico Líder e digitar `/dashboard/` na URL: o sistema redireciona para `/management/` (ou inicial) e impede o acesso.
- [ ] Entrar com login de Operador/Admin: o botão aparece e o acesso funciona normalmente.
- [ ] Todos os testes automatizados do Django passam com sucesso (`python manage.py test`).

---

## ⚠️ 9. RISCOS

- **Nomenclatura de Grupos:** Garantir que a alteração no frontend remova apenas `Tecnicos_Lideres` mantendo `Operadores` e `Operador` para que Operadores e Administradores continuem com acesso.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Inspecionar o `base.html` e ajustar o `{% if %}` em volta do link do Dashboard para excluir o grupo do Técnico Líder (`Tecnicos_Lideres`).
2. Inspecionar a `views.py` nas funções `dashboard` e `exportar_relatorio_excel`.
3. Alterar seus decorators de `@lider_ou_operador_required` para `@operador_required`.
4. Ajustar os testes em `tests.py` para refletir o novo bloqueio do Técnico Líder no dashboard.
5. Rodar os testes com `python manage.py test`.
6. Atualizar o `Instrucoes.txt`.

---

## 🧪 11. TESTES MANUAIS

1. Logar com Técnico Líder (Tecnico_Lider) e verificar que o botão do Dashboard sumiu da navbar.
2. Digitar `/dashboard/` no navegador como Técnico Líder e garantir que é redirecionado e recebe a mensagem de erro de acesso restrito.
3. Logar com Operador e garantir que o Dashboard e exportar Excel continuam acessíveis e visíveis na navbar.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

O agente DEVE informar no final do processo:
- Arquivos lidos
- Arquivos alterados
- Alterações feitas
- Justificativa

---

# 🤖 USO COM SUBAGENTES

## Ordem obrigatória:

### 1. Arquiteto
Deve analisar e estruturar o plano mínimo de alteração, identificando os pontos de alteração no backend (`views.py`) e frontend (`base.html`).

### 2. Backend
Deve fazer a implementação de backend e frontend conforme especificado.

### 3. QA
Deve validar a implementação rodando os testes automatizados do Django e garantindo que não há regressões ou códigos duplicados.
