# PROMPT — FASE 1: PORTAL PÓS-LOGIN & ROTEAMENTO ENTRE MÓDULOS

## 📌 Contexto & Objetivo
Atualmente, após o login, os usuários são redirecionados automaticamente pela função `home_redirect`. Além disso, no cabeçalho do módulo de Produção (`base_production.html`), o logo clica em `home_redirect`, o que expulsa usuários com privilégios de operador de volta para a Manutenção.

Nesta Fase 1, vamos implementar:
1. **Correção do link do logo/título no módulo de Produção.**
2. **Tela de Seleção de Módulo Pós-Login ("Hub / Portal de Entrada").**
3. **Regras inteligentes de bypass automático de perfil.**
4. **Atalho de alternância rápida de módulo no cabeçalho para usuários híbridos.**

---

## 🔒 Regras da Constituição a Seguir
- Apenas 1 ambiente virtual (`.venv`).
- Toda verificação de permissão deve ser feita no **Backend** (Django views e decorators).
- Layout responsivo e elegante, em Português (pt-br).
- Registrar resumo das alterações em `Instrucoes.txt`.

---

## 🛠️ Especificações Técnicas Detalhadas

### 1. Correção do Link do Logo na Produção
- **Arquivo:** `production/templates/production/base_production.html`
- **Ação:** Alterar o `href` do elemento `.navbar-brand` (logo/título "PAINEL PRODUÇÃO") de `{% url 'home_redirect' %}` para `{% url 'production:dashboard' %}`.

### 2. Helpers de Permissão e Roteamento (`maintenance/views.py`)
Criar ou refatorar funções auxiliares de detecção de permissão:
- `_user_can_access_maintenance(user)`:
  - Retorna `True` se for `superuser`, `staff`, pertencer aos grupos `['Operadores', 'Operador', 'Tecnicos_Lideres', 'Tecnicos']` ou possuir `technician_profile`.
- `_user_can_access_production(user)`:
  - Retorna `True` se for `superuser`, `staff`, pertencer ao grupo `'Liderança de Produção'`, `'Operadores'`, `'Operador'` ou grupo de PCP.
- `_user_has_dual_access(user)`:
  - Retorna `True` se o usuário tem permissão para **AMBOS** os módulos.

### 3. Nova View e Rota do Portal (`portal_select`)
- **Rota:** `/portal/` (nome: `portal_select`) protegida por `@login_required`.
- **Comportamento de `home_redirect`:**
  - Se o usuário tem acesso apenas à Manutenção: redireciona para `technician_management` (se técnico) ou `dashboard` (se operador de manutenção).
  - Se o usuário tem acesso apenas à Produção: redireciona para `production:dashboard`.
  - Se o usuário tem acesso aos dois módulos: redireciona para `portal_select`.
  - Se for usuário de TV (`username='tv'` ou grupo `Visualizador`): redireciona para `tv_dashboard`.
- **View `portal_select`:**
  - Se um usuário sem acesso duplo tentar acessar diretamente `/portal/`, redireciona-o automaticamente para o único módulo ao qual tem direito.
  - Renderiza o template `maintenance/portal_select.html`.

### 4. Template `maintenance/portal_select.html`
- **Design:** Tela moderna, limpa, responsiva (estilo Hub de Sistemas), centralizada, com saudação ao usuário logado, botão de logout e dois grandes cards interativos com efeitos de hover/transição:
  - **Card 1 — Painel de Manutenção:**
    - Ícone de engrenagem / ferramentas (`bi-tools` / `bi-wrench`).
    - Título: **Manutenção Industrial**
    - Descrição: Gestão de técnicos, atendimentos em tempo real, painel de TV, indicadores e ordens de serviço.
    - Botão de ação: **Acessar Manutenção** (leva para `dashboard` ou `technician_management`).
  - **Card 2 — Painel de Produção:**
    - Ícone de indústria / CPU (`bi-cpu` / `bi-gear-wide-connected`).
    - Título: **Produção & PCP**
    - Descrição: Acompanhamento de máquinas, cavidades, planos de turno, metas, matrizes e bladders.
    - Botão de ação: **Acessar Produção** (leva para `production:dashboard`).

### 5. Alternância Rápida de Módulos nos Menus Superiores
- Em `maintenance/templates/maintenance/base.html` e `production/templates/production/base_production.html`:
  - Se `_user_has_dual_access(request.user)` for verdadeiro, exibir no menu do usuário ou na barra superior o link/botão:
    - `"Trocar para Produção"` (quando estiver na Manutenção).
    - `"Trocar para Manutenção"` (quando estiver na Produção).
    - `"Portal de Módulos"` (para voltar ao seletor).

---

## 🧪 Critérios de Aceite e Validação
1. Login com usuário apenas **Técnico** (`tecnico1`): Vai direto para a tela de técnicos (`/management/`), sem passar pelo portal.
2. Login com usuário apenas **Líder de Produção** (`lider_prod`): Vai direto para o `/producao/`, sem passar pelo portal.
3. Login com **Operador / Administrador** (`admin`): Vai para `/portal/` e exibe os dois cards funcionais.
4. Ao clicar no logo "PAINEL PRODUÇÃO" dentro do módulo de produção, o usuário permanece na home de produção e não é jogado para a manutenção.
5. Links de alternância rápida na navbar funcionam perfeitamente para quem tem acesso duplo.
6. Atualização registrada em `Instrucoes.txt`.
