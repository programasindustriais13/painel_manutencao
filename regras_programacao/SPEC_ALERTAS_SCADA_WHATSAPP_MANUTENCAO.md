# 🧠 SPEC — ALERTAS SCADA VIA WHATSAPP PARA MANUTENÇÃO

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/admin/production/productionglobalalarm/` (Configuração dos alarmes monitorados)
  - `/admin/production/whatsappalertrecipient/` (Cadastro de destinatários individuais)
  - `http://localhost:3000/send` (Microserviço Node.js / Baileys existente)
  - `/producao/configuracao-scada/api/testar-xid/` (Teste de XID com `XIDTestService`)
- **Contexto(s):** Monitoramento de Utilidades Industriais e Equipamentos (pressões de ar comprimido, vapor, vácuo, temperaturas, níveis), Coletor SCADA em Background, Mensageria WhatsApp.
- **Perfil(s) afetados:** Administrador / Superusuário (`is_superuser=True`), Equipe de Manutenção Industrial (Técnicos, Supervisores, Gestores).

---

## ❗ 2. PROBLEMA ATUAL

1. **Ausência de Alerta Proativo:**
   - Valores críticos de telemetria industrial (como queda de pressão de ar comprimido ou vapor nas prensas) só são percebidos quando uma máquina para ou quando o operador consulta o sinótico.
2. **Subutilização da Infraestrutura Existente:**
   - O projeto já possui leitura em lote de XIDs pelo coletor `collect_production_scada`, microserviço WhatsApp (Node.js/Baileys) com fila sequencial e escudo anti-banimento, e cadastro de `WhatsAppGroup` no Django Admin. No entanto, não há integração entre o monitoramento SCADA e o disparo de alertas para a manutenção.
3. **Risco de Falso Alarme e Banimento do WhatsApp:**
   - Flutuações pontuais de pressão (quedas momentâneas de 2 segundos) poderiam disparar tempestades de mensagens se não houver filtro de permanência (delay / anti-oscilação).
   - Leituras indisponíveis (`None`, falha de rede do SCADA) não podem ser interpretadas como valor zero.
   - Envios imediatos e desordenados para múltiplos destinos poderiam estourar o rate limit ou causar banimento do número WhatsApp.

---

## 🎯 3. OBJETIVO

1. **Evolução do Modelo `ProductionGlobalAlarm`:**
   - Evoluir o modelo existente `ProductionGlobalAlarm` (mantendo integridade e compatibilidade com o painel sinótico existente) para suportar parametrização de limites (mínimo e/ou máximo), unidade, delay de anti-oscilação, intervalo de repetição, destinatários individuais e grupos.
2. **Cadastro Administrativo de Destinatários Individuais:**
   - Criar modelo `WhatsAppAlertRecipient` no app `production` para cadastro simples e flexível de contatos com nome, telefone e status ativo, normalizando o número para o padrão nacional e internacional.
3. **Máquina de Estados Resiliente e Persistente:**
   - Implementar máquina de estados no banco `default`: `NORMAL` → `PENDENTE` → `ALARME_ATIVO` → `NORMAL`, com suporte a `DESABILITADO` durante manutenção programada.
   - Anti-oscilação: disparo somente se o valor permanecer continuamente fora da faixa durante o tempo de delay configurado.
   - Normalização: disparo de uma única mensagem de recuperação ao retornar à faixa normal.
4. **Proteção Anti-Spam e Consolidação:**
   - Agrupar múltiplos alarmes gerados no mesmo ciclo para o mesmo destinatário em uma mensagem consolidada.
   - Respeitar estritamente o microserviço Node.js (retorno `202`, tratamento de `429` com backoff e `503` com circuit breaker, sem crashar o coletor).
5. **Integração sem Sobrecarga no Coletor SCADA:**
   - Integrar a avaliação no ciclo de `collect_production_scada` aproveitando os valores já lidos em memória, desacoplado em um service dedicado `MaintenanceAlertService`.
6. **Zero Escrita no SCADA e Compatibilidade SQLite/MySQL:**
   - Nenhuma escrita no banco `scada`. Migrations aditivas no banco `default`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a Modificar:
- `production/models.py`:
  - Criar `WhatsAppAlertRecipient` (nome, telefone, ativo).
  - Evoluir `ProductionGlobalAlarm`:
    - `descricao` (TextField, opcional)
    - `unidade` (CharField, opcional: bar, °C, etc.)
    - `valor_minimo` (FloatField, opcional)
    - `valor_maximo` (FloatField, opcional)
    - `delay_segundos` (PositiveIntegerField, default=60)
    - `intervalo_repeticao_minutos` (PositiveIntegerField, default=10, choices: 1, 5, 10, 30 min)
    - `habilitado` (BooleanField, default=True)
    - `notificar_normalizacao` (BooleanField, default=True)
    - `destinatarios_individuais` (ManyToManyField(WhatsAppAlertRecipient, blank=True))
    - `grupos` (ManyToManyField('maintenance.WhatsAppGroup', blank=True))
    - Campos de persistência de estado:
      - `estado_atual` (CharField: NORMAL, PENDENTE, ALARME_ATIVO, DESABILITADO)
      - `fora_da_faixa_desde` (DateTimeField, null=True, blank=True)
      - `ultima_leitura_valor` (FloatField, null=True, blank=True)
      - `ultima_leitura_data` (DateTimeField, null=True, blank=True)
      - `ultima_notificacao_data` (DateTimeField, null=True, blank=True)
      - `alerta_inicial_enviado` (BooleanField, default=False)
      - `ultima_normalizacao_data` (DateTimeField, null=True, blank=True)
- `production/routers.py`:
  - Registrar `WhatsAppAlertRecipient` na lista de models locais gerenciados no banco `default`.
- `production/services/maintenance_alerts.py` [NOVO]:
  - `MaintenanceAlertService`:
    - `evaluate_alerts(scada_values: dict, now=None)`
    - Validação de faixa, máquina de estados, delay e intervalo de repetição.
    - Formatação de mensagens individuais e consolidadas.
    - Dispatcher defensivo com tratamento de `202`, `429`, `503` e erros de conexão.
- `production/services/__init__.py`:
  - Exportar `MaintenanceAlertService`.
- `production/management/commands/collect_production_scada.py`:
  - Chamar `MaintenanceAlertService.evaluate_alerts(scada_vals)` a cada ciclo.
- `production/admin.py`:
  - Registrar `WhatsAppAlertRecipientAdmin`.
  - Atualizar `ProductionGlobalAlarmAdmin` com fieldsets amigáveis, contagem de destinos, filtros, busca e link/ação para teste de XID.
- `production/test_maintenance_alerts.py` [NOVO]:
  - Suíte completa de testes automatizados com mocks de rede cobrindo todos os 31 casos.

---

## 🚫 5. FORA DE ESCOPO

- NÃO criar outro microserviço WhatsApp ou duplicar `server.js`.
- NÃO abrir outra porta Node.js nem criar outra sessão Baileys.
- NÃO criar outra tabela de grupos de WhatsApp (reutilizar `maintenance.WhatsAppGroup`).
- NÃO escrever no banco `scada` (zero escrita).
- NÃO alterar a rotação de leitura das máquinas ou inventário do Scada-LTS.
- NÃO depender de requisições web ou abertura de páginas para disparar alertas.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Apenas 1 ambiente virtual e 1 base de código ativa.
- Estado persistente salvo no banco `default`.
- Compatibilidade plena SQLite e MySQL.
- Resiliência: falha do microserviço Node.js nunca derruba o coletor de produção.
- Zero envio de mensagens reais durante a execução dos testes automatizados.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Configuração de Limites:**
   - Permitidos: apenas mínimo, apenas máximo, ou ambos.
   - Pelo menos um limite é obrigatório.
   - Se ambos informados: validação obrigatória `valor_minimo < valor_maximo`.
2. **Leituras Inválidas e SCADA Offline:**
   - Leituras `None`, não numéricas, erro de conexão ou stale NÃO são tratadas como `0.0`.
   - São tratadas como telemetria indisponível, registradas em log de diagnóstico, sem alterar estado de alarme nem disparar mensagens.
3. **Máquina de Estados e Transições:**
   - `NORMAL → PENDENTE`: valor sai da faixa permitida. Registra `fora_da_faixa_desde = agora`.
   - `PENDENTE → NORMAL`: valor normaliza antes de atingir `delay_segundos`. Cancela condição pendente.
   - `PENDENTE → ALARME_ATIVO`: tempo fora da faixa `>= delay_segundos`. Emite primeiro alerta e registra `alerta_inicial_enviado = True`, `ultima_notificacao_data = agora`.
   - `ALARME_ATIVO → ALARME_ATIVO`: valor continua fora da faixa. Nova mensagem emitida apenas se `agora >= ultima_notificacao_data + intervalo_repeticao`.
   - `ALARME_ATIVO → NORMAL`: valor retorna à faixa. Emite mensagem de normalização uma única vez (se `notificar_normalizacao=True`) e reseta para `NORMAL`.
4. **Desabilitação / Modo Manutenção:**
   - Quando `habilitado=False`: estado vai para `DESABILITADO`, nenhum alerta ou repetição é enviado, e qualquer delay acumulado é zerado.
   - Ao reabilitar: avalia como nova observação a partir do próximo ciclo.
5. **Normalização de Destinatários e Agrupamento Anti-Spam:**
   - Telefones individuais recebem higienização de dígitos (DDI 55, DDD, 8 ou 9 dígitos).
   - Grupos utilizam o JID `@g.us` cadastrado no `WhatsAppGroup`.
   - Apenas destinatários ativos (`is_active=True`) são considerados.
   - Se múltiplos alarmes ficarem elegíveis no mesmo ciclo para o mesmo destinatário/grupo, o serviço unifica os itens em uma única mensagem consolidada.
6. **Tratamento de Respostas do Microserviço:**
   - `HTTP 202`: sucesso de enfileiramento aceito pelo Node.js.
   - `HTTP 429`: rate limit ativo no Node. Registrar advertência, não retentar em loop imediato, aguardar próximo ciclo.
   - `HTTP 503`: circuit breaker aberto no Node. Respeitar indisponibilidade temporária.
   - Conexão recusada / Timeout: logar warning, manter estado interno íntegro e prosseguir.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] 31 testes automatizados cobrindo todos os fluxos especificados.
- [ ] Validações de limites bloqueiam configurações incorretas no Admin e nos models.
- [ ] Delay anti-oscilação previne disparos imediatos em flutuações rápidas.
- [ ] Repetição obedece ao intervalo configurado sem duplicidade.
- [ ] Normalização dispara exatamente uma mensagem.
- [ ] Alarme desabilitado não emite mensagens nem acumula delay.
- [ ] Leituras None ou falhas de SCADA não geram falso alarme.
- [ ] Mensagens simultâneas para o mesmo destino são consolidadas em uma única mensagem.
- [ ] Zero escrita no banco SCADA.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco de Bloqueio no WhatsApp:**
  - *Mitigação:* Consolidação por destino, fila sequencial do Node.js, atraso humanizado (2-5s) e rate limit.
- **Risco de Reinício do Coletor perder o delay:**
  - *Mitigação:* `fora_da_faixa_desde` e `ultima_notificacao_data` são persistidos no banco `default`.
- **Risco de Queda do Node.js travar o coletor:**
  - *Mitigação:* Chamadas HTTP protegidas com timeout curto (5s) e tratamento completo de exceções sem propagação de erro.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Criar `WhatsAppAlertRecipient` e atualizar `ProductionGlobalAlarm` em `production/models.py`.
2. Registrar `WhatsAppAlertRecipient` no `production/routers.py`.
3. Criar e aplicar migration aditiva no banco `default`.
4. Implementar `production/services/maintenance_alerts.py`.
5. Atualizar `collect_production_scada.py` para invocar a avaliação a cada ciclo.
6. Registrar e estilizar no `production/admin.py`.
7. Implementar os 31 testes unitários em `production/test_maintenance_alerts.py`.
