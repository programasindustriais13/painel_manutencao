# 🧠 SPEC_PRODUCAO_07C — PLANEJAMENTO E CADASTRO MANUAL DE METAS DE PRODUÇÃO COM CATÁLOGO LOCAL

---

## 📌 1. PREDECESSORA E CONTEXTO

- **Predecessora**: `SPEC_PRODUCAO_07B_ACUMULO_PRODUCAO_COM_RESETS.md`
- **URL(s) envolvidas**:
  - `/producao/` (Dashboard de Produção)
  - `/producao/metas/` (Área de Gestão de Metas da Produção)
  - `/producao/metas/criar/` (Modal/Formulário de Cadastro de Meta)
  - `/producao/catalogos/matrizes/` (Gestão do Catálogo de Matrizes e Produtos)
- **Contexto(s)**: Módulo de Produção / Planejamento e Controle de Produção (PCP) / Gestão Industrial
- **Perfil(s) afetados**: Líder de Produção, PCP, Operadores, Administrador

---

## ❗ 2. PROBLEMA ATUAL

Atualmente, o sistema possui apenas um campo simplificado `meta_producao_manual` em `ProductionCavityConfig`, que armazena um número fixo de meta direta na cavidade.
Esta abordagem possui sérias limitações no ambiente fabril:
1. O PCP precisa cadastrar metas operacionais vinculadas a **datas futuras**, **turnos específicos**, e **matrizes/produtos específicos**.
2. É frequentemente necessário cadastrar uma meta para uma matriz ou produto que **ainda não está instalada em nenhuma prensa** no Scada.
3. Não existe um catálogo local normalizado de matrizes e produtos, dependendo exclusivamente dos valores textuais instáveis recebidos do Scada.
4. O controle de acesso para alteração de metas precisa ser devidamente autorizado sem quebrar o isolamento do módulo nem criar grupos redundantes.

---

## 🎯 3. OBJETIVO

Criar uma área protegida para Líderes de Produção e PCP cadastrar e gerenciar Metas de Produção planejadas, além de um Catálogo Local de Matrizes e Produtos:
1. **Model `ProductionTarget` (Meta Planejada)**:
   - Data da meta (`date`).
   - Turno (`shift`: FK `ProductionShift`, opcional para meta diária geral).
   - Matriz/Produto (`matrix_catalog`: FK `ProductionMatrixCatalog` ou código textual).
   - Quantidade planejada (`planned_quantity`).
   - Máquina prevista (`predicted_machine`: FK `maintenance.Machine`, opcional).
   - Cavidade prevista (`predicted_cavity`: FK `ProductionCavityConfig`, opcional).
   - Observação (`observation`).
   - Status (`status`: `ATIVO`, `CANCELADO`, `CONCLUIDO`).
   - Auditoria (`created_by`, `created_at`, `updated_by`, `updated_at`).
2. **Model `ProductionMatrixCatalog` (Catálogo Local de Matrizes)**:
   - Código canônico (ex: `"M-1024"`).
   - Descrição (ex: `"Matriz 175/70R14 Curing"`).
   - Produto (ex: `"Pneu 175/70R14"`).
   - Status ativo/inativo (`ativo`).
   - Aliases recebidos do Scada (`aliases_scada`: texto separado por vírgulas, ex: `"MATRIZ 1024, Matriz 1024, 1024"`).
3. **Autorização e Permissões**:
   - Não criar automaticamente um novo grupo "PCP" no banco.
   - Auditar grupos e permissões: conceder autorização para superusers, staff, usuários do grupo "Liderança de Produção" ou portadores da permissão `production.add_productiontarget`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/models.py):
  - Criar `ProductionMatrixCatalog`.
  - Criar `ProductionTarget`.
- [forms.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/forms.py) [NEW]:
  - Criar `ProductionTargetForm` e `ProductionMatrixCatalogForm`.
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/views.py):
  - Adicionar views de listagem, criação, edição e cancelamento de metas (`target_list`, `target_create`, `target_edit`, `target_cancel`).
- [urls.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/urls.py):
  - Mapear rotas `/producao/metas/` e CRUD de metas.
- [templates](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/templates/production/):
  - Criar `production/target_list.html` e modal de cadastro.
- [migrations](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/production/migrations/):
  - Nova migration `0014_productionmatrixcatalog_productiontarget.py`.

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO criar grupos auth destrutivos automaticamente nas migrations de dados.
- ❌ NÃO depender exclusivamente de matrizes instaladas no Scada para permitir o cadastro de metas.
- ❌ NÃO alterar tabelas da Manutenção nem do Scada.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`:
- Validação de formulários no backend (Django Forms + CSRF).
- Proteção por decorators (`@lider_ou_pcp_required`).
- Usar ORM nativo do Django sem SQL puro.

---

## ⚙️ 7. REGRAS DE NEGÓCIO DETALHADAS

1. **Vínculo da Meta com o Dashboard**:
   - Quando existe uma `ProductionTarget` ativa para o `(date, shift, matriz/produto)` do turno atual, o sistema utiliza a `planned_quantity` desta meta como a meta de referência do turno.
   - Caso não exista meta específica cadastrada no `ProductionTarget`, o sistema faz fallback gracioso para a `meta_producao_manual` da cavidade configurada.
2. **Duplicação e Validação**:
   - É permitido cadastrar metas para a mesma matriz em máquinas/cavidades diferentes.
   - Duas metas com exatamente a mesma chave `(date, shift, matriz, maquina, cavidade)` são bloqueadas pelo form (`ValidationError`).
3. **Alteração Pós-Início do Turno**:
   - Se uma meta for alterada após o início do turno, o sistema atualiza o `updated_by` e `updated_at`, registrando a observação da alteração e recalculando o percentual de atingimento a partir do momento da alteração.
4. **Cancelamento de Meta**:
   - Metas canceladas mudam seu status para `CANCELADO` e deixam de ser contabilizadas nos agregados do turno, permanecendo no histórico para fins de auditoria.

---

## 🗄️ 8. MIGRATION PREVISTA

- **Arquivo**: `production/migrations/0014_productionmatrixcatalog_productiontarget.py`
- **Operações**: `CreateModel` para `ProductionMatrixCatalog` e `ProductionTarget` com índices em `(date, shift)` e `(status, date)`.

---

## 🧪 9. CRITÉRIOS DE ACEITAÇÃO

- [ ] É possível cadastrar uma meta para uma matriz/produto ainda não instalada em nenhuma prensa no Scada.
- [ ] A área de metas em `/producao/metas/` exige autenticação e permissão de Líder de Produção / PCP.
- [ ] O Catálogo de Matrizes permite associar múltiplos aliases textuais do Scada (ex: `"MATRIZ 1024, Matriz 1024, 1024"`).
- [ ] Formulários impedem o cadastro de metas duplicadas para a mesma cavidade/turno.
- [ ] Cancelamento de meta preserva o registro para auditoria sem somar no dashboard.
- [ ] Suíte de testes automatizados passa 100%.

---

## ⚠️ 10. RISCOS E MITIGAÇÕES

- **Risco**: Usuário sem permissão conseguir cadastrar ou alterar metas.
  - *Mitigação*: Decorator `@lider_ou_pcp_required` checando `request.user` em todas as views e actions de POST.

---

## 🔍 11. PLANO DE IMPLEMENTAÇÃO

1. Criar `ProductionMatrixCatalog` e `ProductionTarget` em `production/models.py`.
2. Executar `makemigrations` gerando a migration `0014`.
3. Criar formulários em `production/forms.py` com validação de unicidade e saneamento de strings.
4. Criar o decorator `lider_ou_pcp_required` em `production/decorators.py`.
5. Implementar views e templates em `production/views.py` e `production/templates/production/target_list.html`.
6. Integrar a resolução de metas planejadas na `ProductionStateService.build_cavities_data`.
7. Criar testes unitários para CRUD e permissões de metas.

---

## 🧪 12. TESTES AUTOMATIZADOS E MANUAIS

### Testes Automatizados:
- `test_create_target_for_uninstalled_matrix`: testa cadastro de meta para matriz não cadastrada nas cavidades ativas.
- `test_duplicate_target_validation`: tenta criar duas metas idênticas e valida rejeição pelo formulário.
- `test_cancel_target`: testa mudança de status para CANCELADO e valida exclusão do cálculo do dashboard.
- `test_unauthorized_user_cannot_access_targets`: garante que operadores ou usuários não autorizados recebem redirecionamento ou HTTP 403.

---

## 🛑 13. GATE DE SAÍDA E REGRA DE PARADA

- **Gate de Saída**: Testes de CRUD de metas e permissões 100% aprovados.
- **Regra de Parada**: Se for tentada a inclusão de grupos no banco de dados que modifiquem permissões de outros apps (`maintenance`), PARAR e restringir o escopo ao app `production`.
