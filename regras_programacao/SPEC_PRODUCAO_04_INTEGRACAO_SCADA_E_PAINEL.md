# 🧠 SPEC 04 — INTEGRAÇÃO SCADA-LTS E VISÃO ATUAL DO PAINEL DE PRODUÇÃO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`
- **Contexto(s):** Módulo de Produção — Leitura em tempo real do Scada-LTS (MySQL) e exibição do estado atual no Dashboard de Produção.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras:** SPEC 02 (Auditoria), SPEC 03/03A (Cadastros locais de XID no Admin e Hardening do Router).

---

## ❗ 2. PROBLEMA ATUAL

- O painel `/producao/` renderiza um template stub sem integração com dados reais de telemetria do Scada-LTS.
- Não existem models não gerenciados (`managed=False`) para representar as tabelas `datapoints`, `pointvalues` e `pointvalueannotations` do Scada-LTS no app `production`.
- Faltam serviços de consulta otimizada em lote (single batch query com subquery `MAX(ts)`) para traduzir XIDs em IDs internos e ler os valores mais recentes sem sobrecarregar a rede ou a base de dados.
- O sistema não possui lógica para interpretar o estado operacional das máquinas (`Produzindo`, `Parada`, `Sem comunicação`, `Dado desatualizado`), nem suporte a parâmetros e alarmes globais no painel.

---

## 🎯 3. OBJETIVO

1. Criar os modelos Django não gerenciados (`managed=False`) para as tabelas `datapoints`, `pointvalues` e `pointvalueannotations` do Scada-LTS em `production/models.py`.
2. Implementar a camada de serviço `ScadaReaderService` para:
   - Resolução e cache de mapeamento `XID -> dataPointId` (TTL longo, ex: 15min).
   - Leitura otimizada em lote (single query por subquery `MAX(ts)`) dos últimos valores para lista de XIDs.
   - Cache em memória com TTL curto (ex: 2s) para leituras e quarentena para XIDs inexistentes (cooldown 10s).
   - Normalização robusta por `dataType` (1=Binary, 2=Multistate, 3=Numeric, 4=String).
   - Identificação de dado desatualizado (`stale_limit_seconds`).
   - Tratamento de timeout e falha de conexão retornando "Sem comunicação" de forma estruturada sem erro 500.
3. Criar a camada `ProductionStateService` para consolidar o estado operacional de cada máquina cadastrada, suas cavidades, produção vs meta, motivos de parada, parâmetros globais e alarmes globais.
4. Evoluir a interface do dashboard `/producao/` com:
   - Banner de totais (Produzindo, Paradas, Sem comunicação).
   - Campo de busca por nome da máquina.
   - Filtros rápidos no frontend (`Todas`, `Produzindo`, `Paradas`, `Sem Comunicação`).
   - Cards por máquina com status visual, tempo decorrido desde o timestamp da mudança, motivo de parada geral, status de abertura (se configurado), cavidades (produção/meta/motivo), parâmetros globais e alarmes globais.
   - Design responsivo (computador e celular), em Português (pt-br), limpo e industrial (sem aparência de TV).
5. Escrever suíte de testes automatizados com mocks/fakes cobrindo todas as regras e falhas de comunicação.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a alterar/criar:
- `production/models.py`: Criar models `managed=False` (`ScadaDataPoint`, `ScadaPointValue`, `ScadaPointValueAnnotation`).
- `production/services.py` [NOVO]: Implementar `ScadaReaderService` e `ProductionStateService`.
- `production/views.py`: Atualizar view `production_dashboard` para alimentar o contexto com o `ProductionStateService`.
- `production/templates/production/dashboard.html`: Evoluir o template com o layout industrial responsivo, filtros no frontend e busca.
- `production/tests.py`: Adicionar testes unitários automatizados para modelos não gerenciados, router, serviços de leitura em lote, normalização, stale, resiliência offline e dashboard.
- `Instrucoes.txt`: Registrar a execução da SPEC 04.
- `implementation_plan.md`: Atualizar progresso.
- `walkthrough.md`: Registrar resumo e evidências.

---

## 🚫 5. FORA DE ESCOPO

- NÃO executar `migrate --database=scada` nem modificar tabelas do Scada-LTS.
- NÃO escrever ou alterar nenhum dado no banco Scada (leitura puramente estrita em `scada`).
- NÃO criar models locais de histórico ou estado (`ProductionMachineState`, `ProductionDowntimeEvent` — pertencem à SPEC 05).
- NÃO implementar coletor persistente em background (pertence à SPEC 05).
- NÃO alterar a constante `LOCAL_MANAGED_MODELS` do `ScadaRouter` (os novos models são `managed=False`).
- NÃO alterar as migrations `0001` e `0002` existentes.
- NÃO alterar o banco `db.sqlite3` manualmente.
- NÃO conectar ao ambiente de produção.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ Não criar múltiplos ambientes virtuais ou duplicar apps Django.
- ✅ Manter isolamento completo do banco `scada` (somente leitura / sem migração).
- ✅ Acesso exclusivo para `Liderança de Produção` e Superusuários (bloqueio de usuários da Manutenção).
- ✅ Fallback amigável quando o Scada estiver offline (exibir "Sem comunicação" sem erro 500).

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Classificação de Status da Máquina:**
   - Se falha de comunicação ou Scada offline: `Sem comunicação` (JAMAIS interpretar falha de comunicação como máquina parada).
   - Se timestamp do valor de status for mais antigo que `stale_limit_seconds`: `Dado desatualizado` (ou marcado com alerta de desatualização).
   - Se o valor do XID de status for igual ao `produzindo_value` da máquina: `Produzindo`.
   - Se o valor for diferente: `Parada`.
2. **Normalização por `dataType`:**
   - `1` (Binary): Se `pointValue == 1.0` -> `True` / `"1"`, senão `False` / `"0"`.
   - `2` (Multistate): `int(pointValue)`.
   - `3` (Numeric): `float(pointValue)` ou `int(pointValue)` se inteiro exato.
   - `4` (String): Leitura da annotation (`textPointValueShort` ou `textPointValueLong`).
3. **Resolução em Lote de XIDs:**
   - Buscar todos os XIDs necessários em uma única consulta `datapoints`.
   - Manter cache `XID -> ID` por 15 minutos.
   - Manter cache de falha para XIDs inexistentes por 10 segundos.
4. **Consulta de Últimos Valores:**
   - Buscar em lote usando subquery com `MAX(ts)` indexada pela chave composta (`dataPointId`, `ts`).
   - Evitar consultas individuais por XID (prevenir N+1 SQL queries).

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] `makemigrations --check --dry-run` confirma 0 migrations geradas.
- [ ] Router envia leitura de models `managed=False` para `scada` e bloqueia escrita com `PermissionError`.
- [ ] Subquery em lote consulta múltiplos XIDs de forma otimizada.
- [ ] Normalização dos 4 tipos (`Binary`, `Multistate`, `Numeric`, `String`) funciona corretamente.
- [ ] Máquina é classificada como `Produzindo`, `Parada`, `Sem comunicação` ou `Dado desatualizado`.
- [ ] Scada offline exibe "Sem comunicação" sem gerar HTTP 500.
- [ ] Dashboard `/producao/` exibe busca, 4 filtros por status, cards responsivos, cavidades, metas, parâmetros e alarmes globais.
- [ ] Usuários da Manutenção são bloqueados ao tentar acessar `/producao/`.
- [ ] Todos os testes da suíte (maintenance + production) passam com sucesso.

---

## ⚠️ 9. RISCOS

- **Exposição de Credenciais:** Assegurar que nenhum log ou mensagem de erro exiba senhas do banco.
- **N+1 SQL Queries:** Garantir que a busca de valores seja agregada em uma única query em lote.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. **Subagente Arquiteto:** Revisar a estrutura e garantir separação clara entre Models, Services, Views e Templates.
2. **Subagente Backend:**
   - Implementar models `managed=False` em `production/models.py`.
   - Criar `production/services.py` com `ScadaReaderService` e `ProductionStateService`.
   - Atualizar `production/views.py` e template `production/templates/production/dashboard.html`.
   - Adicionar testes em `production/tests.py`.
3. **Subagente QA:** Executar bateria completa de verificações e comandos manage.py.
4. **Documentação e Commit:** Atualizar `Instrucoes.txt`, `implementation_plan.md`, `walkthrough.md` e realizar commit git.

---

## 🤖 REGISTRO DOS SUBAGENTES

### 1. Arquiteto
- Estrutura analisada e aprovada.
- Separação em `services.py` garante que as views continuem magras.
- Models `managed=False` garantem tipagem e ORM Django sem alterar schemas.

### 2. Backend
- Models `ScadaDataPoint`, `ScadaPointValue`, `ScadaPointValueAnnotation` criados com `managed=False`.
- `ScadaReaderService` implementado com cache em memória, batch subquery `MAX(ts)` e normalização de 4 tipos.
- `ProductionStateService` implementado com cálculo de status, stale check, parsing de cavidades, parâmetros e alarmes.
- View e template com CSS responsivo vanilla, busca e tabs no frontend atualizados.

### 3. QA
- Testes automatizados criados cobrindo roteamento, bloqueio de escrita, batch query, normalização, stale data, offline fallback, permissões e dashboard.
- Todos os testes executados com sucesso.
