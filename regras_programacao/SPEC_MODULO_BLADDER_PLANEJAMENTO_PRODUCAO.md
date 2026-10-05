# 🧠 SPEC — MÓDULO DE PLANEJAMENTO E CONTROLE DE PRODUÇÃO: SETOR DE BLADDER (APP DEDICADO)

---

## 📌 1. CONTEXTO E DEFINIÇÃO ARQUITETURAL

- **Módulo / Domínio:** Setor de Fabricação e Transformação de Bladders Industriais.
- **Decisão Arquitetural Formal:** Criação do **app Django dedicado `bladder`**, operando no banco transacional `default`.
  - Namespace de URLs: `bladder`
  - App label: `bladder`
  - Isolamento estrito: **NÃO** grava no banco `scada` (coletor SCADA da vulcanização de pneus permanece isolado).
  - Sem duplicação de autenticação: reaproveita `django.contrib.auth.models.User` e Django Groups.
  - Sem múltiplos projetos ou ambientes virtuais: 1 único projeto Django, 1 venv.
  - Compatibilidade bilateral garantida: SQLite (desenvolvimento local) e MySQL (produção).
- **Rotas Principais:**
  - `/bladder/` — Dashboard Operacional em tempo real e indicadores do setor.
  - `/bladder/cronograma/` — Calendário mensal de planejamento e controle do líder.
  - `/bladder/ordens/` — Listagem geral de Ordens de Produção (filtros por processo, status, data e turma).
  - `/bladder/ordens/nova/` — Criação de nova Ordem de Produção pelo líder (com incorporação automática de saldo pendente).
  - `/bladder/ordens/<int:pk>/` — Detalhes da OP, recursos necessários, saldo, histórico e apontamentos.
  - `/bladder/ordens/<int:pk>/editar/` — Edição de parâmetros da OP pelo líder.
  - `/bladder/ordens/<int:pk>/reprogramar/` — Reprogramação de data da OP com motivo obrigatório e preservação no histórico.
  - `/bladder/ordens/<int:pk>/cancelar/` — Cancelamento lógico da OP com motivo obrigatório.
  - `/bladder/operador/` — Interface de Chão de Fábrica simplificada e responsiva para o operador de turno.
  - `/bladder/operador/apontar/<int:pk>/` — Ações operacionais: Iniciar, Concluir, Apontar Parcial e Justificar Ocorrência.
  - `/bladder/operador/apontamento/<int:pk>/corrigir/` — Correção de apontamento próprio dentro do turno aberto.
  - `/bladder/relatorios/` — Fechamento mensal de indicadores, saldo, tempos e matéria-prima teórica.
  - `/bladder/relatorios/exportar-excel/` — Exportação sanitizada em planilha Excel via `openpyxl`.
  - `/portal/` — Hub de seleção de módulos pós-login (com card próprio "Setor de Bladder").

---

## ⚙️ 2. REGRAS DE NEGÓCIO CONFIRMADAS

### 2.1. Escala 12×36 Real (06:00 às 18:00)
1. **Janela Operacional Única:** O setor opera das **06:00 às 18:00** (12 horas).
2. **NÃO existe turno noturno 18:00–06:00.** A suposição anterior de turno noturno foi formalmente descartada.
3. **Alternância das Turmas:**
   - Existem duas equipes principais: **Turma A** e **Turma B**.
   - Ambas trabalham no mesmo horário (06:00–18:00) em **dias alternados**:
     - Dia 1: Turma A
     - Dia 2: Turma B
     - Dia 3: Turma A
     - Dia 4: Turma B
     - ...
4. **Configuração Dinâmica no Admin:**
   - A data de início da alternância **NÃO** é hardcoded no código.
   - Modelo `ConfiguracaoEscalaBladder` gerenciável via `/admin/`:
     - `data_referencia`: data base para o cálculo da alternância.
     - `turma_referencia`: qual turma trabalhou na data de referência (`TURMA_A` ou `TURMA_B`).
     - `hora_inicio`: horário de abertura do turno (padrão 06:00).
     - `hora_fim`: horário de encerramento do turno (padrão 18:00).
     - `ativo`: sinalizador da configuração em vigor.
   - Suporte a ajustes excepcionais de escala através de registros de override para datas específicas (`AjusteEscalaExcepcionalBladder`).

### 2.2. Funcionários de Apoio Fora da Escala 12×36
1. Existem colaboradores que atuam no setor com papel de **Apoio Operacional** (ex: folguistas, reforço semanal, etc.).
2. **Sem hardcode de dias ou horários no código:**
   - Modelo `FuncionarioApoioBladder` administrável via `/admin/`:
     - `usuario`: vínculo com `User`.
     - `papel`: descrição do papel/função de apoio.
     - `tipo_escala`: dias da semana específicos (ex: seg/qua/sex) ou datas pontuais.
     - `dias_semana`: lista/máscara de dias permitidos (0=Segunda, ..., 6=Domingo).
     - `hora_inicio` e `hora_fim`: janela de trabalho do apoio.
     - `ativo`: status do colaborador.
3. O funcionário de apoio pode realizar apontamentos quando autorizado, sem alterar a Turma A/B titular responsável pelo dia.

### 2.3. Nova Filosofia Operacional e Gestão Canônica de Saldos (Homologação do Líder)

> [!IMPORTANT]
> **EVOLUÇÃO DO FLUXO OPERACIONAL (HOMOLOGAÇÃO CANÔNICA DO LÍDER):**
> - **ANTES:** Apontamento individual e contínuo durante a execução + saldo pendente consumido automaticamente via FIFO na próxima OP.
> - **AGORA:** Operador apenas consulta o Quadro Operacional no Tablet durante o turno físico (sem apontamento contínuo) + Fechamento único e auditado no encerramento do turno (`FechamentoTurnoBladder` + `ItemFechamentoTurnoBladder`) realizado exclusivamente pelo operador escalado + Saldo remanescente vira pendência aberta no Ledger (`SaldoPendenteBladder`) + **Incorporação somente por decisão explícita do Líder** em programações futuras.

1. **Unicidade de Turno da OP:**
   - Uma Ordem de Produção pertence estritamente à data/turno para a qual foi programada.
   - Uma OP **NÃO** atravessa intencionalmente mais de um turno ou mais de um dia.
2. **Quadro Operacional no Tablet Chão de Fábrica (`/bladder/operador/`):**
   - Cards compactos (~2 por linha em tablet), exibindo OP, equipamento, modelo, meta e parâmetros técnicos ET.029 reais via modal.
   - Remoção de botões como "Iniciar Produção" e apontamento contínuo durante a atividade física.
3. **Fechamento Auditável do Turno (`/bladder/operador/fechar-turno/`):**
   - Evento único, auditável e idempotente realizado exclusivamente pelo operador de máquina escalado na data/turma.
   - Para cada OP do turno informa-se: quantidade realizada, situação (`CONCLUIDA`, `PARCIAL`, `NAO_REALIZADA`), motivo obrigatório se incompleta (com detalhamento se 'Outro') e observações.
   - Validação contra sobreprodução silenciosa (`realizada > meta` é bloqueada).
   - Bloqueio estrito contra duplo fechamento (idempotência atômica).
4. **Ledger de Saldo e Decisão Explícita do Líder (Zero Consumo Automático):**
   - O saldo não cumprido vira registro no Ledger auditável `SaldoPendenteBladder` com status `PENDENTE`.
   - Ao programar nova OP para o modelo (`/bladder/ordens/nova/`), o sistema localiza pendências e emite aviso destacado com os dados da OP de origem (número, data, máquina, programado, realizado, saldo, turma, motivo).
   - O Líder tem decisão explícita:
     - `[ INCORPORAR PENDÊNCIA ]` (seletivo por saldo ou total): atualiza a nova OP com `saldo_anterior_incorporado`, define `quantidade_planejada = quantidade_nova + saldo_anterior_incorporado`, marca o saldo como `INCORPORADO` e vincula `op_origem -> op_destino` via transação atômica e `select_for_update()`.
     - `[ IGNORAR POR ENQUANTO ]`: o saldo permanece `PENDENTE` no Ledger, nenhuma informação é perdida e a pendência permanece disponível para futuras programações.
   - Se a OP destino for posteriormente cancelada pelo líder, os saldos incorporados são automaticamente reabertos como `PENDENTE`.

### 2.4. Atraso Dinâmico via Configuração de Escala
1. Uma OP nos estados `PENDENTE` ou `EM_EXECUCAO` torna-se dinamicamente **ATRASADA** quando o horário configurado de término do turno (`ConfiguracaoEscalaBladder.hora_fim`) já expirou sem que tenha ocorrido fechamento do turno.
2. **NÃO utilizar horário hardcoded 18:00.** A verificação consulta dinamicamente a `ConfiguracaoEscalaBladder` ativa.
3. Uma vez realizado o fechamento do turno, a OP assume seu resultado final (`CONCLUIDA` ou `PARCIAL`) e **não é mais considerada atrasada**.
4. Respeita o timezone do Django configurado no projeto (`America/Sao_Paulo`).

### 2.5. Reprogramação pelo Líder
1. A reprogramação é realizada na **mesma OP** (não cria clone).
2. A data programada é atualizada pelo líder e refletida dinamicamente no Calendário e no Dashboard.
3. A data anterior, nova data, motivo obrigatório, usuário e carimbo de data/hora são gravados imutavelmente em `HistoricoProgramacaoBladder`.

### 2.6. Cancelamento Lógico Auditável
1. Somente a **Liderança Bladder** (ou superuser) pode cancelar programações.
2. Cancelamento é puramente lógico: altera status para `CANCELADA`.
3. Exclusão física de OPs é bloqueada na rotina operacional.
4. Justificativa de cancelamento é obrigatória e auditada no histórico.

### 2.7. Correção de Apontamentos pelo Operador e pelo Líder
1. **Durante o turno aberto (06:00 às 18:00 do dia do turno):**
   - O próprio operador que fez o lançamento pode corrigir erro de digitação na quantidade ou ocorrência.
2. **Após o encerramento do turno:**
   - Correção restrita ao Líder ou Administrador.
3. **Trilha de Auditoria Obrigatória:**
   - Modelo `HistoricoApontamentoBladder` grava: valor anterior, valor corrigido, usuário autor, carimbo de data/hora e justificativa. Nunca sobrescrever silenciosamente.

### 2.8. Processos do Setor e Vínculo com Máquinas
1. Catálogo dinâmico `ProcessoBladder` contendo os 6 processos iniciais confirmados:
   - `01` - Prensa 01 (vinculada à máquina 408: `PRENSA DE BLADER 01`)
   - `02` - Prensa 02 (vinculada à máquina 409: `PRENSA DE BLADER 02`)
   - `03` - Extrusão de Bladder (vinculada à máquina 419: `EXTRUSORA DE BLADDER 02`)
   - `04` - Extrusão de Apex
   - `05` - Anéis de Vedação
   - `06` - Manuseio de Tarugo
2. Permite ordenação, ativação/desativação e novos processos futuros (ex: Prensa 03 / máquina 420).

### 2.9. Catálogo de Produtos e Análise da Especificação ET.029
1. Auditoria da Planilha `ET.029 - ESPECIFICAÇÃO TÉCNICA - BLA - TESTE.xlsx`:
   - Aba **'BLA - EXTRUSÃO'**: 9 modelos oficiais de fabricação de bladders (`BLA001` a `BLA009`), matrizes de extrusão (`MAT04`, `MAT06`), comprimentos de corte e chanfro, diâmetro do tarugo e pesos de tarugo (`2,500 kg`, `2,000 kg`, `3,100 kg`, `1,500 kg`, `1,200 kg`, `2,600 kg`, `2,850 kg`).
   - Aba **'BLA - VULCANIZAÇÃO'**: tempos de vulcanização (2:00 h), pesos vulcanizados acabados (`2,250 kg`, `1,825 kg`, `2,765 kg`, etc.), circunferências e alturas.
2. Relação com `production.ProductionBladder`:
   - `ProductionBladder` em `production` atende apenas códigos BLA para rastreamento de pneus montados em prensas de vulcanização (sem matriz de corte, diâmetro, chanfro ou peso de tarugo).
   - O app `bladder` terá seu catálogo dedicado `ProdutoBladder`, com FK opcional para `production.ProductionBladder` mantendo coerência sem acoplamento indevido.
3. Carga e Sincronização Idempotente:
   - Management command `import_produtos_bladder` para carregar de forma transacional e idempotente os produtos e especificações da planilha `ET.029`.

### 2.10. Dimensionamento e Consumo Teórico de Matéria-Prima
1. **Regra de Dimensionamento Teórico:**
   $$1 \text{ Tarugo} = 1 \text{ Bladder}$$
2. **Fórmula do Consumo Teórico:**
   $$\text{Necessidade Teórica Planejada (kg)} = Q_{\text{total\_planejada}} \times \text{Peso do Tarugo (kg)}$$
   $$\text{Consumo Teórico do Realizado (kg)} = Q_{\text{realizada}} \times \text{Peso do Tarugo (kg)}$$
3. Rótulo obrigatório na interface: **"Consumo Teórico Calculado"** ou **"Previsão de Matéria-Prima"**.
4. **NÃO inventar consumo real nem balança inexistente.**

### 2.11. Catálogo Dinâmico de Recursos Necessários
1. Modelo `RecursoBladder` categorizado: `MATRIZ`, `COMPOSTO`, `FERRAMENTA`, `MATERIA_PRIMA`, `OUTROS`.
2. M2M `recursos_alocados` na Ordem de Produção + campo livre `recursos_observacoes` para necessidades operacionais pontuais.

### 2.12. Perfis, Permissões e Segurança (Fase Complementar)
1. **Regra de Negócio de Acesso Estrito:**
   - O acesso ao módulo `/bladder/` é restrito exclusivamente a:
     1. Líder do setor de Bladder (`Liderança Bladder`);
     2. Operadores de máquina do setor de Bladder (`Operadores Bladder` com `PerfilOperacionalBladder` ativo);
     3. Funcionários de apoio cadastrados e ativos (`FuncionarioApoioBladder`);
     4. Superusuário apenas como exceção administrativa.
   - **Usuários `staff` genéricos NÃO obtêm acesso ao Bladder apenas por serem staff.**
   - **Usuários de Manutenção, Produção/SCADA, Matrizaria ou outros módulos NÃO acessam `/bladder/` sem permissão explícita no Bladder.**

2. **Modelo `PerfilOperacionalBladder`:**
   - Vinculado ao `User` via `OneToOneField(related_name='perfil_operacional_bladder')`.
   - Campo `turma`: escolhas obrigatórias `TURMA_A` ou `TURMA_B`.
   - Campo `ativo`: boolean (padrão `True`). Se inativo, a operação normal é bloqueada imediatamente.
   - Identifica a equipe de revezamento 12x36 titular do operador regular. Líderes e apoio não necessitam de turma fixa.

3. **Funcionário de Apoio (`FuncionarioApoioBladder`):**
   - Não pertence à Turma A ou B;
   - Possui permissão operacional nos dias/horários configurados no Admin;
   - Registra apontamentos sem alterar a identidade da Turma A/B titular do dia;
   - Não é transformado em operador regular artificialmente.

4. **Permissões do Líder (`Liderança Bladder`):**
   - Acesso integral ao dashboard (`/bladder/`), calendário, ordens, criação de OP, detalhes, reprogramação, cancelamento, saldos, relatórios gerenciais, exportações Excel e acompanhamento de turmas.

5. **Permissões do Operador (`Operadores Bladder`):**
   - Acesso exclusivo ao chão de fábrica (`/bladder/operador/`), início de execução, apontamento (conclusão/parcial/ocorrência) e correção de lançamentos próprios enquanto o turno estiver aberto.
   - Bloqueio no backend em todas as rotas sensíveis (criação, edição, reprogramação, cancelamento, relatórios e exportações). Redirecionamento seguro para `/bladder/operador/`.

6. **Roteamento Central e Portal:**
   - `_user_can_access_bladder(user)`: validação unificada no backend sem bypass para staff genérico.
   - `home_redirect`: se usuário possuir apenas Bladder, líder vai para `/bladder/` e operador vai para `/bladder/operador/`. Usuários com múltiplos módulos são direcionados para `portal_select`.
   - Card "Setor de Bladder" no `portal_select`: visível exclusivamente para colaboradores autorizados com link dinâmico para a respectiva área de trabalho.

### 2.13. Rodada Final de Homologação pelo Cliente (Ajustes Finais de Operação)

1. **Chão de Fábrica (Tablet Industrial):**
   - Atividades abertas antes do encerramento do turno exibem estritamente status `PROGRAMADA` (nunca `Pendente`).
   - `PENDÊNCIA` é consequência exclusiva de fechamento de turno com meta não atingida.
   - Botão único principal `FECHAR TURNO` posicionado no topo da tela em destaque para fácil toque no tablet (removida duplicidade inferior).
   - Menu do operador simplificado na barra de navegação: apenas "Chão de Fábrica", dados da escala e fechamento. Menus administrativos (Dashboard, Calendário, Ordens, Nova OP, Relatórios) restritos no frontend e protegidos no backend com bloqueio seguro.
   - Cards compactos mantidos em ~2 por linha com parâmetros essenciais da ET.029 e modal completo de detalhes técnicos.

2. **Relatórios e Fechamento Mensal:**
   - Filtros no topo por Mês, Ano, Turno (Todos, Turma A, Turma B) e Modelo de Bladder (Todos, modelos cadastrados).
   - Resumo do mês: Programado, Realizado, Saldo Pendente e Cumprimento da Meta (`Realizado / Programado * 100`, divisão segura por zero).
   - Produção por Turno: detalhamento para Turma A, Turma B e Total Consolidado com programado, realizado, saldo e percentual, originados estritamente dos fechamentos de turno.
   - Produção por Dia: tabela cronológica diária com Data, Turma A, Turma B e Total Diário, finalizando com o Acumulado do Período.
   - Pendências do Período: tabela originária dos fechamentos com Data, Turno, Número da OP, Modelo, Programado, Realizado, Saldo e Motivo da pendência.
   - Prevenção absoluta contra dupla contagem: incorporação de saldo em nova OP não duplica realização no acumulado.
   - Exportação Excel espelhada em 5 abas estruturadas com proteção contra injeção de fórmulas.

3. **Ordens de Produção e Rastreabilidade de Pendências:**
   - Padronização de nomenclaturas na listagem: `Qtd. Nova`, `Pendência Incorporada`, `Meta Total`, `Realizado`, `Saldo Gerado` e `Status`.
   - Regras matemáticas: `Meta Total = Qtd. Nova + Pendência Incorporada` e pós-fechamento `Saldo Gerado = Meta Total - Realizado`.
   - Rastreabilidade na ficha da OP (`ordem_detalhe`): tabela estruturada exibindo OP de origem, data da OP de origem, turma de origem, modelo, programado original, realizado original e saldo incorporado, suportando inclusive múltiplas OPs de origem.
   - Status visual padronizado: `PROGRAMADA` (durante turno aberto), `CONCLUÍDA` (meta cumprida), `PARCIAL / PENDÊNCIA` (produção parcial), `NÃO REALIZADA / PENDÊNCIA` (produção zero) e `CANCELADA`.

### 2.14. Nova Rodada de Homologação Funcional — Decisões Canônicas do Líder do Setor

1. **Princípio Canônico:**
   - O RESPONSÁVEL PELO SETOR PLANEJA. O SISTEMA ORGANIZA E REGISTRA. O OPERADOR EXECUTA.
   - Sem estoques mínimos, sem algoritmos de capacidade, sem sugestão de compras ou transferência automática de pendências.

2. **Programação do Dia, Não da Turma:**
   - O líder informa Data, Máquina/Processo, Bladder (Código + Medida), Quantidade e Prioridade opcional.
   - A turma prevista é SEMPRE consequência da escala cadastrada (`ConfiguracaoEscalaBladder` e eventuais ajustes excepcionais).
   - Backend deriva determinística e dinamicamente a turma da data programada.
   - Na reprogramação de data, a turma prevista é automaticamente recalculada com base na nova data.

3. **Seletor de Bladder — Código + Medida:**
   - Seletor exibe estritamente: `CÓDIGO — MEDIDA` (ex: `BLA001 — B200/16`, `BLA004 — B250/12`).
   - Sem poluição visual de descrições longas, parâmetros técnicos ou matrizes no seletor (mantidos na Ficha Técnica).

4. **Quantidade Programada como Meta e Flexibilidade Operacional:**
   - A meta é decisão operacional humana. Não limita a produção máxima.
   - Extrusora pode ter múltiplos modelos programados no mesmo dia. Prensas não bloqueiam múltiplos modelos artificialmente.

5. **Produção Acima da Meta (Sobreprodução Válida):**
   - Quantidade realizada PODE superar a meta programada (ex: meta 20, realizado 22).
   - Resultado: `CONCLUÍDA`. Excedente: `+2 un`. Saldo: `0 un`. Pendência no ledger: `0 un`.
   - Nenhuma justificativa exigida para produção igual ou acima da meta.
   - Percentual de cumprimento matemático: `Realizado / Programado * 100` (ex: 22/20 = 110%), sem corte silencioso em 100%.

6. **Produção Abaixo da Meta (Déficit / Saldo Remanescente):**
   - Meta 20, Realizado 18 -> `PARCIAL / PENDÊNCIA`, Saldo 2 un.
   - Meta 20, Realizado 0 -> `NÃO REALIZADA / PENDÊNCIA`, Saldo 20 un.
   - Exigência estrita de DUAS informações:
     a) Categoria(s) do desvio: suporte a UMA OU MAIS categorias estruturadas (`CategoriaDesvioBladder`: Problema no equipamento, Falta de matéria-prima, Problema de qualidade, Manutenção, Falta de operador, Outro).
     b) Descrição livre obrigatória ("O que aconteceu?").

7. **Cálculo Rigoroso de Pendências e Excedentes (Sem Compensação Cruzada):**
   - Pendência formal gerada estritamente no fechamento do turno.
   - Calculada POR OP: `pendencia_op = max(meta_op - realizado_op, 0)`.
   - Excedente calculado POR OP: `excedente_op = max(realizado_op - meta_op, 0)`.
   - Excedente de um modelo NUNCA compensa o déficit de outro modelo.
   - Diferença líquida geral (`realizado_total - programado_total`) é apenas indicador matemático global.

8. **Pendências no Ledger:**
   - Pendências ficam abertas no Ledger até decisão manual explícita do Líder de incorporar ou ignorar.
   - Nenhuma OP fantasma é gerada automaticamente.

---

## 🏛️ 3. MODELAGEM RELACIONAL PROPOSTA (APP `bladder`)

```
                 ┌────────────────────────────────┐
                 │      maintenance.Machine       │
                 │   (408, 409, 419, 420...)      │
                 └───────────────┬────────────────┘
                                 │ 1 (opcional)
                                 │
                                 │ N
                 ┌───────────────┴────────────────┐
                 │        ProcessoBladder         │
                 │  (01 a 06 + dinâmicos futuros) │
                 └───────────────┬────────────────┘
                                 │ 1
                                 │
                                 │ N
┌────────────────────────┐  1    │   1  ┌────────────────────────┐
│     ProdutoBladder     ├───────┼─────┤  RecursoBladder (M2M)   │
│ (Código, Peso Tarugo)  │       │      └────────────────────────┘
└───────────┬────────────┘       │
            │ 1                  │
            │                    ▼
            │ N        ┌──────────────────────────────────┐
            ├─────────►│       OrdemProducaoBladder       │
            │          │ (Qtd Nova, Saldo Inc, Total,     │
            │          │  Data, Status, Turma, Recursos)  │
            │          └───────┬─────────┬──────────┬─────┘
            │                  │ 1       │ 1        │ 1
            │                  │         │          │
            ▼                N │       N │        N │
┌────────────────────────┐     ▼         ▼          ▼
│  SaldoPendenteBladder  │  ┌─────────┐┌─────────┐┌─────────┐
│ (Ledger: OP Origem,    │  │Apontam. ││Histórico││Hist.Apon│
│  OP Destino, FIFO)     │  │Turno    ││Program. ││(Auditor)│
└────────────────────────┘  └─────────┘└─────────┘└─────────┘
```

---

## 🧪 4. PLANO DE FASES AUTÔNOMAS

- **FASE 0: Governança, SPEC e Análise Técnica** (Concluída nesta etapa)
- **FASE 1: Fundação do App Bladder, Modelos de Escala, Processos, Decorators e Portal**
- **FASE 2: Catálogo de Produtos (ET.029), Ordem de Produção, Calendário e Consumo Teórico**
- **FASE 3: Interface Operacional do Chão de Fábrica (/bladder/operador/)**
- **FASE 4: Execução Parcial, Ledger de Saldo FIFO e Incorporação Automática**
- **FASE 5: Auditoria, Reprogramação, Cancelamento Lógico e Correção de Apontamentos**
- **FASE 6: Indicadores em Tempo Real, Cálculo Dinâmico de Atraso e Dashboard**
- **FASE 7: Consolidação de Recursos Necessários e Dimensionamento de Matéria-Prima**
- **FASE 8: Relatórios de Fechamento Mensal e Exportação Excel Sanitizada**
- **FASE 9: Usabilidade, Responsividade e Homologação Técnica Local**
- **FASE 10: Regressão Geral, Verificações de Segurança e Documentação Final**

---
