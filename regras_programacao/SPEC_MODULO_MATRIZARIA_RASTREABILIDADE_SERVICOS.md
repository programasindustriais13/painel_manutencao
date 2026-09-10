# 🧠 SPEC — MÓDULO MATRIZARIA: CONTROLE E RASTREABILIDADE DE SERVIÇOS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/matrizaria/` (Kanban operacional de serviços)
  - `/matrizaria/solicitar/` (Abertura de serviço para chão de fábrica)
  - `/matrizaria/servicos/<int:pk>/` (Detalhes com timeline de auditoria e ciclos)
  - `/matrizaria/servicos/<int:pk>/iniciar/` (Assumir atendimento ou retrabalho)
  - `/matrizaria/servicos/<int:pk>/transferir/` (Transferência auditada de responsabilidade)
  - `/matrizaria/servicos/<int:pk>/finalizar/` (Encerramento de ciclo técnico com descrição obrigatória)
  - `/matrizaria/servicos/<int:pk>/conferir/` (Conferência com aprovação ou devolução com motivo)
  - `/matrizaria/servicos/<int:pk>/cancelar/` (Cancelamento justificado por liderança autorizada)
  - `/matrizaria/tv/` (Painel contínuo da oficina com alertas canônicos de bladder)
  - `/matrizaria/api/tv-data/` (Endpoint leve e desacoplado para telemetria da TV)
  - `/matrizaria/relatorios/` e `/matrizaria/relatorios/exportar-excel/` (Auditoria e exportação em duas abas)
  - `/portal/` (Seletor de módulos pós-login)
  - `/producao/maquinas/<int:pk>/` (Histórico unificado da prensa com abas)
- **Contextos:** Matrizaria Industrial, Chão de Fábrica (Vulcanização), Qualidade / Auditoria, Modo TV.
- **Perfis afetados:** Líderes de Produção, Operadores da Vulcanização, Colaboradores da Matrizaria, Gestores/Administradores e Conta de Exibição TV.

---

## ❗ 2. PROBLEMA ATUAL

- Os serviços executados pela Matrizaria ocorrem sem controle formal no sistema (solicitações verbais).
- Inexistência de registros confiáveis de solicitação, início, término de execução e conferência formal do solicitante, resultando em não conformidade em auditoria externa de qualidade.
- Ausência de rastreamento individualizado das unidades físicas de matrizes no chão de fábrica (`001`, `002`, etc.), existindo apenas o cadastro de modelos canônicos do SCADA.
- Sobrescrita de dados em casos de retrabalho ou devolução pela liderança, destruindo a trilha histórica do atendimento original.
- Falta de monitoramento visual antecipado na oficina quando uma prensa está prestes a atingir o limite de ciclo de bladder.

---

## 🎯 3. OBJETIVO

1. Implementar o novo app Django `matrizaria` operando no banco `default`, sem acoplar com as regras de técnicos da Manutenção nem com o coletor SCADA.
2. Modelar as entidades `TipoServicoMatrizaria`, `MatrizFisica`, `SolicitacaoServicoMatrizaria`, `CicloExecucaoMatrizaria` e `HistoricoTransicaoServicoMatrizaria`.
3. Controlar o fluxo completo via máquina de estados: `SOLICITADO` → `EM_EXECUCAO` → `AGUARDANDO_CONFERENCIA` → `CONCLUIDO` / `AGUARDANDO_RETRABALHO` / `CANCELADO`.
4. Garantir que cada início (inclusive retrabalho) abra um ciclo individual em `CicloExecucaoMatrizaria`, impedindo sobrescrita de dados anteriores.
5. Blindar o histórico contra edições ou exclusões destrutivas no Admin e via ORM, gravando snapshots mínimos de nomes no momento de cada ação.
6. Proteger a concorrência via guardas de versão (`versao`) e estado no ORM com transações atômicas.
7. Implementar relatório de auditoria com seletor "Consultar por" capaz de localizar serviços por execução em data específica, acompanhado de exportador Excel em duas abas com sanitização de fórmulas.
8. Criar a TV da Matrizaria alternando suavemente a fila de serviços (20s) e alertas canônicos de bladder (15s) consumindo `BladderTrackingService.get_active_bladders_context`.
9. Atualizar o `/portal/` pós-login, garantindo redirecionamento direto para quem tem 1 módulo e exibição estrita dos módulos autorizados.
10. Integrar o histórico da prensa na tela de máquinas com visão por abas (`[ Todos | Manutenção | Matrizaria ]`).

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Novos arquivos no app `matrizaria/`:
- `matrizaria/__init__.py`
- `matrizaria/apps.py`
- `matrizaria/models.py`
- `matrizaria/admin.py`
- `matrizaria/urls.py`
- `matrizaria/views.py`
- `matrizaria/services.py`
- `matrizaria/decorators.py`
- `matrizaria/forms.py`
- `matrizaria/templates/matrizaria/base_matrizaria.html`
- `matrizaria/templates/matrizaria/kanban.html`
- `matrizaria/templates/matrizaria/form_solicitacao.html`
- `matrizaria/templates/matrizaria/detalhe_solicitacao.html`
- `matrizaria/templates/matrizaria/modal_conferencia.html`
- `matrizaria/templates/matrizaria/tv.html`
- `matrizaria/templates/matrizaria/relatorios.html`
- `matrizaria/tests.py`
- `matrizaria/management/commands/provisionar_grupos_matrizaria.py`

### Arquivos existentes a alterar:
- `maintenance_project/settings.py` (Registrar `matrizaria` em `INSTALLED_APPS`)
- `maintenance_project/urls.py` (Incluir `path('matrizaria/', include('matrizaria.urls', namespace='matrizaria'))`)
- `production/routers.py` (Ajustar explicitamente `allow_relation` para relacionamentos locais entre `matrizaria` e `production`)
- `maintenance/views.py` (Ajustar `home_redirect`, `portal_select` e helpers)
- `maintenance/context_processors.py` (Injetar `can_access_matrizaria`)
- `maintenance/templates/maintenance/portal_select.html` (Card da Matrizaria)
- `production/services.py` e `production/templates/production/machine_detail.html` (Histórico unificado da prensa)
- `Instrucoes.txt` (Documentação da entrega)

---

## 🚫 5. FORA DE ESCOPO

- NÃO cadastrar listas oficiais de serviços ou matrizes físicas reais da empresa (devem ser cadastrados pelos usuários autorizados via `/admin/`).
- NÃO criar cadastro paralelo de prensas (reutilizar obrigatoriamente `maintenance.Machine`).
- NÃO duplicar modelos de catálogo de matrizes (reutilizar `production.ProductionMatrixCatalog`).
- NÃO duplicar rotinas ou queries de leitura SCADA de limites de bladder (consumir `BladderTrackingService`).
- NÃO realizar migrações, conexões ou escritas na base `scada`.
- NÃO permitir exclusão destrutiva ou reabertura de chamados com status `CONCLUIDO`.
- NÃO conceder privilégios de manutenção ou produção para operadores de vulcanização.
- NÃO executar deploy para produção nem reiniciar servidores em produção.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Apenas 1 ambiente virtual (`.venv`) e 1 base de código ativa.
- Validação rigorosa de permissões no backend (decorators e ORM).
- Portabilidade total entre SQLite (desenvolvimento) e MySQL (produção).
- Geração de planilhas Excel em memória via `openpyxl`, com proteção contra injeção de fórmulas.
- Utilização de `settings.AUTH_USER_MODEL` em todos os relacionamentos com usuários.
- Isolamento estrito do banco `scada` (sem migrações e sem escrita).

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Vínculo da Solicitação:** Toda solicitação exige uma prensa cadastrada (`maintenance.Machine`). A matriz física é exigida progressivamente caso o tipo de serviço possua `exige_matriz_fisica=True`.
2. **Ciclos Individuais:** Cada início de trabalho abre um `CicloExecucaoMatrizaria`. O retrabalho abre um novo ciclo numérico sem apagar o anterior.
3. **Descrição Técnica Obrigatória:** A finalização de execução técnica exige preenchimento de `descricao_servico_executado`.
4. **Devolução para Retrabalho:** A reprovação na conferência move o chamado para `AGUARDANDO_RETRABALHO`, registrando motivo obrigatório.
5. **Segregação de Funções (Anti-Autoconferência):** O sistema impede que qualquer usuário que tenha iniciado, finalizado ou participado como responsável de ciclos do chamado aprove a própria conferência.
6. **Controle de Concorrência:** Toda transição de estado valida o status e a versão (`versao`) no ORM em transação atômica.
7. **Relatório Temporal:** Suporte a consulta por execução no período considerando intervalos de ciclos, virada de meia-noite e início prévio.
8. **TV da Matrizaria:** Alterna entre Fila de Serviços (20s) e Alertas de Bladder (15s) sem quebrar caso SCADA esteja offline.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] App `matrizaria` registrado e migrado com sucesso no banco `default`.
- [ ] Usuário com acesso exclusivo entra direto em `/matrizaria/`.
- [ ] Usuário multicontexto visualiza no `/portal/` apenas os módulos a que tem direito.
- [ ] Operador de Vulcanização é impedido de acessar rotas de Manutenção e Produção.
- [ ] Kanban exibe solicitações divididas nas colunas em tempo real.
- [ ] Ciclos de retrabalho são preservados individualmente com datas e autores.
- [ ] Autoconferência é bloqueada pelo backend para quem participou da execução.
- [ ] Relatório exporta planilha Excel em duas abas ("Serviços" e "Histórico") sanitizada contra injeção de fórmulas.
- [ ] TV da Matrizaria opera com alternância suave e resiliência a falhas do SCADA.
- [ ] Histórico da prensa exibe manutenções e serviços de matrizaria conforme filtros do usuário.
- [ ] Suíte de testes automatizados passa 100%.

---

## ⚠️ 9. RISCOS

- **Concorrência entre Operadores:** Mitigado via checagem de versão (`versao`) e transações atômicas no ORM.
- **Sobrescrita em Retrabalho:** Mitigado pela entidade relacional `CicloExecucaoMatrizaria` (1:N).
- **Mutação de Cadastros Futuros:** Mitigado por snapshots mínimos nos chamados e `on_delete=models.PROTECT`.
- **Injeção de Fórmulas no Excel:** Mitigado prefixando células iniciadas com `=`, `+`, `-`, `@` com apóstrofo `'`.
- **Roteador SCADA:** Mitigado garantindo que `matrizaria` pertença exclusivamente ao banco `default`.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. Criar a estrutura do app `matrizaria` e registrar em `INSTALLED_APPS`.
2. Implementar os modelos em `matrizaria/models.py` e ajustar `allow_relation` em `production/routers.py`.
3. Gerar e aplicar migrations locais exclusivamente no banco `default`.
4. Implementar a camada de serviço central `matrizaria/services.py` e command de provisionamento de grupos.
5. Implementar decorators de autorização e atualizar `home_redirect`, `portal_select` e `context_processors`.
6. Implementar views, forms e templates do Kanban, solicitações, conferência e TV.
7. Implementar views de relatório e exportação Excel em duas abas.
8. Integrar aba de Matrizaria na tela de detalhes da máquina na Produção.
9. Criar e executar suíte abrangente de testes automatizados.
10. Atualizar documentação em `Instrucoes.txt`.

---

## 🧪 11. TESTES MANUAIS

1. **Abertura de Chamado:** Logar como Líder de Produção, acessar `/matrizaria/solicitar/`, abrir chamado para uma prensa sem matriz física.
2. **Atendimento Técnico:** Logar como Colaborador da Matrizaria, clicar em "Iniciar Atendimento", verificar mudança de coluna no Kanban e criação do Ciclo 1.
3. **Validação de Matriz Obrigatória:** Selecionar tipo de serviço que exige matriz física e tentar finalizar sem vincular matriz: verificar bloqueio e mensagem amigável.
4. **Finalização Técnica:** Vincular exemplar físico, preencher descrição obrigatória e finalizar: verificar transição para `AGUARDANDO_CONFERENCIA`.
5. **Anti-Autoconferência:** Tentar aprovar com o mesmo usuário executor: validar que o sistema bloqueia a aprovação.
6. **Reprovação / Retrabalho:** Com outro líder ou operador, reprovar informando motivo: verificar transição para `AGUARDANDO_RETRABALHO` e exibição destacada no Kanban.
7. **Retomada e Conclusão:** Colaborador da Matrizaria clica em "Iniciar Retrabalho" (Ciclo 2), finaliza novamente, e o líder aprova definitivamente: verificar status `CONCLUIDO`.
8. **Relatório e Excel:** Acessar `/matrizaria/relatorios/`, filtrar por execução na data do serviço e baixar o Excel: verificar as abas "Serviços" e "Histórico".
9. **Painel TV:** Acessar `/matrizaria/tv/` e validar alternância suave entre serviços e alertas de bladder.
10. **Isolamento de Segurança:** Logar com Operador da Vulcanização e tentar acessar `/dashboard/` ou `/producao/`: verificar recusa e redirecionamento.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

- **Suíte de Testes Automatizados:** 19 testes automatizados em `matrizaria/tests.py` com 100% de sucesso.
- **Relatório de Validação:** Aprovado em todos os critérios de concorrência, integridade referencial, timezone local e políticas de sessão.

---

## 🛠️ 13. AJUSTES OPERACIONAIS, CONTROLE DE SESSÃO E TV (RODADA 2)

### 1. TV — Sincronização Dinâmica Completa de Chamados e Contadores
- **Causa Raiz Identificada:** O script de polling da TV atualizava apenas elementos de contagem (`innerText`), não manipulando o DOM das listas de cards (`#list-solicitados`, `#list-execucao`, `#list-conferencia`, `#list-bladders`), além de desconsiderar chamados em retrabalho na coluna inicial. O relógio e telemetria também exibiam desvio de UTC em relação ao fuso local.
- **Solução Implementada:** 
  - Templates parciais dedicados (`tv_col_solicitados.html`, `tv_col_execucao.html`, `tv_col_conferencia.html`, `tv_col_bladders.html`) renderizados no backend via `render_to_string`.
  - Inclusão de `fila_solicitados` combinando retrabalhos e novas solicitações na primeira coluna.
  - O endpoint `/matrizaria/api/tv/data/` devolve fragmentos HTML pré-renderizados e contadores atômicos.
  - JavaScript da TV atualiza o innerHTML dos contêineres e sincroniza contadores sem necessidade de F5, mantendo cadência de 15s sem reiniciar rotação visual nem perder dados em falhas transitórias.
  - Correção de fuso horário utilizando `timezone.localtime(timezone.now())` garantindo sincronia perfeita com o relógio local.

### 2. Chamados Cancelados — Consulta Canônica e Relatórios
- **Critério Temporal:** Adicionado critério canônico `"CANCELADAS"` em `MatrizariaService.consultar_relatorio` e no formulário `RelatorioFiltroForm`, filtrando especificamente por `data_cancelamento`.
- **Integridade:**
  - Localiza chamados cancelados antes do início técnico e chamados cancelados durante a execução (cujo ciclo ativo é encerrado com `INTERROMPIDO_CANCELAMENTO`, sem inventar datas ou duração de conclusão fictícia).
  - Consulta `"ABERTAS"` continua incluindo cancelados abertos no período quando o filtro de status permitir.
  - Consulta `"COM_EXECUCAO"` reflete exclusivamente intervenção técnica real.
- **Interface e Atalhos:**
  - Botão de atalho rápido "Cancelados" no Kanban operacional para usuários com permissão de relatório.
  - Seletor rápido "Chamados Cancelados no Mês Atual" na tela de relatórios.
  - Alerta explicativo quando a combinação "Cancelado + Execução no período" não localizar registros, oferecendo link direto para consulta por cancelamento.
- **Exportação:** Exportação Excel inclui registros cancelados com exibição de quem cancelou, data/hora e motivo, com sanitização de fórmulas.

### 3. Logout por Inatividade Humana e Perfil Exclusivo de TV
- **Reutilização do Middleware:** Atualizado `SessionExpiryByProfileMiddleware` em `maintenance/middleware.py` com autoridade estrita do servidor:
  - `INACTIVITY_TIMEOUT_SECONDS = 300` (5 minutos configurável centralmente em `settings.py`).
  - `INACTIVITY_WARNING_SECONDS = 30` (aviso prévio de 30s com contagem regressiva).
  - Consultas em segundo plano (`/matrizaria/api/tv/data/`, `/api/session/status/`) NÃO renovam inatividade.
  - Interações humanas reais (cliques, toques, digitação, rolagem) renovam a sessão via endpoint autenticado e protegido por CSRF `/api/session/keep-alive/` (com debounce).
  - Sincronização multi-abas via `localStorage` e verificação imediata ao retornar de suspensão/retomada.
  - Bloqueio com redirecionamento para login com mensagem clara de expiração.
- **Perfil Dedicado de TV:**
  - Função estrita `is_dedicated_tv_account`: usuário ativo, sem permissões de staff/superuser, sem grupos operacionais, pertencente ao grupo `Visualizador` ou `Visualizador Matrizaria` (ou username `tv` / `tv_matrizaria`).
  - Sessão perpétua de exibição contínua sem logout por inatividade de periféricos.
  - Usuários comuns ou administradores visualizando a TV continuam sujeitos ao timeout humano de 5 minutos.

### 4. Edição de Solicitação Antes do Primeiro Início
- **Regra de Negócio:** Permitida a edição da solicitação original **apenas** quando `status == 'SOLICITADO'` e nenhum ciclo técnico tiver sido iniciado (`ciclos_execucao.count() == 0`).
- **Campos Editáveis:** Prensa (com rejeição estrita de CHECK-LIST e formatação limpa de rótulos), Tipo de Serviço, Matriz Física (com validação condicional obrigatória), Prioridade e Descrição da Necessidade.
- **Preservação e Auditoria:**
  - Número do chamado, solicitante original, data/hora original e snapshot da abertura são rigorosamente preservados.
  - Registro de auditoria em `HistoricoTransicaoServicoMatrizaria` com `tipo_evento="ALTERACAO_DADO"`, motivo obrigatório e diff detalhado dos campos antes e depois no campo `dados_modificados`.
  - Controle de concorrência com validação de versão (`versao`) no backend dentro de transação atômica. Se um matrizeiro iniciar o chamado enquanto o formulário de edição estiver aberto, o salvamento é recusado.

### 5. Transferência de Responsabilidade — Listagem Restrita a Matrizeiros Habilitados
- **Critério Centralizado:** Método canônico `MatrizariaService.get_matrizeiros_habilitados(solicitacao)`:
  - Usuários ativos (`is_active=True`);
  - Explicitamente vinculados ao grupo operacional `Matrizaria`;
  - Exclusão do responsável atual atribuído ao chamado;
  - Exclusão de contas exclusivas de TV (`tv`, `tv_matrizaria`, grupos `Visualizador` / `Visualizador Matrizaria`).
  - Exclusão de líderes, operadores ou técnicos que não pertençam ao grupo `Matrizaria`.
- **Validação Dupla:** Aplicada a mesma regra no `TransferirResponsabilidadeForm` e na camada de serviço `MatrizariaService.transferir_responsabilidade` (bloqueio de IDs adulterados via POST).
- **Interface:** Exibição de mensagem informativa caso não haja outro matrizeiro disponível: *"Nenhum outro colaborador da Matrizaria está habilitado para receber este chamado."*

