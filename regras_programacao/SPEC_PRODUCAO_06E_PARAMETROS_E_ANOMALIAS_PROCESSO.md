# 🧠 SPEC 06E — MONITORAMENTO DE PARÂMETROS E ANOMALIAS DE PROCESSO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/`, `/producao/maquinas/<id>/`, `/admin/production/productionparameterconfig/`, `/admin/production/productionparameteranomalyevent/`
- **Contexto(s):** Módulo de Produção — Parametrização de faixas permitidas (temperatura, pressão, vácuo, vapor, etc.), tolerância a desvios, histerese de normalização e rastreamento de anomalias de processo.
- **Perfil(s) afetados:** Liderança de Produção (`Liderança de Produção`), Administradores / Superusuários. Usuários da Manutenção são bloqueados.
- **Predecessoras Obrigatórias:** `SPEC_PRODUCAO_06D_ESTIMATIVA_PERDA_PRODUCAO.md`.

---

## ❗ 2. PROBLEMA ATUAL

- Atualmente, os parâmetros globais (`ProductionGlobalParameter`) apenas exibem os valores lidos em tempo real, sem verificação de faixas mínimas e máximas de segurança operacional.
- Não há cadastros de tolerância (tempo em segundos que o parâmetro pode ficar fora da faixa antes de disparar um evento) nem de histerese (margem de retorno para evitar oscilações repetitivas no limite).
- Não há registros históricos de eventos de anomalia de processo (`ProductionParameterAnomalyEvent`) para saber por quanto tempo um processo operou fora dos limites especificados.
- Faltam vínculos entre anomalias de parâmetro e o snapshot de produto, matriz, lote e o evento de parada correspondente (`ProductionDowntimeEvent`).

---

## 🎯 3. OBJETIVO

1. **Evolução de Parametrização:** Criar `ProductionParameterConfig` no banco `default` em `production/models.py` (ou evoluir `ProductionGlobalParameter`) suportando:
   - `nome`, `chave`, `xid`, `unidade`, `ordem`;
   - `machine_config` (FK opcional para parâmetros específicos de prensa);
   - `cavity_config` (FK opcional para parâmetros específicos de cavidade);
   - `limite_minimo` (FloatField opcional);
   - `limite_maximo` (FloatField opcional);
   - `tolerancia_segundos` (PositiveIntegerField, default=0 — tempo fora da faixa exigido antes de abrir anomalia);
   - `histerese` (FloatField, default=0.0 — margem para fechar anomalia);
   - `ativo` (BooleanField, default=True);
   - `stale_limit_seconds` (PositiveIntegerField, default=120).
2. **Model `ProductionParameterAnomalyEvent`:** Criar no banco `default` para registrar ocorrências fora da faixa:
   - `parameter_config` (FK);
   - `machine_config` (FK);
   - `cavity_config` (FK opcional);
   - `inicio`, `fim`, `duracao_segundos`;
   - `menor_valor`, `maior_valor`, `ultimo_valor`;
   - `produto_snapshot`, `matriz_snapshot`, `lote_snapshot`;
   - `downtime_event` (FK opcional para `ProductionDowntimeEvent`).
3. **Inclusão no Router:** Adicionar `"productionparameterconfig"` e `"productionparameteranomalyevent"` em `ScadaRouter.LOCAL_MANAGED_MODELS`.
4. **Lógica de Anomalia no Coletor:**
   - Abrir anomalia SOMENTE após exceder a `tolerancia_segundos` configurada fora da faixa;
   - Não abrir novos eventos a cada ciclo (manter evento aberto e atualizar `menor_valor`, `maior_valor` e `ultimo_valor`);
   - Fechar evento SOMENTE quando o valor retornar para dentro da faixa com margem de `histerese`;
   - Não abrir nem fechar eventos durante estado stale ou sem comunicação;
   - Correlacionar a anomalia com produto, matriz, lote e evento de parada ativo se existirem.
5. **Disclaimer Obrigatório na Interface:** Informar na interface web: *"Precisão temporal das anomalias vinculada ao intervalo de leitura do coletor (60s)"*. O intervalo do coletor em produção (60s) NÃO deve ser alterado sem teste de carga prévio.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos Permitidos:
- `production/models.py`: Criar `ProductionParameterConfig` e `ProductionParameterAnomalyEvent`.
- `production/routers.py`: Adicionar os modelos em `LOCAL_MANAGED_MODELS`.
- `production/admin.py`: Registrar no Admin com inline e list_display.
- `production/migrations/0011_parametros_e_anomalias_processo.py` [NOVA]: Migration aditiva no banco `default`.
- `production/services.py`: Lógica de validação de faixas, tolerância, histerese e gravação idempotente de anomalias no coletor.
- `production/templates/production/dashboard.html`: Exibir alertas de anomalia de parâmetros nos cards.
- `production/templates/production/machine_detail.html`: Exibir anomalias relacionadas no histórico da máquina/cavidade.
- `production/tests.py`: Adicionar suíte `Spec06EParameterAnomaliesTestCase`.
- `Instrucoes.txt`: Registrar execução da SPEC 06E.

### Arquivos Proibidos:
- Reduzir o intervalo do coletor em produção (mantido em 60s).
- Escrever no Scada MySQL.

---

## 🔐 5. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ⚠️ Cumprir integralmente o `constitution.md`.
- ❌ Não gerar um novo registro de evento a cada coleta contínua.
- ✅ Histerese obrigatória para evitar oscilações repetitivas (flickering).
- ✅ Escrita puramente no banco `default`.

---

## ⚙️ 6. REGRAS DE NEGÓCIO E MÁQUINA DE ANOMALIAS

1. **Condição de Abertura:**
   - O parâmetro está fora da faixa se `valor < limite_minimo` OU `valor > limite_maximo`.
   - Se o valor permanecer fora da faixa por `tempo_fora >= tolerancia_segundos`: abre 1 evento em `ProductionParameterAnomalyEvent` com `fim=None`.
   - Registrar snapshot de `produto`, `matriz`, `lote` e vincular a `downtime_event` se houver parada ativa na máquina.

2. **Manutenção do Evento Aberto:**
   - Enquanto a anomalia continuar aberta:
     - `ultimo_valor = valor_atual`;
     - `menor_valor = min(menor_valor, valor_atual)`;
     - `maior_valor = max(maior_valor, valor_atual)`.

3. **Condição de Fechamento com Histerese:**
   - Se a anomalia foi por limite MÍNIMO (valor caiu abaixo do mínimo): fecha SOMENTE quando `valor >= limite_minimo + histerese`.
   - Se a anomalia foi por limite MÁXIMO (valor subiu acima do máximo): fecha SOMENTE quando `valor <= limite_maximo - histerese`.
   - Ao fechar: preenche `fim = now` e calcula `duracao_segundos`.

4. **Tratamento Stale / Sem Comunicação:**
   - Se o dado estiver desatualizado ou o Scada desconectado: o estado da anomalia fica CONGELADO (não abre nem fecha anomalias).

---

## 🧪 7. CRITÉRIOS DE ACEITAÇÃO

- [ ] Models de parâmetros e anomalias criados e roteados no `default`.
- [ ] Migration `0011` gerada e aplicada com sucesso.
- [ ] Tolerância de tempo respeitada antes de abrir evento de anomalia.
- [ ] Histerese impede abertura/fechamento repetitivo em valores oscilantes no limite.
- [ ] Atualização de menor_valor e maior_valor funcionando em eventos abertos.
- [ ] Snapshot de produto/matriz/lote gravado na abertura.
- [ ] Notice de precisão temporal exibido na interface.
- [ ] Suíte de testes automatizados 100% verde.

---

## ⚠️ 8. RISCOS

- **Oscilação no limite (Flickering):** Mitigado pelo parâmetro de histerese.

---

## 🔍 9. PLANO DE IMPLEMENTAÇÃO

1. Criar os modelos em `production/models.py` e registrar em `routers.py`.
2. Registrar em `admin.py`.
3. Gerar e aplicar migration `0011` no `default`.
4. Implementar a máquina de anomalias com tolerancia/histerese em `services.py`.
5. Atualizar templates (`dashboard.html`, `machine_detail.html`).
6. Escrever suíte de testes unitários em `tests.py`.

---

## 🧪 10. TESTES AUTOMATIZADOS E MANUAIS

- **Automatizados:** Testar tolerância de tempo, histerese de fechamento, atualização de menor/maior valor e congelamento em dado stale.
- **Manuais:** Alterar parâmetro de temperatura para valor acima do máximo no mock/admin, aguardar tempo de tolerância e verificar abertura da anomalia no detalhe da máquina.

---

## 🛡️ 11. ROLLBACK E GATE DE SAÍDA

- **Rollback:** `python manage.py migrate production 0010` reverte a migração `0011`.
- **Gate de Saída:** Suíte global de testes 100% verde.
- **Regra de Parada:** Interromper se houver alteração do intervalo do coletor sem autorização.
