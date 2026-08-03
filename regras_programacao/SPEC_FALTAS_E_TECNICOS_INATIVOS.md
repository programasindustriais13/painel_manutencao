# 🧠 SPEC — Faltas (Justificada/Não Justificada) e Técnicos Inativos

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** 
  - `/management/` (Controle de Técnicos)
  - `/tv/` (Painel TV)
  - `/dashboard/` (Dashboard de Gestão)
  - `/cruds/` (Configurações e Cadastros de Técnicos)
  - `/admin/` (Django Admin — Cadastro de Técnicos)
  - `/technicians/<id>/start/` (Início de Alocação / Ordem de Serviço)
  - `/technicians/<id>/availability/` (Alteração de Escala / Disponibilidade)
- **Contexto(s):** Painel TV, Controle de Técnicos em Tempo Real, Dashboard de Gestão, Cadastros/CRUDs, Django Admin.
- **Perfil(s) afetados:** Técnico, Técnico Líder, Operador/Líder, Administrador.

---

## ❗ 2. PROBLEMA ATUAL

1. **Ausência por Faltas:** Atualmente, a escala permite marcar apenas Folga/Escala, Férias, Licença Médica e Plantão Externo. Não existem opções para registrar "Falta Justificada" e "Falta Não Justificada", impedindo a gestão e auditoria correta das ausências.
2. **Desligamento/Inativação de Técnicos:** Não há forma segura de inativar um técnico que saiu da empresa sem excluí-lo fisicamente do banco de dados. Excluir um técnico causaria perda de histórico de Ordens de Serviço, pausas, auditorias de escala, relatórios e métricas de MTTR.
3. **Falta de Filtros Operacionais vs. Históricos:** Sem o conceito de técnico ativo, ex-funcionários continuariam aparecendo no Painel TV, no Controle de Técnicos e nos seletores de novas ordens de serviço.

---

## 🎯 3. OBJETIVO

1. **Novos Estados de Ausência:**
   - Adicionar os status `AUSENTE_FALTA_JUSTIFICADA` ("Ausente – Falta Justificada") e `AUSENTE_FALTA_NAO_JUSTIFICADA` ("Ausente – Falta Não Justificada").
   - Garantir que técnicos nestes estados fiquem indisponíveis para novas ordens de serviço, apresentem destaque visual de indisponibilidade, gerem registro no `HistoricoEscala` com o `usuario_responsavel` e possam retornar a "Disponível (Ocioso)".

2. **Gestão de Técnicos Inativos (`is_active`):**
   - Criar o campo `is_active` (`models.BooleanField(default=True, verbose_name="Ativo no quadro da empresa")`) no modelo `Technician`.
   - Garantir que todos os técnicos atuais permaneçam ativos (`default=True`).
   - Ocultar técnicos inativos do `/management/`, `/tv/` e seletores operacionais de novas ordens.
   - Manter técnicos inativos visíveis no Django Admin e no CRUD (`/cruds/`), permitindo busca, edição e reativação.
   - Bloquear via validação no backend qualquer tentativa de atribuir novas ordens a técnicos inativos.
   - Bloquear via backend a inativação de técnicos com atendimentos abertos (`EM_ATENDIMENTO` ou `EM_PAUSA`).
   - Preservar técnicos inativos em consultas históricas, relatórios de período, gráficos do dashboard e logs de auditoria.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `maintenance/models.py`
- `maintenance/admin.py`
- `maintenance/forms.py`
- `maintenance/views.py`
- `maintenance/templates/maintenance/technician_management.html`
- `maintenance/templates/maintenance/crud_list.html`
- `maintenance/templates/maintenance/technician_form.html`
- `maintenance/tests.py`
- `maintenance/migrations/` (nova migration gerada via Django)
- `Instrucoes.txt`

### Possíveis módulos:
- `maintenance` (models, admin, forms, views, templates, tests)

---

## 🚫 5. FORA DE ESCOPO

- Não alterar a funcionalidade do app `production`.
- Não refatorar a estrutura do projeto ou criar novos apps Django.
- Não criar novos ambientes virtuais ou pastas paralelas.
- Não alterar banco de dados via SQL puro.
- Não excluir ou alterar registros históricos de `Allocation`, `HistoricoEscala` ou `HistoricoPausa`.
- Não alterar a regra de concorrência de atendimentos já existente.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`:

- ❌ Não criar múltiplos ambientes (.venv2, etc).
- ❌ Não duplicar projeto ou apps.
- ❌ Não duplicar lógica existente.
- ✅ Reutilizar código existente e centralizar no modelo/form/service.
- ✅ Validar permissões e regras de negócio no backend.
- ✅ Usar ORM do Django (compatível com SQLite e MySQL).
- ❌ Não usar SQL direto.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Status de Ausência:**
   - O conjunto `STATUS_AUSENCIA` no modelo `Technician` conterá:
     `{'AUSENTE_FOLGA', 'AUSENTE_FERIAS', 'AUSENTE_MEDICO', 'EXTERNO_PLANTAO', 'AUSENTE_FALTA_JUSTIFICADA', 'AUSENTE_FALTA_NAO_JUSTIFICADA'}`.
   - A propriedade `is_ausente` utilizará `STATUS_AUSENCIA`.
   - `set_availability` permitirá a transição para qualquer status de `STATUS_AUSENCIA` ou `'OCIOSO'`, registrando a alteração no `HistoricoEscala` com o `request.user`.

2. **Campo `is_active`:**
   - Adicionado a `Technician` com `default=True`.
   - Django Admin exibirá `is_active` em `list_display` e `list_filter` de `TecnicoAdmin`.

3. **Validação de Inativação:**
   - Tentativa de definir `is_active=False` para um técnico com atendimento aberto (`status == 'EM_ATENDIMENTO'` ou `'EM_PAUSA'`, ou `allocations.filter(data_fim__isnull=True).exists()`) deve ser bloqueada no backend (`Technician.clean()` e `TechnicianForm.clean()`).
   - Mensagem de erro: *"O técnico possui atendimentos em aberto. Conclua ou transfira os atendimentos antes de inativá-lo."*

4. **Validação de Atribuição de Ordem:**
   - Tentativa de iniciar/atribuir nova alocação para técnico inativo (`is_active=False`) deve ser bloqueada no backend (`start_service` / `Allocation.clean()`).
   - Mensagem de erro: *"Este técnico não está ativo no quadro da empresa e não pode receber novas ordens de serviço."*

5. **Consultas Operacionais vs. Históricas:**
   - **Operacionais (`is_active=True`):** `/management/`, `/tv/`, seletores de novos chamados, KPIs do status ATUAL da equipe (capacidade do quadro).
   - **Históricas (Sem filtro `is_active=True`):** relatórios por período (`relatorio_turno`, exportação Excel), gráficos do dashboard por período (`alloc_filtrado`), históricos de escala (`HistoricoEscala`), auditoria Admin e aba de cadastros (`/cruds/`).

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Status "Falta Justificada" e "Falta Não Justificada" disponíveis no seletor de disponibilidade.
- [ ] Ambos os novos status impedem alocação em novas ordens de serviço.
- [ ] Troca para os novos status gera registro no `HistoricoEscala` com `usuario_responsavel`.
- [ ] Técnico pode retornar de falta para "Disponível (Ocioso)".
- [ ] Campo `is_active` adicionado a `Technician` com `default=True` via migration segura.
- [ ] Todos os técnicos existentes mantêm `is_active=True` após migration.
- [ ] Técnicos inativos somem do `/management/` e do `/tv/`.
- [ ] Tentativa via backend/POST de alocar ordem para técnico inativo é bloqueada com mensagem clara.
- [ ] Tentativa de inativar técnico com alocação em atendimento ou pausada é bloqueada com mensagem clara.
- [ ] Técnicos inativos permanecem visíveis em ordens históricas, relatórios de período e logs.
- [ ] Administrador visualiza, filtra, pesquisa, edita e reativa técnicos inativos no Admin e no `/cruds/`.
- [ ] `python manage.py check` e `python manage.py makemigrations --check` sem pendências.
- [ ] Todos os testes automatizados executados e aprovados.

---

## ⚠️ 9. RISCOS

- **Impacto em relatórios históricos:** Risco de aplicar `is_active=True` em consultas de relatórios de período e sumir com dados de ex-funcionários.
  - *Mitigação:* O filtro `is_active=True` será aplicado APENAS nas consultas do quadro operacional atual (`/management/`, `/tv/` e KPI cards de status atual). As consultas por período (`alloc_filtrado`) continuarão buscando alocações sem filtrar `is_active`.
- **Efeito colateral no Admin:** Risco de impedir que o admin consiga reativar técnicos inativos.
  - *Mitigação:* O Admin não filtrará técnicos por `is_active=True` na query base; apenas disponibilizará a opção em `list_filter`.
- **Inconsistência ao inativar técnico trabalhando:** Risco de inativar um técnico que está no meio de um atendimento.
  - *Mitigação:* Validação estrita no `clean()` do modelo e do formulário bloqueando a inativação se houver alocação ativa ou pausada.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Subagente Arquiteto (Mapeamento e Projeto):
- **Status da SPEC:** `PROPOSTA` -> `APROVADA`
- **Arquivos a alterar:**
  1. `maintenance/models.py`:
     - Adicionar choices `AUSENTE_FALTA_JUSTIFICADA` e `AUSENTE_FALTA_NAO_JUSTIFICADA` a `STATUS_CHOICES`.
     - Atualizar `STATUS_AUSENCIA` para incluir os dois novos status.
     - Adicionar campo `is_active = models.BooleanField(default=True, verbose_name="Ativo no quadro da empresa")`.
     - Adicionar validação `clean()` para impedir `is_active=False` com alocações abertas.
  2. `maintenance/admin.py`:
     - Adicionar `'is_active'` em `list_display` e `list_filter` de `TecnicoAdmin`.
  3. `maintenance/forms.py`:
     - Adicionar `'is_active'` aos campos de `TechnicianForm`.
     - Adicionar validação em `TechnicianForm.clean()`.
  4. `maintenance/views.py`:
     - Atualizar `set_availability` para derivar `STATUS_PERMITIDOS` de `STATUS_AUSENCIA`.
     - Atualizar `technician_management` para filtrar `Technician.objects.filter(is_active=True)`.
     - Atualizar `tv_dashboard` para filtrar `Technician.objects.filter(is_active=True)`.
     - Atualizar `dashboard` (KPI cards de capacidade atual) para filtrar `is_active=True`.
     - Atualizar `start_service` para validar se o técnico está ativo antes de criar alocação.
  5. `maintenance/templates/maintenance/technician_management.html`:
     - Atualizar modal/widget de escala, badges e visualização de ausência.
  6. `maintenance/templates/maintenance/crud_list.html`:
     - Exibir badge de ativo/inativo na tabela de cadastros.
  7. `maintenance/templates/maintenance/technician_form.html`:
     - Adicionar campo `is_active` no formulário de edição/cadastro.
  8. `maintenance/tests.py`:
     - Escrever suíte de testes cobrindo todas as novas regras.
  9. `Instrucoes.txt`:
     - Atualizar documentação.

- **Consultas Operacionais que receberão filtro `is_active=True`:**
  - `technician_management`: `Technician.objects.filter(is_active=True).order_by('nome')`
  - `tv_dashboard`: `Technician.objects.filter(is_active=True).prefetch_related(...)`
  - `dashboard` (KPIs de status atual): `total_techs`, `active_techs`, `paused_techs`, `idle_techs`, `absent_techs`.

- **Consultas Históricas preservadas sem filtro `is_active`:**
  - `dashboard` (`alloc_filtrado` - alocações por período)
  - `relatorio_turno` (alocações e gráficos por período)
  - `exportar_relatorio_excel` (alocações do período)
  - `HistoricoEscala` e `HistoricoEscalaAdmin`
  - `crud_list` (listagem completa para gestão administrativa)
  - Django Admin `TecnicoAdmin` (queryset base completo)

- **Estratégia de Rollback:**
  - Caso seja necessário reverter, a migration pode ser desfeita via `python manage.py migrate maintenance <migration_anterior>`, sem perda de dados históricos de alocações ou técnicos.

---

## 🧪 11. TESTES MANUAIS

1. Alterar disponibilidade de um técnico para "Falta Justificada" e verificar badge e bloqueio de início de serviço.
2. Alterar disponibilidade de um técnico para "Falta Não Justificada" e verificar auditoria em `HistoricoEscala`.
3. Retornar técnico ausente para "Disponível (Ocioso)".
4. Tentar inativar técnico no Django Admin enquanto possui serviço `EM_ATENDIMENTO` -> Verificar mensagem de erro.
5. Tentar inativar técnico no Django Admin enquanto possui serviço `EM_PAUSA` -> Verificar mensagem de erro.
6. Inativar um técnico sem atendimentos abertos no Admin.
7. Verificar que o técnico inativo desapareceu do `/management/` e do `/tv/`.
8. Tentar enviar POST manual em `/technicians/<id_inativo>/start/` -> Verificar mensagem de bloqueio no backend.
9. Consultar ordens antigas e relatório Excel -> Verificar que o técnico inativo continua aparecendo nas Ordens de Serviço históricas.
10. Reativar o técnico no Admin -> Verificar que ele reaparece no `/management/` e no `/tv/`.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

### Arquivos lidos:
- `constitution.md`
- `regras_programacao/SPEC_TEMPLATE.md`
- `maintenance/models.py`
- `maintenance/admin.py`
- `maintenance/forms.py`
- `maintenance/views.py`
- `maintenance/urls.py`
- `maintenance/middleware.py`
- `maintenance/templates/maintenance/technician_management.html`
- `maintenance/templates/maintenance/tv_dashboard.html`
- `maintenance/templates/maintenance/crud_list.html`
- `maintenance/templates/maintenance/technician_form.html`
- `maintenance/tests.py`

### Arquivos alterados:
- *(Serão preenchidos na fase de implementação)*

### Alterações feitas:
- *(Serão preenchidos na fase de implementação)*

### Justificativa:
- *(Serão preenchidos na fase de implementação)*
