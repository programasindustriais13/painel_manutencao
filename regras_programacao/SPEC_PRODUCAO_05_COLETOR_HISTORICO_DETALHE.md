# 🧠 SPEC 05 — COLETOR, HISTÓRICO E DETALHE DAS MÁQUINAS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/` (Dashboard Geral de Produção)
  - `/producao/maquinas/<int:pk>/` (Detalhe e Histórico da Máquina)
- **Contexto(s):** Módulo de Produção — Persistência local de eventos de parada, serviço de coleta em segundo plano e histórico detalhado por máquina com KPIs.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras:** SPEC 02 (Auditoria), SPEC 03/03A (Cadastros locais e Hardening do Router), SPEC 04 (Integração Scada e Dashboard Visual).

---

## ❗ 2. PROBLEMA ATUAL

- O estado das máquinas é atualmente calculado de forma transiente na memória durante a renderização do dashboard `/producao/`, sem histórico persistido no banco local.
- Não existem modelos locais para armazenar o estado ativo da máquina (`ProductionMachineState`) nem o histórico de paradas (`ProductionDowntimeEvent`) no banco `default`.
- Não existe um coletor em segundo plano (`collect_production_scada`) para monitorar o Scada-LTS de forma contínua, idempotente e resiliente.
- Não existe uma tela de detalhes por máquina (`/producao/maquinas/<id>/`) para consultar a linha do tempo de paradas, motivos, cronômetro persistido e KPIs do período (tempo total parado, quantidade, maior parada e média).

---

## 🎯 3. OBJETIVO

1. **Modelos Locais:** Criar `ProductionMachineState` e `ProductionDowntimeEvent` no banco `default` do app `production` e registrá-los em `ScadaRouter.LOCAL_MANAGED_MODELS`.
2. **Máquina de Estados Idempotente:** Implementar regras estritas de transição operacional (Produzindo ↔ Parada) em `ProductionStateService`, garantindo resiliência a falhas de comunicação e retomada pós-crash sem duplicação de eventos.
3. **Coletor de Background:** Criar o comando `python manage.py collect_production_scada` com opções `--once` e `--interval`, lock cross-process, tratamento de sinais (Ctrl+C) e isolamento total do processo web.
4. **Detalhe da Máquina:** Criar a rota `/producao/maquinas/<int:pk>/` com cronômetro persistido, situação de cavidades, meta, comunicação, filtros por período (`hoje`, `7d`, `30d`, intervalo customizado) e tabela de histórico com KPIs.
5. **Segurança e Testes:** Manter total isolamento do banco Scada, garantindo escrita estrita no banco `default` e suíte de testes cobrindo todas as regras de transição, concorrência e filtros.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a alterar/criar:
- `production/models.py`: Criar `ProductionMachineState` e `ProductionDowntimeEvent`.
- `production/routers.py`: Adicionar `"productionmachinestate"` e `"productiondowntimeevent"` em `LOCAL_MANAGED_MODELS`.
- `production/migrations/0004_...`: Gerar migration aditiva exclusiva no banco `default`.
- `production/services.py`: Atualizar `ProductionStateService` com a máquina de estados, persistência idempotente e serviços de estatística por período.
- `production/management/commands/collect_production_scada.py` [NOVO]: Implementar o coletor CLI.
- `production/views.py`: Adicionar view `machine_detail`.
- `production/templates/production/machine_detail.html` [NOVO]: Implementar interface responsiva de detalhe da máquina.
- `production/urls.py`: Adicionar rota `maquinas/<int:pk>/`.
- `production/tests.py`: Expandir suíte de testes com cobertura completa.
- `Instrucoes.txt`: Registrar a execução da SPEC 05.
- `implementation_plan.md`: Atualizar progresso.
- `walkthrough.md`: Registrar evidências de conclusão.

---

## 🚫 5. FORA DE ESCOPO

- NÃO executar `migrate --database=scada` nem modificar schemas do Scada-LTS.
- NÃO escrever ou alterar nenhum dado no banco Scada (leitura puramente estrita em `scada`).
- NÃO alterar migrations anteriores (`0001`, `0002`, `0003`).
- NÃO iniciar o coletor dentro de `AppConfig.ready()` nem criar threads no processo web (Waitress/Gunicorn).
- NÃO criar gráficos avançados nesta SPEC.
- NÃO configurar serviços do Windows Server (NSSM) nesta SPEC (pertence à SPEC 06).
- NÃO alterar o banco `db.sqlite3` manualmente.
- NÃO conectar ao ambiente de produção.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ Não criar múltiplos ambientes virtuais ou duplicar apps Django.
- ✅ Manter escrita restrita ao banco `default`.
- ✅ Acesso exclusivo para `Liderança de Produção` e Superusuários (bloqueio de usuários da Manutenção).
- ✅ Fallback amigável quando o Scada estiver offline (exibir status de comunicação sem erro 500).

---

## ⚙️ 7. REGRAS DE NEGÓCIO E MÁQUINA DE ESTADOS

1. **Produzindo → Parada:**
   - Criar **apenas um** evento em `ProductionDowntimeEvent` com `fim=None`.
   - Registrar `inicio`, `snapshot_valor_status`, `timestamp_inicial_scada` e `motivo_geral`.
   - Atualizar `ProductionMachineState` (`estado_atual="PARADA"`, `inicio_estado_atual=inicio`).
2. **Continua Parada:**
   - Não criar eventos duplicados.
   - Manter o evento atual aberto e atualizar o motivo se modificado.
3. **Parada → Produzindo:**
   - Fechar o evento aberto preenchendo `fim` e `timestamp_final_scada`.
   - Calcular a duração em segundos (`duracao_segundos`).
   - Atualizar `ProductionMachineState` (`estado_atual="PRODUZINDO"`, `inicio_estado_atual=fim`).
4. **Sem Comunicação ou Dado Stale:**
   - Não abrir novo evento de parada.
   - Não fechar evento de parada existente.
   - Não interpretar como parada operacional.
   - Preservar o último estado industrial válido no registro.
   - Marcar `sem_comunicacao=True` ou `dado_desatualizado=True` em `ProductionMachineState`.
5. **Retorno da Comunicação:**
   - Reconciliar o estado atual com base na nova leitura do Scada sem duplicar eventos.
6. **Reinício do Processo:**
   - Recuperar eventos abertos existentes (`fim__isnull=True`).
   - Continuar o cronômetro sem gerar nova parada para a mesma ocorrência.
7. **Idempotência:**
   - Operações protegidas por `transaction.atomic` no banco `default`.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Models `ProductionMachineState` e `ProductionDowntimeEvent` criados no banco `default`.
- [ ] `LOCAL_MANAGED_MODELS` do `ScadaRouter` atualizado com os novos modelos.
- [ ] Migration aditiva gerada sem erros e aplicada no `default`.
- [ ] Máquina de estados executa transições Produzindo ↔ Parada sem duplicação.
- [ ] Perda de comunicação/stale não abre nem fecha eventos.
- [ ] Management command `collect_production_scada` roda com `--once` e `--interval` e possui lock de processo.
- [ ] Detalhe da máquina em `/producao/maquinas/<id>/` exibe cronômetro persistido, cavidades, metas e tabela de histórico.
- [ ] Filtros por data (`hoje`, `7d`, `30d`, intervalo) calculam KPIs (tempo total, quantidade, maior e média) considerando sobreposição de eventos.
- [ ] Bloqueio de acesso para usuários da Manutenção em `/producao/maquinas/<id>/`.
- [ ] Suíte de testes completa (production + maintenance) executada e aprovada 100%.

---

## ⚠️ 9. RISCOS

- **Lock Preso:** Garantir que o lock de arquivo seja liberado em saídas normais, exceções ou sinais (SIGINT/SIGTERM).
- **Cálculo de KPIs com Eventos Parcialmente Sobrepostos:** Garantir que apenas a fração do evento dentro da janela do filtro seja somada nos KPIs.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. **Fase 1 (Arquiteto):** Modelagem de dados, inclusão no router, migration aditiva e estrutura da máquina de estados.
2. **Fase 2 (Backend):**
   - Implementação dos modelos e atualização do `ScadaRouter`.
   - Lógica de transição idempotente em `ProductionStateService`.
   - Management command `collect_production_scada`.
   - View e template `/producao/maquinas/<id>/` com filtros e KPIs.
   - Suíte de testes automatizados.
3. **Fase 3 (QA):** Execução do checklist de auditoria, verificações de migração, permissões e testes globais.
4. **Fase 4 (Documentação e Commit):** Atualizar `Instrucoes.txt`, `implementation_plan.md`, `walkthrough.md` e criar commit Git único.

---

## 🤖 REGISTRO DOS SUBAGENTES

### 1. Arquiteto
- Estrutura analisada e validada.
- Separação entre modelos locais (`default`), leitura (`scada`) e serviço de transições idempotentes garante alta consistência e ausência de side effects.
- Lock cross-process via arquivo garante que apenas um coletor execute por vez.

### 2. Backend
- Modelos `ProductionMachineState` e `ProductionDowntimeEvent` implementados em `production/models.py`.
- `ScadaRouter.LOCAL_MANAGED_MODELS` atualizado. Migration `0004` gerada e aplicada no `default`.
- Transição de estados idempotente com `transaction.atomic` implementada em `ProductionStateService`.
- Management command `collect_production_scada` com `--once`, `--interval` e lock por arquivo criado.
- View `machine_detail` e template `machine_detail.html` com filtros por período e KPIs responsivos implementados.

### 3. QA
- Testes automatizados em `production/tests.py` restaurados (SPEC 04) e expandidos (SPEC 05) para cobrir roteamento, transições, concorrência, coletor, falhas de comunicação, visualizações de detalhe e filtros por data.
- Bateria completa de testes executada com 100% de sucesso (44/44 testes do app `production` e 67/67 testes da suíte global).
