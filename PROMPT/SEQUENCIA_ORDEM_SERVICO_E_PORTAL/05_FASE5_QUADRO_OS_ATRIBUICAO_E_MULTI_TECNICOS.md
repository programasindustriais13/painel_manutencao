# PROMPT — FASE 5: QUADRO DE OSS, ATRIBUIÇÃO & SUPORTE A MÚLTIPLOS TÉCNICOS

## 📌 Contexto & Objetivo
No dia a dia industrial, ordens de serviço complexas exigem o trabalho conjunto de mais de um técnico (ex: manutenção mecânica + elétrica). Além disso, operadores e líderes precisam de uma visão clara das OSs pendentes na fila da fábrica e a capacidade de designar técnicos específicos para cada serviço.

Nesta Fase 5, vamos implementar:
1. **O Quadro de Ordens de Serviço (`/ordens-servico/`).**
2. **A funcionalidade de Operador Atribuir/Designar Técnico para a OS.**
3. **A ação do Técnico de Assumir/Iniciar uma OS da fila.**
4. **O suporte completo a Múltiplos Técnicos trabalhando na mesma OS.**
5. **Integração visual com a tela de técnicos (`/management/`) e Modo TV (`/tv/`).**

---

## 🔒 Regras da Constituição a Seguir
- **Regra Crítica de Concorrência:** Um técnico só pode ter, no máximo, **UMA** alocação com status `'EM_ATENDIMENTO'` por vez. Se o técnico já estiver atendendo outra máquina, o sistema deve exigir a pausa ou conclusão do atendimento atual antes de entrar na nova OS.
- Técnicos marcados como ausentes (férias, folga, atestado) **não podem** ser alocados em novas OSs.
- Validação de permissões no Backend.
- Registrar resumo das alterações em `Instrucoes.txt`.

---

## 🛠️ Especificações Técnicas Detalhadas

### 1. View e Rota do Quadro de OSs (`maintenance/views.py` -> `os_board`)
- **Rota:** `/ordens-servico/` (nome: `os_board`).
- **Abas / Seções na Tela:**
  - **Aba 1 — Pendentes (Na Fila):**
    - Cards com: Número da OS, Criticidade (Badge com cor), Máquina, Setor, Solicitante, Tempo de espera desde a abertura, Miniatura da foto de abertura, Técnico designado (se houver).
    - Botões de ação:
      - Para Técnicos: Botão **"Iniciar Atendimento"**.
      - Para Operadores/Líderes: Botão **"Atribuir Técnico"** (modal com seleção de técnicos disponíveis) ou **"Cancelar OS"**.
  - **Aba 2 — Em Andamento:**
    - Mostra as OSs em execução com a lista de técnicos alocados nela no momento.
    - Botão **"Entrar nesta OS / Trabalhar em Equipe"** (para um 2º ou 3º técnico se juntar ao serviço).
    - Botão **"Ver Detalhes / Atualizações"**.
  - **Aba 3 — Concluídas:**
    - Histórico recente com filtros por data, máquina e setor, exibindo miniaturas da foto de abertura e foto de conclusão.

### 2. Fluxo: Técnico Iniciar / Assumir OS (`maintenance/views.py` -> `os_start_service`)
- Rota: `/ordens-servico/<int:os_id>/iniciar/`
- Lógica de negócio:
  1. Identifica o técnico vinculado ao usuário logado (ou selecionado pelo operador).
  2. Valida se o técnico não está ausente (`technician.is_ausente`).
  3. Valida concorrência: Se o técnico já possui alocação ativa (`active_allocation`), avisa que é necessário pausar o serviço atual primeiro.
  4. Cria uma nova instância de `Allocation`:
     - `tecnico = technician`
     - `maquina = os.maquina`
     - `ordem_servico = os`
     - `atividade_observacao = f"OS #{os.numero_os} - {os.descricao_falha}"`
     - `data_inicio = timezone.now()`
     - `status = 'EM_ATENDIMENTO'`
     - `usuario_operador = request.user`
  5. Atualiza o status do técnico para `'EM_ATENDIMENTO'`.
  6. Atualiza o status da `OrdemServico` para `'EM_ANDAMENTO'`.

### 3. Fluxo: Múltiplos Técnicos na Mesma OS (`os_join_team`)
- Rota: `/ordens-servico/<int:os_id>/entrar-equipe/`
- Lógica de negócio:
  1. Permite que outro técnico disponível entre na mesma OS.
  2. Cria uma nova `Allocation` individual para esse 2º técnico, apontando para a mesma `OrdemServico`.
  3. Cada técnico tem seu próprio ciclo de pausas e tempo registrado com precisão, mas todos consolidados sob a mesma OS.

### 4. Integração com o Painel de Técnicos (`/management/`) e TV (`/tv/`)
- No card do técnico em `/management/`: se o atendimento for vinculado a uma OS, exibir a badge clicável: `[ OS #10482 ]`.
- No painel da TV (`/tv/`): exibir junto à máquina a tag da OS em atendimento.

---

## 🧪 Critérios de Aceite e Validação
1. Visualização clara do Quadro de OSs com abas de Pendentes, Em Andamento e Concluídas.
2. Atribuição de técnico por operador: a OS passa a exibir o nome do técnico designado.
3. Início de atendimento por um técnico:
   - Cria alocação no banco vinculada à OS.
   - Status da OS muda para `EM_ANDAMENTO`.
   - Card do técnico fica `EM_ATENDIMENTO`.
4. Teste de múltiplos técnicos:
   - Técnico A inicia a OS #1001.
   - Técnico B clica em "Entrar nesta OS".
   - O banco registra 2 alocações ativas ligadas à OS #1001.
   - Ambos aparecem como trabalhando na mesma máquina/OS.
5. Validação de bloqueio de concorrência: técnico com alocação ativa não consegue iniciar uma nova sem pausar a anterior.
6. Atualização registrada em `Instrucoes.txt`.
