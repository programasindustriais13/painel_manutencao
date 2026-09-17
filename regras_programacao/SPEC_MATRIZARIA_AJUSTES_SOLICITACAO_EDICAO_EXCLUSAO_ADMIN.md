# 🧠 SPEC — MATRIZARIA: OPÇÃO SEM MÁQUINA, CORREÇÃO DE EDIÇÃO/EXCLUSÃO E EXCLUSÃO ADMINISTRATIVA SUPERUSER

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/matrizaria/solicitar/` (Abertura de serviço para chão de fábrica)
  - `/matrizaria/servicos/<int:pk>/` (Detalhe da solicitação com botões operacionais)
  - `/matrizaria/servicos/<int:pk>/editar/` (Edição antes do início técnico)
  - `/matrizaria/servicos/<int:pk>/excluir/` (Exclusão operacional controlada de solicitações pendentes)
  - `/matrizaria/relatorios/` e `/matrizaria/relatorios/exportar-excel/` (Relatórios e exportação)
  - `/matrizaria/` (Kanban operacional)
  - `/matrizaria/tv/` e `/matrizaria/api/tv-data/` (Painel contínuo da oficina)
  - `/producao/maquinas/<int:pk>/` (Linha do tempo da prensa)
  - `/admin/` (Django Admin de `matrizaria`, `maintenance` e `production`)
- **Contexto(s):** Módulo de Matrizaria Industrial, Chão de Fábrica, Django Admin para Superusuários.
- **Perfil(s) afetados:** Operadores de Vulcanização, Matrizeiros, Líderes de Produção, Superusuários (`is_superuser=True`).

---

## ❗ 2. PROBLEMA ATUAL

1. **Obrigatoriedade de Prensa/Máquina:**
   - O formulário `/matrizaria/solicitar/` exige seleção de `Machine`. Existem serviços internos da própria Matrizaria (ex: retífica de anéis, usinagem geral de bancada, ajuste de matriz sobressalente em estoque) que não pertencem a nenhuma prensa.
   - Atualmente não é possível registrar um chamado interno sem selecionar uma prensa real, o que polui o histórico da prensa selecionada indevidamente.
2. **Botões Editar e Apagar/Excluir não funcionam:**
   - **Edição:** Na view `detalhe_servico_view`, a flag `can_editar` avalia permissão considerando `user_can_conf` (que inclui operadores dos grupos `"Operadores"` e `"Operador"`), porém na camada de serviço `MatrizariaService.editar_solicitacao`, a checagem interna `is_gestao` restringe a `"Liderança de Produção"`, `"Lideres"` e `"Tecnicos_Lideres"`, gerando `PermissionDenied` silencioso ou exibindo mensagens de erro quando um operador tenta editar solicitação pendente aberta por ele mesmo ou por colega de turno. Além disso, o seletor de máquina não contempla a opção "Matrizaria".
   - **Exclusão operacional:** Não existia rota ou endpoint operacional de exclusão em `matrizaria/urls.py`, deixando usuários sem forma de remover chamados abertos por engano que ainda não foram iniciados.
3. **Superusuário bloqueado no `/admin/`:**
   - Para limpar registros de testes e treinamentos, o superusuário tenta excluir via Django Admin, mas é impedido por `has_delete_permission = False` e `actions = None` em `SolicitacaoServicoMatrizariaAdmin`, `CicloExecucaoMatrizariaAdmin`, `HistoricoTransicaoServicoMatrizariaAdmin` e `LoteImportacaoMatrizFisicaAdmin`.
   - Além disso, modelos como `TipoServicoMatrizaria`, `MatrizFisica` e `Machine` possuem `on_delete=models.PROTECT`, levantando `ProtectedError` no Django caso existam registros dependentes.

---

## 🎯 3. OBJETIVO

1. **Opção "Matrizaria" em Prensa / Máquina:**
   - Disponibilizar no campo `Prensa / Máquina` a opção explícita `Matrizaria — Serviço interno / Sem máquina`.
   - Tornar o campo `prensa` opcional no modelo (`null=True, blank=True`) e criar um discriminador explícito (`destino`: `"MAQUINA"` vs `"MATRIZARIA"`).
   - Não criar nenhuma máquina fictícia no banco `Machine`.
   - Exibir `"Matrizaria"` em todas as telas, TV, Kanban, snapshots, relatórios e Excel.
   - Garantir que serviços internos NUNCA apareçam na linha do tempo de prensas reais.
2. **Correção de Edição e Exclusão Operacional:**
   - Alinhar as regras de permissão em `views.py`, `forms.py` e `services.py` para que a edição de chamados em status `SOLICITADO` (sem início técnico) funcione com validação de concorrência, CSRF e auditoria.
   - Implementar exclusão operacional para solicitações em status `SOLICITADO` sem ciclos técnicos iniciados, via método POST, exigindo CSRF, confirmação em modal, mensagem de sucesso e tratamento amigável de restrições.
3. **Exclusão Administrativa Excepcional para Superuser no `/admin/`:**
   - Implementar um serviço administrativo centralizado (`AdminCascadeDeletionService`) que permite ao **Superusuário** (`is_superuser=True`) excluir registros locais e seus dependentes protegidos de forma atômica, segura e auditada.
   - Preservar rigorosamente o comportamento de `on_delete=models.PROTECT` para staff e usuários comuns.
   - Bloquear terminantemente qualquer exclusão ou escrita no alias `scada`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a Modificar:
- `matrizaria/models.py`:
  - Adicionar campo `destino` (`choices=[("MAQUINA", "Prensa / Máquina"), ("MATRIZARIA", "Matrizaria — Serviço interno / Sem máquina")]`, `default="MAQUINA"`).
  - Alterar `prensa` para `null=True, blank=True`.
  - Atualizar validação no método `clean()` e representação em `__str__`.
- `matrizaria/forms.py`:
  - Atualizar `SolicitacaoServicoForm` e `EditarSolicitacaoForm` com campo/choices de destino que expõe a opção "Matrizaria — Serviço interno / Sem máquina".
  - Atualizar `RelatorioFiltroForm` para filtrar por destino ou máquina.
- `matrizaria/services.py`:
  - Atualizar `criar_solicitacao` e `editar_solicitacao` para receber `destino` e tratar `prensa=None` quando `destino="MATRIZARIA"`.
  - Harmonizar permissão de edição em `editar_solicitacao`.
  - Adicionar método `excluir_solicitacao_operacional`.
  - Criar `AdminCascadeDeletionService` para exclusão forçada atômica exclusiva de superusuários.
- `matrizaria/views.py`:
  - Tratar a opção "Matrizaria" nas views de abertura, detalhe e relatórios.
  - Adicionar view `excluir_solicitacao_view` (POST, CSRF, permissão, redirect).
- `matrizaria/urls.py`:
  - Adicionar rota `servicos/<int:pk>/excluir/`.
- `matrizaria/templates/matrizaria/form_solicitacao.html`:
  - Exibir opção de Matrizaria no seletor de máquina.
- `matrizaria/templates/matrizaria/detalhe_solicitacao.html`:
  - Atualizar modal de edição para permitir selecionar "Matrizaria" e adicionar modal/botão de exclusão operacional quando o status for `SOLICITADO` e sem ciclos iniciados.
- `matrizaria/admin.py`:
  - Liberar permissão de exclusão exclusivamente para `request.user.is_superuser`.
  - Registrar ação administrativa e confirmação de exclusão em cascata controlada via `AdminCascadeDeletionService`.
- `maintenance/admin.py`:
  - Permitir exclusão em cascata pelo superusuário para modelos bloqueados por histórico de testes, se necessário.
- `matrizaria/tests.py`:
  - Expandir suíte com testes cobrindo serviço interno, edição corrigida, exclusão operacional e exclusão administrativa de superuser.

---

## 🚫 5. FORA DE ESCOPO

- NÃO criar `Machine` fictícia chamada "Matrizaria".
- NÃO converter globalmente `on_delete=PROTECT` para `on_delete=CASCADE` no schema do banco.
- NÃO permitir exclusão operacional de chamados que já tiveram atendimento técnico (`status != 'SOLICITADO'` ou com ciclos).
- NÃO disponibilizar endpoints públicos de exclusão administrativa.
- NÃO tocar no banco `scada` (zero escrita).
- NÃO executar exclusão de dados reais durante migrations ou testes.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Apenas 1 ambiente virtual (`.venv`) e 1 base de código ativa.
- Validação rigorosa de permissões no backend (decorators e ORM).
- Compatibilidade estrita entre SQLite (desenvolvimento) e MySQL (produção).
- Migrations aditivas e reversíveis (`null=True, blank=True` ou `default`).
- Zero escrita no banco `scada`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Discriminador de Destino:**
   - Se `destino == "MAQUINA"`: `prensa` é obrigatória. `prensa_nome_snapshot` grava o nome da máquina.
   - Se `destino == "MATRIZARIA"`: `prensa` deve ser `None`. `prensa_nome_snapshot` grava `"Matrizaria"`.
   - Envio acidental de formulário sem máquina e sem escolha de Matrizaria é bloqueado com erro de validação.
2. **Apresentação Visual:**
   - No Kanban, TV, relatórios, modal e cabeçalho, serviços internos exibem `"Matrizaria"`.
   - Linha do tempo da prensa (`get_unified_press_timeline`) filtra estritamente por `prensa_id=machine_id`, portanto chamados com `prensa_id=None` não aparecem na prensa.
3. **Edição Operacional:**
   - Permitida para quem abriu o chamado ou líderes/operadores autorizados quando `status == "SOLICITADO"` e 0 ciclos.
   - Preserva `data_solicitacao`, `solicitado_por`, `versao` validada, grava histórico de auditoria (`tipo_evento="ALTERACAO_DADO"`).
4. **Exclusão Operacional:**
   - Disponível apenas se `status == "SOLICITADO"` e 0 ciclos de execução iniciados.
   - Exige método POST com token CSRF.
   - Permissão restrita a superusuário, staff, solicitante original ou líderes autorizados.
   - Remove o chamado e seu histórico inicial de abertura atomicamente.
5. **Exclusão Administrativa no Admin (Superuser):**
   - Exclusiva para `request.user.is_superuser is True`.
   - Coleta dependências protegidas recursivas dentro do app local no alias `default`.
   - Exibe tela de confirmação intermediária listando os objetos que serão excluídos.
   - Executa dentro de `transaction.atomic(using='default')`.
   - Se falhar, realiza rollback completo.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Abertura de chamado selecionando "Matrizaria — Serviço interno / Sem máquina" salva sem erros (`prensa=None`, `destino='MATRIZARIA'`, `prensa_nome_snapshot='Matrizaria'`).
- [ ] Abertura de chamado com destino máquina sem selecionar prensa é rejeitada.
- [ ] O chamado de Matrizaria aparece no Kanban e TV como "Matrizaria".
- [ ] O chamado de Matrizaria NÃO aparece na timeline de nenhuma máquina real (`/producao/maquinas/<id>/`).
- [ ] Relatórios e exportação Excel exibem "Matrizaria" na coluna de prensa/equipamento.
- [ ] Botão de edição funciona para usuários autorizados, permitindo alterar prensa, destino, tipo de serviço, matriz física e descrição.
- [ ] Botão de exclusão operacional exclui chamados não iniciados com confirmação e CSRF.
- [ ] Chamados iniciados ou concluídos não podem ser excluídos operacionalmente.
- [ ] Superuser consegue excluir registros com dependentes protegidos pelo `/admin/` via ação administrativa dedicada.
- [ ] Usuários não-superusuários continuam bloqueados por relações `PROTECT`.
- [ ] Zero escrita no banco `scada`.
- [ ] 100% dos testes passam.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco:** `AttributeError` em código que assume `solicitacao.prensa.nome`.
  - *Mitigação:* Usar consistentemente `solicitacao.prensa_nome_snapshot or (solicitacao.prensa.nome if solicitacao.prensa else "Matrizaria")`.
- **Risco:** Exclusão acidental de dados de produção pelo admin.
  - *Mitigação:* Confirmação detalhada com contagem de objetos e restrição exclusiva a superusuários.
- **Risco:** Incompatibilidade SQLite e MySQL.
  - *Mitigação:* Usar ORM padrão e transações atômicas nativas.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. **Models e Migration:**
   - Adicionar `destino` e tornar `prensa` anulável em `matrizaria/models.py`.
   - Gerar migration aditiva `0003_solicitacaoservicomatrizaria_destino_and_more.py`.
2. **Forms e Services:**
   - Atualizar `SolicitacaoServicoForm`, `EditarSolicitacaoForm`, `RelatorioFiltroForm`.
   - Atualizar `MatrizariaService.criar_solicitacao`, `editar_solicitacao`, `excluir_solicitacao_operacional`.
   - Criar `AdminCascadeDeletionService` para superusuários.
3. **Views e Templates:**
   - Atualizar `solicitar_servico_view`, `editar_solicitacao_view`, criar `excluir_solicitacao_view`.
   - Atualizar `form_solicitacao.html` e `detalhe_solicitacao.html`.
4. **Admin:**
   - Integrar `AdminCascadeDeletionService` no `matrizaria/admin.py` sob guarda de `is_superuser`.
5. **Testes e Validação:**
   - Cobrir os 11 casos de teste obrigatórios descritos na demanda.
