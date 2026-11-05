# 🧠 SPEC — REESTRUTURAÇÃO DO MÓDULO BLADDER, ESTOQUE DR-201 E INTEGRAÇÕES

---

## 📌 1. CONTEXTO

- **URLs Envolvidas:**
  - `/bladder/` (Dashboard Executivo do Líder — Tema Escuro, Indicadores Chave, Alertas de Estoque)
  - `/bladder/operador/` (Ambiente Principal do Operador / Chão de Fábrica — Tema Claro, 3 Abas: Recados Recebidos, Atividades do Turno, Histórico)
  - `/bladder/operador/fechar-turno/` (Fechamento do Turno Simplificado — Apresentação consolidada de atividades, produção, recados e estoque)
  - `/bladder/ordens/` e `/bladder/ordens/nova/` (Ordens de Produção com formulário simplificado, derivação de turma por escala e OPs atrasadas clicáveis)
  - `/bladder/estoque/` (NOVO — Gestão de Estoque de Bladders Acabados, Semáforo Crítico/Atenção/Normal, Cobertura em Dias, Ação Gerar OP)
  - `/bladder/estoque/movimentar/` (NOVO — Entrada física, Saída para vulcanização e Ajuste auditado)
  - `/bladder/estoque/auditoria-dr201/` (NOVO — Auditoria e reconciliação dos dados da DR-201)
  - `/bladder/passagem-turno/` e `/bladder/recados/` (Passagem de turno com correção de duplicidade em edição e entrega pós-18h)
  - `/bladder/relatorios/` (Relatórios consolidados de produção, OPs, atividades e estoque)
- **Contextos:**
  - Operação de Chão de Fábrica no Tablet Industrial (Tema Claro, botões grandes, navegação touch)
  - Gestão e Planejamento da Liderança (Tema Escuro, contraste amarelo/cinza, indicadores objetivos)
  - Controle de Estoque físico de Bladders Acabados integrado ao catálogo ET.029
  - Integração com o microserviço WhatsApp existente do módulo Manutenção
- **Perfis Afetados:**
  - Líder Bladder
  - Operador Bladder (Turma A e Turma B na escala 12×36)
  - Funcionário de Apoio Bladder
  - Superusuário

---

## ❗ 2. PROBLEMA ATUAL

1. **Interface e Navegação:**
   - O operador e o líder compartilhavam visualmente padrões muito densos. O operador precisa de um tema claro, botões grandes e cards intuitivos, com foco em suas atividades e passagem de turno, sem menus gerenciais confusos.
   - Havia menus duplicados (ex: Nova OP no menu principal fora de Ordens de Produção).
2. **Atividades Rígidas:**
   - Atividades operacionais de chão de fábrica (limpeza, manutenção, organização, extrusão, corte) exigiam indiscriminadamente quantidade, modelo de Bladder e peso de tarugo, mesmo quando tais campos não faziam sentido prático para a tarefa.
3. **Passagem de Turno:**
   - Ao editar um recado operacional, a versão antiga continuava aparecendo ativa, gerando poluição e duplicidade.
   - Recados gerados após as 18:00 (término do turno formal) sofriam risco de transitar por dois turnos antes de atingir a equipe titular correta, devido a cálculos baseados estritamente na data sem considerar timezone e escala.
   - Falta de controle visual de expiração de informativos já lidos (24h/48h) sem exclusão do banco.
4. **Estoque de Bladders Acabados:**
   - O controle de estoque era mantido fora do Django, em planilha Google Sheets (`DR.201`).
   - A planilha `DR.201` funciona como formulário de respostas (Google Forms) de leituras de etiquetas (com mais de 2.900 registros individuais), sem fórmulas consolidadas de saldo ou estoque mínimo, havendo saídas registradas sem entrada prévia (saldo BLA003 negativo na soma bruta de eventos).
   - O cliente deseja abandonar o fluxo de formulário externo e controlar o estoque de Bladders acabados de forma centralizada, segura e atômica dentro do app `bladder` no Django.
5. **Integração WhatsApp:**
   - O cliente necessita de resumo automático matinal de estoque (dias úteis às 07:30) com modelos críticos e em atenção. O projeto já conta com infraestrutura Baileys Node.js em `whatsapp_service/`, mas o Bladder não possuía rotina configurável e idempotente para utilizá-la com segurança.

---

## 🎯 3. OBJETIVO

1. **Reestruturação Visual Dual:**
   - Ambiente do Líder: Tema escuro (#1a1a1a / #252525), tipografia nítida, acentos em amarelo industrial, foco em tomada de decisão e indicadores limpos.
   - Ambiente do Operador: Tema claro (#f8f9fa / #ffffff), cards brancos de alto contraste, botões touch amplos (mínimo 48px), paleta semafórica (verde = concluído, amarelo = atenção, vermelho = crítico).
2. **Navegação Simplificada:**
   - Líder: 1. Visão Geral; 2. Turno; 3. Ordens de Produção (com Nova OP interna); 4. Estoque; 5. Calendário; 6. Relatórios.
   - Operador: Entrada direta em **Turno** (`/bladder/operador/`), com 3 abas essenciais: *Recados Recebidos*, *Atividades do Turno* e *Histórico*.
3. **Tipos de Atividades Flexíveis:**
   - Modelo configurável `TipoAtividadeBladder` definindo por tipo: exige quantidade, exige modelo, exige dados técnicos de tarugo, exige observação, permite anexo, exige conclusão.
   - Separação clara entre *Atividades Quantitativas de Produção* (ligadas a OPs) e *Atividades Operacionais* (conclusão direta).
4. **Passagem de Turno Robusta:**
   - Formulário ultrassimplificado: Mensagem, Tipo (Informativo / Ação necessária), Destino automático.
   - Edição idempotente: atualização do registro ativo com trilha de versão, eliminando recados duplicados.
   - Cálculo preciso de destino considerando horário real, timezone local, hora de término da escala (`hora_fim`) e alternância da escala 12×36.
   - Leitura com marcação de ciência e expiração visual de informativos (24h/48h) preservando o histórico imutável.
5. **Estoque de Bladders Acabados no App Bladder:**
   - Reutilização direta de `ProdutoBladder` (10 modelos: BLA001 a BLA010).
   - Ledger transacional auditável `MovimentacaoEstoqueBladder` (Entrada, Saída, Ajuste de Inventário).
   - Bloqueio estrito de estoque negativo e proteção contra envio duplo.
   - Entrada física não automática: conclusão de OP não gera entrada fantasma.
   - Ajustes de inventário restritos ao líder, registrando saldo anterior, novo, diferença, usuário e justificativa.
6. **Alertas Semafóricos e OP Assistida:**
   - Crítico: `estoque <= estoque_minimo`
   - Atenção: `estoque > estoque_minimo e estoque <= 1.5 * estoque_minimo`
   - Normal: `estoque > 1.5 * estoque_minimo`
   - Cobertura estimada: `Estoque Atual / Consumo Médio Diário` (baseado em saídas reais dos últimos 30 dias; "histórico insuficiente" se não houver dados).
   - Ação `GERAR OP` em modelos críticos com sugestão inicial `max(0, minimo - atual)`.
7. **Integração WhatsApp Reutilizável:**
   - Reutilização do microserviço Node.js Baileys (`WHATSAPP_SERVICE_URL`).
   - Modelo de configuração `ConfiguracaoWhatsAppBladder` e comando de agendamento idempotente para dias úteis às 07:30.
   - Execução defensiva sem disparo real durante o desenvolvimento.
8. **Governança e Rastreabilidade:**
   - 100% no banco `default`. Zero tabelas ou escritas no alias `scada`.
   - Backup local prévio realizado.
   - Nenhuma migration destrutiva.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Modelos (`bladder/models.py`):
- `ProdutoBladder`: Adição dos campos `estoque_minimo` (PositiveIntegerField, default=0) e `estoque_atual` (IntegerField, default=0).
- `TipoAtividadeBladder`: Cadastro de tipos de atividade com flags condicionais de formulário.
- `AtividadeOperacionalTurnoBladder`: Registro de atividades operacionais do turno.
- `MovimentacaoEstoqueBladder`: Ledger auditável de movimentações (Entrada, Saída, Ajuste, Carga Inicial DR-201).
- `ConfiguracaoWhatsAppBladder`: Configuração de envio automático do resumo matinal de estoque.
- `MensagemPassagemTurnoBladder`: Ajuste nos campos de versão/edição e expiração visual.

### Serviços (`bladder/services.py`):
- Reconciliação e leitura da planilha Google Sheets DR-201 via Service Account.
- Motor de movimentação atômica de estoque (`registrar_entrada_estoque`, `registrar_saida_estoque`, `registrar_ajuste_estoque`).
- Cálculo de status semafórico, cobertura em dias e sugestão de OP.
- Motor de cálculo de próximo turno operacional refinado para horários pós-escala.
- Serviço de geração de resumo de estoque e despacho seguro ao WhatsApp Baileys.

### Formulários e Views (`bladder/forms.py`, `bladder/views.py`, `bladder/urls.py`):
- Views de Estoque: `/bladder/estoque/`, `/bladder/estoque/movimentar/`, `/bladder/estoque/ajuste/`, `/bladder/estoque/gerar-op/<id>/`.
- Views de Auditoria DR-201: `/bladder/estoque/dr201/`.
- Views de Atividades Operacionais e configuração de tipos.
- Adaptação das telas de Operador (`operador_turno.html`), Líder (`dashboard.html`), Ordens (`ordens_lista.html`, `ordem_form.html`) e Fechamento (`fechamento_turno.html`).

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO executar suítes de testes automatizados (`manage.py test`, `pytest`) nesta rodada.
- ❌ NÃO criar novo app Django (tudo permanece estritamente no app `bladder`).
- ❌ NÃO tocar no banco `scada` (zero escritas ou migrations).
- ❌ NÃO criar novo serviço WhatsApp ou nova biblioteca Baileys (reutilizar a infraestrutura existente).
- ❌ NÃO escrever na planilha Google Sheets DR-201 (acesso 100% somente leitura).
- ❌ NÃO aplicar saldos iniciais de origem incerta ou inconsistente sem reconciliação prévia.
- ❌ NÃO apagar registros, OPs antigas, históricos ou cadastros existentes.
- ❌ NÃO realizar commit, push ou deploy em produção.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION & SEGURANÇA)

- Seguir estritamente `constitution.md`.
- Usar ORM do Django sempre, garantindo total compatibilidade entre SQLite local e MySQL de produção.
- Controle de acesso no backend via decorators: `@lider_bladder_required`, `@operador_ou_lider_bladder_required`.
- Proteção CSRF em todos os formulários.
- Backup prévio do banco local `db.sqlite3` confirmado.
- Credenciais e segredos protegidos contra exibição em logs e inclusão no Git.

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO

- [ ] Auditoria da planilha DR-201 concluída com mapeamento completo de modelos, lotes e saldos.
- [ ] Interface visual dual implementada (Líder escuro, Operador claro).
- [ ] Atividades flexíveis cadastradas e integradas ao Chão de Fábrica.
- [ ] Passagem de turno corrigida para edição idempotente e entrega pós-18h com expiração visual.
- [ ] Ordens de produção com formulário simplificado e OPs atrasadas clicáveis.
- [ ] Ledger de estoque operacional com bloqueio de saldo negativo e transações atômicas.
- [ ] Semáforo de estoque (Crítico, Atenção, Normal) e cálculo de cobertura em dias.
- [ ] Ação Gerar OP assistida funcional para o Líder a partir de modelo crítico.
- [ ] Módulo WhatsApp configurável e agendamento preparado para dias úteis às 07:30 sem envios de teste reais.
- [ ] Dashboard e Relatórios integrando produção e estoque sem inconsistências.
- [ ] `manage.py check` e `makemigrations --check --dry-run` sem erros.

